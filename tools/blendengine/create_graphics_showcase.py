# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the self-contained 'Aperture Hall' EEVEE graphics showcase.

Run from the repository root with Blender 3.6 or newer::

    blender -b --factory-startup --python tools/blendengine/create_graphics_showcase.py \
        -- --output-dir /tmp/blendengine-showcase --render

All geometry and material textures are generated here. No downloaded assets,
external textures, third-party add-ons, or renderer plug-ins are required.
"""

import argparse
import math
from pathlib import Path
import random
import sys

import bpy
from mathutils import Vector


def material(name, color, roughness=0.5, metallic=0.0, texture_scale=6.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = texture_scale
    noise.inputs["Detail"].default_value = 3.0
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.15
    ramp.color_ramp.elements[0].color = (*(c * 0.62 for c in color), 1.0)
    ramp.color_ramp.elements[1].position = 0.85
    ramp.color_ramp.elements[1].color = (*(c * 1.2 for c in color), 1.0)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    # Keep the relief small: broad noise should read as material, not rubble.
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.16 if metallic < 0.5 else 0.08
    bump.inputs["Distance"].default_value = 0.045 if roughness > 0.4 else 0.014
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def emissive(name, color, strength):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    emission = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
    emission.default_value = (*color, 1.0)
    strength_input = bsdf.inputs.get("Emission Strength")
    if strength_input is not None:
        strength_input.default_value = strength
    return mat


def weighted_normals(obj):
    # Blender 3.6 requires this mesh flag; Blender 4.1+ removed it.
    if hasattr(obj.data, "use_auto_smooth"):
        obj.data.use_auto_smooth = True
    modifier = obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
    modifier.keep_sharp = True


def box(name, location, dimensions, mat, bevel=0.035):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        modifier = obj.modifiers.new("Machined edge highlights", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
        weighted_normals(obj)
    return obj


def cylinder(name, location, radius, depth, mat, vertices=96):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    bevel = obj.modifiers.new("Soft rim", "BEVEL")
    bevel.width = 0.045
    bevel.segments = 3
    weighted_normals(obj)
    return obj


def ring(name, radius, thickness, location, mat):
    bpy.ops.mesh.primitive_torus_add(
        major_segments=144, minor_segments=16, location=location,
        major_radius=radius, minor_radius=thickness,
        rotation=(math.pi / 2, 0, 0),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def area(name, location, target, color, energy, size, size_y=None):
    light = bpy.data.lights.new(name, "AREA")
    light.color = color
    light.energy = energy
    light.shape = "RECTANGLE" if size_y else "DISK"
    light.size = size
    if size_y:
        light.size_y = size_y
    if hasattr(light, "use_shadow"):
        light.use_shadow = True
    if hasattr(light, "use_contact_shadow"):
        light.use_contact_shadow = True
    obj = bpy.data.objects.new(name, light)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def setup_renderer(scene, args):
    addon_path = Path(__file__).resolve().parents[2] / "scripts" / "addons_core"
    sys.path.insert(0, str(addon_path))
    import blendengine
    from blendengine import graphics, optimization
    blendengine.register()
    graphics.configure_realtime(scene)
    optimization.apply_preset(scene, "CINEMATIC")
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.render.fps = 30
    scene.render.image_settings.color_depth = "8"

    if hasattr(scene.render, "use_motion_blur"):
        scene.render.use_motion_blur = False
    eevee = getattr(scene, "eevee", None)
    if eevee is not None:
        if args.samples:
            eevee.taa_render_samples = args.samples
        if hasattr(eevee, "use_motion_blur"):
            eevee.use_motion_blur = False

    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = -0.35
    scene.view_settings.gamma = 1.0

    world = bpy.data.worlds.new("Aperture Hall | cool ambient")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.17, 0.25, 0.36, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.18
    scene.world = world

    # This is a new, generated scene. Existing user compositor graphs are never touched.
    scene.use_nodes = True
    nodes, links = scene.node_tree.nodes, scene.node_tree.links
    nodes.clear()
    source = nodes.new("CompositorNodeRLayers")
    glow = nodes.new("CompositorNodeGlare")
    glow.name = "Restrained highlight glow"
    glow.glare_type = "FOG_GLOW"
    glow.quality = "HIGH"
    glow.threshold = 2.0
    glow.size = 7
    glow.mix = -0.88
    output = nodes.new("CompositorNodeComposite")
    source.location = (-300, 0)
    glow.location = (0, 0)
    output.location = (250, 0)
    links.new(source.outputs["Image"], glow.inputs["Image"])
    links.new(glow.outputs["Image"], output.inputs["Image"])


def build_scene(args):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.name = "BlendEngine | Aperture Hall"
    setup_renderer(scene, args)
    rng = random.Random(43)

    concrete = material("PBR | basalt concrete", (0.15, 0.18, 0.20), 0.76, texture_scale=7)
    pale = material("PBR | cast limestone", (0.38, 0.36, 0.31), 0.68, texture_scale=8)
    dark = material("PBR | anodized titanium", (0.065, 0.083, 0.10), 0.27, 0.78, 28)
    copper = material("PBR | brushed copper", (0.48, 0.19, 0.073), 0.26, 0.82, 40)
    floor = material("PBR | rain polished slate", (0.085, 0.105, 0.115), 0.19, 0.28, 42)
    grout = material("PBR | expansion joints", (0.018, 0.022, 0.026), 0.8)
    amber = emissive("Light | amber ceramic", (1.0, 0.37, 0.075), 7.0)
    cyan = emissive("Light | ice cyan", (0.08, 0.66, 0.89), 5.0)

    # Slab joints give clear, physical perspective and catch the hero reflection.
    box("Foundation", (0, 1, -0.28), (20, 30, 0.4), grout)
    for x in range(-5, 5):
        for y in range(-6, 9):
            obj = box("Slate slab %02d %02d" % (x + 5, y + 6),
                      (x * 2 + 1, y * 2 + 1, -0.04), (1.975, 1.975, 0.15), floor, 0.018)
            obj.rotation_euler.z = rng.uniform(-0.0006, 0.0006)

    # Tall, patterned concrete shell. Side fins catch cyan and sunset highlights.
    box("Rear wall", (0, 10.3, 4.6), (20, 0.7, 9.2), concrete, 0.06)
    box("Rear inset", (0, 9.85, 4.5), (7.8, 0.22, 7.3), dark)
    for x in (-4.35, 4.35):
        box("Portal backdrop pilaster", (x, 9.4, 4.6), (0.65, 1.8, 9.2), pale)
    for x in range(-8, 9, 2):
        box("Rear concrete relief", (x, 9.83, 4.7), (0.06, 0.1, 8.8), dark, 0.008)
    for side in (-1, 1):
        box("Hall side wall", (side * 9.4, 1.5, 4.4), (0.65, 19, 8.8), concrete)
        for y in (-6, -2.5, 1, 4.5, 8):
            box("Structural blade", (side * 8.95, y, 4.1), (0.65, 0.65, 8.2), pale, 0.045)
            box("Vertical cyan light", (side * 8.56, y - 0.31, 3.6), (0.065, 0.04, 5.8), cyan, 0.01)
        box("Floor guide light", (side * 6.3, 0.5, 0.051), (0.038, 19, 0.026), cyan, 0.005)
    for y in (-2, 2.0, 6.0, 9.4):
        box("Ceiling crossbeam", (0, y, 8.7), (19, 0.36, 0.8), concrete)

    # A stepped base grounds the circular machine. Repeated copper accents add scale.
    cylinder("Lower plinth", (0, 4, 0.12), 3.65, 0.25, dark)
    cylinder("Upper plinth", (0, 4, 0.31), 3.20, 0.2, concrete)
    cylinder("Copper plinth lip", (0, 4, 0.43), 2.96, 0.055, copper)
    cylinder("Slate plinth surface", (0, 4, 0.48), 2.88, 0.06, dark)
    ring("Outer titanium aperture", 2.7, 0.22, (0, 4.8, 3.25), dark)
    ring("Outer copper aperture", 2.82, 0.055, (0, 4.79, 3.25), copper)
    ring("Inner amber aperture", 2.42, 0.045, (0, 4.53, 3.25), amber)
    ring("Inner machined lip", 2.34, 0.085, (0, 4.68, 3.25), copper)
    for index in range(32):
        angle = index * math.tau / 32
        obj = box("Aperture radial clamp %02d" % index,
                  (math.sin(angle) * 2.72, 4.72, 3.25 + math.cos(angle) * 2.72),
                  (0.15, 0.58, 0.34), copper, 0.022)
        obj.rotation_euler.y = angle

    # Faceted, physically reflective hero rather than an emissive sphere.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1.0, location=(0, 4.15, 3.25))
    hero = bpy.context.object
    hero.name = "Levitating copper polyhedron"
    hero.scale = (0.9, 0.9, 1.3)
    hero.rotation_euler = (0.18, 0.22, 0.3)
    hero.data.materials.append(copper)
    bevel = hero.modifiers.new("Polished facet edges", "BEVEL")
    bevel.width = 0.018
    bevel.segments = 3
    weighted_normals(hero)
    cylinder("Artifact pedestal", (0, 4.15, 0.86), 0.75, 0.72, dark)
    cylinder("Pedestal amber rim", (0, 4.15, 1.23), 0.76, 0.035, amber)

    for side in (-1, 1):
        for y in (-1, 6.9):
            box("Instrument plinth", (side * 5.8, y, 0.62), (0.72, 0.72, 1.24), dark)
            box("Instrument copper cap", (side * 5.8, y, 1.25), (0.76, 0.76, 0.08), copper)
            box("Instrument amber slit", (side * 5.8, y - 0.366, 0.9), (0.42, 0.022, 0.035), amber, 0.006)

    # Emission supplies visible sources; area lights supply the actual illumination.
    area("Warm aperture key", (0, 4.2, 5.55), (0, 2.5, 0), (1.0, 0.45, 0.16), 1600, 4.0)
    area("Hero softbox", (-3, 0, 6.8), (0, 4, 2.8), (1.0, 0.78, 0.51), 2200, 4.5)
    area("Cool hero rim", (3.5, 7.6, 5), (0, 3, 2.7), (0.16, 0.63, 1.0), 2100, 3)
    area("Front fill", (1, -7, 6), (0, 4, 3), (0.35, 0.57, 0.75), 1300, 8)
    area("Wall sunset wash", (-6, 1.0, 8.5), (3, 8, 2), (1.0, 0.63, 0.33), 2400, 5, 2)
    for side in (-1, 1):
        area("Cyan wall wash", (side * 8.3, 2, 5.8), (side * 5.0, 2, 0),
             (0.12, 0.67, 1.0), 1900, 6, 1)
    area("Aperture rear halo", (0, 6.2, 4.5), (0, 10.0, 4.5), (1.0, 0.35, 0.08), 1700, 3)

    camera_data = bpy.data.cameras.new("Cinematic 39mm")
    camera = bpy.data.objects.new("Showcase camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (8.6, -15.7, 5.9)
    target = Vector((0.0, 3.4, 2.9))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 39
    camera_data.clip_end = 160
    camera_data.dof.use_dof = True
    camera_data.dof.focus_object = hero
    camera_data.dof.aperture_fstop = 7.1
    scene.camera = camera

    for screen in bpy.data.screens:
        for space_area in screen.areas:
            if space_area.type == "VIEW_3D":
                space_area.spaces.active.region_3d.view_perspective = "CAMERA"
                # Opening the .blend should show the authored lights/world.
                space_area.spaces.active.shading.type = "RENDERED"
                space_area.spaces.active.overlay.show_overlays = False

    bpy.ops.object.select_all(action="DESELECT")
    hero.select_set(True)
    bpy.context.view_layer.objects.active = hero
    scene["showcase_generator"] = "tools/blendengine/create_graphics_showcase.py"
    scene["showcase_assets"] = "Original procedural geometry and materials; no external assets"
    scene["showcase_purpose"] = "EEVEE graphics demonstration; not a native game export or GPU performance benchmark"
    return scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--samples", type=int, default=0, help="Optional render sample override for quick previews")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scene = build_scene(args)
    scene.render.filepath = str((args.output_dir / "aperture_hall.png").resolve())
    bpy.ops.wm.save_as_mainfile(filepath=str((args.output_dir / "aperture_hall.blend").resolve()))
    if args.render:
        bpy.ops.render.render(write_still=True)
    print("BLENDENGINE_SHOWCASE: " + str(args.output_dir.resolve()))


if __name__ == "__main__":
    main()
