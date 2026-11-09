# SPDX-License-Identifier: GPL-2.0-or-later
"""Unit tests for the AI Game Creator's spec format and planners.

These modules do not need Blender. Run from the repository root with any
Python 3.10+::

    python3 tests/python/blendengine_ai_spec.py

The Claude planner tests use a fake client, so they never call the API; they
run when the ``anthropic`` package is importable and are skipped otherwise.
"""

import importlib.util
import json
import math
from pathlib import Path
import random
import sys
import types
from types import SimpleNamespace
import unittest


ADDON_DIR = Path(__file__).resolve().parents[2] / "scripts" / "addons_core" / "blendengine"
PACKAGE = "blendengine_ai_under_test"


def _load(name):
    """Import an add-on module without running the bpy-dependent package __init__."""
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ADDON_DIR)]
        sys.modules[PACKAGE] = package
    full_name = "%s.%s" % (PACKAGE, name)
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, ADDON_DIR / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


spec_lib = _load("ai_game_spec")
planner = _load("ai_game_planner")


def walk_schema(schema, path="$"):
    """Yield (path, node) for every node in a JSON schema."""
    yield path, schema
    if schema.get("type") == "object":
        for key, child in schema["properties"].items():
            yield from walk_schema(child, path + "." + key)
    elif schema.get("type") == "array":
        yield from walk_schema(schema["items"], path + "[]")


class SchemaTests(unittest.TestCase):
    def test_every_object_is_closed_and_fully_required(self):
        for path, node in walk_schema(spec_lib.SPEC_JSON_SCHEMA):
            if node.get("type") == "object":
                self.assertIs(node["additionalProperties"], False, path)
                self.assertEqual(set(node["required"]), set(node["properties"]), path)

    def test_schema_avoids_unsupported_constraints(self):
        # Structured outputs reject numeric and string bounds; ranges are
        # enforced by normalize_spec instead.
        banned = {"minimum", "maximum", "minLength", "maxLength", "pattern", "maxItems"}
        for path, node in walk_schema(spec_lib.SPEC_JSON_SCHEMA):
            self.assertFalse(banned & set(node), path)

    def test_schema_enums_match_builder_vocabulary(self):
        world = spec_lib.SPEC_JSON_SCHEMA["properties"]["world"]["properties"]
        self.assertEqual(tuple(world["theme"]["enum"]), spec_lib.THEMES)
        goal = spec_lib.SPEC_JSON_SCHEMA["properties"]["goal"]["properties"]
        self.assertEqual(tuple(goal["type"]["enum"]), spec_lib.GOAL_TYPES)

    def test_default_spec_survives_normalization_unchanged(self):
        spec, warnings = spec_lib.normalize_spec(spec_lib.default_spec("SNOW"))
        self.assertEqual(warnings, [])
        self.assertEqual(spec["world"]["theme"], "SNOW")
        self.assertEqual(spec["goal"]["target_count"], spec_lib.total_count(spec["collectibles"]))


class NormalizeTests(unittest.TestCase):
    def test_garbage_input_becomes_a_valid_default(self):
        for raw in (None, 42, "not json", [], {"world": "nope", "player": 7}):
            spec, _warnings = spec_lib.normalize_spec(raw)
            self.assertIn(spec["world"]["theme"], spec_lib.THEMES)
            self.assertIn(spec["goal"]["type"], spec_lib.GOAL_TYPES)

    def test_numbers_are_clamped_and_nan_rejected(self):
        spec, _ = spec_lib.normalize_spec({
            "world": {"size": 10000, "hilliness": float("nan")},
            "player": {"walk_speed": -5, "run_speed": 1e9, "jump_force": "high", "max_health": float("inf")},
        })
        self.assertEqual(spec["world"]["size"], 120.0)
        self.assertTrue(0.0 <= spec["world"]["hilliness"] <= 1.0)
        self.assertEqual(spec["player"]["walk_speed"], 1.0)
        self.assertEqual(spec["player"]["run_speed"], 25.0)
        self.assertEqual(spec["player"]["jump_force"], 6.5)
        self.assertEqual(spec["player"]["max_health"], 100.0)

    def test_object_budgets_are_enforced(self):
        raw = {
            "enemies": [{"count": 999, "behavior": "ATTACK"} for _ in range(10)],
            "collectibles": [{"count": 999} for _ in range(10)],
            "hazards": [{"count": 999} for _ in range(10)],
            "props": [{"kind": "TREE", "count": 999} for _ in range(10)],
            "platforms": 999,
            "health_pickups": 999,
        }
        spec, _ = spec_lib.normalize_spec(raw)
        self.assertLessEqual(len(spec["enemies"]), spec_lib.MAX_ENEMY_GROUPS)
        self.assertLessEqual(spec_lib.total_count(spec["enemies"]), spec_lib.MAX_ENEMIES_TOTAL)
        self.assertLessEqual(spec_lib.total_count(spec["collectibles"]), spec_lib.MAX_COLLECTIBLES_TOTAL)
        self.assertLessEqual(spec_lib.total_count(spec["hazards"]), spec_lib.MAX_HAZARDS_TOTAL)
        self.assertLessEqual(spec_lib.total_count(spec["props"]), spec_lib.MAX_PROPS_TOTAL)
        self.assertEqual(spec["platforms"], spec_lib.MAX_PLATFORMS)
        self.assertEqual(spec["health_pickups"], spec_lib.MAX_HEALTH_PICKUPS)
        self.assertLess(spec_lib.estimated_object_count(spec), 300)

    def test_enums_and_text_are_sanitized(self):
        spec, _ = spec_lib.normalize_spec({
            "title": "Bad\x00Title\n" + "x" * 500,
            "camera": "first-person",
            "world": {"theme": "neon city", "ground_color": "#ABC", "sky_color": "red"},
            "enemies": [{"name": "<script>Zom/bie</script>", "shape": "DRAGON", "count": 2}],
        })
        self.assertNotIn("\x00", spec["title"])
        self.assertLessEqual(len(spec["title"]), 60)
        self.assertEqual(spec["camera"], "FIRST_PERSON")
        self.assertEqual(spec["world"]["theme"], "NEON_CITY")
        self.assertEqual(spec["world"]["ground_color"], "#aabbcc")
        self.assertEqual(spec["world"]["sky_color"], spec_lib.THEME_PRESETS["NEON_CITY"]["sky"])
        self.assertEqual(spec["enemies"][0]["shape"], "BRUTE")
        self.assertNotIn("<", spec["enemies"][0]["name"])
        self.assertNotIn("/", spec["enemies"][0]["name"])

    def test_2d_forces_side_view_and_3d_rejects_it(self):
        spec, _ = spec_lib.normalize_spec({"dimension": "2D", "camera": "TOP_DOWN"})
        self.assertEqual(spec["camera"], "SIDE_VIEW")
        spec, _ = spec_lib.normalize_spec({"dimension": "3D", "camera": "SIDE_VIEW"})
        self.assertEqual(spec["camera"], "THIRD_PERSON")

    def test_impossible_goals_are_repaired(self):
        spec, warnings = spec_lib.normalize_spec({"collectibles": [], "goal": {"type": "COLLECT_ALL"}})
        self.assertGreater(spec_lib.total_count(spec["collectibles"]), 0)
        self.assertEqual(spec["goal"]["target_count"], spec_lib.total_count(spec["collectibles"]))
        self.assertTrue(warnings)

        spec, _ = spec_lib.normalize_spec({
            "enemies": [], "player": {"can_shoot": False}, "goal": {"type": "DEFEAT_ALL", "target_count": 99}})
        self.assertTrue(spec["player"]["can_shoot"])
        self.assertEqual(spec["goal"]["target_count"], spec_lib.total_count(spec["enemies"]))

        spec, _ = spec_lib.normalize_spec({"goal": {"type": "SURVIVE", "time_limit_seconds": 0}})
        self.assertGreaterEqual(spec["goal"]["time_limit_seconds"], 10.0)

        spec, _ = spec_lib.normalize_spec({
            "collectibles": [{"count": 3}], "goal": {"type": "REACH_EXIT", "target_count": 50}})
        self.assertEqual(spec["goal"]["target_count"], 3)

    def test_seed_is_stable_and_respected(self):
        first, _ = spec_lib.normalize_spec({"title": "Same"})
        second, _ = spec_lib.normalize_spec({"title": "Same"})
        self.assertEqual(first["seed"], second["seed"])
        third, _ = spec_lib.normalize_spec({"title": "Same", "seed": 1234})
        self.assertEqual(third["seed"], 1234)

    def test_colors_convert_to_linear(self):
        self.assertEqual(spec_lib.hex_to_linear("#ffffff"), (1.0, 1.0, 1.0))
        self.assertEqual(spec_lib.hex_to_linear("#000000"), (0.0, 0.0, 0.0))
        mid = spec_lib.hex_to_linear("#808080")[0]
        self.assertAlmostEqual(mid, 0.2158605, places=4)


class LayoutTests(unittest.TestCase):
    def test_scatter_keeps_spacing_and_clear_zones(self):
        rng = random.Random(7)
        occupied = []
        avoid = [(0.0, 0.0, 5.0)]
        points = spec_lib.scatter_points(rng, 20, 20.0, 3.0, avoid=avoid, existing=occupied)
        self.assertEqual(len(points), 20)
        for x, y in points:
            self.assertGreaterEqual(math.hypot(x, y), 5.0)
            self.assertTrue(-20.0 <= x <= 20.0 and -20.0 <= y <= 20.0)
        for index, (x, y) in enumerate(points):
            for ox, oy in points[index + 1:]:
                self.assertGreater(math.hypot(x - ox, y - oy), 1.4)

    def test_scatter_ring(self):
        points = spec_lib.scatter_points(random.Random(3), 15, 30.0, 2.0, inner_radius=10.0, outer_radius=25.0)
        for x, y in points:
            self.assertTrue(10.0 <= math.hypot(x, y) <= 25.0)

    def test_terrain_is_flat_where_actors_walk(self):
        half = 24.0
        for x, y in ((0, 0), (5, -8), (-10, 10), (12, 4)):
            self.assertLess(abs(spec_lib.terrain_height(x, y, half, 1.0)), 0.1)
        self.assertGreater(spec_lib.terrain_height(half, 0.0, half, 1.0), 3.0)


class OfflinePlannerTests(unittest.TestCase):
    def plan(self, prompt, **kwargs):
        spec, _warnings = planner.plan_offline(prompt, **kwargs)
        normalized, _ = spec_lib.normalize_spec(spec)
        self.assertEqual(spec["goal"], normalized["goal"])
        return spec

    def test_uzbek_collect_game(self):
        spec = self.plan("O'rmonda 12 ta tanga yig'adigan, bo'rilardan qochadigan 3D o'yin")
        self.assertEqual(spec["world"]["theme"], "FOREST")
        self.assertEqual(spec["goal"]["type"], "COLLECT_ALL")
        self.assertEqual(spec["goal"]["target_count"], 12)
        self.assertEqual(spec["collectibles"][0]["name"], "Tanga")
        self.assertEqual(spec["enemies"][0]["name"], "Bo'ri")
        self.assertIn("yig'ing", spec["goal"]["description"])

    def test_uzbek_typographic_apostrophes(self):
        spec = self.plan("Oʻrmonda 5 ta tanga yigʻ")
        self.assertEqual(spec["world"]["theme"], "FOREST")
        self.assertEqual(spec["goal"]["target_count"], 5)

    def test_english_2d_platformer(self):
        spec = self.plan("2D platformer in a snowy world, collect 15 stars and reach the portal, hard")
        self.assertEqual(spec["dimension"], "2D")
        self.assertEqual(spec["camera"], "SIDE_VIEW")
        self.assertEqual(spec["world"]["theme"], "SNOW")
        self.assertEqual(spec["difficulty"], "HARD")
        self.assertEqual(spec["goal"]["type"], "REACH_EXIT")
        self.assertEqual(spec["goal"]["target_count"], 15)
        self.assertGreaterEqual(spec["platforms"], 6)

    def test_first_person_shooter(self):
        spec = self.plan("First person zombie shooter in a neon city at night, kill all zombies")
        self.assertEqual(spec["camera"], "FIRST_PERSON")
        self.assertTrue(spec["player"]["can_shoot"])
        self.assertEqual(spec["world"]["time_of_day"], "NIGHT")
        self.assertEqual(spec["goal"]["type"], "DEFEAT_ALL")
        self.assertEqual(spec["enemies"][0]["name"], "Zombie")

    def test_survival_with_seconds_and_boss(self):
        spec = self.plan("Kosmosda 90 soniya omon qolish, o'zga sayyoraliklar va lazer tuzoqlari, boss bilan")
        self.assertEqual(spec["world"]["theme"], "SPACE")
        self.assertEqual(spec["goal"]["type"], "SURVIVE")
        self.assertEqual(spec["goal"]["time_limit_seconds"], 90.0)
        self.assertEqual([h["kind"] for h in spec["hazards"]], ["LASER"])
        self.assertTrue(any(e["behavior"] == "ENEMY_BOSS" for e in spec["enemies"]))

    def test_russian_prompt(self):
        spec = self.plan("Сделай игру в пустыне: собери 8 кристаллов, скорпионы и шипы")
        self.assertEqual(spec["world"]["theme"], "DESERT")
        self.assertEqual(spec["goal"]["target_count"], 8)
        self.assertEqual(spec["collectibles"][0]["name"], "Кристалл")
        self.assertEqual(spec["hazards"][0]["kind"], "SPIKES")

    def test_peaceful_game_has_no_enemies(self):
        spec = self.plan("a relaxing candy game for kids with no enemies")
        self.assertEqual(spec["enemies"], [])
        self.assertEqual(spec["difficulty"], "EASY")

    def test_quoted_title_and_minutes(self):
        spec = self.plan('"Lava Lords": survive 2 minutes on a volcano')
        self.assertEqual(spec["title"], "Lava Lords")
        self.assertEqual(spec["goal"]["time_limit_seconds"], 120.0)

    def test_refine_changes_only_what_is_mentioned(self):
        base = self.plan("O'rmonda 12 ta tanga yig'adigan, bo'rilardan qochadigan 3D o'yin")
        refined = self.plan("ko'proq dushman va tunda bo'lsin", base_spec=base)
        self.assertEqual(refined["title"], base["title"])
        self.assertEqual(refined["world"]["theme"], "FOREST")
        self.assertEqual(refined["world"]["time_of_day"], "NIGHT")
        self.assertGreater(spec_lib.total_count(refined["enemies"]), spec_lib.total_count(base["enemies"]))
        self.assertEqual(refined["goal"]["target_count"], 12)
        self.assertEqual(refined["seed"], base["seed"])

    def test_refine_adding_lava_keeps_the_world(self):
        base = self.plan("Kosmosda 90 soniya omon qolish, o'zga sayyoraliklar va lazer to'siqlari")
        refined = self.plan("ko'proq dushman, tunda bo'lsin va lava qo'sh", base_spec=base)
        self.assertEqual(refined["world"]["theme"], "SPACE")
        self.assertEqual(refined["title"], base["title"])
        self.assertEqual(sorted(h["kind"] for h in refined["hazards"]), ["LASER", "LAVA"])
        self.assertGreater(spec_lib.total_count(refined["enemies"]), spec_lib.total_count(base["enemies"]))
        # A new idea still reads "lava world" as a volcano.
        self.assertEqual(self.plan("lava world with monsters")["world"]["theme"], "VOLCANO")

    def test_refine_keeps_named_enemies_and_reads_counts_after_the_noun(self):
        base = self.plan("Shahar xarobalarida zombilardan omon qolish: 3D first-person, 8 ta zombi")
        zombies = base["enemies"][0]
        refined = self.plan("Zombilar 6 ta bo'lsin, lekin sekinroq yursin", base_spec=base)
        self.assertEqual(len(refined["enemies"]), 1)
        self.assertEqual(refined["enemies"][0]["name"], zombies["name"])
        self.assertEqual(refined["enemies"][0]["count"], 6)
        self.assertLess(refined["enemies"][0]["speed"], zombies["speed"])
        slower = self.plan("zombilar sekinroq", base_spec=base)
        self.assertEqual(slower["enemies"][0]["count"], zombies["count"])
        self.assertEqual(self.plan("zombies: 5", base_spec=base)["enemies"][0]["count"], 5)
        # "3 times faster" is not a count.
        self.assertEqual(self.plan("zombies 3 times faster", base_spec=base)["enemies"][0]["count"], zombies["count"])
        both = self.plan("add 3 robots", base_spec=base)
        self.assertEqual([g["count"] for g in both["enemies"]], [zombies["count"], 3])

    def test_every_theme_keyword_builds(self):
        for theme, words in planner.THEME_KEYWORDS.items():
            spec = self.plan("a game in the %s" % words[0])
            self.assertEqual(spec["world"]["theme"], theme, words[0])

    def test_generate_spec_offline(self):
        result = planner.generate_spec("forest coins", provider="OFFLINE")
        self.assertEqual(result.source, "offline")
        with self.assertRaises(planner.PlannerError):
            planner.generate_spec("   ", provider="OFFLINE")


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def fake_client(response=None, error=None):
    messages = FakeMessages(response, error)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def text_response(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(stop_reason=stop_reason, content=[
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=text),
    ])


@unittest.skipUnless(planner.sdk_available(), "anthropic SDK not installed")
class ClaudePlannerTests(unittest.TestCase):
    def claude_spec(self):
        spec = spec_lib.default_spec("VOLCANO")
        spec.update({"title": "Magma Run", "camera": "TOP_DOWN"})
        spec["goal"].update({"type": "SURVIVE", "time_limit_seconds": 45})
        spec.pop("seed", None)
        spec.pop("version", None)
        return spec

    def test_request_shape(self):
        client, messages = fake_client(text_response(self.claude_spec()))
        spec, _warnings = planner.plan_with_claude("volcano survival", client=client, platform="ANDROID")
        self.assertEqual(spec["title"], "Magma Run")
        self.assertEqual(spec["camera"], "TOP_DOWN")
        call = messages.calls[0]
        self.assertEqual(call["model"], "claude-opus-5-5")
        self.assertEqual(call["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(call["fallbacks"], "default")
        self.assertEqual(call["output_config"]["effort"], "medium")
        self.assertEqual(call["output_config"]["format"]["type"], "json_schema")
        self.assertIs(call["output_config"]["format"]["schema"], spec_lib.SPEC_JSON_SCHEMA)
        self.assertNotIn("thinking", call)
        self.assertNotIn("temperature", call)
        self.assertIn("Target platform: Android", call["messages"][0]["content"])
        self.assertIn("volcano survival", call["messages"][0]["content"])

    def test_refine_sends_current_spec_and_keeps_seed(self):
        base, _ = spec_lib.normalize_spec(self.claude_spec())
        base["seed"] = 99
        client, messages = fake_client(text_response(self.claude_spec()))
        spec, _ = planner.plan_with_claude("add a boss", client=client, base_spec=base)
        content = messages.calls[0]["messages"][0]["content"]
        self.assertIn("Current game spec:", content)
        self.assertIn("Magma Run", content)
        self.assertIn("Change request: add a boss", content)
        self.assertEqual(spec["seed"], 99)

    def test_model_output_is_normalized(self):
        hostile = self.claude_spec()
        hostile["enemies"] = [{"name": "x", "count": 10 ** 6, "behavior": "ATTACK", "shape": "BRUTE",
                               "color": "#fff", "size": 99, "speed": 99, "health": -5, "damage": 1e9}]
        client, _ = fake_client(text_response(hostile))
        spec, _ = planner.plan_with_claude("idea", client=client)
        enemy = spec["enemies"][0]
        self.assertEqual(enemy["count"], spec_lib.MAX_ENEMIES_PER_GROUP)
        self.assertEqual((enemy["size"], enemy["speed"], enemy["health"], enemy["damage"]), (4.0, 12.0, 1.0, 100.0))

    def test_refusal_and_truncation_raise(self):
        for stop_reason in ("refusal", "max_tokens"):
            client, _ = fake_client(text_response({}, stop_reason=stop_reason))
            with self.assertRaises(planner.PlannerError):
                planner.plan_with_claude("idea", client=client)
        client, _ = fake_client(text_response("not json"))
        with self.assertRaises(planner.PlannerError):
            planner.plan_with_claude("idea", client=client)

    def test_connection_error_is_reported_and_auto_falls_back(self):
        import anthropic
        try:
            import httpx2 as httpx
        except ImportError:
            import httpx
        error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
        client, _ = fake_client(error=error)
        with self.assertRaises(planner.PlannerError) as caught:
            planner.generate_spec("forest coins", provider="CLAUDE", client=client)
        self.assertIn("Could not reach", str(caught.exception))

        client, _ = fake_client(error=error)
        result = planner.generate_spec("forest coins", provider="AUTO", client=client)
        self.assertEqual(result.source, "offline")
        self.assertIn("Claude unavailable", result.warnings[0])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [arg for arg in sys.argv[1:] if arg.startswith("-")], verbosity=2)
