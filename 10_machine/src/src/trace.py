#!/usr/bin/env python3
"""Steps 2+3 — line art into G-code, plus a preview of what the pen will draw.

    python src/trace.py output/caricature.png
    python src/trace.py output/caricature.png --bed 150x150

Writes <name>.gcode and <name>_preview.png into output/.
ALWAYS look at the preview before sending anything to the plotter.
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gcode as gc          # noqa: E402
import vectorize as vec     # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="line art -> G-code")
    ap.add_argument("image")
    ap.add_argument("--bed", default="100x100", help="drawing area in mm, e.g. 150x150")
    ap.add_argument("--margin", type=float, default=5.0)
    ap.add_argument("--simplify", type=float, default=1.8,
                    help="higher = fewer points per stroke")
    ap.add_argument("--min-points", type=int, default=12,
                    help="drop strokes shorter than this (noise)")
    ap.add_argument("--max-side", type=int, default=1024, help="working resolution")
    ap.add_argument("--outdir", default="output")
    args = ap.parse_args()

    bed_w, bed_h = (float(v) for v in args.bed.lower().split("x"))
    os.makedirs(args.outdir, exist_ok=True)
    name = os.path.basename(args.image).rsplit(".", 1)[0]

    with open(args.image, "rb") as f:
        data = f.read()

    paths, shape = vec.image_to_paths(
        data,
        max_side=args.max_side,
        simplify=args.simplify,
        min_points=args.min_points,
    )
    if not paths:
        print("no drawable lines found")
        return 1

    paths_mm = gc.fit_to_bed(paths, shape, bed_w=bed_w, bed_h=bed_h, margin=args.margin)
    text, stats = gc.generate(paths_mm, bed_w=bed_w, bed_h=bed_h)

    gcode_path = os.path.join(args.outdir, f"{name}.gcode")
    with open(gcode_path, "w") as f:
        f.write(text)

    # Preview: exactly the route the pen takes.
    scale = 8
    img = Image.new("RGB", (int(bed_w * scale), int(bed_h * scale)), "white")
    draw = ImageDraw.Draw(img)
    for p in paths_mm:
        draw.line([(float(x) * scale, (bed_h - float(y)) * scale) for x, y in p],
                  fill="black", width=2)
    preview_path = os.path.join(args.outdir, f"{name}_preview.png")
    img.save(preview_path)

    mins, secs = divmod(stats["estimated_seconds"], 60)
    print(f"{stats['paths']} strokes, {stats['points']} points")
    print(f"drawing {stats['draw_mm']:.0f}mm + travel {stats['travel_mm']:.0f}mm")
    print(f"estimated plot time: ~{mins}m{secs:02d}s")
    print(f"-> {gcode_path}")
    print(f"-> {preview_path}   <- check this first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
