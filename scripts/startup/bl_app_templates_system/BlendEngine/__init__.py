# SPDX-License-Identifier: GPL-2.0-or-later
"""Compatibility entry for saved BlendEngine template preferences.

The editor UI is now built into bl_ui and the screen editor C module. Opening
this template must not enable an add-on, generate a demo scene, change input
bindings, or hide the user's workspaces. Native features also work without it.
"""


def register():
    pass


def unregister():
    pass
