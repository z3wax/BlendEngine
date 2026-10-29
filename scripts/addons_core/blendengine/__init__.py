# SPDX-License-Identifier: GPL-2.0-or-later
#
# BlendEngine add-on entry point.

bl_info = {
    "name": "BlendEngine",
    "author": "BlendEngine Contributors",
    "version": (0, 1, 0),
    "blender": (3, 6, 0),
    "location": "Top Bar > BlendEngine, 3D View > Sidebar > BlendEngine",
    "description": "Beginner-friendly no-code game-engine workflow built on Blender",
    "warning": "",
    "doc_url": "",
    "support": "COMMUNITY",
    "category": "Game Engine",
}

if "bpy" in locals():
    import importlib

    for module_name in (
        "properties",
        "editor",
        "utils",
        "components",
        "input_system",
        "animation_system",
        "ai_system",
        "graphics",
        "optimization",
        "performance",
        "export_system",
        "demo_game",
        "runtime",
        "templates",
        "operators",
        "panels",
    ):
        if module_name in globals():
            importlib.reload(globals()[module_name])
        else:
            globals()[module_name] = importlib.import_module("." + module_name, __name__)
else:
    from . import (
        properties,
        editor,
        utils,
        components,
        input_system,
        animation_system,
        ai_system,
        graphics,
        optimization,
        performance,
        export_system,
        demo_game,
        runtime,
        templates,
        operators,
        panels,
    )

import bpy


_REGISTER_MODULES = (
    properties,
    components,
    input_system,
    animation_system,
    ai_system,
    optimization,
    performance,
    export_system,
    runtime,
    templates,
    operators,
    panels,
)


def register():
    for module in _REGISTER_MODULES:
        module.register()


def unregister():
    for module in reversed(_REGISTER_MODULES):
        module.unregister()
