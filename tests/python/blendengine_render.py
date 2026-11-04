# SPDX-License-Identifier: GPL-2.0-or-later
"""Regression checks for value-preserving render/depsgraph synchronization."""
from pathlib import Path
import sys
import unittest
import math
import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/addons_core'))
import blendengine
blendengine.register()
from blendengine import components, graphics, render_sync, runtime


class RenderSyncTests(unittest.TestCase):
    def setUp(self):
        self.old=bpy.context.window.scene
        self.scene=bpy.data.scenes.new('render sync regression')
        bpy.context.window.scene=self.scene
        graphics.configure_realtime(self.scene)
        mesh=bpy.data.meshes.new('controller mesh')
        mesh.from_pydata([(-.2,-.2,-.9),(.2,.2,.9)],[],[])
        self.player=bpy.data.objects.new('Player',mesh)
        self.scene.collection.objects.link(self.player)
        self.player.location.z=.9
        components.add_player_controller(self.player)
        camera=bpy.data.objects.new('Camera',bpy.data.cameras.new('Camera'))
        self.scene.collection.objects.link(camera)
        camera.location=(0,-5,3)
        self.scene.camera=camera
        self.session=runtime.GameSession(bpy.context)

    def tearDown(self):
        bpy.context.window.scene=self.old
        bpy.data.scenes.remove(self.scene)

    def test_equal_values_do_not_submit_rna_writes(self):
        self.assertFalse(render_sync.vector(self.player,'location',self.player.location.copy()))
        self.assertFalse(render_sync.scalar(self.player.location,'z',self.player.location.z))
        self.assertTrue(render_sync.scalar(self.player.location,'z',1.5))
        self.assertEqual(self.player.location.z,1.5)
        self.player.rotation_euler.z=math.pi
        self.assertFalse(render_sync.scalar(self.player.rotation_euler,'z',math.pi))

    def test_idle_camera_and_player_do_not_dirty_render_objects(self):
        for _ in range(3):
            self.session._update_player(1/60)
            self.session._update_camera()
            bpy.context.view_layer.update()
        changed=[]
        def observed(_scene,graph):
            changed.extend(u.id.name for u in graph.updates if isinstance(u.id,bpy.types.Object))
        bpy.app.handlers.depsgraph_update_post.append(observed)
        try:
            for _ in range(8):
                self.session._update_player(1/60)
                self.session._update_camera()
                bpy.context.view_layer.update()
        finally:
            bpy.app.handlers.depsgraph_update_post.remove(observed)
        self.assertEqual(changed,[])

    def test_real_changes_are_not_dropped_and_quality_is_untouched(self):
        from blendengine import input_system
        input_system.ensure_defaults(self.scene)
        before=(self.scene.render.engine,self.scene.eevee.taa_samples,
                self.scene.eevee.taa_render_samples,self.scene.render.resolution_percentage,
                self.scene.view_settings.view_transform)
        self.session.input_state={'W'}
        self.session._update_player(.25)
        self.session._update_camera()
        self.assertGreater(self.player.location.y,0)
        self.assertGreater(self.scene.camera.location.y,-5)
        self.assertEqual(before,(self.scene.render.engine,self.scene.eevee.taa_samples,
                                self.scene.eevee.taa_render_samples,self.scene.render.resolution_percentage,
                                self.scene.view_settings.view_transform))


suite=unittest.defaultTestLoader.loadTestsFromTestCase(RenderSyncTests)
result=unittest.TextTestRunner(verbosity=2).run(suite)
blendengine.unregister()
if not result.wasSuccessful():
    raise SystemExit(1)
