# SPDX-License-Identifier: GPL-2.0-or-later
#
# Input-map helpers for BlendEngine.

from . import utils


def ensure_defaults(scene):
    return utils.ensure_default_input_bindings(scene)


def add_binding(scene, action="CUSTOM", key=""):
    input_map = scene.blendengine_input_map
    binding = input_map.bindings.add()
    binding.action = action
    binding.name = action.replace("_", " ").title() if action != "CUSTOM" else "Custom Action"
    binding.key = key
    binding.device = "MOUSE" if "MOUSE" in key else "KEYBOARD"
    input_map.active_binding_index = len(input_map.bindings) - 1
    return binding


def remove_active_binding(scene):
    input_map = scene.blendengine_input_map
    return utils.remove_active_item(input_map.bindings, input_map, "active_binding_index")


def binding_display_name(binding):
    action = binding.custom_action if binding.action == "CUSTOM" and binding.custom_action else binding.action
    return "%s: %s" % (action.replace("_", " ").title(), binding.key)


def register():
    pass


def unregister():
    pass
