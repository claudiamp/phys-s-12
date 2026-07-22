"""Step 2 — raster line art into pen paths (polylines).

No AI here. This is classic, deterministic computer vision.

The key step is SKELETONIZATION. If you traced by contour (what potrace does),
every black line would become a closed polygon and the plotter would draw it
twice, once down each edge: the stroke comes out fat and takes twice as long.
Thinning to 1 pixel first means each line produces ONE pass, which is what you
want with a pen.
"""

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

# Neighbours clockwise from north: P2..P9 in the Zhang-Suen paper.
_NB8 = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


# --------------------------------------------------------------------------
# Loading and thresholding
# --------------------------------------------------------------------------

def load_gray(image_bytes, max_side=800):
    """Load as grayscale and cap the size.

    max_side drives both compute time and detail. Note thumbnail() only shrinks,
    so asking for more than the source resolution does nothing.
    """
    im = Image.open(io.BytesIO(image_bytes)).convert("L")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    return im


def otsu_threshold(gray_u8):
    """Otsu's method: split the histogram where it best separates two groups.

    Saves us from hardcoding a threshold that only works for one lighting.
    """
    hist = np.bincount(gray_u8.ravel(), minlength=256).astype(np.float64)
    total = gray_u8.size
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]

    denom = omega * (1.0 - omega)
    denom[denom <= 0] = 1e-12
    between = (mu_t * omega - mu) ** 2 / denom
    return int(np.argmax(between))


def _dog_balanced(g1, g2):
    """Difference of Gaussians with the blurs mean-matched.

    A fixed tau makes the result depend on the photo's overall brightness, so it
    works on one photo and not the next. Scaling g2 to g1's mean removes that.
    """
    m1, m2 = float(g1.mean()), float(g2.mean())
    scale = (m1 / m2) if m2 > 1e-6 else 1.0
    return g2 * scale


def edges_mask(im, sigma=1.0, k=1.6, ink_fraction=0.09):
    """Edge detection returning a boolean ink mask. Used for the no-AI path.

    Do NOT use Otsu here. Otsu assumes a histogram with two separate peaks,
    which a drawing has, but an edge map does not: it is mostly flat with the
    edges in the tail. Otsu would split down the middle and call half the
    background ink. A percentile is both correct and useful, since it gives
    direct control: ink_fraction=0.09 means "keep the strongest 9% of edges".
    """
    g1 = np.asarray(im.filter(ImageFilter.GaussianBlur(sigma)), dtype=np.float32)
    g2 = np.asarray(im.filter(ImageFilter.GaussianBlur(sigma * k)), dtype=np.float32)
    dog = g1 - _dog_balanced(g1, g2)

    # Keep only the dark side of each edge, on purpose: that gives one thin
    # line per contour instead of two parallel lines around it.
    cutoff = np.percentile(dog, ink_fraction * 100.0)
    return dog <= cutoff


def binarize(im, invert=False, blur=0.6):
    """Return a boolean array where True means ink."""
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if invert:
        im = ImageOps.invert(im)

    arr = np.asarray(im, dtype=np.uint8)
    return arr <= otsu_threshold(arr)


# --------------------------------------------------------------------------
# Skeletonization (Zhang-Suen)
# --------------------------------------------------------------------------

def _neighbours(p):
    """The 8 neighbours as aligned planes, so we can work vectorized."""
    return (
        p[0:-2, 1:-1],  # P2 N
        p[0:-2, 2:],    # P3 NE
        p[1:-1, 2:],    # P4 E
        p[2:, 2:],      # P5 SE
        p[2:, 1:-1],    # P6 S
        p[2:, 0:-2],    # P7 SW
        p[1:-1, 0:-2],  # P8 W
        p[0:-2, 0:-2],  # P9 NW
    )


def fill_small_holes(mask, max_area=80):
    """Fill tiny white holes enclosed by ink.

    WHY: where two strokes touch at their tips they trap a sliver of white.
    Skeletonization preserves topology, so it preserves that hole too: the
    skeleton goes AROUND it and produces a closed loop. On paper that reads as a
    bubble -- the pen draws the outline of the sliver instead of one line
    through it.

    CAREFUL: a PUPIL is also a small enclosed white hole. On clean line art this
    step eats the eyes. See the note in image_to_paths -- it is off by default.
    """
    h, w = mask.shape

    # PIL does the flood fill in C. Doing it pixel by pixel in Python over ~1M
    # pixels would be far too slow.
    img = Image.fromarray((~mask).astype(np.uint8) * 255)  # background=255, ink=0

    # Several seeds in case a corner lands on ink.
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if img.getpixel(seed) == 255:
            ImageDraw.floodfill(img, seed, 128)

    arr = np.asarray(img)
    holes = arr == 255  # background not reachable from the border => enclosed
    if not holes.any():
        return mask

    # Label ONLY the hole pixels (there are few) to measure each one. Scanning
    # the whole image here would be wasted work.
    filled = mask.copy()
    pending = set(zip(*np.nonzero(holes)))

    while pending:
        seed = pending.pop()
        comp = [seed]
        stack = [seed]
        while stack:
            y, x = stack.pop()
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                q = (y + dy, x + dx)
                if q in pending:
                    pending.discard(q)
                    comp.append(q)
                    stack.append(q)
        if len(comp) <= max_area:
            ys, xs = zip(*comp)
            filled[np.array(ys), np.array(xs)] = True

    return filled


def skeletonize(mask, max_iter=100):
    """Thin the mask to 1-pixel lines, preserving topology.

    Zhang-Suen, vectorized with numpy. Each pass deletes border pixels that meet
    four conditions guaranteeing the line is neither broken nor shortened at its
    ends. Converges in ~15-40 passes depending on stroke thickness.
    """
    img = mask.astype(np.uint8)

    for _ in range(max_iter):
        changed = False

        for step in (0, 1):
            padded = np.pad(img, 1, mode="constant")
            P2, P3, P4, P5, P6, P7, P8, P9 = _neighbours(padded)

            # B = how many neighbours are ink.
            B = P2 + P3 + P4 + P5 + P6 + P7 + P8 + P9

            # A = how many 0->1 transitions there are walking the neighbours in
            # a circle. A == 1 means this pixel is not a bridge: deleting it
            # will not split the line in two.
            seq = [P2, P3, P4, P5, P6, P7, P8, P9, P2]
            A = np.zeros(img.shape, dtype=np.uint8)
            for i in range(8):
                A += ((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8)

            if step == 0:
                c1 = (P2 * P4 * P6) == 0
                c2 = (P4 * P6 * P8) == 0
            else:
                c1 = (P2 * P4 * P8) == 0
                c2 = (P2 * P6 * P8) == 0

            # B>=2 avoids deleting endpoints (that would shorten the line).
            # B<=6 avoids deleting pixels inside a blob.
            doomed = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & c1 & c2

            if doomed.any():
                img[doomed] = 0
                changed = True

        if not changed:
            break

    return img.astype(bool)


# --------------------------------------------------------------------------
# Path tracing
# --------------------------------------------------------------------------

def trace_paths(skel, min_points=5):
    """Walk the skeleton and return polylines as lists of (y, x).

    We treat the skeleton as a graph. Pixels with exactly 2 neighbours are
    pass-through; those with 1 (endpoints) or 3+ (junctions) are nodes. We walk
    node to node consuming edges, then sweep whatever is left, which are closed
    loops with no node at all (a circle, for instance).
    """
    ink = set(zip(*np.nonzero(skel)))
    if not ink:
        return []

    def nbrs(p):
        """Neighbours of p, ignoring redundant diagonals.

        On a rasterized diagonal (a staircase) the corner pixel touches its
        diagonal neighbour AND the two orthogonal ones in between. That gives it
        degree 3 and turns it into a fake junction; since the steps are
        consecutive, you get fake junctions next to each other and the stroke
        shatters into 2-pixel fragments.

        If the orthogonal path already exists, the diagonal edge adds no
        connectivity, so we prune it. Degrees go back to 2 and the staircase is
        walked as what it is: a single line.
        """
        y, x = p
        out = []
        for dy, dx in _NB8:
            q = (y + dy, x + dx)
            if q not in ink:
                continue
            if dy and dx and ((y + dy, x) in ink or (y, x + dx) in ink):
                continue  # redundant diagonal
            out.append(q)
        return out

    degree = {p: len(nbrs(p)) for p in ink}
    used = set()  # edges already walked, as frozenset({a, b})
    paths = []

    def walk(start):
        """Walk from start until we hit a node or run out of edges."""
        path = [start]
        cur = start
        while True:
            options = [q for q in nbrs(cur) if frozenset((cur, q)) not in used]
            if not options:
                break
            nxt = options[0]
            used.add(frozenset((cur, nxt)))
            path.append(nxt)
            cur = nxt
            if degree[cur] != 2:
                break  # reached a junction or an endpoint
        return path

    # Start from endpoints and junctions: gives the most natural strokes.
    for seed in [p for p in ink if degree[p] != 2]:
        while True:
            path = walk(seed)
            if len(path) < 2:
                break
            paths.append(path)

    # Whatever is left are closed loops.
    for p in ink:
        while any(frozenset((p, q)) not in used for q in nbrs(p)):
            path = walk(p)
            if len(path) < 2:
                break
            paths.append(path)

    return [p for p in paths if len(p) >= min_points]


# --------------------------------------------------------------------------
# Stitching, simplifying, ordering
# --------------------------------------------------------------------------

def stitch_paths(paths, tol=1.5):
    """Rejoin fragments that are really one continuous stroke.

    Even after pruning redundant diagonals, tracing splits strokes at junctions.
    Every extra fragment is one pen-up and one pen-down (~0.5s of servo plus the
    travel), so stitching fragments whose endpoints touch is one of the biggest
    real time savers. It also avoids the ink blobs a pen leaves when it sets
    back down in the middle of a line.
    """
    if not paths:
        return []

    arrs = [np.asarray(p, dtype=np.float64) for p in paths]
    starts = np.array([a[0] for a in arrs])
    ends = np.array([a[-1] for a in arrs])
    used = np.zeros(len(arrs), dtype=bool)
    tol2 = tol * tol
    out = []

    def nearest_free(point):
        cand = np.flatnonzero(~used)
        if cand.size == 0:
            return None
        d_start = ((starts[cand] - point) ** 2).sum(axis=1)
        d_end = ((ends[cand] - point) ** 2).sum(axis=1)
        best = int(np.argmin(np.minimum(d_start, d_end)))
        if min(d_start[best], d_end[best]) > tol2:
            return None
        return int(cand[best]), bool(d_start[best] <= d_end[best])

    for i in range(len(arrs)):
        if used[i]:
            continue
        used[i] = True
        chain = arrs[i]

        # Grow from the tail.
        while True:
            hit = nearest_free(chain[-1])
            if hit is None:
                break
            j, by_start = hit
            nxt = arrs[j] if by_start else arrs[j][::-1]
            chain = np.vstack([chain, nxt[1:]])  # [1:] avoids duplicating the joint
            used[j] = True

        # Grow from the head.
        while True:
            hit = nearest_free(chain[0])
            if hit is None:
                break
            j, by_start = hit
            prev = arrs[j][::-1] if by_start else arrs[j]
            chain = np.vstack([prev[:-1], chain])
            used[j] = True

        out.append(chain)

    return out


def rdp(points, epsilon):
    """Ramer-Douglas-Peucker, iterative (no recursion, so long paths cannot
    blow the stack).

    Drops points that deviate less than epsilon from the straight line. A
    2000-pixel stroke usually ends up at 40-80 points with no visible
    difference, and that is the difference between a 5MB G-code file and a
    200KB one.
    """
    pts = np.asarray(points, dtype=np.float64)
    n = len(pts)
    if n < 3:
        return pts

    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]

    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue

        a, b = pts[i], pts[j]
        seg = b - a
        length = float(np.hypot(seg[0], seg[1]))
        sub = pts[i + 1:j]

        if length < 1e-9:
            dist = np.hypot(sub[:, 0] - a[0], sub[:, 1] - a[1])
        else:
            # Point-to-line distance via the 2D cross product.
            dist = np.abs(seg[0] * (a[1] - sub[:, 1]) - (a[0] - sub[:, 0]) * seg[1]) / length

        k = int(np.argmax(dist))
        if dist[k] > epsilon:
            m = i + 1 + k
            keep[m] = True
            stack.append((i, m))
            stack.append((m, j))

    return pts[keep]


def order_paths(paths, start=(0.0, 0.0)):
    """Reorder strokes nearest-neighbour, reversing them when that helps.

    Without this the pen jumps around the sheet between strokes and a 3-minute
    drawing becomes 15. It is a greedy heuristic, not optimal TSP, but it cuts
    travel by roughly 80% and runs in milliseconds.
    """
    if not paths:
        return []

    starts = np.array([p[0] for p in paths], dtype=np.float64)
    ends = np.array([p[-1] for p in paths], dtype=np.float64)
    pending = np.ones(len(paths), dtype=bool)

    cur = np.asarray(start, dtype=np.float64)
    ordered = []

    for _ in range(len(paths)):
        idx = np.flatnonzero(pending)
        d_start = np.hypot(starts[idx, 0] - cur[0], starts[idx, 1] - cur[1])
        d_end = np.hypot(ends[idx, 0] - cur[0], ends[idx, 1] - cur[1])

        best_local = int(np.argmin(np.minimum(d_start, d_end)))
        best = int(idx[best_local])

        path = paths[best]
        # If the far end is closer, draw the stroke backwards: identical on
        # paper, and it saves the travel.
        if d_end[best_local] < d_start[best_local]:
            path = path[::-1]

        ordered.append(path)
        cur = np.asarray(path[-1], dtype=np.float64)
        pending[best] = False

    return ordered


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def image_to_paths(image_bytes, max_side=1024, simplify=1.8, min_points=12,
                   from_photo=False, ink_fraction=0.09, hole_area=0):
    """Full raster -> polylines in pixel coordinates. Returns (paths, shape).

    from_photo=True runs edge detection first, for the no-AI path. With real
    line art leave it False: the image is already lines, and detecting edges on
    lines would double every one of them.
    """
    im = load_gray(image_bytes, max_side=max_side)

    if from_photo:
        mask = edges_mask(im, ink_fraction=ink_fraction)
    else:
        mask = binarize(im)
        # Safety net: if the line art came with a dark background the threshold
        # is inverted and we would try to draw the whole sheet.
        if mask.mean() > 0.5:
            mask = ~mask

    if not mask.any():
        return [], mask.shape

    # OFF BY DEFAULT (hole_area=0), and it is worth knowing why.
    #
    # Filling tiny white holes helped when images came with strokes touching
    # each other: two lines that meet trap a sliver of white, the skeleton goes
    # around it, and the pen draws a bubble instead of a line.
    #
    # But a PUPIL is also a small enclosed white hole, so on clean line art this
    # step eats the eyes -- the pupil collapses into a blob. Measured on the
    # same image, the stroke count is identical with and without it, so here it
    # is all cost and no benefit. Turn it up by hand only if bubbles come back.
    if hole_area:
        mask = fill_small_holes(mask, max_area=hole_area)

    skel = skeletonize(mask)

    # Trace WITHOUT filtering by length: the short fragments at junctions are
    # exactly the connectors stitching needs. Filter noise after stitching.
    paths = trace_paths(skel, min_points=2)
    paths = stitch_paths(paths)
    paths = [p for p in paths if len(p) >= min_points]
    paths = [rdp(p, simplify) for p in paths]
    paths = [p for p in paths if len(p) >= 2]
    paths = order_paths(paths)

    return paths, skel.shape
