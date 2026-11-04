# SPDX-License-Identifier: GPL-2.0-or-later
"""Gameplay regressions for the editor runtime, without a GPU or rendered FPS.

    blender -b --factory-startup --python-exit-code 1 \\
        --python tests/python/blendengine_runtime.py
"""

from pathlib import Path
import random
import sys
from types import SimpleNamespace
import unittest

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))

import blendengine
from blendengine import components, performance, runtime, utils


class RuntimeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blendengine.register()

    @classmethod
    def tearDownClass(cls):
        blendengine.unregister()

    def setUp(self):
        self.previous_scene = bpy.context.scene
        self.scene = bpy.data.scenes.new("Runtime Regression")
        bpy.context.window.scene = self.scene
        self.scene.blendengine_project.show_logs = False
        self.session = None

    def tearDown(self):
        if self.session is not None:
            self.session = None
        for obj in tuple(self.scene.objects):
            mesh = obj.data if obj.type == 'MESH' else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        bpy.context.window.scene = self.previous_scene
        bpy.data.scenes.remove(self.scene)

    def cube(self, name, location=(0, 0, 0), dimensions=(1, 1, 1), collider=False):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(
            [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5),
             (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
             (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5),
             (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5)],
            [], [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
                 (1, 5, 6, 2), (2, 6, 7, 3), (4, 0, 3, 7)],
        )
        obj = bpy.data.objects.new(name, mesh)
        self.scene.collection.objects.link(obj)
        obj.location = location
        obj.scale = dimensions
        utils.mark_game_object(obj, tag=name)
        if collider:
            components.add_collider(obj)
        return obj

    def new_session(self):
        bpy.context.view_layer.update()
        self.session = runtime.GameSession(bpy.context)
        return self.session

    def behavior(self, owner, event_type, action_type='SHOW_LOG', text="Event", tag=""):
        behavior = owner.blendengine_object.behaviors.add()
        behavior.name = "Regression " + event_type
        event = behavior.events.add()
        event.event_type = event_type
        event.tag = tag
        action = behavior.actions.add()
        action.action_type = action_type
        action.text_value = text
        return behavior, event, action

    def test_bound_input_moves_player_and_release_stops_movement(self):
        player = self.cube("Player", (0, 0, 1))
        controller = components.add_player_controller(player)
        controller.gravity = 0
        controller.walk_speed = 4
        binding = self.scene.blendengine_input_map.bindings.add()
        binding.action = 'MOVE_RIGHT'
        binding.key = 'D'
        session = self.new_session()

        session.handle_event(SimpleNamespace(type='D', value='PRESS'))
        session.step(0.25)
        self.assertAlmostEqual(player.location.x, 1.0)
        session.handle_event(SimpleNamespace(type='D', value='RELEASE'))
        session.step(0.25)
        self.assertAlmostEqual(player.location.x, 1.0)

    def test_diagonal_motion_keeps_walk_speed_and_jump_still_runs(self):
        player = self.cube("Player", (0, 0, 1))
        controller = components.add_player_controller(player)
        controller.gravity = 0
        controller.walk_speed = 4
        controller.jump_force = 5
        for action, key in [('MOVE_RIGHT', 'D'), ('MOVE_FORWARD', 'W'), ('JUMP', 'SPACE')]:
            binding = self.scene.blendengine_input_map.bindings.add()
            binding.action, binding.key = action, key
        session = self.new_session()
        session.input_state.update({'D', 'W'})
        session.step(0.25)
        self.assertAlmostEqual(player.location.xy.length, 1.0, places=6)
        session.input_state.clear()
        session.input_state.add('SPACE')
        session.step(0.1)
        self.assertAlmostEqual(player.location.z, 1.5, places=6)

    def test_collision_enter_runs_once_until_objects_separate(self):
        self.cube("First", collider=True)
        second = self.cube("Second", (0.5, 0, 0), collider=True)
        session = self.new_session()
        calls = []
        session._execute_behaviors_on_object = lambda obj, event, dt, tag="": calls.append((obj.name, event, tag))

        session.step(0)
        self.assertEqual(len(calls), 2)
        session.step(0)
        self.assertEqual(len(calls), 2)
        second.location.x = 8
        session.step(0)
        self.assertFalse(session._collision_overlaps)
        second.location.x = 0.5
        session.step(0)
        self.assertEqual(len(calls), 4)

    def test_sparse_collision_pairs_and_event_order_match_exhaustive_spheres(self):
        rng = random.Random(3417)
        for index in range(96):
            self.cube(
                "Collider %03d" % index,
                (rng.uniform(-12, 12), rng.uniform(-12, 12), rng.uniform(-3, 3)),
                tuple(rng.uniform(0.15, 3.5) for _ in range(3)), collider=True,
            )
        # A large collider exercises extents spanning many smaller colliders.
        self.cube("Wide ground", (0, 0, -2), (18, 16, 0.5), collider=True)
        session = self.new_session()
        colliders = tuple(self.scene.objects)
        pairs, expected_calls = set(), []
        for index, first in enumerate(colliders):
            for second in colliders[index + 1:]:
                radius = max(*first.dimensions, 0.1) * 0.5 + max(*second.dimensions, 0.1) * 0.5
                if (first.location - second.location).length <= radius:
                    pairs.add(tuple(sorted((first.name, second.name))))
                    expected_calls.extend([(first.name, 'ON_COLLISION', second.name),
                                           (second.name, 'ON_COLLISION', first.name)])
        calls = []
        session._execute_behaviors_on_object = lambda obj, event, dt, tag="": calls.append((obj.name, event, tag))

        session.step(0)

        self.assertTrue(pairs)
        self.assertEqual(session._collision_overlaps, pairs)
        self.assertEqual(calls, expected_calls)

    def test_collision_action_moving_later_collider_preserves_same_tick_events(self):
        first = self.cube("A", collider=True)
        self.cube("B", (0.4, 0, 0), collider=True)
        later = self.cube("C", (20, 0, 0), collider=True)
        _behavior, _event, action = self.behavior(first, 'ON_COLLISION', 'MOVE_OBJECT', tag='B')
        action.target_object = later
        action.vector_value = (-20, 0, 0)
        session = self.new_session()

        session.step(1.0)

        self.assertAlmostEqual(later.location.x, 0)
        self.assertEqual(session._collision_overlaps, {('A', 'B'), ('A', 'C'), ('B', 'C')})

    def test_sphere_contact_boundary_is_inclusive(self):
        self.cube("A", dimensions=(2, 2, 2), collider=True)
        second = self.cube("B", (2, 0, 0), dimensions=(2, 2, 2), collider=True)
        session = self.new_session()
        session.step(0)
        self.assertEqual(session._collision_overlaps, {('A', 'B')})
        second.location.x = 2.001
        session.step(0)
        self.assertFalse(session._collision_overlaps)

    def test_trigger_tag_filter_and_reentry_are_preserved(self):
        trigger = self.cube("Gate", dimensions=(3, 3, 3))
        components.add_trigger_zone(trigger)
        other = self.cube("Runner", (0.5, 0, 0))
        self.behavior(trigger, 'ON_ENTER_TRIGGER', text='gate accepted runner', tag='Runner')
        session = self.new_session()

        session.step(0)
        self.assertEqual(sum('gate accepted runner' in line for line in session.logs), 1)
        session.step(0)
        self.assertEqual(sum('gate accepted runner' in line for line in session.logs), 1)
        other.location.x = 20
        session.step(0)
        other.location.x = 0.5
        session.step(0)
        self.assertEqual(sum('gate accepted runner' in line for line in session.logs), 2)

    def test_component_enable_changes_are_observed_on_the_next_tick(self):
        self.cube("A", collider=True)
        second = self.cube("B", (0.4, 0, 0), collider=True)
        component = utils.find_component(second, 'COLLIDER')
        session = self.new_session()
        session.step(0)
        self.assertEqual(session._collision_overlaps, {('A', 'B')})
        component.enabled = False
        session.step(0)
        self.assertFalse(session._collision_overlaps)
        component.enabled = True
        session.step(0)
        self.assertEqual(session._collision_overlaps, {('A', 'B')})

    def test_new_behavior_and_enabled_flag_are_observed_during_play(self):
        obj = self.cube("Actor")
        session = self.new_session()
        session.step(0)
        behavior, _event, _action = self.behavior(obj, 'ON_UPDATE', text='authored while playing')
        session.step(0)
        self.assertEqual(sum('authored while playing' in line for line in session.logs), 1)
        behavior.enabled = False
        session.step(0)
        self.assertEqual(sum('authored while playing' in line for line in session.logs), 1)

    def test_spawning_object_is_visible_to_collisions_on_next_tick(self):
        actor = self.cube("Actor", (0, 0, 0), collider=True)
        prefab = self.cube("Prefab", (10, 0, 0), collider=True)
        _behavior, _event, action = self.behavior(actor, 'ON_START', 'SPAWN_OBJECT')
        action.target_object = prefab
        action.vector_value = (-10, 0, 0)
        session = self.new_session()

        session.execute_behaviors('ON_START', 0)
        session.step(0)

        self.assertEqual(len(self.scene.objects), 3)
        self.assertEqual(session._collision_overlaps, {('Actor', 'Prefab.001')})

    def test_delete_and_replace_with_equal_object_count_does_not_leave_stale_cache(self):
        self.cube("A", collider=True)
        removed = self.cube("B", (0.4, 0, 0), collider=True)
        session = self.new_session()
        session.step(0)
        bpy.data.objects.remove(removed, do_unlink=True)
        self.cube("Replacement", (0.3, 0, 0), collider=True)
        bpy.context.view_layer.update()

        session.step(0)

        self.assertEqual(session._collision_overlaps, {('A', 'Replacement')})

    def test_forced_metrics_do_not_report_the_target_budget_as_measured_fps(self):
        self.cube("Actor")
        self.scene.blendengine_performance_budget.target_fps = 144
        session = self.new_session()

        session._update_runtime_metrics(force=True)

        self.assertEqual(session.fps, 0)
        self.assertEqual(self.scene.blendengine_project.runtime_fps, 0)

    def test_expensive_asset_estimates_are_reused_and_force_refreshable(self):
        self.cube("Actor")
        session = self.new_session()
        original = performance.estimate_scene
        calls = []

        def counted(scene):
            calls.append(scene.name)
            return original(scene)

        performance.estimate_scene = counted
        try:
            session._update_runtime_metrics()
            session._update_runtime_metrics()
            self.assertEqual(len(calls), 1)
            session._update_runtime_metrics(force=True)
            self.assertEqual(len(calls), 2)
            session.elapsed += 1.1
            session._update_runtime_metrics()
            self.assertEqual(len(calls), 3)
        finally:
            performance.estimate_scene = original

    def test_visible_triangle_totals_track_hiding_and_force_refresh_tracks_topology(self):
        first = self.cube("First")
        second = self.cube("Second", (5, 0, 0))
        session = self.new_session()
        session._update_runtime_metrics(force=True)
        self.assertEqual(self.scene.blendengine_project.runtime_triangles_visible, 24)
        second.hide_set(True)
        session._update_runtime_metrics()
        self.assertEqual(self.scene.blendengine_project.runtime_triangles_visible, 12)

        first.data.clear_geometry()
        first.data.from_pydata(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
            [], [(0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)],
        )
        first.data.update()
        bpy.context.view_layer.update()
        session._update_runtime_metrics(force=True)

        self.assertEqual(self.scene.blendengine_project.runtime_triangles_visible, 4)
        self.assertEqual(session._geometry_metrics['triangle_count'], 16)


if __name__ == '__main__':
    print("BlendEngine gameplay integration on Blender", bpy.app.version_string)
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RuntimeIntegrationTests)
    )
    if not result.wasSuccessful():
        raise RuntimeError("BlendEngine runtime integration tests failed")
