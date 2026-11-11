# SPDX-License-Identifier: GPL-2.0-or-later
"""Integration tests for the generated Highland Patrol first-person level.

Run from the repository root with Blender 4.3 (or its ``bpy`` module)::

    blender --background --factory-startup --python-exit-code 1 \
        --python tests/python/blendengine_highland.py
"""

from pathlib import Path
import sys
import unittest

import bpy
from mathutils import Vector


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))

import blendengine
from blendengine import highland, runtime, utils


class HighlandPatrolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blendengine.register()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.created = highland.generate_highland_patrol(bpy.context, grass_tufts=200, trees=40)
        cls.scene = bpy.context.scene

    @classmethod
    def tearDownClass(cls):
        runtime.finish_active_session()
        blendengine.unregister()

    def test_level_is_playable_as_generated(self):
        result = runtime.validate_scene(self.scene)
        self.assertTrue(result.ok, result.all_messages())
        self.assertEqual(utils.find_player_object(self.scene), self.created["player"])
        controller = self.created["player"].blendengine_object.player_controller
        self.assertEqual(controller.controller_type, "FIRST_PERSON")
        self.assertEqual(self.scene.camera, self.created["camera"])
        self.assertEqual(self.created["rifle"].parent, self.created["camera"])
        self.assertEqual(self.created["rifle"].blendengine_object.object_tag, "Weapon")

    def test_everything_stands_on_the_generated_ground(self):
        terrain = self.created["terrain"]
        self.assertEqual(terrain.blendengine_object.object_tag, "Ground")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for obj in [self.created["player"]] + self.created["enemies"]:
            origin = Vector((obj.location.x, obj.location.y, 200.0))
            hit, location, _normal, _index, hit_obj, _matrix = self.scene.ray_cast(
                depsgraph, origin, Vector((0, 0, -1)))
            self.assertTrue(hit)
            # Feet within a hand's width of the surface under them (the mesh interpolates the height function).
            ground = float(highland.terrain_height(obj.location.x, obj.location.y))
            self.assertAlmostEqual(obj.location.z - 0.9, ground, delta=0.01)
            self.assertLess(abs(location.z - (obj.location.z - 0.9)), 2.0, hit_obj.name)

    def test_repeated_props_share_mesh_data(self):
        meshes = {obj.data.name for obj in self.scene.objects if obj.type == "MESH"}
        mesh_objects = sum(1 for obj in self.scene.objects if obj.type == "MESH")
        self.assertGreater(mesh_objects, 300)
        self.assertLess(len(meshes), 25)
        self.assertEqual(len(bpy.data.images), 0, "the level needs no texture files")

    def test_enemies_are_targets_for_the_weapon(self):
        self.assertEqual(len(self.created["enemies"]), 6)
        for enemy in self.created["enemies"]:
            settings = enemy.blendengine_object
            self.assertEqual(settings.object_tag, "Enemy")
            self.assertTrue(settings.health.enabled)
            self.assertTrue(settings.npc_behavior.enabled)
            self.assertEqual(settings.npc_behavior.target_object, self.created["player"])

    def test_same_seed_builds_the_same_level(self):
        positions = [tuple(round(v, 4) for v in enemy.location) for enemy in self.created["enemies"]]
        again = highland.generate_highland_patrol(bpy.context, grass_tufts=200, trees=40)
        type(self).created = again
        self.assertEqual([tuple(round(v, 4) for v in enemy.location) for enemy in again["enemies"]], positions)

    def test_z_session_walks_the_terrain_and_the_rifle_hits_an_enemy(self):
        player, camera = self.created["player"], self.created["camera"]
        enemy = self.created["enemies"][0]
        session, validation = runtime.start_test_run(bpy.context)
        self.assertIsNotNone(session, validation.all_messages())
        try:
            # Walk uphill: the player must follow the ground, not float or sink.
            player.location.x, player.location.y = 25.0, -20.0
            for _ in range(5):
                session.step(1.0 / 60.0)
            expected = float(highland.terrain_height(player.location.x, player.location.y)) + 0.9
            self.assertAlmostEqual(player.location.z, expected, delta=0.35)

            # Stand in front of an enemy and fire.
            player.location = enemy.location + Vector((0.0, -6.0, 0.0))
            player.rotation_euler.z = 0.0
            session.step(1.0 / 60.0)
            camera.location = enemy.location + Vector((0.0, -6.0, 0.2))
            camera.rotation_euler = (1.5708, 0.0, 0.0)
            bpy.context.view_layer.update()
            health = enemy.blendengine_object.health
            before = health.current_health
            session._attack_cooldown = 0.0
            session._shoot_weapon()
            self.assertLess(health.current_health, before)
        finally:
            runtime.finish_active_session()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HighlandPatrolTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError("BlendEngine Highland Patrol tests failed")
