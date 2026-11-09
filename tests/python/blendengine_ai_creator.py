# SPDX-License-Identifier: GPL-2.0-or-later
"""Blender integration tests for the AI Game Creator.

Builds games from prompts with the offline planner, then plays them headless
through the real runtime (GameSession) to prove each goal can be won. Run from
the repository root with Blender 3.6+::

    blender --background --factory-startup --python-exit-code 1 \
        --python tests/python/blendengine_ai_creator.py

or with the ``bpy`` module from PyPI::

    python tests/python/blendengine_ai_creator.py
"""

import json
import math
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

import bpy
from mathutils import Vector


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))

import blendengine
from blendengine import ai_game_builder, ai_game_creator, ai_game_planner, ai_game_spec, ai_studio, export_system, runtime


DT = 1.0 / 60.0


def objects_with(scene, prefix):
    return sorted((obj for obj in scene.objects if obj.name.startswith(prefix)), key=lambda obj: obj.name)


VALID_ICONS = {item.identifier for item in bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items}


class RecordingLayout:
    """Stand-in for bpy.types.UILayout that checks what draw code asks for."""

    def __init__(self, test):
        self.test = test
        self.operators = []

    def _icon(self, kwargs):
        icon = kwargs.get("icon")
        if icon:
            self.test.assertIn(icon, VALID_ICONS)

    def row(self, *args, **kwargs):
        return self

    column = box = row

    def grid_flow(self, *args, **kwargs):
        return self

    def separator(self, *args, **kwargs):
        pass

    separator_spacer = separator

    def label(self, text="", **kwargs):
        self._icon(kwargs)

    def prop(self, data, name, **kwargs):
        self._icon(kwargs)
        rna = getattr(data, "bl_rna", None)
        if rna is not None:
            self.test.assertIn(name, rna.properties.keys(), "%s has no property %s" % (data, name))
        else:
            self.test.assertTrue(hasattr(data, name), name)

    def operator(self, idname, **kwargs):
        self._icon(kwargs)
        category, name = idname.split(".")
        operator = getattr(getattr(bpy.ops, category), name)
        properties = operator.get_rna_type().properties.keys()
        self.operators.append(idname)

        class OperatorProperties:
            def __setattr__(self_inner, key, value):
                self.test.assertIn(key, properties, "%s has no property %s" % (idname, key))

        return OperatorProperties()

    def menu(self, *args, **kwargs):
        pass


def player_variable(player, name):
    for variable in player.blendengine_object.variables:
        if variable.name == name:
            return variable.int_value
    return None


class AIGameCreatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blendengine.register()

    @classmethod
    def tearDownClass(cls):
        runtime.finish_active_session("Stopped")
        blendengine.unregister()

    def setUp(self):
        self.scene = bpy.context.scene
        self.scene.blendengine_ai.provider = "OFFLINE"
        self.scene.blendengine_project.target_platform = "WINDOWS"

    def tearDown(self):
        runtime.finish_active_session("Stopped")

    def create(self, prompt):
        result = ai_game_creator.start_design(bpy.context, prompt)
        self.assertIsNotNone(result, "background mode builds synchronously")
        validation = runtime.validate_scene(self.scene)
        self.assertTrue(validation.ok, validation.errors)
        return result

    def build_spec(self, **changes):
        spec = ai_game_spec.default_spec("GRASSLAND")
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(spec.get(key), dict):
                spec[key].update(value)
            else:
                spec[key] = value
        plan = ai_game_planner.PlanResult(ai_game_spec.normalize_spec(spec)[0], "test")
        return ai_game_creator.apply_plan(bpy.context, self.scene, plan, "test")

    def start(self):
        session, result = runtime.start_test_run(bpy.context)
        self.assertIsNotNone(session, result.errors)
        return session

    def step(self, session, seconds=DT):
        for _ in range(max(1, int(round(seconds / DT)))):
            session.step(DT)
            if session.stop_requested:
                return

    def touch(self, session, player, obj):
        """Stand on top of ``obj`` long enough for its trigger to fire."""
        player.location = obj.location.copy()
        self.step(session, 3 * DT)
        player.location = obj.location + Vector((30.0, 30.0, 0.0))
        self.step(session, DT)

    # -- building -------------------------------------------------------

    def test_prompts_build_valid_scenes(self):
        prompts = (
            "O'rmonda 12 ta tanga yig'adigan, bo'rilardan qochadigan 3D o'yin",
            "2D platformer in a snowy world, collect 15 stars and reach the portal, hard",
            "First person zombie shooter in a neon city at night, kill all zombies",
            "Kosmosda 90 soniya omon qolish, o'zga sayyoraliklar va lazer tuzoqlari, boss bilan",
            "top-down desert game with scorpions, lava and 8 gems, big open world",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                result = self.create(prompt)
                spec = result["spec"]
                self.assertEqual(self.scene.blendengine_project.game_title, spec["title"])
                self.assertIs(self.scene.camera, result["camera"])
                player = runtime.utils.find_player_object(self.scene)
                self.assertIs(player, result["player"])
                self.assertEqual(len(objects_with(self.scene, "AI_Exit_Portal")), int(spec["goal"]["type"] == "REACH_EXIT"))
                enemies = [obj for obj in self.scene.objects if obj.blendengine_object.npc_behavior.enabled]
                self.assertEqual(len(enemies), ai_game_spec.total_count(spec["enemies"]))
                pickups = [obj for obj in self.scene.objects if obj.blendengine_object.object_tag == "Pickup"]
                self.assertEqual(len(pickups), ai_game_spec.total_count(spec["collectibles"]))
                self.assertLess(len(self.scene.objects), ai_game_spec.estimated_object_count(spec) + 10)
                stored = json.loads(bpy.data.texts[ai_game_builder.SPEC_TEXT_NAME].as_string())
                self.assertEqual(stored["title"], spec["title"])

    def test_repeated_meshes_are_shared(self):
        self.create("forest with 20 coins and many trees")
        coins = [obj for obj in self.scene.objects if obj.blendengine_object.object_tag == "Pickup"]
        self.assertGreater(len(coins), 5)
        self.assertEqual(len({obj.data.name for obj in coins}), 1)

    def test_rebuild_cleans_previous_game(self):
        self.create("forest coins")
        first_meshes = len(bpy.data.meshes)
        for _ in range(3):
            self.create("forest coins")
        self.assertEqual(len(bpy.data.meshes), first_meshes)
        self.assertEqual(len([c for c in self.scene.collection.children if c.name.startswith("AI World")]), 1)

    def test_variation_keeps_design_and_moves_layout(self):
        self.create("forest with 10 coins")
        before = {obj.name: obj.location.copy() for obj in objects_with(self.scene, "AI_Coin")}
        bpy.ops.blendengine.ai_variation()
        after = {obj.name: obj.location.copy() for obj in objects_with(self.scene, "AI_Coin")}
        self.assertEqual(set(before), set(after))
        self.assertTrue(any((before[name] - after[name]).length > 0.01 for name in before))

    def test_refine_with_offline_planner(self):
        self.create("O'rmonda 6 ta tanga yig'")
        self.scene.blendengine_ai.refine_prompt = "tunda bo'lsin va boss qo'sh"
        bpy.ops.blendengine.ai_refine_game()
        spec = json.loads(self.scene.blendengine_ai.last_spec_json)
        self.assertEqual(spec["world"]["time_of_day"], "NIGHT")
        self.assertTrue(any(group["behavior"] == "ENEMY_BOSS" for group in spec["enemies"]))
        self.assertEqual(spec["goal"]["target_count"], 6)

    def test_worker_thread_and_main_thread_completion(self):
        """The interactive path: plan on a thread, build from the timer callback."""
        import threading

        def run_job(prompt, cancel=False):
            job = ai_game_creator._PlanJob(self.scene.name, prompt, {"provider": "OFFLINE"}, True)
            ai_game_creator._JOB = job
            self.scene.blendengine_ai.busy = True
            worker = threading.Thread(target=job.run)
            worker.start()
            worker.join(timeout=30)
            self.assertTrue(job.done)
            job.cancelled = cancel
            self.assertIsNone(ai_game_creator._poll_job())
            self.assertIsNone(ai_game_creator._JOB)
            self.assertFalse(self.scene.blendengine_ai.busy)
            return self.scene.blendengine_ai

        settings = run_job("O'rmonda 7 ta tanga yig'")
        self.assertEqual(settings.status_icon, "CHECKMARK")
        self.assertEqual(json.loads(settings.last_spec_json)["goal"]["target_count"], 7)
        settings = run_job("   ")
        self.assertEqual(settings.status_icon, "ERROR")
        title = self.scene.blendengine_project.game_title
        settings = run_job("desert gems", cancel=True)
        self.assertEqual(settings.status_icon, "CANCEL")
        self.assertEqual(self.scene.blendengine_project.game_title, title)

    def test_building_is_blocked_while_a_game_runs(self):
        self.create("forest coins")
        title = self.scene.blendengine_project.game_title
        self.start()
        with self.assertRaises(ai_game_planner.PlannerError):
            ai_game_creator.start_design(bpy.context, "desert gems")
        runtime.finish_active_session("Stopped")
        self.assertEqual(self.scene.blendengine_project.game_title, title)

    # -- gameplay ---------------------------------------------------------

    def test_collect_all_wins_and_stop_restores_scene(self):
        self.build_spec(enemies=[], hazards=[], health_pickups=0,
                        collectibles=[{"name": "Coin", "count": 4, "shape": "COIN", "color": "#ffcc00", "points": 10}],
                        goal={"type": "COLLECT_ALL", "target_count": 4})
        player = runtime.utils.find_player_object(self.scene)
        start_location = player.location.copy()
        coins = objects_with(self.scene, "AI_Coin")
        self.assertEqual(len(coins), 4)
        session = self.start()
        for index, coin in enumerate(coins):
            self.touch(session, player, coin)
            if index < 3:
                self.assertFalse(session.stop_requested)
            self.assertTrue(coin.hide_viewport)
        self.assertEqual(player_variable(player, "Collected"), 4)
        self.assertEqual(player_variable(player, "Score"), 40)
        self.assertTrue(session.stop_requested)
        self.assertEqual(session.end_status, "Victory")

        runtime.finish_active_session(session.end_status)
        self.assertEqual(self.scene.blendengine_project.test_status, "Victory")
        self.assertEqual(player_variable(player, "Collected"), 0)
        self.assertTrue(all(not coin.hide_viewport for coin in coins))
        self.assertLess((player.location - start_location).length, 1e-4)

    def test_pickup_counts_only_once(self):
        self.build_spec(enemies=[], hazards=[], health_pickups=0,
                        collectibles=[{"name": "Gem", "count": 2, "shape": "GEM", "color": "#33ccff", "points": 5}])
        player = runtime.utils.find_player_object(self.scene)
        gem = objects_with(self.scene, "AI_Gem")[0]
        session = self.start()
        for _ in range(3):
            self.touch(session, player, gem)
        self.assertEqual(player_variable(player, "Collected"), 1)

    def test_hazard_hurts_and_health_pickup_heals(self):
        self.build_spec(enemies=[], collectibles=[{"count": 1}], health_pickups=1,
                        hazards=[{"name": "Lava", "count": 1, "kind": "LAVA", "damage": 25}],
                        goal={"type": "COLLECT_ALL"})
        player = runtime.utils.find_player_object(self.scene)
        health = player.blendengine_object.health
        session = self.start()
        self.touch(session, player, objects_with(self.scene, "AI_Lava")[0])
        self.assertAlmostEqual(health.current_health, 75.0)
        self.touch(session, player, objects_with(self.scene, "AI_HealthPickup")[0])
        self.assertAlmostEqual(health.current_health, 100.0)

    def test_death_ends_the_run_as_game_over(self):
        self.build_spec(enemies=[], collectibles=[{"count": 1}], player={"max_health": 20},
                        hazards=[{"name": "Spikes", "count": 1, "kind": "SPIKES", "damage": 50}])
        player = runtime.utils.find_player_object(self.scene)
        session = self.start()
        self.touch(session, player, objects_with(self.scene, "AI_Spikes")[0])
        self.assertTrue(session.stop_requested)
        self.assertEqual(session.end_status, "Game Over")

    def test_defeat_all_by_shooting(self):
        self.build_spec(camera="FIRST_PERSON", player={"can_shoot": True}, hazards=[], collectibles=[],
                        enemies=[{"name": "Drone", "count": 2, "behavior": "IDLE", "shape": "DRONE",
                                  "color": "#ff0000", "size": 1.0, "speed": 0, "health": 50, "damage": 0}],
                        goal={"type": "DEFEAT_ALL"})
        player = runtime.utils.find_player_object(self.scene)
        enemies = [obj for obj in self.scene.objects if obj.blendengine_object.npc_behavior.enabled]
        ammo_before = player_variable(player, "Ammo")
        session = self.start()
        for enemy in enemies:
            # The third hit lands on an already defeated enemy and must not count again.
            for _ in range(3):
                session._damage_enemy(enemy, 25.0, player)
        self.step(session, 2 * DT)
        self.assertEqual(player_variable(player, "Kills"), 2)
        self.assertEqual(session.end_status, "Victory")
        self.assertEqual(ammo_before, 80)

    def test_no_attack_when_game_has_no_weapon(self):
        self.build_spec(player={"can_shoot": False}, hazards=[], goal={"type": "COLLECT_ALL"})
        player = runtime.utils.find_player_object(self.scene)
        self.assertEqual(player.blendengine_object.player_controller.attack_key, "")
        session = self.start()
        session._shoot_weapon()
        self.assertEqual(session._attack_cooldown, 0.0)

    def test_enemy_attack_uses_spec_damage(self):
        self.build_spec(hazards=[], collectibles=[{"count": 1}],
                        enemies=[{"name": "Brute", "count": 1, "behavior": "ATTACK", "shape": "BRUTE",
                                  "color": "#ff0000", "size": 1.0, "speed": 0, "health": 50, "damage": 17}])
        player = runtime.utils.find_player_object(self.scene)
        enemy = next(obj for obj in self.scene.objects if obj.blendengine_object.npc_behavior.enabled)
        session = self.start()
        enemy.location = player.location + Vector((0.5, 0.0, 0.0))
        self.step(session, DT)
        self.assertAlmostEqual(player.blendengine_object.health.current_health, 83.0)

    def test_survive_timer_wins(self):
        self.build_spec(enemies=[], collectibles=[],
                        hazards=[{"name": "Lava", "count": 1, "kind": "LAVA", "damage": 10}],
                        goal={"type": "SURVIVE", "time_limit_seconds": 10})
        session = self.start()
        self.step(session, 9.0)
        self.assertFalse(session.stop_requested)
        self.step(session, 1.5)
        self.assertEqual(session.end_status, "Victory")

    def test_time_limit_loses(self):
        self.build_spec(enemies=[], hazards=[], collectibles=[{"count": 3}],
                        goal={"type": "COLLECT_ALL", "time_limit_seconds": 12})
        session = self.start()
        self.step(session, 13.0)
        self.assertEqual(session.end_status, "Game Over")

    def test_exit_portal_needs_pickups_first(self):
        self.build_spec(enemies=[], hazards=[], health_pickups=0,
                        collectibles=[{"name": "Key", "count": 2, "shape": "KEY", "color": "#ffcc00", "points": 1}],
                        goal={"type": "REACH_EXIT", "target_count": 2})
        player = runtime.utils.find_player_object(self.scene)
        portal = objects_with(self.scene, "AI_Exit_Portal")[0]
        session = self.start()
        self.touch(session, player, portal)
        self.assertFalse(session.stop_requested)
        for key in objects_with(self.scene, "AI_Key"):
            self.touch(session, player, key)
        self.touch(session, player, portal)
        self.assertEqual(session.end_status, "Victory")

    def test_player_lands_on_platforms_and_walks_under_them(self):
        # Reaching a far exit is the goal, so landing on a pickup cannot end the run.
        self.build_spec(enemies=[], hazards=[], collectibles=[{"count": 3}], platforms=3, health_pickups=0,
                        goal={"type": "REACH_EXIT", "target_count": 0})
        player = runtime.utils.find_player_object(self.scene)
        platforms = objects_with(self.scene, "AI_Platform")
        high = platforms[-1]
        top = high.location.z + 0.25
        half_height = player.dimensions.z * 0.5
        session = self.start()
        player.location = high.location + Vector((0.0, 0.0, 1.5))
        self.step(session, 1.5)
        self.assertFalse(session.stop_requested)
        self.assertAlmostEqual(player.location.z, top + half_height, places=2)

        # Standing on the ground below a high platform must not teleport the player onto it.
        player.location = Vector((high.location.x, high.location.y, 1.0))
        self.step(session, 1.5)
        self.assertLess(player.location.z, top)
        self.assertLess(player.location.z, half_height + 0.3)

    def test_npcs_and_player_face_where_they_go(self):
        """Local +Y must point at the target/heading (atan2(x, y) mirrored it)."""
        self.build_spec(hazards=[], collectibles=[{"count": 1}],
                        enemies=[{"name": "Brute", "count": 1, "behavior": "FOLLOW_PLAYER", "shape": "BRUTE",
                                  "color": "#ff0000", "size": 1.0, "speed": 2.0, "health": 50, "damage": 0}])
        player = runtime.utils.find_player_object(self.scene)
        enemy = next(obj for obj in self.scene.objects if obj.blendengine_object.npc_behavior.enabled)
        session = self.start()
        enemy.location = player.location + Vector((6.0, 4.0, 0.0))
        self.step(session, 1.0)  # enemies turn at a limited rate now
        facing = enemy.matrix_basis.to_3x3() @ Vector((0.0, 1.0, 0.0))
        facing.z = 0.0
        to_player = player.location - enemy.location
        to_player.z = 0.0
        self.assertGreater(facing.normalized().dot(to_player.normalized()), 0.99)

        session.input_state.add("D")
        self.step(session, 0.2)
        heading = player.matrix_basis.to_3x3() @ Vector((0.0, 1.0, 0.0))
        self.assertGreater(heading.x, 0.99)

    def test_culling_uses_world_space_bounds(self):
        """A large building parented under a scaled root stays visible when its
        surface is near the camera, even though its own location is far away."""
        self.build_spec(enemies=[], hazards=[], collectibles=[{"count": 1}])
        mesh = bpy.data.meshes.new("CullTestMesh")
        mesh.from_pydata([(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (0, 1)], [],
                         [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
        root = bpy.data.objects.new("CullTestRoot", None)
        building = bpy.data.objects.new("CullTestBuilding", mesh)
        for obj in (root, building):
            self.scene.collection.objects.link(obj)
        building.parent = root
        building.location = (0.0, 0.0, 0.0)
        root.scale = (40.0, 40.0, 40.0)          # 80 m wide, 40 m tall
        player = runtime.utils.find_player_object(self.scene)
        root.location = player.location + Vector((0.0, 50.0, -1.0))  # facade 10 m ahead
        optimization = self.scene.blendengine_optimization
        optimization.camera_frustum_generation = True
        optimization.hide_behind_camera = True
        session = self.start()
        session._update_visibility_culling()
        self.assertFalse(building.hide_get())
        root.location = player.location + Vector((0.0, -500.0, 0.0))  # far behind
        session._update_visibility_culling()
        self.assertTrue(building.hide_get())

    def _zombie_game(self, count=1):
        self.build_spec(hazards=[], collectibles=[{"count": 1}], goal={"type": "SURVIVE", "time_limit_seconds": 120},
                        enemies=[{"name": "Zombie", "count": count, "behavior": "ATTACK", "shape": "BRUTE",
                                  "color": "#557744", "size": 1.0, "speed": 2.0, "health": 50, "damage": 0}])
        player = runtime.utils.find_player_object(self.scene)
        zombies = [obj for obj in self.scene.objects if obj.blendengine_object.npc_behavior.enabled]
        return player, zombies

    def test_shambling_zombie_turns_steps_and_sways(self):
        player, (zombie,) = self._zombie_game()
        npc = zombie.blendengine_object.npc_behavior
        self.assertEqual((npc.gait, npc.turn_speed), ("SHAMBLE", 4.0))
        # Leg swing comes from shape keys on the zombie's mesh.
        zombie.shape_key_add(name="Basis")
        zombie.shape_key_add(name="BE_StepL")
        zombie.shape_key_add(name="BE_StepR")
        blocks = zombie.data.shape_keys.key_blocks
        base_z = zombie.location.z
        zombie.location = player.location + Vector((0.0, 10.0, base_z - player.location.z))
        zombie.rotation_euler.z = 0.0  # facing away from the player
        session = self.start()
        self.step(session, 0.25)
        facing = zombie.matrix_basis.to_3x3() @ Vector((0.0, 1.0, 0.0))
        self.assertGreater(facing.y, -0.95, "turned instantly instead of at turn_speed")
        heights, lean, left, right = [], [], [], []
        for _ in range(150):
            session.step(DT)
            heights.append(zombie.location.z)
            lean.append(zombie.rotation_euler.x)
            left.append(blocks["BE_StepL"].value)
            right.append(blocks["BE_StepR"].value)
        facing = zombie.matrix_basis.to_3x3() @ Vector((0.0, 1.0, 0.0))
        to_player = player.location - zombie.location
        to_player.z = 0.0
        facing.z = 0.0
        self.assertGreater(facing.normalized().dot(to_player.normalized()), 0.95)
        self.assertGreater(max(heights) - min(heights), 0.02)   # head bob
        self.assertLess(max(lean), -0.05)                        # leaning forward
        self.assertGreater(max(left), 0.3)
        self.assertGreater(max(right), 0.3)                      # legs alternate
        runtime.finish_active_session("Stopped")
        self.assertAlmostEqual(zombie.location.z, base_z, places=4)
        self.assertEqual((blocks["BE_StepL"].value, blocks["BE_StepR"].value), (0.0, 0.0))

    def test_walking_npcs_keep_apart(self):
        player, zombies = self._zombie_game(count=3)
        session = self.start()
        for zombie in zombies:
            zombie.location.x, zombie.location.y = player.location.x, player.location.y + 6.0
        self.step(session, 0.5)
        for index, first in enumerate(zombies):
            for second in zombies[index + 1:]:
                gap = Vector((first.location.x - second.location.x, first.location.y - second.location.y))
                self.assertGreater(gap.length, 0.8)

    def test_first_person_eases_in_looks_and_bobs(self):
        self.build_spec(camera="FIRST_PERSON", player={"can_shoot": True}, enemies=[], hazards=[],
                        collectibles=[{"count": 1}], goal={"type": "SURVIVE", "time_limit_seconds": 120})
        player = runtime.utils.find_player_object(self.scene)
        controller = player.blendengine_object.player_controller
        self.assertTrue(controller.mouse_look)
        camera = self.scene.camera
        session = self.start()
        session.look(100.0, 40.0)
        self.assertAlmostEqual(player.rotation_euler.z, -0.25, places=4)
        session.input_state.add("W")
        start = player.location.copy()
        self.step(session, DT)
        self.assertLess((player.location - start).length / DT, controller.walk_speed * 0.6)  # eases in
        heights = []
        for _ in range(60):
            session.step(DT)
            heights.append(camera.location.z - player.location.z)
        velocity = session._player_velocity
        self.assertAlmostEqual(velocity.length, controller.walk_speed, places=2)
        forward = Vector((-math.sin(-0.25), math.cos(-0.25), 0.0))
        self.assertGreater(velocity.normalized().dot(forward), 0.999)  # moves where it looks
        self.assertGreater(max(heights) - min(heights), 0.02)           # head bob
        self.assertGreater(camera.rotation_euler.x, math.radians(90.0))  # looking slightly up

    def test_world_bounds_keep_player_inside(self):
        self.build_spec(enemies=[], hazards=[], collectibles=[{"count": 1}])
        player = runtime.utils.find_player_object(self.scene)
        min_x, min_y, max_x, max_y = self.scene["blendengine_world_bounds"]
        session = self.start()
        session.input_state.add("D")
        player.location.x = max_x + 50.0
        self.step(session, DT)
        self.assertLessEqual(player.location.x, max_x + 1e-4)

    def test_2d_movement_stays_on_the_lane(self):
        self.create("2D platformer with slimes, collect 5 coins")
        player = runtime.utils.find_player_object(self.scene)
        enemies = [obj for obj in self.scene.objects if obj.blendengine_object.npc_behavior.enabled]
        session = self.start()
        session.input_state.update({"W", "D"})
        start_x = player.location.x
        self.step(session, 1.0)
        self.assertAlmostEqual(player.location.y, 0.0, places=4)
        self.assertGreater(player.location.x, start_x + 2.0)
        for enemy in enemies:
            self.assertAlmostEqual(enemy.location.y, 0.0, places=3)

    # -- user interface ----------------------------------------------------

    def test_ui_draw_code_uses_real_properties_operators_and_icons(self):
        from blendengine import panels

        layout = RecordingLayout(self)
        ai_game_creator.draw_ai_creator(layout, bpy.context)  # before any game exists
        self.create("forest coins")
        self.scene.blendengine_ai.status = "Built a game."
        for compact in (False, True):
            ai_game_creator.draw_ai_creator(layout, bpy.context, compact=compact)
        panels._draw_engine_dashboard(layout, bpy.context)
        panels._draw_game_creation(layout, self.scene)
        prefs = types.SimpleNamespace(layout=layout, api_key="", model="claude-opus-5-5", effort="medium")
        ai_game_creator.BE_AIGameCreatorPreferences.draw(prefs, bpy.context)
        self.assertIn("blendengine.ai_generate_game", layout.operators)
        self.assertIn("blendengine.ai_refine_game", layout.operators)

    # -- AI Studio (chat-first workspace) ----------------------------------

    def test_studio_chat_records_and_sends(self):
        settings = self.scene.blendengine_ai
        bpy.ops.blendengine.ai_chat_new()
        self.assertEqual(ai_game_creator.chat_messages(self.scene), [])
        self.assertEqual(bpy.ops.blendengine.ai_chat_send(), {"CANCELLED"})  # empty message

        settings.chat_input = "forest game collect 5 coins"
        self.assertEqual(bpy.ops.blendengine.ai_chat_send(), {"FINISHED"})
        self.assertEqual(settings.chat_input, "")
        self.assertEqual(settings.chat_mode, "CHANGE")
        messages = ai_game_creator.chat_messages(self.scene)
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["kind"], "create")
        title = messages[1]["title"]
        self.assertTrue(messages[1]["facts"])
        self.assertEqual(ai_studio._games(messages), [title])

        # A follow-up message changes the same game instead of starting over.
        settings.chat_input = "add lava and make it harder"
        self.assertEqual(bpy.ops.blendengine.ai_chat_send(), {"FINISHED"})
        messages = ai_game_creator.chat_messages(self.scene)
        self.assertEqual(messages[2]["kind"], "change")
        self.assertEqual(messages[3]["title"], title)
        self.assertEqual(ai_studio._games(messages), [title])
        spec = ai_game_creator._stored_spec(self.scene)
        self.assertIn("LAVA", [hazard["kind"] for hazard in spec["hazards"]])

        # "New game" starts a fresh conversation; examples fill the composer.
        bpy.ops.blendengine.ai_chat_example(index=1)
        self.assertEqual(settings.chat_input, ai_game_creator.EXAMPLE_PROMPTS[1][1])
        self.assertEqual(settings.chat_mode, "NEW")
        bpy.ops.blendengine.ai_chat_new()
        self.assertEqual(ai_game_creator.chat_messages(self.scene), [])

        for _ in range(ai_game_creator.MAX_CHAT_MESSAGES + 5):
            ai_game_creator.record_chat(self.scene, "user", "hi")
        self.assertEqual(len(ai_game_creator.chat_messages(self.scene)), ai_game_creator.MAX_CHAT_MESSAGES)

    def test_studio_headers_use_real_properties_and_operators(self):
        layout = RecordingLayout(self)
        context = types.SimpleNamespace(scene=self.scene, preferences=bpy.context.preferences, region=None,
                                        space_data=None)
        ai_studio.draw_composer(layout, context)  # before any game exists
        self.create("forest coins")
        ai_studio.draw_composer(layout, context)
        self.scene.blendengine_ai.busy = True
        ai_studio.draw_composer(layout, context)
        self.scene.blendengine_ai.busy = False
        ai_studio.draw_game_header(layout, context)
        for idname in ("blendengine.ai_chat_send", "blendengine.ai_chat_new", "blendengine.ai_cancel",
                       "blendengine.test_run_scene", "blendengine.ai_variation", "blendengine.prepare_build"):
            self.assertIn(idname, layout.operators)
        # Outside the studio the 3D View keeps Blender's own header.
        self.assertIs(bpy.types.VIEW3D_HT_header.draw, ai_studio._header_draw)
        self.assertFalse(ai_studio.utils.is_studio_chat_area(bpy.context))

    # -- persistence & export ----------------------------------------------

    def test_save_reload_and_export(self):
        self.create("O'rmonda 5 ta tanga yig'adigan o'yin")
        title = self.scene.blendengine_project.game_title
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ai_game.blend")
            bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
            bpy.ops.wm.open_mainfile(filepath=path)
            scene = bpy.context.scene
            self.scene = scene
            self.assertEqual(scene.blendengine_project.game_title, title)
            coin = next(obj for obj in scene.objects if obj.blendengine_object.object_tag == "Pickup")
            actions = [action.action_type for behavior in coin.blendengine_object.behaviors for action in behavior.actions]
            self.assertIn("ADD_VARIABLE", actions)
            self.assertIn("COLLECT_OBJECT", actions)
            self.assertTrue(scene.blendengine_ai.last_spec_json)

            scene.blendengine_project.target_platform = "WEB"
            scene.blendengine_project.build_folder = directory
            package = export_system.prepare_build_package(bpy.context)
            with open(package["game_data"], encoding="utf-8") as handle:
                game_data = json.load(handle)
            exported = json.dumps(game_data)
            self.assertIn("COLLECT_OBJECT", exported)
            self.assertIn("WIN_GAME", exported)


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    program = unittest.main(argv=[sys.argv[0]] + arguments, exit=False, verbosity=2)
    if not program.result.wasSuccessful():
        sys.exit(1)
