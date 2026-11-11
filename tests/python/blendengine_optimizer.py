# SPDX-License-Identifier: GPL-2.0-or-later
"""Blender integration tests for the Smart Optimizer, runtime culling and cinematic look.

Run from the repository root with Blender 4.3 (or its ``bpy`` module)::

    blender --background --factory-startup --python-exit-code 1 \
        --python tests/python/blendengine_optimizer.py

The tests build small scenes through the real ``bpy`` API. They check what the
optimizer removes and, just as importantly, what it must leave alone. Picture
equality is measured separately by ``tools/blendengine/optimizer_benchmark.py``.
"""

from pathlib import Path
import json
import math
import sys
import tempfile
import unittest

import bpy
import bmesh
import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))

import blendengine
from blendengine import cinematic, components, runtime, runtime_optimizer, smart_optimizer, utils, visibility


def triangles(obj):
    return sum(len(polygon.vertices) - 2 for polygon in obj.data.polygons)


class OptimizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blendengine.register()

    @classmethod
    def tearDownClass(cls):
        blendengine.unregister()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.scene.blendengine_project.resolution_x = 1280
        self.scene.blendengine_project.resolution_y = 720
        self.scene.render.resolution_x = 1280
        self.scene.render.resolution_y = 720
        self.settings = self.scene.blendengine_smart
        self.settings.build_lods = False

    # -- scene construction -------------------------------------------------

    def box(self, name, size, location, cuts=0, material=None):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
        if cuts:
            bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.scale = size
        obj.location = location
        self.scene.collection.objects.link(obj)
        if material is not None:
            mesh.materials.append(material)
        return obj

    def panel(self, name, size, location, material):
        """Upright square facing the play area, showing its whole image once."""
        half = size * 0.5
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(-half, 0, -half), (half, 0, -half), (half, 0, half), (-half, 0, half)], [], [(0, 1, 2, 3)])
        layer = mesh.uv_layers.new()
        for loop, uv in zip(layer.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
            loop.uv = uv
        mesh.materials.append(material)
        obj = bpy.data.objects.new(name, mesh)
        obj.location = location
        self.scene.collection.objects.link(obj)
        return obj

    def sphere(self, name, radius, location, subdivisions=4):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=radius)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.location = location
        self.scene.collection.objects.link(obj)
        return obj

    def textured(self, name, size, scale=None):
        image = bpy.data.images.new(name, size, size)
        pixels = np.random.default_rng(len(name)).random(size * size * 4, dtype=np.float32)
        pixels[3::4] = 1.0
        image.pixels.foreach_set(pixels)
        image.pack()
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        links.new(texture.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
        if scale is not None:
            coords = nodes.new("ShaderNodeTexCoord")
            mapping = nodes.new("ShaderNodeMapping")
            mapping.inputs["Scale"].default_value = (scale, scale, 1.0)
            links.new(coords.outputs["UV"], mapping.inputs["Vector"])
            links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
        return material

    def player_scene(self, first_person=True):
        """A 40 m floor with a player standing in the middle and a sun."""
        ground = self.box("Ground", (40, 40, 0.2), (0, 0, -0.1))
        ground.blendengine_object.object_tag = "Ground"
        player = self.box("Player", (0.6, 0.6, 1.8), (0, 0, 0.9))
        camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        self.scene.collection.objects.link(camera)
        camera.location = (0, 0, 1.62)
        camera.rotation_euler = (math.radians(90), 0, 0)
        self.scene.camera = camera
        components.add_player_controller(player, camera=camera)
        if first_person:
            player.blendengine_object.player_controller.controller_type = "FIRST_PERSON"
        sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
        sun.rotation_euler = (0.6, 0.2, 0.0)
        self.scene.collection.objects.link(sun)
        bpy.context.view_layer.update()
        return ground, player, camera

    def optimize(self):
        bpy.context.view_layer.update()
        return smart_optimizer.optimize(bpy.context)

    def step(self, report, identifier):
        return next(step for step in report["steps"] if step["id"] == identifier)

    # -- materials and meshes -----------------------------------------------

    def test_identical_materials_merge_and_unused_slots_go(self):
        self.player_scene()
        first = self.textured("Brick", 64)
        second = first.copy()
        different = first.copy()
        different.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.11
        unused = bpy.data.materials.new("Unused")
        a = self.box("A", (1, 1, 1), (3, 0, 0.5), material=first)
        b = self.box("B", (1, 1, 2), (6, 0, 1.0), material=second)
        c = self.box("C", (1, 2, 1), (9, 0, 0.5), material=different)
        a.data.materials.append(unused)

        report = self.optimize()

        self.assertEqual(a.material_slots[0].material, b.material_slots[0].material)
        self.assertNotEqual(a.material_slots[0].material, c.material_slots[0].material)
        self.assertEqual(len(a.material_slots), 1)
        step = self.step(report, "materials")
        self.assertEqual((step["merged"], step["slots_removed"]), (1, 1))
        self.assertLess(report["after"]["draw_calls"], report["before"]["draw_calls"])

    def test_slot_cleanup_keeps_each_face_on_its_material(self):
        self.player_scene()
        red, blue = bpy.data.materials.new("Red"), bpy.data.materials.new("Blue")
        red.diffuse_color, blue.diffuse_color = (1, 0, 0, 1), (0, 0, 1, 1)
        obj = self.box("Mixed", (1, 1, 1), (3, 0, 0.5))
        for material in (bpy.data.materials.new("Spare"), red, bpy.data.materials.new("Spare2"), blue):
            obj.data.materials.append(material)
        for polygon in obj.data.polygons:
            polygon.material_index = 1 if polygon.index % 2 else 3
        expected = [obj.data.materials[polygon.material_index].name for polygon in obj.data.polygons]

        smart_optimizer.clean_materials(self.scene)

        self.assertEqual([material.name for material in obj.data.materials], ["Red", "Blue"])
        actual = [obj.data.materials[polygon.material_index].name for polygon in obj.data.polygons]
        self.assertEqual(actual, expected)

    def test_identical_meshes_are_shared_but_different_ones_are_not(self):
        self.player_scene()
        crates = [self.box("Crate%d" % i, (1, 1, 1), (3 + i * 2, 5, 0.5), cuts=2) for i in range(4)]
        odd = self.box("Odd", (1, 1, 1), (3, 8, 0.5), cuts=2)
        odd.data.vertices[0].co.x += 0.25

        step = smart_optimizer.share_meshes(self.scene)

        self.assertEqual(len({crate.data.name for crate in crates}), 1)
        self.assertNotEqual(odd.data.name, crates[0].data.name)
        self.assertEqual(step["count"], 3)
        smart_optimizer.restore(self.scene)
        self.assertEqual(len({crate.data.name for crate in crates}), 4)

    # -- hidden geometry ----------------------------------------------------

    def test_faces_pressed_against_the_ground_are_removed_and_visible_ones_stay(self):
        self.player_scene()
        crate = self.box("Crate", (2, 2, 2), (5, 0, 1.0), cuts=7)
        before = triangles(crate)

        report = self.optimize()

        self.assertLess(triangles(crate), before)
        matrix = crate.matrix_world
        normals = [(matrix.to_3x3() @ polygon.normal).normalized() for polygon in crate.data.polygons]
        heights = [(matrix @ polygon.center).z for polygon in crate.data.polygons]
        # All four sides and the top are intact: 5 sides of 8x8 quads.
        self.assertEqual(sum(1 for normal in normals if normal.z > -0.5), 5 * 64)
        # What is left of the bottom is only the safety ring next to the visible sides.
        bottom = [height for normal, height in zip(normals, heights) if normal.z < -0.5]
        self.assertEqual(len(bottom), 64 - 36)
        self.assertGreater(self.step(report, "faces")["saved_triangles"], 0)

        restored = smart_optimizer.restore(self.scene)
        self.assertEqual(triangles(crate), before)
        self.assertEqual(restored["meshes"], 1)

    def test_enclosed_object_is_skipped_and_can_be_restored(self):
        self.player_scene()
        self.box("Vault", (4, 4, 4), (8, 0, 2.0))
        hidden = self.sphere("Treasure", 0.5, (8, 0, 2.0))
        seen = self.sphere("Statue", 0.5, (0, 8, 0.5))

        report = self.optimize()

        self.assertTrue(hidden.hide_render)
        self.assertFalse(seen.hide_render)
        self.assertEqual(self.step(report, "objects")["count"], 1)
        smart_optimizer.restore(self.scene)
        self.assertFalse(hidden.hide_render)
        self.assertFalse(hidden.hide_viewport)

    def test_surface_seen_only_by_a_light_keeps_casting_its_shadow(self):
        """A roof slab above eye level is never seen from below its top, but the sun sees it."""
        self.player_scene()
        self.scene.blendengine_smart.safety_rings = 0
        roof = self.box("Roof", (6, 6, 0.3), (0, 10, 5.0), cuts=3)

        self.optimize()

        tops = [polygon for polygon in roof.data.polygons if polygon.normal.z > 0.5]
        self.assertEqual(len(tops), 16)

    def test_moving_and_gameplay_objects_are_never_reduced(self):
        _ground, player, _camera = self.player_scene()
        self.box("Vault", (4, 4, 4), (8, 0, 2.0))
        enemy = self.sphere("Enemy", 0.5, (8, 0, 2.0))
        components.add_npc_behavior(enemy, template="PATROL")
        animated = self.box("Lift", (2, 2, 2), (-8, 0, 1.0), cuts=5)
        animated.keyframe_insert("location", frame=1)
        counts = triangles(enemy), triangles(animated), triangles(player)

        self.optimize()

        self.assertFalse(enemy.hide_render)
        self.assertEqual((triangles(enemy), triangles(animated), triangles(player)), counts)

    def test_transparent_walls_do_not_hide_what_is_behind_them(self):
        self.player_scene()
        glass = bpy.data.materials.new("Glass")
        glass.use_nodes = True
        glass.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 0.3
        self.box("Case", (4, 4, 4), (8, 0, 2.0), material=glass)
        exhibit = self.sphere("Exhibit", 0.5, (8, 0, 2.0))

        self.optimize()

        self.assertFalse(exhibit.hide_render)
        self.assertFalse(visibility.material_is_opaque(glass))

    def test_camera_path_mode_only_keeps_what_the_shot_frames(self):
        camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        self.scene.collection.objects.link(camera)
        camera.location = (0, -10, 1)
        camera.rotation_euler = (math.radians(90), 0, 0)
        self.scene.camera = camera
        self.scene.frame_start, self.scene.frame_end = 1, 3
        self.box("Floor", (30, 60, 0.2), (0, 0, -0.1))
        framed = self.sphere("Framed", 1.0, (0, 0, 1.0))
        behind = self.sphere("BehindCamera", 1.0, (0, -20, 1.0))
        before = triangles(framed)

        report = self.optimize()

        self.assertEqual(report["mode"], "CAMERA_PATH")
        self.assertTrue(behind.hide_render)
        self.assertFalse(framed.hide_render)
        # The far side of the sphere faces away from the only camera.
        self.assertLess(triangles(framed), before)
        self.assertGreater(triangles(framed), before * 0.4)

    # -- textures -----------------------------------------------------------

    def test_far_texture_shrinks_and_a_touchable_one_keeps_every_texel(self):
        self.player_scene()
        self.settings.vantage_spacing = 4.0
        # The floor ends at y = 20, so the billboards are never closer than 40 m.
        far = self.panel("Billboard", 8.0, (0, 60, 6.0), self.textured("Far", 2048))
        near = self.panel("Poster", 2.0, (4, 4, 1.0), self.textured("Near", 2048))
        tiled = self.panel("Tiled", 8.0, (12, 60, 6.0), self.textured("FarTiled", 2048, scale=8.0))
        stretched = self.panel("Stretched", 8.0, (-12, 60, 6.0), self.textured("FarStretched", 2048))
        stretched.scale = (1.0, 1.0, 0.125)
        stretched_image = stretched.material_slots[0].material.node_tree.nodes["Image Texture"].image
        far_image = far.material_slots[0].material.node_tree.nodes["Image Texture"].image
        near_image = near.material_slots[0].material.node_tree.nodes["Image Texture"].image
        tiled_image = tiled.material_slots[0].material.node_tree.nodes["Image Texture"].image

        report = self.optimize()
        analysis_focal, edge = visibility.camera_optics(self.scene.camera, 1280, 720)

        self.assertEqual(tuple(near_image.size), (2048, 2048))
        self.assertEqual(tuple(far_image.size), (512, 512))
        # Eight repeats put eight times the texels on every meter, so each repeat needs fewer of them.
        self.assertLess(tiled_image.size[0], far_image.size[0])
        # Squashing the panel must not cost the long axis its sharpness.
        self.assertEqual(stretched_image.size[0], far_image.size[0])
        # Still at least one texel per pixel where the camera can get closest (40 m from the ground edge).
        texels_per_meter = far_image.size[0] / 8.0
        pixels_per_meter = analysis_focal * edge / 40.0
        self.assertGreaterEqual(texels_per_meter, pixels_per_meter)
        self.assertGreater(self.step(report, "textures")["saved_texture_mb"], 10.0)

        restored = smart_optimizer.restore(self.scene)
        far_image = far.material_slots[0].material.node_tree.nodes["Image Texture"].image
        self.assertEqual(tuple(far_image.size), (2048, 2048))
        self.assertEqual(restored["images"], 3)

    def test_resized_texture_survives_saving_and_original_can_be_discarded(self):
        self.player_scene()
        far = self.panel("Billboard", 8.0, (0, 80, 6.0), self.textured("Far", 1024))
        self.optimize()
        image = far.material_slots[0].material.node_tree.nodes["Image Texture"].image
        size = tuple(image.size)
        self.assertLess(size[0], 1024)
        self.assertEqual(smart_optimizer.purge_backups(self.scene), 1)

        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "optimized.blend")
            bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path)
            reopened = bpy.data.objects["Billboard"].material_slots[0].material.node_tree.nodes["Image Texture"].image
            self.assertEqual(tuple(reopened.size), size)
            self.assertFalse(any(item.name.startswith("BE_ORIG_") for item in bpy.data.images))

    def test_image_files_are_shared_resized_in_the_blend_only_and_reloaded_on_restore(self):
        self.player_scene()
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "poster.png")
            source = self.textured("Source", 1024).node_tree.nodes["Image Texture"].image
            source.filepath_raw = path
            source.file_format = "PNG"
            source.save()
            size_on_disk = Path(path).stat().st_size
            bpy.data.images.remove(source)

            materials = []
            for name in ("First", "Second"):
                material = bpy.data.materials.new(name)
                material.use_nodes = True
                texture = material.node_tree.nodes.new("ShaderNodeTexImage")
                texture.image = bpy.data.images.load(path, check_existing=False)
                material.node_tree.links.new(texture.outputs["Color"],
                                             material.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
                materials.append(material)
            materials[1].node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.2
            self.panel("BillboardA", 8.0, (0, 80, 6.0), materials[0])
            self.panel("BillboardB", 8.0, (12, 80, 6.0), materials[1])

            report = self.optimize()

            images = [material.node_tree.nodes["Image Texture"].image for material in materials]
            self.assertEqual(images[0], images[1], "both materials load the same file")
            self.assertEqual(self.step(report, "images")["count"], 1)
            self.assertLess(images[0].size[0], 1024)
            self.assertEqual(Path(path).stat().st_size, size_on_disk, "the source file is never rewritten")

            smart_optimizer.restore(self.scene)
            restored = materials[0].node_tree.nodes["Image Texture"].image
            self.assertEqual(tuple(restored.size), (1024, 1024))
            self.assertIsNone(restored.packed_file)

    def test_textures_with_unmeasured_users_are_left_alone(self):
        self.player_scene()
        material = self.textured("Sky", 1024)
        self.box("Billboard", (8, 0.2, 8), (0, 80, 6.0), material=material)
        image = material.node_tree.nodes["Image Texture"].image
        world = bpy.data.worlds.new("World")
        world.use_nodes = True
        environment = world.node_tree.nodes.new("ShaderNodeTexEnvironment")
        environment.image = image
        self.scene.world = world
        procedural = self.textured("Projected", 1024)
        nodes, links = procedural.node_tree.nodes, procedural.node_tree.links
        coords = nodes.new("ShaderNodeTexCoord")
        links.new(coords.outputs["Object"], nodes["Image Texture"].inputs["Vector"])
        self.box("Billboard2", (8, 0.2, 8), (12, 80, 6.0), material=procedural)

        self.optimize()

        self.assertEqual(tuple(image.size), (1024, 1024))
        self.assertEqual(tuple(nodes["Image Texture"].image.size), (1024, 1024))

    def test_lossy_mode_only_engages_when_the_budget_is_exceeded(self):
        self.player_scene()
        near = self.panel("Poster", 0.5, (4, 4, 1.0), self.textured("Near", 2048))
        image = near.material_slots[0].material.node_tree.nodes["Image Texture"].image
        budget = self.scene.blendengine_performance_budget
        budget.max_texture_memory_mb = 4

        report = self.optimize()
        self.assertEqual(tuple(image.size), (2048, 2048))
        self.assertTrue(any("over the 4 MB budget" in item for item in report["decisions"]))

        self.settings.allow_lossy = True
        report = self.optimize()
        self.assertLess(image.size[0], 2048)
        self.assertFalse(report["steps"][-1]["lossless"])

    # -- runtime ------------------------------------------------------------

    def test_baked_visible_sets_cull_occluded_objects_and_restore_afterwards(self):
        _ground, _player, camera = self.player_scene()
        self.settings.vantage_spacing = 4.0
        self.box("Wall", (30, 0.5, 8), (0, 10, 4.0))
        hidden = self.sphere("BehindWall", 0.8, (0, 14, 0.8))
        open_air = self.sphere("InTheOpen", 0.8, (0, 5, 0.8))

        self.optimize()
        data = json.loads(self.scene[smart_optimizer.PVS])
        self.assertIn("BehindWall", data["objects"])
        self.assertFalse(hidden.hide_render, "the far side of the wall is walkable, so the object is needed")

        bpy.context.view_layer.update()
        culler = runtime_optimizer.SceneCuller(self.scene)
        stats = culler.update(camera, self.scene.blendengine_optimization)
        self.assertGreaterEqual(stats["occluded"], 1)
        if culler.soft:
            self.assertFalse(hidden.visible_camera)
            self.assertFalse(hidden.hide_get(), "soft culling keeps the object in the scene for shadows")
            self.assertTrue(open_air.visible_camera)
        else:
            self.assertTrue(hidden.hide_get())
            self.assertFalse(open_air.hide_get())

        # Walk around the wall: the object must come back.
        camera.location = (0, 16, 1.62)
        camera.rotation_euler = (math.radians(90), 0, math.radians(180))
        bpy.context.view_layer.update()
        culler.update(camera, self.scene.blendengine_optimization)
        self.assertTrue(hidden.visible_camera)
        self.assertFalse(hidden.hide_get())

        camera.location = (0, 0, 1.62)
        bpy.context.view_layer.update()
        culler.update(camera, self.scene.blendengine_optimization)
        culler.restore()
        self.assertTrue(hidden.visible_camera)
        self.assertFalse(hidden.hide_get())

    def test_frustum_culling_uses_bounds_not_origins(self):
        ground, _player, camera = self.player_scene()
        side = self.sphere("Side", 0.5, (30, 0, 0.5))
        self.scene.blendengine_optimization.camera_frustum_generation = False
        bpy.context.view_layer.update()
        culler = runtime_optimizer.SceneCuller(self.scene)
        culler.update(camera, self.scene.blendengine_optimization)

        def culled(obj):
            return (not obj.visible_camera) if culler.soft else obj.hide_get()

        # The floor's origin is under the camera, yet the floor fills the view.
        self.assertFalse(culled(ground))
        self.assertTrue(culled(side))
        culler.restore()

    def test_culler_never_reveals_objects_hidden_on_purpose(self):
        _ground, _player, camera = self.player_scene()
        body = self.sphere("Body", 0.4, (0, 3, 1.0))
        body.blendengine_object.object_tag = "PlayerBody"
        body.hide_set(True)
        culler = runtime_optimizer.SceneCuller(self.scene)
        culler.update(camera, self.scene.blendengine_optimization)
        self.assertTrue(body.hide_get())
        culler.restore()
        self.assertTrue(body.hide_get())

    def test_test_run_session_culls_while_playing_and_restores_on_stop(self):
        _ground, _player, camera = self.player_scene()
        self.settings.vantage_spacing = 4.0
        self.box("Wall", (30, 0.5, 8), (0, 10, 4.0))
        hidden = self.sphere("BehindWall", 0.8, (0, 14, 0.8))
        self.optimize()
        utils.ensure_default_input_bindings(self.scene)
        self.scene.blendengine_optimization.dynamic_resolution = True

        session, validation = runtime.start_test_run(bpy.context)
        self.assertIsNotNone(session, validation.all_messages())
        try:
            self.assertIsNotNone(session._governor)
            for _ in range(10):
                session.step(1.0 / 60.0)
            culled = (not hidden.visible_camera) if session._culler.soft else hidden.hide_get()
            self.assertTrue(culled)
            self.assertLess(self.scene.blendengine_project.runtime_visible_objects, len(self.scene.objects))
        finally:
            runtime.finish_active_session()
        self.assertTrue(hidden.visible_camera)
        self.assertFalse(hidden.hide_get())
        self.assertFalse(self.scene.blendengine_project.test_running)

    def test_lods_are_built_and_swapped_by_distance(self):
        _ground, _player, camera = self.player_scene()
        self.settings.build_lods = True
        statue = self.sphere("Statue", 1.0, (0, 6, 1.0), subdivisions=5)
        small = self.sphere("Pebble", 0.2, (3, 6, 0.2), subdivisions=2)

        report = self.optimize()

        names = list(statue[smart_optimizer.LOD_MESHES])
        distances = list(statue[smart_optimizer.LOD_DISTANCES])
        self.assertEqual(len(names), 3)
        self.assertLess(distances[0], distances[1])
        counts = [smart_optimizer._triangles(bpy.data.meshes[name]) for name in names]
        self.assertGreater(counts[0], counts[1])
        self.assertGreater(counts[1], counts[2])
        self.assertNotIn(smart_optimizer.LOD_MESHES, small)
        self.assertFalse(self.step(report, "lods")["lossless"])

        self.scene.blendengine_optimization.camera_frustum_generation = False
        culler = runtime_optimizer.SceneCuller(self.scene)
        for distance, expected in ((2.0, 0), (distances[0] + 3.0, 1), (distances[1] + 3.0, 2), (2.0, 0)):
            camera.location = (0, 6 - distance - 1.0, 1.0)
            bpy.context.view_layer.update()
            culler.update(camera, self.scene.blendengine_optimization)
            self.assertEqual(statue.data.name, names[expected])
        camera.location = (0, -200, 1.0)
        bpy.context.view_layer.update()
        culler.update(camera, self.scene.blendengine_optimization)
        culler.restore()
        self.assertEqual(statue.data.name, names[0])

    def test_quality_governor_steps_down_under_load_and_recovers_with_hysteresis(self):
        for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                self.scene.render.engine = engine
                break
            except TypeError:
                continue
        eevee = self.scene.eevee
        original = {name: getattr(eevee, name) for name in ("shadow_ray_count", "volumetric_samples")
                    if hasattr(eevee, name)}
        governor = runtime_optimizer.QualityGovernor(self.scene, target_fps=60, interval=10)

        for _ in range(10):
            self.assertIn(governor.update(16.0), (None,))
        self.assertEqual(governor.level, 0)

        levels = [governor.update(22.0, emergency=False) for _ in range(40)]
        self.assertEqual(governor.level, 4)
        self.assertEqual([level for level in levels if level is not None], [1, 2, 3, 4])
        if "shadow_ray_count" in original:
            self.assertEqual(eevee.shadow_ray_count, 1)

        # One fast interval is not enough to raise quality again.
        for _ in range(10):
            governor.update(5.0)
        self.assertEqual(governor.level, 4)
        for _ in range(200):
            governor.update(5.0)
        self.assertEqual(governor.level, 0)

        governor.update(80.0)
        for _ in range(9):
            governor.update(80.0)
        self.assertEqual(governor.level, 2, "an emergency drop skips a level")
        governor.restore()
        for name, value in original.items():
            self.assertEqual(getattr(eevee, name), value)

    # -- cinematic look -----------------------------------------------------

    def test_cinematic_look_focuses_the_lens_and_adds_removable_post(self):
        _ground, player, camera = self.player_scene(first_person=False)
        camera.location = (0, -6, 3.2)
        bpy.context.view_layer.update()
        result = cinematic.apply_look(self.scene, fstop=2.0)

        self.assertFalse(result["skipped"])
        self.assertTrue(camera.data.dof.use_dof)
        self.assertEqual(camera.data.dof.focus_object, player)
        self.assertAlmostEqual(camera.data.dof.aperture_fstop, 2.0)
        self.assertIn(self.scene.view_settings.view_transform, {"AgX", "Filmic"})
        if hasattr(self.scene, "node_tree"):
            tagged = [node for node in self.scene.node_tree.nodes if node.get(cinematic.NODE_TAG)]
            self.assertGreaterEqual(len(tagged), 4)
            output = next(node for node in self.scene.node_tree.nodes if node.bl_idname == "CompositorNodeComposite")
            self.assertTrue(output.inputs["Image"].is_linked)
            # Applying twice must not stack a second chain.
            cinematic.apply_look(self.scene)
            again = [node for node in self.scene.node_tree.nodes if node.get(cinematic.NODE_TAG)]
            self.assertEqual(len(again), len(tagged))
            self.assertEqual(cinematic.remove_post(self.scene), len(tagged))
            self.assertEqual(output.inputs["Image"].links[0].from_node.bl_idname, "CompositorNodeRLayers")

    def test_first_person_camera_does_not_focus_on_its_own_body(self):
        _ground, _player, camera = self.player_scene(first_person=True)
        camera.data.dof.focus_distance = 7.5
        cinematic.apply_look(self.scene, post=False)
        self.assertTrue(camera.data.dof.use_dof)
        self.assertIsNone(camera.data.dof.focus_object)
        self.assertAlmostEqual(camera.data.dof.focus_distance, 7.5)

    def test_cinematic_look_keeps_an_authored_compositor(self):
        self.player_scene()
        if not hasattr(self.scene, "node_tree"):
            self.skipTest("This Blender version has a different compositor API")
        self.scene.use_nodes = True
        tree = self.scene.node_tree
        authored = tree.nodes.new("CompositorNodeBrightContrast")
        count = len(tree.nodes)

        result = cinematic.apply_look(self.scene)

        self.assertEqual(len(tree.nodes), count)
        self.assertIn(authored.name, tree.nodes)
        self.assertTrue(any("authored compositor" in item for item in result["unsupported"]))

    # -- operators ----------------------------------------------------------

    def test_operators_run_end_to_end_and_write_a_report(self):
        self.player_scene()
        crate = self.box("Crate", (2, 2, 2), (5, 0, 1.0), cuts=7)
        before = triangles(crate)

        self.assertEqual(bpy.ops.blendengine.smart_optimize(), {"FINISHED"})
        self.assertLess(triangles(crate), before)
        text = bpy.data.texts["BlendEngine Smart Optimizer"].as_string()
        self.assertIn("picture unchanged", text)
        self.assertIn("Triangles", self.scene.blendengine_smart.last_summary)

        self.assertEqual(bpy.ops.blendengine.smart_restore(), {"FINISHED"})
        self.assertEqual(triangles(crate), before)
        self.assertEqual(bpy.ops.blendengine.apply_cinematic_look(), {"FINISHED"})
        self.assertEqual(self.scene.blendengine_quality_profile.preset, "CINEMATIC")

    def test_running_twice_changes_nothing_more(self):
        self.player_scene()
        crate = self.box("Crate", (2, 2, 2), (5, 0, 1.0), cuts=7)
        self.optimize()
        once = triangles(crate)
        report = self.optimize()
        self.assertEqual(triangles(crate), once)
        self.assertEqual(report["before"]["triangles"], report["after"]["triangles"])
        smart_optimizer.restore(self.scene)
        self.assertEqual(triangles(crate), 6 * 64 * 2)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OptimizerTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError("BlendEngine optimizer tests failed")
