# SPDX-License-Identifier: GPL-2.0-or-later
#
# BlendEngine user interface.

import bpy
from bpy.types import Menu, Panel, UIList

from . import input_system, performance, utils


class TOPBAR_MT_blendengine(Menu):
    bl_idname = "TOPBAR_MT_blendengine"
    bl_label = "BlendEngine"

    def draw(self, context):
        layout = self.layout
        project = context.scene.blendengine_project

        row = layout.row(align=True)
        for page, label, icon in (
            ("STUDIO", "Studio", "WINDOW"),
            ("WORLD", "World", "WORLD"),
            ("LOGIC", "Logic", "NODETREE"),
            ("PLAY", "Play", "PLAY"),
            ("BUILD", "Ship", "EXPORT"),
        ):
            op = row.operator("blendengine.open_page", text=label, icon=icon)
            op.page = page
        layout.operator_context = "INVOKE_DEFAULT"
        layout.operator("blendengine.easy_create_game", text="New Game", icon="ADD")
        layout.operator_context = "EXEC_REGION_WIN"
        if project.test_running:
            layout.operator("blendengine.stop_test_run", text="Stop Game", icon="PAUSE")
        else:
            layout.operator("blendengine.test_run_scene", text="Run Game", icon="PLAY")
        layout.operator("blendengine.prepare_build", text="Build", icon="EXPORT")
        layout.separator()
        layout.operator("blendengine.optimize_for_one_gb", text="1GB Auto Optimize", icon="MOD_SIMPLIFY")
        layout.operator("blendengine.analyze_scene_performance", text="Analyze Project", icon="INFO")
        layout.operator_context = "INVOKE_DEFAULT"
        layout.operator("blendengine.make_game_lighter", text="Optimization Assistant", icon="MOD_DECIM")
        layout.operator_context = "EXEC_REGION_WIN"


def draw_topbar_menu(self, _context):
    self.layout.menu(TOPBAR_MT_blendengine.bl_idname)


class BE_MT_editor_quality(Menu):
    bl_idname = "BE_MT_editor_quality"
    bl_label = "Preview Quality"

    def draw(self, _context):
        for preset in ("LOW", "BALANCED", "HIGH", "CINEMATIC"):
            op = self.layout.operator("blendengine.apply_optimization_preset", text=preset.title())
            op.preset = preset


def _draw_engine_view_header(self, context):
    from . import editor
    if not editor.is_engine_workspace(context):
        _ORIGINAL_VIEW_HEADER(self, context)
        return
    layout = self.layout
    project = context.scene.blendengine_project
    row = layout.row(align=True)
    row.label(text="BLENDENGINE", icon="CUBE")
    row.operator("blendengine.create_playable_demo", text="New Demo", icon="ADD")
    layout.separator()
    row = layout.row(align=True)
    for page, label in (("STUDIO", "Scene"), ("PLAY", "Game")):
        op = row.operator("blendengine.open_page", text=label,
                          depress=context.window.workspace.name == utils.engine_page_name(page))
        op.page = page
    layout.separator_spacer()
    row = layout.row(align=True)
    if project.test_running:
        row.operator("blendengine.pause_test_run", text="Resume" if project.test_paused else "Pause",
                     icon="PLAY" if project.test_paused else "PAUSE", depress=project.test_paused)
        step = row.row(align=True)
        step.enabled = project.test_paused
        step.operator("blendengine.step_test_run", text="", icon="FRAME_NEXT")
        row.operator("blendengine.stop_test_run", text="Stop", icon="CANCEL")
    else:
        row.operator("blendengine.test_run_scene", text="Play", icon="PLAY")
    layout.separator_spacer()
    if project.test_running and project.runtime_viewport_fps > 0:
        layout.label(text="Viewport %.1f Hz" % project.runtime_viewport_fps)
    profile = context.scene.blendengine_quality_profile
    layout.menu("BE_MT_editor_quality", text=profile.preset.replace("_", " ").title(), icon="SHADING_RENDERED")
    layout.operator("blendengine.toggle_fast_preview", text="Fast Preview", icon="SHADING_SOLID",
                    depress=bool(context.screen.get("blendengine_fast_preview", False)))


def _draw_engine_outliner_header(self, context):
    from . import editor
    if editor.is_engine_workspace(context):
        self.layout.label(text="Hierarchy", icon="OUTLINER")


def _draw_engine_properties_header(self, context):
    from . import editor
    if editor.is_engine_workspace(context):
        self.layout.label(text="Inspector", icon="PROPERTIES")


class OBJECT_PT_blendengine_inspector(Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_label = "Game Object"
    bl_order = -100

    @classmethod
    def poll(cls, context):
        from . import editor
        return context.object is not None and editor.is_engine_workspace(context)

    def draw(self, context):
        layout = self.layout
        obj = context.object
        project = context.scene.blendengine_project
        settings = obj.blendengine_object
        row = layout.row()
        row.prop(obj, "name", text="", icon="OBJECT_DATA")
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(settings, "object_tag", text="Tag")
        layout.prop(obj, "location")
        layout.prop(obj, "rotation_euler", text="Rotation")
        layout.prop(obj, "scale")
        if settings.player_controller.enabled:
            layout.separator()
            layout.label(text="Player Controller", icon="OUTLINER_OB_ARMATURE")
            layout.prop(settings.player_controller, "walk_speed", text="Walk Speed")
            layout.prop(settings.player_controller, "run_speed", text="Run Speed")
            layout.prop(settings.player_controller, "jump_force", text="Jump Force")
        layout.separator()
        layout.label(text="Simulation: " + project.test_status,
                     icon="PAUSE" if project.test_paused else "PLAY")
        if project.test_running:
            layout.label(text="Logic %.2f ms / updates %.1f Hz" %
                         (project.runtime_frame_ms, project.runtime_fps))


class BE_UL_components(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        component = item
        icon = "CHECKBOX_HLT" if component.enabled else "CHECKBOX_DEHLT"
        layout.prop(component, "name", text="", emboss=False, icon=icon)


class BE_UL_behaviors(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        icon = "PLAY" if item.enabled else "PAUSE"
        layout.prop(item, "name", text="", emboss=False, icon=icon)


class BE_UL_events(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "name", text="", emboss=False, icon="EVENT")


class BE_UL_conditions(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "name", text="", emboss=False, icon="FILTER")


class BE_UL_actions(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "name", text="", emboss=False, icon="FORWARD")


class BE_UL_variables(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "name", text="", emboss=False, icon="RNA")


class BE_UL_input_bindings(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=input_system.binding_display_name(item), icon="EVENT_W")


class BE_UL_animation_states(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "name", text="", emboss=False, icon="ACTION")


class BE_UL_animation_transitions(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "name", text="", emboss=False, icon="DRIVER")


class BE_UL_performance_messages(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        icon = "CHECKMARK" if item.severity == "GOOD" else "ERROR" if item.severity == "CRITICAL" else "INFO"
        layout.label(text="%s: %s" % (item.severity.title().replace("_", " "), item.message), icon=icon)


class BE_View3DPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendEngine"


class BE_ScenePanel:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"


class BE_ObjectPanel:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None


def _draw_project_settings(layout, scene):
    project = scene.blendengine_project
    layout.use_property_split = True
    layout.use_property_decorate = False

    layout.prop(project, "game_title")
    layout.prop(project, "simple_mode")
    layout.prop(project, "game_dimension")
    layout.prop(project, "default_scene")
    layout.prop(project, "target_platform")
    row = layout.row(align=True)
    row.prop(project, "resolution_x")
    row.prop(project, "resolution_y")
    layout.prop(project, "display_mode")
    layout.prop(project, "quality_level")
    layout.prop(project, "save_system_enabled")
    layout.prop(project, "physics_gravity")
    layout.prop(project, "build_folder")

    if not project.simple_mode:
        layout.separator()
        layout.prop(project, "main_menu_scene")
        layout.prop(project, "loading_screen_scene")


def _status_icon(ok=True, warn=False):
    if ok and not warn:
        return "CHECKMARK"
    return "ERROR" if not ok else "INFO"


def _missing_script_count(scene):
    count = 0
    for obj in scene.objects:
        settings = getattr(obj, "blendengine_object", None)
        if settings is None:
            continue
        for behavior in settings.behaviors:
            for action in behavior.actions:
                if action.action_type == "CUSTOM_SCRIPT" and not action.text_value.strip():
                    count += 1
    return count


def _heavy_texture_count(limit=2048):
    count = 0
    for image in bpy.data.images:
        size = getattr(image, "size", None)
        if size and len(size) >= 2 and (int(size[0]) > limit or int(size[1]) > limit):
            count += 1
    return count


def _draw_status_row(layout, ok, text, detail=""):
    row = layout.row(align=True)
    row.label(text=text, icon=_status_icon(ok, warn=not ok))
    if detail:
        row.label(text=detail)


def _scene_counts(scene):
    game_objects = 0
    behaviors = 0
    components = 0
    for obj in scene.objects:
        settings = getattr(obj, "blendengine_object", None)
        if settings is None:
            continue
        if settings.is_game_object:
            game_objects += 1
        behaviors += len(settings.behaviors)
        components += len(settings.components)
    return game_objects, behaviors, components


def _draw_engine_dashboard(layout, context):
    scene = context.scene
    project = scene.blendengine_project
    opt = scene.blendengine_optimization
    report = scene.blendengine_performance_report
    budget = scene.blendengine_performance_budget
    metrics = performance.estimate_scene(scene)
    missing_scripts = _missing_script_count(scene)
    heavy_textures = _heavy_texture_count(2048 if opt.one_gb_ram_mode else 4096)
    game_objects, behaviors, components = _scene_counts(scene)

    header = layout.row(align=True)
    header.scale_y = 1.4
    header.label(text="BlendEngine Studio", icon="PLAY")

    layout.prop(project, "game_title", text="")

    grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
    grid.label(text="FPS %d" % budget.target_fps, icon="TIME")
    grid.label(text="RAM %d MB" % opt.max_runtime_ram_mb, icon="INFO")
    grid.label(text="%d Objects" % game_objects, icon="OUTLINER_OB_MESH")
    grid.label(text="%d Rules" % behaviors, icon="NODETREE")

    row = layout.row(align=True)
    row.scale_y = 1.45
    row.operator_context = "INVOKE_DEFAULT"
    row.operator("blendengine.easy_create_game", text="New Game", icon="ADD")
    row.operator_context = "EXEC_DEFAULT"
    if project.test_running:
        row.operator("blendengine.stop_test_run", text="Stop Game", icon="PAUSE")
    else:
        row.operator("blendengine.test_run_scene", text="Run Game", icon="PLAY")

    row = layout.row(align=True)
    row.operator("blendengine.optimize_for_one_gb", text="1GB Optimize", icon="MOD_SIMPLIFY")
    row.operator("blendengine.prepare_build", text="Build", icon="EXPORT")

    layout.separator()
    status = layout.column(align=True)
    _draw_status_row(status, budget.target_fps >= 60, "FPS target", "%d" % budget.target_fps)
    _draw_status_row(status, opt.max_runtime_ram_mb <= 1024 if opt.one_gb_ram_mode else True, "Memory budget", "%d MB" % opt.max_runtime_ram_mb)
    _draw_status_row(status, heavy_textures == 0, "Heavy textures", "%d" % heavy_textures)
    _draw_status_row(status, missing_scripts == 0, "Missing scripts", "%d" % missing_scripts)
    _draw_status_row(status, report.status != "CRITICAL", "Build readiness", report.status.title())
    status.label(text="%d tris / %d draw calls / %.1f MB textures" % (
        metrics["triangle_count"],
        metrics["draw_calls_estimated"],
        metrics["texture_memory_mb"],
    ), icon="INFO")
    status.label(text=project.test_status, icon="PLAY" if project.test_running else "PAUSE")
    if context.window and context.window.workspace and context.window.workspace.name == "BlendEngine":
        status.label(text="Game input lock: %s" % ("On" if scene.blendengine_editor.input_lock_enabled else "Off"), icon="KEYINGSET")


def _draw_smart_viewport(layout, scene):
    editor = scene.blendengine_editor
    project = scene.blendengine_project
    row = layout.row(align=True)
    row.prop(editor, "object_snap", toggle=True, icon="SNAP_ON")
    row.prop(editor, "grid_snap", toggle=True, icon="MESH_GRID")
    row = layout.row(align=True)
    row.prop(project, "show_colliders", text="Collision", toggle=True, icon="MESH_CUBE")
    row.prop(project, "show_navigation", text="AI Nav", toggle=True, icon="TRACKING")
    row = layout.row(align=True)
    row.prop(editor, "physics_preview", toggle=True, icon="MOD_PHYSICS")
    row.prop(editor, "lighting_preview", toggle=True, icon="LIGHT")
    row = layout.row(align=True)
    row.prop(editor, "performance_heatmap", toggle=True, icon="SEQ_HISTOGRAM")
    row.prop(editor, "camera_preview", toggle=True, icon="CAMERA_DATA")
    row.prop(editor, "multiplayer_preview", toggle=True, icon="URL")
    layout.label(text="Heatmap: Green good, Yellow watch, Red heavy.", icon="INFO")
    layout.separator()
    layout.use_property_split = True
    layout.prop(editor, "input_lock_enabled")
    row = layout.row(align=True)
    row.operator("blendengine.editor_input_lock", text="Enable Lock", icon="LOCKED")
    row.operator("blendengine.disable_editor_input_lock", text="Disable", icon="UNLOCKED")


def _draw_component_tools(layout):
    col = layout.column(align=True)
    row = col.row(align=True)
    row.operator("blendengine.add_player_controller", icon="OUTLINER_OB_ARMATURE")
    row.operator("blendengine.add_collider", icon="MESH_CUBE")
    row = col.row(align=True)
    row.operator("blendengine.add_rigidbody", icon="MOD_PHYSICS")
    row.operator("blendengine.add_trigger_zone", icon="EMPTY_AXIS")
    row = col.row(align=True)
    row.operator("blendengine.add_health_component", icon="FAKE_USER_ON")
    row.operator("blendengine.add_game_behavior", icon="NODETREE")
    row = col.row(align=True)
    row.operator("blendengine.add_npc_behavior", icon="OUTLINER_OB_ARMATURE")


def _draw_components(layout, obj):
    settings = obj.blendengine_object
    layout.use_property_split = True
    layout.use_property_decorate = False

    layout.prop(settings, "is_game_object")
    layout.prop(settings, "object_tag")
    _draw_component_tools(layout)

    row = layout.row()
    row.template_list("BE_UL_components", "", settings, "components", settings, "active_component_index", rows=4)
    col = row.column(align=True)
    op = col.operator("blendengine.add_component", icon="ADD", text="")
    op.component_type = "TRANSFORM"

    component = utils.active_item(settings.components, settings.active_component_index)
    if component:
        box = layout.box()
        box.prop(component, "name")
        box.prop(component, "component_type")
        box.prop(component, "enabled")
        box.prop(component, "tag")
        box.prop(component, "notes")


def _draw_player_controller(layout, obj):
    settings = obj.blendengine_object
    controller = settings.player_controller
    layout.use_property_split = True
    layout.use_property_decorate = False

    if not controller.enabled:
        layout.operator("blendengine.add_player_controller", icon="ADD")
        return

    layout.prop(controller, "enabled")
    layout.prop(controller, "controller_type")
    layout.separator()
    layout.prop(controller, "walk_speed")
    layout.prop(controller, "run_speed")
    layout.prop(controller, "jump_force")
    layout.prop(controller, "gravity")
    layout.prop(controller, "mouse_sensitivity")
    layout.prop(controller, "camera_follow")
    layout.separator()
    layout.prop(controller, "rotation_smoothing")
    layout.prop(controller, "acceleration")
    layout.prop(controller, "deceleration")
    layout.prop(controller, "ground_detection")
    layout.separator()
    row = layout.row(align=True)
    row.prop(controller, "sprint")
    row.prop(controller, "crouch")
    row = layout.row(align=True)
    row.prop(controller, "climb")
    row.prop(controller, "swim")
    layout.prop(controller, "interact_key")
    layout.prop(controller, "attack_key")

    if not bpy.context.scene.blendengine_project.simple_mode:
        layout.separator()
        layout.prop(controller, "idle_animation")
        layout.prop(controller, "walk_animation")
        layout.prop(controller, "run_animation")
        layout.prop(controller, "jump_animation")
        layout.prop(controller, "attack_animation")


def _draw_variables(layout, obj):
    settings = obj.blendengine_object
    row = layout.row()
    row.template_list("BE_UL_variables", "", settings, "variables", settings, "active_variable_index", rows=3)
    col = row.column(align=True)
    col.operator("blendengine.variable_add", icon="ADD", text="")
    col.operator("blendengine.variable_remove", icon="REMOVE", text="")

    variable = utils.active_item(settings.variables, settings.active_variable_index)
    if variable:
        box = layout.box()
        box.use_property_split = True
        box.prop(variable, "name")
        box.prop(variable, "variable_type")
        if variable.variable_type == "BOOL":
            box.prop(variable, "bool_value", text="Value")
        elif variable.variable_type == "INT":
            box.prop(variable, "int_value", text="Value")
        elif variable.variable_type == "FLOAT":
            box.prop(variable, "float_value", text="Value")
        else:
            box.prop(variable, "string_value", text="Value")
        box.prop(variable, "description")


def _draw_behavior_item_details(layout, behavior):
    event = utils.active_item(behavior.events, behavior.active_event_index)
    if event:
        box = layout.box()
        box.label(text="Selected Event")
        box.use_property_split = True
        box.prop(event, "name")
        box.prop(event, "event_type")
        if event.event_type == "ON_KEY_PRESS":
            box.prop(event, "key")
        elif event.event_type in {"ON_COLLISION", "ON_ENTER_TRIGGER"}:
            box.prop(event, "tag")
        elif event.event_type == "ON_TIMER":
            box.prop(event, "timer_seconds")
        elif event.event_type == "CUSTOM_EVENT":
            box.prop(event, "custom_event")

    condition = utils.active_item(behavior.conditions, behavior.active_condition_index)
    if condition:
        box = layout.box()
        box.label(text="Selected Condition")
        box.use_property_split = True
        box.prop(condition, "name")
        box.prop(condition, "condition_type")
        if condition.condition_type != "ALWAYS":
            box.prop(condition, "variable_name")
            box.prop(condition, "compare")
            box.prop(condition, "number_value")
            box.prop(condition, "text_value")
            box.prop(condition, "bool_value")

    action = utils.active_item(behavior.actions, behavior.active_action_index)
    if action:
        box = layout.box()
        box.label(text="Selected Action")
        box.use_property_split = True
        box.prop(action, "name")
        box.prop(action, "action_type")
        box.prop(action, "target_object")
        if action.action_type == "PLAY_ANIMATION":
            box.prop(action, "animation")
        elif action.action_type == "LOAD_SCENE":
            box.prop(action, "scene")
        elif action.action_type in {"SET_VARIABLE", "CHANGE_HEALTH"}:
            box.prop(action, "variable_name")
            box.prop(action, "number_value")
        elif action.action_type in {"MOVE_OBJECT", "ROTATE_OBJECT"}:
            box.prop(action, "vector_value")
        else:
            box.prop(action, "text_value")


def _draw_behaviors(layout, obj):
    settings = obj.blendengine_object
    row = layout.row()
    row.template_list("BE_UL_behaviors", "", settings, "behaviors", settings, "active_behavior_index", rows=3)
    col = row.column(align=True)
    col.operator("blendengine.add_game_behavior", icon="ADD", text="")
    col.operator("blendengine.remove_game_behavior", icon="REMOVE", text="")

    behavior = utils.active_item(settings.behaviors, settings.active_behavior_index)
    if not behavior:
        return

    layout.use_property_split = True
    layout.prop(behavior, "name")
    layout.prop(behavior, "enabled")
    layout.prop(behavior, "description")

    row = layout.row()
    row.template_list("BE_UL_events", "", behavior, "events", behavior, "active_event_index", rows=2)
    col = row.column(align=True)
    op = col.operator("blendengine.behavior_item_add", icon="ADD", text="")
    op.kind = "EVENT"
    op = col.operator("blendengine.behavior_item_remove", icon="REMOVE", text="")
    op.kind = "EVENT"

    row = layout.row()
    row.template_list("BE_UL_conditions", "", behavior, "conditions", behavior, "active_condition_index", rows=2)
    col = row.column(align=True)
    op = col.operator("blendengine.behavior_item_add", icon="ADD", text="")
    op.kind = "CONDITION"
    op = col.operator("blendengine.behavior_item_remove", icon="REMOVE", text="")
    op.kind = "CONDITION"

    row = layout.row()
    row.template_list("BE_UL_actions", "", behavior, "actions", behavior, "active_action_index", rows=2)
    col = row.column(align=True)
    op = col.operator("blendengine.behavior_item_add", icon="ADD", text="")
    op.kind = "ACTION"
    op = col.operator("blendengine.behavior_item_remove", icon="REMOVE", text="")
    op.kind = "ACTION"

    _draw_behavior_item_details(layout, behavior)


def _draw_input_map(layout, scene):
    input_map = scene.blendengine_input_map
    row = layout.row()
    row.template_list("BE_UL_input_bindings", "", input_map, "bindings", input_map, "active_binding_index", rows=6)
    col = row.column(align=True)
    col.operator("blendengine.input_defaults", icon="PRESET", text="")
    col.operator("blendengine.input_binding_add", icon="ADD", text="")
    col.operator("blendengine.input_binding_remove", icon="REMOVE", text="")

    binding = utils.active_item(input_map.bindings, input_map.active_binding_index)
    if binding:
        box = layout.box()
        box.use_property_split = True
        box.prop(binding, "name")
        box.prop(binding, "action")
        if binding.action == "CUSTOM":
            box.prop(binding, "custom_action")
        box.prop(binding, "device")
        box.prop(binding, "key")
        box.prop(binding, "scale")


def _draw_animation_controller(layout, obj):
    controller = obj.blendengine_object.animation_controller
    layout.use_property_split = True
    layout.use_property_decorate = False

    if not controller.enabled:
        layout.operator("blendengine.animation_state_add", icon="ADD")
        return

    layout.prop(controller, "enabled")
    layout.prop(controller, "default_state")

    row = layout.row()
    row.template_list("BE_UL_animation_states", "", controller, "states", controller, "active_state_index", rows=4)
    col = row.column(align=True)
    col.operator("blendengine.animation_state_add", icon="ADD", text="")
    col.operator("blendengine.animation_state_remove", icon="REMOVE", text="")

    state = utils.active_item(controller.states, controller.active_state_index)
    if state:
        box = layout.box()
        box.use_property_split = True
        box.prop(state, "name")
        box.prop(state, "state_type")
        box.prop(state, "animation")
        box.prop(state, "loop")
        box.prop(state, "speed")

    row = layout.row()
    row.template_list(
        "BE_UL_animation_transitions",
        "",
        controller,
        "transitions",
        controller,
        "active_transition_index",
        rows=3,
    )
    col = row.column(align=True)
    col.operator("blendengine.animation_transition_add", icon="ADD", text="")
    col.operator("blendengine.animation_transition_remove", icon="REMOVE", text="")

    transition = utils.active_item(controller.transitions, controller.active_transition_index)
    if transition:
        box = layout.box()
        box.use_property_split = True
        box.prop(transition, "name")
        box.prop(transition, "from_state")
        box.prop(transition, "to_state")
        box.prop(transition, "trigger")
        if transition.trigger == "KEY_PRESSED":
            box.prop(transition, "key")
        elif transition.trigger == "EVENT_TRIGGERED":
            box.prop(transition, "event_name")
        else:
            box.prop(transition, "threshold")


def _draw_npc(layout, obj):
    npc = obj.blendengine_object.npc_behavior
    layout.use_property_split = True
    layout.use_property_decorate = False

    if not npc.enabled:
        layout.operator("blendengine.add_npc_behavior", icon="ADD")
        return

    layout.prop(npc, "enabled")
    layout.prop(npc, "behavior_template")
    layout.prop(npc, "target_object")
    layout.prop(npc, "move_speed")
    layout.prop(npc, "patrol_radius")
    layout.prop(npc, "detection_range")
    layout.prop(npc, "attack_range")
    layout.prop(npc, "dialogue_text")
    layout.prop(npc, "quest_id")


def _draw_health(layout, obj):
    health = obj.blendengine_object.health
    layout.use_property_split = True
    layout.use_property_decorate = False
    if not health.enabled:
        layout.operator("blendengine.add_health_component", icon="ADD")
        return
    layout.prop(health, "enabled")
    layout.prop(health, "max_health")
    layout.prop(health, "current_health")
    layout.prop(health, "destroy_on_death")
    layout.prop(health, "game_over_on_death")


def _draw_test_run(layout, scene):
    project = scene.blendengine_project
    layout.label(text="Dedicated Play Mode page", icon="SCREEN_BACK")
    layout.label(text=project.test_status, icon="PLAY" if project.test_running else "PAUSE")
    row = layout.row(align=True)
    row.scale_y = 1.5
    if project.test_running:
        row.operator("blendengine.stop_test_run", text="Stop Game", icon="PAUSE")
    else:
        row.operator("blendengine.test_run_scene", text="Run Game", icon="PLAY")
    op = layout.operator("blendengine.open_page", text="Open Play Mode Page", icon="WINDOW")
    op.page = "PLAY"

    layout.use_property_split = True
    layout.prop(scene.blendengine_editor, "input_lock_enabled")
    layout.prop(project, "show_fps")
    layout.prop(project, "show_colliders")
    layout.prop(project, "show_navigation")
    layout.prop(project, "show_game_variables")
    layout.prop(project, "show_logs")
    layout.prop(project, "debug_mode")
    layout.separator()
    layout.label(text="Live Play HUD", icon="SEQ_HISTOGRAM")
    grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
    grid.label(text="Updates %.1f Hz" % project.runtime_fps, icon="TIME")
    grid.label(text="Logic %.2f ms" % project.runtime_frame_ms, icon="PREVIEW_RANGE")
    grid.label(text="RAM %.0f MB" % project.runtime_memory_mb, icon="MEMORY")
    grid.label(text="Visible %d" % project.runtime_visible_objects, icon="HIDE_OFF")
    grid.label(text="Tris %d" % project.runtime_triangles_visible, icon="MESH_DATA")
    grid.label(text="Draw %d" % project.runtime_draw_calls_estimated, icon="RENDERLAYERS")


def _draw_build(layout, scene):
    project = scene.blendengine_project
    export = scene.blendengine_export
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(project, "target_platform")
    row = layout.row(align=True)
    for platform in ("WINDOWS", "LINUX", "MACOS"):
        op = row.operator("blendengine.apply_platform_profile", text=platform.title())
        op.platform = platform
    row = layout.row(align=True)
    for platform in ("IOS", "ANDROID", "WEB"):
        op = row.operator("blendengine.apply_platform_profile", text=platform.title())
        op.platform = platform
    layout.prop(project, "build_folder")
    layout.prop(export, "package_name")
    layout.prop(export, "export_playable_project")
    layout.prop(export, "export_assets")
    layout.prop(export, "export_scene_package")
    layout.prop(export, "include_debug_overlay")
    layout.operator("blendengine.prepare_build", icon="EXPORT")


def _draw_game_creation(layout, scene):
    project = scene.blendengine_project
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(project, "game_dimension")
    layout.prop(project, "target_platform")
    row = layout.row(align=True)
    row.operator_context = "INVOKE_DEFAULT"
    row.operator("blendengine.easy_create_game", text="Magic Create", icon="PLAY")
    row.operator_context = "EXEC_DEFAULT"
    op = row.operator("blendengine.open_page", text="Studio", icon="WINDOW")
    op.page = "STUDIO"
    col = layout.column(align=True)
    col.operator("blendengine.generate_cyberpunk_shooter_template", text="Cyberpunk Zombie Shooter", icon="OUTLINER_OB_ARMATURE")
    col.operator("blendengine.generate_basic_template", text="3D Starter World", icon="SCENE_DATA")
    col.operator("blendengine.generate_2d_template", text="2D Platformer", icon="IMAGE_DATA")
    col.operator("blendengine.input_defaults", text="Reset Controls", icon="EVENT_W")


def _draw_world_hierarchy(layout, scene):
    game_objects = []
    for obj in scene.objects:
        settings = getattr(obj, "blendengine_object", None)
        if settings is not None and settings.is_game_object:
            game_objects.append(obj)
    layout.label(text="%d gameplay objects in world" % len(game_objects), icon="OUTLINER")
    for obj in game_objects[:18]:
        row = layout.row(align=True)
        icon = "OUTLINER_OB_CAMERA" if obj.type == "CAMERA" else "LIGHT" if obj.type == "LIGHT" else "OUTLINER_OB_MESH"
        row.prop(obj, "name", text="", emboss=False, icon=icon)
        row.label(text=obj.blendengine_object.object_tag or "Untagged")
    if len(game_objects) > 18:
        layout.label(text="+ %d more objects" % (len(game_objects) - 18), icon="DOT")


def _draw_inspector(layout, context):
    obj = context.object
    if obj is None:
        layout.label(text="Select a gameplay object.", icon="INFO")
        return
    layout.label(text=obj.name, icon="OUTLINER_OB_MESH")
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(obj, "location")
    layout.prop(obj, "rotation_euler", text="Rotation")
    layout.prop(obj, "scale")
    layout.separator()
    _draw_components(layout, obj)


def _draw_assets(layout):
    layout.label(text="%d meshes  %d materials  %d images  %d sounds" % (
        len(bpy.data.meshes),
        len(bpy.data.materials),
        len(bpy.data.images),
        len(bpy.data.sounds),
    ), icon="ASSET_MANAGER")
    col = layout.column(align=True)
    col.operator("wm.append", text="Import Asset", icon="IMPORT")
    col.operator("wm.save_as_mainfile", text="Save Project", icon="FILE_TICK")
    for material in list(bpy.data.materials)[:10]:
        layout.prop(material, "name", text="", emboss=False, icon="MATERIAL")


def _draw_material_editor(layout, context):
    obj = context.object
    mat = obj.active_material if obj and hasattr(obj, "active_material") else None
    if mat is None:
        layout.operator("object.material_slot_add", text="Add Material", icon="ADD")
        return
    layout.label(text=mat.name, icon="MATERIAL")
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(mat, "diffuse_color", text="Base Color")
    layout.prop(mat, "use_nodes", text="PBR Nodes")
    layout.label(text="Shader presets: PBR, Water, Glass, Skin, Car Paint, Wetness", icon="SHADING_RENDERED")


def _behavior_cpp_preview(behavior):
    if behavior is None:
        return ["// Select or add a rule to see generated code."]
    lines = ["void %s::Run(GameObject* self) {" % behavior.name.replace(" ", "")]
    if behavior.events:
        lines.append("  // Event: %s" % behavior.events[behavior.active_event_index].event_type)
    for condition in behavior.conditions:
        if condition.condition_type != "ALWAYS":
            lines.append("  if (!Check_%s(self)) return;" % condition.name.replace(" ", ""))
    for action in behavior.actions:
        if action.action_type == "CHANGE_HEALTH":
            lines.append("  ChangeHealth(self, %.2f);" % action.number_value)
        elif action.action_type == "SET_VARIABLE":
            lines.append("  self->Set(\"%s\", %.2f);" % (action.variable_name, action.number_value))
        elif action.action_type == "SHOW_LOG":
            lines.append("  Log(\"%s\");" % action.text_value.replace('"', '\\"'))
        elif action.action_type == "CUSTOM_SCRIPT":
            lines.append("  RunScript(\"%s\");" % action.text_value.replace('"', '\\"'))
        else:
            lines.append("  DoAction(\"%s\");" % action.action_type)
    lines.append("}")
    return lines


def _draw_visual_code(layout, context):
    obj = context.object
    if obj is None:
        layout.label(text="Select object to edit visual rules.", icon="INFO")
        return
    _draw_behaviors(layout, obj)
    behavior = utils.active_item(obj.blendengine_object.behaviors, obj.blendengine_object.active_behavior_index)
    layout.separator()
    layout.label(text="Generated Code Preview", icon="SCRIPT")
    box = layout.box()
    for line in _behavior_cpp_preview(behavior)[:12]:
        box.label(text=line)


def _draw_multiplayer(layout, scene):
    multiplayer = scene.blendengine_multiplayer
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(multiplayer, "enabled")
    layout.prop(multiplayer, "mode")
    layout.prop(multiplayer, "max_players")
    layout.prop(multiplayer, "server_tick_rate")
    layout.prop(multiplayer, "port")
    layout.separator()
    row = layout.row(align=True)
    row.prop(multiplayer, "sync_position", toggle=True)
    row.prop(multiplayer, "sync_health", toggle=True)
    row = layout.row(align=True)
    row.prop(multiplayer, "sync_inventory", toggle=True)
    row.prop(multiplayer, "sync_animation", toggle=True)
    row = layout.row(align=True)
    row.prop(multiplayer, "predicted_movement", toggle=True)
    row.prop(multiplayer, "rollback_safety", toggle=True)


def _draw_terrain_tools(layout, scene):
    optimization = scene.blendengine_optimization
    layout.label(text="Open world streaming", icon="WORLD")
    layout.use_property_split = True
    layout.prop(optimization, "world_cell_size")
    layout.prop(optimization, "visible_cell_radius")
    layout.prop(optimization, "level_streaming")
    layout.separator()
    layout.label(text="Generate: terrain, grass, trees, river, road, city, cave, biome", icon="MOD_BUILD")
    layout.operator("blendengine.optimize_for_one_gb", text="Prepare Streaming World", icon="MOD_SIMPLIFY")


def _draw_character_creator(layout, context):
    obj = context.object
    layout.label(text="Humanoid setup", icon="ARMATURE_DATA")
    if obj is None:
        layout.label(text="Select a character mesh or armature.", icon="INFO")
        return
    row = layout.row(align=True)
    row.operator("blendengine.add_player_controller", text="Player", icon="OUTLINER_OB_ARMATURE")
    row.operator("blendengine.add_npc_behavior", text="NPC", icon="OUTLINER_OB_ARMATURE")
    row = layout.row(align=True)
    row.operator("blendengine.add_health_component", text="Health", icon="FAKE_USER_ON")
    row.operator("blendengine.add_rigidbody", text="Ragdoll Body", icon="MOD_PHYSICS")
    _draw_animation_controller(layout, obj)


def _draw_profiler(layout, scene):
    report = scene.blendengine_performance_report
    project = scene.blendengine_project
    metrics = performance.estimate_scene(scene)
    layout.label(text=report.summary, icon="ERROR" if report.status == "CRITICAL" else "INFO")
    row = layout.row(align=True)
    row.operator("blendengine.analyze_scene_performance", text="Analyze", icon="INFO")
    row.operator("blendengine.generate_optimization_report", text="Report", icon="FILE_TEXT")
    layout.use_property_split = True
    layout.prop(report, "triangle_count")
    layout.prop(report, "draw_calls_estimated")
    layout.prop(report, "texture_memory_mb")
    layout.prop(report, "objects_without_lod")
    layout.label(text="Live estimate: %d objects, %d images, %.1f MB textures" % (
        metrics["object_count"],
        metrics["texture_count"],
        metrics["texture_memory_mb"],
    ), icon="SEQ_HISTOGRAM")
    layout.separator()
    layout.label(text="Play Mode Runtime", icon="PLAY")
    layout.label(text="Updates %.1f Hz | Logic %.2f ms | RAM %.0f MB" % (
        project.runtime_fps,
        project.runtime_frame_ms,
        project.runtime_memory_mb,
    ))
    layout.label(text="Visible %d | Tris %d | Draw %d" % (
        project.runtime_visible_objects,
        project.runtime_triangles_visible,
        project.runtime_draw_calls_estimated,
    ))


def _draw_console(layout, scene):
    report = scene.blendengine_performance_report
    runtime_log = bpy.data.texts.get("BlendEngine Runtime Log")
    layout.label(text="Console / Logs", icon="CONSOLE")
    if runtime_log:
        for line in runtime_log.as_string().splitlines()[-8:]:
            layout.label(text=line[:96])
    else:
        layout.label(text="No runtime logs yet.")
    layout.separator()
    for message in list(report.messages)[:6]:
        layout.label(text="%s: %s" % (message.severity, message.message[:72]), icon=_status_icon(message.severity != "CRITICAL", message.severity == "WARNING"))


def _draw_audio_vfx_lighting(layout, scene):
    layout.label(text="Audio: %d sounds" % len(bpy.data.sounds), icon="SPEAKER")
    layout.label(text="VFX: particles %d" % scene.blendengine_performance_report.particle_system_count, icon="PARTICLES")
    layout.label(text="Lighting: %d lights, %d dynamic" % (
        scene.blendengine_performance_report.light_count,
        scene.blendengine_performance_report.dynamic_light_count,
    ), icon="LIGHT")
    layout.operator("blendengine.mark_baked_lighting_candidate", text="Mark Selected Baked", icon="LIGHT")


def _draw_plugins_marketplace_vcs(layout):
    layout.label(text="Plugin Manager: local extension hooks ready", icon="PREFERENCES")
    layout.label(text="Marketplace: project asset pipeline placeholder", icon="ASSET_MANAGER")
    layout.label(text="Version Control: use repository status outside editor", icon="FILE_TICK")


def _draw_optimization_profile(layout, scene):
    profile = scene.blendengine_quality_profile
    optimization = scene.blendengine_optimization
    layout.label(text="Graphics & Performance", icon="SHADING_RENDERED")
    layout.label(text="Apply a profile to update EEVEE rendering.")

    row = layout.row(align=True)
    for preset in ("ULTRA_LOW", "LOW", "BALANCED"):
        op = row.operator("blendengine.apply_optimization_preset", text=preset.replace("_", " ").title())
        op.preset = preset
    row = layout.row(align=True)
    for preset in ("HIGH", "CINEMATIC", "CUSTOM"):
        op = row.operator("blendengine.apply_optimization_preset", text=preset.replace("_", " ").title())
        op.preset = preset

    if scene.render.engine not in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
        layout.label(text="Select EEVEE to apply real-time graphics.", icon="INFO")
    elif hasattr(scene.eevee, "use_raytracing"):
        layout.label(text="Bloom uses your compositor in this EEVEE version.", icon="INFO")

    layout.label(text="Custom applies the values below; FPS is a budget.")

    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(profile, "preset")
    op = layout.operator("blendengine.apply_optimization_preset", text="Apply Selected Profile", icon="CHECKMARK")
    op.preset = profile.preset
    layout.prop(profile, "target_fps")
    layout.prop(profile, "resolution_scale")
    layout.prop(profile, "texture_quality")
    layout.prop(profile, "shadow_quality")
    layout.prop(profile, "shadow_distance")
    layout.prop(profile, "anti_aliasing")
    layout.prop(profile, "ambient_occlusion")
    layout.prop(profile, "bloom")
    layout.prop(profile, "reflections")
    layout.prop(profile, "volumetrics")
    layout.prop(profile, "motion_blur")
    layout.prop(profile, "lod_multiplier")
    layout.prop(profile, "max_dynamic_lights")
    layout.prop(profile, "max_shadow_casters")
    layout.prop(profile, "physics_quality")
    layout.prop(profile, "animation_update_rate")
    layout.prop(profile, "animation_quality")
    layout.prop(profile, "particles_quality")
    layout.prop(profile, "vegetation_density")
    layout.prop(profile, "reflection_quality")
    layout.prop(profile, "post_processing_quality")

    layout.separator()
    layout.label(text="Lightweight Graphics Strategy")
    layout.prop(optimization, "weak_hardware_target")
    layout.prop(optimization, "one_gb_ram_mode")
    layout.prop(optimization, "max_runtime_ram_mb")
    layout.prop(optimization, "camera_frustum_generation")
    layout.prop(optimization, "hide_behind_camera")
    layout.prop(optimization, "hidden_surface_culling")
    layout.prop(optimization, "texture_streaming")
    layout.prop(optimization, "mesh_streaming")
    layout.prop(optimization, "world_cell_size")
    layout.prop(optimization, "visible_cell_radius")
    layout.prop(optimization, "max_visible_objects")
    layout.prop(optimization, "generation_budget_ms")
    layout.prop(optimization, "dynamic_resolution")
    layout.prop(optimization, "emergency_quality_drop")
    layout.prop(optimization, "prefer_baked_lighting")
    layout.prop(optimization, "use_lod_strategy")
    layout.prop(optimization, "use_impostors")
    layout.prop(optimization, "use_texture_atlases")
    layout.prop(optimization, "use_material_batching")
    layout.prop(optimization, "use_instancing")
    layout.prop(optimization, "use_occlusion_culling")
    layout.prop(optimization, "use_frustum_culling")
    layout.prop(optimization, "use_animation_culling")
    layout.prop(optimization, "use_physics_culling")
    layout.prop(optimization, "use_simplified_colliders")
    layout.prop(optimization, "async_asset_loading")
    layout.prop(optimization, "level_streaming")
    layout.prop(optimization, "scalable_post_processing")


def _draw_performance_budget(layout, scene):
    budget = scene.blendengine_performance_budget
    layout.label(text="Budgets are beginner guardrails for weak-computer performance.", icon="INFO")
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(budget, "target_fps")
    layout.prop(budget, "max_triangles_visible")
    layout.prop(budget, "max_draw_calls_estimated")
    layout.prop(budget, "max_texture_memory_mb")
    layout.prop(budget, "max_dynamic_lights")
    layout.prop(budget, "max_shadow_casters")
    layout.prop(budget, "max_rigidbodies")
    layout.prop(budget, "max_particles")
    layout.prop(budget, "max_bones_visible")


def _draw_scene_analyzer(layout, scene):
    report = scene.blendengine_performance_report
    layout.label(text=report.summary, icon="ERROR" if report.status == "CRITICAL" else "INFO")
    row = layout.row(align=True)
    row.operator("blendengine.analyze_scene_performance", icon="INFO")
    row.operator("blendengine.generate_optimization_report", icon="FILE_TEXT")
    layout.operator_context = "INVOKE_DEFAULT"
    layout.operator("blendengine.make_game_lighter", icon="MOD_DECIM")
    layout.operator_context = "EXEC_REGION_WIN"

    col = layout.column(align=True)
    col.operator("blendengine.generate_lod_placeholders", icon="MOD_DECIM")
    col.operator("blendengine.mark_static_object", icon="MESH_CUBE")
    col.operator("blendengine.add_lod_group", icon="MOD_DECIM")
    col.operator("blendengine.mark_instancing_candidate", icon="LINKED")
    col.operator("blendengine.mark_baked_lighting_candidate", icon="LIGHT")

    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.separator()
    layout.label(text="Current Estimates")
    layout.prop(report, "triangle_count")
    layout.prop(report, "draw_calls_estimated")
    layout.prop(report, "texture_memory_mb")
    layout.prop(report, "dynamic_light_count")
    layout.prop(report, "shadow_caster_count")
    layout.prop(report, "rigidbody_count")
    layout.prop(report, "particle_count_estimated")
    layout.prop(report, "bone_count_visible")
    layout.prop(report, "objects_without_lod")
    layout.prop(report, "material_count")
    layout.prop(report, "object_count")

    row = layout.row()
    row.template_list("BE_UL_performance_messages", "", report, "messages", report, "active_message_index", rows=5)
    message = utils.active_item(report.messages, report.active_message_index)
    if message and message.suggested_fix:
        box = layout.box()
        box.label(text="Suggested Fix")
        box.label(text=message.suggested_fix)


def _draw_object_optimization(layout, obj):
    opt = obj.blendengine_object.optimization
    layout.label(text="Runtime/build optimization markers.", icon="INFO")
    row = layout.row(align=True)
    row.operator("blendengine.mark_static_object", icon="MESH_CUBE")
    row.operator("blendengine.add_lod_group", icon="MOD_DECIM")
    row = layout.row(align=True)
    row.operator("blendengine.mark_instancing_candidate", icon="LINKED")
    row.operator("blendengine.mark_baked_lighting_candidate", icon="LIGHT")

    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(opt, "static_object")
    layout.prop(opt, "dynamic_object")
    layout.prop(opt, "occluder")
    layout.prop(opt, "lod_group")
    layout.prop(opt, "lod_placeholder_count")
    layout.prop(opt, "impostor_candidate")
    layout.prop(opt, "baked_lighting_candidate")
    layout.prop(opt, "collider_simplification")
    layout.prop(opt, "disable_when_far")
    layout.prop(opt, "disable_distance")
    layout.prop(opt, "animation_culling")
    layout.prop(opt, "physics_sleep")
    layout.prop(opt, "merge_candidate")
    layout.prop(opt, "instancing_candidate")
    layout.prop(opt, "notes")


class VIEW3D_PT_blendengine_engine_hub(BE_View3DPanel, Panel):
    bl_label = "Engine Dashboard"

    def draw(self, context):
        _draw_engine_dashboard(self.layout, context)


class VIEW3D_PT_blendengine_smart_viewport(BE_View3DPanel, Panel):
    bl_label = "Smart Viewport"

    def draw(self, context):
        _draw_smart_viewport(self.layout, context.scene)


class VIEW3D_PT_blendengine_world(BE_View3DPanel, Panel):
    bl_label = "World Hierarchy"
    bl_category = "World"

    def draw(self, context):
        _draw_world_hierarchy(self.layout, context.scene)


class VIEW3D_PT_blendengine_inspector(BE_View3DPanel, Panel):
    bl_label = "Inspector"
    bl_category = "Inspector"

    def draw(self, context):
        _draw_inspector(self.layout, context)


class VIEW3D_PT_blendengine_assets(BE_View3DPanel, Panel):
    bl_label = "Asset Browser"
    bl_category = "Assets"

    def draw(self, _context):
        _draw_assets(self.layout)


class VIEW3D_PT_blendengine_materials(BE_View3DPanel, Panel):
    bl_label = "Material Editor"
    bl_category = "Assets"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_material_editor(self.layout, context)


class VIEW3D_PT_blendengine_quick_start(BE_View3DPanel, Panel):
    bl_label = "Create Game"
    bl_category = "Create"

    def draw(self, context):
        _draw_game_creation(self.layout, context.scene)


class VIEW3D_PT_blendengine_object(BE_View3DPanel, Panel):
    bl_label = "Game Object Inspector"
    bl_category = "Object"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None:
            layout.label(text="Select an object.", icon="INFO")
            return
        _draw_components(layout, obj)


class VIEW3D_PT_blendengine_player(BE_View3DPanel, Panel):
    bl_label = "Player Controller"
    bl_category = "Object"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None:
            layout.label(text="Select a player object.", icon="INFO")
            return
        _draw_player_controller(layout, obj)


class VIEW3D_PT_blendengine_logic(BE_View3DPanel, Panel):
    bl_label = "No-Code Rules"
    bl_category = "Logic"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None:
            layout.label(text="Select an object.", icon="INFO")
            return
        _draw_behaviors(layout, obj)
        layout.separator()
        _draw_variables(layout, obj)


class VIEW3D_PT_blendengine_visual_code(BE_View3DPanel, Panel):
    bl_label = "Visual Script + Code"
    bl_category = "Logic"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_visual_code(self.layout, context)


class VIEW3D_PT_blendengine_animation(BE_View3DPanel, Panel):
    bl_label = "Animation Editor"
    bl_category = "Animation"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None:
            layout.label(text="Select an animated object.", icon="INFO")
            return
        _draw_animation_controller(layout, obj)


class VIEW3D_PT_blendengine_character(BE_View3DPanel, Panel):
    bl_label = "Character Creator"
    bl_category = "Character"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_character_creator(self.layout, context)


class VIEW3D_PT_blendengine_ai(BE_View3DPanel, Panel):
    bl_label = "AI Editor"
    bl_category = "AI"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None:
            layout.label(text="Select an NPC object.", icon="INFO")
            return
        _draw_npc(layout, obj)


class VIEW3D_PT_blendengine_terrain(BE_View3DPanel, Panel):
    bl_label = "Terrain / Open World"
    bl_category = "World"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_terrain_tools(self.layout, context.scene)


class VIEW3D_PT_blendengine_physics(BE_View3DPanel, Panel):
    bl_label = "Physics Editor"
    bl_category = "Physics"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None:
            layout.label(text="Select object for physics.", icon="INFO")
            return
        row = layout.row(align=True)
        row.operator("blendengine.add_collider", text="Collider", icon="MESH_CUBE")
        row.operator("blendengine.add_rigidbody", text="Rigidbody", icon="MOD_PHYSICS")
        _draw_object_optimization(layout, obj)


class VIEW3D_PT_blendengine_health(BE_View3DPanel, Panel):
    bl_label = "Health"
    bl_category = "Object"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        obj = context.object
        if obj is None:
            self.layout.label(text="Select an object.", icon="INFO")
            return
        _draw_health(self.layout, obj)


class VIEW3D_PT_blendengine_input(BE_View3DPanel, Panel):
    bl_label = "Input Map"
    bl_category = "Create"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_input_map(self.layout, context.scene)


class VIEW3D_PT_blendengine_multiplayer(BE_View3DPanel, Panel):
    bl_label = "Multiplayer"
    bl_category = "Multiplayer"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_multiplayer(self.layout, context.scene)


class VIEW3D_PT_blendengine_optimization(BE_View3DPanel, Panel):
    bl_label = "Streaming + Culling"
    bl_category = "Optimize"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_optimization_profile(self.layout, context.scene)


class VIEW3D_PT_blendengine_budget(BE_View3DPanel, Panel):
    bl_label = "Frame Budget"
    bl_category = "Optimize"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_performance_budget(self.layout, context.scene)


class VIEW3D_PT_blendengine_analyzer(BE_View3DPanel, Panel):
    bl_label = "Scene Analyzer"
    bl_category = "Optimize"

    def draw(self, context):
        _draw_scene_analyzer(self.layout, context.scene)


class VIEW3D_PT_blendengine_profiler(BE_View3DPanel, Panel):
    bl_label = "Profiler"
    bl_category = "Profiler"

    def draw(self, context):
        _draw_profiler(self.layout, context.scene)


class VIEW3D_PT_blendengine_console(BE_View3DPanel, Panel):
    bl_label = "Console / Logs"
    bl_category = "Console"

    def draw(self, context):
        _draw_console(self.layout, context.scene)


class VIEW3D_PT_blendengine_audio_vfx_lighting(BE_View3DPanel, Panel):
    bl_label = "Audio / VFX / Lighting"
    bl_category = "Assets"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_audio_vfx_lighting(self.layout, context.scene)


class VIEW3D_PT_blendengine_plugins(BE_View3DPanel, Panel):
    bl_label = "Plugins / Marketplace / VCS"
    bl_category = "Ship"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, _context):
        _draw_plugins_marketplace_vcs(self.layout)


class VIEW3D_PT_blendengine_test_run(BE_View3DPanel, Panel):
    bl_label = "Run Game"
    bl_category = "Play Mode"

    def draw(self, context):
        _draw_test_run(self.layout, context.scene)


class VIEW3D_PT_blendengine_play_mode_console(BE_View3DPanel, Panel):
    bl_label = "Play Mode Console"
    bl_category = "Play Mode"

    def draw(self, context):
        _draw_console(self.layout, context.scene)


class VIEW3D_PT_blendengine_build(BE_View3DPanel, Panel):
    bl_label = "Cross-Platform Build"
    bl_category = "Ship"

    def draw(self, context):
        _draw_build(self.layout, context.scene)


class SCENE_PT_blendengine_project(BE_ScenePanel, Panel):
    bl_label = "BlendEngine Project"

    def draw(self, context):
        _draw_project_settings(self.layout, context.scene)


class SCENE_PT_blendengine_input(BE_ScenePanel, Panel):
    bl_label = "BlendEngine Input Map"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_input_map(self.layout, context.scene)


class SCENE_PT_blendengine_optimization(BE_ScenePanel, Panel):
    bl_label = "BlendEngine Optimization"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_optimization_profile(self.layout, context.scene)


class SCENE_PT_blendengine_budget(BE_ScenePanel, Panel):
    bl_label = "BlendEngine Performance Budget"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_performance_budget(self.layout, context.scene)


class SCENE_PT_blendengine_analyzer(BE_ScenePanel, Panel):
    bl_label = "BlendEngine Scene Analyzer"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_scene_analyzer(self.layout, context.scene)


class SCENE_PT_blendengine_build(BE_ScenePanel, Panel):
    bl_label = "BlendEngine Build / Export"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_build(self.layout, context.scene)


class OBJECT_PT_blendengine_components(BE_ObjectPanel, Panel):
    bl_label = "BlendEngine Components"

    def draw(self, context):
        _draw_components(self.layout, context.object)


class OBJECT_PT_blendengine_logic(BE_ObjectPanel, Panel):
    bl_label = "BlendEngine No-Code Logic"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_behaviors(self.layout, context.object)
        self.layout.separator()
        _draw_variables(self.layout, context.object)


class OBJECT_PT_blendengine_player(BE_ObjectPanel, Panel):
    bl_label = "BlendEngine Player Controller"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_player_controller(self.layout, context.object)


class OBJECT_PT_blendengine_animation(BE_ObjectPanel, Panel):
    bl_label = "BlendEngine Animation States"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_animation_controller(self.layout, context.object)


class OBJECT_PT_blendengine_optimization(BE_ObjectPanel, Panel):
    bl_label = "BlendEngine Optimization"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_object_optimization(self.layout, context.object)


classes = (
    TOPBAR_MT_blendengine,
    BE_MT_editor_quality,
    OBJECT_PT_blendengine_inspector,
    BE_UL_components,
    BE_UL_behaviors,
    BE_UL_events,
    BE_UL_conditions,
    BE_UL_actions,
    BE_UL_variables,
    BE_UL_input_bindings,
    BE_UL_animation_states,
    BE_UL_animation_transitions,
    BE_UL_performance_messages,
    VIEW3D_PT_blendengine_engine_hub,
    VIEW3D_PT_blendengine_smart_viewport,
    VIEW3D_PT_blendengine_world,
    VIEW3D_PT_blendengine_inspector,
    VIEW3D_PT_blendengine_assets,
    VIEW3D_PT_blendengine_materials,
    VIEW3D_PT_blendengine_quick_start,
    VIEW3D_PT_blendengine_object,
    VIEW3D_PT_blendengine_player,
    VIEW3D_PT_blendengine_logic,
    VIEW3D_PT_blendengine_visual_code,
    VIEW3D_PT_blendengine_animation,
    VIEW3D_PT_blendengine_character,
    VIEW3D_PT_blendengine_ai,
    VIEW3D_PT_blendengine_terrain,
    VIEW3D_PT_blendengine_physics,
    VIEW3D_PT_blendengine_health,
    VIEW3D_PT_blendengine_input,
    VIEW3D_PT_blendengine_multiplayer,
    VIEW3D_PT_blendengine_optimization,
    VIEW3D_PT_blendengine_budget,
    VIEW3D_PT_blendengine_analyzer,
    VIEW3D_PT_blendengine_profiler,
    VIEW3D_PT_blendengine_console,
    VIEW3D_PT_blendengine_audio_vfx_lighting,
    VIEW3D_PT_blendengine_test_run,
    VIEW3D_PT_blendengine_play_mode_console,
    VIEW3D_PT_blendengine_build,
    VIEW3D_PT_blendengine_plugins,
    SCENE_PT_blendengine_project,
    SCENE_PT_blendengine_input,
    SCENE_PT_blendengine_optimization,
    SCENE_PT_blendengine_budget,
    SCENE_PT_blendengine_analyzer,
    SCENE_PT_blendengine_build,
    OBJECT_PT_blendengine_components,
    OBJECT_PT_blendengine_logic,
    OBJECT_PT_blendengine_player,
    OBJECT_PT_blendengine_animation,
    OBJECT_PT_blendengine_optimization,
)


def register():
    global _ORIGINAL_VIEW_HEADER
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_editor_menus.append(draw_topbar_menu)
    _ORIGINAL_VIEW_HEADER = bpy.types.VIEW3D_HT_header.draw
    bpy.types.VIEW3D_HT_header.draw = _draw_engine_view_header
    bpy.types.OUTLINER_HT_header.prepend(_draw_engine_outliner_header)
    bpy.types.PROPERTIES_HT_header.prepend(_draw_engine_properties_header)


def unregister():
    bpy.types.VIEW3D_HT_header.draw = _ORIGINAL_VIEW_HEADER
    bpy.types.OUTLINER_HT_header.remove(_draw_engine_outliner_header)
    bpy.types.PROPERTIES_HT_header.remove(_draw_engine_properties_header)
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_topbar_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


_ORIGINAL_VIEW_HEADER = None
