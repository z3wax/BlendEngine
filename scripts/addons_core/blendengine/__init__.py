# SPDX-License-Identifier: GPL-2.0-or-later
#
# BlendEngine add-on entry point.

bl_info = {
    "name": "BlendEngine",
    "author": "BlendEngine Contributors",
    "version": (0, 3, 0),
    "blender": (3, 6, 0),
    "location": "Top Bar > BlendEngine, 3D View > Sidebar > BlendEngine > AI Game Creator",
    "description": "AI game creator and beginner-friendly no-code game engine built on Blender",
    "warning": "",
    "doc_url": "",
    "support": "COMMUNITY",
    "category": "Game Engine",
}

if "bpy" in locals():
    import importlib

    for module_name in (
        "properties",
        "utils",
        "components",
        "input_system",
        "animation_system",
        "ai_system",
        "ai_game_spec",
        "ai_game_planner",
        "graphics",
        "optimization",
        "performance",
        "export_system",
        "runtime",
        "templates",
        "ai_game_builder",
        "operators",
        "ai_game_creator",
        "ai_studio",
        "panels",
    ):
        if module_name in globals():
            importlib.reload(globals()[module_name])
        else:
            globals()[module_name] = importlib.import_module("." + module_name, __name__)
else:
    from . import (
        properties,
        utils,
        components,
        input_system,
        animation_system,
        ai_system,
        ai_game_spec,
        ai_game_planner,
        graphics,
        optimization,
        performance,
        export_system,
        runtime,
        templates,
        ai_game_builder,
        operators,
        ai_game_creator,
        ai_studio,
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
    ai_game_creator,
    ai_studio,
    panels,
)


def register():
    for module in _REGISTER_MODULES:
        module.register()


def unregister():
    for module in reversed(_REGISTER_MODULES):
        module.unregister()
