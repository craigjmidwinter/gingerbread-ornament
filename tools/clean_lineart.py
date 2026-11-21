"""
Clean a downloaded colouring page into add-on line art (plain python3 + numpy + PIL):
  python3 -I tools/clean_lineart.py <in.png> <out.png> [threshold=0.5] [keep_far=0|1|strict] [x0,y0,x1,y1 ...]

- flattens transparency onto white
- drops light-grey shading (anything lighter than the threshold becomes paper)
- drops stray specks and scattered decorations (snow dots, stars) that sit outside the
  main drawing, since they would bulge the cookie outline; keep_far=1 keeps them,
  strict keeps only the main drawing and what it encloses (busy page backgrounds)
- erases a printed page frame (rows/columns that are mostly ink)
- erases any given rectangles (input pixel coords), e.g. a background landscape
- crops to the drawing with a small margin
Kept pixels keep their anti-aliased grey values so the outline stays smooth.
"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gingerbread_ornament"))
import core  # noqa: E402

src, dst = sys.argv[1], sys.argv[2]
thr = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
keep_far = len(sys.argv) > 4 and sys.argv[4] == "1"
strict = len(sys.argv) > 4 and sys.argv[4] == "strict"     # only the main drawing + what it encloses

im = Image.open(src).convert("RGBA")
bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
bg.alpha_composite(im)
rgb = np.asarray(bg.convert("RGB"), np.float64) / 255.0
lum = core.luminance(rgb)
for r in sys.argv[5:]:
    x0, y0, x1, y1 = (int(v) for v in r.split(","))
    lum[y0:y1, x0:x1] = 1.0
# Printed page frame: straight rows/columns that are mostly ink (plus a couple of px around).
dark = lum < thr
for axis in (0, 1):
    frac = dark.mean(axis=axis)
    for k in np.flatnonzero(frac > 0.5):
        if axis == 0:
            lum[:, max(k - 3, 0):k + 4] = 1.0
        else:
            lum[max(k - 3, 0):k + 4, :] = 1.0
ink = lum < thr

lab, n = core.label_components(ink, diag=True)
sizes = np.bincount(lab.ravel(), minlength=n + 1)
sizes[0] = 0
main = int(sizes.argmax())
keep = lab == main
# Everything enclosed by the main drawing counts as part of it.
bgl, nb = core.label_components(~keep)
border = set(np.unique(np.concatenate([bgl[0], bgl[-1], bgl[:, 0], bgl[:, -1]])).tolist())
inside = ~np.isin(bgl, list(border)) & ~keep
hull = core.dilate(keep | inside, 6)
min_px = max(12, int(ink.size * 2e-5))
removed = 0
for k in range(1, n + 1):
    if k == main or sizes[k] == 0:
        continue
    comp = lab == k
    big = sizes[k] >= 0.02 * sizes[main] and not strict
    if (comp & hull).any() and sizes[k] >= min_px or big or keep_far and sizes[k] >= min_px:
        keep |= comp
    else:
        removed += 1

# Keep the anti-aliased edge pixels around what we kept.
soft = core.dilate(keep, 2) & (lum < 0.98)
out = np.where(soft, lum, 1.0)
rows = np.flatnonzero((out < thr).any(axis=1))
cols = np.flatnonzero((out < thr).any(axis=0))
pad = 10
r0, r1 = max(rows[0] - pad, 0), min(rows[-1] + pad + 1, out.shape[0])
c0, c1 = max(cols[0] - pad, 0), min(cols[-1] + pad + 1, out.shape[1])
out = out[r0:r1, c0:c1]
Image.fromarray((out * 255).round().astype(np.uint8)).save(dst)
print("%s: kept %d px of ink, removed %d specks/decorations, %dx%d"
      % (os.path.basename(dst), int((out < thr).sum()), removed, out.shape[1], out.shape[0]))
