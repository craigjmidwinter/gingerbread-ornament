"""
Numbered region map of a line-art image (plain python3, no Blender), for writing colour recipes:
  python3 -I tools/region_map.py <line.png> <out_map.png> <out_anchors.json> [size_mm=80]

Each enclosed region gets its label number drawn at its innermost point; the JSON maps
label -> [source x, source y, area mm²] (a point well inside the region, in image pixels),
which tools/xmas_make.py uses to colour regions by position.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gingerbread_ornament"))
import core  # noqa: E402

src, out_png, out_json = sys.argv[1:4]
size = float(sys.argv[4]) if len(sys.argv) > 4 else 80.0
rgb = np.asarray(Image.open(src).convert("RGB"), np.float64) / 255.0
o = core.analyse(rgb, None, size_mm=size)
im = Image.open(src).convert("RGB")
scale = 1600 / max(im.size)
im = im.resize((int(im.width * scale), int(im.height * scale)))
d = ImageDraw.Draw(im)
anchors = {}
for r in o.regions:
    lab = r["label"]
    m = o.top == lab
    dd = np.where(m, o.d_top, -1)
    i, j = np.unravel_index(int(dd.argmax()), dd.shape)
    sx, sy = float(o.src_xs[j]), float(o.src_ys[i])
    anchors[lab] = [round(sx, 1), round(sy, 1), round(r["area_mm2"], 1)]
    x, y = sx * scale, sy * scale
    d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 0, 0))
    d.text((x + 4, y - 6), str(lab), fill=(200, 0, 0))
im.save(out_png)
json.dump(anchors, open(out_json, "w"), indent=0)
print("%s: %d regions" % (os.path.basename(src), len(o.regions)))
