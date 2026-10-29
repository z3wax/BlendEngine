# SPDX-License-Identifier: GPL-2.0-or-later
"""Neon Relay gameplay regression, using the real GameSession input loop.

    blender -b --factory-startup --python-exit-code 1 \
        --python tests/python/blendengine_demo.py

No rendering, navigation flythrough, or simulated score increments are used.
The victory test steers with the same WASD input state read by live play mode.
Native GUI input/video verification is a separate check.
"""

from pathlib import Path
import sys
import unittest

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "addons_core"))
import blendengine
from blendengine import demo_game, runtime


class NeonRelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blendengine.register()

    def setUp(self):
        self.original_scene = bpy.context.scene
        self.objects = demo_game.create_demo(bpy.context)
        self.scene = self.objects["scene"]
        self.player = self.objects["player"]
        self.session = runtime.GameSession(bpy.context)
        # Isolate application workspace mutation from the real gameplay loop.
        self.session._prepare_play_view = lambda: None
        self.session.start()
        self.game = self.session._gameplay

    def tearDown(self):
        self.session.stop()
        if bpy.context.window is not None:
            bpy.context.window.scene = self.original_scene
        for obj in tuple(self.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(self.scene)

    def advance(self, frames=1, keys=()):
        self.session.input_state = set(keys)
        for _ in range(frames):
            self.session.step(1.0 / 60.0)

    def steer_to(self, x, y):
        for _ in range(1500):
            if self.game.state == "WON":
                return  # Portal arrival freezes the runner inside its goal radius.
            delta_x, delta_y = x-self.player.location.x, y-self.player.location.y
            if abs(delta_x) < 0.12 and abs(delta_y) < 0.12:
                self.session.input_state.clear()
                return
            keys = set()
            if abs(delta_x) >= 0.1:
                keys.add("D" if delta_x > 0 else "A")
            if abs(delta_y) >= 0.1:
                keys.add("W" if delta_y > 0 else "S")
            self.advance(keys=keys)
        self.fail("Player could not reach waypoint (%s,%s); actual %s" % (x, y, self.player.location))

    def test_real_input_collects_five_cores_and_wins_at_portal(self):
        self.assertTrue(runtime.validate_scene(self.scene).ok)
        self.assertEqual(self.game.state, "RUNNING")
        for waypoint in demo_game.RECORDING_WAYPOINTS:
            self.steer_to(*waypoint)
            if self.game.state == "WON":
                break
        self.assertEqual(self.game.state, "WON")
        self.assertEqual(self.game.score.int_value, 5)
        self.assertEqual(len(self.game.collected), 5)
        self.assertTrue(all(core.hide_viewport and core.hide_render for core in self.objects["cores"]))
        self.assertEqual(self.game.health.current_health, 100)
        self.assertFalse(self.player.blendengine_object.player_controller.enabled)
        self.assertGreater(self.game.elapsed, 1)
        # Entering the portal without collecting does not award a victory.
        self.advance(keys={"R"})
        self.advance()
        self.player.location.xy = self.objects["portal"].location.xy
        self.advance()
        self.assertEqual(self.game.state, "RUNNING")
        self.assertEqual(self.game.score.int_value, 0)

    def test_jump_avoids_hazard_and_damage_can_end_game(self):
        hazard = self.objects["hazards"][0]
        self.player.location.x, self.player.location.y = hazard.location.x, hazard.location.y
        self.player.location.z = 1.8
        self.advance()
        self.assertEqual(self.game.health.current_health, 100)
        for _ in range(4):
            self.player.location.z = 0.92
            self.session._vertical_velocity[self.player.name] = 0
            self.game._hazard_cooldown = 0
            self.advance()
        self.assertEqual(self.game.health.current_health, 0)
        self.assertEqual(self.game.state, "LOST")
        self.assertFalse(self.player.blendengine_object.player_controller.enabled)

    def test_restart_restores_pickups_score_health_and_spawn(self):
        self.steer_to(*demo_game.RECORDING_WAYPOINTS[0])
        self.assertEqual(self.game.score.int_value, 1)
        self.advance(keys={"R"})
        self.advance()
        self.assertEqual(self.game.state, "RUNNING")
        self.assertEqual(self.game.score.int_value, 0)
        self.assertEqual(len(self.game.collected), 0)
        self.assertTrue(all(not core.hide_viewport and not core.hide_render for core in self.objects["cores"]))
        self.assertLess((self.player.location.xy - Vector(demo_game.SPAWN).xy).length, 0.01)
        self.assertEqual(self.game.health.current_health, 100)

    def test_stop_restores_camera_for_another_play_session(self):
        camera_location = self.scene.camera.location.copy()
        self.advance(30, keys={"W"})
        self.assertGreater((self.scene.camera.location-camera_location).length, 1)
        self.session.stop()
        self.assertLess((self.scene.camera.location-camera_location).length, 0.001)
        # A second session must not inherit the previous run's camera offset.
        self.session = runtime.GameSession(bpy.context)
        self.session._prepare_play_view = lambda: None
        self.session.start()
        self.game = self.session._gameplay
        self.advance()
        self.assertLess((self.scene.camera.location-camera_location).length, 0.001)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NeonRelayTests))
    if not result.wasSuccessful():
        raise RuntimeError("Neon Relay gameplay regressions failed")
