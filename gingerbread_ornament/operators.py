# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Craig Midwinter
"""
Operators for the Gingerbread Ornament add-on.
"""
import os
import re

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper
from bpy_extras import view3d_utils

from . import builder, threemf


def params_from_props(props):
    return dict(
        size_mm=props.size_mm,
        res_mm=props.res_mm,
        ink_threshold=props.ink_threshold,
        line_boost_mm=props.line_boost_mm,
        outline_smooth_mm=props.outline_smooth_mm,
        min_region_mm2=props.min_region_mm2,
        cookie_margin_mm=props.cookie_margin_mm,
        cookie_smooth_mm=props.cookie_smooth_mm,
        cookie_thickness_mm=props.cookie_thickness_mm,
        cookie_bevel_mm=props.cookie_bevel_mm,
        line_height_mm=props.line_height_mm,
        line_edge_mm=props.line_edge_mm,
        line_round_mm=props.line_round_mm,
        fill_height_mm=props.fill_height_mm,
        fill_edge_mm=props.fill_edge_mm,
        fill_round_mm=props.fill_round_mm,
        hole=props.hole,
        hole_diameter_mm=props.hole_diameter_mm,
        hole_ring_mm=props.hole_ring_mm,
        colour_merge=props.colour_merge,
        line_split=props.line_split,
        flush_height_mm=props.flush_height_mm,
        flush_edge_mm=props.flush_edge_mm,
        flush_round_mm=props.flush_round_mm,
        seamless=props.icing_look == 'SEAMLESS',
        max_filaments=props.max_filaments,
        geometry=2,
    )


class GINGERBREAD_OT_generate(Operator):
    """Build the cookie, piped icing and one part per enclosed region from the image(s)"""
    bl_idname = "gingerbread.generate"
    bl_label = "Generate Ornament"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.gingerbread_props
        if props.image_mode == 'MULTI':
            return self._execute_multi(context, props)
        line = props.line_image.strip()
        colour = props.colour_image.strip()
        for p in (line, colour):
            if p and not os.path.isfile(bpy.path.abspath(p)):
                self.report({'ERROR'}, "File not found: %s" % p)
                return {'CANCELLED'}
        try:
            builder.generate(context.scene, line, colour, params_from_props(props),
                             log=lambda m: print(m))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        n = len(builder.gingerbread_objects(context.scene))
        self.report({'INFO'}, "Generated %d parts" % n)
        return {'FINISHED'}

    def _execute_multi(self, context, props):
        entries = []
        for e in props.images:
            if not e.enabled:
                continue
            line, colour = e.line_image.strip(), e.colour_image.strip()
            if not line and not colour:
                continue
            for p in (line, colour):
                if p and not os.path.isfile(bpy.path.abspath(p)):
                    self.report({'ERROR'}, "%s: file not found: %s" % (e.title, p))
                    return {'CANCELLED'}
            entries.append((e.title, line, colour))
        if not entries:
            self.report({'ERROR'}, "Add images to the list (and tick them) first")
            return {'CANCELLED'}
        try:
            cols = builder.generate_multi(context.scene, entries, params_from_props(props), log=lambda m: print(m))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        n = len(builder.gingerbread_objects(context.scene))
        self.report({'INFO'}, "Generated %d ornaments, %d parts, %d shared filaments"
                    % (len(cols), n, len(props.filaments)))
        return {'FINISHED'}


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".tga", ".exr", ".hdr")


def title_from_path(path):
    """"snow_man-2.png" -> "Snow man 2"."""
    stem = os.path.splitext(os.path.basename(path))[0]
    t = re.sub(r"[_\-]+", " ", stem).strip()
    return t[:1].upper() + t[1:] if t else "Ornament"


class GINGERBREAD_OT_add_images(Operator):
    """Add line-art images (select several at once): each becomes one ornament"""
    bl_idname = "gingerbread.add_images"
    bl_label = "Add Images"
    bl_options = {'REGISTER', 'UNDO'}

    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    filter_image: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        props = context.scene.gingerbread_props
        added = 0
        for f in self.files:
            if not f.name or not f.name.lower().endswith(IMAGE_EXTS):
                continue
            e = props.images.add()
            e.line_image = os.path.join(self.directory, f.name)
            e.title = title_from_path(f.name)
            added += 1
        if not added:
            self.report({'WARNING'}, "No images selected")
            return {'CANCELLED'}
        props.active_image = len(props.images) - 1
        props.image_mode = 'MULTI'
        self.report({'INFO'}, "Added %d image(s)" % added)
        return {'FINISHED'}


class GINGERBREAD_OT_remove_image(Operator):
    """Remove the selected image from the list"""
    bl_idname = "gingerbread.remove_image"
    bl_label = "Remove Image"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.gingerbread_props
        i = props.active_image
        if not 0 <= i < len(props.images):
            return {'CANCELLED'}
        props.images.remove(i)
        props.active_image = max(0, min(i, len(props.images) - 1))
        return {'FINISHED'}


class GINGERBREAD_OT_move_image(Operator):
    """Move the selected image up or down (the list order is the left-to-right layout order)"""
    bl_idname = "gingerbread.move_image"
    bl_label = "Move Image"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")], default='UP')

    def execute(self, context):
        props = context.scene.gingerbread_props
        i = props.active_image
        j = i - 1 if self.direction == 'UP' else i + 1
        if not (0 <= i < len(props.images) and 0 <= j < len(props.images)):
            return {'CANCELLED'}
        props.images.move(i, j)
        props.active_image = j
        return {'FINISHED'}


class GINGERBREAD_OT_assign_slot(Operator):
    """Give the selected regions this filament colour (-1 = leave as bare cookie)"""
    bl_idname = "gingerbread.assign_slot"
    bl_label = "Assign Filament"
    bl_options = {'REGISTER', 'UNDO'}

    slot: IntProperty(default=0)

    def execute(self, context):
        objs = [o for o in context.selected_objects if "gb_kind" in o]
        if not objs:
            self.report({'WARNING'}, "Select one or more Gingerbread parts first (click a region)")
            return {'CANCELLED'}
        for o in objs:
            if self.slot < 0 and o.get("gb_kind") != 'REGION':
                continue
            builder.set_slot(context.scene, o, self.slot)
        if self.slot >= 0:
            context.scene.gingerbread_props.active_filament = self.slot
        return {'FINISHED'}


NEW_COLOURS = [(0.90, 0.10, 0.10), (0.10, 0.35, 0.90), (0.15, 0.70, 0.20), (1.00, 0.80, 0.10),
               (0.55, 0.20, 0.75), (1.00, 0.50, 0.10), (0.95, 0.55, 0.70), (0.10, 0.10, 0.10),
               (0.40, 0.80, 0.95), (0.45, 0.25, 0.10)]


def next_colour(used):
    """First preset colour not already close to an existing filament."""
    for c in NEW_COLOURS:
        if all(sum((a - b) ** 2 for a, b in zip(c, u)) > 0.06 for u in used):
            return c
    return NEW_COLOURS[len(used) % len(NEW_COLOURS)]


class GINGERBREAD_OT_add_filament(Operator):
    """Add a filament and start colouring regions with it (click regions in the viewport)"""
    bl_idname = "gingerbread.add_filament"
    bl_label = "Add Filament"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.gingerbread_props
        used = [tuple(f.color) for f in props.filaments]
        f = props.filaments.add()
        f.name = "Colour %d" % (len(props.filaments) - 2)
        f.color = next_colour(used)
        props.active_filament = len(props.filaments) - 1
        builder.slot_material(props.active_filament, tuple(f.color))
        # Straight into colouring mode with the new filament (or just switch to it if already there).
        _start_painting(context)
        _update_status(context)
        _redraw_all()
        return {'FINISHED'}


class GINGERBREAD_OT_select_slot(Operator):
    """Select every part that uses this filament"""
    bl_idname = "gingerbread.select_slot"
    bl_label = "Select Parts"
    bl_options = {'REGISTER', 'UNDO'}

    slot: IntProperty(default=0)

    def execute(self, context):
        for o in context.view_layer.objects:
            o.select_set(False)
        for o in builder.gingerbread_objects(context.scene):
            if int(o.get("gb_slot", 0)) == self.slot:
                o.select_set(True)
                context.view_layer.objects.active = o
        return {'FINISHED'}


# ---------------------------------------------------------------- colouring mode
# One colouring session at a time. The state lives at module level so the panel can show it,
# the panel's Stop button can end it, and loading a file clears it.
_PAINT = {"op": None, "draw": None, "window": None, "cursor": False}
NUMBER_KEYS = {k: i for i, k in enumerate(
    ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"))}
NUMBER_KEYS.update({"NUMPAD_%d" % (i + 1): i for i in range(9)})
STATUS_TEXT = ("Gingerbread colouring: click a region = paint with %s | Shift-click = bare cookie | "
               "Alt-click = pick its colour | Ctrl-click = puffed/painted | 1-9 = switch filament | Esc / Right-click = done")


def is_painting():
    return _PAINT["op"] is not None


def _redraw_all():
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _active_name(props):
    i = props.active_filament
    if 0 <= i < len(props.filaments):
        return "%s (#%d)" % (props.filaments[i].name, i + 1)
    return "?"


def _update_status(context):
    if not is_painting():
        return
    try:
        context.workspace.status_text_set(STATUS_TEXT % _active_name(context.scene.gingerbread_props))
    except Exception:
        pass


def stop_painting(context=None):
    """End colouring mode from anywhere (Esc, right-click, the panel button, file load)."""
    if _PAINT["draw"] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_PAINT["draw"], 'WINDOW')
        except Exception:
            pass
    win = _PAINT["window"]
    if _PAINT["cursor"] and win is not None:
        try:
            win.cursor_modal_restore()
        except Exception:
            pass
    try:
        (context or bpy.context).workspace.status_text_set(None)
    except Exception:
        pass
    _PAINT.update(op=None, draw=None, window=None, cursor=False)
    try:
        _redraw_all()
    except Exception:
        pass


def _view3d_under_mouse(context, event):
    """(area, window_region) if the mouse is over the open part of a 3D viewport, else None.
    The sidebar, toolbar and headers don't count, so panel clicks pass straight through."""
    mx, my = event.mouse_x, event.mouse_y
    for area in context.window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        if not (area.x <= mx < area.x + area.width and area.y <= my < area.y + area.height):
            continue
        win = None
        for r in area.regions:
            if r.type == 'WINDOW':
                win = r
            elif r.width > 1 and r.height > 1 and r.x <= mx < r.x + r.width and r.y <= my < r.y + r.height:
                return None
        if win is not None and win.x <= mx < win.x + win.width and win.y <= my < win.y + win.height:
            return area, win
        return None
    return None


def _insets(area, win):
    """How much of the viewport the sidebar / toolbar / headers cover (region overlap)."""
    left = right = top = 0
    for r in area.regions:
        if r.type == 'WINDOW' or r.width <= 1 or r.height <= 1:
            continue
        if r.x + r.width <= win.x or r.x >= win.x + win.width or r.y + r.height <= win.y or r.y >= win.y + win.height:
            continue
        if r.height > win.height * 0.5:
            if r.x > win.x + win.width * 0.5:
                right = max(right, win.x + win.width - r.x)
            else:
                left = max(left, r.x + r.width - win.x)
        elif r.y > win.y + win.height * 0.5:
            top = max(top, win.y + win.height - r.y)
    return left, right, top


def _draw_overlay():
    """Viewport indicator: an orange frame plus a banner naming the active filament."""
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader

    ctx = bpy.context
    area, win = ctx.area, ctx.region
    if area is None or win is None or not hasattr(ctx.scene, "gingerbread_props"):
        return
    props = ctx.scene.gingerbread_props
    s = ctx.preferences.system.ui_scale
    left, right, top = _insets(area, win)
    x0, x1, y1 = left, win.width - right, win.height - top
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    def rect(a, b, c, d, colour):
        batch = batch_for_shader(shader, 'TRIS', {"pos": [(a, b), (c, b), (c, d), (a, d)]},
                                 indices=((0, 1, 2), (0, 2, 3)))
        shader.uniform_float("color", colour)
        batch.draw(shader)

    frame = (1.0, 0.55, 0.1, 0.95)
    t = 4 * s
    rect(x0, 0, x1, t, frame)
    rect(x0, y1 - t, x1, y1, frame)
    rect(x0, 0, x0 + t, y1, frame)
    rect(x1 - t, 0, x1, y1, frame)

    i = props.active_filament
    has = 0 <= i < len(props.filaments)
    rgb = tuple(props.filaments[i].color) if has else (0.5, 0.5, 0.5)
    title = "COLOURING MODE   painting with  %s" % (_active_name(props) if has else "?")
    if props.paint_style != 'KEEP':
        title += "   (%s)" % props.paint_style.title()
    hint = ("Click = paint   Shift-click = bare cookie   Alt-click = pick colour   Ctrl-click = puffed / painted   "
            "1-9 = switch   Esc / Right-click = done")
    blf.size(0, 17 * s)
    tw, th = blf.dimensions(0, title)
    blf.size(0, 12 * s)
    hw, hh = blf.dimensions(0, hint)
    sw = 20 * s
    pad = 10 * s
    width = max(tw + sw + pad, hw) + 2 * pad
    height = th + hh + 3 * pad
    cx = (x0 + x1) / 2
    bx0 = max(x0 + t, cx - width / 2)
    by1 = y1 - t - 8 * s
    by0 = by1 - height
    rect(bx0, by0, bx0 + width, by1, (0.08, 0.08, 0.08, 0.88))
    rect(bx0, by1 - 3 * s, bx0 + width, by1, frame)
    # swatch of the active filament, with a light outline so dark colours still show
    sy1 = by1 - pad
    sy0 = sy1 - sw
    rect(bx0 + pad - 1.5 * s, sy0 - 1.5 * s, bx0 + pad + sw + 1.5 * s, sy1 + 1.5 * s, (0.9, 0.9, 0.9, 1))
    rect(bx0 + pad, sy0, bx0 + pad + sw, sy1, (*rgb, 1.0))
    blf.size(0, 17 * s)
    blf.color(0, 1, 1, 1, 1)
    blf.position(0, bx0 + 2 * pad + sw, sy0 + (sw - th) / 2 + 2 * s, 0)
    blf.draw(0, title)
    blf.size(0, 12 * s)
    blf.color(0, 0.85, 0.85, 0.85, 1)
    blf.position(0, bx0 + pad, by0 + pad, 0)
    blf.draw(0, hint)
    gpu.state.blend_set('NONE')


class GINGERBREAD_OT_paint(Operator):
    """Colouring mode: click regions in the viewport to give them the active filament.
    Shift-click: bare cookie. Alt-click: pick a region's colour. 1-9: switch filament. Esc / right-click: done.
    The panel stays usable, so you can add or switch filaments without leaving the mode"""
    bl_idname = "gingerbread.paint"
    bl_label = "Click to Colour Regions"

    def _hit(self, context, region, event):
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        rv3d = region.data
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        depsgraph = context.evaluated_depsgraph_get()
        hit, loc, nrm, idx, obj, mat = context.scene.ray_cast(depsgraph, origin, direction)
        if hit and obj is not None:
            return bpy.data.objects.get(obj.name)
        return None

    def _cursor(self, context, over):
        if over and not _PAINT["cursor"]:
            context.window.cursor_modal_set('PAINT_BRUSH')
            _PAINT["cursor"] = True
        elif not over and _PAINT["cursor"]:
            context.window.cursor_modal_restore()
            _PAINT["cursor"] = False

    def _finish(self, context):
        stop_painting(context)
        return {'FINISHED'}

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception:
            # Never leave the mode half-on: if anything goes wrong, end it cleanly.
            import traceback
            traceback.print_exc()
            stop_painting(context)
            return {'CANCELLED'}

    def _modal(self, context, event):
        if _PAINT["op"] is not self:  # stopped from the panel, or a newer session took over
            return {'FINISHED'}
        if event.type == 'ESC' and event.value == 'PRESS':
            return self._finish(context)
        over = _view3d_under_mouse(context, event)
        self._cursor(context, over is not None)
        if over is None:
            return {'PASS_THROUGH'}  # sidebar, headers, other editors keep working
        props = context.scene.gingerbread_props
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            return self._finish(context)
        if (event.type in NUMBER_KEYS and event.value == 'PRESS'
                and not (event.ctrl or event.alt or event.oskey or event.shift)):
            i = NUMBER_KEYS[event.type]
            if i < len(props.filaments):
                props.active_filament = i
                _update_status(context)
                _redraw_all()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            obj = self._hit(context, over[1], event)
            if obj is None or "gb_kind" not in obj:
                return {'PASS_THROUGH'}  # gizmos, empty space, other objects
            if event.alt:
                s = int(obj.get("gb_slot", 0))
                if 0 <= s < len(props.filaments):
                    props.active_filament = s
                    _update_status(context)
                    _redraw_all()
                return {'RUNNING_MODAL'}
            if event.ctrl or event.oskey:
                try:
                    n, changed = builder.set_style(context.scene, [obj], 'TOGGLE')
                    if changed:
                        self.report({'INFO'}, "%s -> %s" % (obj.name, obj.get("gb_style", "").title()))
                except Exception as e:
                    self.report({'WARNING'}, "Style change failed: %s" % e)
                try:
                    bpy.ops.ed.undo_push(message="Gingerbread: style %s" % obj.name)
                except Exception:
                    pass
                _redraw_all()
                return {'RUNNING_MODAL'}
            slot = -1 if event.shift else props.active_filament
            if slot < 0 and obj.get("gb_kind") != 'REGION':
                self.report({'INFO'}, "Only enclosed regions can be bare cookie")
                return {'RUNNING_MODAL'}
            if slot >= len(props.filaments):
                return {'RUNNING_MODAL'}
            builder.set_slot(context.scene, obj, slot)
            if slot >= 0 and props.paint_style != 'KEEP':
                try:
                    builder.set_style(context.scene, [obj], props.paint_style)
                except Exception as e:
                    self.report({'WARNING'}, "Style change failed: %s" % e)
            for o in context.selected_objects:
                o.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            try:
                bpy.ops.ed.undo_push(message="Gingerbread: colour %s" % obj.name)
            except Exception:
                pass
            _redraw_all()
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        if is_painting():  # the button is a toggle
            stop_painting(context)
            return {'FINISHED'}
        if context.window is None:
            return {'CANCELLED'}
        if not builder.gingerbread_objects(context.scene):
            self.report({'WARNING'}, "Generate the ornament first")
            return {'CANCELLED'}
        props = context.scene.gingerbread_props
        if not 0 <= props.active_filament < len(props.filaments):
            props.active_filament = min(1, len(props.filaments) - 1)
        context.window_manager.modal_handler_add(self)
        _PAINT.update(op=self, window=context.window, cursor=False,
                      draw=bpy.types.SpaceView3D.draw_handler_add(_draw_overlay, (), 'WINDOW', 'POST_PIXEL'))
        _update_status(context)
        _redraw_all()
        return {'RUNNING_MODAL'}


def _start_painting(context):
    if not is_painting() and builder.gingerbread_objects(context.scene) and context.window is not None:
        try:
            bpy.ops.gingerbread.paint('INVOKE_DEFAULT')
        except Exception as e:
            print("[Gingerbread] could not start colouring mode:", e)


class GINGERBREAD_OT_set_active_filament(Operator):
    """Paint with this filament: makes it active and starts colouring mode (click regions in the viewport)"""
    bl_idname = "gingerbread.set_active_filament"
    bl_label = "Paint With Filament"

    slot: IntProperty(default=0)

    def execute(self, context):
        props = context.scene.gingerbread_props
        if not 0 <= self.slot < len(props.filaments):
            return {'CANCELLED'}
        props.active_filament = self.slot
        _start_painting(context)
        _update_status(context)
        _redraw_all()
        return {'FINISHED'}


class GINGERBREAD_OT_stop_painting(Operator):
    """Leave colouring mode (same as Esc or right-click in the viewport)"""
    bl_idname = "gingerbread.stop_painting"
    bl_label = "Stop Colouring"

    def execute(self, context):
        stop_painting(context)
        return {'FINISHED'}


STYLE_ITEMS = [
    ('PUFFED', "Puffed", "Region: raised, domed flood icing in its own colour (lines stay raised)"),
    ('PAINTED', "Painted", "Region: flush with its outline, one flat painted-looking surface (lines next to it go flush)"),
    ('AUTO', "Auto", "Line: flush when every coloured region it touches is painted, otherwise raised"),
    ('RAISED', "Raised", "Line: always a raised piped bead"),
    ('FLUSH', "Flush", "Line: flat, level with the painted surface"),
    ('TOGGLE', "Toggle", "Switch between puffed/raised and painted/flush"),
]


class GINGERBREAD_OT_set_style(Operator):
    """Set the icing style of the selected regions / lines"""
    bl_idname = "gingerbread.set_style"
    bl_label = "Set Icing Style"
    bl_options = {'REGISTER', 'UNDO'}

    style: EnumProperty(items=STYLE_ITEMS, default='TOGGLE')

    def execute(self, context):
        objs = [o for o in context.selected_objects if o.get("gb_kind") in ('REGION', 'LINES')]
        if not objs:
            self.report({'WARNING'}, "Select regions or lines first (or Ctrl-click them in colouring mode)")
            return {'CANCELLED'}
        try:
            n, changed = builder.set_style(context.scene, objs, self.style)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, "%d part(s) restyled, %d rebuilt" % (len(changed), n))
        return {'FINISHED'}


class GINGERBREAD_OT_apply_look(Operator):
    """Give every region the Icing Look (puffed or painted) and set every line back to Auto"""
    bl_idname = "gingerbread.apply_look"
    bl_label = "Apply Look to All"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        look = scene.gingerbread_props.icing_look
        objs = builder.gingerbread_objects(scene)
        seamless = look == 'SEAMLESS'
        look = 'PAINTED' if seamless else look
        regs = [o for o in objs if o.get("gb_kind") == 'REGION']
        lines = [o for o in objs if o.get("gb_kind") == 'LINES']
        if not regs and not lines:
            self.report({'WARNING'}, "Generate the ornament first")
            return {'CANCELLED'}
        try:
            builder.set_seamless(scene, seamless)
            for o in regs:
                o["gb_style"] = look
            for o in lines:
                o["gb_style"] = 'AUTO'
            n = builder.rebuild(scene, regs + lines)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, "%s look applied, %d parts rebuilt"
                    % ("Seamless" if seamless else look.title(), n))
        return {'FINISHED'}


class GINGERBREAD_OT_export_3mf(Operator, ExportHelper):
    """Export the ornament as a multi-colour 3MF (one part per colour region, Bambu Studio ready)"""
    bl_idname = "gingerbread.export_3mf"
    bl_label = "Export 3MF"
    filename_ext = ".3mf"
    filter_glob: StringProperty(default="*.3mf", options={'HIDDEN'})

    def execute(self, context):
        props = context.scene.gingerbread_props
        try:
            parts, colours = builder.collect_export_parts(context)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, "Export failed while collecting parts: %s" % e)
            return {'CANCELLED'}
        if not parts:
            self.report({'ERROR'}, "Nothing to export: generate an ornament first")
            return {'CANCELLED'}
        tpl = props.bambu_template.strip()
        tpl = os.path.expanduser(bpy.path.abspath(tpl)) if tpl else None
        warnings = []
        try:
            threemf.write_3mf(self.filepath, parts, colours, title=props.title or "Gingerbread Ornament",
                              template_3mf=tpl, warnings=warnings)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, "Export failed: %s" % e)
            return {'CANCELLED'}
        for w in warnings:
            self.report({'WARNING'}, w)
        self.report({'INFO'}, "Exported %d parts, %d filaments -> %s" % (len(parts), len(colours), self.filepath))
        return {'FINISHED'}


# ---------------------------------------------------------------- multi-image export

def _template_path(props):
    tpl = props.bambu_template.strip()
    return os.path.expanduser(bpy.path.abspath(tpl)) if tpl else None


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s or "ornament"


def _collect_ornaments(op, context):
    try:
        orns, colours = builder.collect_export_ornaments(context)
    except Exception as e:
        import traceback
        traceback.print_exc()
        op.report({'ERROR'}, "Export failed while collecting parts: %s" % e)
        return None, None
    if not orns:
        op.report({'ERROR'}, "Nothing to export: generate the ornaments first")
        return None, None
    return orns, colours


class GINGERBREAD_OT_export_plate(Operator, ExportHelper):
    """Export every ornament together on one plate as one multi-colour 3MF (same filaments for all)"""
    bl_idname = "gingerbread.export_plate"
    bl_label = "Export Plate 3MF"
    filename_ext = ".3mf"
    filter_glob: StringProperty(default="*.3mf", options={'HIDDEN'})

    def execute(self, context):
        props = context.scene.gingerbread_props
        if not hasattr(threemf, "write_3mf_plate"):
            self.report({'ERROR'}, "This version of the add-on can't write plate files")
            return {'CANCELLED'}
        orns, colours = _collect_ornaments(self, context)
        if orns is None:
            return {'CANCELLED'}
        objects = [dict(name=t, parts=parts) for t, parts in orns]
        warnings = []
        try:
            threemf.write_3mf_plate(self.filepath, objects, colours,
                                    title=props.title or "Gingerbread Ornaments",
                                    template_3mf=_template_path(props), warnings=warnings)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, "Export failed: %s" % e)
            return {'CANCELLED'}
        for w in warnings:
            self.report({'WARNING'}, w)
        self.report({'INFO'}, "Exported %d ornaments, %d filaments -> %s"
                    % (len(objects), len(colours), self.filepath))
        return {'FINISHED'}


class GINGERBREAD_OT_export_each(Operator):
    """Export one 3MF per ornament into a folder (file name = ornament title). Every file gets the
    same filament list and slot numbers, so they all print with the same AMS setup"""
    bl_idname = "gingerbread.export_each"
    bl_label = "Export Each 3MF"

    directory: StringProperty(name="Folder", subtype='DIR_PATH')
    filter_folder: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        props = context.scene.gingerbread_props
        folder = bpy.path.abspath(self.directory) if self.directory else ""
        if not folder or not os.path.isdir(folder):
            self.report({'ERROR'}, "Pick a folder to export into")
            return {'CANCELLED'}
        orns, colours = _collect_ornaments(self, context)
        if orns is None:
            return {'CANCELLED'}
        tpl = _template_path(props)
        warnings, written, used = [], [], set()
        for title, parts in orns:
            slug, n = slugify(title), 2
            name = slug
            while name in used:
                name = "%s-%d" % (slug, n)
                n += 1
            used.add(name)
            path = os.path.join(folder, name + ".3mf")
            try:
                threemf.write_3mf(path, parts, colours, title=title, template_3mf=tpl, warnings=warnings)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.report({'ERROR'}, "Export of %s failed: %s" % (title, e))
                return {'CANCELLED'}
            written.append(path)
        for w in dict.fromkeys(warnings):   # the same template warning once, not once per file
            self.report({'WARNING'}, w)
        self.report({'INFO'}, "Exported %d files, %d filaments each -> %s" % (len(written), len(colours), folder))
        return {'FINISHED'}
