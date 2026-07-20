# Photo → Pen Plotter

Turn a photo of a person into a line drawing and plot it with a pen.

Three steps, each one script:

```
photo.jpg  ──►  line art  ──►  pen paths  ──►  drawing.gcode  ──►  ESP32
           OpenAI        skeletonize      G-code
```

Everything runs locally. The only network call is the image generation.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then paste your OpenAI key into .env
```

The OpenAI API is billed separately from ChatGPT — a Plus subscription does
**not** include API credit. Get a key at
[platform.openai.com](https://platform.openai.com/api-keys).

A few dollars goes a long way: the default `--quality low` costs about **$0.016
per drawing**, so a class of 30 students with 3 tries each is around **$1.50**.

## Usage

**1. Photo → line art**

```bash
python src/caricature.py photos/foto2.jpeg output/me.png
python src/caricature.py photos/foto2.jpeg output/me.png --style caricature
python src/caricature.py photos/foto2.jpeg output/me.png --quality high
```

Five styles:

| `--style` | what it does |
|---|---|
| `coloring` *(default)* | faithful line art, real proportions |
| `caricature` | cute cartoon: bigger head, big eyes, small nose |
| `classic` | classic caricature: exaggerates each person's own features |
| `pixar` | animated-film look: large eyes, rounded face, oversized head |
| `chibi` | chibi: huge head, tiny body, large sparkling eyes |


Accepts `jpeg`, `png`, `webp`

**2. Line art → G-code**

```bash
python src/trace.py output/me.png
python src/trace.py output/me.png --bed 150x150
```

Writes `output/me.gcode` and `output/me_preview.png`.

**Always open the preview before plotting.** It shows the exact route the pen
will take, which is not the same thing as the image you fed in.

**3. Send to the plotter**

Not automated yet. Send `output/me.gcode` to the ESP32 over serial.

