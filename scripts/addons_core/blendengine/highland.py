# SPDX-License-Identifier: GPL-2.0-or-later
#
# "Highland Patrol": an original first-person outdoor shooter starter.
#
# A sunlit mountain valley with a rocky outcrop, conifers, grass, a hand-held
# rifle and patrolling enemies. Everything is generated here from code: the
# terrain is a noise heightfield, rocks are displaced spheres, trees and grass
# are small shared meshes placed many times. No model or texture files.
#
# The level is built for the engine's own runtime: the terrain carries the
# "Ground" tag the player walks on, enemies use the Enemy tag the weapon ray
# cast looks for, and repeated props share mesh data so EEVEE draws them as
# instances.

import math

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

from . import cinematic, components, graphics, input_system, optimization, utils


TERRAIN_SIZE = 180.0
TERRAIN_CELLS = 144
SPAWN = (0.0, -34.0)
PREFIX = "BE_Highland_"


# ---------------------------------------------------------------------------
# Height field

_NOISE_TABLES = {}


def _value_noise(x, y, seed):
    """Smooth 2D value noise in [-1, 1] for numpy arrays."""
    table = _NOISE_TABLES.get(seed)
    if table is None:
        table = _NOISE_TABLES[seed] = np.random.default_rng(seed).random((256, 256)) * 2.0 - 1.0
    x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    fx, fy = x - x0, y - y0
    fx, fy = fx * fx * (3.0 - 2.0 * fx), fy * fy * (3.0 - 2.0 * fy)
    a = table[x0 % 256, y0 % 256]
    b = table[(x0 + 1) % 256, y0 % 256]
    c = table[x0 % 256, (y0 + 1) % 256]
    d = table[(x0 + 1) % 256, (y0 + 1) % 256]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def terrain_height(x, y):
    """Height of the valley at world (x, y); accepts numpy arrays."""
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    rolling = (_value_noise(x / 38.0, y / 38.0, 3) * 4.2
               + _value_noise(x / 14.0, y / 14.0, 5) * 1.3
               + _value_noise(x / 4.5, y / 4.5, 7) * 0.28)
    # A long hillside climbs to the east, a lower rocky shoulder to the west.
    east = np.clip(x - 6.0, 0.0, None)
    west = np.clip(-x - 9.0, 0.0, None)
    slopes = 0.011 * east ** 1.75 + 0.02 * west ** 1.5
    # The trail the player starts on winds north along the valley floor.
    trail_x = 3.0 * np.sin(y / 17.0)
    valley = np.exp(-((x - trail_x) / 9.0) ** 2)
    return (rolling + slopes) * (1.0 - 0.72 * valley) - 0.4 * valley


class HeightField:
    """Sampled terrain so thousands of props can ask for the ground quickly."""

    def __init__(self, size=TERRAIN_SIZE, cells=TERRAIN_CELLS):
        self.size, self.cells = size, cells
        axis = np.linspace(-size * 0.5, size * 0.5, cells + 1)
        self.x, self.y = np.meshgrid(axis, axis, indexing="xy")
        self.z = terrain_height(self.x, self.y)

    def at(self, x, y):
        return float(terrain_height(x, y))

    def slope(self, x, y):
        step = 0.6
        return math.hypot(self.at(x + step, y) - self.at(x - step, y),
                          self.at(x, y + step) - self.at(x, y - step)) / (2.0 * step)


# ---------------------------------------------------------------------------
# Materials

def _new_material(name):
    material = bpy.data.materials.get(name)
    if material is not None:
        bpy.data.materials.remove(material)
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    return material, material.node_tree.nodes, material.node_tree.links


def _noise(nodes, scale, detail=6.0, roughness=0.6, location=(-900, 0)):
    node = nodes.new("ShaderNodeTexNoise")
    node.inputs["Scale"].default_value = scale
    node.inputs["Detail"].default_value = detail
    node.inputs["Roughness"].default_value = roughness
    node.location = location
    return node


def _ramp(nodes, stops, location=(-600, 0)):
    node = nodes.new("ShaderNodeValToRGB")
    elements = node.color_ramp.elements
    while len(elements) < len(stops):
        elements.new(0.5)
    for element, (position, color) in zip(elements, stops):
        element.position = position
        element.color = tuple(color) + (1.0,)
    node.location = location
    return node


def _mix(nodes, links, factor, first, second, location):
    node = nodes.new("ShaderNodeMixRGB")
    node.location = location
    links.new(factor, node.inputs["Fac"])
    links.new(first, node.inputs["Color1"])
    links.new(second, node.inputs["Color2"])
    return node.outputs["Color"]


def _bump(nodes, links, height, shader, strength, distance=0.1):
    node = nodes.new("ShaderNodeBump")
    node.inputs["Strength"].default_value = strength
    node.inputs["Distance"].default_value = distance
    node.location = (-250, -320)
    links.new(height, node.inputs["Height"])
    links.new(node.outputs["Normal"], shader.inputs["Normal"])


def terrain_material():
    """Grass on flat ground, bare rock where it is steep, dry patches and a worn trail."""
    material, nodes, links = _new_material(PREFIX + "Terrain")
    shader = nodes["Principled BSDF"]
    shader.inputs["Roughness"].default_value = 0.92

    coords = nodes.new("ShaderNodeTexCoord")
    coords.location = (-1350, 60)
    patches = _noise(nodes, 0.11, 5.0, 0.62, (-1100, 300))
    blades = _noise(nodes, 7.0, 8.0, 0.7, (-1100, 60))
    grass = _ramp(nodes, ((0.3, (0.035, 0.075, 0.016)), (0.5, (0.085, 0.14, 0.03)), (0.72, (0.21, 0.2, 0.07))),
                  (-820, 300))
    links.new(patches.outputs["Fac"], grass.inputs["Fac"])
    fine = _ramp(nodes, ((0.3, (0.55, 0.55, 0.55)), (0.75, (1.0, 1.0, 1.0))), (-820, 60))
    links.new(blades.outputs["Fac"], fine.inputs["Fac"])
    multiply = nodes.new("ShaderNodeMixRGB")
    multiply.blend_type = "MULTIPLY"
    multiply.inputs["Fac"].default_value = 0.8
    multiply.location = (-520, 220)
    links.new(grass.outputs["Color"], multiply.inputs["Color1"])
    links.new(fine.outputs["Color"], multiply.inputs["Color2"])

    stone_noise = _noise(nodes, 0.7, 9.0, 0.72, (-1100, -200))
    for node in (patches, blades, stone_noise):
        links.new(coords.outputs["Object"], node.inputs["Vector"])
    stone = _ramp(nodes, ((0.2, (0.13, 0.11, 0.09)), (0.55, (0.32, 0.28, 0.23)), (0.85, (0.5, 0.46, 0.4))),
                  (-820, -200))
    links.new(stone_noise.outputs["Fac"], stone.inputs["Fac"])

    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (-1100, -460)
    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.location = (-900, -460)
    links.new(geometry.outputs["Normal"], separate.inputs["Vector"])
    steep = _ramp(nodes, ((0.74, (1.0, 1.0, 1.0)), (0.9, (0.0, 0.0, 0.0))), (-700, -460))
    links.new(separate.outputs["Z"], steep.inputs["Fac"])
    color = _mix(nodes, links, steep.outputs["Color"], multiply.outputs["Color"], stone.outputs["Color"], (-280, 120))

    # The trail is painted into a vertex colour layer by the terrain builder.
    trail = nodes.new("ShaderNodeVertexColor")
    trail.layer_name = "Trail"
    trail.location = (-520, -40)
    dirt = nodes.new("ShaderNodeRGB")
    dirt.outputs["Color"].default_value = (0.13, 0.095, 0.06, 1.0)
    dirt.location = (-520, -160)
    color = _mix(nodes, links, trail.outputs["Color"], color, dirt.outputs["Color"], (-80, 120))
    links.new(color, shader.inputs["Base Color"])
    _bump(nodes, links, blades.outputs["Fac"], shader, 0.35, 0.12)
    return material


def rock_material():
    material, nodes, links = _new_material(PREFIX + "Rock")
    shader = nodes["Principled BSDF"]
    shader.inputs["Roughness"].default_value = 0.88
    coords = nodes.new("ShaderNodeTexCoord")
    coords.location = (-1300, 0)
    strata = _noise(nodes, 1.6, 10.0, 0.74, (-1050, 180))
    cracks = nodes.new("ShaderNodeTexVoronoi")
    cracks.feature = "DISTANCE_TO_EDGE"
    cracks.inputs["Scale"].default_value = 3.2
    cracks.location = (-1050, -120)
    for node in (strata, cracks):
        links.new(coords.outputs["Object"], node.inputs["Vector"])
    tone = _ramp(nodes, ((0.25, (0.035, 0.03, 0.026)), (0.5, (0.13, 0.115, 0.095)), (0.75, (0.3, 0.27, 0.22))),
                 (-760, 180))
    links.new(strata.outputs["Fac"], tone.inputs["Fac"])
    crack_tone = _ramp(nodes, ((0.0, (0.25, 0.25, 0.25)), (0.08, (1.0, 1.0, 1.0))), (-760, -120))
    links.new(cracks.outputs["Distance"], crack_tone.inputs["Fac"])
    multiply = nodes.new("ShaderNodeMixRGB")
    multiply.blend_type = "MULTIPLY"
    multiply.inputs["Fac"].default_value = 0.85
    multiply.location = (-460, 100)
    links.new(tone.outputs["Color"], multiply.inputs["Color1"])
    links.new(crack_tone.outputs["Color"], multiply.inputs["Color2"])
    links.new(multiply.outputs["Color"], shader.inputs["Base Color"])
    height = nodes.new("ShaderNodeMath")
    height.operation = "MULTIPLY"
    height.location = (-460, -260)
    links.new(strata.outputs["Fac"], height.inputs[0])
    links.new(crack_tone.outputs["Color"], height.inputs[1])
    _bump(nodes, links, height.outputs["Value"], shader, 0.9, 0.25)
    return material


def _varied_material(name, dark, light, roughness, scale):
    """A colour that shifts a little per object and across each surface."""
    material, nodes, links = _new_material(name)
    shader = nodes["Principled BSDF"]
    shader.inputs["Roughness"].default_value = roughness
    info = nodes.new("ShaderNodeObjectInfo")
    info.location = (-900, 200)
    grain = _noise(nodes, scale, 4.0, 0.6, (-900, -60))
    add = nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    add.use_clamp = True
    add.location = (-680, 80)
    scale_random = nodes.new("ShaderNodeMath")
    scale_random.operation = "MULTIPLY"
    scale_random.inputs[1].default_value = 0.45
    scale_random.location = (-780, 220)
    links.new(info.outputs["Random"], scale_random.inputs[0])
    links.new(scale_random.outputs["Value"], add.inputs[0])
    half = nodes.new("ShaderNodeMath")
    half.operation = "MULTIPLY"
    half.inputs[1].default_value = 0.7
    half.location = (-780, -60)
    links.new(grain.outputs["Fac"], half.inputs[0])
    links.new(half.outputs["Value"], add.inputs[1])
    tone = _ramp(nodes, ((0.2, dark), (0.9, light)), (-460, 80))
    links.new(add.outputs["Value"], tone.inputs["Fac"])
    links.new(tone.outputs["Color"], shader.inputs["Base Color"])
    _bump(nodes, links, grain.outputs["Fac"], shader, 0.3, 0.05)
    return material


def _plain_material(name, color, roughness, metallic=0.0):
    material, nodes, _links = _new_material(name)
    shader = nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = tuple(color) + (1.0,)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    material.diffuse_color = tuple(color) + (1.0,)
    return material


# ---------------------------------------------------------------------------
# Meshes

def _mesh_from_bmesh(name, bm, smooth=False):
    mesh = bpy.data.meshes.new(name)
    if smooth:
        for face in bm.faces:
            face.smooth = True
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _link(context, name, mesh, location=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1), collection=None):
    obj = bpy.data.objects.new(name, mesh)
    obj.location, obj.rotation_euler, obj.scale = location, rotation, scale
    (collection or context.scene.collection).objects.link(obj)
    return obj


def _collection(scene, name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def terrain_mesh(field, material):
    cells = field.cells
    co = np.stack((field.x, field.y, field.z), axis=-1).reshape(-1, 3)
    stride = cells + 1
    index = np.arange(cells * stride).reshape(cells, stride)[:, :-1]
    faces = np.stack((index, index + 1, index + stride + 1, index + stride), axis=-1).reshape(-1, 4)
    mesh = bpy.data.meshes.new(PREFIX + "Terrain")
    mesh.from_pydata(co.tolist(), [], faces.tolist())
    smooth = np.ones(len(mesh.polygons), dtype=bool)
    mesh.polygons.foreach_set("use_smooth", smooth)
    uv = mesh.uv_layers.new(name="UVMap")
    loops = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loops)
    uv.data.foreach_set("uv", (co[loops][:, :2] / field.size + 0.5).ravel())
    # Paint the trail where the height function carved the valley floor.
    trail_x = 3.0 * np.sin(co[:, 1] / 17.0)
    wear = np.exp(-((co[:, 0] - trail_x) / 1.5) ** 2)
    wear *= 0.55 + 0.45 * _value_noise(co[:, 0] / 2.5, co[:, 1] / 2.5, 11)
    colors = mesh.color_attributes.new("Trail", "FLOAT_COLOR", "POINT")
    rgba = np.repeat(np.clip(wear, 0.0, 1.0)[:, None], 4, axis=1)
    rgba[:, 3] = 1.0
    colors.data.foreach_set("color", rgba.ravel())
    mesh.materials.append(material)
    mesh.update()
    return mesh


def horizon_mesh(material, size=1100.0, cells=56):
    """Distant ridges around the valley; never walked on, so kept coarse."""
    axis = np.linspace(-size * 0.5, size * 0.5, cells + 1)
    x, y = np.meshgrid(axis, axis, indexing="xy")
    distance = np.hypot(x, y)
    ridges = (_value_noise(x / 150.0, y / 150.0, 21) * 0.5 + 0.5) * 95.0 + _value_noise(x / 45.0, y / 45.0, 23) * 14.0
    rise = np.clip((distance - 110.0) / 260.0, 0.0, 1.0)
    z = ridges * rise ** 1.4 + terrain_height(x, y) * (1.0 - rise) - 2.5 * (1.0 - rise)
    co = np.stack((x, y, z), axis=-1).reshape(-1, 3)
    stride = cells + 1
    index = np.arange(cells * stride).reshape(cells, stride)[:, :-1]
    faces = np.stack((index, index + 1, index + stride + 1, index + stride), axis=-1).reshape(-1, 4)
    # The playable terrain covers the middle; leave it out here.
    centers = co[faces].mean(axis=1)
    keep = np.maximum(np.abs(centers[:, 0]), np.abs(centers[:, 1])) > TERRAIN_SIZE * 0.5 - size / cells
    mesh = bpy.data.meshes.new(PREFIX + "Horizon")
    mesh.from_pydata(co.tolist(), [], faces[keep].tolist())
    mesh.polygons.foreach_set("use_smooth", np.ones(len(mesh.polygons), dtype=bool))
    mesh.materials.append(material)
    mesh.update()
    return mesh


def rock_mesh(name, seed, material):
    """A boulder: a sphere pushed in and out by layered waves, with flattened facets."""
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=1.0)
    directions = rng.normal(size=(14, 3))
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    for vert in bm.verts:
        point = np.array(vert.co)
        offset = 0.0
        for k, direction in enumerate(directions):
            frequency = 1.3 + k * 1.1
            wave = math.sin(float(point @ direction) * frequency + k * 1.7)
            # Folding the wave gives ridges and creases instead of smooth swells.
            offset += (abs(wave) * 2.0 - 1.0) * 0.2 / (1.0 + k * 0.5)
        # Shear planes give the hard, split faces of fractured stone.
        for direction in directions[:6]:
            reach = float(point @ direction)
            if reach > 0.55:
                offset -= (reach - 0.55) * 1.1
        vert.co = vert.co * (1.0 + offset)
    for face in bm.faces:
        face.smooth = False
    mesh = _mesh_from_bmesh(name, bm)
    mesh.materials.append(material)
    return mesh


def conifer_mesh(name, seed, bark, needles, height=9.0):
    """A tall conifer: a tapering trunk carrying separate, drooping whorls of branches."""
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=7, radius1=0.2, radius2=0.035, depth=height,
                          matrix=Matrix.Translation((0, 0, height * 0.5)))
    trunk_faces = len(bm.faces)
    tiers = 13
    for tier in range(tiers):
        t = tier / (tiers - 1)
        base = height * (0.3 + 0.66 * t)
        radius = (2.3 - 1.95 * t) * rng.uniform(0.8, 1.15)
        depth = 1.1 - 0.5 * t
        segments = 11
        result = bmesh.ops.create_cone(
            bm, cap_ends=True, cap_tris=True, segments=segments, radius1=radius, radius2=0.05, depth=depth,
            matrix=Matrix.Translation((0, 0, base + depth * 0.5)) @ Matrix.Rotation(rng.uniform(0, math.tau), 4, "Z"))
        for vert in result["verts"]:
            if vert.co.z < base + depth * 0.25:
                # Uneven, hanging branch tips.
                vert.co.z -= rng.uniform(0.15, 0.7) * (1.0 - 0.5 * t)
                spread = rng.uniform(0.55, 1.25)
                vert.co.x *= spread
                vert.co.y *= spread
    bm.faces.ensure_lookup_table()
    for face in bm.faces[trunk_faces:]:
        face.material_index = 1
    mesh = _mesh_from_bmesh(name, bm, smooth=True)
    mesh.materials.append(bark)
    mesh.materials.append(needles)
    return mesh


def grass_mesh(name, seed, material, blades=20, height=0.42):
    """A tuft of curved blades, each a narrow strip of two quads."""
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    for _ in range(blades):
        angle = rng.uniform(0, math.tau)
        root = Vector((rng.normal(0, 0.24), rng.normal(0, 0.24), 0.0))
        side = Vector((math.cos(angle), math.sin(angle), 0.0)) * rng.uniform(0.01, 0.018)
        lean = Vector((-math.sin(angle), math.cos(angle), 0.0)) * rng.uniform(0.05, 0.3)
        tall = height * rng.uniform(0.55, 1.25)
        rows = []
        for step in range(3):
            t = step / 2.0
            center = root + lean * t * t + Vector((0, 0, tall * t))
            width = side * (1.0 - 0.85 * t)
            rows.append((bm.verts.new(center - width), bm.verts.new(center + width)))
        for lower, upper in zip(rows, rows[1:]):
            bm.faces.new((lower[0], lower[1], upper[1], upper[0]))
    mesh = _mesh_from_bmesh(name, bm, smooth=True)
    mesh.materials.append(material)
    return mesh


def bush_mesh(name, seed, material):
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    for _ in range(5):
        center = Vector((rng.normal(0, 0.35), rng.normal(0, 0.35), rng.uniform(0.25, 0.6)))
        bmesh.ops.create_icosphere(bm, subdivisions=3, radius=rng.uniform(0.35, 0.6),
                                   matrix=Matrix.Translation(center))
    for vert in bm.verts:
        vert.co += Vector(rng.normal(0, 0.035, 3))
    mesh = _mesh_from_bmesh(name, bm, smooth=True)
    mesh.materials.append(material)
    return mesh


def _add_box(bm, size, center, material_index=0, rotation=None):
    matrix = Matrix.Translation(center)
    if rotation is not None:
        matrix = matrix @ rotation
    result = bmesh.ops.create_cube(bm, size=1.0, matrix=matrix @ Matrix.Diagonal((size[0], size[1], size[2], 1.0)))
    for face in {face for vert in result["verts"] for face in vert.link_faces}:
        face.material_index = material_index


def _add_tube(bm, radius, length, center, material_index=0, segments=12, axis="Y"):
    rotation = Matrix.Rotation(math.radians(90), 4, "X") if axis == "Y" else Matrix.Identity(4)
    result = bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius, radius2=radius,
                                   depth=length, matrix=Matrix.Translation(center) @ rotation)
    for face in {face for vert in result["verts"] for face in vert.link_faces}:
        face.material_index = material_index
        face.smooth = len(face.verts) == 4


def rifle_mesh(body, metal):
    """A generic carbine in camera space: +Y is forward, built around the origin at the grip."""
    bm = bmesh.new()
    _add_box(bm, (0.052, 0.34, 0.085), (0, 0.06, 0.05))                 # receiver
    _add_box(bm, (0.056, 0.3, 0.07), (0, 0.38, 0.05))                   # handguard
    for offset in range(5):                                             # cooling slots
        _add_box(bm, (0.06, 0.03, 0.022), (0, 0.27 + offset * 0.055, 0.052), 1)
    _add_tube(bm, 0.012, 0.3, (0, 0.67, 0.052), 1)                      # barrel
    _add_tube(bm, 0.019, 0.07, (0, 0.82, 0.052), 1)                     # muzzle device
    _add_box(bm, (0.03, 0.44, 0.014), (0, 0.2, 0.1), 1)                 # top rail
    _add_box(bm, (0.04, 0.26, 0.07), (0, -0.25, 0.035))                 # stock
    _add_box(bm, (0.048, 0.035, 0.12), (0, -0.385, 0.02))               # butt pad
    _add_box(bm, (0.04, 0.055, 0.12), (0, -0.04, -0.045),               # grip
             rotation=Matrix.Rotation(math.radians(-16), 4, "X"))
    _add_box(bm, (0.034, 0.075, 0.2), (0, 0.11, -0.085), 1,             # magazine
             rotation=Matrix.Rotation(math.radians(9), 4, "X"))
    _add_box(bm, (0.012, 0.09, 0.012), (0, 0.035, -0.012), 1)           # trigger guard
    # Ring sight: a short open tube on a post.
    ring_matrix = Matrix.Translation((0, 0.12, 0.148)) @ Matrix.Rotation(math.radians(90), 4, "X")
    ring = bmesh.ops.create_cone(bm, cap_ends=False, segments=20, radius1=0.026, radius2=0.026, depth=0.03,
                                 matrix=ring_matrix)
    walls = bmesh.ops.solidify(bm, geom=list({face for vert in ring["verts"] for face in vert.link_faces}),
                               thickness=0.004)
    for item in walls["geom"]:
        if isinstance(item, bmesh.types.BMFace):
            item.material_index = 1
    _add_box(bm, (0.02, 0.05, 0.02), (0, 0.12, 0.112), 1)               # sight base
    _add_box(bm, (0.008, 0.008, 0.04), (0, 0.5, 0.125), 1)              # front post
    mesh = _mesh_from_bmesh(PREFIX + "Rifle", bm)
    mesh.materials.append(body)
    mesh.materials.append(metal)
    return mesh


def soldier_mesh(name, cloth, gear):
    """A simple standing figure, 1.8 m tall with its origin at the hips' centre."""
    bm = bmesh.new()
    for x in (-0.11, 0.11):
        _add_tube(bm, 0.085, 0.86, (x, 0, -0.47), 0, 10, axis="Z")       # legs
        _add_tube(bm, 0.06, 0.62, (x * 2.5, 0, 0.3), 0, 8, axis="Z")     # arms
    _add_box(bm, (0.42, 0.25, 0.62), (0, 0, 0.27), 0)                    # torso
    _add_box(bm, (0.46, 0.3, 0.36), (0, 0.01, 0.34), 1)                  # vest
    result = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.125, matrix=Matrix.Translation((0, 0, 0.72)))
    for face in {face for vert in result["verts"] for face in vert.link_faces}:
        face.smooth = True
    _add_box(bm, (0.27, 0.29, 0.13), (0, 0, 0.8), 1)                     # helmet
    _add_box(bm, (0.05, 0.6, 0.08), (0.2, 0.2, 0.2), 1)                  # carried weapon
    mesh = _mesh_from_bmesh(name, bm)
    mesh.materials.append(cloth)
    mesh.materials.append(gear)
    return mesh


# ---------------------------------------------------------------------------
# Scattering

def _scatter(rng, count, field, accept, half=None):
    """Random ground positions that satisfy `accept(x, y, slope)`."""
    half = half if half is not None else field.size * 0.5 - 4.0
    points = []
    attempts = 0
    while len(points) < count and attempts < count * 40:
        attempts += 1
        x, y = rng.uniform(-half, half, 2)
        if accept(x, y, field.slope(x, y)):
            points.append((float(x), float(y)))
    return points


def _trail_distance(x, y):
    return abs(x - 3.0 * math.sin(y / 17.0))


def _mark_scenery(obj, tag=""):
    optimization.mark_static_object(obj)
    optimization.mark_instancing_candidate(obj)
    if tag:
        obj.blendengine_object.object_tag = tag


# ---------------------------------------------------------------------------
# Lighting

def setup_sky(scene, sun_elevation=math.radians(24.0), sun_heading=math.radians(-14.0)):
    """A physical sky with a low sun ahead of the player, and a matching sun lamp."""
    world = bpy.data.worlds.new(PREFIX + "Sky")
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    background = nodes["Background"]
    sky = nodes.new("ShaderNodeTexSky")
    # Blender names its physical sky model differently across versions.
    for sky_type in ("NISHITA", "MULTIPLE_SCATTERING", "SINGLE_SCATTERING", "HOSEK_WILKIE"):
        try:
            sky.sky_type = sky_type
            break
        except TypeError:
            continue
    for name, value in (("sun_elevation", sun_elevation), ("sun_rotation", sun_heading), ("sun_disc", True),
                        ("sun_size", math.radians(2.0)), ("sun_intensity", 0.12), ("altitude", 900.0),
                        ("air_density", 1.3), ("dust_density", 1.5), ("aerosol_density", 1.5),
                        ("ozone_density", 1.0)):
        if hasattr(sky, name):
            setattr(sky, name, value)
    links.new(sky.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = 0.13
    scene.world = world

    sun = bpy.data.objects.new(PREFIX + "Sun", bpy.data.lights.new(PREFIX + "Sun", "SUN"))
    sun.data.energy = 6.5
    sun.data.color = (1.0, 0.9, 0.74)
    sun.data.angle = math.radians(1.6)
    # The lamp shines from where the sky draws its sun: heading is clockwise from +Y.
    towards_sun = Vector((math.sin(sun_heading) * math.cos(sun_elevation),
                          math.cos(sun_heading) * math.cos(sun_elevation), math.sin(sun_elevation)))
    sun.rotation_euler = towards_sun.to_track_quat("Z", "Y").to_euler()
    sun.location = (0.0, 0.0, 60.0)
    scene.collection.objects.link(sun)
    return sun


# ---------------------------------------------------------------------------
# The level

def generate_highland_patrol(context, clean_scene=True, seed=4, grass_tufts=2400, trees=150, enemies=6):
    """Build the level in the current scene and return its key objects."""
    scene = context.scene
    if clean_scene:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)

    project = utils.ensure_project_defaults(scene)
    project.game_title = "Highland Patrol"
    project.default_scene = scene
    project.game_dimension = "THREE_D"
    project.resolution_x, project.resolution_y = 1600, 900
    project.show_fps = True
    project.show_game_variables = True
    scene.render.resolution_x, scene.render.resolution_y = 1600, 900
    scene.render.fps = 60
    graphics.configure_realtime(scene)
    optimization.apply_preset(scene, "HIGH")
    # Open terrain is seen far away; the streaming radius of small indoor levels would cut it off.
    scene.blendengine_optimization.camera_frustum_generation = False

    rng = np.random.default_rng(seed)
    field = HeightField()

    ground_material = terrain_material()
    stone = rock_material()
    bark = _varied_material(PREFIX + "Bark", (0.07, 0.045, 0.03), (0.2, 0.14, 0.09), 0.9, 14.0)
    needles = _varied_material(PREFIX + "Needles", (0.008, 0.025, 0.012), (0.035, 0.085, 0.03), 0.8, 3.0)
    grass = _varied_material(PREFIX + "Grass", (0.06, 0.11, 0.022), (0.3, 0.3, 0.09), 0.7, 2.0)
    shrub = _varied_material(PREFIX + "Shrub", (0.03, 0.07, 0.02), (0.13, 0.2, 0.06), 0.8, 5.0)

    # Ground.
    terrain = _link(context, PREFIX + "Terrain", terrain_mesh(field, ground_material))
    components.add_collider(terrain, tag="Ground")
    optimization.mark_static_object(terrain)
    terrain.blendengine_object.object_tag = "Ground"
    horizon = _link(context, PREFIX + "Horizon", horizon_mesh(ground_material))
    _mark_scenery(horizon)

    # Rocks: a tall outcrop beside the spawn, boulders across the slopes.
    rocks = _collection(scene, PREFIX + "Rocks")
    rock_meshes = [rock_mesh(PREFIX + "Rock_%d" % i, 40 + i, stone) for i in range(4)]
    outcrop = (
        ((-6.6, -30.0), (3.4, 4.2, 4.6), 0.5), ((-8.8, -25.5), (4.6, 4.0, 3.8), 2.1),
        ((-4.6, -32.6), (1.5, 1.8, 1.25), 3.4), ((-10.8, -31.5), (4.6, 5.0, 6.6), 1.2),
        ((-3.9, -27.6), (1.0, 1.2, 0.8), 4.0),
    )
    for index, ((x, y), scale, turn) in enumerate(outcrop):
        rock = _link(context, PREFIX + "Outcrop_%d" % index, rock_meshes[index % 4],
                     (x, y, field.at(x, y) + scale[2] * 0.3), (0.2 * index, 0.15, turn), scale, rocks)
        _mark_scenery(rock, "Rock")
    spots = _scatter(rng, 70, field, lambda x, y, slope: _trail_distance(x, y) > 5.0 and math.hypot(x, y + 34) > 14)
    for index, (x, y) in enumerate(spots):
        size = float(rng.lognormal(-0.2, 0.55))
        scale = (size * rng.uniform(0.8, 1.5), size * rng.uniform(0.8, 1.5), size * rng.uniform(0.5, 1.0))
        rock = _link(context, PREFIX + "Boulder_%02d" % index, rock_meshes[index % 4],
                     (x, y, field.at(x, y) + scale[2] * 0.15), tuple(rng.uniform(0, math.tau, 3)), scale, rocks)
        _mark_scenery(rock, "Rock")

    # Trees: three shapes shared by every tree, denser away from the trail.
    forest = _collection(scene, PREFIX + "Trees")
    tree_meshes = [conifer_mesh(PREFIX + "Conifer_%d" % i, 60 + i, bark, needles, height) for i, height in
                   enumerate((8.5, 10.5, 12.5))]

    def tree_ground(x, y, slope):
        return (_trail_distance(x, y) > 6.5 and slope < 0.75 and math.hypot(x - SPAWN[0], y - SPAWN[1]) > 9.0
                and _value_noise(np.float64(x / 26.0), np.float64(y / 26.0), 31) > -0.25)

    for index, (x, y) in enumerate(_scatter(rng, trees, field, tree_ground)):
        size = float(rng.uniform(0.75, 1.35))
        tree = _link(context, PREFIX + "Tree_%03d" % index, tree_meshes[index % 3],
                     (x, y, field.at(x, y) - 0.25), (rng.uniform(-0.04, 0.04), rng.uniform(-0.04, 0.04),
                                                      rng.uniform(0, math.tau)), (size, size, size), forest)
        _mark_scenery(tree, "Tree")

    # Undergrowth near where the player walks; farther away the ground colour carries it.
    plants = _collection(scene, PREFIX + "Plants")
    grass_meshes = [grass_mesh(PREFIX + "Tuft_%d" % i, 80 + i, grass) for i in range(4)]
    bush_meshes = [bush_mesh(PREFIX + "Bush_%d" % i, 90 + i, shrub) for i in range(2)]

    def near_trail(x, y, slope):
        return 1.0 < _trail_distance(x, y) < 20.0 and slope < 0.9 and -50.0 < y < 30.0

    for index, (x, y) in enumerate(_scatter(rng, grass_tufts, field, near_trail)):
        size = float(rng.uniform(0.8, 1.7))
        tuft = _link(context, PREFIX + "Grass_%04d" % index, grass_meshes[index % 4], (x, y, field.at(x, y) - 0.03),
                     (0, 0, rng.uniform(0, math.tau)), (size, size, size * rng.uniform(0.8, 1.4)), plants)
        _mark_scenery(tuft)
    bush_spots = _scatter(rng, 60, field, lambda x, y, s: (
            3.5 < _trail_distance(x, y) < 40 and s < 0.8 and math.hypot(x - SPAWN[0], y - SPAWN[1]) > 12.0))
    for index, (x, y) in enumerate(bush_spots):
        size = float(rng.uniform(0.7, 1.6))
        bush = _link(context, PREFIX + "Bush_%02d" % index, bush_meshes[index % 2], (x, y, field.at(x, y) - 0.1),
                     (0, 0, rng.uniform(0, math.tau)), (size, size, size * 0.8), plants)
        _mark_scenery(bush)

    sun = setup_sky(scene)

    # Player and the camera the runtime drives.
    ground_z = field.at(*SPAWN)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.38, radius2=0.38, depth=1.8)
    player = _link(context, PREFIX + "Player", _mesh_from_bmesh(PREFIX + "Player", bm),
                   (SPAWN[0], SPAWN[1], ground_z + 0.9))
    player.display_type = "WIRE"
    player.hide_render = True
    components.add_player_controller(player)
    player.blendengine_object.object_tag = "PlayerBody"
    controller = player.blendengine_object.player_controller
    controller.controller_type = "FIRST_PERSON"
    controller.walk_speed, controller.run_speed = 4.5, 8.0
    components.add_collider(player, tag="Player")
    components.add_health(player, max_health=100.0)
    optimization.mark_dynamic_object(player)
    for name, value in (("Score", 0), ("Ammo", 120), ("Kills", 0)):
        variable = player.blendengine_object.variables.add()
        variable.name, variable.variable_type, variable.int_value = name, "INT", value

    camera = bpy.data.objects.new(PREFIX + "Camera", bpy.data.cameras.new(PREFIX + "Camera"))
    camera.data.lens = 24.0
    camera.data.clip_start, camera.data.clip_end = 0.05, 1500.0
    camera.location = (SPAWN[0], SPAWN[1], ground_z + 1.62)
    camera.rotation_euler = (math.radians(86.0), 0.0, math.radians(-6.0))
    scene.collection.objects.link(camera)
    scene.camera = camera
    controller.camera_follow = camera
    utils.ensure_component(camera, "CAMERA_CONTROLLER", tag="MainCamera")

    body = _plain_material(PREFIX + "RiflePolymer", (0.11, 0.1, 0.08), 0.62)
    metal = _plain_material(PREFIX + "RifleSteel", (0.035, 0.037, 0.04), 0.38, 0.85)
    rifle = _link(context, PREFIX + "Rifle", rifle_mesh(body, metal))
    rifle.parent = camera
    # Camera space looks down -Z; lay the rifle's +Y along it, low and to the right.
    rifle.location = (0.14, -0.19, -0.52)
    rifle.rotation_euler = (math.radians(-88.0), math.radians(2.0), math.radians(-3.5))
    rifle.blendengine_object.object_tag = "Weapon"
    utils.ensure_component(rifle, "WEAPON", tag="Weapon")
    optimization.mark_dynamic_object(rifle)

    # Enemy patrol spread up the valley.
    cloth = _plain_material(PREFIX + "Fatigues", (0.16, 0.19, 0.11), 0.85)
    gear = _plain_material(PREFIX + "Gear", (0.07, 0.065, 0.05), 0.7)
    figure = soldier_mesh(PREFIX + "Soldier", cloth, gear)
    squad = _collection(scene, PREFIX + "Enemies")
    posts = _scatter(rng, enemies, field,
                     lambda x, y, slope: 4.0 < _trail_distance(x, y) < 30.0 and -8.0 < y < 55.0 and slope < 0.5)
    enemy_objects = []
    for index, (x, y) in enumerate(posts):
        enemy = _link(context, PREFIX + "Enemy_%02d" % (index + 1), figure, (x, y, field.at(x, y) + 0.9),
                      (0, 0, rng.uniform(0, math.tau)), collection=squad)
        components.add_collider(enemy, tag="Enemy")
        components.add_health(enemy, max_health=100.0)
        npc = components.add_npc_behavior(enemy, "PATROL" if index % 2 else "ATTACK", target=player)
        npc.move_speed, npc.attack_range, npc.detection_range = 2.4, 1.6, 45.0
        enemy.blendengine_object.object_tag = "Enemy"
        optimization.mark_dynamic_object(enemy)
        enemy_objects.append(enemy)

    input_system.ensure_defaults(scene)
    input_system.add_binding(scene, action="ATTACK", key="LEFTMOUSE")
    input_system.add_binding(scene, action="AIM", key="RIGHTMOUSE")

    # Film look without lens blur: the rifle sits centimetres from the camera.
    cinematic.apply_look(scene, depth_of_field=False, bloom=0.3, vignette=0.25, dispersion=0.0)
    scene.view_settings.exposure = -0.2

    context.view_layer.update()
    return {
        "player": player,
        "camera": camera,
        "terrain": terrain,
        "rifle": rifle,
        "sun": sun,
        "enemies": enemy_objects,
        "enemy_count": len(enemy_objects),
        "field": field,
    }
