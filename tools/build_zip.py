# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Craig Midwinter
"""
Build the extension zip that ships on Gumroad (reproducible: sorted entries, fixed timestamps):
  python3 tools/build_zip.py [out_dir=dist/gumroad]

Why not `blender --command extension build`: Kate's gate wants the copyright entry exactly
"Bambu Lab (bundled printer/filament settings, AGPL-3.0)", and Blender's STRICT manifest check
(used only by `extension build/validate`, i.e. the extensions.blender.org path) requires every
copyright entry to start with a year. Installing is non-strict: Install from Disk /
`extension install-file` accept this zip (tested). If the add-on is ever submitted to
extensions.blender.org, prefix that entry with a year ("2022-2026 Bambu Lab (...)").

Same layout as `extension build`: the add-on's files at the zip root, with the manifest's
paths_exclude_pattern left out.
"""
import fnmatch
import os
import sys
import tomllib
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "gingerbread_ornament")
STAMP = (2026, 1, 1, 0, 0, 0)


def main():
    out_dir = os.path.join(REPO, sys.argv[1] if len(sys.argv) > 1 else "dist/gumroad")
    m = tomllib.load(open(os.path.join(SRC, "blender_manifest.toml"), "rb"))
    for k in ("id", "version", "name", "maintainer", "blender_version_min", "license", "copyright"):
        assert m.get(k), "manifest is missing " + k
    excl = m.get("build", {}).get("paths_exclude_pattern", [])

    def skipped(rel):
        parts = rel.split("/")
        for pat in excl:
            p = pat.strip("/")
            if pat.endswith("/") and p in parts[:-1]:
                return True
            if any(fnmatch.fnmatch(x, p) for x in parts):
                return True
        return False

    files = []
    for root, dirs, names in os.walk(SRC):
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), SRC).replace(os.sep, "/")
            if not skipped(rel):
                files.append(rel)
    files.sort()
    out = os.path.join(out_dir, "%s-%s.zip" % (m["id"], m["version"]))
    tmp = out + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            info = zipfile.ZipInfo(rel, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, open(os.path.join(SRC, rel), "rb").read())
    os.replace(tmp, out)
    print("built %s: %d files %s" % (os.path.relpath(out, REPO), len(files), files))


if __name__ == "__main__":
    main()
