"""The three steps of the pipeline, as functions instead of scripts.

    photo.jpg  --generate_line_art-->  line_art.png  --trace-->  job.gcode
                    (OpenAI)                          (local, free)

The modules from 10_machine/src/src are imported, not shelled out to. trace.py
is already a thin CLI over image_to_paths + fit_to_bed + generate, so this is
just a second caller of the same functions -- with real exceptions and the
stats dict instead of parsed stdout.

Only step 1 touches the network.
"""

import base64
import math
import os
import sys

import numpy as np

# The pipeline lives next to the week 10 scripts.
_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "src")
)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import gcode as gc          # noqa: E402
import vectorize as vec     # noqa: E402
from caricature import PROMPTS  # noqa: E402  -- the style prompts, single source

# The kiosk offers two. The console can use any of them when regenerating.
KIOSK_STYLES = ("chibi", "pixar")
ALL_STYLES = tuple(sorted(PROMPTS))

# Matches the week 10 script: "low" is ~13x cheaper than "high" and plenty here.
QUALITY = os.environ.get("OPENAI_QUALITY", "low")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-image-2")


class PipelineError(Exception):
    pass


def generate_line_art(photo_path, out_path, style):
    """Step 1. Photo -> black-and-white line art. Costs an API call.

    About $0.016 at quality "low".
    """
    if style not in PROMPTS:
        raise PipelineError(f"unknown style {style!r}")
    if not os.environ.get("OPENAI_API_KEY"):
        raise PipelineError("OPENAI_API_KEY is not set")

    from openai import OpenAI

    # The timeout has to be generous or the SDK gives up before the model
    # answers -- same reason as the week 10 script.
    with open(photo_path, "rb") as f:
        result = OpenAI(timeout=300).images.edit(
            model=MODEL,
            image=f,
            prompt=PROMPTS[style],
            size="1024x1024",
            quality=QUALITY,
        )

    with open(out_path, "wb") as f:
        f.write(base64.b64decode(result.data[0].b64_json))

    return out_path


# --- how long the machine will actually take -------------------------------
#
# gcode.py estimates from the F words, which the firmware ignores entirely. It
# runs at its own fixed speed and acceleration, and every segment is a separate
# blocking move, so the head accelerates from rest and stops again at every
# single point. Segments average ~1.5mm, which means almost nothing ever
# reaches top speed and the whole drawing is ramps.
#
# These must match firmware.ino. If you change them there, change them here.
STEPS_PER_MM = (16 * 200) / (12.22 * math.pi)
DRAW_SPEED = float(os.environ.get("DRAW_SPEED", "2000"))
DRAW_ACCEL = float(os.environ.get("DRAW_ACCEL", "12000"))
TRAVEL_SPEED = float(os.environ.get("TRAVEL_SPEED", "2400"))
TRAVEL_ACCEL = float(os.environ.get("TRAVEL_ACCEL", "8000"))
PEN_STEP_MS = float(os.environ.get("PEN_STEP_MS", "2"))
PEN_SETTLE_MS = float(os.environ.get("PEN_SETTLE_MS", "150"))
PEN_THROW_DEG = float(os.environ.get("PEN_THROW_DEG", "70"))

# Turn each drawing half a circle so it faces the visitors rather than the
# operator standing at the origin corner. Set to 0 to draw them facing home.
ROTATE_180 = os.environ.get("PLOT_ROTATE", "180").strip() == "180"

# Fitted against six timed plots (78 to 268 strokes): the raw physics runs
# about 8% long, mostly because moveToMm limits speed on the axis with the most
# steps rather than on the diagonal, so a slanted move is shorter than the
# hypotenuse used here. One factor covers every job to within 2.2%.
# job.json records plot_seconds, so this can be refitted whenever the machine
# or the motion constants change.
ESTIMATE_SCALE = float(os.environ.get("ESTIMATE_SCALE", "0.92"))


def _move_seconds(distance_mm, speed_steps, accel_steps):
    """One blocking move: accelerate from rest, stop at the far end."""
    v = speed_steps / STEPS_PER_MM
    a = accel_steps / STEPS_PER_MM
    if distance_mm <= 0:
        return 0.0
    if distance_mm < v * v / a:          # too short to ever reach top speed
        return 2.0 * math.sqrt(distance_mm / a)
    return v / a + distance_mm / v       # ramp up, cruise, ramp down


def estimate_seconds(paths_mm):
    """Predicted wall-clock for a plot, in seconds."""
    seconds = 0.0
    here = (0.0, 0.0)
    for path in paths_mm:
        if len(path) < 2:
            continue
        seconds += _move_seconds(math.dist(here, path[0]), TRAVEL_SPEED, TRAVEL_ACCEL)
        for a, b in zip(path, path[1:]):
            seconds += _move_seconds(math.dist(a, b), DRAW_SPEED, DRAW_ACCEL)
        here = tuple(path[-1])
        # pen down at the start of the stroke, up again at the end
        seconds += 2 * (PEN_THROW_DEG * PEN_STEP_MS + PEN_SETTLE_MS) / 1000.0
    return seconds * ESTIMATE_SCALE


def trace(line_art_path, gcode_path, svg_path, *,
          bed=(100.0, 100.0), margin=5.0, simplify=1.8, min_points=12,
          max_side=1024):
    """Steps 2 and 3. Line art -> pen paths -> G-code, plus the route preview.

    Local, free, and a couple of seconds. Returns the stats dict:
    paths, points, draw_mm, travel_mm, gcode_lines, estimated_seconds.

    from_photo stays False. The input here is already line art -- running edge
    detection on lines would double every one of them.
    """
    bed_w, bed_h = bed

    with open(line_art_path, "rb") as f:
        data = f.read()

    paths, shape = vec.image_to_paths(
        data, max_side=max_side, simplify=simplify, min_points=min_points,
    )
    if not paths:
        raise PipelineError("no drawable lines found in the line art")

    paths_mm = gc.fit_to_bed(paths, shape, bed_w=bed_w, bed_h=bed_h, margin=margin)

    if ROTATE_180:
        # fit_to_bed puts the head at high Y, which reads correctly from the
        # origin corner -- where the operator stands. Everyone else is on the
        # far side and sees it upside down. Turning it half a circle fixes that.
        #
        # Both axes, not just Y: from the far side +X runs to the viewer's
        # left, so flipping Y alone would hand them a mirror image.
        paths_mm = [np.array([bed_w, bed_h]) - p for p in paths_mm]

    text, stats = gc.generate(paths_mm, bed_w=bed_w, bed_h=bed_h)

    with open(gcode_path, "w") as f:
        f.write(text)

    # The exact route the pen takes -- not the same picture as the line art,
    # which is the whole reason to look at it before plotting.
    with open(svg_path, "w") as f:
        f.write(gc.to_svg(paths_mm, bed_w=bed_w, bed_h=bed_h))

    # gcode.py's own estimate comes from the F words, which this firmware
    # ignores. Replace it with one that models what the machine really does.
    stats["estimated_seconds"] = int(estimate_seconds(paths_mm))
    stats["simplify"] = simplify
    stats["min_points"] = min_points
    return stats


def estimate_text(stats):
    """'97 strokes · ~4m12s' -- the number the operator decides on."""
    secs = int(stats.get("estimated_seconds", 0))
    mins, rem = divmod(secs, 60)
    return f"{stats.get('paths', 0)} strokes · ~{mins}m{rem:02d}s"
