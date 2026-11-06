# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the native scene assistant in Blender, including HTTP model transport.

Run with Blender 3.6 --background --factory-startup --python-exit-code 1.
No external model or credentials are used. GUI Undo is a separate manual check;
these tests verify scene transactions and cancellation in background Blender.
"""

from contextlib import contextmanager
import http.server
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/addons_core'))
import blendengine
blendengine.register()
from blendengine import ai_system, editor_agent, export_system


def create_action(name='Planned Cube'):
    return {'tool': 'create_object', 'name': name, 'kind': 'CUBE',
            'location': [1, 2, 3], 'scale': [1, 1, 1], 'color': [.8, .1, .05]}


@contextmanager
def model_server(plan, *, release=None):
    """A real loopback HTTP endpoint, optionally held after receiving a request."""
    entered = threading.Event()
    requests = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append({'path': self.path, 'authorization': self.headers.get('Authorization'),
                             'body': json.loads(self.rfile.read(int(self.headers['Content-Length'])))})
            entered.set()
            if release is not None:
                release.wait(4)
            payload = json.dumps({'choices': [{'message': {'content': json.dumps(plan)}}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:%d/v1' % server.server_port, entered, requests
    finally:
        if release is not None:
            release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class EditorAgentTests(unittest.TestCase):
    def setUp(self):
        editor_agent._cancel_jobs()
        self.previous_scene = bpy.context.window.scene
        self.scene = bpy.data.scenes.new('Scene Agent regression')
        bpy.context.window.scene = self.scene
        self.settings = self.scene.blendengine_agent
        self.owned = {name: set(getattr(bpy.data, name)) for name in
                      ('objects', 'meshes', 'materials', 'lights', 'armatures', 'actions')}

    def tearDown(self):
        editor_agent._cancel_jobs()
        bpy.context.window.scene = self.previous_scene
        for obj in list(self.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(self.scene)
        for name in ('meshes', 'lights', 'armatures', 'materials', 'actions'):
            collection = getattr(bpy.data, name)
            for block in set(collection) - self.owned[name]:
                if block.users == 0:
                    collection.remove(block)

    def cube(self, name, location=(0, 0, 0)):
        bpy.ops.mesh.primitive_cube_add(location=location)
        obj = bpy.context.object
        obj.name = name
        return obj

    def select(self, *objects):
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[-1] if objects else None

    def install_plan(self, actions):
        context = editor_agent.scene_context(bpy.context)
        editor_agent._accept_plan(self.scene, {'summary': 'Test scene changes', 'actions': actions},
                                  context, editor_agent._snapshot(self.scene, context['selected']))

    def poll_model(self, timeout=4):
        deadline = time.monotonic() + timeout
        while self.settings.status == 'RUNNING' and time.monotonic() < deadline:
            result = editor_agent._poll_jobs()
            if result is None and bpy.app.timers.is_registered(editor_agent._poll_jobs):
                bpy.app.timers.unregister(editor_agent._poll_jobs)
            time.sleep(.01)
        self.assertNotEqual(self.settings.status, 'RUNNING', 'model worker did not finish')

    def quality(self):
        return (self.scene.render.engine, self.scene.render.resolution_percentage,
                self.scene.eevee.taa_samples, self.scene.eevee.taa_render_samples,
                self.scene.eevee.use_gtao, self.scene.eevee.use_ssr,
                self.scene.view_settings.view_transform)

    def test_local_operator_plans_then_applies_uzbek_creation_without_quality_change(self):
        quality = self.quality()
        self.settings.prompt = 'qizil kub qo‘sh'
        self.assertEqual(bpy.ops.blendengine.agent_plan(), {'FINISHED'})
        self.assertEqual(len(self.scene.objects), 0, 'planning must not mutate the scene')
        self.assertEqual(self.settings.status, 'READY')
        action = json.loads(self.settings.plan_json)['actions'][0]
        self.assertEqual(bpy.ops.blendengine.agent_apply(), {'FINISHED'})
        obj = self.scene.objects[action['name']]
        self.assertEqual(obj.type, 'MESH')
        self.assertEqual(tuple(obj.location), tuple(action['location']))
        self.assertAlmostEqual(obj.active_material.diffuse_color[0], .8)
        self.assertGreater(obj.active_material.diffuse_color[0], obj.active_material.diffuse_color[2])
        self.assertEqual(self.settings.plan_json, '')
        self.assertEqual(quality, self.quality())

    def test_plan_steps_can_target_the_object_they_create(self):
        self.install_plan([create_action(), {'tool': 'transform_object', 'object': 'Planned Cube',
                                            'location': [-2, 4, 1]},
                           {'tool': 'set_material', 'object': 'Planned Cube', 'color': [.1, .7, .2]}])
        bpy.ops.blendengine.agent_apply()
        obj = self.scene.objects['Planned Cube']
        self.assertEqual(tuple(obj.location), (-2, 4, 1))
        self.assertAlmostEqual(obj.active_material.diffuse_color[1], .7)
        self.assertEqual(len(self.scene.objects), 1)

    def test_selection_is_frozen_when_a_different_object_is_selected_before_apply(self):
        intended = self.cube('Original target')
        other = self.cube('Later selection', (5, 0, 0))
        self.select(intended)
        self.settings.prompt = 'move selected to 1 2 3'
        bpy.ops.blendengine.agent_plan()
        self.select(other)
        bpy.ops.blendengine.agent_apply()
        self.assertEqual(tuple(intended.location), (1, 2, 3))
        self.assertEqual(tuple(other.location), (5, 0, 0))

    def test_recreated_target_is_rejected_before_other_actions_mutate_scene(self):
        target = self.cube('Stable name')
        self.select(target)
        self.install_plan([create_action(), {'tool': 'transform_object', 'object': '@selected',
                                            'location': [4, 5, 6]}])
        snapshot = json.loads(self.settings.snapshot_json)
        original_pointer = target.as_pointer()
        bpy.data.objects.remove(target, do_unlink=True)
        # A surviving filler prevents a freed ID allocation being immediately reused.
        self.cube('Unrelated object')
        replacement = self.cube('Stable name', (9, 8, 7))
        self.assertNotEqual(original_pointer, replacement.as_pointer())
        with self.assertRaisesRegex(ValueError, 'changed after planning'):
            editor_agent.apply_plan(bpy.context, json.loads(self.settings.plan_json), snapshot)
        self.assertNotIn('Planned Cube', self.scene.objects)
        self.assertEqual(tuple(replacement.location), (9, 8, 7))

    def test_material_change_does_not_recolor_linked_duplicates(self):
        selected = self.cube('Selected')
        original_material = bpy.data.materials.new('Existing finish')
        original_material.diffuse_color = (.2, .3, .4, 1)
        selected.data.materials.append(original_material)
        linked = selected.copy()
        self.scene.collection.objects.link(linked)
        linked.name = 'Linked duplicate'
        original_mesh = linked.data
        self.select(selected)
        self.install_plan([{'tool': 'set_material', 'object': '@selected', 'color': [.8, .1, .2]}])
        bpy.ops.blendengine.agent_apply()
        self.assertIs(linked.data, original_mesh)
        self.assertIs(linked.active_material, original_material)
        self.assertIsNot(selected.data, linked.data)
        self.assertAlmostEqual(original_material.diffuse_color[0], .2)
        self.assertAlmostEqual(selected.active_material.diffuse_color[0], .8)

    def test_recolor_preserves_pbr_links_surface_parameters_and_face_slots(self):
        selected = self.cube('Textured target')
        originals = []
        for index in range(2):
            material = bpy.data.materials.new('Textured finish %d' % index)
            material.use_nodes = True
            shader = material.node_tree.nodes['Principled BSDF']
            shader.inputs['Metallic'].default_value = .73
            shader.inputs['Roughness'].default_value = .22
            grain = material.node_tree.nodes.new('ShaderNodeTexNoise')
            bump = material.node_tree.nodes.new('ShaderNodeBump')
            bump.inputs['Strength'].default_value = .18
            material.node_tree.links.new(grain.outputs['Color'], shader.inputs['Base Color'])
            material.node_tree.links.new(grain.outputs['Fac'], bump.inputs['Height'])
            material.node_tree.links.new(bump.outputs['Normal'], shader.inputs['Normal'])
            selected.data.materials.append(material)
            originals.append(material)
        for polygon in selected.data.polygons:
            polygon.material_index = polygon.index % 2
        linked = selected.copy()
        self.scene.collection.objects.link(linked)
        indices = tuple(p.material_index for p in linked.data.polygons)
        self.select(selected)
        self.install_plan([{'tool': 'set_material', 'object': '@selected', 'color': [.8, .1, .2]}])
        bpy.ops.blendengine.agent_apply()
        self.assertEqual(tuple(p.material_index for p in selected.data.polygons), indices)
        self.assertEqual(tuple(p.material_index for p in linked.data.polygons), indices)
        self.assertEqual(list(linked.data.materials), originals)
        self.assertEqual(len(selected.data.materials), 2)
        for changed, original in zip(selected.data.materials, originals):
            self.assertIsNot(changed, original)
            shader = changed.node_tree.nodes['Principled BSDF']
            self.assertAlmostEqual(shader.inputs['Metallic'].default_value, .73)
            self.assertAlmostEqual(shader.inputs['Roughness'].default_value, .22)
            bump = shader.inputs['Normal'].links[0].from_node
            self.assertEqual(bump.type, 'BUMP')
            self.assertAlmostEqual(bump.inputs['Strength'].default_value, .18)
            self.assertEqual(bump.inputs['Height'].links[0].from_node.type, 'TEX_NOISE')
            tint = shader.inputs['Base Color'].links[0].from_node
            self.assertEqual(tint.type, 'MIX_RGB')
            self.assertEqual(tint.blend_type, 'MULTIPLY')
            self.assertEqual(tint.inputs[1].links[0].from_node.type, 'TEX_NOISE')
            self.assertAlmostEqual(tint.inputs[2].default_value[0], .8)
            original_shader = original.node_tree.nodes['Principled BSDF']
            self.assertEqual(original_shader.inputs['Base Color'].links[0].from_node.type, 'TEX_NOISE')

    def test_npc_controller_recolor_targets_visible_human_and_rolls_back_that_mesh(self):
        player = ai_system.create_agent(bpy.context, name='Player prototype', behavior='IDLE', speed=0)
        player.blendengine_object.npc_behavior.enabled = False
        player.blendengine_object.player_controller.enabled = True
        player_actor = self.scene.objects[player['blendengine_agent_actor']]
        self.scene['story_actor'] = player_actor.name
        self.scene['story_rig'] = player['blendengine_agent_rig']
        scout = ai_system.create_agent(bpy.context, name='Visible scout', behavior='FOLLOW_PLAYER')
        scout_actor = self.scene.objects[scout['blendengine_agent_actor']]
        self.assertIs(scout_actor.data, player_actor.data)
        self.assertTrue(scout.hide_render)
        controller_data = scout.data
        original_player_materials = list(player_actor.data.materials)
        self.select(scout)
        self.install_plan([{'tool': 'set_material', 'object': '@selected', 'color': [.1, .3, .8]}])
        bpy.ops.blendengine.agent_apply()
        self.assertIs(scout.data, controller_data)
        self.assertIsNot(scout_actor.data, player_actor.data)
        self.assertEqual(list(player_actor.data.materials), original_player_materials)
        self.assertTrue(all(abs(mat.diffuse_color[2]-.8) < 1e-6 for mat in scout_actor.data.materials))
        before_mesh = scout_actor.data
        before_materials = list(before_mesh.materials)
        before_indices = tuple(p.material_index for p in before_mesh.polygons)
        before = {name: set(getattr(bpy.data, name)) for name in self.owned}
        self.install_plan([
            {'tool': 'set_material', 'object': '@selected', 'color': [.9, .2, .1]},
            {'tool': 'create_npc', 'name': 'Failure trigger', 'behavior': 'GUIDE',
             'location': [1, 2, .92], 'speed': 3},
        ])
        with mock.patch.object(editor_agent.ai_system, 'create_agent', side_effect=RuntimeError('fixture failure')):
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                editor_agent.apply_plan(bpy.context, json.loads(self.settings.plan_json),
                                        json.loads(self.settings.snapshot_json))
        self.assertIs(scout_actor.data, before_mesh)
        self.assertEqual(list(scout_actor.data.materials), before_materials)
        self.assertEqual(tuple(p.material_index for p in scout_actor.data.polygons), before_indices)
        self.assertEqual(list(player_actor.data.materials), original_player_materials)
        for name, collection in before.items():
            self.assertEqual(set(getattr(bpy.data, name)), collection, name + ' leaked after NPC rollback')

    def test_stale_plan_rejects_replacement_even_when_blender_reuses_id_memory(self):
        target = bpy.data.objects.new('Recycled target', None)
        self.scene.collection.objects.link(target)
        self.select(target)
        self.install_plan([{'tool': 'transform_object', 'object': '@selected', 'location': [7, 8, 9]}])
        plan = json.loads(self.settings.plan_json)
        snapshot = json.loads(self.settings.snapshot_json)
        bpy.data.objects.remove(target, do_unlink=True)
        replacement = bpy.data.objects.new('Recycled target', None)
        self.scene.collection.objects.link(replacement)
        replacement.location = (2, 3, 4)
        # Blender's allocator frequently returns the same as_pointer() address.
        # A plan identifies the original ID, not whichever object now occupies it.
        with self.assertRaisesRegex(ValueError, 'changed after planning|expired'):
            editor_agent.apply_plan(bpy.context, plan, snapshot)
        self.assertEqual(tuple(replacement.location), (2, 3, 4))

    def test_failed_batch_restores_transforms_materials_npc_roles_and_datablocks(self):
        obj = self.cube('Existing object', (3, 2, 1))
        material = bpy.data.materials.new('Original material')
        obj.data.materials.append(material)
        mesh = obj.data
        settings = obj.blendengine_object
        before_role = (settings.is_game_object, settings.object_tag, settings.active_component_index)
        before_npc = (settings.npc_behavior.enabled, settings.npc_behavior.behavior_template,
                      settings.npc_behavior.move_speed)
        self.select(obj)
        self.install_plan([
            {'tool': 'transform_object', 'object': '@selected', 'location': [8, 8, 8]},
            {'tool': 'set_material', 'object': '@selected', 'color': [.9, .1, .2]},
            {'tool': 'set_npc', 'object': '@selected', 'behavior': 'FOLLOW_PLAYER', 'speed': 4},
            create_action('Transient cube'),
            {'tool': 'create_npc', 'name': 'Failure trigger', 'behavior': 'GUIDE',
             'location': [1, 2, .92], 'speed': 3},
        ])
        before = {name: set(getattr(bpy.data, name)) for name in self.owned}
        with mock.patch.object(editor_agent.ai_system, 'create_agent', side_effect=RuntimeError('fixture failure')):
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                editor_agent.apply_plan(bpy.context, json.loads(self.settings.plan_json),
                                        json.loads(self.settings.snapshot_json))
        self.assertEqual(tuple(obj.location), (3, 2, 1))
        self.assertIs(obj.data, mesh)
        self.assertEqual(list(obj.data.materials), [material])
        self.assertEqual((settings.is_game_object, settings.object_tag, settings.active_component_index), before_role)
        self.assertEqual((settings.npc_behavior.enabled, settings.npc_behavior.behavior_template,
                          settings.npc_behavior.move_speed), before_npc)
        self.assertEqual(len(settings.components), 0)
        self.assertEqual(set(bpy.context.selected_objects), {obj})
        for name, collection in before.items():
            self.assertEqual(set(getattr(bpy.data, name)), collection, name + ' leaked after rollback')

    def test_rollback_preserves_face_materials_on_untouched_linked_meshes(self):
        obj = self.cube('Multi-material target')
        materials = [bpy.data.materials.new('Finish one'), bpy.data.materials.new('Finish two')]
        for material in materials:
            obj.data.materials.append(material)
        for polygon in obj.data.polygons:
            polygon.material_index = polygon.index % 2
        original_mesh = obj.data
        indices = tuple(p.material_index for p in original_mesh.polygons)
        linked = obj.copy()
        self.scene.collection.objects.link(linked)
        linked.name = 'Untouched linked object'
        self.select(obj)
        self.install_plan([
            {'tool': 'set_material', 'object': '@selected', 'color': [.8, .3, .2]},
            {'tool': 'create_npc', 'name': 'Failure trigger', 'behavior': 'FOLLOW_PLAYER',
             'location': [1, 2, .92], 'speed': 3},
        ])
        with mock.patch.object(editor_agent.ai_system, 'create_agent', side_effect=RuntimeError('fixture failure')):
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                editor_agent.apply_plan(bpy.context, json.loads(self.settings.plan_json),
                                        json.loads(self.settings.snapshot_json))
        self.assertIs(obj.data, original_mesh)
        self.assertIs(linked.data, original_mesh)
        self.assertEqual(list(original_mesh.materials), materials)
        self.assertEqual(tuple(p.material_index for p in original_mesh.polygons), indices)

    def test_real_model_request_returns_to_main_thread_and_never_persists_key(self):
        response = {'summary': 'Create a green object', 'actions': [create_action('Model cube')]}
        secret = 'fixture-only-api-key-not-a-real-credential'
        main_thread = threading.get_ident()
        accepted_threads = []
        original_accept = editor_agent._accept_plan

        def accept(*args, **kwargs):
            accepted_threads.append(threading.get_ident())
            return original_accept(*args, **kwargs)

        with model_server(response) as (endpoint, entered, requests), \
                mock.patch.dict(os.environ, {'BE_AGENT_TEST_KEY': secret}), \
                mock.patch.object(editor_agent, '_accept_plan', side_effect=accept):
            self.settings.mode = 'MODEL'
            self.settings.endpoint = endpoint
            self.settings.model = 'fixture-model'
            self.settings.key_env = 'BE_AGENT_TEST_KEY'
            self.settings.prompt = 'Make a green cube'
            bpy.ops.blendengine.agent_plan()
            self.assertEqual(self.settings.status, 'RUNNING')
            self.assertTrue(entered.wait(2))
            self.assertEqual(len(self.scene.objects), 0)
            self.poll_model()
            self.assertEqual(self.settings.status, 'READY', self.settings.reply)
            self.assertEqual(accepted_threads, [main_thread])
            self.assertEqual(requests[0]['path'], '/v1/chat/completions')
            self.assertEqual(requests[0]['body']['model'], 'fixture-model')
            self.assertEqual(requests[0]['authorization'], 'Bearer ' + secret)
            self.assertNotIn(secret, json.dumps(requests[0]['body']))
            bpy.ops.blendengine.agent_apply()
        self.assertIn('Model cube', self.scene.objects)
        self.assertNotIn(secret, json.dumps(export_system.serialize_game_data(self.scene)))
        self.assertNotIn(secret, self.settings.plan_json + self.settings.reply + self.settings.snapshot_json)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'agent-credential-regression.blend'
            bpy.ops.wm.save_as_mainfile(filepath=str(path), compress=False)
            self.assertNotIn(secret.encode(), path.read_bytes())

    def test_cancelled_model_result_cannot_change_scene_or_replace_newer_local_plan(self):
        release = threading.Event()
        response = {'summary': 'Late model result', 'actions': [create_action('Cancelled cube')]}
        with model_server(response, release=release) as (endpoint, entered, _requests):
            self.settings.mode, self.settings.endpoint = 'MODEL', endpoint
            bpy.ops.blendengine.agent_plan()
            self.assertTrue(entered.wait(2))
            bpy.ops.blendengine.agent_cancel()
            self.settings.mode, self.settings.prompt = 'LOCAL', 'yashil shar qo‘sh'
            bpy.ops.blendengine.agent_plan()
            newer_plan = self.settings.plan_json
            release.set()
            time.sleep(.1)
            editor_agent._poll_jobs()
            self.assertEqual(self.settings.plan_json, newer_plan)
            self.assertEqual(len(self.scene.objects), 0)
            bpy.ops.blendengine.agent_apply()
        self.assertNotIn('Cancelled cube', self.scene.objects)
        self.assertEqual(len(self.scene.objects), 1)

    def test_renaming_scene_during_inference_keeps_its_result_bound_to_the_same_scene(self):
        release = threading.Event()
        response = {'summary': 'Create after scene rename', 'actions': [create_action('Renamed scene cube')]}
        with model_server(response, release=release) as (endpoint, entered, _requests):
            self.settings.mode, self.settings.endpoint = 'MODEL', endpoint
            bpy.ops.blendengine.agent_plan()
            self.assertTrue(entered.wait(2))
            self.scene.name = 'Scene renamed while waiting'
            release.set()
            self.poll_model()
            self.assertEqual(self.settings.status, 'READY', self.settings.reply)
            self.assertEqual(len(self.scene.objects), 0)
            bpy.ops.blendengine.agent_apply()
        self.assertIn('Renamed scene cube', self.scene.objects)
        self.assertNotIn('Renamed scene cube', self.previous_scene.objects)

    def test_untrusted_model_tool_is_rejected_without_mutation(self):
        response = {'summary': 'Untrusted provider', 'actions': [{'tool': 'execute_python', 'code': 'bad'}]}
        with model_server(response) as (endpoint, entered, _requests):
            self.settings.mode, self.settings.endpoint = 'MODEL', endpoint
            bpy.ops.blendengine.agent_plan()
            self.assertTrue(entered.wait(2))
            self.poll_model()
        self.assertEqual(self.settings.status, 'ERROR')
        self.assertFalse(self.settings.plan_json)
        self.assertEqual(len(self.scene.objects), 0)


result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EditorAgentTests))
blendengine.unregister()
if not result.wasSuccessful():
    raise SystemExit(1)
