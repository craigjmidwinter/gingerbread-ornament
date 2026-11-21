# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Craig Midwinter
"""
PUBLIC_NAME: the one public maintainer/copyright name (Kate's gate, section 5.2).
Default "Craig Midwinter". To swap in a handle everywhere at once:

  python3 tools/set_public_name.py "New Name"            # rewrite the files below
  python3 tools/set_public_name.py --check               # list where the current name appears

Covers: manifest maintainer + copyright, the three LICENSE headers, THIRD-PARTY-NOTICES, every
SPDX copyright header in the add-on and web code, the web footer and the Gumroad docs.
Rebuild the zip afterwards: python3 tools/build_zip.py
"""
import glob
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURRENT = "Craig Midwinter"


def files():
    pats = ["gingerbread_ornament/*.py", "gingerbread_ornament/blender_manifest.toml",
            "gingerbread_ornament/LICENSE", "gingerbread_ornament/THIRD-PARTY-NOTICES",
            "gingerbread_ornament/README.txt", "LICENSE", "tools/*.py", "tests/*.py",
            "web/LICENSE", "web/index.html", "web/js/*.js", "web/py/*.py", "web/scripts/*",
            "web/test/*.mjs", "web/README.md", "dist/gumroad/*.md"]
    out = []
    for p in pats:
        out += [f for f in glob.glob(os.path.join(REPO, p)) if os.path.isfile(f)]
    return sorted(set(out))


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    hits = [(f, open(f, encoding="utf-8").read().count(CURRENT)) for f in files()]
    hits = [(f, n) for f, n in hits if n]
    if sys.argv[1] == "--check":
        for f, n in hits:
            print("%3d  %s" % (n, os.path.relpath(f, REPO)))
        return
    new = sys.argv[1].strip()
    assert new and '"' not in new, "name must be non-empty and contain no double quotes"
    for f, n in hits:
        s = open(f, encoding="utf-8").read()
        open(f, "w", encoding="utf-8").write(s.replace(CURRENT, new))
        print("%3d  %s" % (n, os.path.relpath(f, REPO)))
    me = os.path.abspath(__file__)
    s = open(me, encoding="utf-8").read()
    open(me, "w", encoding="utf-8").write(s.replace('CURRENT = "%s"' % CURRENT, 'CURRENT = "%s"' % new))


if __name__ == "__main__":
    main()
