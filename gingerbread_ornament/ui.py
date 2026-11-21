# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Craig Midwinter
"""
Properties and sidebar panel (View3D > Sidebar > Gingerbread).
"""
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, StringProperty)
from bpy.types import Panel, PropertyGroup, UIList

from . import builder
from .operators import (GINGERBREAD_OT_generate, GINGERBREAD_OT_assign_slot, GINGERBREAD_OT_add_filament,
                        GINGERBREAD_OT_select_slot, GINGERBREAD_OT_paint, GINGERBREAD_OT_export_3mf,
                        GINGERBREAD_OT_set_active_filament, GINGERBREAD_OT_stop_painting, is_painting,
                        GINGERBREAD_OT_set_style, GINGERBREAD_OT_apply_look, GINGERBREAD_OT_add_images,
                        GINGERBREAD_OT_remove_image, GINGERBREAD_OT_move_image, GINGERBREAD_OT_export_plate,
                        GINGERBREAD_OT_export_each)


def _filament_changed(self, context):
    try:
        builder.sync_palette_materials(context.scene)
    except Exception as e:
        print("[Gingerbread] palette sync failed:", e)


class GINGERBREAD_Filament(PropertyGroup):
    name: StringProperty(name="Name", default="Colour")
    color: FloatVectorProperty(name="Colour", subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
                               default=(1.0, 1.0, 1.0), update=_filament_changed)


class GINGERBREAD_ImageEntry(PropertyGroup):
    """One image in multi-image mode: becomes one ornament."""
    line_image: StringProperty(name="Line Art", description="Black line-art / colouring page image",
                               subtype='FILE_PATH', default="")
    colour_image: StringProperty(name="Coloured (optional)",
                                 description="Same image coloured in: each enclosed area takes its colour from here",
                                 subtype='FILE_PATH', default="")
    title: StringProperty(name="Title", description="Ornament name: used for its parts, its collection and "
                                                    "its 3MF file name", default="Ornament")
    enabled: BoolProperty(name="Include", description="Generate this image", default=True)


class GINGERBREAD_UL_images(UIList):
    bl_idname = "GINGERBREAD_UL_images"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.prop(item, "title", text="", emboss=False, icon='IMAGE_DATA')
        if item.colour_image.strip():
            row.label(text="", icon='COLOR')


def mm(name, desc, default, lo, hi, step=10):
    return FloatProperty(name=name, description=desc, default=default, min=lo, max=hi, step=step, precision=2)


class GINGERBREAD_Properties(PropertyGroup):
    line_image: StringProperty(name="Line Art", description="Black line-art / colouring page image",
                               subtype='FILE_PATH', default="")
    colour_image: StringProperty(name="Coloured (optional)",
                                 description="Same image coloured in: each enclosed area takes its colour from here. "
                                             "White areas stay bare cookie",
                                 subtype='FILE_PATH', default="")
    title: StringProperty(name="Title", default="Gingerbread Ornament")
    image_mode: EnumProperty(
        name="Images",
        description="One ornament from one image, or several ornaments (one per image) sharing one "
                    "filament palette",
        items=[('SINGLE', "One Image", "One ornament from one line-art image"),
               ('MULTI', "Several Images", "One ornament per image, all in one scene with one shared set of "
                                           "filaments; export them one file each or together on one plate")],
        default='SINGLE')
    images: CollectionProperty(type=GINGERBREAD_ImageEntry)
    active_image: IntProperty(name="Active Image", default=0, min=0)

    size_mm: mm("Size (mm)", "Longest side of the whole finished ornament, hanging-hole tab included", 80.0, 20.0, 250.0, 100)
    res_mm: mm("Detail (mm/px)", "Working grid resolution; smaller = finer but heavier mesh", 0.15, 0.05, 0.5, 1)
    ink_threshold: FloatProperty(name="Line Threshold", description="Pixels darker than this are lines",
                                 default=0.5, min=0.05, max=0.95)
    line_boost_mm: mm("Line Thicken (mm)", "Grow every line by this much per side so the icing is printable",
                      0.30, 0.0, 2.0, 5)
    outline_smooth_mm: mm("Line Smoothing (mm)",
                          "Rounds off pixel stair-steps in the line outlines (bigger = smoother, softer corners; "
                          "0 = follow the pixels exactly). Low-res images are also interpolated when this is on",
                          0.15, 0.0, 1.0, 5)
    min_region_mm2: mm("Min Region (mm²)", "Smaller enclosed areas are filled with icing instead", 0.8, 0.0, 50.0, 10)

    cookie_thickness_mm: mm("Cookie Thickness", "", 4.0, 1.0, 15.0)
    cookie_margin_mm: mm("Cookie Margin", "Cookie edge beyond the outermost icing line", 2.2, 0.5, 15.0)
    cookie_smooth_mm: mm("Outline Smoothing", "Rounds off notches in the cookie outline", 2.5, 0.0, 15.0)
    cookie_bevel_mm: mm("Cookie Edge Round", "Radius of the baked, rounded top edge", 1.6, 0.0, 6.0)

    line_height_mm: mm("Piping Height", "Height of piped icing lines above the cookie", 1.2, 0.2, 5.0)
    line_edge_mm: mm("Piping Edge Height", "Height at the edge of the piped bead", 0.3, 0.1, 3.0)
    line_round_mm: mm("Piping Roundness", "Horizontal radius of the bead's rounded top", 0.6, 0.05, 3.0)
    fill_height_mm: mm("Flood Height", "Height of coloured flood-icing regions", 0.8, 0.2, 5.0)
    fill_edge_mm: mm("Flood Edge Height", "", 0.4, 0.1, 3.0)
    fill_round_mm: mm("Flood Roundness", "", 0.9, 0.05, 5.0)

    hole: BoolProperty(name="Hanging Hole", default=True)
    hole_diameter_mm: mm("Hole Diameter", "", 4.5, 1.0, 15.0)
    hole_ring_mm: mm("Hole Wall", "Cookie wall around the hole", 2.6, 1.0, 10.0)

    colour_merge: FloatProperty(name="Colour Merge", description="Region colours closer than this share a filament",
                                default=0.18, min=0.0, max=1.0)
    cookie_color: FloatVectorProperty(name="Cookie", subtype='COLOR_GAMMA', size=3, min=0, max=1,
                                      default=(0.682, 0.514, 0.357))
    icing_color: FloatVectorProperty(name="Icing", subtype='COLOR_GAMMA', size=3, min=0, max=1,
                                     default=(1.0, 1.0, 1.0))

    line_split: EnumProperty(
        name="Icing Lines",
        description="How the piped icing lines are split into parts you can colour",
        items=[('STROKES', "Each Stroke", "Cut lines where they meet: every stroke is its own part "
                                         "(an outline running through a junction stays one stroke)"),
               ('PIECES', "Connected Pieces", "One part per group of lines that touch each other"),
               ('ONE', "One Part", "All icing lines are a single part")],
        default='STROKES')
    max_filaments: IntProperty(name="Max Filaments",
                               description="Merge the most similar colours until the ornament fits this many "
                                           "filaments (4 = one AMS, 8 = two). Also the limit for the 'filaments in use' warning. "
                                           "0 = no limit (warns above 4)", default=0, min=0, max=16)
    icing_look: EnumProperty(
        name="Icing Look",
        description="How coloured regions are iced when the ornament is generated (change single regions later "
                    "with Ctrl-click in colouring mode)",
        items=[('PUFFED', "Puffed", "Each coloured region is its own raised, domed flood section; "
                                    "the piped outlines stand above it"),
               ('PAINTED', "Painted", "Coloured regions are flush with their outlines: one flat surface that "
                                      "looks painted, outlines don't pop above it; edges round off at bare cookie"),
               ('SEAMLESS', "Seamless", "The whole iced area is one continuous flat surface: every region and "
                                        "every line at exactly the same height, no domes, ridges or seams; "
                                        "colour changes only (like an inlaid glaze)")],
        default='PUFFED')
    flush_height_mm: mm("Painted Height", "Height of the flat painted surface above the cookie", 0.8, 0.2, 3.0)
    flush_edge_mm: mm("Painted Edge Height", "Height where the painted surface meets bare cookie", 0.4, 0.0, 3.0)
    flush_round_mm: mm("Painted Edge Round", "Width of the rounded edge where painted icing meets bare cookie",
                       0.4, 0.05, 3.0)
    paint_style: EnumProperty(
        name="Click Also Sets",
        description="In colouring mode, a click can also set the region's style",
        items=[('KEEP', "Colour Only", "Clicking only changes the colour"),
               ('PUFFED', "Puffed", "Clicked regions also become puffed (lines raised)"),
               ('PAINTED', "Painted", "Clicked regions also become painted/flush (lines flush)")],
        default='KEEP')
    filaments: CollectionProperty(type=GINGERBREAD_Filament)
    active_filament: IntProperty(name="Active Filament", default=1, min=0)
    bambu_template: StringProperty(
        name="Printer Settings From",
        description="OPTIONAL, and NOT the output file (you name that when you click Export). Pick an existing 3MF "
                    "that Bambu Studio saved for your printer to copy its printer and filament presets. Leave empty "
                    "to use the built-in Bambu Lab P1S settings. Either way Bambu Studio opens the export with every "
                    "filament and colour in place",
        subtype='FILE_PATH', default="")
    show_advanced: BoolProperty(name="Advanced", default=False)


def _filament_row(layout, props):
    i = props.active_filament
    if 0 <= i < len(props.filaments):
        f = props.filaments[i]
        row = layout.row(align=True)
        row.label(text="Painting with  %d" % (i + 1))
        row.prop(f, "color", text="")
        row.label(text=f.name)


def template_status(path):
    """(message, ok) for the Bambu Template field, shown live under it."""
    import os
    import zipfile
    path = (path or "").strip()
    if not path:
        return "Built-in Bambu Lab P1S settings + your filament colours", True
    full = os.path.expanduser(bpy.path.abspath(path))
    if os.path.isdir(full):
        return "That's a folder: pick a .3mf saved by Bambu Studio (built-in P1S used)", False
    if not os.path.isfile(full):
        return "File not found: built-in P1S settings will be used", False
    if not full.lower().endswith(".3mf"):
        return "Not a .3mf file: built-in P1S settings will be used", False
    try:
        with zipfile.ZipFile(full) as z:
            if "Metadata/project_settings.config" not in z.namelist():
                return "No printer settings in that 3MF: built-in P1S used", False
    except Exception:
        return "Not a readable 3MF: built-in P1S settings will be used", False
    return "Printer + filament presets copied from %s" % os.path.basename(full), True


class GINGERBREAD_PT_panel(Panel):
    bl_label = "Gingerbread Ornament"
    bl_idname = "GINGERBREAD_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Gingerbread"

    @staticmethod
    def _draw_painting_banner(layout, props):
        box = layout.box()
        col = box.column()
        col.alert = True
        col.label(text="COLOURING MODE ON", icon='BRUSH_DATA')
        _filament_row(box, props)
        col = box.column(align=True)
        col.label(text="Click region: paint   Shift-click: bare cookie")
        col.label(text="Alt-click: pick colour   1-9: switch filament")
        col.label(text="Ctrl-click: puffed ⇄ painted")
        row = box.row()
        row.scale_y = 1.4
        row.alert = True
        row.operator(GINGERBREAD_OT_stop_painting.bl_idname, text="Stop Colouring  (Esc / Right-click)", icon='CANCEL')

    @staticmethod
    def _draw_image_list(box, props):
        row = box.row()
        row.template_list(GINGERBREAD_UL_images.bl_idname, "", props, "images", props, "active_image", rows=4)
        col = row.column(align=True)
        col.operator(GINGERBREAD_OT_add_images.bl_idname, text="", icon='ADD')
        col.operator(GINGERBREAD_OT_remove_image.bl_idname, text="", icon='REMOVE')
        col.separator()
        col.operator(GINGERBREAD_OT_move_image.bl_idname, text="", icon='TRIA_UP').direction = 'UP'
        col.operator(GINGERBREAD_OT_move_image.bl_idname, text="", icon='TRIA_DOWN').direction = 'DOWN'
        if len(props.images) == 0:
            box.label(text="Click + to add line-art images (pick several)", icon='INFO')
        elif 0 <= props.active_image < len(props.images):
            e = props.images[props.active_image]
            col = box.column(align=True)
            col.prop(e, "title")
            col.prop(e, "line_image")
            col.prop(e, "colour_image")
        n = sum(1 for e in props.images if e.enabled)
        if props.images:
            box.label(text="%d of %d images ticked: one ornament each, shared filaments" % (n, len(props.images)))

    def draw(self, context):
        layout = self.layout
        props = context.scene.gingerbread_props
        painting = is_painting()
        if painting:
            self._draw_painting_banner(layout, props)

        box = layout.box()
        box.label(text="1. Images", icon='IMAGE_DATA')
        row = box.row(align=True)
        row.prop(props, "image_mode", expand=True)
        multi = props.image_mode == 'MULTI'
        if multi:
            self._draw_image_list(box, props)
        else:
            box.prop(props, "line_image")
            box.prop(props, "colour_image")

        box = layout.box()
        box.label(text="2. Shape", icon='MESH_DATA')
        col = box.column(align=True)
        col.prop(props, "size_mm")
        col.prop(props, "cookie_thickness_mm")
        col.prop(props, "cookie_bevel_mm")
        col.prop(props, "line_height_mm")
        col.prop(props, "fill_height_mm")
        col.prop(props, "line_boost_mm")
        col.prop(props, "outline_smooth_mm")
        row = box.row()
        row.prop(props, "hole")
        if props.hole:
            row.prop(props, "hole_diameter_mm", text="Ø")
        row = box.row(align=True)
        row.prop(props, "max_filaments")
        box.prop(props, "line_split")
        row = box.row(align=True)
        row.prop(props, "icing_look", expand=True)
        if props.icing_look in ('PAINTED', 'SEAMLESS'):
            box.prop(props, "flush_height_mm")
        row = box.row(align=True)
        row.prop(props, "cookie_color")
        row.prop(props, "icing_color")
        box.prop(props, "show_advanced", icon='TRIA_DOWN' if props.show_advanced else 'TRIA_RIGHT')
        if props.show_advanced:
            col = box.column(align=True)
            for p in ("res_mm", "ink_threshold", "min_region_mm2", "cookie_margin_mm", "cookie_smooth_mm",
                      "line_edge_mm", "line_round_mm", "fill_edge_mm", "fill_round_mm", "hole_ring_mm",
                      "flush_height_mm", "flush_edge_mm", "flush_round_mm", "colour_merge"):
                col.prop(props, p)
        layout.operator(GINGERBREAD_OT_generate.bl_idname, icon='MOD_SOLIDIFY')

        box = layout.box()
        box.label(text="3. Colours (filament slots)", icon='COLOR')
        if len(props.filaments) == 0:
            box.label(text="Generate first", icon='INFO')
        for i, f in enumerate(props.filaments):
            active = i == props.active_filament
            row = box.row(align=True)
            # The radio button = "paint with this": makes it active and enters colouring mode.
            op = row.operator(GINGERBREAD_OT_set_active_filament.bl_idname, text=str(i + 1) if i < 9 else "",
                              icon='RADIOBUT_ON' if active else 'RADIOBUT_OFF', depress=active and painting)
            op.slot = i
            row.prop(f, "color", text="")
            row.prop(f, "name", text="")
            op = row.operator(GINGERBREAD_OT_assign_slot.bl_idname, text="", icon='BRUSH_DATA')
            op.slot = i
            op = row.operator(GINGERBREAD_OT_select_slot.bl_idname, text="", icon='RESTRICT_SELECT_OFF')
            op.slot = i
        row = box.row(align=True)
        row.operator(GINGERBREAD_OT_add_filament.bl_idname, icon='ADD')
        op = row.operator(GINGERBREAD_OT_assign_slot.bl_idname, text="Bare Cookie", icon='X')
        op.slot = -1
        box.prop(props, "paint_style")
        row = box.row()
        row.scale_y = 1.5
        if painting:
            row.alert = True
            row.operator(GINGERBREAD_OT_paint.bl_idname, text="Stop Colouring  (Esc)", icon='CANCEL', depress=True)
        else:
            row.operator(GINGERBREAD_OT_paint.bl_idname, text="Click to Colour Regions", icon='BRUSH_DATA')
            if props.filaments:
                box.label(text="Tip: Add Filament or click a ◉ to start painting with it", icon='INFO')
        n_used = len({int(o.get("gb_slot", 0)) for o in builder.gingerbread_objects(context.scene)
                      if o.get("gb_slot", 0) >= 0})
        limit = props.max_filaments or 4
        if n_used > limit:
            box.label(text=("%d filaments in use (Max Filaments is %d)" % (n_used, limit)) if props.max_filaments
                      else ("%d filaments in use (one AMS holds 4)" % n_used), icon='ERROR')
        elif n_used > 4:
            box.label(text="%d filaments: needs more than one AMS" % n_used, icon='INFO')

        obj = context.active_object
        if obj is not None and "gb_kind" in obj:
            s = int(obj.get("gb_slot", 0))
            name = "bare cookie" if s < 0 else (props.filaments[s].name if s < len(props.filaments) else "?")
            box.label(text="%s → %s" % (obj.name, name), icon='OBJECT_DATA')
            kind = obj.get("gb_kind")
            if kind in ('REGION', 'LINES'):
                row = box.row(align=True)
                row.label(text="Style:")
                cur = obj.get("gb_style", 'PUFFED' if kind == 'REGION' else 'AUTO')
                for st in (('PUFFED', 'PAINTED') if kind == 'REGION' else ('AUTO', 'RAISED', 'FLUSH')):
                    op = row.operator(GINGERBREAD_OT_set_style.bl_idname, text=st.title(), depress=(cur == st))
                    op.style = st
        if builder.gingerbread_objects(context.scene):
            row = box.row(align=True)
            row.prop(props, "icing_look", text="")
            row.operator(GINGERBREAD_OT_apply_look.bl_idname, icon='CHECKMARK')

        box = layout.box()
        box.label(text="4. Export", icon='EXPORT')
        if multi:
            box.prop(props, "title", text="Plate Title")
            col = box.column(align=True)
            col.scale_y = 1.4
            col.operator(GINGERBREAD_OT_export_plate.bl_idname, text="Export Plate 3MF…", icon='FILE_3D')
            col.operator(GINGERBREAD_OT_export_each.bl_idname, text="Export Each 3MF…", icon='FILE_FOLDER')
            box.label(text="Plate: all ornaments in one file. Each: one file per", icon='INFO')
            box.label(text="ornament in a folder. Every file has the same filaments.")
        else:
            box.prop(props, "title")
            row = box.row()
            row.scale_y = 1.4
            row.operator(GINGERBREAD_OT_export_3mf.bl_idname, text="Export 3MF…", icon='FILE_3D')
            box.label(text="You choose the file name when you click Export.", icon='INFO')
        # Printer settings: optional, clearly separate from the output file name.
        sub = box.box()
        sub.label(text="Printer settings (optional)", icon='PREFERENCES')
        sub.prop(props, "bambu_template", text="Copy from")
        status, ok = template_status(props.bambu_template)
        row = sub.row()
        row.alert = not ok
        row.label(text=status, icon='CHECKMARK' if ok else 'ERROR')
