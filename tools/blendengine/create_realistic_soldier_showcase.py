# SPDX-License-Identifier: GPL-2.0-or-later
"""Build 'Neon Quarantine HD': the soldier shooter at realistic quality.

The starter game (``startup.blend``) ships a heavily simplified city so it fits
the 1 GB / weak-PC budget. This tool keeps all of its gameplay (player,
SCAR rifle, zombies, pickups, rules) and upgrades the look for desktop PCs:

* the full-detail, textured city from ``builds/model_cache``. The model is a
  roughly 1:10 miniature of Times Square, so it is scaled up to human size
  and an intersection is placed where the fight happens (the starter game
  kept it at 1:1, which put the soldier on the rooftops). Textures are capped
  at ``--max-texture`` (4096 px by default, 2048 for mid-range GPUs);
* the soldier posed to aim a rifle and turned toward the zombies, and the
  first-person rifle moved into view;
* procedural PBR materials for the soldier, zombies, rifle, and arms;
* HDRI night sky, moonlight, neon key/rim lights, volumetric haze, bloom,
  soft shadows, reflections, and (legacy EEVEE) baked indirect light.

Run from the repository root with Blender 3.6 or newer::

    blender -b scripts/startup/bl_app_templates_system/BlendEngine/startup.blend \\
        --python tools/blendengine/create_realistic_soldier_showcase.py -- \\
        --output-dir /tmp/neon_quarantine_hd --render

Outputs ``NeonQuarantineHD.blend`` (playable with Play Mode) and, with
``--render``, ``fps.png``, ``third_person.png``, ``street.png``, and ``zombie.png`` rendered
with EEVEE, the engine's real-time renderer.
"""

import argparse
import math
import os
from pathlib import Path
import sys
import time

import bpy
from mathutils import Matrix, Vector


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CITY_GLB = REPOSITORY_ROOT / "builds" / "model_cache" / "cyberpunk-city" / "source" / "scene.glb"
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))


def ensure_engine():
    if not hasattr(bpy.types.Object, "blendengine_object"):
        import blendengine
        blendengine.register()
    from blendengine import optimization, performance, templates
    return optimization, performance, templates


# ---------------------------------------------------------------------------
# Materials.
# ---------------------------------------------------------------------------

def _srgb(hex_color):
    value = hex_color.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels) + (1.0,)


def world_matrix(obj):
    """World matrix computed from the parent chain.

    ``Object.matrix_world`` is not refreshed for objects hidden in the
    viewport (the first-person soldier body is), so it can hold a stale
    transform even after a view layer update."""
    matrix = obj.matrix_basis.copy()
    while obj.parent is not None:
        matrix = obj.matrix_parent_inverse @ matrix
        obj = obj.parent
        matrix = obj.matrix_basis @ matrix
    return matrix


def set_world_matrix(obj, matrix):
    """Inverse of ``world_matrix`` for an object that already has its parent."""
    if obj.parent is None:
        obj.matrix_basis = matrix
    else:
        obj.matrix_basis = (world_matrix(obj.parent) @ obj.matrix_parent_inverse).inverted() @ matrix


def _input(node, *names):
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    return None


def _noise(nodes, links, vector, scale, detail=4.0, roughness=0.55, distortion=0.0):
    node = nodes.new("ShaderNodeTexNoise")
    node.inputs["Scale"].default_value = scale
    node.inputs["Detail"].default_value = detail
    node.inputs["Roughness"].default_value = roughness
    if "Distortion" in node.inputs:
        node.inputs["Distortion"].default_value = distortion
    links.new(vector, node.inputs["Vector"])
    return node.outputs["Fac"]


def _mask(nodes, links, value, low, high):
    """Soft threshold: 0 below ``low``, 1 above ``high``."""
    node = nodes.new("ShaderNodeMapRange")
    node.inputs["From Min"].default_value = low
    node.inputs["From Max"].default_value = high
    node.clamp = True
    links.new(value, node.inputs["Value"])
    return node.outputs["Result"]


def _mix_color(nodes, links, factor, color_a, color_b):
    node = nodes.new("ShaderNodeMixRGB")
    if isinstance(factor, float):
        node.inputs["Fac"].default_value = factor
    else:
        links.new(factor, node.inputs["Fac"])
    for socket, color in ((node.inputs["Color1"], color_a), (node.inputs["Color2"], color_b)):
        if isinstance(color, tuple):
            socket.default_value = color
        else:
            links.new(color, socket)
    return node.outputs["Color"]


def _mix_value(nodes, links, factor, value_a, value_b):
    node = nodes.new("ShaderNodeMath")
    node.operation = "MULTIPLY_ADD"  # factor * (b - a) + a
    links.new(factor, node.inputs[0])
    node.inputs[1].default_value = value_b - value_a
    node.inputs[2].default_value = value_a
    return node.outputs["Value"]


def pbr(name, colors, roughness, metallic=0.0, pattern_scale=5.0, bump=0.2, micro=300.0, subsurface=0.0,
        emission=None, emission_strength=0.0, alpha=1.0, constant=False, dirt=0.0, blood=0.0, veins=0.0,
        wrinkles=0.0, blood_cover=0.0):
    """Layered procedural PBR material.

    Patterns use Generated coordinates (0..1 across each part), so they keep
    the same size whatever unit scale an imported model uses; the Sketchfab
    meshes here are stored at 1/40 scale, which made object-space noise
    collapse into a flat average. Layers: a palette (camo, mottled skin),
    optional dirt, wet blood, veins, and micro + wrinkle relief."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    vector = nodes.new("ShaderNodeTexCoord").outputs["Generated"]

    ramp = nodes.new("ShaderNodeValToRGB")
    if constant:
        ramp.color_ramp.interpolation = "CONSTANT"
    elements = ramp.color_ramp.elements
    while len(elements) < len(colors):
        elements.new(0.5)
    for index, color in enumerate(colors):
        elements[index].position = (index / max(1, len(colors) - 1)) * 0.8 + (0.1 if len(colors) > 1 else 0.0)
        elements[index].color = _srgb(color)
    links.new(_noise(nodes, links, vector, pattern_scale, detail=6.0), ramp.inputs["Fac"])
    color = ramp.outputs["Color"]
    rough = _mix_value(nodes, links, _noise(nodes, links, vector, pattern_scale * 5.0), roughness - 0.08, roughness + 0.08)

    if dirt > 0.0:
        grime = _mask(nodes, links, _noise(nodes, links, vector, 3.5, detail=8.0), 0.45, 0.75)
        amount = nodes.new("ShaderNodeMath")
        amount.operation = "MULTIPLY"
        links.new(grime, amount.inputs[0])
        amount.inputs[1].default_value = dirt
        color = _mix_color(nodes, links, amount.outputs["Value"], color, _srgb("#2f2a22"))
    if veins > 0.0:
        voronoi = nodes.new("ShaderNodeTexVoronoi")
        voronoi.feature = "DISTANCE_TO_EDGE"
        voronoi.inputs["Scale"].default_value = 28.0
        links.new(vector, voronoi.inputs["Vector"])
        lines = _mask(nodes, links, voronoi.outputs["Distance"], 0.03, 0.0)
        amount = nodes.new("ShaderNodeMath")
        amount.operation = "MULTIPLY"
        links.new(lines, amount.inputs[0])
        amount.inputs[1].default_value = veins
        color = _mix_color(nodes, links, amount.outputs["Value"], color, _srgb("#3b4a3e"))
    if blood > 0.0:
        low = 0.62 - blood_cover
        stains = _mask(nodes, links, _noise(nodes, links, vector, 6.0, detail=10.0, distortion=1.5), low, low + 0.06)
        amount = nodes.new("ShaderNodeMath")
        amount.operation = "MULTIPLY"
        links.new(stains, amount.inputs[0])
        amount.inputs[1].default_value = blood
        color = _mix_color(nodes, links, amount.outputs["Value"], color, _srgb("#3d0707"))
        # Fresh blood is glossy.
        wet = nodes.new("ShaderNodeMath")
        wet.operation = "MULTIPLY_ADD"
        links.new(amount.outputs["Value"], wet.inputs[0])
        wet.inputs[1].default_value = -0.5
        links.new(rough, wet.inputs[2])
        rough = wet.outputs["Value"]

    links.new(color, _input(bsdf, "Base Color"))
    links.new(rough, _input(bsdf, "Roughness"))
    _input(bsdf, "Metallic").default_value = metallic
    if subsurface > 0.0:
        sss = _input(bsdf, "Subsurface Weight", "Subsurface")
        if sss is not None:
            sss.default_value = subsurface
        radius = _input(bsdf, "Subsurface Radius")
        if radius is not None:
            radius.default_value = (0.9, 0.3, 0.2)
        sss_scale = _input(bsdf, "Subsurface Scale")
        if sss_scale is not None:
            sss_scale.default_value = 0.02

    height = _noise(nodes, links, vector, micro, detail=2.0)
    if wrinkles > 0.0:
        add = nodes.new("ShaderNodeMath")
        add.operation = "MULTIPLY_ADD"
        links.new(_noise(nodes, links, vector, 40.0, detail=6.0), add.inputs[0])
        add.inputs[1].default_value = wrinkles
        links.new(height, add.inputs[2])
        height = add.outputs["Value"]
    bump_node = nodes.new("ShaderNodeBump")
    bump_node.inputs["Strength"].default_value = bump
    bump_node.inputs["Distance"].default_value = 0.004
    links.new(height, bump_node.inputs["Height"])
    links.new(bump_node.outputs["Normal"], _input(bsdf, "Normal"))

    if emission is not None:
        _input(bsdf, "Emission Color", "Emission").default_value = _srgb(emission)
        _input(bsdf, "Emission Strength").default_value = emission_strength
    if alpha < 1.0:
        _input(bsdf, "Alpha").default_value = alpha
        mat.blend_method = "BLEND"
    return mat


def material_library():
    return {
        "camo": pbr("HD_Soldier_Camo", ("#8b7d5a", "#5b5a3a", "#6b4f35", "#3d4630"), 0.86, pattern_scale=6.0,
                    bump=0.25, micro=260.0, constant=True, dirt=0.25),
        "armor": pbr("HD_Soldier_Armor", ("#4f543e", "#454a37"), 0.52, pattern_scale=3.0, bump=0.12, micro=120.0,
                     dirt=0.3),
        "helmet": pbr("HD_Soldier_Helmet", ("#6e6650", "#5f5845"), 0.48, pattern_scale=3.0, bump=0.1, micro=150.0,
                      dirt=0.3),
        "canvas": pbr("HD_Soldier_Canvas", ("#7a6a4f", "#6a5c44"), 0.9, pattern_scale=9.0, bump=0.3, micro=400.0,
                      dirt=0.3),
        "gloves": pbr("HD_Soldier_Gloves", ("#1c1c1e", "#26262a"), 0.55, pattern_scale=12.0, bump=0.2),
        "mask": pbr("HD_Soldier_Mask", ("#1a1b1d", "#222327"), 0.85, pattern_scale=12.0, bump=0.3, micro=500.0),
        "skin": pbr("HD_Soldier_Skin", ("#c08a6b", "#a8735a"), 0.5, pattern_scale=20.0, bump=0.05, subsurface=0.15),
        "eyes": pbr("HD_Soldier_Eyes", ("#101012",), 0.05, bump=0.0),
        "plastic": pbr("HD_Black_Plastic", ("#141416", "#1c1c20"), 0.4, pattern_scale=10.0, bump=0.08),
        # Infected soldiers: grey-green decaying skin with bruises, veins, and blood.
        "zombie": pbr("HD_Zombie_Skin", ("#8d9a7c", "#76815f", "#5f5a48", "#4a3a3c"), 0.5, pattern_scale=7.0,
                      bump=0.45, micro=220.0, subsurface=0.1, veins=0.85, blood=1.0, wrinkles=1.0, dirt=0.45,
                      blood_cover=0.06),
        "zombie_cloth": pbr("HD_Zombie_Uniform", ("#5e5a46", "#45463a", "#544233", "#33382e"), 0.9, pattern_scale=6.0,
                            bump=0.3, micro=260.0, constant=True, dirt=0.7, blood=1.0, blood_cover=0.08),
        "zombie_gear": pbr("HD_Zombie_Gear", ("#3f4334", "#363a2e"), 0.6, pattern_scale=3.0, bump=0.15, micro=120.0,
                           dirt=0.8, blood=0.7),
        "zombie_eyes": pbr("HD_Zombie_Eyes", ("#d9d27a",), 0.1, bump=0.0, emission="#e8d65a", emission_strength=2.5),
        "receiver": pbr("HD_SCAR_Anodized", ("#1a1b1d", "#202226"), 0.36, metallic=0.85, pattern_scale=8.0,
                        bump=0.05, micro=400.0),
        "polymer": pbr("HD_SCAR_FDE_Polymer", ("#8a7556", "#7c6a4e"), 0.6, pattern_scale=6.0, bump=0.15, micro=350.0),
        "lens": pbr("HD_SCAR_Lens", ("#0a1a24",), 0.03, metallic=1.0, bump=0.0),
        "med": pbr("HD_Pickup_Med", ("#1fe07a",), 0.2, bump=0.0, emission="#1fe07a", emission_strength=4.0, alpha=0.6),
        "ammo": pbr("HD_Pickup_Ammo", ("#ffb02e",), 0.2, bump=0.0, emission="#ffb02e", emission_strength=4.0, alpha=0.6),
        "exit": pbr("HD_Pickup_Exit", ("#2ee6ff",), 0.2, bump=0.0, emission="#2ee6ff", emission_strength=5.0, alpha=0.6),
    }


SOLDIER_PARTS = (
    (("Body", "Legs_", "Corset", "Unsershoulder"), "camo"),
    (("Helmet",), "helmet"),
    (("Plate", "plate", "Shoulderpads", "Elbowpads", "Legarmor", "Bootarmor", "Eggarmor", "Glovearmor"), "armor"),
    (("Backpack", "Pouches", "Backpad"), "canvas"),
    (("Gloves",), "gloves"),
    (("Facemask",), "mask"),
    (("Head",), "skin"),
    (("Eyes",), "eyes"),
    (("Headset", "Radio", "Cable"), "plastic"),
)


def _assign(obj, material):
    if obj.type != "MESH":
        return
    obj.data.materials.clear()
    obj.data.materials.append(material)


def upgrade_characters(scene, lib):
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        name = obj.name
        if name.startswith("BE_PlayerSoldierVisual"):
            part = obj.parent.name if obj.parent else name
            for keys, key in SOLDIER_PARTS:
                if any(k in part for k in keys):
                    _assign(obj, lib[key])
                    break
        elif name.startswith("BE_SCAR"):
            if "Glass" in name:
                _assign(obj, lib["lens"])
            elif any(k in name for k in ("priklad", "ruchka", "modul")):
                _assign(obj, lib["polymer"])
            else:
                _assign(obj, lib["receiver"])
        elif name.startswith(("BE_MED_Pickup", "BE_AMMO_Pickup", "BE_EXIT_Pickup")):
            # Game items read as glowing holograms instead of plain boxes.
            _assign(obj, lib[name[3:].split("_")[0].lower()])
            obj.display_type = "TEXTURED"
            obj["blendengine_visible_trigger"] = True
        elif name.startswith("BE_FP_Arm"):
            # Placeholder cylinders; the HD view model shows the rifle only.
            obj.hide_render = True
            obj.hide_viewport = True


# Gear an infected soldier keeps; the rest of the kit was lost or torn off.
INFECTED_DROP = ("Helmet", "Facemask", "Headset", "Radio", "Cable", "Backpack", "Backpad")
INFECTED_PARTS = (
    (("Head",), "zombie"),
    (("Eyes",), "zombie_eyes"),
    (("Body", "Legs_", "Corset", "Unsershoulder"), "zombie_cloth"),
    (("Gloves",), "zombie"),
)


def _soldier_parts(root):
    rifle = bpy.data.objects.get("BE_PlayerSoldierVisual_Rifle")
    skip = set(rifle.children_recursive) if rifle is not None else set()
    return [obj for obj in root.children_recursive if obj.type == "MESH" and obj not in skip]


def _zombie_roots(scene):
    return sorted((obj for obj in scene.objects
                   if obj.name.startswith("BE_Zombie_") and obj.type == "EMPTY" and obj.parent is None),
                  key=lambda obj: obj.name)


def _replace_zombie_body(zombie_root, sources, model_front_minus_y=True, scale=1.0, source_space=None,
                         material_for=None):
    """Hide the zombie's old meshes and parent new copies of ``sources``.

    The runtime turns NPC roots so their local +Y faces the target; a model
    whose front is -Y (the glTF convention) is turned by 180 degrees."""
    for child in zombie_root.children_recursive:
        if child.type == "MESH":
            child.hide_render = True
            child.hide_viewport = True
            child.blendengine_object.object_tag = "ZombieLegacyMesh"
    bpy.context.view_layer.update()
    holder = bpy.data.objects.new(zombie_root.name + "_Body", None)
    for collection in zombie_root.users_collection:
        collection.objects.link(holder)
    holder.parent = zombie_root
    root_world = world_matrix(zombie_root)
    feet = root_world.translation.copy()
    feet.z = 0.0
    yaw = root_world.to_euler().z + (math.pi if model_front_minus_y else 0.0)
    set_world_matrix(holder, Matrix.Translation(feet) @ Matrix.Rotation(yaw, 4, "Z") @ Matrix.Scale(scale, 4))
    to_source = source_space.inverted() if source_space is not None else Matrix.Identity(4)
    bpy.context.view_layer.update()
    for source in sources:
        copy = source.copy()
        copy.data = source.data  # shared mesh, per-object materials
        for collection in zombie_root.users_collection:
            collection.objects.link(copy)
        copy.parent = holder
        copy.matrix_parent_inverse.identity()
        copy.matrix_basis = to_source @ world_matrix(source)
        copy.hide_render = False
        copy.hide_viewport = False
        copy.blendengine_object.object_tag = "Zombie"
        if material_for is not None:
            material = material_for(source)
            if material is not None:
                for slot in copy.material_slots:
                    slot.link = "OBJECT"
                    slot.material = material
    return holder


def build_infected_soldiers(scene, lib, seed=7):
    """Zombies rebuilt from the intact soldier model.

    The zombie mesh in startup.blend was decimated so hard for the 1 GB
    profile that its skin and clothing shells broke into intersecting
    shards, and its texture was stripped; the original file is not in the
    repository. Use ``--zombie-model`` to bring back an original model."""
    import random
    rng = random.Random(seed)
    soldier = bpy.data.objects.get("BE_PlayerSoldierVisual_Root")
    if soldier is None:
        return 0
    bpy.context.view_layer.update()
    parts = _soldier_parts(soldier)
    count = 0
    for zombie_root in _zombie_roots(scene):
        kept = []
        for part in parts:
            name = part.parent.name if part.parent else part.name
            if any(key in name for key in INFECTED_DROP):
                continue
            # Some armor pieces were ripped off: every zombie looks different.
            if any(key in name for key in ("plate", "Plate", "pads", "armor", "Pouches")) and rng.random() < 0.35:
                continue
            kept.append(part)

        def material_for(part):
            name = part.parent.name if part.parent else part.name
            for keys, key in INFECTED_PARTS:
                if any(k in name for k in keys):
                    return lib[key]
            return lib["zombie_gear"]

        # The soldier model faces -Y in its own space, like glTF models.
        _replace_zombie_body(zombie_root, kept, model_front_minus_y=True,
                             source_space=world_matrix(soldier), material_for=material_for)
        count += 1
    return count


def import_zombie_model(scene, path, height=1.75, faces_plus_y=False):
    """Use an original zombie .glb (for example sexy_zombie_girl.glb from the
    starter's MODELS folder) instead of the infected soldiers."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    imported = [obj for obj in bpy.data.objects if obj not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    bpy.context.view_layer.update()
    points = [world_matrix(obj) @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = min(p.z for p in points)
    model_height = max(p.z for p in points) - low
    center = Vector(((min(p.x for p in points) + max(p.x for p in points)) * 0.5,
                     (min(p.y for p in points) + max(p.y for p in points)) * 0.5, low))
    space = Matrix.Translation(center)
    for obj in meshes:
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
    for zombie_root in _zombie_roots(scene):
        _replace_zombie_body(zombie_root, meshes, model_front_minus_y=not faces_plus_y,
                             scale=height / max(model_height, 1e-3), source_space=space)
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    return len(meshes)


# ---------------------------------------------------------------------------
# City.
# ---------------------------------------------------------------------------

# A road intersection in the model's own coordinates (found from a top view).
CITY_INTERSECTION = Vector((2.0, 0.16, 0.0))


def replace_city(scene, templates, max_texture, scale):
    old = bpy.data.collections.get("BE_CyberpunkCity")
    if old is not None:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old)
    for obj in list(scene.objects):
        if obj.name.startswith(("BE_Wet_Road_Reflection", "BE_Neon_Crosswalk", "BE_Neon_Road_Line", "BE_Sign_")):
            # Set dressing sized for the miniature city; the HD city has its
            # own textured roads, markings, and storefront signs.
            obj.hide_render = True
            obj.hide_viewport = True
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for item in list(block):
            if item.users == 0:
                block.remove(item)

    before_objects = set(bpy.data.objects)
    before_images = set(bpy.data.images)
    bpy.ops.import_scene.gltf(filepath=str(CITY_GLB))
    imported = [obj for obj in bpy.data.objects if obj not in before_objects]
    collection = bpy.data.collections.new("BE_CityHD")
    scene.collection.children.link(collection)
    root = bpy.data.objects.new("BE_CityHD_Root", None)
    collection.objects.link(root)
    for obj in imported:
        for owner in list(obj.users_collection):
            owner.objects.unlink(obj)
        collection.objects.link(obj)
        obj.name = "BE_CityHD_" + obj.name
        if obj.parent is None:
            obj.parent = root
    # Scale the miniature to human size around the chosen intersection,
    # then drop it so the road surface sits at the gameplay floor (z = 0).
    root.scale = (scale, scale, scale)
    root.location = -CITY_INTERSECTION * scale
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    hit, location, _normal, _index, _obj, _matrix = scene.ray_cast(
        depsgraph, Vector((0.0, 0.0, 50.0 * scale)), Vector((0.0, 0.0, -1.0)))
    if hit:
        root.location.z -= location.z
    templates._mark_imported_meshes(imported, "City", static=True)

    for image in bpy.data.images:
        if image in before_images or not image.size[0]:
            continue
        width, height = image.size
        largest = max(width, height)
        if largest > max_texture:
            factor = max_texture / largest
            image.scale(max(1, int(width * factor)), max(1, int(height * factor)))
        image.pack()
    return imported


# ---------------------------------------------------------------------------
# Soldier pose and view model.
# ---------------------------------------------------------------------------

def _smoothstep(edge0, edge1, value):
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def pose_soldier(scene):
    """Turn the T-posed soldier toward the zombies and swing both arms
    forward into a rifle-ready stance (the model has no skeleton). Like
    glTF models, it faces -Y in its own space (facemask and breastplate
    sit on the -Y side of the head and torso)."""
    root = bpy.data.objects.get("BE_PlayerSoldierVisual_Root")
    if root is None or root.get("hd_posed"):
        return None
    meshes = [obj for obj in root.children_recursive if obj.type == "MESH"]
    shoulder_x, shoulder_z = 0.2, 1.45
    to_root = world_matrix(root).inverted()
    for obj in meshes:
        world = to_root @ world_matrix(obj)
        inverse = world.inverted()
        mesh = obj.data
        if mesh.users > 1:
            obj.data = mesh = mesh.copy()
        for vertex in mesh.vertices:
            local = world @ vertex.co
            side = 1.0 if local.x > 0.0 else -1.0
            weight = _smoothstep(shoulder_x, shoulder_x + 0.16, abs(local.x))
            if weight <= 0.0 or local.z < 1.0:
                continue
            pivot = Vector((side * shoulder_x, 0.0, shoulder_z))
            offset = local - pivot
            # Lower the arm, then swing it toward -Y (the model's front).
            down = Matrix.Rotation(side * math.radians(28.0) * weight, 3, "Y")
            forward = Matrix.Rotation(side * math.radians(-78.0) * weight, 3, "Z")
            inward = Matrix.Rotation(side * math.radians(-14.0) * weight, 3, "Z")
            offset = inward @ forward @ down @ offset
            vertex.co = inverse @ (pivot + offset)
        mesh.update()
    root.rotation_euler.z = math.pi
    root["hd_posed"] = True

    # Give the soldier a rifle: linked copies of the first-person SCAR meshes.
    holder = bpy.data.objects.new("BE_PlayerSoldierVisual_Rifle", None)
    for collection in root.users_collection:
        collection.objects.link(holder)
    holder.parent = root
    holder.location = (0.06, -0.42, 1.24)
    camera, parts = _view_model_parts()
    if parts:
        to_camera = world_matrix(camera).inverted()
        center = _parts_center(camera, parts)
        # Camera space (-Z forward, +Y up) -> soldier space (-Y forward, +Z up).
        orient = Matrix.Rotation(math.pi, 4, "Z") @ Matrix.Rotation(math.pi / 2.0, 4, "X")
        for obj in parts:
            copy = obj.copy()
            for collection in holder.users_collection:
                collection.objects.link(copy)
            copy.parent = holder
            copy.matrix_parent_inverse.identity()
            copy.matrix_basis = orient @ Matrix.Translation(-center) @ to_camera @ world_matrix(obj)
            copy.blendengine_object.object_tag = "PlayerBody"
    return root


def _view_model_parts():
    camera = bpy.data.objects.get("BE_FPS_Camera")
    if camera is None:
        return None, []
    parts = [obj for obj in camera.children_recursive
             if obj.type == "MESH" and obj.blendengine_object.object_tag == "Weapon"]
    return camera, parts


def _parts_center(camera, parts):
    to_camera = world_matrix(camera).inverted()
    points = [to_camera @ (world_matrix(obj) @ Vector(corner)) for obj in parts for corner in obj.bound_box]
    return Vector(tuple((min(p[i] for p in points) + max(p[i] for p in points)) * 0.5 for i in range(3)))


def face_zombies_forward(scene):
    """The zombie model looks down -Y, while the runtime turns NPCs so +Y
    points at their target, which made them walk at the player backwards.
    Turn the model inside its root and the root back: same look in the
    editor, correct facing in Play Mode."""
    for root in scene.objects:
        if not (root.name.startswith("BE_Zombie_") and root.type == "EMPTY" and root.parent is None):
            continue
        if root.get("hd_faced"):
            continue
        # Imported children use quaternion rotation, so turn them by matrix
        # about the root's origin instead of editing rotation_euler.
        bpy.context.view_layer.update()
        root_world = world_matrix(root)
        turn = root_world @ Matrix.Rotation(math.pi, 4, "Z") @ root_world.inverted()
        for child in root.children:
            set_world_matrix(child, turn @ world_matrix(child))
        root.rotation_euler.z += math.pi
        root["hd_faced"] = True


def high_end_budget(scene):
    """Budget for desktop PCs with a dedicated GPU (the default targets 1 GB devices)."""
    budget = scene.blendengine_performance_budget
    budget.max_triangles_visible = 2500000
    budget.max_texture_memory_mb = 1024
    budget.max_dynamic_lights = 8
    budget.max_shadow_casters = 4
    optimization = scene.blendengine_optimization
    optimization.one_gb_ram_mode = False
    # The HD city is ~300 m long: stream far enough that the skyline never pops.
    optimization.world_cell_size = 60.0
    optimization.visible_cell_radius = 3
    optimization.max_visible_objects = 1000


def place_view_model():
    """Move the first-person rifle up into the lower right of the screen.

    The starter rig parents every rifle part straight to the camera and
    leaves it below the visible frame, so the parts are shifted together."""
    bpy.context.view_layer.update()
    camera, parts = _view_model_parts()
    if not parts:
        return
    center = _parts_center(camera, parts)
    target = Vector((0.15, -0.2, -0.5))
    # The starter rig holds the rifle upside down: roll it upright, then turn
    # the barrel slightly toward the screen center so its side shows.
    shift = (Matrix.Translation(target) @ Matrix.Rotation(math.radians(9.0), 4, "Y")
             @ Matrix.Rotation(math.pi, 4, "Z") @ Matrix.Translation(-center))
    for obj in parts:
        if obj.parent == camera:
            camera_world = world_matrix(camera)
            set_world_matrix(obj, camera_world @ shift @ camera_world.inverted() @ world_matrix(obj))


# ---------------------------------------------------------------------------
# Light and render settings.
# ---------------------------------------------------------------------------

def _studio_hdri(name):
    folder = bpy.utils.system_resource("DATAFILES", path="studiolights/world")
    path = os.path.join(folder, name) if folder else ""
    return path if path and os.path.exists(path) else ""


def setup_lighting(scene, haze):
    world = scene.world or bpy.data.worlds.new("HD_World")
    scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = 0.55
    hdri = _studio_hdri("night.exr") or _studio_hdri("city.exr")
    if hdri:
        environment = nodes.new("ShaderNodeTexEnvironment")
        environment.image = bpy.data.images.load(hdri, check_existing=True)
        links.new(environment.outputs["Color"], background.inputs["Color"])
    else:
        background.inputs["Color"].default_value = (0.012, 0.018, 0.035, 1.0)
    links.new(background.outputs["Background"], output.inputs["Surface"])
    if haze > 0.0:
        scatter = nodes.new("ShaderNodeVolumeScatter")
        scatter.inputs["Density"].default_value = haze
        scatter.inputs["Anisotropy"].default_value = 0.35
        links.new(scatter.outputs["Volume"], output.inputs["Volume"])

    moon = bpy.data.objects.get("BE_Moon_Sun")
    if moon is not None and moon.type == "LIGHT":
        moon.data.energy = 1.2
        moon.data.color = (0.62, 0.72, 1.0)
        moon.rotation_euler = (math.radians(52.0), 0.0, math.radians(-38.0))
        if hasattr(moon.data, "angle"):
            moon.data.angle = math.radians(1.5)

    def area(name, location, target, color, energy, size):
        data = bpy.data.lights.get(name) or bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.color = color
        data.size = size
        obj = bpy.data.objects.get(name) or bpy.data.objects.new(name, data)
        if obj.name not in scene.collection.objects:
            scene.collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler = (Vector(target) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
        return obj

    # Neon key and rim lights sell the street: magenta signage left, cyan right.
    area("HD_Neon_Key_Magenta", (-4.5, -1.0, 4.5), (0.0, 1.0, 0.8), (1.0, 0.18, 0.55), 520.0, 3.0)
    area("HD_Neon_Rim_Cyan", (4.0, 3.5, 3.5), (0.0, -3.0, 1.2), (0.15, 0.75, 1.0), 420.0, 2.5)
    area("HD_Street_Fill", (0.0, -10.0, 6.0), (0.0, 0.0, 0.5), (0.55, 0.65, 1.0), 220.0, 8.0)


def configure_render(scene, optimization, samples):
    optimization.apply_preset(scene, "CINEMATIC")
    eevee = scene.eevee
    for name, value in (
        ("taa_render_samples", samples),
        ("use_gtao", True), ("gtao_distance", 1.2),
        ("use_bloom", True), ("bloom_intensity", 0.06), ("bloom_threshold", 0.9),
        ("use_ssr", True), ("use_ssr_halfres", False), ("ssr_quality", 0.75),
        ("use_soft_shadows", True), ("shadow_cube_size", "2048"), ("shadow_cascade_size", "4096"),
        ("use_volumetric_lights", True), ("use_volumetric_shadows", True), ("volumetric_tile_size", "4"),
        ("volumetric_end", 160.0), ("use_shadows", True), ("use_raytracing", True),
    ):
        if hasattr(eevee, name):
            try:
                setattr(eevee, name, value)
            except (TypeError, ValueError):
                pass
    view = scene.view_settings
    for transform in ("AgX", "Filmic"):
        try:
            view.view_transform = transform
            break
        except TypeError:
            continue
    for look in ("AgX - Medium High Contrast", "Medium High Contrast", "Filmic - Medium High Contrast"):
        try:
            view.look = look
            break
        except TypeError:
            continue
    view.exposure = 0.15
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100


def bake_indirect_light(scene):
    """Legacy EEVEE only: bake bounced neon light into an irradiance volume."""
    if scene.render.engine != "BLENDER_EEVEE" or not hasattr(bpy.ops.scene, "light_cache_bake"):
        return False
    probe_data = bpy.data.lightprobes.new("HD_Irradiance", "GRID")
    for name, value in (("grid_resolution_x", 8), ("grid_resolution_y", 6), ("grid_resolution_z", 3)):
        setattr(probe_data, name, value)
    probe = bpy.data.objects.new("HD_Irradiance", probe_data)
    scene.collection.objects.link(probe)
    probe.location = (0.0, 0.0, 4.0)
    probe.scale = (16.0, 12.0, 4.0)
    cube_data = None
    for probe_type in ("CUBE", "SPHERE", "CUBEMAP"):  # renamed across Blender versions
        try:
            cube_data = bpy.data.lightprobes.new("HD_Reflections", probe_type)
            break
        except TypeError:
            continue
    cube = bpy.data.objects.new("HD_Reflections", cube_data)
    scene.collection.objects.link(cube)
    cube.location = (0.0, -1.0, 2.0)
    if hasattr(cube_data, "influence_distance"):
        cube_data.influence_distance = 25.0
    scene.eevee.gi_diffuse_bounces = 2
    scene.eevee.gi_cubemap_resolution = "512"
    started = time.time()
    bpy.ops.scene.light_cache_bake()
    print("[showcase] baked indirect light in %.0fs" % (time.time() - started))
    return True


# ---------------------------------------------------------------------------
# Shots.
# ---------------------------------------------------------------------------

def _set_tag_render(scene, tags, hidden):
    for obj in scene.objects:
        if obj.blendengine_object.object_tag in tags:
            obj.hide_render = hidden


def _camera(scene, name, location, target, lens, focus=None, fstop=4.0):
    data = bpy.data.cameras.get(name) or bpy.data.cameras.new(name)
    data.lens = lens
    data.clip_end = 300.0
    obj = bpy.data.objects.get(name) or bpy.data.objects.new(name, data)
    if obj.name not in scene.collection.objects:
        scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (Vector(target) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
    data.dof.use_dof = focus is not None
    if focus is not None:
        data.dof.focus_distance = focus
        data.dof.aperture_fstop = fstop
    return obj


def render_shots(scene, output_dir):
    game_camera = scene.camera or bpy.data.objects.get("BE_FPS_Camera")
    shots = []

    # 1. What the player sees: first person, rifle in hand, zombies ahead.
    fps = bpy.data.objects["BE_FPS_Camera"]
    fps.rotation_euler = (math.radians(91.0), 0.0, math.radians(-4.0))
    fps.data.lens = 26
    _set_tag_render(scene, {"PlayerBody"}, True)
    _set_tag_render(scene, {"Weapon"}, False)
    shots.append(("fps", fps))
    for name, camera in shots:
        scene.camera = camera
        scene.render.filepath = os.path.join(output_dir, name + ".png")
        bpy.ops.render.render(write_still=True)
    shots.clear()

    # 2. Third person over-the-shoulder and 3. a wide street shot.
    _set_tag_render(scene, {"PlayerBody"}, False)
    _set_tag_render(scene, {"Weapon", "FirstPersonArms"}, True)
    for obj in scene.objects:
        if obj.name.startswith("BE_Player_FirstPersonBody"):
            obj.hide_render = True
    third = _camera(scene, "HD_Shot_ThirdPerson", (1.55, -7.9, 1.7), (-0.2, 2.0, 1.25), 35, focus=3.3, fstop=4.0)
    street = _camera(scene, "HD_Shot_Street", (-5.0, -12.5, 1.9), (1.5, 3.0, 3.6), 22)
    zombie = bpy.data.objects.get("BE_Zombie_01")
    spot = world_matrix(zombie).translation if zombie else Vector((0.0, 1.8, 0.0))
    target = (spot.x, spot.y, 1.3)
    closeup = _camera(scene, "HD_Shot_Zombie", (target[0] + 0.9, target[1] - 2.6, 1.55), target, 50,
                      focus=2.75, fstop=2.8)
    for name, camera in (("third_person", third), ("street", street), ("zombie", closeup)):
        started = time.time()
        scene.camera = camera
        scene.render.filepath = os.path.join(output_dir, name + ".png")
        bpy.ops.render.render(write_still=True)
        print("[showcase] rendered %s in %.0fs" % (name, time.time() - started))
    _set_tag_render(scene, {"Weapon"}, False)
    scene.camera = game_camera


def main():
    parser = argparse.ArgumentParser(description="Build Neon Quarantine HD.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--max-texture", type=int, default=4096)
    parser.add_argument("--city-scale", type=float, default=10.0)
    parser.add_argument("--haze", type=float, default=0.012, help="World volume density; 0 disables it")
    parser.add_argument("--no-bake", action="store_true")
    parser.add_argument("--zombie-model", help="Original zombie .glb to use instead of infected soldiers")
    parser.add_argument("--zombie-faces-plus-y", action="store_true",
                        help="Set if zombies from --zombie-model walk backwards (model not in glTF orientation)")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    optimization, performance, templates = ensure_engine()
    os.makedirs(args.output_dir, exist_ok=True)
    scene = bpy.context.scene
    if bpy.data.objects.get("BE_FPS_Camera") is None:
        raise SystemExit("Open the BlendEngine startup.blend (Neon Quarantine) first.")
    if not CITY_GLB.exists():
        raise SystemExit("Missing %s" % CITY_GLB)

    scene.blendengine_project.game_title = "Neon Quarantine HD"
    scene.blendengine_export.package_name = "NeonQuarantineHD"
    started = time.time()
    replace_city(scene, templates, args.max_texture, args.city_scale)
    lib = material_library()
    upgrade_characters(scene, lib)
    place_view_model()
    pose_soldier(scene)
    face_zombies_forward(scene)
    if args.zombie_model:
        print("[showcase] zombies from %s: %d meshes" % (args.zombie_model, import_zombie_model(
            scene, args.zombie_model, faces_plus_y=args.zombie_faces_plus_y)))
    else:
        print("[showcase] infected soldiers: %d" % build_infected_soldiers(scene, lib))
    setup_lighting(scene, args.haze)
    configure_render(scene, optimization, args.samples)
    if not args.no_bake:
        bake_indirect_light(scene)
    print("[showcase] scene built in %.0fs" % (time.time() - started))

    metrics = performance.estimate_scene(scene)
    print("[showcase] triangles %d, draw calls ~%d, texture memory ~%.0f MB, lights %d" % (
        metrics["triangle_count"], metrics["draw_calls_estimated"], metrics["texture_memory_mb"],
        sum(1 for obj in scene.objects if obj.type == "LIGHT")))

    if args.render:
        render_shots(scene, args.output_dir)

    # The saved game uses the High profile: Cinematic is for screenshots.
    optimization.apply_preset(scene, "HIGH")
    high_end_budget(scene)
    scene.camera = bpy.data.objects["BE_FPS_Camera"]
    blend_path = os.path.join(args.output_dir, "NeonQuarantineHD.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)
    print("[showcase] saved", blend_path)


if __name__ == "__main__":
    main()
