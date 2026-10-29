# SPDX-License-Identifier: GPL-2.0-or-later
"""Native game-editor workspace built from Blender's existing editor areas."""

import bpy
import json


WORKSPACES = {"BlendEngine", "World Builder", "Logic Lab", "Play Mode", "Build & Export"}
LAYOUT_VERSION = 1


def is_engine_workspace(context):
    return bool(context.window and context.window.workspace.name in WORKSPACES)


def toggle_fast_preview(context):
    """Trade scene lighting for Workbench while preserving the authored renderer."""
    screen = context.screen
    if screen is None:
        return False
    enabled = not bool(screen.get("blendengine_fast_preview", False))
    viewports = [area for area in screen.areas if area.type == "VIEW_3D"]
    if enabled:
        previous = []
        for area in viewports:
            shading = area.spaces.active.shading
            values = {name: getattr(shading, name) for name in
                      ("type", "light", "color_type", "show_cavity", "cavity_type", "show_shadows")}
            previous.append(values)
            shading.type = "SOLID"
            shading.light = "STUDIO"
            shading.color_type = "MATERIAL"
            shading.show_cavity = True
            shading.cavity_type = "BOTH"
            shading.show_shadows = True
        screen["blendengine_fast_previous"] = json.dumps(previous)
    else:
        previous = json.loads(screen.get("blendengine_fast_previous", "[]"))
        for index, area in enumerate(viewports):
            values = previous[index] if index < len(previous) else {"type": "RENDERED"}
            for name, value in values.items():
                _set(area.spaces.active.shading, name, value)
    screen["blendengine_fast_preview"] = enabled
    for area in viewports:
        area.tag_redraw()
    return enabled


def _set(owner, name, value):
    if owner is not None and hasattr(owner, name):
        try:
            setattr(owner, name, value)
        except (AttributeError, TypeError, ValueError):
            pass


def apply_theme(context):
    """Apply the editor palette when explicitly entering a BlendEngine workspace."""
    if not context.preferences.themes:
        return
    theme = context.preferences.themes[0]
    ui = theme.user_interface
    for name in ("wcol_regular", "wcol_tool", "wcol_toolbar_item", "wcol_num", "wcol_numslider",
                 "wcol_option", "wcol_toggle", "wcol_radio", "wcol_tab", "wcol_text", "wcol_menu_item"):
        widget = getattr(ui, name, None)
        _set(widget, "inner", (0.075, 0.09, 0.11, 1.0))
        _set(widget, "inner_sel", (0.04, 0.52, 0.49, 1.0))
        _set(widget, "text", (0.8, 0.86, 0.89, 1.0))
        _set(widget, "text_sel", (0.95, 1.0, 1.0, 1.0))
        _set(widget, "outline", (0.025, 0.032, 0.043, 1.0))
        _set(widget, "roundness", 0.3)
    for name in ("view_3d", "outliner", "properties", "file_browser", "text_editor"):
        part = getattr(theme, name, None)
        space = getattr(part, "space", None)
        _set(space, "back", (0.026, 0.035, 0.045))
        _set(space, "header", (0.045, 0.058, 0.073, 1.0))
        _set(space, "header_text", (0.8, 0.88, 0.91, 1.0))
        _set(space, "header_text_hi", (0.32, 0.95, 0.84, 1.0))
        _set(getattr(space, "panelcolors", None), "back", (0.045, 0.058, 0.073, 1.0))
    _set(theme.outliner, "active", (0.08, 0.25, 0.28))
    _set(theme.outliner, "selected_highlight", (0.07, 0.31, 0.33))
    _set(theme.view_3d, "object_active", (0.15, 0.95, 0.78))
    _set(theme.view_3d, "object_selected", (0.12, 0.68, 0.62))


def _override(context, area):
    values = {"window": context.window, "screen": context.screen, "area": area}
    region = next((region for region in area.regions if region.type == "WINDOW"), None)
    if region is not None:
        values["region"] = region
    return context.temp_override(**values)


def _runtime_log():
    log = bpy.data.texts.get("BlendEngine Runtime Log")
    if log is None:
        log = bpy.data.texts.new("BlendEngine Runtime Log")
        log.write("BLENDENGINE / OUTPUT\n\nReady. Press Play to run the current scene.\nWASD move  /  Space jump  /  Shift sprint\nPause freezes simulation. Stop returns to editing.\n")
    return log


def _asset_browser(area):
    area.type = "FILE_BROWSER"
    area.ui_type = "ASSETS"
    space = area.spaces.active
    _set(space, "show_region_toolbar", False)
    _set(space, "show_region_ui", False)
    _set(space, "show_region_tool_props", False)
    params = getattr(space, "params", None)
    _set(params, "asset_library_ref", "LOCAL")
    _set(params, "asset_library_reference", "LOCAL")
    _set(params, "display_size", 64)


def _ensure_layout(context):
    screen = context.screen
    if bpy.app.background or screen.get("blendengine_layout_version") == LAYOUT_VERSION:
        return
    # Duplicating a workspace copies editor areas without reliably copying
    # Screen ID properties. Recognize an existing complete dock by its real
    # content as well, so opening Game cannot split the Assets pane again.
    asset_docks = [area for area in screen.areas
                   if area.type == "FILE_BROWSER" and area.ui_type == "ASSETS" and area.height >= 120]
    output_docks = [area for area in screen.areas
                    if area.type == "TEXT_EDITOR" and area.height >= 120 and
                    getattr(area.spaces.active, "text", None) is not None and
                    area.spaces.active.text.name == "BlendEngine Runtime Log"]
    if asset_docks and output_docks:
        screen["blendengine_layout_version"] = LAYOUT_VERSION
        return
    _set(getattr(context.preferences, "apps", None), "show_edge_resize", True)
    viewports = [area for area in screen.areas if area.type == "VIEW_3D"]
    if not viewports:
        area = max(screen.areas, key=lambda area: area.width * area.height)
        area.type = "VIEW_3D"
        viewports = [area]
    main = max(viewports, key=lambda area: area.width * area.height)
    # Standard layouts already provide the right Outliner / Properties dock.
    # Reuse the timeline below Scene, enlarging its shared border in place.
    bottoms = [area for area in screen.areas
               if area.type in {"DOPESHEET_EDITOR", "CONSOLE", "TEXT_EDITOR", "FILE_BROWSER", "INFO"}
               and area.y < main.y + main.height * 0.25 and area.width > main.width * 0.6]
    bottom = max(bottoms, key=lambda area: area.height) if bottoms else None
    if bottom is not None and bottom.height < 120:
        # Edge resizing depends on the OS pointer being over that edge. Keep
        # the original narrow timeline as a native reports strip, and create
        # a correctly sized content dock through the scriptable split API.
        bottom.type = "INFO"
        bottom = None
    if bottom is None:
        before = {area.as_pointer() for area in screen.areas}
        try:
            with _override(context, main):
                bpy.ops.screen.area_split(direction="HORIZONTAL", factor=0.24)
            candidates = [area for area in screen.areas
                          if area.as_pointer() not in before or area == main]
            bottom = min(candidates, key=lambda area: area.y)
        except RuntimeError:
            return
    # Split the dock into actual reusable asset content and an output log.
    before = {area.as_pointer() for area in screen.areas}
    try:
        with _override(context, bottom):
            bpy.ops.screen.area_split(direction="VERTICAL", factor=0.64)
        docks = [area for area in screen.areas
                 if area.as_pointer() not in before or area == bottom]
        docks.sort(key=lambda area: area.x)
        _asset_browser(docks[0])
        if len(docks) > 1:
            output = docks[-1]
            output.type = "TEXT_EDITOR"
            output.spaces.active.text = _runtime_log()
        else:
            # A new area's pixel geometry becomes valid on the next UI pass.
            # Defer the second split rather than marking a partial layout done.
            workspace = context.window.workspace.name
            def finish_layout():
                current = bpy.context
                if current.window and current.window.workspace.name == workspace:
                    configure_screen(current)
                return None
            bpy.app.timers.register(finish_layout, first_interval=0.1)
            return
    except RuntimeError:
        _asset_browser(bottom)
    screen["blendengine_layout_version"] = LAYOUT_VERSION


def configure_screen(context):
    if context.screen is None or not is_engine_workspace(context):
        return
    _ensure_layout(context)
    apply_theme(context)
    play = context.window.workspace.name == "Play Mode"
    for area in context.screen.areas:
        space = area.spaces.active
        _set(area, "show_menus", False)
        _set(space, "show_region_header", True)
        if area.type == "VIEW_3D":
            _set(space, "show_region_toolbar", False)
            _set(space, "show_region_ui", False)
            _set(space, "show_gizmo", not play)
            _set(space, "show_gizmo_object_translate", not play)
            _set(space, "show_gizmo_object_rotate", not play)
            _set(space, "show_gizmo_object_scale", not play)
            _set(space.overlay, "show_overlays", not play)
            _set(space.overlay, "show_relationship_lines", False)
            _set(space.overlay, "show_floor", not play)
            _set(space.overlay, "show_axis_x", not play)
            _set(space.overlay, "show_axis_y", not play)
            # Entering Game selects authored lighting once. Reconfiguring the
            # same workspace preserves the user's preview and shading choices.
            marker = "blendengine_game_shading" if play else "blendengine_scene_shading"
            if not context.screen.get(marker):
                space.shading.type = "RENDERED" if play else "MATERIAL"
                _set(space.shading, "use_scene_lights", True)
                _set(space.shading, "use_scene_world", True)
                context.screen[marker] = True
            if play:
                from . import utils
                utils.enter_camera_view(context)
        elif area.type == "OUTLINER":
            space.display_mode = "VIEW_LAYER"
            _set(space, "show_restrict_column_render", False)
            _set(space, "show_restrict_column_viewport", True)
        elif area.type == "PROPERTIES":
            space.context = "OBJECT"
            _set(space, "show_region_nav_bar", True)
        elif area.type == "FILE_BROWSER" and area.ui_type == "ASSETS":
            _asset_browser(area)
        elif area.type == "TEXT_EDITOR":
            space.text = _runtime_log()
            _set(space, "show_line_numbers", False)
            _set(space, "show_word_wrap", True)
            _set(space, "show_syntax_highlight", False)
            _set(space, "show_region_ui", False)
            _set(space, "font_size", 12)
        area.tag_redraw()
