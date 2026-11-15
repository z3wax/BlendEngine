# SPDX-License-Identifier: GPL-2.0-or-later
"""Build and render 'Core Ignition', a vertical 1080x1920 YouTube Shorts clip.

A 15 second, 30 fps EEVEE animation: a copper gyroscope ignites inside a circular
hall, its rings accelerate into a shockwave, lock into alignment and reveal the
BlendEngine title. Run from the repository root with Blender 4.2 or newer::

    blender -b --factory-startup --python-exit-code 1 \
        --python tools/blendengine/create_shorts_video.py -- \
        --output-dir /tmp/blendengine-short --render --encode

or with the ``bpy`` Python module::

    python tools/blendengine/create_shorts_video.py -- --output-dir /tmp/blendengine-short --render --encode

Rendering writes ``frames/frame_####.png`` and skips frames that already exist,
so an interrupted render can be resumed. ``--encode`` also writes the procedural
``soundtrack.wav`` and muxes ``blendengine_short.mp4`` with ffmpeg (H.264 + AAC).

Geometry, materials, animation and audio are all generated here, reusing the
procedural PBR helpers of ``create_graphics_showcase.py``. No downloaded models,
textures, music or third-party add-ons are used.
"""

import argparse
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import wave

import bpy
from mathutils import Euler, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import create_graphics_showcase as showcase  # noqa: E402

FPS = 30
DURATION = 15.0
FRAME_COUNT = int(DURATION * FPS)  # Frames 1..450.
CENTER = Vector((0.0, 0.0, 3.6))

# Timeline (seconds). The soundtrack uses the same constants.
IGNITE = (0.15, 0.35, 0.55)  # Ring bands switch on one after another.
CORE_FLARE = 0.7
RISER_START = 4.5
DROP = 7.0
BEAT = 0.5  # 120 BPM pulse after the drop.
LOCK_START = 10.0
LOCK = 11.0
TITLE = 11.25
RESUME = 12.0

# Brand palette (linear RGB). Mint/cyan come from docs/brand/banner.svg.
MINT = (0.32, 0.90, 0.62)
CYAN = (0.13, 0.61, 0.75)
AMBER = (1.0, 0.37, 0.075)

FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf",
    "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


# ---------------------------------------------------------------------------
# Timing helpers


def frame_time(frame):
    return (frame - 1) / FPS


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def smoothstep(edge0, edge1, value):
    x = clamp((value - edge0) / (edge1 - edge0))
    return x * x * (3.0 - 2.0 * x)


def ease_out_back(x, overshoot=1.6):
    x = clamp(x) - 1.0
    return 1.0 + x * x * ((overshoot + 1.0) * x + overshoot)


def beats_since_drop(t):
    """Decaying pulse that re-triggers on every beat after the drop."""
    if t < DROP:
        return 0.0
    phase = (t - DROP) % BEAT
    return math.exp(-phase * 9.0)


def ignite(t, start, flash=2.6):
    """A strip that flickers on at ``start`` and settles to full strength."""
    if t < start:
        return 0.0
    age = t - start
    if age < 0.12:
        return flash if int(age * FPS) % 2 == 0 else 0.15
    return 1.0 + (flash - 1.0) * math.exp(-(age - 0.12) * 7.0)


def speed_multiplier(t):
    """Gyroscope speed: idle, riser, drop spike, sustain."""
    value = 1.0 + 2.6 * smoothstep(RISER_START, DROP, t)
    if t >= DROP:
        value = 3.6 + 2.8 * math.exp(-(t - DROP) * 2.0)
    return value


def hermite(p0, v0, p1, v1, s, span):
    s2, s3 = s * s, s * s * s
    return ((2 * s3 - 3 * s2 + 1) * p0 + (s3 - 2 * s2 + s) * span * v0
            + (-2 * s3 + 3 * s2) * p1 + (s3 - s2) * span * v1)


def locking_angles(base_speed):
    """Spin, lock to an aligned pose (a multiple of pi) at LOCK, then drift."""
    substeps = FPS * 4
    step = 1.0 / substeps
    angle = 0.0
    free = {}
    for key in range(round(LOCK_START * substeps) + 1):
        free[key] = angle
        angle += base_speed * speed_multiplier((key + 0.5) * step) * step
    a0 = free[round(LOCK_START * substeps)]
    v0 = base_speed * speed_multiplier(LOCK_START)
    goal = a0 + 0.5 * v0 * (LOCK - LOCK_START)
    a1 = math.pi * (math.ceil(goal / math.pi) if v0 > 0 else math.floor(goal / math.pi))

    values = []
    for frame in range(1, FRAME_COUNT + 1):
        t = frame_time(frame)
        if t <= LOCK_START:
            values.append(free[(frame - 1) * 4])
        elif t <= LOCK:
            span = LOCK - LOCK_START
            values.append(hermite(a0, v0, a1, 0.0, (t - LOCK_START) / span, span))
        elif t <= RESUME:
            values.append(a1)
        else:
            # Ease back into a slow idle spin for the outro (loop friendly).
            s = t - RESUME
            ramp = 0.3 * base_speed
            values.append(a1 + ramp * (s - (1.0 - math.exp(-s * 1.5)) / 1.5))
    return values


# ---------------------------------------------------------------------------
# Animation baking. Per-frame LINEAR keys keep every curve fully authored here.


def bake(owner, data_path, values, index=-1):
    anim = owner.animation_data or owner.animation_data_create()
    if anim.action is None:
        anim.action = bpy.data.actions.new("%s | motion" % owner.name)
    action = anim.action
    if hasattr(action, "fcurve_ensure_for_datablock"):
        fcurve = action.fcurve_ensure_for_datablock(owner, data_path, index=index)
    else:
        fcurve = action.fcurves.new(data_path, index=index)
    points = fcurve.keyframe_points
    points.add(len(values))
    coords = []
    for frame, value in enumerate(values, start=1):
        coords.extend((frame, value))
    points.foreach_set("co", coords)
    for point in points:
        point.interpolation = "LINEAR"
    fcurve.update()


def bake_vector(owner, data_path, vectors, components=3):
    for index in range(components):
        bake(owner, data_path, [v[index] for v in vectors], index)


def bake_input(material, socket_name, values):
    """Animate a Principled BSDF input socket (e.g. emission strength)."""
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    socket = bsdf.inputs[socket_name]
    bake(material.node_tree, socket.path_from_id("default_value"), values)


def sample(function):
    return [function(frame_time(frame)) for frame in range(1, FRAME_COUNT + 1)]


# ---------------------------------------------------------------------------
# Scene construction


def emission_driven_by_object_color(name, color, strength):
    """Emissive material whose strength is scaled per object by obj.color[0]."""
    mat = showcase.emissive(name, color, strength)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    info = nodes.new("ShaderNodeObjectInfo")
    split = nodes.new("ShaderNodeSeparateColor")
    scale = nodes.new("ShaderNodeMath")
    scale.operation = "MULTIPLY"
    scale.inputs[1].default_value = strength
    links.new(info.outputs["Color"], split.inputs["Color"])
    links.new(split.outputs[0], scale.inputs[0])
    links.new(scale.outputs["Value"], bsdf.inputs["Emission Strength"])
    return mat


def text_material(name):
    """Bright satin aluminium faces with mint light on bevels and edges."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.72, 0.78, 0.8, 1)
    bsdf.inputs["Metallic"].default_value = 0.55
    bsdf.inputs["Roughness"].default_value = 0.34
    bsdf.inputs["Emission Color"].default_value = (*MINT, 1)
    weight = nodes.new("ShaderNodeLayerWeight")
    weight.inputs["Blend"].default_value = 0.35
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = 0.08
    ramp.inputs["From Max"].default_value = 0.6
    ramp.inputs["To Min"].default_value = 0.0
    ramp.inputs["To Max"].default_value = 1.0
    strength = nodes.new("ShaderNodeMath")
    strength.name = "Edge glow strength"
    strength.operation = "MULTIPLY"
    strength.inputs[1].default_value = 0.0
    links.new(weight.outputs["Facing"], ramp.inputs["Value"])
    links.new(ramp.outputs["Result"], strength.inputs[0])
    links.new(strength.outputs["Value"], bsdf.inputs["Emission Strength"])
    return mat, strength


def linked_copy(source, name, location, rotation=(0, 0, 0), scale=(1, 1, 1)):
    obj = bpy.data.objects.new(name, source.data)
    bpy.context.collection.objects.link(obj)
    obj.location, obj.rotation_euler, obj.scale = location, rotation, scale
    return obj


def apply_modifiers(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    for modifier in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=modifier.name)


def empty(name, parent=None, location=(0, 0, 0)):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.empty_display_size = 0.4
    obj.parent = parent
    obj.location = location
    return obj


def torus(name, parent, radius, thickness, mat, segments=160):
    bpy.ops.mesh.primitive_torus_add(
        major_segments=segments, minor_segments=18, major_radius=radius,
        minor_radius=thickness, location=(0, 0, 0), rotation=(math.pi / 2, 0, 0),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.parent = parent
    return obj


def find_font(path):
    if path:
        return bpy.data.fonts.load(path)
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return bpy.data.fonts.load(candidate)
    return None  # Blender's built-in font.


def text_object(name, body, size, font, mat, extrude=0.0, bevel=0.0, spacing=1.0):
    curve = bpy.data.curves.new(name, type="FONT")
    curve.body = body
    curve.size = size
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.space_line = 0.82
    curve.space_character = spacing
    curve.extrude = extrude
    curve.bevel_depth = bevel
    curve.bevel_resolution = 3
    if font is not None:
        curve.font = font
    curve.materials.append(mat)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.rotation_euler = (math.pi / 2, 0, 0)  # Stand up, facing -Y.
    return obj


def point_light(name, location, color, energy, radius=0.2):
    light = bpy.data.lights.new(name, "POINT")
    light.color = color
    light.energy = energy
    light.shadow_soft_size = radius
    obj = bpy.data.objects.new(name, light)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def apply_software_budget(scene):
    """Trim per-pixel tracing for CPU (software OpenGL) rendering.

    Keeps the Cinematic profile's features (soft shadows, screen-traced
    reflections, fast GI, motion blur, DOF) but with fewer rays/steps. Measured
    on a 4-core CPU with Mesa llvmpipe, this cut a 540x960 frame from 43 s to 10 s.
    """
    eevee = scene.eevee
    for name, value in (("shadow_ray_count", 1), ("shadow_step_count", 6), ("shadow_resolution_scale", 0.5),
                        ("fast_gi_ray_count", 2), ("fast_gi_step_count", 8)):
        if hasattr(eevee, name):
            setattr(eevee, name, value)
    options = getattr(eevee, "ray_tracing_options", None)
    if options is not None:
        options.resolution_scale = "2"
        options.trace_max_roughness = 0.4
    for light in bpy.data.lights:
        if hasattr(light, "shadow_maximum_resolution"):
            light.shadow_maximum_resolution = 0.005


def setup_render(scene, args):
    showcase_args = argparse.Namespace(width=args.width, height=args.height, samples=args.samples)
    showcase.setup_renderer(scene, showcase_args)  # BlendEngine Cinematic profile + glow.
    scene.name = "BlendEngine | Core Ignition (Shorts)"
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, FRAME_COUNT
    scene.view_settings.exposure = -0.15
    # Velocity based motion blur from the Cinematic profile reads as real camera motion.
    scene.render.motion_blur_shutter = 0.42
    world = scene.world
    world.name = "Core Ignition | deep teal ambient"
    background = world.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (0.035, 0.07, 0.09, 1)
    background.inputs["Strength"].default_value = 0.35

    tree = scene.node_tree
    glow = tree.nodes.get("Restrained highlight glow")
    glow.threshold = 1.4
    glow.mix = -0.72
    glow.size = 8
    # Gentle vignette keeps the eye on the centre of a tall phone frame.
    composite = next(node for node in tree.nodes if node.bl_idname == "CompositorNodeComposite")
    mask = tree.nodes.new("CompositorNodeEllipseMask")
    mask.width, mask.height = 0.92, 0.82
    blur = tree.nodes.new("CompositorNodeBlur")
    blur.filter_type = "FAST_GAUSS"
    blur.use_relative = True
    blur.factor_x = blur.factor_y = 32
    shade = tree.nodes.new("CompositorNodeMixRGB")
    shade.blend_type = "MULTIPLY"
    shade.inputs["Fac"].default_value = 1.0
    darken = tree.nodes.new("CompositorNodeMapRange")
    darken.inputs["To Min"].default_value = 0.42
    tree.links.new(mask.outputs["Mask"], blur.inputs["Image"])
    tree.links.new(blur.outputs["Image"], darken.inputs["Value"])
    tree.links.new(glow.outputs["Image"], shade.inputs[1])
    tree.links.new(darken.outputs["Value"], shade.inputs[2])
    tree.links.new(shade.outputs["Image"], composite.inputs["Image"])


def build_hall(rng, mats):
    """Circular slate floor, glowing grout, pillars with light strips, halo."""
    floor_glow = showcase.emissive("Light | floor grout glow", CYAN, 0.7)
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=16, depth=0.1, location=(0, 0, -0.08))
    bpy.context.object.name = "Grout light bed"
    bpy.context.object.data.materials.append(floor_glow)

    template = showcase.box("Slab template", (0, 0, -100), (0.965, 0.965, 0.16), mats["floor"], 0.02)
    apply_modifiers(template)
    slabs = []
    for ix in range(-15, 16):
        for iy in range(-15, 16):
            x, y = ix * 1.0, iy * 1.0
            distance = math.hypot(x, y)
            if distance > 15.2:
                continue
            slab = linked_copy(template, "Floor slab %+03d %+03d" % (ix, iy), (x, y, 0.0))
            slab.rotation_euler.z = rng.uniform(-0.002, 0.002)
            slabs.append((slab, distance))
    bpy.data.objects.remove(template)

    # Open-ended shell: a bottom cap would cover the glowing grout between slabs.
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=15.6, depth=18, location=(0, 0, 9),
                                        end_fill_type="NOTHING")
    wall = bpy.context.object
    wall.name = "Hall shell"
    wall.data.materials.append(mats["concrete"])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.flip_normals()  # Face the lit interior.
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=15.7, depth=0.4, location=(0, 0, 16.2))
    bpy.context.object.name = "Hall ceiling"
    bpy.context.object.data.materials.append(mats["concrete"])

    strip_mat = emission_driven_by_object_color("Light | pillar strip", MINT, 7.0)
    strips = []
    count = 20
    for index in range(count):
        angle = index * math.tau / count
        direction = Vector((math.cos(angle), math.sin(angle), 0))
        pillar = showcase.box("Hall pillar %02d" % index, direction * 13.4 + Vector((0, 0, 8)),
                              (0.9, 0.9, 16), mats["pale"], 0.05)
        pillar.rotation_euler.z = angle
        strip = showcase.box("Pillar light strip %02d" % index, direction * 12.92 + Vector((0, 0, 6.5)),
                             (0.05, 0.14, 12.5), strip_mat, 0.0)
        strip.rotation_euler.z = angle
        strips.append((strip, angle))

    halo_mat = showcase.emissive("Light | ceiling halo", MINT, 6.0)
    bpy.ops.mesh.primitive_torus_add(major_segments=192, minor_segments=12, major_radius=4.4,
                                     minor_radius=0.06, location=(0, 0, 14.5))
    bpy.context.object.name = "Ceiling halo"
    bpy.context.object.data.materials.append(halo_mat)
    for y in (-6, 0, 6):
        showcase.box("Ceiling beam", (0, y, 15.2), (31, 0.5, 0.9), mats["concrete"], 0.05)
    return slabs, strips, floor_glow


def build_gyroscope(mats):
    """Three nested gimbal rings around a levitating copper core."""
    showcase.cylinder("Lower plinth", (0, 0, 0.14), 2.7, 0.28, mats["dark"])
    showcase.cylinder("Upper plinth", (0, 0, 0.36), 2.3, 0.18, mats["concrete"])
    showcase.cylinder("Copper plinth lip", (0, 0, 0.47), 2.12, 0.05, mats["copper"])
    showcase.cylinder("Slate plinth surface", (0, 0, 0.5), 2.0, 0.06, mats["floor"])
    plinth_glow = showcase.emissive("Light | plinth ring", AMBER, 6.0)
    bpy.ops.mesh.primitive_torus_add(major_segments=160, minor_segments=10, major_radius=2.05,
                                     minor_radius=0.018, location=(0, 0, 0.53))
    bpy.context.object.name = "Plinth amber rim"
    bpy.context.object.data.materials.append(plinth_glow)

    root = empty("Gyroscope root", location=CENTER)
    pivot_a = empty("Gimbal A (yaw)", root)
    pivot_b = empty("Gimbal B (pitch)", pivot_a)
    pivot_c = empty("Gimbal C (roll)", pivot_b)

    band_a = showcase.emissive("Light | ring A mint", MINT, 9.0)
    band_b = showcase.emissive("Light | ring B cyan", CYAN, 11.0)
    band_c = showcase.emissive("Light | ring C amber", AMBER, 10.0)

    torus("Ring A titanium", pivot_a, 2.3, 0.12, mats["dark"])
    torus("Ring A copper lip", pivot_a, 2.43, 0.035, mats["copper"])
    torus("Ring A light", pivot_a, 2.17, 0.022, band_a)
    for index in range(16):
        angle = index * math.tau / 16
        clamp_obj = showcase.box("Ring A clamp %02d" % index,
                                 (math.sin(angle) * 2.3, 0, math.cos(angle) * 2.3),
                                 (0.14, 0.42, 0.3), mats["copper"], 0.02)
        clamp_obj.rotation_euler.y = angle
        clamp_obj.parent = pivot_a
    torus("Ring B copper", pivot_b, 1.86, 0.085, mats["copper"])
    torus("Ring B light", pivot_b, 1.75, 0.022, band_b)
    for index in range(8):
        angle = index * math.tau / 8 + math.pi / 8
        stud = showcase.box("Ring B stud %02d" % index,
                            (math.sin(angle) * 1.86, 0, math.cos(angle) * 1.86),
                            (0.1, 0.26, 0.2), mats["dark"], 0.015)
        stud.rotation_euler.y = angle
        stud.parent = pivot_b
    torus("Ring C titanium", pivot_c, 1.44, 0.07, mats["dark"])
    torus("Ring C light", pivot_c, 1.35, 0.02, band_c)
    # Axles make the nesting read as a mechanism rather than floating hoops.
    for side in (-1, 1):
        axle = showcase.cylinder("Gimbal B axle", (side * 2.07, 0, 0), 0.07, 0.42, mats["copper"], 32)
        axle.rotation_euler.y = math.pi / 2
        axle.parent = pivot_b
        axle = showcase.cylinder("Gimbal C axle", (0, 0, side * 1.65), 0.06, 0.36, mats["copper"], 32)
        axle.parent = pivot_c

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.62, location=(0, 0, 0))
    core = bpy.context.object
    core.name = "Copper core"
    core.scale = (0.85, 0.85, 1.15)
    core.data.materials.append(mats["copper"])
    bevel = core.modifiers.new("Polished facet edges", "BEVEL")
    bevel.width = 0.014
    bevel.segments = 3
    showcase.weighted_normals(core)
    core.parent = root
    if hasattr(core, "visible_shadow"):
        core.visible_shadow = False  # Lets the inner light reach the hall.

    cage_mat = showcase.emissive("Light | core cage", AMBER, 9.0)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.92, location=(0, 0, 0))
    cage = bpy.context.object
    cage.name = "Core energy cage"
    wire = cage.modifiers.new("Energy lattice", "WIREFRAME")
    wire.thickness = 0.018
    cage.data.materials.append(cage_mat)
    cage.parent = root
    if hasattr(cage, "visible_shadow"):
        cage.visible_shadow = False

    core_light = point_light("Core light", (0, 0, 0), (1.0, 0.5, 0.2), 0, 0.3)
    core_light.parent = root
    return {
        "root": root, "pivots": (pivot_a, pivot_b, pivot_c), "bands": (band_a, band_b, band_c),
        "core": core, "cage": cage, "cage_mat": cage_mat, "core_light": core_light,
        "plinth_glow": plinth_glow,
    }


def build_shards(rng, mats):
    shard_glow = emission_driven_by_object_color("Light | shard glow", MINT, 14.0)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.16, location=(0, 0, -100))
    facet = bpy.context.object
    facet.name = "Shard template facet"
    facet.data.materials.append(mats["copper"])
    bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0, 0, -100))
    cube = bpy.context.object
    cube.name = "Shard template cube"
    cube.data.materials.append(mats["dark"])
    bevel = cube.modifiers.new("Edge", "BEVEL")
    bevel.width = 0.02
    bevel.segments = 2
    apply_modifiers(cube)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=0, radius=0.11, location=(0, 0, -100))
    gem = bpy.context.object
    gem.name = "Shard template gem"
    gem.data.materials.append(shard_glow)

    shards = []
    count = 46
    for index in range(count):
        source = (facet, cube, gem, facet, cube)[index % 5]
        obj = linked_copy(source, "Orbit shard %02d" % index, (0, 0, 0))  # Shares mesh + material.
        scale = rng.uniform(0.6, 1.5)
        obj.scale = (scale, scale * rng.uniform(0.7, 1.3), scale * rng.uniform(0.8, 1.6))
        obj.color = (0.0, 0.0, 0.0, 1.0)
        shards.append({
            "obj": obj,
            "glow": source is gem,
            "phase": index * math.tau * 0.6180339 + rng.uniform(-0.2, 0.2),
            "radius": rng.uniform(2.9, 4.3),
            "height": rng.uniform(0.75, 2.3),
            "lift": (index / count) * 8.0 + rng.uniform(-0.4, 0.4),
            "bob": rng.uniform(0, math.tau),
            "spin": Vector((rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-2, 2))),
        })
    for template in (facet, cube, gem):
        template.hide_render = True
        template.hide_viewport = True
    return shards


def build_title(font, subtitle_font):
    mat, glow_node = text_material("Title | titanium with mint edges")
    title = text_object("Title BlendEngine", "BLEND\nENGINE", 1.02, font, mat, extrude=0.09, bevel=0.022,
                        spacing=1.06)
    subtitle_mat = showcase.emissive("Title | subtitle glow", MINT, 0.0)
    subtitle = text_object("Subtitle", "OPEN-SOURCE 3D  \u2022  BUILT ON BLENDER", 0.2, subtitle_font,
                           subtitle_mat, spacing=1.18)
    rule_mat = showcase.emissive("Title | rule glow", MINT, 0.0)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    rule = bpy.context.object
    rule.name = "Title underline"
    rule.dimensions = (3.6, 0.02, 0.025)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    rule.data.materials.append(rule_mat)
    # Dark backing plate keeps the thin subtitle legible over bright pillar strips.
    plate_mat = bpy.data.materials.new("Title | subtitle backing")
    plate_mat.diffuse_color = (0.008, 0.012, 0.016, 1)
    plate_mat.use_nodes = True
    plate_bsdf = plate_mat.node_tree.nodes.get("Principled BSDF")
    plate_bsdf.inputs["Base Color"].default_value = (0.008, 0.012, 0.016, 1)
    plate_bsdf.inputs["Roughness"].default_value = 0.55
    showcase.box("Subtitle backing plate", (0, 0, 0), (4.0, 0.02, 0.36), plate_mat, 0.0)
    plate = bpy.context.object
    return title, mat, glow_node, subtitle, subtitle_mat, rule, rule_mat, plate


def add_area(name, location, target, color, energy, size, size_y=None):
    return showcase.area(name, location, target, color, energy, size, size_y)


# ---------------------------------------------------------------------------
# Animation


CAMERA_POSES = (
    # time, azimuth (deg), elevation (deg), orbit radius, look-at height, lens (mm)
    (0.0, -72, -9, 5.6, 3.45, 30),
    (3.0, -38, -3, 4.1, 3.6, 30),
    (5.0, 55, 7, 4.7, 3.6, 28),
    (7.0, 158, 17, 6.2, 3.6, 26),
    (9.0, 214, 33, 9.6, 3.6, 22),
    (11.0, 252, 20, 10.6, 4.3, 26),
    (12.6, 266, 7, 10.0, 4.85, 31),
    (15.0, 271, 5, 9.4, 4.9, 32),
)


def camera_pose(t):
    poses = CAMERA_POSES
    if t <= poses[0][0]:
        return poses[0][1:]
    if t >= poses[-1][0]:
        return poses[-1][1:]
    index = max(i for i in range(len(poses) - 1) if poses[i][0] <= t)
    p0, p1 = poses[index], poses[index + 1]
    span = p1[0] - p0[0]

    def tangent(i, channel):
        before = poses[max(i - 1, 0)]
        after = poses[min(i + 1, len(poses) - 1)]
        if i == len(poses) - 1:
            return 0.0  # Come to rest on the final frame.
        return (after[channel] - before[channel]) / (after[0] - before[0])

    s = (t - p0[0]) / span
    return tuple(
        hermite(p0[c], tangent(index, c), p1[c], tangent(index + 1, c), s, span) for c in range(1, 6)
    )


def animate_camera(camera, focus):
    locations, rotations, lenses, focus_points = [], [], [], []
    previous = None
    for frame in range(1, FRAME_COUNT + 1):
        t = frame_time(frame)
        azimuth, elevation, radius, look_height, lens = camera_pose(t)
        az, el = math.radians(azimuth), math.radians(elevation)
        location = CENTER + radius * Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el),
                                             math.sin(el)))
        target = Vector((0.0, 0.0, look_height))
        if t >= DROP:  # Short impact shake.
            amount = 0.075 * math.exp(-(t - DROP) * 6.0)
            location += amount * Vector((math.sin(t * 97), math.cos(t * 83), math.sin(t * 71 + 1)))
            target += amount * 0.5 * Vector((math.cos(t * 61), 0, math.sin(t * 89)))
        quat = (target - location).to_track_quat("-Z", "Y")
        euler = quat.to_euler("XYZ", previous) if previous else quat.to_euler("XYZ")
        previous = euler
        locations.append(location)
        rotations.append(euler)
        lenses.append(lens)
        title_focus = Vector((0.0, -2.4, 6.6))
        focus_points.append(CENTER.lerp(title_focus, smoothstep(TITLE - 0.4, TITLE + 0.6, t)))
    bake_vector(camera, "location", locations)
    bake_vector(camera, "rotation_euler", rotations)
    bake(camera.data, "lens", lenses)
    bake_vector(focus, "location", focus_points)


def animate_gyroscope(gyro):
    pivot_a, pivot_b, pivot_c = gyro["pivots"]
    bake(pivot_a, "rotation_euler", locking_angles(0.55), 2)
    bake(pivot_b, "rotation_euler", locking_angles(-0.85), 0)
    bake(pivot_c, "rotation_euler", locking_angles(1.25), 2)

    def root_location(t):
        bob = 0.07 * math.sin(t * math.tau / 3.2)
        return (0.0, 0.0, CENTER.z + bob)

    bake_vector(gyro["root"], "location", sample(root_location))

    spin = [0.0]
    for frame in range(2, FRAME_COUNT + 1):
        t = frame_time(frame)
        spin.append(spin[-1] + 0.9 * speed_multiplier(t) / FPS)

    core_rot = [(0.25 * math.sin(frame_time(f) * 0.9), 0.18 * math.cos(frame_time(f) * 0.7), spin[f - 1])
                for f in range(1, FRAME_COUNT + 1)]
    bake_vector(gyro["core"], "rotation_euler", core_rot)
    bake_vector(gyro["cage"], "rotation_euler", [(r[1], -r[0], -r[2] * 0.6) for r in core_rot])

    def core_scale(t):
        punch = 0.0
        if t >= DROP:
            age = t - DROP
            punch = 0.32 * math.exp(-age * 4.0) * math.cos(age * 18.0)
        flare = 0.12 * math.exp(-max(0.0, t - CORE_FLARE) * 5.0) if t >= CORE_FLARE else 0.0
        size = 1.0 + punch + flare
        return (0.85 * size, 0.85 * size, 1.15 * size)

    bake_vector(gyro["core"], "scale", sample(core_scale))

    def cage_scale(t):
        grow = smoothstep(0.0, CORE_FLARE + 0.4, t)
        pulse = 0.1 * beats_since_drop(t)
        burst = 0.45 * math.exp(-(t - DROP) * 3.0) if t >= DROP else 0.0
        size = 0.65 + 0.35 * grow + pulse + burst
        return (size, size, size)

    bake_vector(gyro["cage"], "scale", sample(cage_scale))

    band_a, band_b, band_c = gyro["bands"]
    for mat, start, base in ((band_a, IGNITE[0], 9.0), (band_b, IGNITE[1], 11.0), (band_c, IGNITE[2], 10.0)):
        def band(t, start=start, base=base):
            lock_flash = 1.4 * math.exp(-(t - LOCK) * 5.0) if t >= LOCK else 0.0
            return base * (ignite(t, start) + 0.7 * beats_since_drop(t) + lock_flash)

        bake_input(mat, "Emission Strength", sample(band))

    def cage_strength(t):
        base = 2.0 + 7.0 * smoothstep(CORE_FLARE - 0.2, CORE_FLARE + 0.3, t)
        flare = 26.0 * math.exp(-(t - CORE_FLARE) * 4.0) if t >= CORE_FLARE else 0.0
        drop = 60.0 * math.exp(-(t - DROP) * 2.5) if t >= DROP else 0.0
        riser = 10.0 * smoothstep(RISER_START, DROP, t) if t < DROP else 0.0
        return base + flare + drop + riser + 6.0 * beats_since_drop(t)

    bake_input(gyro["cage_mat"], "Emission Strength", sample(cage_strength))

    def core_light(t):
        on = smoothstep(CORE_FLARE - 0.2, CORE_FLARE + 0.2, t)
        drop = 9000.0 * math.exp(-(t - DROP) * 2.2) if t >= DROP else 0.0
        return 550.0 * on + 1500.0 * smoothstep(RISER_START, DROP, t) * (t < DROP) + drop \
            + 700.0 * beats_since_drop(t)

    bake(gyro["core_light"].data, "energy", sample(core_light))

    def plinth(t):
        return 6.0 * ignite(t, 0.05, 1.8) + 10.0 * beats_since_drop(t)

    bake_input(gyro["plinth_glow"], "Emission Strength", sample(plinth))


def animate_hall(slabs, strips, floor_glow):
    wave_speed, width, height = 7.5, 0.85, 0.34
    for slab, distance in slabs:
        if distance > 13.0:
            continue
        values = []
        for frame in range(1, FRAME_COUNT + 1):
            t = frame_time(frame)
            z = 0.0
            if t >= DROP:
                front = (t - DROP) * wave_speed
                falloff = math.exp(-distance / 9.0)
                z = height * falloff * math.exp(-((distance - front) / width) ** 2)
                # A smaller echo ring on the downbeat two bars later.
                if t >= DROP + 2.0:
                    front2 = (t - DROP - 2.0) * wave_speed
                    z += 0.35 * height * falloff * math.exp(-((distance - front2) / width) ** 2)
            values.append(z)
        if max(values) > 0.004:
            bake(slab, "location", values, 2)

    for strip, angle in strips:
        # Light runs around the hall from the camera's side, then breathes on the beat.
        delay = 0.6 + 0.75 * ((angle - math.radians(250)) % math.tau) / math.tau

        def strength(t, delay=delay):
            return ignite(t, delay, 2.2) * (1.0 + 0.5 * beats_since_drop(t))

        bake_vector(strip, "color", [(strength(frame_time(f)), 0, 0, 1) for f in range(1, FRAME_COUNT + 1)], 4)

    def grout(t):
        return 0.25 + 0.6 * smoothstep(0.4, 1.4, t) + 2.4 * beats_since_drop(t) \
            + (8.0 * math.exp(-(t - DROP) * 3.0) if t >= DROP else 0.0)

    bake_input(floor_glow, "Emission Strength", sample(grout))


def animate_shards(shards):
    for shard in shards:
        obj = shard["obj"]
        locations, rotations, colors = [], [], []
        angle = shard["phase"]
        for frame in range(1, FRAME_COUNT + 1):
            t = frame_time(frame)
            angular = 0.28 + 0.5 * smoothstep(RISER_START, DROP, t)
            burst = 0.0
            lift = 0.0
            if t >= DROP:
                age = t - DROP
                burst = 2.4 * (1.0 - math.exp(-age * 3.2)) - 0.9 * smoothstep(1.5, 6.0, age)
                lift = shard["lift"] * smoothstep(0.0, 4.5, age)
                angular = 0.78 - 0.35 * smoothstep(2.0, 6.0, age) + 2.5 * math.exp(-age * 2.5)
            angle += angular / FPS
            radius = shard["radius"] + burst + 0.15 * math.sin(t * 1.3 + shard["bob"])
            z = shard["height"] + lift + 0.12 * math.sin(t * 2.1 + shard["bob"])
            locations.append(Vector((math.cos(angle) * radius, math.sin(angle) * radius, z)))
            rotations.append(shard["spin"] * t * (1.0 + 0.8 * smoothstep(RISER_START, DROP + 1, t)))
            if shard["glow"]:
                colors.append((ignite(t, CORE_FLARE + 0.1 * (shard["phase"] % 1.0), 2.0)
                               * (1.0 + 1.2 * beats_since_drop(t)), 0, 0, 1))
        bake_vector(obj, "location", locations)
        bake_vector(obj, "rotation_euler", rotations)
        if shard["glow"]:
            bake_vector(obj, "color", colors, 4)
        # Shards at title height dissolve into the reveal flash so the end card stays clean.
        settled = shard["height"] + shard["lift"]
        if settled > 4.6:
            base = Vector(obj.scale)
            delay = 0.25 * ((shard["phase"] / math.tau) % 1.0)
            bake_vector(obj, "scale", sample(
                lambda t: base * (1.0 - smoothstep(TITLE - 0.2 + delay, TITLE + 0.35 + delay, t))))


def animate_shockwave(ring_obj, mat):
    def scale(t):
        if t < DROP:
            return (0.01, 0.01, 0.01)
        size = 1.6 + 15.0 * (1.0 - math.exp(-(t - DROP) * 1.6))
        return (size, size, 1.0)

    bake_vector(ring_obj, "scale", sample(scale))

    def strength(t):
        if t < DROP:
            return 0.0
        return 45.0 * math.exp(-(t - DROP) * 2.2)

    bake_input(mat, "Emission Strength", sample(strength))


def animate_title(title, glow_node, title_mat, subtitle, subtitle_mat, rule, rule_mat, plate):
    start = CENTER + Vector((0, -0.5, 0))
    final = Vector((0.0, -2.4, 7.05))

    def location(t):
        x = smoothstep(TITLE, TITLE + 1.1, t)
        return start.lerp(final, x)

    def scale(t):
        size = 0.02 + 0.98 * ease_out_back((t - TITLE) / 1.0, 1.4) if t >= TITLE else 0.0
        return (size, size, size)

    bake_vector(title, "location", sample(location))
    bake_vector(title, "scale", sample(scale))
    bake_vector(title, "rotation_euler",
                sample(lambda t: (math.pi / 2 + 0.6 * (1.0 - smoothstep(TITLE, TITLE + 1.0, t)),
                                  0.0, -0.9 * (1.0 - smoothstep(TITLE, TITLE + 1.2, t)) ** 2)))
    node_path = glow_node.inputs[1].path_from_id("default_value")
    bake(title_mat.node_tree, node_path,
         sample(lambda t: 0.0 if t < TITLE else 5.0 + 30.0 * math.exp(-(t - TITLE - 0.6) ** 2 * 6.0)
                + 2.0 * beats_since_drop(t) * (t < LOCK)))

    sub_start = TITLE + 1.0
    subtitle_base = Vector((0.0, -2.5, 6.0))
    bake_vector(subtitle, "location", sample(
        lambda t: subtitle_base + Vector((0, 0, -0.18 * (1.0 - smoothstep(sub_start, sub_start + 0.6, t))))))
    bake_vector(subtitle, "scale", sample(lambda t: (1.0, 1.0, 1.0) if t >= sub_start - 0.05 else (0, 0, 0)))
    bake_input(subtitle_mat, "Emission Strength",
               sample(lambda t: 3.2 * smoothstep(sub_start, sub_start + 0.6, t)))

    plate.location = (0.0, -2.43, 6.0)
    bake_vector(plate, "scale", sample(
        lambda t: (smoothstep(sub_start - 0.3, sub_start + 0.3, t) + 1e-3, 1.0, 1.0)))
    rule.location = (0.0, -2.45, 6.25)
    bake_vector(rule, "scale", sample(
        lambda t: (smoothstep(TITLE + 0.7, TITLE + 1.4, t) + 1e-3, 1.0, 1.0)))
    bake_input(rule_mat, "Emission Strength",
               sample(lambda t: 8.0 * smoothstep(TITLE + 0.7, TITLE + 1.0, t)))


def build_scene(args):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    setup_render(scene, args)
    rng = random.Random(1920)

    mats = {
        "concrete": showcase.material("PBR | basalt concrete", (0.11, 0.135, 0.15), 0.78, texture_scale=7),
        "pale": showcase.material("PBR | cast limestone", (0.3, 0.29, 0.26), 0.66, texture_scale=8),
        "dark": showcase.material("PBR | anodized titanium", (0.065, 0.083, 0.10), 0.26, 0.8, 28),
        "copper": showcase.material("PBR | brushed copper", (0.52, 0.2, 0.075), 0.24, 0.85, 40),
        "floor": showcase.material("PBR | rain polished slate", (0.07, 0.088, 0.098), 0.16, 0.3, 42),
    }

    slabs, strips, floor_glow = build_hall(rng, mats)
    gyro = build_gyroscope(mats)
    shards = build_shards(rng, mats)

    shock_mat = showcase.emissive("Light | shockwave", MINT, 0.0)
    bpy.ops.mesh.primitive_torus_add(major_segments=192, minor_segments=10, major_radius=1.0,
                                     minor_radius=0.05, location=(0, 0, 0.2))
    shock = bpy.context.object
    shock.name = "Drop shockwave"
    shock.data.materials.append(shock_mat)

    font = find_font(args.font)
    title, title_mat, glow_node, subtitle, subtitle_mat, rule, rule_mat, plate = build_title(font, font)

    # Lighting: warm key from above, cool rims, a soft front fill and wall washes.
    add_area("Warm key", (1.5, -2.0, 9.0), (0, 0, 3.4), (1.0, 0.62, 0.34), 1500, 3.5)
    add_area("Cool rim left", (-5.5, 5.0, 6.5), (0, 0, 3.4), CYAN, 2200, 3.0)
    add_area("Cool rim right", (5.5, 5.5, 5.5), (0, 0, 3.4), (0.2, 0.7, 1.0), 1800, 3.0)
    add_area("Front fill", (0, -12, 5.5), (0, 0, 4), (0.42, 0.6, 0.78), 900, 8.0)
    add_area("Title face light", (0, -7.5, 8.5), (0, -2.4, 6.8), (0.85, 0.92, 1.0), 420, 3.0)
    for index in range(4):
        angle = index * math.tau / 4 + math.pi / 4
        add_area("Wall wash %d" % index, (math.cos(angle) * 6, math.sin(angle) * 6, 11),
                 (math.cos(angle) * 13, math.sin(angle) * 13, 4), (0.2, 0.75, 0.9), 2600, 5, 1.5)

    camera_data = bpy.data.cameras.new("Shorts camera")
    camera_data.sensor_fit = "VERTICAL"
    camera_data.sensor_height = 36.0
    camera_data.clip_start = 0.05
    camera_data.clip_end = 120
    camera = bpy.data.objects.new("Shorts camera", camera_data)
    scene.collection.objects.link(camera)
    focus = empty("Camera focus")
    camera_data.dof.use_dof = True
    camera_data.dof.focus_object = focus
    camera_data.dof.aperture_fstop = 3.5
    scene.camera = camera

    animate_camera(camera, focus)
    animate_gyroscope(gyro)
    animate_hall(slabs, strips, floor_glow)
    animate_shards(shards)
    animate_shockwave(shock, shock_mat)
    animate_title(title, glow_node, title_mat, subtitle, subtitle_mat, rule, rule_mat, plate)
    if args.budget == "software":
        apply_software_budget(scene)

    for screen in bpy.data.screens:
        for space_area in screen.areas:
            if space_area.type == "VIEW_3D":
                space_area.spaces.active.region_3d.view_perspective = "CAMERA"
                space_area.spaces.active.shading.type = "RENDERED"
                space_area.spaces.active.overlay.show_overlays = False

    scene.frame_set(1)
    scene["shorts_generator"] = "tools/blendengine/create_shorts_video.py"
    scene["shorts_assets"] = "Original procedural geometry, materials, animation and audio; no external assets"
    return scene


# ---------------------------------------------------------------------------
# Procedural soundtrack (numpy ships with Blender).


def write_soundtrack(path, seed=7):
    import numpy as np

    rate = 48000
    n = int(DURATION * rate)
    t = np.arange(n) / rate
    rng = np.random.default_rng(seed)
    mix = np.zeros((n, 2))

    def env(start, attack, decay, length=None):
        e = np.zeros(n)
        mask = t >= start
        age = t[mask] - start
        e[mask] = np.minimum(age / max(attack, 1e-4), 1.0) * np.exp(-np.maximum(age - attack, 0) / decay)
        if length is not None:
            e[t > start + length] *= np.exp(-(t[t > start + length] - start - length) * 12)
        return e

    def lowpass(signal, cutoff):
        """One-pole low pass; cutoff may be an array (sweeps)."""
        cutoff = np.broadcast_to(cutoff, signal.shape)
        alpha = 1.0 - np.exp(-2 * np.pi * cutoff / rate)
        out = np.empty_like(signal)
        acc = 0.0
        for i in range(len(signal)):
            acc += alpha[i] * (signal[i] - acc)
            out[i] = acc
        return out

    def saw(freq, phase=0.0):
        return 2.0 * ((t * freq + phase) % 1.0) - 1.0

    def place(signal, gain=1.0, pan=0.0):
        mix[:, 0] += signal * gain * math.cos((pan + 1) * math.pi / 4)
        mix[:, 1] += signal * gain * math.sin((pan + 1) * math.pi / 4)

    # Pad: A minor -> F major -> C major -> G, slowly filtered, swelling into the drop.
    chords = ((0.0, (110.0, 164.81, 220.0, 261.63)), (3.5, (87.31, 130.81, 174.61, 220.0)),
              (7.0, (130.81, 196.0, 261.63, 329.63)), (11.0, (98.0, 146.83, 196.0, 246.94)),
              (13.0, (110.0, 164.81, 220.0, 261.63)))
    pad = np.zeros(n)
    for index, (start, notes) in enumerate(chords):
        end = chords[index + 1][0] if index + 1 < len(chords) else DURATION
        window = np.clip((t - start) / 0.25, 0, 1) * np.clip((end + 0.25 - t) / 0.25, 0, 1)
        for note in notes:
            for detune in (-0.12, 0.0, 0.11):
                pad += window * saw(note * (1 + detune / 100 * 3), rng.random()) / 12
    cutoff = 300 + 1600 * np.clip((t - 0.5) / 6.5, 0, 1) ** 2 + 1400 * (t >= DROP) * np.exp(-(t - DROP).clip(0) * 0.5)
    pad = lowpass(pad, cutoff)
    pad_level = 0.22 + 0.2 * np.clip((t - 3) / 4, 0, 1)
    place(pad * pad_level * np.clip(t / 0.4, 0, 1) * np.clip((DURATION - t) / 1.2, 0, 1), 1.0)

    # Sub drone.
    place(np.sin(2 * np.pi * 55 * t) * 0.18 * np.clip(t / 1.0, 0, 1) * np.clip((DURATION - t) / 1.5, 0, 1))

    # Ignition ticks for each ring band, and the core flare.
    for index, start in enumerate(IGNITE):
        noise = rng.standard_normal(n)
        tick = noise * env(start, 0.001, 0.025) * 0.35
        blip = np.sin(2 * np.pi * (880 * 2 ** (index * 4 / 12)) * t) * env(start, 0.002, 0.12) * 0.22
        place(tick + blip, pan=(-0.6, 0.6, 0.0)[index])
    flare = np.sin(2 * np.pi * (220 + 660 * np.clip(t - CORE_FLARE, 0, 1)) * t) * env(CORE_FLARE, 0.01, 0.5)
    place(flare * 0.12)

    # Riser: filtered noise sweep plus a rising tone into the drop.
    riser_mask = (t >= RISER_START) & (t < DROP)
    progress = np.clip((t - RISER_START) / (DROP - RISER_START), 0, 1)
    noise = rng.standard_normal(n)
    sweep = noise - lowpass(noise, 200 + 6000 * progress ** 2)
    place(sweep * progress ** 2.2 * riser_mask * 0.35, pan=0.0)
    tone_freq = 110 * 2 ** (progress * 2)
    tone_phase = np.cumsum(tone_freq) / rate
    place(np.sin(2 * np.pi * tone_phase) * progress ** 2 * riser_mask * 0.16)

    # Drop impact: pitched boom, noise burst and a long tail.
    age = np.clip(t - DROP, 0, None)
    boom_freq = 38 + 90 * np.exp(-age * 9)
    boom = np.sin(2 * np.pi * np.cumsum(boom_freq) / rate) * env(DROP, 0.003, 1.1) * (t >= DROP)
    place(boom * 0.9)
    burst = lowpass(rng.standard_normal(n), 2500) * env(DROP, 0.002, 0.35)
    place(burst * 0.5, pan=-0.2)
    place(lowpass(rng.standard_normal(n), 1800) * env(DROP, 0.002, 0.35) * 0.5, pan=0.2)

    # Post-drop groove: kick on beats, hats off-beat, pulsing bass (stops for the lock).
    beat_times = np.arange(DROP + BEAT, LOCK - 0.01, BEAT)
    for beat in beat_times:
        k_age = np.clip(t - beat, 0, None)
        kick = np.sin(2 * np.pi * np.cumsum(45 + 110 * np.exp(-k_age * 30)) / rate) * env(beat, 0.002, 0.18)
        place(kick * 0.75)
        hat = rng.standard_normal(n) * env(beat + BEAT / 2, 0.001, 0.03)
        place((hat - lowpass(hat, 7000)) * 0.25, pan=0.35)
    bass_notes = (55.0, 55.0, 65.41, 49.0)
    bass = np.zeros(n)
    for index, start in enumerate(np.arange(DROP, LOCK - 0.01, BEAT / 2)):
        note = bass_notes[int((start - DROP) // 1.0) % len(bass_notes)]
        bass += saw(note) * env(start, 0.005, 0.16, BEAT / 2 - 0.02)
    place(lowpass(bass, 420) * 0.5)

    # Rings lock: three metallic clanks, then a bright shimmer for the title.
    for index, start in enumerate((LOCK - 0.12, LOCK - 0.05, LOCK)):
        clank = sum(np.sin(2 * np.pi * f * t) / (k + 1)
                    for k, f in enumerate((523.0 * 1.0, 523.0 * 2.76, 523.0 * 5.4, 523.0 * 8.93)))
        place(clank * env(start, 0.001, 0.25 + 0.3 * index) * 0.18, pan=(-0.4, 0.4, 0.0)[index])
    for index, note in enumerate((880.0, 1046.5, 1318.5, 1760.0, 2093.0)):
        start = TITLE + 0.08 * index
        bell = (np.sin(2 * np.pi * note * t) + 0.3 * np.sin(2 * np.pi * note * 2.01 * t)) * env(start, 0.004, 1.4)
        place(bell * 0.09, pan=-0.5 + index * 0.25)
    whoosh = rng.standard_normal(n)
    whoosh = lowpass(whoosh, 400 + 3000 * np.clip((t - TITLE + 0.6) / 0.6, 0, 1)) \
        * np.clip((t - TITLE + 0.6) / 0.6, 0, 1) * np.exp(-np.clip(t - TITLE, 0, None) * 4) * (t >= TITLE - 0.6)
    place(whoosh * 0.35)

    # Simple stereo reverb: convolve with decaying, decorrelated noise.
    tail = int(2.2 * rate)
    decay = np.exp(-np.arange(tail) / rate * 3.2)
    wet = np.zeros_like(mix)
    size = 1 << (n + tail).bit_length()
    for channel in range(2):
        impulse = rng.standard_normal(tail) * decay
        impulse /= np.sqrt(np.sum(impulse ** 2))
        spectrum = np.fft.rfft(mix[:, channel], size) * np.fft.rfft(impulse, size)
        wet[:, channel] = np.fft.irfft(spectrum, size)[:n]
    mix = mix + wet * 0.22

    # Master: fades, soft clip, normalise to -2 dBFS.
    mix *= np.clip(t / 0.03, 0, 1)[:, None] * np.clip((DURATION - t) / 0.6, 0, 1)[:, None]
    mix = np.tanh(mix * 1.3)
    mix *= 10 ** (-2 / 20) / np.max(np.abs(mix))  # Headroom for AAC true peak.
    data = (mix * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())
    return path


def encode(frames_dir, audio, output, size):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for --encode")
    command = [
        ffmpeg, "-y", "-loglevel", "error",
        "-framerate", str(FPS), "-i", str(frames_dir / "frame_%04d.png"),
        "-i", str(audio),
        # Lanczos upscale when frames were rendered below the delivery size.
        "-vf", "scale=%d:%d:flags=lanczos,unsharp=3:3:0.35" % size,
        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-level", "4.2", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
        str(output),
    ]
    subprocess.run(command, check=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--render", action="store_true", help="Render all frames to output-dir/frames")
    parser.add_argument("--encode", action="store_true", help="Write the soundtrack and mux an MP4")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--samples", type=int, default=0, help="EEVEE sample override (profile default otherwise)")
    parser.add_argument("--scale", type=int, default=100, help="Resolution percentage for previews")
    parser.add_argument("--stills", default="", help="Comma separated frames to render as preview stills")
    parser.add_argument("--frame-start", type=int, default=1)
    parser.add_argument("--frame-end", type=int, default=FRAME_COUNT)
    parser.add_argument("--font", default="", help="Font file for the title (Inter Bold if installed)")
    parser.add_argument("--video-size", default="1080x1920", help="Delivery size of the encoded MP4")
    parser.add_argument("--budget", choices=("cinematic", "software"), default="cinematic",
                        help="'software' trims ray/step counts for CPU-only (llvmpipe) rendering")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    args.output_dir.mkdir(parents=True, exist_ok=True)

    scene = build_scene(args)
    scene.render.resolution_percentage = args.scale
    bpy.ops.wm.save_as_mainfile(filepath=str((args.output_dir / "core_ignition_short.blend").resolve()))

    for still in filter(None, args.stills.split(",")):
        scene.frame_set(int(still))
        scene.render.filepath = str((args.output_dir / ("still_%04d.png" % int(still))).resolve())
        bpy.ops.render.render(write_still=True)

    frames_dir = args.output_dir / "frames"
    if args.render:
        frames_dir.mkdir(exist_ok=True)
        scene.frame_start, scene.frame_end = args.frame_start, args.frame_end
        scene.render.filepath = str(frames_dir.resolve()) + "/frame_"
        scene.render.use_overwrite = False  # Resume interrupted renders: finished frames are skipped.
        scene.render.use_placeholder = False  # A killed frame must not leave an empty file behind.
        bpy.ops.render.render(animation=True)

    if args.encode:
        audio = write_soundtrack(args.output_dir / "soundtrack.wav")
        size = tuple(int(v) for v in args.video_size.lower().split("x"))
        video = encode(frames_dir, audio, args.output_dir / "blendengine_short.mp4", size)
        print("BLENDENGINE_SHORT: " + str(video.resolve()))
    print("BLENDENGINE_SHORT_SCENE: " + str(args.output_dir.resolve()))


if __name__ == "__main__":
    main()
    if not bpy.app.binary_path:
        # Standalone bpy module: skip interpreter teardown, which can spin forever
        # in software OpenGL (Mesa llvmpipe) worker threads after a render.
        sys.stdout.flush()
        sys.stderr.flush()
        import os
        os._exit(0)
