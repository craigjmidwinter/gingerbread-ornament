# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Craig Midwinter
"""
Gingerbread Ornament Generator

Line-art image in -> multi-colour gingerbread ornament 3MF out: a cookie body with a
rounded baked edge, piped icing lines with a rounded bead profile, every enclosed
area as its own colourable flood-icing part, and a hanging hole.
"""
import importlib

import bpy
from bpy.props import PointerProperty

from . import core, threemf, builder

core = importlib.reload(core)
threemf = importlib.reload(threemf)
builder = importlib.reload(builder)

from . import operators, ui

operators = importlib.reload(operators)
ui = importlib.reload(ui)

classes = [
    ui.GINGERBREAD_Filament,
    ui.GINGERBREAD_ImageEntry,
    ui.GINGERBREAD_Properties,
    ui.GINGERBREAD_UL_images,
    operators.GINGERBREAD_OT_generate,
    operators.GINGERBREAD_OT_assign_slot,
    operators.GINGERBREAD_OT_add_filament,
    operators.GINGERBREAD_OT_select_slot,
    operators.GINGERBREAD_OT_paint,
    operators.GINGERBREAD_OT_set_active_filament,
    operators.GINGERBREAD_OT_stop_painting,
    operators.GINGERBREAD_OT_set_style,
    operators.GINGERBREAD_OT_apply_look,
    operators.GINGERBREAD_OT_export_3mf,
    operators.GINGERBREAD_OT_add_images,
    operators.GINGERBREAD_OT_remove_image,
    operators.GINGERBREAD_OT_move_image,
    operators.GINGERBREAD_OT_export_plate,
    operators.GINGERBREAD_OT_export_each,
    ui.GINGERBREAD_PT_panel,
]


@bpy.app.handlers.persistent
def _gb_load_pre(*_args):
    # Loading a file kills running modal operators; drop the colouring-mode overlay too.
    operators.stop_painting()


def _remove_handlers():
    for h in list(bpy.app.handlers.load_pre):
        if getattr(h, "__name__", "") == "_gb_load_pre":
            bpy.app.handlers.load_pre.remove(h)


def register():
    print("[Gingerbread] Registering add-on")
    for cls in classes:
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
        bpy.utils.register_class(cls)
    if hasattr(bpy.types.Scene, "gingerbread_props"):
        del bpy.types.Scene.gingerbread_props
    bpy.types.Scene.gingerbread_props = PointerProperty(type=ui.GINGERBREAD_Properties)
    _remove_handlers()
    bpy.app.handlers.load_pre.append(_gb_load_pre)


def unregister():
    operators.stop_painting()
    _remove_handlers()
    if hasattr(bpy.types.Scene, "gingerbread_props"):
        del bpy.types.Scene.gingerbread_props
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
    print("[Gingerbread] Unregistered")


if __name__ == "__main__":
    register()
