# SPDX-License-Identifier: GPL-2.0-or-later
#
# BlendEngine application-template hook.

import bpy
from bpy.app.handlers import persistent
import os
import sys


def _enable_engine():
    scripts_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    for folder in ("addons", "addons_core"):
        path = os.path.join(scripts_root, folder)
        if path not in sys.path:
            sys.path.append(path)
    try:
        import addon_utils
        addon_utils.modules_refresh()
        addon_utils.enable("blendengine", default_set=False, persistent=True)
        return
    except Exception:
        pass
    try:
        bpy.ops.preferences.addon_enable(module="blendengine")
    except Exception:
        pass


def _configure_window(context):
    prefs = context.preferences
    view = prefs.view
    view.show_splash = True
    view.show_statusbar_version = False
    view.show_statusbar_stats = True
    view.show_navigate_ui = True
    _apply_black_theme(context)


def _safe_color(owner, name, value):
    try:
        setattr(owner, name, value)
    except Exception:
        pass


def _style_widget(widget, inner=(0.015, 0.017, 0.02, 1.0), selected=(0.0, 0.78, 0.64, 1.0)):
    _safe_color(widget, "inner", inner)
    _safe_color(widget, "inner_sel", selected)
    _safe_color(widget, "text", (0.82, 0.88, 0.9, 1.0))
    _safe_color(widget, "text_sel", (0.02, 0.03, 0.035, 1.0))
    _safe_color(widget, "outline", (0.0, 0.0, 0.0, 1.0))
    _safe_color(widget, "item", (0.05, 0.92, 0.78, 1.0))
    try:
        widget.roundness = 0.18
    except Exception:
        pass


def _apply_black_theme(context):
    themes = context.preferences.themes
    if not themes:
        return
    theme = themes[0]
    ui = theme.user_interface
    dark = (0.008, 0.009, 0.011, 1.0)
    panel = (0.018, 0.02, 0.024, 1.0)
    raised = (0.035, 0.04, 0.048, 1.0)
    cyan = (0.0, 0.78, 0.64, 1.0)
    blue = (0.08, 0.34, 0.95, 1.0)
    amber = (1.0, 0.72, 0.18, 1.0)

    for name in (
        "wcol_regular", "wcol_tool", "wcol_toolbar_item", "wcol_box",
        "wcol_menu", "wcol_menu_item", "wcol_pulldown", "wcol_text",
        "wcol_num", "wcol_numslider", "wcol_option", "wcol_radio",
        "wcol_toggle", "wcol_tab", "wcol_list_item", "wcol_scroll",
        "wcol_progress", "wcol_pie_menu",
    ):
        widget = getattr(ui, name, None)
        if widget is not None:
            _style_widget(widget, raised if "item" in name or "tool" in name else panel, cyan)

    if hasattr(ui, "wcol_menu_back"):
        _style_widget(ui.wcol_menu_back, dark, blue)
    if hasattr(ui, "wcol_state"):
        _safe_color(ui.wcol_state, "inner_anim", blue)
        _safe_color(ui.wcol_state, "inner_anim_sel", cyan)
        _safe_color(ui.wcol_state, "inner_key", amber)
        _safe_color(ui.wcol_state, "inner_key_sel", amber)

    view3d = theme.view_3d
    if hasattr(view3d, "space"):
        space = view3d.space
        _safe_color(space.gradients, "background_type", "SINGLE_COLOR")
        _safe_color(space.gradients, "high_gradient", (0.006, 0.007, 0.009))
        _safe_color(space.gradients, "gradient", (0.006, 0.007, 0.009))
        _safe_color(space, "header", (0.008, 0.009, 0.011, 1.0))
        _safe_color(space, "header_text", (0.82, 0.88, 0.9, 1.0))
        _safe_color(space, "header_text_hi", (0.0, 0.95, 0.78, 1.0))
        _safe_color(space.panelcolors, "back", (0.012, 0.014, 0.017, 1.0))
        _safe_color(space.panelcolors, "sub_back", (0.018, 0.02, 0.024, 1.0))
        _safe_color(space.panelcolors, "header", (0.02, 0.025, 0.03, 1.0))
    _safe_color(view3d, "grid", (0.11, 0.13, 0.15))
    _safe_color(view3d, "view_overlay", (0.0, 0.78, 0.64))
    _safe_color(view3d, "object_selected", (0.0, 0.95, 0.78))
    _safe_color(view3d, "object_active", (1.0, 0.72, 0.18))
    _safe_color(view3d, "wire", (0.28, 0.35, 0.39))
    _safe_color(view3d, "camera", (0.08, 0.34, 0.95))
    _safe_color(view3d, "light", (1.0, 0.72, 0.18))
    _safe_color(view3d, "empty", (0.0, 0.78, 0.64))


def _prepare_engine_workspaces(context):
    if not context.window:
        return
    try:
        from blendengine import utils
    except Exception:
        return

    studio = bpy.data.workspaces.get("BlendEngine")
    if studio is not None:
        context.window.workspace = studio
    try:
        utils.configure_current_screen_for_blendengine(context)
    except Exception:
        pass


def _initialize_scene(context):
    _enable_engine()

    scene = context.scene
    if scene is None:
        return None

    already_initialized = scene.get("blendengine_template_initialized", False)
    if already_initialized:
        try:
            bpy.ops.blendengine.create_workspace()
        except Exception:
            pass
        return scene

    try:
        bpy.ops.blendengine.easy_create_game(template="CYBERPUNK_SHOOTER", target_platform="LINUX")
        scene.blendengine_project.game_title = "Neon Quarantine"
        scene.blendengine_export.package_name = "NeonQuarantine"
        scene["blendengine_template_initialized"] = True
        bpy.ops.blendengine.create_workspace()
        try:
            bpy.ops.blendengine.editor_input_lock()
        except Exception:
            pass
    except Exception:
        pass
    return scene


def _startup_timer():
    try:
        context = bpy.context
        _configure_window(context)
        _initialize_scene(context)
        if not context.window_manager.windows:
            return None
        _prepare_engine_workspaces(context)
        context.window.workspace = bpy.data.workspaces.get("BlendEngine") or context.window.workspace
        scene = context.scene
        if scene is not None and hasattr(scene, "blendengine_editor"):
            scene.blendengine_editor.input_lock_enabled = True
            if not scene.blendengine_editor.input_lock_running:
                try:
                    bpy.ops.blendengine.editor_input_lock()
                except Exception:
                    pass
    except Exception:
        pass
    return None


@persistent
def load_handler(_dummy):
    bpy.app.timers.register(_startup_timer, first_interval=0.1)


def register():
    _enable_engine()
    _startup_timer()
    bpy.app.timers.register(_startup_timer, first_interval=0.1)
    if load_handler not in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.append(load_handler)
    if load_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_handler)


def unregister():
    if load_handler in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.remove(load_handler)
    if load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_handler)
