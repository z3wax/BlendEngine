# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure what the Smart Optimizer saves and whether the picture changes.

Builds a deliberately wasteful game level ("Bazaar"), renders fixed player
viewpoints with EEVEE before and after optimizing, and compares the frames
pixel by pixel. Everything is generated here; nothing is downloaded.

Run from the repository root with Blender 4.3 (or its ``bpy`` module)::

    blender -b --factory-startup --python-exit-code 1 \
        --python tools/blendengine/optimizer_benchmark.py -- \
        --output-dir /tmp/blendengine-benchmark --render

Without ``--render`` only the scene statistics are measured (no GPU needed).
The script wipes the current Blender session, so start it in a fresh one.
"""

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

import bpy
import bmesh
import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))

import blendengine
from blendengine import cinematic, components, optimization, runtime_optimizer, smart_optimizer


# Player positions used for the comparison: (name, (x, y), heading, tilt) in degrees,
# heading 0 = +Y and tilt 90 = level. "sign" stands at the plaza edge under Sign00,
# one of the images the optimizer halves, and looks up at it: the closest that
# resized texture can ever be seen.
VIEWS = (
    ("street", (0.0, -14.0), 0.0, 88.0),
    ("crates", (-7.0, -6.0), -42.0, 88.0),
    ("statues", (4.0, 2.0), 59.0, 88.0),
    ("sign", (17.8, 0.0), 90.0, 112.0),
)
EYE = 1.62


def detail_image(name, size, seed, tint):
    """An image with structure at every scale, down to single texels."""
    rng = np.random.default_rng(seed)
    grid_y, grid_x = np.mgrid[0:size, 0:size].astype(np.float32) / size
    value = 0.45 + 0.2 * np.sign(np.sin(grid_x * math.tau * 12.0) * np.sin(grid_y * math.tau * 8.0))
    for cells in (8, 32, 128, 512):
        if cells > size:
            break
        block = rng.random((cells, cells), dtype=np.float32) - 0.5
        value += np.repeat(np.repeat(block, size // cells, axis=0), size // cells, axis=1) * (0.9 / math.sqrt(cells))
    value += (rng.random((size, size), dtype=np.float32) - 0.5) * 0.12
    pixels = np.empty((size, size, 4), dtype=np.float32)
    for channel in range(3):
        pixels[:, :, channel] = np.clip(value * tint[channel], 0.0, 1.0)
    pixels[:, :, 3] = 1.0
    image = bpy.data.images.new(name, size, size)
    image.pixels.foreach_set(pixels.ravel())
    image.pack()
    return image


def image_material(name, image, repeat=None, roughness=0.6):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    shader = nodes["Principled BSDF"]
    shader.inputs["Roughness"].default_value = roughness
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    if repeat is not None:
        coords = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (repeat, repeat, 1.0)
        links.new(coords.outputs["UV"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
    return material


def add_object(scene, name, mesh, location, scale=(1.0, 1.0, 1.0), rotation_z=0.0):
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.scale = scale
    obj.rotation_euler.z = rotation_z
    scene.collection.objects.link(obj)
    return obj


def box_mesh(name, cuts=0):
    """Unit cube whose six faces each show the whole image."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    layer = bm.loops.layers.uv.new("UVMap")
    for face in bm.faces:
        axis = max(range(3), key=lambda i: abs(face.normal[i]))
        u_axis, v_axis = [i for i in range(3) if i != axis]
        for loop in face.loops:
            loop[layer].uv = (loop.vert.co[u_axis] + 0.5, loop.vert.co[v_axis] + 0.5)
    if cuts:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def sphere_mesh(name, subdivisions):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=1.0, calc_uvs=True)
    for face in bm.faces:
        face.smooth = True
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def panel_mesh(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-0.5, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5), (-0.5, 0, 0.5)], [], [(0, 1, 2, 3)])
    layer = mesh.uv_layers.new()
    for loop, uv in zip(layer.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop.uv = uv
    return mesh


def build_level(texture_size=4096):
    """A small level built the way beginners build them: copies of everything."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    blendengine.register()
    scene = bpy.context.scene
    scene.name = "Bazaar"
    half = texture_size // 2

    ground_image = detail_image("Cobblestone", half, 1, (0.55, 0.5, 0.45))
    facade_images = [detail_image("Facade%d" % i, half, 10 + i, tint)
                     for i, tint in enumerate(((0.8, 0.62, 0.45), (0.55, 0.62, 0.75), (0.7, 0.7, 0.62)))]
    crate_image = detail_image("CrateWood", half, 20, (0.62, 0.45, 0.28))
    marble_image = detail_image("Marble", half, 21, (0.85, 0.84, 0.8))
    skyline_tints = ((0.5, 0.58, 0.7), (0.62, 0.55, 0.6), (0.45, 0.6, 0.55), (0.66, 0.6, 0.5))
    skyline_images = [detail_image("Skyline%d" % i, texture_size, 30 + i, tint)
                      for i, tint in enumerate(skyline_tints)]

    sign_images = [detail_image("Sign%02d" % i, half, 40 + i, (0.9, 0.35 + 0.05 * (i % 5), 0.25))
                   for i in range(12)]

    # The plaza is the only floor the player walks on; the town stands around it.
    ground = add_object(scene, "Ground", box_mesh("Ground"), (0, 0, -0.25), (36, 36, 0.5))
    ground.data.materials.append(image_material("Cobblestone", ground_image, repeat=8.0, roughness=0.85))
    ground.blendengine_object.object_tag = "Ground"
    terrain = add_object(scene, "Terrain", box_mesh("Terrain"), (0, 0, -0.27), (140, 140, 0.5))
    terrain.data.materials.append(image_material("Dirt", ground_image, repeat=30.0, roughness=1.0))

    # Buildings: one mesh and one material copy each, furniture sealed inside,
    # and a shop sign with its own full-size texture high on the wall.
    for index in range(12):
        angle = index / 12.0 * math.tau
        radius = 27.0 if index % 2 else 29.5
        x, y = math.cos(angle) * radius, math.sin(angle) * radius
        height = 7.0 + (index % 3) * 2.0
        building = add_object(scene, "Building%02d" % index, box_mesh("Building%02d" % index, cuts=15),
                              (x, y, height * 0.5 - 0.02), (6.0, 6.0, height), angle)
        facade = facade_images[index % 3]
        building.data.materials.append(image_material("Facade%d.%03d" % (index % 3, index), facade, roughness=0.7))
        for item in range(3):
            add_object(scene, "Furniture%02d_%d" % (index, item), sphere_mesh("Furniture%02d_%d" % (index, item), 4),
                       (x, y, 1.0 + item * 1.8), (0.8, 0.8, 0.8))
        inward = radius - 3.05
        sign = add_object(scene, "Sign%02d" % index, panel_mesh("Sign%02d" % index),
                          (math.cos(angle) * inward, math.sin(angle) * inward, 5.2), (2.4, 1.0, 1.2),
                          angle + math.pi / 2.0)
        sign.data.materials.append(image_material("Sign%02d" % index, sign_images[index], roughness=0.5))

    # Crates: unique mesh and material per crate, stacked so many faces touch.
    for index in range(40):
        column, level = divmod(index, 2)
        x = -14.0 + (column % 5) * 1.0
        y = -2.0 + (column // 5) * 1.0
        crate = add_object(scene, "Crate%02d" % index, box_mesh("Crate%02d" % index, cuts=3),
                           (x, y, 0.5 + level * 1.0))
        crate.data.materials.append(image_material("CrateWood.%03d" % index, crate_image, roughness=0.8))
        crate.data.materials.append(bpy.data.materials.new("CrateSpare.%03d" % index))

    # Statues on pedestals.
    for index in range(6):
        x = 8.0 + (index % 3) * 3.5
        y = 4.0 + (index // 3) * 5.0
        pedestal = add_object(scene, "Pedestal%d" % index, box_mesh("Pedestal%d" % index, cuts=7), (x, y, 0.5),
                              (1.6, 1.6, 1.0))
        pedestal.data.materials.append(image_material("Marble.%03d" % index, marble_image, roughness=0.35))
        statue = add_object(scene, "Statue%d" % index, sphere_mesh("Statue%d" % index, 5), (x, y, 1.9),
                            (0.9, 0.9, 1.0))
        statue.data.materials.append(image_material("MarbleStatue.%03d" % index, marble_image, roughness=0.25))

    # A skyline far outside the walkable floor, at film-poster resolution.
    for index, image in enumerate(skyline_images):
        angle = index / 4.0 * math.tau + math.pi / 4.0
        panel = add_object(scene, "Skyline%d" % index, panel_mesh("Skyline%d" % index),
                           (math.sin(angle) * 160.0, math.cos(angle) * 160.0, 24.0), (90.0, 1.0, 50.0), -angle)
        panel.data.materials.append(image_material("Skyline%d" % index, image, roughness=1.0))

    player = add_object(scene, "Player", box_mesh("Player"), (0.0, -14.0, 0.9), (0.6, 0.6, 1.8))
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.data.lens = 28.0
    camera.data.clip_end = 600.0
    scene.collection.objects.link(camera)
    scene.camera = camera
    components.add_player_controller(player, camera=camera)
    player.blendengine_object.player_controller.controller_type = "FIRST_PERSON"
    # A first-person game does not draw the body the camera sits in.
    player.hide_render = True

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 4.0
    sun.data.angle = math.radians(2.0)
    sun.rotation_euler = (math.radians(52.0), 0.0, math.radians(35.0))
    scene.collection.objects.link(sun)
    for index, position in enumerate(((-11.0, -1.0, 4.0), (14.0, 6.0, 5.0))):
        lamp = bpy.data.objects.new("Lamp%d" % index, bpy.data.lights.new("Lamp%d" % index, "POINT"))
        lamp.data.energy = 800.0
        lamp.data.color = (1.0, 0.78, 0.55)
        lamp.location = position
        scene.collection.objects.link(lamp)

    world = bpy.data.worlds.new("Dusk")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.25, 0.36, 0.55, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6
    scene.world = world

    place_camera(scene, VIEWS[0])
    bpy.context.view_layer.update()
    return scene


def place_camera(scene, view):
    _name, (x, y), heading, tilt = view
    camera = scene.camera
    camera.location = (x, y, EYE)
    camera.rotation_euler = (math.radians(tilt), 0.0, math.radians(-heading))
    bpy.context.view_layer.update()


def render_views(scene, folder, tag, names):
    frames = {}
    seconds = {}
    for view in VIEWS:
        if view[0] not in names:
            continue
        place_camera(scene, view)
        path = os.path.join(folder, "%s_%s.png" % (view[0], tag))
        scene.render.filepath = path
        start = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        seconds[view[0]] = time.perf_counter() - start
        image = bpy.data.images.load(path)
        pixels = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        frames[view[0]] = pixels.reshape(image.size[1], image.size[0], 4)[:, :, :3].copy()
        bpy.data.images.remove(image)
    return frames, seconds


def compare(before, after):
    result = {}
    for name in before:
        difference = (before[name] - after[name]) * 255.0
        mse = float(np.mean(difference ** 2))
        result[name] = {
            "psnr_db": 99.0 if mse <= 1e-12 else 10.0 * math.log10(255.0 ** 2 / mse),
            "mean_abs_levels": float(np.mean(np.abs(difference))),
            "pixels_off_by_more_than_8_levels_percent": float(np.mean(np.abs(difference).max(axis=2) > 8.0) * 100.0),
        }
    return result


def walk_culling(scene):
    """Average share of objects and triangles handed to the camera along a walk."""
    culler = runtime_optimizer.SceneCuller(scene)
    counts = {name: smart_optimizer._triangles(bpy.data.meshes[names[0]])
              for name, (names, _distances) in culler.lods.items()}
    total_objects = total_triangles = sent_objects = sent_triangles = 0
    for step in range(48):
        angle = step / 48.0 * math.tau
        place_camera(scene, ("walk", (math.cos(angle) * 9.0, math.sin(angle) * 9.0), math.degrees(angle) * 3.0, 88.0))
        culler.update(scene.camera, scene.blendengine_optimization)
        for obj, _center, _radius, _slot in culler.items:
            if obj.type != "MESH":
                continue
            full = counts.get(obj.name, smart_optimizer._triangles(obj.data))
            total_objects += 1
            total_triangles += full
            seen = obj.visible_camera if culler.soft else not obj.hide_get()
            if seen and not obj.hide_get():
                sent_objects += 1
                sent_triangles += smart_optimizer._triangles(obj.data)
    culler.restore()
    return {
        "objects_sent_percent": 100.0 * sent_objects / max(1, total_objects),
        "triangles_sent_percent": 100.0 * sent_triangles / max(1, total_triangles),
    }


def main():
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="/tmp/blendengine-benchmark")
    parser.add_argument("--render", action="store_true",
                        help="render the comparison frames (needs a GPU or software GL)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--texture-size", type=int, default=4096)
    parser.add_argument("--depth-of-field", action="store_true",
                        help="keep the lens blur; off by default so the comparison is as sharp as possible")
    parser.add_argument("--views", default=",".join(view[0] for view in VIEWS),
                        help="comma separated view names to render")
    parser.add_argument("--save-blend", action="store_true")
    options = parser.parse_args(arguments)
    os.makedirs(options.output_dir, exist_ok=True)

    scene = build_level(options.texture_size)
    scene.blendengine_project.resolution_x = options.width
    scene.blendengine_project.resolution_y = options.height
    scene.render.resolution_x = options.width
    scene.render.resolution_y = options.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    from blendengine import graphics
    graphics.configure_realtime(scene)
    optimization.apply_preset(scene, "CINEMATIC")
    look = cinematic.apply_look(scene, depth_of_field=options.depth_of_field)
    scene.eevee.taa_render_samples = options.samples
    # Still frames from a fixed camera: motion blur would only multiply the sample count.
    if hasattr(scene.eevee, "use_motion_blur"):
        scene.eevee.use_motion_blur = False
    scene.render.use_motion_blur = False
    # The quality profile's phone budgets do not belong to the Cinematic preset; state them here.
    scene.blendengine_performance_budget.max_texture_memory_mb = 256

    result = {
        "blender": bpy.app.version_string,
        "engine": scene.render.engine,
        "resolution": [options.width, options.height],
        "samples": options.samples,
        "cinematic_settings_applied": len(look["applied"]),
    }
    before_frames = None
    if options.render:
        before_frames, before_seconds = render_views(scene, options.output_dir, "before", options.views.split(","))
        result["render_seconds_before"] = before_seconds

    place_camera(scene, VIEWS[0])
    start = time.perf_counter()
    report = smart_optimizer.optimize(bpy.context)
    result["optimize_seconds"] = time.perf_counter() - start
    result["before"] = report["before"]
    result["after"] = report["after"]
    result["viewpoints"] = report["vantages"]
    keys = ("id", "lossless", "count", "saved_triangles", "saved_texture_mb", "detail")
    result["steps"] = [{key: step[key] for key in keys} for step in report["steps"]]
    result["decisions"] = report["decisions"]
    print(smart_optimizer.report_text(report))

    if options.render:
        after_frames, after_seconds = render_views(scene, options.output_dir, "after", options.views.split(","))
        result["render_seconds_after"] = after_seconds
        result["picture"] = compare(before_frames, after_frames)
    result["runtime_walk"] = walk_culling(scene)

    if options.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(options.output_dir, "bazaar_optimized.blend"))
    with open(os.path.join(options.output_dir, "benchmark.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.stdout.flush()
        blendengine.unregister()
