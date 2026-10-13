#!/usr/bin/env python3
"""Turns a portrait photo into dots.json, the point cloud drawn in the card's
VISUAL.MAP panel. Only needed when the photo changes; generate.py just reads
the JSON. Needs Pillow and numpy.

    python3 portrait.py path/to/photo.jpg
"""
import json
import pathlib
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = pathlib.Path(__file__).parent
CROP = (0.28, 0.17, 0.62, 0.475)  # left, top, right, bottom as fractions of the photo
WIDTH, HEIGHT = 394, 532  # drawing area inside the panel, px
DOTS = 5600

random.seed(7)
photo = ImageOps.exif_transpose(Image.open(sys.argv[1])).convert("RGB")
w, h = photo.size
photo = photo.crop((int(CROP[0] * w), int(CROP[1] * h), int(CROP[2] * w), int(CROP[3] * h)))
photo = photo.resize((WIDTH, HEIGHT), Image.LANCZOS)
rgb = np.asarray(photo).astype(float)
r, b = rgb[..., 0], rgb[..., 2]
lum = 0.299 * r + 0.587 * rgb[..., 1] + 0.114 * b

# The backdrop is a bright warm curtain. Keep only the part of that mask that
# touches the frame edge, so highlights on the face are not cut out with it.
mask = Image.fromarray((((lum > 150) & ((r - b) > 38)) * 255).astype("uint8"))
mask = mask.filter(ImageFilter.MedianFilter(5))
for x, y in [(0, 0), (WIDTH - 1, 0), (WIDTH // 2, 0), (WIDTH // 4, 0), (3 * WIDTH // 4, 0),
             (0, HEIGHT // 3), (WIDTH - 1, HEIGHT // 3)]:
    if mask.getpixel((x, y)) == 255:
        ImageDraw.floodfill(mask, (x, y), 128)
background = np.asarray(mask) == 128
skin = ~background & (lum < 150)
shirt = ~background & ~skin


def rank(values):
    return values.argsort().argsort() / max(1, len(values) - 1)


# Dot density: hair and beard densest, lit skin lighter, shirt a faint texture.
density = np.zeros_like(lum)
density[skin] = 0.05 + 0.95 * (1 - rank(lum[skin])) ** 2.8
density[shirt] = 0.03 + 0.10 * (1 - rank(lum[shirt]))

dots = []
while len(dots) < DOTS:
    x, y = random.uniform(0, WIDTH - 1), random.uniform(0, HEIGHT - 1)
    if random.random() < density[int(y), int(x)]:
        dots.append([round(x, 1), round(y, 1)])

(ROOT / "dots.json").write_text(json.dumps({"width": WIDTH, "height": HEIGHT, "dots": dots}))
print(f"wrote {len(dots)} dots")
