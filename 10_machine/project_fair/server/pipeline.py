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
import os
import sys

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
    text, stats = gc.generate(paths_mm, bed_w=bed_w, bed_h=bed_h)

    with open(gcode_path, "w") as f:
        f.write(text)

    # The exact route the pen takes -- not the same picture as the line art,
    # which is the whole reason to look at it before plotting.
    with open(svg_path, "w") as f:
        f.write(gc.to_svg(paths_mm, bed_w=bed_w, bed_h=bed_h))

    stats["simplify"] = simplify
    stats["min_points"] = min_points
    return stats


def estimate_text(stats):
    """'97 strokes · ~4m12s' -- the number the operator decides on."""
    secs = int(stats.get("estimated_seconds", 0))
    mins, rem = divmod(secs, 60)
    return f"{stats.get('paths', 0)} strokes · ~{mins}m{rem:02d}s"
