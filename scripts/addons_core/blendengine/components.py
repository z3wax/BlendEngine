# SPDX-License-Identifier: GPL-2.0-or-later
#
# Component setup helpers for BlendEngine.

import bpy

from . import utils


def add_player_controller(obj, camera=None):
    utils.ensure_component(obj, "PLAYER_CONTROLLER", tag="Player")
    settings = utils.mark_game_object(obj, tag="Player")
    player = settings.player_controller
    player.enabled = True
    if camera is not None:
        player.camera_follow = camera
    return player


def add_collider(obj, tag=""):
    component = utils.ensure_component(obj, "COLLIDER", tag=tag)
    component.notes = "Collider data. Add Rigidbody to enable Blender physics preview."
    return component


def add_rigidbody(context, obj):
    component = utils.ensure_component(obj, "RIGIDBODY")
    component.notes = "Uses Blender rigid body data when available."

    previous_active = context.view_layer.objects.active
    previous_selection = [selected for selected in context.selected_objects]
    try:
        for selected in previous_selection:
            selected.select_set(False)
        context.view_layer.objects.active = obj
        obj.select_set(True)
        if obj.rigid_body is None:
            bpy.ops.rigidbody.object_add(type="ACTIVE")
        if obj.rigid_body:
            obj.rigid_body.mass = 1.0
            obj.rigid_body.collision_shape = "CAPSULE" if obj.name.lower().startswith("player") else "BOX"
    finally:
        obj.select_set(False)
        for selected in previous_selection:
            selected.select_set(True)
        if previous_active is not None:
            context.view_layer.objects.active = previous_active
    return component


def add_npc_behavior(obj, template="IDLE", target=None):
    utils.ensure_component(obj, "NPC_CONTROLLER", tag="NPC")
    settings = utils.mark_game_object(obj, tag="NPC")
    npc = settings.npc_behavior
    npc.enabled = True
    npc.behavior_template = template
    if target is not None:
        npc.target_object = target
    return npc


def add_trigger_zone(obj):
    component = utils.ensure_component(obj, "TRIGGER_ZONE", tag="Trigger")
    component.notes = "Trigger Zone runs On Enter Trigger events in the runtime."
    obj.display_type = "WIRE"
    obj.show_in_front = True
    return component


def add_health(obj, max_health=100.0):
    utils.ensure_component(obj, "HEALTH")
    settings = utils.mark_game_object(obj)
    health = settings.health
    health.enabled = True
    health.max_health = max_health
    health.current_health = max_health
    return health


def add_animation_controller(obj):
    return utils.ensure_basic_animation_states(obj)


def register():
    pass


def unregister():
    pass
