"""
Build one print-ready ornament from a colour recipe (headless):
  blender --background --factory-startup --python tools/xmas_make.py -- <recipes.json> <name> <out_dir>

recipes.json: {name: {"line": "inputs/x.png" (relative to the json), "look": "PUFFED",
                      "colours": [[name, "#RRGGBB"], ...]   (extra filaments after Cookie + Icing),
                      "max_filaments": 4,                   (warning limit, e.g. 8 for two AMS units),
                      "paint": [[x, y, slot], ...],       (source-image pixel -> filament slot)
                      "cookie": "#RRGGBB",                (optional cookie colour)
                      "default_slot": -1}}                 (optional: every region starts at this slot,
                                                            e.g. -1 = bare cookie for the classic look)
Add --preview-only after <out_dir> to skip the 3MF and only render previews.
Slots: 0 cookie, 1 icing (white), 2.. the extra colours, -1 bare cookie. A point on a line
colours that line stroke; a point in an enclosed area colours that region.
Writes <out_dir>/<name>.3mf and <out_dir>/previews/<name>_top.png, _angle.png.
"""
import json
import os
import sys

import bpy
import mathutils
import numpy as np

REPO = __file__.rsplit("/tools/", 1)[0]
sys.path.insert(0, REPO)
import gingerbread_ornament as gb  # noqa: E402
gb.register()
from gingerbread_ornament import builder, threemf  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
recipes_path, name, out_dir = argv[:3]
preview_only = "--preview-only" in argv[3:]
rec = json.load(open(recipes_path))[name]
base = os.path.dirname(os.path.abspath(recipes_path))
scene = bpy.context.scene
p = scene.gingerbread_props
p.line_image = os.path.join(base, rec["line"])
p.title = rec.get("title", name)
p.size_mm = rec.get("size_mm", 80.0)
p.icing_look = rec.get("look", 'PUFFED')
p.max_filaments = rec.get("max_filaments", 4)
bpy.ops.gingerbread.generate()


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


for cname, hexc in rec.get("colours", []):
    f = p.filaments.add()
    f.name = cname
    f.color = hex_rgb(hexc)
if "icing" in rec:
    p.filaments[1].color = hex_rgb(rec["icing"])
if "cookie" in rec:
    p.filaments[0].color = hex_rgb(rec["cookie"])

o = builder._ornament(scene)
objs = builder.gingerbread_objects(scene)
reg = {int(x["gb_label"]): x for x in objs if x.get("gb_kind") == 'REGION'}
lin = {int(x["gb_label"]): x for x in objs if x.get("gb_kind") == 'LINES'}
changed, missed = [], []
if "default_slot" in rec:
    for ob in list(reg.values()):
        builder.apply_slot(ob, int(rec["default_slot"]), scene)
        changed.append(ob)


def snap(i, j, r=4):
    """A point meant for a thin line (eyes, nose) that just misses it: nearest line pixel within r cells."""
    if int(o.top[i, j]) == 1:
        return i, j
    best = None
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            ii, jj = i + di, j + dj
            if 0 <= ii < o.top.shape[0] and 0 <= jj < o.top.shape[1] and int(o.top[ii, jj]) == 1:
                d = di * di + dj * dj
                if best is None or d < best[0]:
                    best = (d, ii, jj)
    return (best[1], best[2]) if best else (i, j)


for item in rec.get("paint", []):
    x, y, slot = item[:3]
    i = int(np.abs(o.src_ys - y).argmin())
    j = int(np.abs(o.src_xs - x).argmin())
    if len(item) > 3 and item[3] == "line":
        i, j = snap(i, j)
    lab = int(o.top[i, j])
    if lab > 1 and lab in reg:
        ob = reg[lab]
    elif lab == 1 and int(o.strokes[i, j]) in lin:
        ob = lin[int(o.strokes[i, j])]
    else:
        missed.append((x, y))
        continue
    builder.apply_slot(ob, slot, scene)
    changed.append(ob)
builder.rebuild(scene, changed)
for ob in builder.gingerbread_objects(scene):        # refresh materials after the rebuild
    builder.apply_slot(ob, int(ob.get("gb_slot", 0)), scene)

os.makedirs(os.path.join(out_dir, "previews"), exist_ok=True)
out_3mf = os.path.join(out_dir, name + ".3mf")
res = "SKIPPED (preview only)" if preview_only else bpy.ops.gingerbread.export_3mf(filepath=out_3mf)
regions = [x for x in builder.gingerbread_objects(scene) if x.get("gb_kind") == 'REGION']
if len(p.filaments) > p.max_filaments:
    print("WARNING %s: %d filaments, Max Filaments is %d" % (name, len(p.filaments), p.max_filaments))
small = [x for x in regions if x.get("gb_area_mm2", 99) < 2.0 and int(x.get("gb_slot", -1)) >= 0]
used = sorted({int(x.get("gb_slot", 0)) for x in builder.gingerbread_objects(scene) if int(x.get("gb_slot", 0)) >= 0})
print("RESULT %s: export=%s size=%dKiB regions=%d strokes=%d painted=%d missed=%s filaments=%s used_slots=%s "
      "tiny_iced_regions=%d"
      % (name, res, 0 if preview_only else os.path.getsize(out_3mf) // 1024, len(regions), len(lin), len(changed), missed,
         [(f.name, threemf.hex_colour(f.color)) for f in p.filaments], used, len(small)))

# ---------------------------------------------------------------- previews
scene.render.engine = 'BLENDER_WORKBENCH'
sh = scene.display.shading
sh.light = 'STUDIO'
sh.color_type = 'MATERIAL'
sh.show_cavity = True
sh.cavity_type = 'BOTH'
sh.show_shadows = True
sh.shadow_intensity = 0.4
scene.view_settings.view_transform = 'Standard'
world = bpy.data.worlds.new("w")
world.color = (0.93, 0.93, 0.93)
scene.world = world
for ob in list(scene.objects):
    if ob.name in ("Cube", "Light"):
        bpy.data.objects.remove(ob)
for ob in builder.gingerbread_objects(scene):        # bare regions aren't printed: hide them
    if int(ob.get("gb_slot", 0)) < 0:
        ob.hide_render = True
cd = bpy.data.cameras.new("c")
cd.type = 'ORTHO'
cd.clip_end = 2000
cam = bpy.data.objects.new("c", cd)
scene.collection.objects.link(cam)
scene.camera = cam
pts = np.array([ob.matrix_world @ mathutils.Vector(c) for ob in builder.gingerbread_objects(scene)
                for c in ob.bound_box])
lo, hi = pts.min(0), pts.max(0)
ctr = mathutils.Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, 2.0))
span = max(hi[0] - lo[0], hi[1] - lo[1]) * 1.08


def shoot(fn, offset, scale, res):
    scene.render.resolution_x, scene.render.resolution_y = res
    cam.location = ctr + mathutils.Vector(offset)
    cam.rotation_euler = (ctr - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cd.ortho_scale = scale
    scene.render.filepath = os.path.join(out_dir, "previews", "%s_%s.png" % (name, fn))
    bpy.ops.render.render(write_still=True)


shoot("top", (0, 0, 300), span, (1000, 1000))
shoot("angle", (0, -220, 200), span * 1.05, (1200, 1000))
print("previews written")
