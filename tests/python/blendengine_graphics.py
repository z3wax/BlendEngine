# SPDX-License-Identifier: GPL-2.0-or-later
"""Blender integration regressions for BlendEngine's actual render settings.

Run from the repository root with Blender 3.6 or 4.3::

    blender --background --factory-startup --python-exit-code 1 \
        --python tests/python/blendengine_graphics.py

These tests exercise registered operators and RNA rather than rendering an image;
the showcase script provides the separate visual smoke test.
"""

from pathlib import Path
import sys
import tempfile
import unittest

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))

import blendengine
from blendengine import graphics, optimization, templates


def scalar_rna_values(owner):
    """Record the RNA settings without following datablocks or pointer cycles."""
    values = {}
    for prop in owner.bl_rna.properties:
        if prop.is_readonly:
            continue
        if prop.type not in {'BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'}:
            continue
        value = getattr(owner, prop.identifier)
        values[prop.identifier] = tuple(value) if getattr(prop, "is_array", False) else value
    return values


def rendering_snapshot(scene):
    values = {
        "engine": scene.render.engine,
        "resolution_percentage": scene.render.resolution_percentage,
        "eevee": scalar_rna_values(scene.eevee),
        "view": scalar_rna_values(scene.view_settings),
    }
    if hasattr(scene.eevee, "ray_tracing_options"):
        values["ray_tracing"] = scalar_rna_values(scene.eevee.ray_tracing_options)
    return values


def reflections_enabled(scene):
    eevee = scene.eevee
    if scene.render.engine == 'BLENDER_EEVEE_NEXT':
        # Next also enables the tracing module for AO-only profiles.
        return eevee.use_raytracing and eevee.ray_tracing_options.trace_max_roughness > 0.0
    return eevee.use_ssr


def shadow_resolution_or_samples(scene):
    eevee = scene.eevee
    if hasattr(eevee, "shadow_ray_count"):
        return eevee.shadow_ray_count
    return int(eevee.shadow_cube_size)


class GraphicsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blendengine.register()

    @classmethod
    def tearDownClass(cls):
        blendengine.unregister()

    def setUp(self):
        self.previous_scene_name = bpy.context.scene.name
        self.scene = bpy.data.scenes.new("BlendEngine Graphics Regression")
        bpy.context.window.scene = self.scene
        graphics.configure_realtime(self.scene)

    def tearDown(self):
        # Look up fresh datablocks: a save/reload test invalidates old references.
        current = bpy.context.scene
        previous = bpy.data.scenes.get(self.previous_scene_name)
        if previous is None or previous == current:
            previous = bpy.data.scenes.new("Scene")
        bpy.context.window.scene = previous
        bpy.data.scenes.remove(current)

    def test_realtime_configuration_uses_the_stable_backend(self):
        if bpy.app.version < (4, 2, 0):
            self.assertEqual(self.scene.render.engine, 'BLENDER_EEVEE')
        else:
            self.assertEqual(self.scene.render.engine, 'BLENDER_EEVEE_NEXT')

    def test_balanced_ambient_occlusion_does_not_enable_glossy_reflections(self):
        optimization.apply_preset(self.scene, 'CINEMATIC')
        optimization.apply_preset(self.scene, 'BALANCED')

        self.assertTrue(self.scene.blendengine_quality_profile.ambient_occlusion)
        self.assertTrue(self.scene.eevee.use_gtao)
        self.assertFalse(reflections_enabled(self.scene))

    def test_cinematic_and_high_change_real_renderer_settings(self):
        scene = self.scene
        optimization.apply_preset(scene, 'LOW')
        low_samples = scene.eevee.taa_render_samples
        low_shadows = shadow_resolution_or_samples(scene)
        self.assertFalse(reflections_enabled(scene))

        optimization.apply_preset(scene, 'HIGH')
        high_samples = scene.eevee.taa_render_samples
        self.assertTrue(reflections_enabled(scene))
        self.assertFalse(scene.blendengine_optimization.one_gb_ram_mode)
        self.assertGreater(high_samples, low_samples)
        self.assertGreater(shadow_resolution_or_samples(scene), low_shadows)

        optimization.apply_preset(scene, 'CINEMATIC')
        self.assertTrue(reflections_enabled(scene))
        self.assertFalse(scene.blendengine_optimization.one_gb_ram_mode)
        self.assertGreaterEqual(scene.eevee.taa_render_samples, high_samples)
        self.assertGreater(scene.eevee.taa_samples, 1)
        self.assertEqual(scene.render.resolution_percentage, 100)

    def test_lowering_quality_disables_expensive_effects(self):
        scene = self.scene
        optimization.apply_preset(scene, 'CINEMATIC')
        expensive_samples = scene.eevee.taa_render_samples
        optimization.apply_preset(scene, 'ULTRA_LOW')

        self.assertFalse(reflections_enabled(scene))
        self.assertLess(scene.eevee.taa_render_samples, expensive_samples)
        self.assertLess(scene.render.resolution_percentage, 100)
        self.assertFalse(scene.eevee.use_gtao)
        if hasattr(scene.eevee, "use_bloom"):
            self.assertFalse(scene.eevee.use_bloom)
        if hasattr(scene.eevee, "use_motion_blur"):
            self.assertFalse(scene.eevee.use_motion_blur)
        if hasattr(scene.render, "use_motion_blur"):
            self.assertFalse(scene.render.use_motion_blur)

    def test_repeated_presets_are_idempotent(self):
        scene = self.scene
        optimization.apply_preset(scene, 'CINEMATIC')
        first = rendering_snapshot(scene)
        optimization.apply_preset(scene, 'CINEMATIC')
        self.assertEqual(rendering_snapshot(scene), first)

        optimization.apply_preset(scene, 'LOW')
        first = rendering_snapshot(scene)
        optimization.apply_preset(scene, 'LOW')
        self.assertEqual(rendering_snapshot(scene), first)

    def test_custom_operator_applies_authored_values_without_resetting_them(self):
        scene = self.scene
        optimization.apply_preset(scene, 'HIGH')
        profile = scene.blendengine_quality_profile
        profile.name = "Authored graphics"
        profile.resolution_scale = 0.75
        profile.target_fps = 47
        profile.reflections = True
        profile.reflection_quality = 'HIGH'
        profile.shadow_quality = 'HIGH'
        profile.anti_aliasing = 'TAA_4X'
        profile.ambient_occlusion = True
        profile.bloom = False
        scene.blendengine_performance_budget.max_triangles_visible = 123456

        result = bpy.ops.blendengine.apply_optimization_preset(preset='CUSTOM')

        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(profile.preset, 'CUSTOM')
        self.assertEqual(profile.name, "Authored graphics")
        self.assertEqual(profile.target_fps, 47)
        self.assertEqual(profile.resolution_scale, 0.75)
        self.assertEqual(scene.blendengine_performance_budget.max_triangles_visible, 123456)
        self.assertEqual(scene.render.resolution_percentage, 75)
        self.assertTrue(reflections_enabled(scene))
        self.assertGreater(scene.eevee.taa_samples, 1)
        if hasattr(scene.eevee, "use_bloom"):
            self.assertFalse(scene.eevee.use_bloom)

    @unittest.skipIf(bpy.app.version >= (4, 0, 0), "The starter generator targets the source Blender 3.6 API")
    def test_desktop_new_game_keeps_high_graphics_and_shadow_casting_lights(self):
        result = bpy.ops.blendengine.easy_create_game(
            template='THREE_D_ADVENTURE', target_platform='WINDOWS',
        )
        self.assertEqual(result, {'FINISHED'})
        scene = self.scene
        self.assertIsNotNone(scene.camera)
        self.assertTrue(any(obj.blendengine_object.is_game_object for obj in scene.objects))

        for platform in ('WINDOWS', 'LINUX', 'MACOS'):
            with self.subTest(platform=platform):
                optimization.platform_defaults(scene, platform)
                self.assertEqual(scene.blendengine_quality_profile.preset, 'HIGH')
                self.assertFalse(scene.blendengine_optimization.one_gb_ram_mode)
                self.assertTrue(reflections_enabled(scene))
                self.assertTrue(any(obj.type == 'LIGHT' and obj.data.use_shadow for obj in scene.objects))

    def test_procedural_starter_material_has_relief_without_duplicate_nodes(self):
        material = bpy.data.materials.new("Starter Surface Regression")
        material.use_nodes = True
        shader = material.node_tree.nodes['Principled BSDF']
        arguments = (material, shader, (0.3, 0.35, 0.4, 1.0), 0.8, 7.0)
        templates._surface_detail(*arguments)
        nodes_before = len(material.node_tree.nodes)
        links_before = len(material.node_tree.links)
        self.assertTrue(shader.inputs['Base Color'].is_linked)
        self.assertTrue(shader.inputs['Roughness'].is_linked)
        self.assertTrue(shader.inputs['Normal'].is_linked)

        templates._surface_detail(*arguments)

        self.assertEqual(len(material.node_tree.nodes), nodes_before)
        self.assertEqual(len(material.node_tree.links), links_before)

    def test_preset_preserves_authored_scene_and_compositor(self):
        scene = self.scene
        scene.render.resolution_x = 1072
        scene.render.resolution_y = 608
        scene.render.fps = 24
        scene.view_settings.exposure = 0.65
        scene.view_settings.gamma = 1.1
        scene.use_nodes = True
        compositor = scene.node_tree
        sentinel = compositor.nodes.new('CompositorNodeValue')
        sentinel.name = "Artist-authored value"
        sentinel.outputs[0].default_value = 0.314
        nodes = tuple((node.name, node.bl_idname) for node in compositor.nodes)
        links = tuple((link.from_node.name, link.to_node.name) for link in compositor.links)

        world = bpy.data.worlds.new("Authored World")
        world.use_nodes = True
        scene.world = world
        world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.42
        material = bpy.data.materials.new("Authored PBR")
        material.use_nodes = True
        material.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.37
        camera = bpy.data.objects.new("Authored Camera", bpy.data.cameras.new("Authored Camera"))
        scene.collection.objects.link(camera)
        camera.data.dof.use_dof = True
        camera.data.dof.aperture_fstop = 5.6
        scene.camera = camera

        optimization.apply_preset(scene, 'CINEMATIC')

        self.assertEqual(scene.world, world)
        self.assertAlmostEqual(world.node_tree.nodes['Background'].inputs['Strength'].default_value, 0.42)
        self.assertAlmostEqual(material.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value, 0.37)
        self.assertEqual(scene.camera, camera)
        self.assertAlmostEqual(camera.data.dof.aperture_fstop, 5.6, places=6)
        self.assertEqual(scene.node_tree, compositor)
        self.assertEqual(tuple((node.name, node.bl_idname) for node in compositor.nodes), nodes)
        self.assertEqual(tuple((link.from_node.name, link.to_node.name) for link in compositor.links), links)
        self.assertAlmostEqual(sentinel.outputs[0].default_value, 0.314)
        self.assertEqual((scene.render.resolution_x, scene.render.resolution_y, scene.render.fps), (1072, 608, 24))
        self.assertAlmostEqual(scene.view_settings.exposure, 0.65)
        self.assertAlmostEqual(scene.view_settings.gamma, 1.1)

    def test_cycles_settings_are_left_intact(self):
        scene = self.scene
        try:
            scene.render.engine = 'CYCLES'
        except TypeError:
            self.skipTest("This Blender build does not include Cycles")
        scene.render.resolution_percentage = 87
        scene.cycles.samples = 11
        before = rendering_snapshot(scene)

        optimization.apply_preset(scene, 'CINEMATIC')

        self.assertEqual(rendering_snapshot(scene), before)
        self.assertEqual(scene.cycles.samples, 11)
        self.assertEqual(scene.blendengine_quality_profile.preset, 'CINEMATIC')

    def test_workbench_is_not_silently_replaced(self):
        scene = self.scene
        scene.render.engine = 'BLENDER_WORKBENCH'
        before = rendering_snapshot(scene)

        optimization.apply_preset(scene, 'HIGH')

        self.assertEqual(rendering_snapshot(scene), before)

    def test_z_render_settings_survive_saving_and_reopening(self):
        scene = self.scene
        optimization.apply_preset(scene, 'CINEMATIC')
        scene["graphics_regression_marker"] = "saved"
        expected = rendering_snapshot(scene)

        with tempfile.TemporaryDirectory(prefix="blendengine-graphics-") as directory:
            filepath = str(Path(directory) / "graphics.blend")
            bpy.ops.wm.save_as_mainfile(filepath=filepath, check_existing=False)
            bpy.ops.wm.open_mainfile(filepath=filepath)
            restored = bpy.context.scene
            self.assertEqual(restored["graphics_regression_marker"], "saved")
            self.assertEqual(restored.blendengine_quality_profile.preset, 'CINEMATIC')
            self.assertEqual(rendering_snapshot(restored), expected)


if __name__ == "__main__":
    print("BlendEngine graphics integration on Blender", bpy.app.version_string)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GraphicsIntegrationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError("BlendEngine graphics integration tests failed")
