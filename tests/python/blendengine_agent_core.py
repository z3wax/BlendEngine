# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor agent parsing and model-tool boundary tests; no Blender required."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "blendengine_agent_core", Path(__file__).resolve().parents[2] / "scripts/addons_core/blendengine/agent_core.py")
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


def context(selected=True):
    return {"selected": ["Crate"] if selected else [],
            "objects": [{"name": "Crate", "type": "MESH", "location": [0, 0, 1], "scale": [1, 1, 1]}],
            "stats": {"objects": 1, "triangles": 12, "materials": 1}}


def create(name="Beacon"):
    return {"tool": "create_object", "name": name, "kind": "CUBE", "location": [1, 2, 3],
            "scale": [1, 1, 1], "color": [0.8, 0.1, 0.1]}


class LocalPlannerTests(unittest.TestCase):
    def test_uzbek_apostrophes_and_cyrillic(self):
        for request in ("qizil kub qo‘sh", "Qizil kub qo'sh!", "qizil kub qosh", "қизил куб қўш"):
            action = agent.plan_request(request, context())["actions"][0]
            self.assertEqual(action["kind"], "CUBE")
            self.assertGreater(action["color"][0], action["color"][2])

    def test_english_and_uzbek_primitives(self):
        for text, kind in (("add a blue sphere", "SPHERE"), ("ko‘k shar qo‘sh", "SPHERE"),
                           ("yorug‘lik qo‘sh", "LIGHT"), ("create a floor", "PLANE")):
            self.assertEqual(agent.plan_request(text, context())["actions"][0]["kind"], kind)

    def test_coordinates_and_named_new_object(self):
        plan = agent.plan_request('add cube "Signal Box" at (1, -2, 3); move it to 4 5 6', context(False))
        self.assertEqual(plan["actions"][0]["name"], "Signal Box")
        self.assertEqual(plan["actions"][1], {"tool": "transform_object", "object": "Signal Box", "location": [4.0, 5.0, 6.0]})

    def test_selected_transform_and_paint(self):
        plan = agent.plan_request("tanlangan obyektni 1 2 3 ga ko‘chir; uni qizil qil", context())
        self.assertEqual([a["tool"] for a in plan["actions"]], ["transform_object", "set_material"])
        self.assertTrue(all(a["object"] == "@selected" for a in plan["actions"]))

    def test_npc_creation_and_behavior_chain(self):
        plan = agent.plan_request("NPC qo‘sh; o‘yinchiga ergashsin; patrul", context(False))
        self.assertEqual(plan["actions"][0]["tool"], "create_npc")
        self.assertEqual(plan["actions"][1]["behavior"], "FOLLOW_PLAYER")
        self.assertEqual(plan["actions"][2]["behavior"], "PATROL")
        self.assertEqual(plan["actions"][1]["object"], plan["actions"][0]["name"])

    def test_npc_guard_and_idle(self):
        self.assertEqual(agent.plan_request("qorovul", context())["actions"][0]["behavior"], "GUARD")
        self.assertEqual(agent.plan_request("to‘xtasin", context())["actions"][0]["speed"], 0)

    def test_audit_preserves_quality(self):
        plan = agent.plan_request("sahnani tahlil va FPS optimizatsiya", context())
        self.assertTrue(all(action == {"tool": "audit"} for action in plan["actions"]))
        self.assertIn("12 source triangles", plan["summary"])
        self.assertIn("quality unchanged", plan["summary"])

    def test_unknown_or_mixed_batch_never_partially_executes(self):
        for request in ("delete all files", "add a cube; run Python", "make everything photorealistic",
                        "why is this cube red?", "how does NPC patrol?", "create a cube by running Python"):
            self.assertEqual(agent.plan_request(request, context())["actions"], [])

    def test_bare_shape_command_and_explicit_make(self):
        self.assertEqual(agent.plan_request("blue cube", context())["actions"][0]["kind"], "CUBE")
        self.assertEqual(agent.plan_request("make a red cube", context())["actions"][0]["kind"], "CUBE")

    def test_missing_selection_is_clear_and_nonmutating(self):
        result = agent.plan_request("move selected to 1 2 3", context(False))
        self.assertEqual(result["actions"], [])
        self.assertIn("select", result["summary"])

    def test_unique_names_and_context_not_modified(self):
        ctx = context()
        snapshot = copy.deepcopy(ctx)
        plan = agent.plan_request("add cube; add cube", ctx)
        self.assertNotEqual(plan["actions"][0]["name"], plan["actions"][1]["name"])
        self.assertEqual(ctx, snapshot)


class ModelBoundaryTests(unittest.TestCase):
    def plan(self, action=None):
        return {"summary": "Create a beacon", "actions": [action or create()]}

    def test_model_json_and_complete_json_fence(self):
        data = json.dumps(self.plan())
        for text in (data, "```json\n" + data + "\n```"):
            result = agent.parse_plan_response(text, context())
            self.assertEqual(result["actions"][0]["location"], [1.0, 2.0, 3.0])

    def test_prose_python_and_nonfinite_json_rejected(self):
        for value in ('Here is a plan: {}', "__import__('os').system('x')", '```python\nprint(1)\n```',
                      '{"summary":"x","actions":[{"tool":"create_object","name":"x","kind":"CUBE","location":[NaN,0,0],"scale":[1,1,1],"color":[1,1,1]}]}'):
            with self.assertRaises(ValueError): agent.parse_plan_response(value, context())

    def test_duplicate_json_keys_are_rejected(self):
        for text in ('{"summary":"x","summary":"y","actions":[]}',
                     '{"summary":"x","actions":[{"tool":"exec","tool":"audit"}]}'):
            with self.assertRaises(ValueError): agent.parse_plan_response(text, context())

    def test_unknown_tools_and_arbitrary_fields_rejected(self):
        for action in ({"tool": "exec", "code": "print(1)"}, {"tool": "delete", "object": "Crate"},
                       dict(create(), script="x"), dict(create(), path="/tmp/game")):
            with self.assertRaises(ValueError): agent.validate_plan(self.plan(action), context())

    def test_missing_fields_never_default_for_model_output(self):
        action = create(); del action["color"]
        with self.assertRaises(ValueError): agent.validate_plan(self.plan(action), context())

    def test_nonfinite_boolean_and_out_of_range_numbers(self):
        for value in (float("inf"), float("nan"), True, 1000.01, -1000.01, "1", 10 ** 1000):
            action = create(); action["location"][0] = value
            with self.assertRaises(ValueError): agent.validate_plan(self.plan(action), context())
        for field, value in (("scale", [0, 1, 1]), ("scale", [101, 1, 1]), ("color", [2, 0, 0]),
                             ("location", [1, 2]), ("location", (1, 2, 3))):
            action = create(); action[field] = value
            with self.assertRaises(ValueError): agent.validate_plan(self.plan(action), context())

    def test_selection_and_object_references_are_validated(self):
        for name in ("Missing", "@selected", "@all"):
            action = {"tool": "transform_object", "object": name, "location": [1, 2, 3]}
            with self.assertRaises(ValueError): agent.validate_plan(self.plan(action), context(False))

    def test_new_objects_only_referenced_after_creation(self):
        move = {"tool": "transform_object", "object": "Beacon", "location": [4, 5, 6]}
        plan = {"summary": "Build", "actions": [create(), move]}
        self.assertEqual(len(agent.validate_plan(plan, context())["actions"]), 2)
        with self.assertRaises(ValueError): agent.validate_plan({"summary": "Bad order", "actions": [move, create()]}, context())

    def test_name_collisions_and_name_size(self):
        for name in ("Crate", "@selected", "x" * 64, "é" * 32, "line\nbreak", ""):
            with self.assertRaises(ValueError): agent.validate_plan(self.plan(create(name)), context())

    def test_batch_limit_and_no_input_mutation(self):
        with self.assertRaises(ValueError): agent.validate_plan({"summary": "Too much", "actions": [{"tool": "audit"}] * 17})
        plan = self.plan(); before = copy.deepcopy(plan)
        result = agent.validate_plan(plan, context())
        result["actions"][0]["color"][0] = 0
        self.assertEqual(plan, before)

    def test_top_level_and_response_limits(self):
        for plan in ([], {"summary": "x", "actions": [], "python": "x"}, {"summary": "", "actions": []},
                     {"summary": "\ud800", "actions": []}):
            with self.assertRaises(ValueError): agent.validate_plan(plan)
        with self.assertRaises(ValueError): agent.parse_plan_response("x" * 24001)


if __name__ == "__main__":
    unittest.main(verbosity=2)
