"""Check every part of a 3MF is a closed, consistently wound solid: python3 tools/check_3mf.py file.3mf"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gingerbread_ornament"))
import threemf  # noqa: E402

bad = 0
parts = threemf.read_3mf(sys.argv[1])
for p in parts:
    v, t = p["verts"], p["tris"]
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    fwd = {tuple(x) for x in e.tolist()}
    open_or_flipped = sum(1 for a, b in fwd if (b, a) not in fwd) + (len(e) - len(fwd))
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    vol = np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6
    if open_or_flipped or vol <= 0:
        bad += 1
        print("BAD", p["name"], "open/flipped edges:", open_or_flipped, "volume:", round(vol, 3))
print("%d parts, %d bad" % (len(parts), bad))
