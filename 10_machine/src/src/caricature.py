#!/usr/bin/env python3
"""Step 1 — turn a photo into black-and-white line art using OpenAI.

    python src/caricature.py photo.jpg
    python src/caricature.py photo.jpg output/me.png
    python src/caricature.py photo.jpg output/me.png --style caricature

Styles:
    coloring    faithful line art, keeps real proportions (default)
    caricature  cute cartoon: bigger head, big eyes, small nose
    classic     classic caricature: exaggerates each person's own features
    pixar       animated-film look: large eyes, rounded face, oversized head
    chibi       chibi: huge head, tiny body, large sparkling eyes

Needs OPENAI_API_KEY, read from .env or the environment.

Note: OpenAI only accepts jpeg, png and webp.
"""

import argparse
import base64
import os
import sys

from openai import OpenAI

COLORING = ("Transform this portrait into a clean black-and-white coloring book illustration.\n"
"Requirements:\n"
"- Simple vector-like line art.\n"
"- No grayscale, no shading, no hatching.\n"
"- White background.\n"
"- Thick, clean outlines.\n"
"- Minimal facial details.\n"
"- Keep the person's hairstyle, smile, and face recognizable.\n"
"- Clothing should only have outlines (do not fill it with black).\n"
"- Large open areas suitable for coloring.\n"
"- Cute, friendly cartoon style.\n"
"- No texture in the hair or beard, outer contour lines only.\n"
"- Eyes and mouth outlined only, never filled with black.\n")

# The last two lines matter more than they look. Without them the model draws
# hair and beards as hundreds of tiny strokes, and fills eyes and mouths with
# solid black. Both are expensive for a plotter: a filled area is not a line,
# and every stray stroke costs a pen-up and a pen-down. On our test photo they
# cut the drawing from 237 strokes to 69.

CARICATURE = """Transform this portrait into a cute cartoon caricature.

Style:
- Big expressive eyes.
- Slightly oversized head (about 20–30% larger than realistic).
- Small nose.
- Friendly smile.
- Soft rounded face.
- Simplified features.
- Keep the hairstyle recognizable.
- Clean vector-style black outlines.
- White background.
- No shading.
- No grayscale.
- Suitable for a coloring book."""

CLASSIC = """Turn this portrait into a classic caricature illustration.

- Exaggerate the person's most recognizable facial features while keeping them clearly identifiable.
- Large head.
- Expressive smile.
- Clean flowing ink lines.
- Minimal details.
- Black and white only.
- White background.
- No shading.
- Suitable for coloring."""

PIXAR = """Create a stylized cartoon portrait inspired by modern animated films.

- Large eyes.
- Soft rounded face.
- Slightly oversized head.
- Friendly expression.
- Simple clean outlines.
- Black and white only.
- No shading.
- Coloring page style."""

# Heads up on "Long flowing hair": that line describes the SUBJECT, not the
# style, so the model will tend to give long hair to whoever is in the photo,
# including people who do not have it. The other styles avoid this by asking to
# keep the hairstyle instead of naming one.

CHIBI = """Transform this portrait into a chibi character.

- Huge head.
- Tiny body.
- Large sparkling eyes.
- Cute smile.
- Simplified hair.
- Black-and-white line art.
- No shading.
- White background.
- Coloring book illustration."""

PROMPTS = {
    "coloring": COLORING,
    "classic": CLASSIC,
    "caricature": CARICATURE,
    "pixar": PIXAR,
    "chibi": CHIBI,
}


def load_env(path=".env"):
    """Minimal .env reader. Existing environment variables win."""
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main():
    ap = argparse.ArgumentParser(description="photo -> black-and-white line art")
    ap.add_argument("photo")
    ap.add_argument("out", nargs="?", default="output/caricature.png")
    ap.add_argument("--style", default="coloring", choices=sorted(PROMPTS),
                    help="coloring = faithful line art; caricature = cute cartoon; "
                         "classic = exaggerated features; pixar = animated-film "
                         "look; chibi = huge head, tiny body")
    # "low" is the default on purpose.
    ap.add_argument("--quality", default="low", choices=["low", "medium", "high"],
                    help="low is enough here and ~13x cheaper than high")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        return 1

    # Timeout has to be generous or the SDK gives up before the model answers.
    with open(args.photo, "rb") as f:
        result = OpenAI(timeout=300).images.edit(
            model="gpt-image-2",
            image=f,
            prompt=PROMPTS[args.style],
            size="1024x1024",
            quality=args.quality,
        )

    with open(args.out, "wb") as f:
        f.write(base64.b64decode(result.data[0].b64_json))

    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
