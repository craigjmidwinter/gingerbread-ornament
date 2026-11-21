# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Craig Midwinter
"""
Blender-side helpers: load images, turn core meshes into objects, manage the
filament palette materials, collect parts for export.
"""
import json
import math

import bpy
import bmesh
import numpy as np

from . import core

COLLECTION_NAME = "Gingerbread"
BARE_SCALE = 0.04
DECIMATE = {'COOKIE': 0.06, 'LINES': 0.5, 'REGION': 0.3}

MULTI_GAP_MM = 10.0

# Analysed ornament per (scene, ornament key), so a style change can rebuild just the parts it
# touches. The key is "" for the single-image ornament (objects directly in "Gingerbread") and the
# child collection name for each ornament in multi-image mode (objects carry it as "gb_ornament").
# Not saved with the .blend: after a restart it is re-analysed from the same images/settings.
_CACHE = {}


# ----------------------------------------------------------------------------
# Images
# ----------------------------------------------------------------------------

def load_image_rgb(path):
    """Load an image file as float RGB (H, W, 3), row 0 = top. Alpha composited on white."""
    path = bpy.path.abspath(path)
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        ch = img.channels
        buf = np.empty(w * h * ch, dtype=np.float32)
        img.pixels.foreach_get(buf)
        a = buf.reshape(h, w, ch)[::-1]
        if ch == 4:
            rgb = a[..., :3] * a[..., 3:4] + (1.0 - a[..., 3:4])
        elif ch >= 3:
            rgb = a[..., :3]
        else:
            rgb = np.repeat(a[..., :1], 3, axis=2)
        if img.is_float:
            # float images are linear; bring back to display space for thresholds
            rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(np.clip(rgb, 0, None), 1 / 2.4) - 0.055)
        return np.ascontiguousarray(rgb, dtype=np.float32)
    finally:
        bpy.data.images.remove(img)


# ----------------------------------------------------------------------------
# Colours / materials
# ----------------------------------------------------------------------------

def srgb_to_linear(c):
    return tuple((v / 12.92) if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c[:3])


def slot_material(index, rgb):
    name = "GB Filament %d" % (index + 1)
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    lin = srgb_to_linear(rgb)
    mat.diffuse_color = (lin[0], lin[1], lin[2], 1.0)
    mat.roughness = 0.6
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (lin[0], lin[1], lin[2], 1.0)
    except Exception:
        pass
    return mat


def sync_palette_materials(scene):
    props = scene.gingerbread_props
    for i, f in enumerate(props.filaments):
        slot_material(i, tuple(f.color))
    for obj in gingerbread_objects(scene):
        apply_slot(obj, obj.get("gb_slot", 0), scene)


def apply_slot(obj, slot, scene):
    """slot: 0-based filament index, or -1 for bare cookie (region not printed)."""
    props = scene.gingerbread_props
    obj["gb_slot"] = int(slot)
    if slot < 0:
        mat_index = 0
        obj.scale.z = BARE_SCALE
    else:
        mat_index = min(slot, len(props.filaments) - 1)
        obj.scale.z = 1.0
    if len(props.filaments) == 0:
        return
    rgb = tuple(props.filaments[mat_index].color)
    mat = slot_material(mat_index, rgb)
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def gingerbread_objects(scene):
    col = bpy.data.collections.get(COLLECTION_NAME)
    if col is None:
        return []
    return [o for o in col.all_objects if o.type == 'MESH' and "gb_kind" in o]


# ----------------------------------------------------------------------------
# Building
# ----------------------------------------------------------------------------

def _make_mesh_object(name, verts, faces, collection, z_origin=0.0, decimate=0.25):
    me = bpy.data.meshes.new(name)
    v = verts.copy()
    v[:, 2] -= z_origin
    me.vertices.add(len(v))
    me.vertices.foreach_set("co", v.astype(np.float32).ravel())
    nf = len(faces)
    me.loops.add(nf * 4)
    me.loops.foreach_set("vertex_index", faces.astype(np.int32).ravel())
    me.polygons.add(nf)
    me.polygons.foreach_set("loop_start", np.arange(0, nf * 4, 4, dtype=np.int32))
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location.z = z_origin
    collection.objects.link(obj)
    if decimate == 'FLAT':
        # Flat part: collapse only the flat interior. Every vertex on a wall (the part's outline,
        # shared with its neighbours) is locked, so neighbouring parts keep exactly matching edges
        # and the surface stays seamless.
        n = len(me.vertices)
        wall = np.zeros(n, bool)
        for poly in me.polygons:
            if abs(poly.normal.z) < 0.5:
                wall[list(poly.vertices)] = True
        vg = obj.vertex_groups.new(name="gb_free")
        vg.add(np.flatnonzero(~wall).tolist(), 1.0, 'REPLACE')
        vg.add(np.flatnonzero(wall).tolist(), 0.0, 'REPLACE')
        mod = obj.modifiers.new("Decimate", 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = 0.02
        mod.vertex_group = "gb_free"
        mod.vertex_group_factor = 1000.0
        dg = bpy.context.evaluated_depsgraph_get()
        new_me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
        obj.modifiers.remove(mod)
        obj.vertex_groups.remove(vg)
        obj.data = new_me
        bpy.data.meshes.remove(me)
        new_me.name = name
    elif decimate and decimate < 1.0:
        # Quadric collapse: flat areas collapse to a few triangles, curved icing keeps its shape.
        mod = obj.modifiers.new("Decimate", 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = decimate
        dg = bpy.context.evaluated_depsgraph_get()
        new_me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
        obj.modifiers.remove(mod)
        obj.data = new_me
        bpy.data.meshes.remove(me)
        new_me.name = name
    # Smooth shading for the rounded icing, but sharp at walls and creases: a flat top must look
    # flat (smooth normals blended with the walls made flat parts look domed in the viewport).
    try:
        obj.data.shade_smooth()
        obj.data.set_sharp_from_angle(angle=math.radians(30))
    except Exception:
        pass
    return obj


def clear_collection():
    """Remove every object in the Gingerbread collection and its per-ornament child collections."""
    col = bpy.data.collections.get(COLLECTION_NAME)
    if col is None:
        return
    for o in list(col.all_objects):
        me = o.data if o.type == 'MESH' else None
        bpy.data.objects.remove(o, do_unlink=True)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
    for child in list(col.children_recursive):
        bpy.data.collections.remove(child)
    if "gb_mode" in col:
        del col["gb_mode"]


def ensure_collection(scene):
    col = bpy.data.collections.get(COLLECTION_NAME)
    if col is None:
        col = bpy.data.collections.new(COLLECTION_NAME)
        scene.collection.children.link(col)
    elif col.name not in scene.collection.children:
        try:
            scene.collection.children.link(col)
        except RuntimeError:
            pass
    return col


def setup_scene_units(scene):
    us = scene.unit_settings
    us.system = 'METRIC'
    us.length_unit = 'MILLIMETERS'
    us.scale_length = 0.001
    for area in getattr(bpy.context, "screen", None).areas if getattr(bpy.context, "screen", None) else []:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.clip_end = max(space.clip_end, 10000)
                    space.overlay.grid_scale = 0.001


def _fill_palette(props, palette):
    props.filaments.clear()
    for i, c in enumerate(palette):
        f = props.filaments.add()
        f.name = "Cookie" if i == 0 else ("Icing" if i == 1 else "Colour %d" % (i - 1))
        f.color = c
    props.active_filament = 2 if len(palette) > 2 else 1


def _icing_look(props):
    look = getattr(props, "icing_look", 'PUFFED')
    return 'PAINTED' if look == 'SEAMLESS' else look


def _build_objects(scene, o, meshes, col, slot_of, look, prefix="", key=None):
    """Turn core meshes into objects in `col`. prefix: name prefix ("Tree " -> "Tree Region 003");
    key: the ornament key stored as gb_ornament (None = single-image mode, no key).
    Returns (objects, n_regions, n_strokes)."""
    T = o.params["cookie_thickness_mm"]
    area_by_label = {r["label"]: r["area_mm2"] for r in o.regions}
    count = 0
    strokes = 0
    n_strokes = sum(1 for m in meshes if m[0] == 'LINES')
    objs = []
    for kind, ident, v, f in meshes:
        if kind == 'COOKIE':
            obj = _make_mesh_object(prefix + "Cookie", v, f, col, decimate=DECIMATE[kind])
            slot = 0
        elif kind == 'LINES':
            strokes += 1
            nm = "Icing Lines" if n_strokes == 1 else "Line %03d" % strokes
            obj = _make_mesh_object(prefix + nm, v, f, col, z_origin=T, decimate=_dec(kind, v))
            obj["gb_style"] = 'AUTO'
            slot = 1
        else:
            count += 1
            obj = _make_mesh_object(prefix + "Region %03d" % count, v, f, col, z_origin=T, decimate=_dec(kind, v))
            obj["gb_area_mm2"] = round(area_by_label[ident], 2)
            obj["gb_style"] = look
            slot = slot_of[ident]
        obj["gb_kind"] = kind
        obj["gb_label"] = int(ident)
        if key is not None:
            obj["gb_ornament"] = key
        apply_slot(obj, slot, scene)
        objs.append(obj)
    return objs, count, strokes


def generate(scene, line_path, colour_path, params, log=print):
    props = scene.gingerbread_props
    line_rgb = load_image_rgb(line_path) if line_path else None
    colour_rgb = load_image_rgb(colour_path) if colour_path else None
    if line_rgb is None and colour_rgb is None:
        raise ValueError("Choose a line-art image (and optionally a coloured version).")
    o = core.analyse(line_rgb, colour_rgb, **params)
    palette, slots = core.build_palette(
        o.regions, merge=params.get("colour_merge", 0.18),
        cookie_rgb=tuple(props.cookie_color), icing_rgb=tuple(props.icing_color),
        max_filaments=params.get("max_filaments", 0))

    # Palette -> scene filaments
    _fill_palette(props, palette)

    setup_scene_units(scene)
    clear_collection()
    col = ensure_collection(scene)
    look = _icing_look(props)
    slot_of = {r["label"]: (-1 if sl is None else sl) for r, sl in zip(o.regions, slots)}
    region_style = {r["label"]: look for r in o.regions}
    region_bare = {lab: sl < 0 for lab, sl in slot_of.items()}
    meshes = core.build_meshes(o, region_style, region_bare)
    col["gb_params"] = json.dumps(dict(line=line_path, colour=colour_path, params=params), default=str)
    stored = json.loads(col["gb_params"])
    _drop_cache(scene)
    _CACHE[(scene.name, "")] = (_params_key(stored["line"], stored["colour"], stored["params"]), o)
    _, count, strokes = _build_objects(scene, o, meshes, col, slot_of, look)
    log("[Gingerbread] %d parts, %d regions, %d line strokes, %d filaments"
        % (len(meshes), count, strokes, len(palette)))
    return o


def _unique_titles(titles):
    out, seen = [], set()
    for t in titles:
        base = (t or "").strip() or "Ornament"
        name, n = base, 2
        while name.lower() in seen:
            name = "%s %d" % (base, n)
            n += 1
        seen.add(name.lower())
        out.append(name)
    return out


def generate_multi(scene, entries, params, log=print, gap_mm=MULTI_GAP_MM):
    """Multi-image mode. entries: list of (title, line_path, colour_path). Every image is analysed
    with the same params; ONE palette is built over all their regions (Max Filaments applies to the
    whole set). Each ornament goes in its own child collection of "Gingerbread" (holding its own
    gb_params), its objects are prefixed with its title and carry gb_ornament = that collection's
    name, and the ornaments are laid out side by side along X. Returns the list of child collections."""
    props = scene.gingerbread_props
    if not entries:
        raise ValueError("Add at least one image (and tick it) first.")
    titles = _unique_titles([e[0] for e in entries])
    analysed = []
    for title, (_, line_path, colour_path) in zip(titles, entries):
        line_rgb = load_image_rgb(line_path) if line_path else None
        colour_rgb = load_image_rgb(colour_path) if colour_path else None
        if line_rgb is None and colour_rgb is None:
            raise ValueError("%s: choose a line-art image." % title)
        try:
            o = core.analyse(line_rgb, colour_rgb, **params)
        except ValueError as e:
            raise ValueError("%s: %s" % (title, e))
        analysed.append((title, line_path, colour_path, o))

    all_regions = [r for (_, _, _, o) in analysed for r in o.regions]
    palette, slots = core.build_palette(
        all_regions, merge=params.get("colour_merge", 0.18),
        cookie_rgb=tuple(props.cookie_color), icing_rgb=tuple(props.icing_color),
        max_filaments=params.get("max_filaments", 0))
    _fill_palette(props, palette)

    setup_scene_units(scene)
    clear_collection()
    main = ensure_collection(scene)
    if "gb_params" in main:
        del main["gb_params"]
    main["gb_mode"] = 'MULTI'
    _drop_cache(scene)
    look = _icing_look(props)
    cols = []
    cursor = 0.0
    placed = []
    pos = 0
    n_parts = 0
    for i, (title, line_path, colour_path, o) in enumerate(analysed):
        my_slots = slots[pos:pos + len(o.regions)]
        pos += len(o.regions)
        slot_of = {r["label"]: (-1 if sl is None else sl) for r, sl in zip(o.regions, my_slots)}
        region_style = {r["label"]: look for r in o.regions}
        region_bare = {lab: sl < 0 for lab, sl in slot_of.items()}
        meshes = core.build_meshes(o, region_style, region_bare)
        col = bpy.data.collections.new("GB %d %s" % (i + 1, title))
        main.children.link(col)
        key = col.name
        col["gb_params"] = json.dumps(dict(line=line_path, colour=colour_path, params=params), default=str)
        col["gb_title"] = title
        col["gb_index"] = i
        stored = json.loads(col["gb_params"])
        _CACHE[(scene.name, key)] = (_params_key(stored["line"], stored["colour"], stored["params"]), o)
        objs, count, strokes = _build_objects(scene, o, meshes, col, slot_of, look, prefix=title + " ", key=key)
        n_parts += len(objs)
        # Side by side along X: the cookie outline is the widest part of every ornament.
        cv = meshes[0][2]
        x0, x1 = float(cv[:, 0].min()), float(cv[:, 0].max())
        dx = cursor - x0
        cursor = dx + x1 + gap_mm
        placed.append((objs, dx))
        cols.append(col)
        log("[Gingerbread] %s: %d parts, %d regions, %d line strokes" % (title, len(objs), count, strokes))
    # centre the row on the origin
    shift = (cursor - gap_mm) / 2.0
    for objs, dx in placed:
        for obj in objs:
            obj.location.x = dx - shift
    log("[Gingerbread] %d ornaments, %d parts, %d shared filaments" % (len(cols), n_parts, len(palette)))
    return cols


# ----------------------------------------------------------------------------
# Styles (puffed / painted) and partial rebuilds
# ----------------------------------------------------------------------------

def _dec(kind, v):
    return 'FLAT' if kind != 'COOKIE' and core.is_flat(v) else DECIMATE[kind]


def _drop_cache(scene):
    for k in [k for k in _CACHE if (k[0] if isinstance(k, tuple) else k) == scene.name]:
        del _CACHE[k]


def ornament_key(obj):
    """Which ornament a part belongs to: "" = the single-image ornament, else its child collection name."""
    return str(obj.get("gb_ornament", ""))


def _params_collection(key):
    col = bpy.data.collections.get(key or COLLECTION_NAME)
    if col is None or "gb_params" not in col:
        raise RuntimeError("Generate the ornament first")
    return col


def ornament_keys(scene):
    """Keys of every generated ornament, in layout order."""
    keys = []
    for o in gingerbread_objects(scene):
        k = ornament_key(o)
        if k not in keys:
            keys.append(k)

    def order(k):
        c = bpy.data.collections.get(k) if k else None
        return int(c.get("gb_index", 0)) if c is not None else -1
    return sorted(keys, key=order)


def ornament_title(key):
    if not key:
        return None
    c = bpy.data.collections.get(key)
    return str(c.get("gb_title", key)) if c is not None else key


def ornament_objects(scene, key):
    return [o for o in gingerbread_objects(scene) if ornament_key(o) == key]


def set_seamless(scene, on):
    """Switch the seamless flag on the stored generation settings (no re-analysis needed),
    on every ornament in the scene."""
    keys = ornament_keys(scene) or [""]
    for key in keys:
        col = _params_collection(key)
        stored = json.loads(col["gb_params"])
        if bool(stored["params"].get("seamless")) == bool(on):
            continue
        o = _ornament(scene, key)
        stored["params"]["seamless"] = bool(on)
        col["gb_params"] = json.dumps(stored)
        o.params["seamless"] = bool(on)
        stored = json.loads(col["gb_params"])
        _CACHE[(scene.name, key)] = (_params_key(stored["line"], stored["colour"], stored["params"]), o)


def _params_key(line_path, colour_path, params):
    return json.dumps(dict(line=line_path, colour=colour_path, params=params), sort_keys=True, default=str)


def _ornament(scene, key=""):
    """The analysed ornament `key` ("" = single-image), re-analysing from the stored inputs if needed."""
    col = _params_collection(key)
    stored = json.loads(col["gb_params"])
    pkey = _params_key(stored["line"], stored["colour"], stored["params"])
    hit = _CACHE.get((scene.name, key))
    if hit is not None and hit[0] == pkey:
        return hit[1]
    line_rgb = load_image_rgb(stored["line"]) if stored["line"] else None
    colour_rgb = load_image_rgb(stored["colour"]) if stored["colour"] else None
    params = dict(stored["params"])
    params.setdefault("outline_smooth_mm", 0.0)    # made before 0.4.0: keep its exact labels
    params.setdefault("geometry", 1)                # made by 0.5.0 or earlier: same scale and strokes as then
    o = core.analyse(line_rgb, colour_rgb, **params)
    core.prepare(o)
    _CACHE[(scene.name, key)] = (pkey, o)
    return o


def current_styles(scene, key=""):
    region_style, region_bare, stroke_style = {}, {}, {}
    for obj in ornament_objects(scene, key):
        kind = obj.get("gb_kind")
        if "gb_label" not in obj:
            continue
        lab = int(obj["gb_label"])
        if kind == 'REGION':
            region_style[lab] = obj.get("gb_style", 'PUFFED')
            region_bare[lab] = int(obj.get("gb_slot", 0)) < 0
        elif kind == 'LINES':
            stroke_style[lab] = obj.get("gb_style", 'AUTO')
    return region_style, region_bare, stroke_style


def _replace_mesh(obj, v, f, z_origin, decimate):
    col = obj.users_collection[0]
    tmp = _make_mesh_object(obj.name + "_tmp", v, f, col, z_origin=z_origin, decimate=decimate)
    old = obj.data
    new = tmp.data
    obj.data = new
    bpy.data.objects.remove(tmp)
    name = old.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    new.name = name


def rebuild(scene, changed):
    """Re-mesh the parts that a style/bare change on `changed` objects can affect, ornament by
    ornament (only the changed objects' own ornament is touched). Returns the number of parts rebuilt."""
    changed = [c for c in changed if "gb_label" in c and c.get("gb_kind") in ('LINES', 'REGION')]
    by_key = {}
    for c in changed:
        by_key.setdefault(ornament_key(c), []).append(c)
    return sum(_rebuild_one(scene, key, objs) for key, objs in by_key.items())


def _rebuild_one(scene, key, changed):
    o = _ornament(scene, key)
    if getattr(o, "ctx", None) is None:
        core.prepare(o)
    rs, rb, ss = current_styles(scene, key)
    rs, rb, flush = core.resolve_styles(o, rs, rb, ss)
    ff = core.flush_field(o, rs, rb, flush)
    regs, strs = set(), set()
    for c in changed:
        r, s_ = core.affected_parts(o, c["gb_kind"], int(c["gb_label"]))
        regs |= r
        strs |= s_
    T = o.params["cookie_thickness_mm"]
    n = 0
    for obj in ornament_objects(scene, key):
        kind = obj.get("gb_kind")
        if "gb_label" not in obj or kind not in ('LINES', 'REGION'):
            continue
        lab = int(obj["gb_label"])
        if (kind == 'REGION' and lab in regs) or (kind == 'LINES' and lab in strs):
            v, f = core.part_mesh(o, kind, lab, rs, flush, ff)
            _replace_mesh(obj, v, f, T, _dec(kind, v))
            apply_slot(obj, int(obj.get("gb_slot", 0)), scene)
            n += 1
    return n


def set_slot(scene, obj, slot):
    """apply_slot plus a rebuild of neighbours when the part switches between bare and iced
    (a painted surface rounds off where it meets bare cookie)."""
    was_bare = int(obj.get("gb_slot", 0)) < 0
    apply_slot(obj, slot, scene)
    if was_bare != (slot < 0) and obj.get("gb_kind") == 'REGION':
        try:
            rebuild(scene, [obj])
        except Exception as e:
            print("[Gingerbread] rebuild after bare change skipped:", e)


def set_style(scene, objs, style):
    """Set gb_style on regions/lines ('PUFFED'/'PAINTED' for regions; 'AUTO'/'RAISED'/'FLUSH' for
    lines; 'TOGGLE' flips between the two looks) and rebuild what changed."""
    changed = []
    for obj in objs:
        kind = obj.get("gb_kind")
        cur = obj.get("gb_style")
        if kind == 'REGION':
            new = {'TOGGLE': 'PUFFED' if cur == 'PAINTED' else 'PAINTED'}.get(style, style)
            if new not in core.REGION_STYLES:
                continue
        elif kind == 'LINES':
            if style == 'TOGGLE':
                key = ornament_key(obj)
                _, _, flush = core.resolve_styles(_ornament(scene, key), *current_styles(scene, key))
                new = 'RAISED' if int(obj["gb_label"]) in flush else 'FLUSH'
            else:
                new = {'PUFFED': 'RAISED', 'PAINTED': 'FLUSH'}.get(style, style)
            if new not in core.LINE_STYLES:
                continue
        else:
            continue
        if new != cur:
            obj["gb_style"] = new
            changed.append(obj)
    return rebuild(scene, changed), changed


# ----------------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------------

def object_tris_world(obj, depsgraph):
    eo = obj.evaluated_get(depsgraph)
    me = eo.to_mesh()
    try:
        me.calc_loop_triangles()
        nv = len(me.vertices)
        co = np.empty(nv * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(nv, 3)
        nt = len(me.loop_triangles)
        tri = np.empty(nt * 3, dtype=np.int64)
        me.loop_triangles.foreach_get("vertices", tri)
        tri = tri.reshape(nt, 3)
        m = np.array(obj.matrix_world)
        co = co @ m[:3, :3].T + m[:3, 3]
        return co, tri
    finally:
        eo.to_mesh_clear()


def _export_slots(scene):
    """(objects to print, remap slot -> 0-based extruder, filament colours). The remap is the union
    of the slots used by every printed part in the scene, so every ornament (and every file written
    from them) shares one filament list and one extruder numbering."""
    props = scene.gingerbread_props
    objs = [o for o in gingerbread_objects(scene) if o.get("gb_slot", 0) >= 0]
    nf = len(props.filaments)
    if nf == 0:
        return [], {}, []
    for o in objs:  # a slot past the end of the filament list (e.g. after undo) -> last filament
        if int(o.get("gb_slot", 0)) >= nf:
            o["gb_slot"] = nf - 1
    used = sorted({int(o.get("gb_slot", 0)) for o in objs})
    remap = {s: i for i, s in enumerate(used)}
    colours = [tuple(props.filaments[s].color) for s in used]
    return objs, remap, colours


def _export_part_list(objs, remap, depsgraph):
    parts = []
    order = {'COOKIE': 0, 'LINES': 1, 'REGION': 2}
    for o in sorted(objs, key=lambda o: (order.get(o.get("gb_kind"), 3), o.name)):
        v, t = object_tris_world(o, depsgraph)
        if len(t) == 0:
            continue
        parts.append(dict(name=o.name, verts=v, tris=t, extruder=remap[int(o.get("gb_slot", 0))] + 1))
    return parts


def collect_export_parts(context):
    """Return (parts, filament_colours) with extruders renumbered to the used slots."""
    objs, remap, colours = _export_slots(context.scene)
    if not colours:
        return [], []
    return _export_part_list(objs, remap, context.evaluated_depsgraph_get()), colours


def collect_export_ornaments(context):
    """Multi-image export: ([(title, parts), ...] in layout order, filament_colours). Every
    ornament's parts use the same extruder numbering (see _export_slots)."""
    scene = context.scene
    objs, remap, colours = _export_slots(scene)
    if not colours:
        return [], []
    depsgraph = context.evaluated_depsgraph_get()
    out = []
    for key in ornament_keys(scene):
        mine = [o for o in objs if ornament_key(o) == key]
        parts = _export_part_list(mine, remap, depsgraph)
        if parts:
            out.append((ornament_title(key) or scene.gingerbread_props.title or "Gingerbread Ornament", parts))
    return out, colours
