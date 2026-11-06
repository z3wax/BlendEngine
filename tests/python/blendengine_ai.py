# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual NPC navigation, perception, human reuse and editor replay checks."""
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts/addons_core'))
import blendengine
from blendengine import ai_system, components, operators, runtime, story_game, utils


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blendengine.register()

    @classmethod
    def tearDownClass(cls):
        blendengine.unregister()

    def setUp(self):
        self.previous = bpy.context.scene
        self.scene = bpy.data.scenes.new('NPC behavior regression')
        bpy.context.window.scene = self.scene
        self.scene.blendengine_project.show_logs = False
        self.scene.blendengine_optimization.camera_frustum_generation = False
        self.scene.blendengine_optimization.hide_behind_camera = False
        self.session = None
        ground = self.cube('Ground', (0, 0, -.5), (40, 40, 1))
        utils.mark_game_object(ground, tag='Ground')
        self.player = self.cube('Player', (6, 0, .92), (.48, .38, 1.84))
        components.add_player_controller(self.player).gravity = 0
        camera = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
        self.scene.collection.objects.link(camera)
        camera.location = (0, -6, 4)
        self.scene.camera = camera

    def tearDown(self):
        if self.session is not None:
            self.session.stop()
        bpy.context.window.scene = self.previous
        for obj in tuple(self.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(self.scene)

    def cube(self, name, location, scale=(1, 1, 1)):
        bpy.ops.mesh.primitive_cube_add(size=1, location=location)
        obj = bpy.context.object
        obj.name, obj.scale = name, scale
        return obj

    def npc(self, behavior='FOLLOW_PLAYER', location=(0, 0, .92)):
        obj = self.cube('Agent', location, (.48, .38, 1.84))
        settings = components.add_npc_behavior(obj, behavior, self.player)
        settings.move_speed = 3.0
        settings.detection_range = 20
        return obj

    def start(self):
        bpy.context.view_layer.update()
        self.session = runtime.GameSession(bpy.context)
        self.session.start()
        return self.session

    def advance(self, steps=300):
        points = []
        for _ in range(steps):
            self.session.step(1/60)
            points.append(tuple(self.agent.location))
        return points

    def test_follow_detours_solid_wall_and_does_not_tunnel(self):
        self.agent = self.npc()
        wall = self.cube('Solid wall', (3, 0, 1), (.6, 4, 2))
        components.add_collider(wall, 'Obstacle')
        wall.hide_render = True  # Invisible collision walls still block agents.
        self.start()
        points = self.advance(600)
        self.assertLess((self.agent.location-self.player.location).xy.length, 1.6)
        self.assertGreater(max(abs(p[1]) for p in points), 2.3)
        self.assertTrue(all(not (2.4 < x < 3.6 and abs(y) < 2.3) for x, y, z in points))
        self.assertGreater(self.session.agent_states[self.agent.name]['walked'], 6)
        # Decisions are throttled instead of asking a model or replanning each frame.
        self.assertLess(self.session.agent_states[self.agent.name]['decisions'], 80)
        self.assertEqual(self.session.agent_states[self.agent.name]['navigation_rebuilds'], 1)

    def test_enclosed_goal_stops_then_recovers_after_wall_moves(self):
        self.agent = self.npc()
        self.player.location = (3, 0, .92)
        wall = self.cube('Blocking solid volume', (3, 0, 1), (3, 4, 2))
        self.start()
        self.advance(120)
        self.assertLess(self.agent.location.x, .1)
        self.assertEqual(self.session.agent_states[self.agent.name]['state'], 'BLOCKED')
        wall.location.y = 10
        bpy.context.view_layer.update()
        self.advance(240)
        self.assertGreater(self.agent.location.x, 1)
        self.assertLess((self.agent.location-self.player.location).xy.length, 1.6)

    def test_patrol_is_continuous_and_guard_returns_home(self):
        self.agent = self.npc('PATROL')
        self.agent.blendengine_object.npc_behavior.patrol_radius = 2
        self.start()
        first = self.agent.location.copy()
        self.session.step(1/60)
        self.assertLess((self.agent.location-first).length, .06)
        points = self.advance(360)
        self.assertGreater(max(p[0] for p in points), 1.7)
        self.assertGreater(max(p[1] for p in points), 1.7)
        self.session.reset_agents()
        npc = self.agent.blendengine_object.npc_behavior
        npc.behavior_template, npc.patrol_radius = 'GUARD', 3
        self.player.location.x = 2.8
        self.advance(120)
        self.assertGreater(self.agent.location.x, .7)
        self.player.location.x = 15
        self.advance(180)
        self.assertLess(self.agent.location.xy.length, .25)

    def test_occluded_enemy_cannot_detect_or_damage_through_wall(self):
        self.player.location = (1.8, 0, .92)
        components.add_health(self.player)
        self.agent = self.npc('ATTACK')
        self.agent.blendengine_object.npc_behavior.attack_range = 3
        self.cube('Occluding wall', (.9, 0, 1), (.3, 8, 2))
        self.start()
        self.advance(180)
        self.assertEqual(self.player.blendengine_object.health.current_health, 100)
        self.assertLess(self.agent.location.xy.length, .01)
        self.assertEqual(self.session.agent_states[self.agent.name]['state'], 'SEARCH')

    def test_pause_loop_freezes_agent_and_stop_restores_even_if_disabled(self):
        self.agent = self.npc()
        original = self.agent.location.copy()
        self.start()
        self.advance(40)
        before = self.agent.location.copy()
        self.scene.blendengine_project.test_paused = True
        fake = SimpleNamespace(_session=self.session, _timer=None, _last_tick=time.perf_counter()-.1)
        event = SimpleNamespace(type='TIMER', timer=None, value='NOTHING')
        for _ in range(8):
            operators.BE_OT_test_run_scene.modal(fake, bpy.context, event)
        self.assertEqual(tuple(self.agent.location), tuple(before))
        self.scene.blendengine_project.test_paused = False
        fake._last_tick = time.perf_counter()-.1
        operators.BE_OT_test_run_scene.modal(fake, bpy.context, event)
        self.assertGreater(self.agent.location.x, before.x)
        self.agent.blendengine_object.npc_behavior.enabled = False
        self.session.step(1/60)
        self.session.stop()
        self.assertEqual(tuple(self.agent.location), tuple(original))

    def test_live_rename_keeps_one_brain_and_original_stop_snapshot(self):
        self.agent = self.npc()
        original = self.agent.location.copy()
        self.start()
        self.advance(20)
        self.agent.name = 'Renamed Scout'
        self.advance(20)
        self.assertEqual(len(self.session._npc_agent_manager.agents), 1)
        self.assertEqual(set(self.session.agent_states), {'Renamed Scout'})
        self.session.stop()
        self.assertEqual(tuple(self.agent.location), tuple(original))

    def test_idle_agents_do_not_dirty_object_transforms(self):
        self.player.location = (1, 0, .92)
        self.agent = self.npc()
        self.start()
        for _ in range(3):
            self.session.step(1/60)
            bpy.context.view_layer.update()
        changed = []
        def observed(scene, graph):
            changed.extend(u.id.name for u in graph.updates if isinstance(u.id, bpy.types.Object))
        bpy.app.handlers.depsgraph_update_post.append(observed)
        try:
            for _ in range(8):
                self.session.step(1/60)
                bpy.context.view_layer.update()
        finally:
            bpy.app.handlers.depsgraph_update_post.remove(observed)
        self.assertEqual(changed, [])

    def test_guide_waits_for_player_and_advances_only_after_player_collects(self):
        self.agent = self.npc('GUIDE')
        clue = self.cube('Signal clue 01', (4, 0, .6))
        portal = bpy.data.objects.new('Terminal', None)
        self.scene.collection.objects.link(portal)
        portal.location = (0, 12, .9)
        self.start()
        game = SimpleNamespace(cores=[clue], collected=set(), portal=portal, state='RUNNING', elapsed=0.0)
        game.update = lambda dt: setattr(game, 'elapsed', game.elapsed+dt)
        game.stop = lambda: None
        self.session._gameplay = game
        self.player.location.x = -6
        self.advance(60)
        self.assertEqual(self.session.agent_states[self.agent.name]['state'], 'WAIT_FOR_PLAYER')
        self.assertLess(self.agent.location.xy.length, .01)
        self.player.location.x = 6
        self.advance(15)
        self.assertEqual(self.session.agent_states[self.agent.name]['state'], 'CATCH_UP')
        self.assertGreater(self.agent.location.x, .3)
        self.player.location.x = 2
        self.advance(150)
        self.assertGreater(self.agent.location.x, 3)
        self.assertEqual(game.collected, set())
        game.collected.add(clue.name)
        self.advance(240)
        self.assertGreater(self.agent.location.y, 2)
        self.assertEqual(self.session.agent_states[self.agent.name]['state'], 'WAIT_FOR_PLAYER')
        game.state = 'WON'
        self.advance(15)
        # Completion stops the guide even when its player is far away.
        self.assertEqual(self.session.agent_states[self.agent.name]['state'], 'COMPLETE')

    def test_human_creation_shares_mesh_and_materials_but_not_pose(self):
        made = story_game.create_story(bpy.context)
        old_scene = self.scene
        self.scene = made['scene']
        self.player = made['player']
        self.agent = ai_system.create_agent(bpy.context, location=(1.5, -9, .92))
        actor = self.scene.objects[self.agent['blendengine_agent_actor']]
        rig = self.scene.objects[self.agent['blendengine_agent_rig']]
        self.assertIs(actor.data, made['actor'].data)
        self.assertIsNot(rig.data, made['rig'].data)
        self.assertIs(actor.modifiers[0].object, rig)
        self.assertEqual(len(rig.pose.bones), 11)
        pose = {b.name: tuple(b.rotation_euler) for b in rig.pose.bones}
        quality = (self.scene.render.engine, self.scene.eevee.taa_samples,
                   self.scene.render.resolution_percentage, self.scene.view_settings.view_transform)
        self.start()
        self.player.location = (0, -5, .92)
        angles = []
        for _ in range(90):
            self.session.step(1/60)
            angles.append(rig.pose.bones['leg.L'].rotation_euler.x)
        self.assertGreater(self.session.agent_states[self.agent.name]['walked'], .3)
        self.assertGreater(max(angles)-min(angles), .1)
        self.assertEqual(quality, (self.scene.render.engine, self.scene.eevee.taa_samples,
                                 self.scene.render.resolution_percentage, self.scene.view_settings.view_transform))
        self.session.stop()
        self.assertTrue(all(tuple(rig.pose.bones[n].rotation_euler) == value for n, value in pose.items()))
        # The old setup scene is no longer the current test fixture.
        bpy.data.scenes.remove(old_scene)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AgentTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
