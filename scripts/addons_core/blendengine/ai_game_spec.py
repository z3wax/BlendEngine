# SPDX-License-Identifier: GPL-2.0-or-later
#
# AI Game Creator: the game spec format.
#
# A "game spec" is a small JSON document that describes a whole game: world,
# player, enemies, pickups, hazards, and the win condition. Claude (or the
# offline planner) writes a spec from a plain-language idea, and
# ``ai_game_builder`` turns it into a playable BlendEngine scene.
#
# This module has no ``bpy`` dependency so it can be unit tested with plain
# Python. Every spec that reaches the builder goes through ``normalize_spec``,
# which clamps numbers, fixes enums, and enforces object budgets, so a bad or
# hostile model response can never create an unbounded scene.

import copy
import hashlib
import json
import math
import re


SPEC_VERSION = 1

DIMENSIONS = ("3D", "2D")
CAMERAS = ("THIRD_PERSON", "FIRST_PERSON", "TOP_DOWN", "SIDE_VIEW")
DIFFICULTIES = ("EASY", "NORMAL", "HARD")
THEMES = (
    "FOREST", "DESERT", "SNOW", "NEON_CITY", "SPACE",
    "DUNGEON", "ISLAND", "VOLCANO", "CANDY", "GRASSLAND",
)
TIMES_OF_DAY = ("DAY", "SUNSET", "NIGHT")
PLAYER_SHAPES = ("CAPSULE", "ROBOT", "CUBE", "SPHERE")
ENEMY_SHAPES = ("BLOB", "BRUTE", "ROBOT", "SPIKY", "GHOST", "DRONE")
ENEMY_BEHAVIORS = ("PATROL", "FOLLOW_PLAYER", "ATTACK", "GUARD_AREA", "FLEE", "ENEMY_BOSS", "IDLE")
COLLECTIBLE_SHAPES = ("COIN", "GEM", "STAR", "ORB", "KEY", "CRATE")
HAZARD_KINDS = ("LAVA", "SPIKES", "POISON", "LASER")
PROP_KINDS = (
    "TREE", "PINE", "PALM", "ROCK", "CACTUS", "BUILDING",
    "CRYSTAL", "PILLAR", "CRATE", "LAMP", "MUSHROOM",
)
GOAL_TYPES = ("COLLECT_ALL", "REACH_EXIT", "DEFEAT_ALL", "SURVIVE")

# Object budgets. They keep generated scenes inside the engine's 1 GB / mobile
# targets and bound the work a single prompt can trigger.
MAX_ENEMY_GROUPS = 4
MAX_ENEMIES_PER_GROUP = 12
MAX_ENEMIES_TOTAL = 24
MAX_COLLECTIBLE_GROUPS = 3
MAX_COLLECTIBLES_PER_GROUP = 30
MAX_COLLECTIBLES_TOTAL = 40
MAX_HAZARD_GROUPS = 3
MAX_HAZARDS_PER_GROUP = 8
MAX_HAZARDS_TOTAL = 12
MAX_PROP_GROUPS = 6
MAX_PROPS_PER_GROUP = 30
MAX_PROPS_TOTAL = 80
MAX_PLATFORMS = 16
MAX_HEALTH_PICKUPS = 8
MAX_DESIGN_NOTES = 6
MAX_TEXT = 160


THEME_PRESETS = {
    "FOREST": {
        "ground": "#3f6b35", "sky": "#9fc8e8", "accent": "#f2c14e", "wall": "#6b5b45",
        "time": "DAY", "hilliness": 0.45,
        "props": (("TREE", 14), ("PINE", 6), ("ROCK", 6), ("MUSHROOM", 4)),
        "enemy": "wolf", "collectible": "coin", "hazard": "POISON",
    },
    "DESERT": {
        "ground": "#d9b26f", "sky": "#f3d9a4", "accent": "#e86f2d", "wall": "#b08a55",
        "time": "DAY", "hilliness": 0.6,
        "props": (("CACTUS", 10), ("ROCK", 8), ("PILLAR", 4)),
        "enemy": "scorpion", "collectible": "gem", "hazard": "SPIKES",
    },
    "SNOW": {
        "ground": "#e8f1f7", "sky": "#bcd6ea", "accent": "#4fc3f7", "wall": "#9fb6c8",
        "time": "DAY", "hilliness": 0.5,
        "props": (("PINE", 14), ("ROCK", 6), ("CRYSTAL", 4)),
        "enemy": "yeti", "collectible": "gem", "hazard": "SPIKES",
    },
    "NEON_CITY": {
        "ground": "#2a2d3d", "sky": "#120a24", "accent": "#ff2bd6", "wall": "#363c55",
        "time": "NIGHT", "hilliness": 0.0,
        "props": (("BUILDING", 12), ("LAMP", 5), ("CRATE", 6)),
        "enemy": "drone", "collectible": "orb", "hazard": "LASER",
    },
    "SPACE": {
        "ground": "#5a4f6e", "sky": "#05060f", "accent": "#7cf7ff", "wall": "#3a3550",
        "time": "NIGHT", "hilliness": 0.35,
        "props": (("CRYSTAL", 10), ("ROCK", 8), ("PILLAR", 3)),
        "enemy": "alien", "collectible": "star", "hazard": "LASER",
    },
    "DUNGEON": {
        "ground": "#58524c", "sky": "#0d0b0a", "accent": "#ffb347", "wall": "#6a625a",
        "time": "NIGHT", "hilliness": 0.0,
        "props": (("PILLAR", 10), ("CRATE", 6), ("ROCK", 4), ("LAMP", 4)),
        "enemy": "skeleton", "collectible": "key", "hazard": "SPIKES",
    },
    "ISLAND": {
        "ground": "#e6d39a", "sky": "#8fd3ff", "accent": "#00b4a6", "wall": "#8a6a45",
        "time": "DAY", "hilliness": 0.3,
        "props": (("PALM", 12), ("ROCK", 6), ("CRATE", 3)),
        "enemy": "pirate", "collectible": "coin", "hazard": "SPIKES",
    },
    "VOLCANO": {
        "ground": "#5b4038", "sky": "#3a1a12", "accent": "#ff5a1f", "wall": "#5a4a44",
        "time": "SUNSET", "hilliness": 0.7,
        "props": (("ROCK", 14), ("CRYSTAL", 4), ("PILLAR", 3)),
        "enemy": "monster", "collectible": "gem", "hazard": "LAVA",
    },
    "CANDY": {
        "ground": "#ffc6e0", "sky": "#ffe6f5", "accent": "#7a5cff", "wall": "#ff8fc2",
        "time": "DAY", "hilliness": 0.35,
        "props": (("MUSHROOM", 10), ("CRYSTAL", 6), ("TREE", 4)),
        "enemy": "slime", "collectible": "star", "hazard": "POISON",
    },
    "GRASSLAND": {
        "ground": "#6fa84b", "sky": "#a8d8ff", "accent": "#ffd23f", "wall": "#8a7a5a",
        "time": "DAY", "hilliness": 0.4,
        "props": (("TREE", 8), ("ROCK", 6), ("CRATE", 3)),
        "enemy": "slime", "collectible": "coin", "hazard": "SPIKES",
    },
}

# Enemy archetypes used by the offline planner and as theme defaults.
ENEMY_ARCHETYPES = {
    "zombie": {"name": "Zombie", "shape": "BRUTE", "behavior": "ATTACK", "color": "#6f9a45", "size": 1.0, "speed": 2.4, "health": 60, "damage": 10},
    "robot": {"name": "Robot", "shape": "ROBOT", "behavior": "ATTACK", "color": "#9aa4b1", "size": 1.0, "speed": 3.0, "health": 80, "damage": 12},
    "drone": {"name": "Drone", "shape": "DRONE", "behavior": "FOLLOW_PLAYER", "color": "#ff3355", "size": 0.7, "speed": 4.0, "health": 30, "damage": 6},
    "slime": {"name": "Slime", "shape": "BLOB", "behavior": "PATROL", "color": "#3fd16b", "size": 0.8, "speed": 2.0, "health": 30, "damage": 6},
    "monster": {"name": "Monster", "shape": "BRUTE", "behavior": "ATTACK", "color": "#8b2bd9", "size": 1.3, "speed": 2.8, "health": 90, "damage": 14},
    "alien": {"name": "Alien", "shape": "SPIKY", "behavior": "FOLLOW_PLAYER", "color": "#41f0c8", "size": 1.0, "speed": 3.4, "health": 50, "damage": 9},
    "ghost": {"name": "Ghost", "shape": "GHOST", "behavior": "FOLLOW_PLAYER", "color": "#cfe8ff", "size": 1.0, "speed": 2.6, "health": 40, "damage": 8},
    "skeleton": {"name": "Skeleton", "shape": "BRUTE", "behavior": "PATROL", "color": "#e8e2c8", "size": 1.0, "speed": 2.6, "health": 45, "damage": 8},
    "wolf": {"name": "Wolf", "shape": "BRUTE", "behavior": "FOLLOW_PLAYER", "color": "#6b6b6b", "size": 0.9, "speed": 4.2, "health": 40, "damage": 9},
    "spider": {"name": "Spider", "shape": "SPIKY", "behavior": "ATTACK", "color": "#2a2a2a", "size": 0.8, "speed": 3.6, "health": 35, "damage": 7},
    "scorpion": {"name": "Scorpion", "shape": "SPIKY", "behavior": "PATROL", "color": "#a0522d", "size": 0.9, "speed": 3.0, "health": 45, "damage": 9},
    "yeti": {"name": "Yeti", "shape": "BRUTE", "behavior": "ATTACK", "color": "#f4f8ff", "size": 1.5, "speed": 2.2, "health": 120, "damage": 15},
    "pirate": {"name": "Pirate", "shape": "BRUTE", "behavior": "PATROL", "color": "#b5452b", "size": 1.0, "speed": 3.0, "health": 60, "damage": 10},
    "ninja": {"name": "Ninja", "shape": "BRUTE", "behavior": "ATTACK", "color": "#222233", "size": 0.95, "speed": 4.6, "health": 45, "damage": 11},
    "soldier": {"name": "Guard", "shape": "ROBOT", "behavior": "GUARD_AREA", "color": "#4b5d3a", "size": 1.0, "speed": 3.0, "health": 70, "damage": 12},
    "dragon": {"name": "Dragon", "shape": "SPIKY", "behavior": "ENEMY_BOSS", "color": "#d43a1a", "size": 3.0, "speed": 3.0, "health": 600, "damage": 25},
    "boss": {"name": "Boss", "shape": "BRUTE", "behavior": "ENEMY_BOSS", "color": "#c0162c", "size": 2.6, "speed": 2.8, "health": 400, "damage": 20},
}

COLLECTIBLE_ARCHETYPES = {
    "coin": {"name": "Coin", "shape": "COIN", "color": "#ffc21a", "points": 10},
    "gem": {"name": "Gem", "shape": "GEM", "color": "#38d6ff", "points": 25},
    "star": {"name": "Star", "shape": "STAR", "color": "#ffe14d", "points": 50},
    "orb": {"name": "Energy Cell", "shape": "ORB", "color": "#5cf2ff", "points": 20},
    "key": {"name": "Key", "shape": "KEY", "color": "#ffcf40", "points": 100},
    "crate": {"name": "Treasure", "shape": "CRATE", "color": "#b07a3c", "points": 75},
    "fruit": {"name": "Fruit", "shape": "ORB", "color": "#ff4040", "points": 10},
}

HAZARD_NAMES = {
    "LAVA": "Lava Pool",
    "SPIKES": "Spike Trap",
    "POISON": "Poison Pool",
    "LASER": "Laser Fence",
}


# ---------------------------------------------------------------------------
# JSON Schema used for Claude structured outputs.
# ---------------------------------------------------------------------------

def _obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def _str(description=""):
    schema = {"type": "string"}
    if description:
        schema["description"] = description
    return schema


def _num(description=""):
    schema = {"type": "number"}
    if description:
        schema["description"] = description
    return schema


def _int(description=""):
    schema = {"type": "integer"}
    if description:
        schema["description"] = description
    return schema


def _enum(values, description=""):
    schema = {"type": "string", "enum": list(values)}
    if description:
        schema["description"] = description
    return schema


def _color(description):
    return _str(description + " as #RRGGBB")


def _array(items, description=""):
    schema = {"type": "array", "items": items}
    if description:
        schema["description"] = description
    return schema


SPEC_JSON_SCHEMA = _obj({
    "title": _str("Short game title in the player's language"),
    "tagline": _str("One-sentence pitch in the player's language"),
    "dimension": _enum(DIMENSIONS),
    "camera": _enum(CAMERAS, "SIDE_VIEW only for 2D games"),
    "difficulty": _enum(DIFFICULTIES),
    "world": _obj({
        "theme": _enum(THEMES),
        "time_of_day": _enum(TIMES_OF_DAY),
        "size": _num("Arena width in meters, 24-120"),
        "hilliness": _num("0 = flat, 1 = rolling hills at the arena edges"),
        "ground_color": _color("Ground color"),
        "sky_color": _color("Sky color"),
        "accent_color": _color("Glow and highlight color"),
    }),
    "player": _obj({
        "name": _str(),
        "shape": _enum(PLAYER_SHAPES),
        "color": _color("Body color"),
        "walk_speed": _num("1-15 m/s"),
        "run_speed": _num("Sprint speed, above walk_speed, up to 25 m/s"),
        "jump_force": _num("0-20; 0 disables jumping"),
        "max_health": _num("1-1000"),
        "can_shoot": {"type": "boolean"},
    }),
    "enemies": _array(_obj({
        "name": _str(),
        "count": _int("0-12"),
        "behavior": _enum(ENEMY_BEHAVIORS),
        "shape": _enum(ENEMY_SHAPES),
        "color": _color("Body color"),
        "size": _num("0.4-4, 1 = human sized"),
        "speed": _num("0-12 m/s"),
        "health": _num("1-2000"),
        "damage": _num("Damage per hit to the player, 0-100"),
    }), "Up to 4 enemy groups, at most 24 enemies in total"),
    "collectibles": _array(_obj({
        "name": _str(),
        "count": _int("0-30"),
        "shape": _enum(COLLECTIBLE_SHAPES),
        "color": _color("Color"),
        "points": _int("Score per pickup"),
    }), "Up to 3 groups, at most 40 pickups in total"),
    "hazards": _array(_obj({
        "name": _str(),
        "count": _int("0-8"),
        "kind": _enum(HAZARD_KINDS),
        "damage": _num("Damage when touched, 0-100"),
    }), "Up to 3 groups"),
    "props": _array(_obj({
        "kind": _enum(PROP_KINDS),
        "count": _int("0-30"),
    }), "Scenery, up to 6 groups and 80 pieces"),
    "platforms": _int("Floating platforms to jump on, 0-16"),
    "health_pickups": _int("0-8"),
    "goal": _obj({
        "type": _enum(GOAL_TYPES),
        "target_count": _int("COLLECT_ALL: pickups needed; REACH_EXIT: pickups needed before the exit opens (0 = none)"),
        "time_limit_seconds": _num("SURVIVE: seconds to survive; other goals: 0 for no limit"),
        "description": _str("One-line objective shown to the player, in the player's language"),
    }),
    "messages": _obj({
        "intro": _str(),
        "win": _str(),
        "lose": _str(),
    }),
    "design_notes": _array(_str(), "2-4 short notes for the creator: what you built and how to play"),
})


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean_text(value, default="", limit=MAX_TEXT):
    if not isinstance(value, str):
        value = default if value is None else str(value)
    value = _CONTROL_RE.sub(" ", value).strip()
    value = re.sub(r"\s+", " ", value)
    if not value:
        value = default
    return value[:limit]


def clean_name(value, default):
    """Short display name that is also safe inside a Blender object name."""
    text = clean_text(value, default, limit=40)
    text = re.sub(r"[^\w \-'.]", "", text, flags=re.UNICODE).strip()
    return text or default


def parse_hex_color(value, default):
    if isinstance(value, str):
        match = _HEX_RE.match(value.strip())
        if match:
            digits = match.group(1)
            if len(digits) == 3:
                digits = "".join(ch * 2 for ch in digits)
            return "#" + digits.lower()
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            channels = [max(0.0, min(1.0, float(v))) for v in value[:3]]
            return "#" + "".join("%02x" % int(round(c * 255)) for c in channels)
        except (TypeError, ValueError):
            pass
    return default


def hex_to_srgb(value):
    value = parse_hex_color(value, "#808080")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def _srgb_channel_to_linear(channel):
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def hex_to_linear(value):
    """Convert a #RRGGBB sRGB color to Blender's linear color space."""
    return tuple(_srgb_channel_to_linear(c) for c in hex_to_srgb(value))


def clamp_number(value, low, high, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(number) or math.isinf(number):
        return float(default)
    return max(float(low), min(float(high), number))


def clamp_int(value, low, high, default):
    return int(round(clamp_number(value, low, high, default)))


def pick_enum(value, allowed, default):
    if isinstance(value, str):
        candidate = value.strip().upper().replace("-", "_").replace(" ", "_")
        if candidate in allowed:
            return candidate
    return default


def _limit_total(groups, per_group_cap, total_cap):
    """Trim group counts so their sum stays within ``total_cap``."""
    remaining = total_cap
    for group in groups:
        group["count"] = max(0, min(int(group["count"]), per_group_cap, remaining))
        remaining -= group["count"]
    return [group for group in groups if group["count"] > 0]


def stable_seed(*parts):
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


# ---------------------------------------------------------------------------
# Defaults and normalization.
# ---------------------------------------------------------------------------

def enemy_from_archetype(key, count, overrides=None):
    base = dict(ENEMY_ARCHETYPES.get(key, ENEMY_ARCHETYPES["slime"]))
    base["count"] = count
    if overrides:
        base.update(overrides)
    return base


def collectible_from_archetype(key, count, overrides=None):
    base = dict(COLLECTIBLE_ARCHETYPES.get(key, COLLECTIBLE_ARCHETYPES["coin"]))
    base["count"] = count
    if overrides:
        base.update(overrides)
    return base


def default_spec(theme="FOREST"):
    theme = theme if theme in THEME_PRESETS else "FOREST"
    preset = THEME_PRESETS[theme]
    return {
        "version": SPEC_VERSION,
        "title": "My AI Game",
        "tagline": "A small adventure built by BlendEngine AI.",
        "dimension": "3D",
        "camera": "THIRD_PERSON",
        "difficulty": "NORMAL",
        "world": {
            "theme": theme,
            "time_of_day": preset["time"],
            "size": 48.0,
            "hilliness": preset["hilliness"],
            "ground_color": preset["ground"],
            "sky_color": preset["sky"],
            "accent_color": preset["accent"],
        },
        "player": {
            "name": "Hero",
            "shape": "CAPSULE",
            "color": "#00b8a3",
            "walk_speed": 5.0,
            "run_speed": 8.5,
            "jump_force": 6.5,
            "max_health": 100.0,
            "can_shoot": False,
        },
        "enemies": [enemy_from_archetype(preset["enemy"], 4)],
        "collectibles": [collectible_from_archetype(preset["collectible"], 10)],
        "hazards": [{"name": HAZARD_NAMES[preset["hazard"]], "count": 3, "kind": preset["hazard"], "damage": 15.0}],
        "props": [{"kind": kind, "count": count} for kind, count in preset["props"]],
        "platforms": 3,
        "health_pickups": 2,
        "goal": {
            "type": "COLLECT_ALL",
            "target_count": 10,
            "time_limit_seconds": 0.0,
            "description": "Collect every pickup.",
        },
        "messages": {
            "intro": "Good luck!",
            "win": "You win!",
            "lose": "Game over.",
        },
        "design_notes": [],
    }


def _normalize_enemy(raw, index):
    raw = raw if isinstance(raw, dict) else {}
    behavior = pick_enum(raw.get("behavior"), ENEMY_BEHAVIORS, "ATTACK")
    is_boss = behavior == "ENEMY_BOSS"
    return {
        "name": clean_name(raw.get("name"), "Boss" if is_boss else "Enemy %d" % (index + 1)),
        "count": clamp_int(raw.get("count"), 0, MAX_ENEMIES_PER_GROUP, 1 if is_boss else 3),
        "behavior": behavior,
        "shape": pick_enum(raw.get("shape"), ENEMY_SHAPES, "BRUTE"),
        "color": parse_hex_color(raw.get("color"), "#c0392b"),
        "size": clamp_number(raw.get("size"), 0.4, 4.0, 2.6 if is_boss else 1.0),
        "speed": clamp_number(raw.get("speed"), 0.0, 12.0, 3.0),
        "health": clamp_number(raw.get("health"), 1.0, 2000.0, 400.0 if is_boss else 60.0),
        "damage": clamp_number(raw.get("damage"), 0.0, 100.0, 20.0 if is_boss else 8.0),
    }


def _normalize_collectible(raw, index):
    raw = raw if isinstance(raw, dict) else {}
    return {
        "name": clean_name(raw.get("name"), "Pickup %d" % (index + 1)),
        "count": clamp_int(raw.get("count"), 0, MAX_COLLECTIBLES_PER_GROUP, 8),
        "shape": pick_enum(raw.get("shape"), COLLECTIBLE_SHAPES, "COIN"),
        "color": parse_hex_color(raw.get("color"), "#ffc21a"),
        "points": clamp_int(raw.get("points"), 0, 1000, 10),
    }


def _normalize_hazard(raw, index, theme):
    raw = raw if isinstance(raw, dict) else {}
    kind = pick_enum(raw.get("kind"), HAZARD_KINDS, THEME_PRESETS[theme]["hazard"])
    return {
        "name": clean_name(raw.get("name"), HAZARD_NAMES[kind]),
        "count": clamp_int(raw.get("count"), 0, MAX_HAZARDS_PER_GROUP, 2),
        "kind": kind,
        "damage": clamp_number(raw.get("damage"), 0.0, 100.0, 15.0),
    }


def _normalize_prop(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        "kind": pick_enum(raw.get("kind"), PROP_KINDS, "ROCK"),
        "count": clamp_int(raw.get("count"), 0, MAX_PROPS_PER_GROUP, 4),
    }


def _list(value, limit):
    if not isinstance(value, list):
        return []
    return value[:limit]


def normalize_spec(raw):
    """Return ``(spec, warnings)`` with every field present, typed, and in range."""
    warnings = []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            warnings.append("Spec was not valid JSON; defaults were used.")
            raw = {}
    if not isinstance(raw, dict):
        warnings.append("Spec was not an object; defaults were used.")
        raw = {}

    world_raw = raw.get("world") if isinstance(raw.get("world"), dict) else {}
    theme = pick_enum(world_raw.get("theme"), THEMES, "FOREST")
    preset = THEME_PRESETS[theme]
    spec = default_spec(theme)

    spec["title"] = clean_text(raw.get("title"), spec["title"], limit=60)
    spec["tagline"] = clean_text(raw.get("tagline"), spec["tagline"])
    spec["dimension"] = pick_enum(raw.get("dimension"), DIMENSIONS, "3D")
    camera = pick_enum(raw.get("camera"), CAMERAS, "THIRD_PERSON")
    if spec["dimension"] == "2D":
        camera = "SIDE_VIEW"
    elif camera == "SIDE_VIEW":
        camera = "THIRD_PERSON"
    spec["camera"] = camera
    spec["difficulty"] = pick_enum(raw.get("difficulty"), DIFFICULTIES, "NORMAL")

    world = spec["world"]
    world["time_of_day"] = pick_enum(world_raw.get("time_of_day"), TIMES_OF_DAY, preset["time"])
    world["size"] = clamp_number(world_raw.get("size"), 24.0, 120.0, 48.0)
    world["hilliness"] = clamp_number(world_raw.get("hilliness"), 0.0, 1.0, preset["hilliness"])
    world["ground_color"] = parse_hex_color(world_raw.get("ground_color"), preset["ground"])
    world["sky_color"] = parse_hex_color(world_raw.get("sky_color"), preset["sky"])
    world["accent_color"] = parse_hex_color(world_raw.get("accent_color"), preset["accent"])

    player_raw = raw.get("player") if isinstance(raw.get("player"), dict) else {}
    player = spec["player"]
    player["name"] = clean_name(player_raw.get("name"), player["name"])
    player["shape"] = pick_enum(player_raw.get("shape"), PLAYER_SHAPES, player["shape"])
    player["color"] = parse_hex_color(player_raw.get("color"), player["color"])
    player["walk_speed"] = clamp_number(player_raw.get("walk_speed"), 1.0, 15.0, player["walk_speed"])
    player["run_speed"] = clamp_number(
        player_raw.get("run_speed"), player["walk_speed"], 25.0, max(player["walk_speed"] * 1.6, player["run_speed"]))
    player["jump_force"] = clamp_number(player_raw.get("jump_force"), 0.0, 20.0, player["jump_force"])
    player["max_health"] = clamp_number(player_raw.get("max_health"), 1.0, 1000.0, player["max_health"])
    player["can_shoot"] = bool(player_raw.get("can_shoot", player["can_shoot"]))

    if "enemies" in raw:
        enemies = [_normalize_enemy(item, i) for i, item in enumerate(_list(raw.get("enemies"), MAX_ENEMY_GROUPS))]
    else:
        enemies = spec["enemies"]
    spec["enemies"] = _limit_total(enemies, MAX_ENEMIES_PER_GROUP, MAX_ENEMIES_TOTAL)

    if "collectibles" in raw:
        collectibles = [_normalize_collectible(item, i) for i, item in enumerate(_list(raw.get("collectibles"), MAX_COLLECTIBLE_GROUPS))]
    else:
        collectibles = spec["collectibles"]
    spec["collectibles"] = _limit_total(collectibles, MAX_COLLECTIBLES_PER_GROUP, MAX_COLLECTIBLES_TOTAL)

    if "hazards" in raw:
        hazards = [_normalize_hazard(item, i, theme) for i, item in enumerate(_list(raw.get("hazards"), MAX_HAZARD_GROUPS))]
    else:
        hazards = spec["hazards"]
    spec["hazards"] = _limit_total(hazards, MAX_HAZARDS_PER_GROUP, MAX_HAZARDS_TOTAL)

    if "props" in raw:
        props = [_normalize_prop(item) for item in _list(raw.get("props"), MAX_PROP_GROUPS)]
    else:
        props = spec["props"]
    spec["props"] = _limit_total(props, MAX_PROPS_PER_GROUP, MAX_PROPS_TOTAL)

    spec["platforms"] = clamp_int(raw.get("platforms"), 0, MAX_PLATFORMS, 6 if spec["dimension"] == "2D" else spec["platforms"])
    spec["health_pickups"] = clamp_int(raw.get("health_pickups"), 0, MAX_HEALTH_PICKUPS, spec["health_pickups"])

    goal_raw = raw.get("goal") if isinstance(raw.get("goal"), dict) else {}
    goal = spec["goal"]
    goal["type"] = pick_enum(goal_raw.get("type"), GOAL_TYPES, "COLLECT_ALL")
    goal["description"] = clean_text(goal_raw.get("description"), "")
    goal["target_count"] = clamp_int(goal_raw.get("target_count"), 0, 999, 0)
    goal["time_limit_seconds"] = clamp_number(goal_raw.get("time_limit_seconds"), 0.0, 1800.0, 0.0)

    messages_raw = raw.get("messages") if isinstance(raw.get("messages"), dict) else {}
    for key in ("intro", "win", "lose"):
        spec["messages"][key] = clean_text(messages_raw.get(key), spec["messages"][key])

    spec["design_notes"] = [
        clean_text(note) for note in _list(raw.get("design_notes"), MAX_DESIGN_NOTES) if clean_text(note)
    ]

    _make_goal_playable(spec, warnings)

    seed = raw.get("seed")
    if isinstance(seed, (int, float)) and not isinstance(seed, bool) and math.isfinite(seed):
        spec["seed"] = int(seed) % (2 ** 31)
    else:
        spec["seed"] = stable_seed(spec["title"], theme, spec["goal"]["type"]) % (2 ** 31)
    spec["version"] = SPEC_VERSION
    return spec, warnings


def _make_goal_playable(spec, warnings):
    """Repair combinations that would make the win condition impossible."""
    goal = spec["goal"]
    theme = spec["world"]["theme"]
    preset = THEME_PRESETS[theme]

    if goal["type"] == "COLLECT_ALL":
        if not spec["collectibles"]:
            spec["collectibles"] = [collectible_from_archetype(preset["collectible"], 8)]
            warnings.append("COLLECT_ALL goal had no pickups; added 8.")
        total = total_count(spec["collectibles"])
        if goal["target_count"] <= 0 or goal["target_count"] > total:
            goal["target_count"] = total
    elif goal["type"] == "DEFEAT_ALL":
        if not spec["enemies"]:
            spec["enemies"] = [enemy_from_archetype(preset["enemy"], 4)]
            warnings.append("DEFEAT_ALL goal had no enemies; added 4.")
        if not spec["player"]["can_shoot"]:
            spec["player"]["can_shoot"] = True
            warnings.append("DEFEAT_ALL goal needs an attack; enabled shooting.")
        goal["target_count"] = total_count(spec["enemies"])
    elif goal["type"] == "REACH_EXIT":
        total = total_count(spec["collectibles"])
        goal["target_count"] = max(0, min(goal["target_count"], total))
    elif goal["type"] == "SURVIVE":
        goal["target_count"] = 0
        if goal["time_limit_seconds"] < 10.0:
            goal["time_limit_seconds"] = 60.0
        if not spec["enemies"] and not spec["hazards"]:
            spec["enemies"] = [enemy_from_archetype(preset["enemy"], 5)]
            warnings.append("SURVIVE goal had no threats; added enemies.")

    if not goal["description"]:
        goal["description"] = describe_goal(spec)


def total_count(groups):
    return sum(int(group.get("count", 0)) for group in groups)


def describe_goal(spec, lang="en"):
    goal = spec["goal"]
    count = goal["target_count"]
    seconds = int(goal["time_limit_seconds"])
    collectible = spec["collectibles"][0]["name"] if spec["collectibles"] else "pickups"
    if lang == "uz":
        if goal["type"] == "COLLECT_ALL":
            return "%d ta %s yig'ing" % (count, collectible.lower())
        if goal["type"] == "DEFEAT_ALL":
            if count == 1 and spec["enemies"]:
                return "%sni yenging" % spec["enemies"][0]["name"]
            return "Barcha %d dushmanni yengib chiqing" % count
        if goal["type"] == "SURVIVE":
            return "%d soniya omon qoling" % seconds
        if count:
            return "%d ta %s yig'ib, portalga yeting" % (count, collectible.lower())
        return "Chiqish portaliga yeting"
    if lang == "ru":
        if goal["type"] == "COLLECT_ALL":
            return "Соберите: %s × %d" % (collectible, count)
        if goal["type"] == "DEFEAT_ALL":
            if count == 1 and spec["enemies"]:
                return "Победите: %s" % spec["enemies"][0]["name"]
            return "Победите всех врагов: %d" % count
        if goal["type"] == "SURVIVE":
            return "Продержитесь %d секунд" % seconds
        if count:
            return "Соберите %s × %d и доберитесь до портала" % (collectible, count)
        return "Доберитесь до портала"
    if goal["type"] == "COLLECT_ALL":
        return "Collect %d %s" % (count, _plural(collectible, count))
    if goal["type"] == "DEFEAT_ALL":
        if count == 1 and spec["enemies"]:
            return "Defeat the %s" % spec["enemies"][0]["name"]
        return "Defeat all %d enemies" % count
    if goal["type"] == "SURVIVE":
        return "Survive for %d seconds" % seconds
    if count:
        return "Collect %d %s, then reach the exit portal" % (count, _plural(collectible, count))
    return "Reach the exit portal"


def _plural(name, count):
    lowered = name.lower()
    if count == 1 or lowered.endswith("s"):
        return lowered
    return lowered + "s"


def summarize(spec):
    """Readable one-line facts for the UI and logs."""
    enemies = total_count(spec["enemies"])
    pickups = total_count(spec["collectibles"])
    hazards = total_count(spec["hazards"])
    props = total_count(spec["props"])
    lines = [
        "%s · %s · %s" % (spec["dimension"], spec["camera"].replace("_", " ").title(), spec["world"]["theme"].replace("_", " ").title()),
        "Goal: %s" % spec["goal"]["description"],
        "%d enemies · %d pickups · %d hazards · %d props · %d platforms" % (
            enemies, pickups, hazards, props, spec["platforms"]),
    ]
    if spec["goal"]["time_limit_seconds"] and spec["goal"]["type"] != "SURVIVE":
        lines.append("Time limit: %d s" % int(spec["goal"]["time_limit_seconds"]))
    return lines


def estimated_object_count(spec):
    count = total_count(spec["enemies"]) + total_count(spec["collectibles"]) + total_count(spec["hazards"])
    count += total_count(spec["props"]) * 2 + spec["platforms"] + spec["health_pickups"]
    return count + 12  # player, camera, lights, ground, walls, goal, director


def dumps(spec):
    return json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=False)


def copy_spec(spec):
    return copy.deepcopy(spec)


# ---------------------------------------------------------------------------
# Layout helpers (pure math, shared by the builder and tests).
# ---------------------------------------------------------------------------

def scatter_points(rng, count, half_extent, min_distance, avoid=(), existing=None, max_attempts=60,
                   inner_radius=0.0, outer_radius=None):
    """Place up to ``count`` points in a square without crowding.

    ``avoid`` holds ``(x, y, radius)`` circles to keep clear (spawn, exit).
    ``existing`` is a shared list of ``(x, y, radius)`` that already occupy
    space; new points are appended to it so later groups avoid them too.
    ``inner_radius``/``outer_radius`` limit points to a ring around the origin.
    """
    placed = []
    occupied = existing if existing is not None else []
    distance = max(0.1, float(min_distance))
    for _ in range(count):
        for attempt in range(max_attempts):
            # Relax spacing gradually so crowded arenas still fill up.
            spacing = distance * (1.0 - 0.5 * attempt / max_attempts)
            x = rng.uniform(-half_extent, half_extent)
            y = rng.uniform(-half_extent, half_extent)
            radius = math.sqrt(x * x + y * y)
            if radius < inner_radius or (outer_radius is not None and radius > outer_radius):
                continue
            if any((x - ax) ** 2 + (y - ay) ** 2 < (ar + spacing * 0.5) ** 2 for ax, ay, ar in avoid):
                continue
            if any((x - ox) ** 2 + (y - oy) ** 2 < (orad + spacing * 0.5) ** 2 for ox, oy, orad in occupied):
                continue
            placed.append((x, y))
            occupied.append((x, y, spacing * 0.5))
            break
    return placed


def terrain_height(x, y, half_extent, hilliness):
    """Height of the generated terrain. The middle stays nearly flat so
    enemies and pickups (which move in XY) never float or sink."""
    if half_extent <= 0.0:
        return 0.0
    distance = math.sqrt(x * x + y * y) / half_extent
    edge = max(0.0, distance - 0.72) / 0.28
    ripple = math.sin(x * 0.35) * math.cos(y * 0.29) * 0.06 * hilliness
    return edge * edge * (0.6 + 3.4 * hilliness) + ripple
