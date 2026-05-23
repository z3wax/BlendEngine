# SPDX-License-Identifier: GPL-2.0-or-later
#
# No-code animation-state helpers.

from . import utils


def ensure_controller(obj):
    return utils.ensure_basic_animation_states(obj)


def add_state(obj, name="Custom State", state_type="CUSTOM"):
    controller = ensure_controller(obj)
    state = controller.states.add()
    state.name = name
    state.state_type = state_type
    state.loop = True
    controller.active_state_index = len(controller.states) - 1
    return state


def remove_active_state(obj):
    controller = obj.blendengine_object.animation_controller
    return utils.remove_active_item(controller.states, controller, "active_state_index")


def add_transition(obj, from_state="Idle", to_state="Walk"):
    controller = ensure_controller(obj)
    transition = controller.transitions.add()
    transition.name = "%s -> %s" % (from_state, to_state)
    transition.from_state = from_state
    transition.to_state = to_state
    controller.active_transition_index = len(controller.transitions) - 1
    return transition


def remove_active_transition(obj):
    controller = obj.blendengine_object.animation_controller
    return utils.remove_active_item(controller.transitions, controller, "active_transition_index")


def register():
    pass


def unregister():
    pass
