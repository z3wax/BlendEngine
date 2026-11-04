# SPDX-License-Identifier: GPL-2.0-or-later
"""Avoid redundant renderer/depsgraph invalidations without changing values."""

from mathutils import Euler, Vector


def vector(owner, name, value):
    """Write the identical RNA value only when it actually changes."""
    current = getattr(owner, name)
    if tuple(current) == tuple(value):
        return False
    setattr(owner, name, value)
    return True


def scalar(owner, name, value):
    # mathutils stores components in float32. Compare the value the original
    # setter would actually store, not an unrounded Python float such as pi.
    if isinstance(owner, (Euler, Vector)):
        value = Vector((value, 0.0, 0.0)).x
    if getattr(owner, name) == value:
        return False
    setattr(owner, name, value)
    return True


def hidden(obj, value):
    if obj.hide_get() == value:
        return False
    obj.hide_set(value)
    return True
