# SPDX-License-Identifier: GPL-2.0-or-later
#
# Small helpers shared by BlendEngine modules.

import bpy
import math


COMPONENT_LABELS = {
    "TRANSFORM": "Transform",
    "MESH_RENDERER": "Mesh Renderer",
    "COLLIDER": "Collider",
    "RIGIDBODY": "Rigidbody",
    "PLAYER_CONTROLLER": "Player Controller",
    "NPC_CONTROLLER": "NPC Controller",
    "CAMERA_CONTROLLER": "Camera Controller",
    "TRIGGER_ZONE": "Trigger Zone",
    "HEALTH": "Health",
    "DAMAGE": "Damage",
    "INVENTORY": "Inventory",
    "DIALOGUE": "Dialogue",
    "QUEST": "Quest",
    "DOOR": "Door",
    "PICKUP_ITEM": "Pickup Item",
    "WEAPON": "Weapon",
    "UI_ELEMENT": "UI Element",
    "AUDIO_SOURCE": "Audio Source",
    "ANIMATION_CONTROLLER": "Animation Controller",
    "STATIC_OBJECT": "Static Object",
    "DYNAMIC_OBJECT": "Dynamic Object",
    "OCCLUDER": "Occluder",
    "LOD_GROUP": "LOD Group",
    "IMPOSTOR_CANDIDATE": "Impostor Candidate",
    "BAKED_LIGHTING_CANDIDATE": "Baked Lighting Candidate",
    "COLLIDER_SIMPLIFICATION": "Collider Simplification",
    "DISABLE_WHEN_FAR": "Disable When Far",
    "ANIMATION_CULLING": "Animation Culling",
    "PHYSICS_SLEEP": "Physics Sleep",
    "MERGE_CANDIDATE": "Merge Candidate",
    "INSTANCING_CANDIDATE": "Instancing Candidate",
}


DEFAULT_INPUT_BINDINGS = (
    ("MOVE_FORWARD", "W", 1.0),
    ("MOVE_BACKWARD", "S", 1.0),
    ("MOVE_LEFT", "A", 1.0),
    ("MOVE_RIGHT", "D", 1.0),
    ("JUMP", "SPACE", 1.0),
    ("SPRINT", "LEFT_SHIFT", 1.0),
    ("CROUCH", "LEFT_CTRL", 1.0),
    ("INTERACT", "E", 1.0),
    ("ATTACK", "F", 1.0),
    ("AIM", "R", 1.0),
    ("PAUSE", "ESC", 1.0),
    ("INVENTORY", "I", 1.0),
)


ENGINE_PAGE_NAMES = {
    "STUDIO": "BlendEngine",
    "WORLD": "World Builder",
    "LOGIC": "Logic Lab",
    "PLAY": "Play Mode",
    "BUILD": "Build & Export",
}


ENGINE_PAGE_LABELS = {
    "BlendEngine": "Studio",
    "World Builder": "World",
    "Logic Lab": "Logic",
    "Play Mode": "Play",
    "Build & Export": "Ship",
}


def active_object(context):
    return getattr(context, "object", None) or getattr(context, "active_object", None)


def game_settings(obj):
    if obj is None:
        return None
    return obj.blendengine_object


def mark_game_object(obj, tag=""):
    settings = game_settings(obj)
    if settings is None:
        return None
    settings.is_game_object = True
    if tag and not settings.object_tag:
        settings.object_tag = tag
    return settings


def component_label(component_type):
    return COMPONENT_LABELS.get(component_type, component_type.replace("_", " ").title())


def find_component(obj, component_type):
    settings = game_settings(obj)
    if settings is None:
        return None
    for component in settings.components:
        if component.component_type == component_type:
            return component
    return None


def ensure_component(obj, component_type, name=None, tag=""):
    settings = mark_game_object(obj, tag=tag)
    if settings is None:
        return None
    component = find_component(obj, component_type)
    if component is None:
        component = settings.components.add()
        component.component_type = component_type
        component.name = name or component_label(component_type)
        component.enabled = True
        if tag:
            component.tag = tag
        settings.active_component_index = len(settings.components) - 1
    return component


def remove_active_item(collection, owner, active_index_attr):
    if not collection:
        return False
    index = max(0, min(getattr(owner, active_index_attr), len(collection) - 1))
    collection.remove(index)
    setattr(owner, active_index_attr, max(0, min(index, len(collection) - 1)))
    return True


def active_item(collection, index):
    if not collection:
        return None
    return collection[max(0, min(index, len(collection) - 1))]


def ensure_project_defaults(scene):
    project = scene.blendengine_project
    if project.default_scene is None:
        project.default_scene = scene
    if not project.game_title:
        project.game_title = "My BlendEngine Game"
    return project


def ensure_default_input_bindings(scene):
    input_map = scene.blendengine_input_map
    if input_map.bindings:
        return input_map

    for action, key, scale in DEFAULT_INPUT_BINDINGS:
        binding = input_map.bindings.add()
        binding.action = action
        binding.name = action.replace("_", " ").title()
        binding.device = "MOUSE" if "MOUSE" in key else "KEYBOARD"
        binding.key = key
        binding.scale = scale

    input_map.active_binding_index = 0
    return input_map


def find_player_object(scene):
    for obj in scene.objects:
        settings = game_settings(obj)
        if settings and settings.player_controller.enabled:
            return obj
    for obj in scene.objects:
        settings = game_settings(obj)
        if settings and find_component(obj, "PLAYER_CONTROLLER"):
            return obj
    return None


def ensure_example_behavior(obj):
    settings = mark_game_object(obj)
    if settings is None:
        return None

    for behavior in settings.behaviors:
        if behavior.name == "On Start Welcome":
            return behavior

    behavior = settings.behaviors.add()
    behavior.name = "On Start Welcome"
    behavior.description = "When the scene starts, write a friendly test log."
    behavior.enabled = True

    event = behavior.events.add()
    event.name = "On Start"
    event.event_type = "ON_START"

    action = behavior.actions.add()
    action.name = "Show Log"
    action.action_type = "SHOW_LOG"
    action.text_value = "BlendEngine test run started."

    settings.active_behavior_index = len(settings.behaviors) - 1
    return behavior


def ensure_basic_animation_states(obj):
    settings = mark_game_object(obj)
    controller = settings.animation_controller
    controller.enabled = True
    ensure_component(obj, "ANIMATION_CONTROLLER")

    existing = {state.name for state in controller.states}
    for name, state_type in (("Idle", "IDLE"), ("Walk", "WALK"), ("Run", "RUN"), ("Jump", "JUMP")):
        if name in existing:
            continue
        state = controller.states.add()
        state.name = name
        state.state_type = state_type
        state.loop = state_type not in {"JUMP"}

    if not controller.default_state:
        controller.default_state = "Idle"
    return controller


def _set_area_menus(area, visible):
    try:
        area.show_menus = visible
    except Exception:
        pass


def _set_space_region(space, name, value):
    try:
        setattr(space, name, value)
    except Exception:
        pass


def _workspace_name(context):
    if context.window and context.window.workspace:
        return context.window.workspace.name
    return ""


def engine_page_name(page):
    return ENGINE_PAGE_NAMES.get(page, ENGINE_PAGE_NAMES["STUDIO"])


def _schedule_screen_configuration(workspace_name):
    def _apply():
        context = bpy.context
        if context.window and context.window.workspace and context.window.workspace.name == workspace_name:
            configure_current_screen_for_blendengine(context)
        return None

    try:
        bpy.app.timers.register(_apply, first_interval=0.05)
    except Exception:
        pass


def enter_camera_view(context):
    scene = context.scene
    if scene is None or scene.camera is None or context.screen is None:
        return False
    changed = False
    for area in context.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue
            region_3d = getattr(space, "region_3d", None)
            if region_3d is not None:
                region_3d.view_perspective = "CAMERA"
                window_region = next((region for region in area.regions if region.type == "WINDOW"), None)
                camera_aspect = scene.render.resolution_x / max(scene.render.resolution_y, 1)
                fit = 0.94
                if window_region and window_region.width and window_region.height:
                    fit *= min(1.0, window_region.height * camera_aspect / window_region.width)
                zoom = 50.0 * (math.sqrt(4.0 * fit) - math.sqrt(2.0))
                _set_space_region(region_3d, "view_camera_zoom", zoom)
                _set_space_region(region_3d, "view_camera_offset", (0.0, 0.0))
                changed = True
            _set_space_region(space, "lock_camera", True)
    camera = scene.camera
    if camera is not None and getattr(camera, "data", None) is not None:
        _set_space_region(camera.data, "show_passepartout", True)
        _set_space_region(camera.data, "passepartout_alpha", 1.0)
    return changed


def configure_current_screen_for_blendengine(context):
    from . import editor
    editor.configure_screen(context)


def activate_or_duplicate_workspace(context, name="BlendEngine", source_name="BlendEngine"):
    window = context.window
    if window is None:
        return None

    existing = bpy.data.workspaces.get(name)
    if existing:
        window.workspace = existing
        if bpy.app.background:
            configure_current_screen_for_blendengine(context)
        else:
            _schedule_screen_configuration(name)
        return existing

    source = bpy.data.workspaces.get(source_name)
    if source is not None:
        window.workspace = source

    before_names = {workspace.name for workspace in bpy.data.workspaces}
    result = bpy.ops.workspace.duplicate()
    if "CANCELLED" in result:
        return None

    workspace = window.workspace
    for candidate in bpy.data.workspaces:
        if candidate.name not in before_names:
            workspace = candidate
            break
    workspace.name = name
    window.workspace = workspace
    if bpy.app.background:
        configure_current_screen_for_blendengine(context)
    else:
        _schedule_screen_configuration(name)
    return workspace


def activate_engine_page(context, page="STUDIO"):
    name = engine_page_name(page)
    source = "BlendEngine"
    workspace = activate_or_duplicate_workspace(context, name, source_name=source)
    if workspace is not None:
        if bpy.app.background:
            configure_current_screen_for_blendengine(context)
        else:
            _schedule_screen_configuration(name)
    return workspace
