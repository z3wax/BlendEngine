# SPDX-License-Identifier: GPL-2.0-or-later
#
# Beginner AI behavior-template helpers.

from . import components


def apply_template(obj, template="IDLE", target=None):
    npc = components.add_npc_behavior(obj, template=template, target=target)

    if template == "PATROL":
        npc.move_speed = 2.5
        npc.patrol_radius = 8.0
    elif template == "FOLLOW_PLAYER":
        npc.move_speed = 3.5
        npc.detection_range = 20.0
    elif template == "ATTACK":
        npc.move_speed = 4.0
        npc.attack_range = 2.0
    elif template == "QUEST_GIVER":
        npc.dialogue_text = "I have a quest for you."
        npc.quest_id = "quest_001"
    elif template == "SHOPKEEPER":
        npc.dialogue_text = "Welcome to my shop."
    elif template == "ENEMY_BOSS":
        npc.move_speed = 3.0
        npc.detection_range = 25.0
        npc.attack_range = 3.0

    return npc


def register():
    pass


def unregister():
    pass
