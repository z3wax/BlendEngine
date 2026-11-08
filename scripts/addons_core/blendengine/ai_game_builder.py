# SPDX-License-Identifier: GPL-2.0-or-later
#
# AI Game Creator: build a playable BlendEngine scene from a game spec.
#
# The builder only uses ``bpy.data`` and ``bmesh`` (no ``bpy.ops``), so it runs
# from timers, background mode, and the command-line tool alike. Repeated
# objects (trees, coins, enemies) share one mesh datablock, which keeps memory
# low and marks them as natural instancing candidates for the optimizer.

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import ai_game_spec as spec_lib
from . import components, graphics, input_system, optimization, templates, utils


SPEC_TEXT_NAME = "BlendEngine AI Game Spec.json"
COLLECTION_PREFIX = "AI "
MAX_POINT_LIGHTS = 6

TIME_OF_DAY_LIGHT = {
    # sun energy, sun color, sun elevation (deg), world strength
    "DAY": (3.6, (1.0, 0.96, 0.9), 52.0, 1.0),
    "SUNSET": (3.4, (1.0, 0.64, 0.42), 30.0, 0.75),
    "NIGHT": (1.0, (0.55, 0.66, 1.0), 38.0, 0.5),
}

# Half height of each shape at size 1, used to stand objects on the ground.
PLAYER_HALF_HEIGHT = {"CAPSULE": 0.9, "ROBOT": 0.9, "CUBE": 0.5, "SPHERE": 0.5}
ENEMY_HALF_HEIGHT = {"BLOB": 0.38, "BRUTE": 0.9, "ROBOT": 0.9, "SPIKY": 0.55, "GHOST": 0.75, "DRONE": 0.35}
ENEMY_HOVER = {"GHOST": 0.35, "DRONE": 1.4}

PROP_SPACING = {
    "TREE": 3.2, "PINE": 3.0, "PALM": 3.4, "ROCK": 2.4, "CACTUS": 2.6, "BUILDING": 7.5,
    "CRYSTAL": 2.2, "PILLAR": 3.0, "CRATE": 1.8, "LAMP": 4.0, "MUSHROOM": 2.2,
}
BIG_PROPS = {"BUILDING", "PILLAR", "PALM"}


# ---------------------------------------------------------------------------
# Mesh construction.
# ---------------------------------------------------------------------------

def _matrix(at=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), rotation=None):
    matrix = Matrix.Translation(Vector(at))
    if rotation is not None:
        for axis, angle in rotation:
            matrix = matrix @ Matrix.Rotation(angle, 4, axis)
    return matrix @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))


class ShapeBuilder:
    """Append primitives to one bmesh, each tagged with a material slot."""

    def __init__(self):
        self.bm = bmesh.new()
        self.material = 0
        self.smooth = False

    def use(self, material, smooth=None):
        self.material = material
        if smooth is not None:
            self.smooth = smooth
        return self

    def _tag(self, verts):
        # Faces of a new primitive are exactly the faces touching its vertices.
        # (Face order is not creation order, so indices cannot be used.)
        for face in {face for vert in verts for face in vert.link_faces}:
            face.material_index = self.material
            face.smooth = self.smooth

    def box(self, size, at=(0.0, 0.0, 0.0), rotation=None):
        result = bmesh.ops.create_cube(self.bm, size=1.0, matrix=_matrix(at, size, rotation))
        self._tag(result["verts"])
        return self

    def cone(self, radius1, radius2, depth, at=(0.0, 0.0, 0.0), segments=12, rotation=None, scale=(1.0, 1.0, 1.0)):
        result = bmesh.ops.create_cone(
            self.bm, cap_ends=True, cap_tris=False, segments=segments,
            radius1=radius1, radius2=radius2, depth=depth, matrix=_matrix(at, scale, rotation))
        self._tag(result["verts"])
        return self

    def cylinder(self, radius, depth, at=(0.0, 0.0, 0.0), segments=12, rotation=None):
        return self.cone(radius, radius, depth, at, segments, rotation)

    def sphere(self, radius, at=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), segments=16, rings=8):
        result = bmesh.ops.create_uvsphere(
            self.bm, u_segments=segments, v_segments=rings, radius=radius, matrix=_matrix(at, scale))
        self._tag(result["verts"])
        return self

    def ico(self, radius, at=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), subdivisions=1):
        result = bmesh.ops.create_icosphere(
            self.bm, subdivisions=subdivisions, radius=radius, matrix=_matrix(at, scale))
        self._tag(result["verts"])
        return self

    def torus(self, major, minor, at=(0.0, 0.0, 0.0), major_segments=32, minor_segments=8, rotation=None):
        matrix = _matrix(at, (1.0, 1.0, 1.0), rotation)
        rings = []
        for i in range(major_segments):
            u = 2.0 * math.pi * i / major_segments
            ring = []
            for j in range(minor_segments):
                v = 2.0 * math.pi * j / minor_segments
                radius = major + minor * math.cos(v)
                local = Vector((radius * math.cos(u), radius * math.sin(u), minor * math.sin(v)))
                ring.append(self.bm.verts.new(matrix @ local))
            rings.append(ring)
        for i in range(major_segments):
            for j in range(minor_segments):
                a = rings[i][j]
                b = rings[(i + 1) % major_segments][j]
                c = rings[(i + 1) % major_segments][(j + 1) % minor_segments]
                d = rings[i][(j + 1) % minor_segments]
                self.bm.faces.new((a, b, c, d))
        self._tag([vert for ring in rings for vert in ring])
        return self

    def star(self, outer, inner, depth, points=5, at=(0.0, 0.0, 0.0), rotation=None):
        matrix = _matrix(at, (1.0, 1.0, 1.0), rotation)
        top, bottom = [], []
        for i in range(points * 2):
            angle = math.pi * i / points + math.pi / 2.0
            radius = outer if i % 2 == 0 else inner
            x, y = radius * math.cos(angle), radius * math.sin(angle)
            top.append(self.bm.verts.new(matrix @ Vector((x, y, depth * 0.5))))
            bottom.append(self.bm.verts.new(matrix @ Vector((x, y, -depth * 0.5))))
        center_top = self.bm.verts.new(matrix @ Vector((0.0, 0.0, depth * 0.5)))
        center_bottom = self.bm.verts.new(matrix @ Vector((0.0, 0.0, -depth * 0.5)))
        count = len(top)
        for i in range(count):
            j = (i + 1) % count
            self.bm.faces.new((center_top, top[i], top[j]))
            self.bm.faces.new((center_bottom, bottom[j], bottom[i]))
            self.bm.faces.new((top[i], bottom[i], bottom[j], top[j]))
        self._tag(top + bottom)
        return self

    def finish(self, name, materials):
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:])
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for material in materials:
            mesh.materials.append(material)
        return mesh


# ---------------------------------------------------------------------------
# Builder.
# ---------------------------------------------------------------------------

def _sanitize(name):
    return "".join(ch if ch.isalnum() else "_" for ch in name).strip("_") or "Item"


class GameBuilder:
    def __init__(self, scene, spec):
        self.scene = scene
        self.spec = spec
        self.rng = random.Random(spec.get("seed", 1))
        self.world = spec["world"]
        self.theme = self.world["theme"]
        self.is_2d = spec["dimension"] == "2D"
        self.half = self.world["size"] * 0.5
        self.hilliness = self.world["hilliness"] if not self.is_2d else 0.0
        self.meshes = {}
        self.materials = {}
        self.collections = {}
        self.point_lights = 0
        self.occupied = []
        self.player = None
        self.camera = None
        self.created = []
        self.level_length = max(36.0, self.world["size"] * 1.2)

    # -- infrastructure ----------------------------------------------------

    def material(self, key, color, **kwargs):
        name = "AI_%s_%s" % (self.theme.title().replace("_", ""), key)
        if name not in self.materials:
            if isinstance(color, str):
                color = spec_lib.hex_to_linear(color)
            emission = kwargs.pop("emission", None)
            if isinstance(emission, str):
                emission = spec_lib.hex_to_linear(emission)
            if emission is not None and len(emission) == 3:
                emission = (emission[0], emission[1], emission[2], 1.0)
            self.materials[name] = templates._material(name, tuple(color[:3]) + (1.0,), emission=emission, **kwargs)
        return self.materials[name]

    def glow(self, key, color, strength=2.5, alpha=1.0, roughness=0.3):
        return self.material(key, color, roughness=roughness, emission=color, emission_strength=strength, alpha=alpha)

    def mesh(self, key, build):
        mesh = self.meshes.get(key)
        if mesh is None:
            mesh = build("AI_%s_Mesh" % key)
            self.meshes[key] = mesh
        return mesh

    def collection(self, key):
        collection = self.collections.get(key)
        if collection is None:
            collection = bpy.data.collections.new(COLLECTION_PREFIX + key)
            self.scene.collection.children.link(collection)
            self.collections[key] = collection
        return collection

    def obj(self, name, data, location, group, rotation=(0.0, 0.0, 0.0), scale=None):
        obj = bpy.data.objects.new(name, data)
        self.collection(group).objects.link(obj)
        obj.location = location
        obj.rotation_euler = rotation
        if scale is not None:
            obj.scale = scale if isinstance(scale, (tuple, list)) else (scale, scale, scale)
        self.created.append(obj)
        return obj

    def ground_z(self, x, y):
        if self.is_2d:
            return 0.0
        return spec_lib.terrain_height(x, y, self.half, self.hilliness)

    def scatter(self, count, spacing, avoid=(), inner=0.0, outer=None, extent=None):
        """Points on the arena floor; enemies and pickups stay on the flat middle."""
        extent = extent if extent is not None else self.half * 0.68
        return spec_lib.scatter_points(
            self.rng, count, extent, spacing, avoid=avoid, existing=self.occupied,
            inner_radius=inner, outer_radius=outer)

    # -- scene -------------------------------------------------------------

    def clear_scene(self):
        scene = self.scene
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for collection in list(scene.collection.children):
            if collection.name.startswith(COLLECTION_PREFIX) and not collection.all_objects:
                bpy.data.collections.remove(collection)
        for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.lights, bpy.data.cameras, bpy.data.materials):
            for block in list(datablocks):
                if block.users == 0 and block.name.startswith("AI_"):
                    datablocks.remove(block)

    def build(self, clean_scene=True):
        if clean_scene:
            self.clear_scene()
        self.setup_project()
        self.setup_world()
        if self.is_2d:
            spawn = Vector((0.0, 0.0, 0.0))
            exit_point = Vector((self.level_length, 0.0, 0.0))
            self.build_2d_level()
        else:
            spawn = Vector((0.0, -self.half * 0.45, 0.0))
            exit_point = Vector((0.0, self.half * 0.5, 0.0))
            self.build_terrain()
            self.build_walls()
        spawn.z = self.ground_z(spawn.x, spawn.y)
        exit_point.z = self.ground_z(exit_point.x, exit_point.y)
        self.spawn = spawn
        self.exit_point = exit_point
        avoid = [(spawn.x, spawn.y, 4.5), (exit_point.x, exit_point.y, 3.5)]

        self.build_player(spawn)
        self.build_camera(spawn)
        if not self.is_2d:
            self.build_platforms(avoid)
            self.build_props(avoid)
        self.build_collectibles(avoid)
        self.build_health_pickups(avoid)
        self.build_hazards(avoid)
        self.build_enemies(avoid)
        self.build_goal(exit_point)
        self.build_director()
        self.build_lights(spawn, exit_point)
        input_system.ensure_defaults(self.scene)
        self.store_spec()
        self.select_player()
        return {
            "player": self.player,
            "camera": self.camera,
            "object_count": len(self.created),
            "title": self.spec["title"],
        }

    def setup_project(self):
        scene = self.scene
        spec = self.spec
        project = utils.ensure_project_defaults(scene)
        project.game_title = spec["title"]
        project.game_dimension = "TWO_D" if self.is_2d else "THREE_D"
        project.default_scene = scene
        project.show_fps = True
        project.show_game_variables = True
        project.show_logs = True
        project.resolution_x = 1280
        project.resolution_y = 720
        scene.render.resolution_x = project.resolution_x
        scene.render.resolution_y = project.resolution_y
        scene.blendengine_export.package_name = _sanitize(spec["title"])[:40] or "AIGame"
        try:
            graphics.configure_realtime(scene)
        except RuntimeError:
            pass
        optimization.apply_preset(scene, "HIGH")
        scene.render.fps = 60
        scene["blendengine_ai_generated"] = True
        scene["blendengine_goal_text"] = spec["goal"]["description"]
        scene["blendengine_goal_target"] = int(spec["goal"]["target_count"])
        scene["blendengine_goal_type"] = spec["goal"]["type"]
        if self.is_2d:
            scene["blendengine_world_bounds"] = (-4.0, -1.0, self.level_length + 4.0, 1.0)
        else:
            limit = self.half * 0.92
            scene["blendengine_world_bounds"] = (-limit, -limit, limit, limit)

    def setup_world(self):
        scene = self.scene
        _energy, _color, _elevation, strength = TIME_OF_DAY_LIGHT[self.world["time_of_day"]]
        sky = spec_lib.hex_to_linear(self.world["sky_color"])
        # Dark skies (space, dungeons, neon nights) would leave the level
        # unlit; keep a minimum amount of ambient light so it stays playable.
        luminance = 0.2126 * sky[0] + 0.7152 * sky[1] + 0.0722 * sky[2]
        minimum = 0.04 if self.world["time_of_day"] == "NIGHT" else 0.07
        strength = min(8.0, max(strength, minimum / max(luminance, 1e-3)))
        world = scene.world or bpy.data.worlds.new("AI_World")
        scene.world = world
        world.color = sky
        world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        if background is None:
            background = next((node for node in world.node_tree.nodes if node.type == "BACKGROUND"), None)
        if background is not None:
            background.inputs[0].default_value = sky + (1.0,)
            background.inputs[1].default_value = strength
        scene.view_settings.exposure = {"DAY": 0.0, "SUNSET": 0.25, "NIGHT": 0.6}[self.world["time_of_day"]]

    # -- terrain & level ---------------------------------------------------

    def build_terrain(self):
        size = self.world["size"] * 1.15
        half = size * 0.5
        divisions = int(max(24, min(64, size / 1.4)))
        vertices, faces = [], []
        for iy in range(divisions + 1):
            y = -half + size * iy / divisions
            for ix in range(divisions + 1):
                x = -half + size * ix / divisions
                vertices.append((x, y, spec_lib.terrain_height(x, y, self.half, self.hilliness)))
        stride = divisions + 1
        for iy in range(divisions):
            for ix in range(divisions):
                a = iy * stride + ix
                faces.append((a, a + 1, a + stride + 1, a + stride))
        mesh = bpy.data.meshes.new("AI_Terrain_Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        mesh.materials.append(self.material("Ground", self.world["ground_color"], roughness=0.92, surface_scale=36.0))
        ground = self.obj("AI_Ground", mesh, (0.0, 0.0, 0.0), "World")
        components.add_collider(ground, tag="Ground")
        optimization.mark_static_object(ground)
        optimization.add_lod_group(ground)
        self.ground = ground

    def build_walls(self):
        theme_wall = spec_lib.THEME_PRESETS[self.theme]["wall"]
        wall_mat = self.material("Wall", theme_wall, roughness=0.85, surface_scale=14.0)
        trim = self.glow("WallTrim", self.world["accent_color"], strength=1.6)
        top = spec_lib.terrain_height(self.half, 0.0, self.half, self.hilliness)
        length = self.half * 2.0 + 1.2

        def build(name):
            shape = ShapeBuilder()
            shape.use(0).box((length, 0.6, 2.6))
            shape.use(1).box((length, 0.66, 0.12), at=(0.0, 0.0, 1.0))
            return shape.finish(name, [wall_mat, trim])

        mesh = self.mesh("Wall", build)
        for index, (x, y, angle) in enumerate((
                (0.0, self.half, 0.0), (0.0, -self.half, 0.0),
                (self.half, 0.0, math.pi / 2.0), (-self.half, 0.0, math.pi / 2.0))):
            wall = self.obj("AI_Wall_%d" % (index + 1), mesh, (x, y, top + 1.0), "World", rotation=(0.0, 0.0, angle))
            optimization.mark_static_object(wall)
            optimization.mark_instancing_candidate(wall)

    def build_2d_level(self):
        length = self.level_length
        ground_mat = self.material("Ground", self.world["ground_color"], roughness=0.9, surface_scale=20.0)
        edge = self.glow("Edge", self.world["accent_color"], strength=1.2)

        shape = ShapeBuilder()
        shape.use(0).box((length + 16.0, 3.0, 1.0), at=(length * 0.5, 0.0, -0.5))
        shape.use(1).box((length + 16.0, 3.06, 0.1), at=(length * 0.5, 0.0, -0.16))
        ground = self.obj("AI_Ground", shape.finish("AI_Ground2D_Mesh", [ground_mat, edge]), (0.0, 0.0, 0.0), "World")
        components.add_collider(ground, tag="Ground")
        optimization.mark_static_object(ground)
        self.ground = ground

        def platform_mesh(name):
            builder = ShapeBuilder()
            builder.use(0).box((3.0, 2.0, 0.45))
            builder.use(1).box((3.06, 2.06, 0.1), at=(0.0, 0.0, -0.05))
            return builder.finish(name, [ground_mat, edge])

        mesh = self.mesh("Platform2D", platform_mesh)
        self.platforms = []
        count = self.spec["platforms"]
        if count:
            step = (length - 12.0) / max(1, count)
            for index in range(count):
                x = 6.0 + step * (index + 0.5)
                top = 1.2 + 0.8 * (index % 3)
                platform = self.obj("AI_Platform_%02d" % (index + 1), mesh, (x, 0.0, top - 0.225), "World")
                components.add_collider(platform, tag="Ground")
                optimization.mark_static_object(platform)
                optimization.mark_instancing_candidate(platform)
                self.platforms.append(Vector((x, 0.0, top)))

        # Distant hills give the side view a horizon.
        backdrop_color = spec_lib.hex_to_linear(spec_lib.THEME_PRESETS[self.theme]["wall"])
        backdrop = self.material("Backdrop", tuple(c * 0.8 for c in backdrop_color), roughness=1.0)
        hills = ShapeBuilder()
        hills.use(0, smooth=True)
        x = -20.0
        while x < length + 30.0:
            radius = self.rng.uniform(7.0, 13.0)
            hills.sphere(radius, at=(x, self.rng.uniform(32.0, 40.0), -radius * 0.35),
                         scale=(1.0, 0.6, self.rng.uniform(0.45, 0.8)), segments=20, rings=10)
            x += radius * 1.3
        horizon = self.obj("AI_Backdrop", hills.finish("AI_Backdrop_Mesh", [backdrop]), (0.0, 0.0, 0.0), "World")
        optimization.mark_static_object(horizon)

        # Scenery sits behind the play lane.
        for group in self.spec["props"]:
            builder = self.prop_mesh(group["kind"])
            for index in range(group["count"]):
                x = self.rng.uniform(-4.0, length + 4.0)
                y = self.rng.uniform(4.0, 12.0)
                prop = self.obj("AI_%s_%02d" % (group["kind"].title(), index + 1), builder, (x, y, 0.0), "World",
                                rotation=(0.0, 0.0, self.rng.uniform(0.0, math.tau)),
                                scale=self.prop_scale(group["kind"]))
                optimization.mark_static_object(prop)
                optimization.mark_instancing_candidate(prop)

    def build_platforms(self, avoid):
        count = self.spec["platforms"]
        self.platforms = []
        if not count:
            return
        mat = self.material("Platform", spec_lib.THEME_PRESETS[self.theme]["wall"], roughness=0.7, surface_scale=10.0)
        edge = self.glow("Edge", self.world["accent_color"], strength=1.4)

        def build(name):
            shape = ShapeBuilder()
            shape.use(0).box((2.8, 2.8, 0.5))
            shape.use(1).box((2.86, 2.86, 0.1), at=(0.0, 0.0, -0.05))
            return shape.finish(name, [mat, edge])

        mesh = self.mesh("Platform", build)
        # A rising arc of stepping stones beside the spawn point.
        radius = self.half * 0.42
        start = self.rng.uniform(0.0, math.tau)
        for index in range(count):
            angle = start + index * 0.55
            x, y = math.cos(angle) * radius, math.sin(angle) * radius
            top = self.ground_z(x, y) + 1.0 + 0.75 * index
            platform = self.obj("AI_Platform_%02d" % (index + 1), mesh, (x, y, top - 0.25), "World")
            components.add_collider(platform, tag="Ground")
            optimization.mark_static_object(platform)
            optimization.mark_instancing_candidate(platform)
            self.platforms.append(Vector((x, y, top)))
            self.occupied.append((x, y, 1.6))

    # -- props -------------------------------------------------------------

    def prop_scale(self, kind):
        if kind == "BUILDING":
            return (1.0, 1.0, self.rng.uniform(0.7, 1.9))
        if kind == "ROCK":
            return (self.rng.uniform(0.7, 1.6), self.rng.uniform(0.7, 1.4), self.rng.uniform(0.6, 1.2))
        return self.rng.uniform(0.8, 1.25)

    def prop_mesh(self, kind):
        theme = self.theme
        accent = self.world["accent_color"]
        wood = self.material("Wood", "#5a3b22", roughness=0.85, surface_scale=8.0)
        stone_color = {
            "DESERT": "#b8946a", "VOLCANO": "#2b2524", "SPACE": "#6d6480", "SNOW": "#9fb0bf", "CANDY": "#c9a0ff",
        }.get(theme, "#7c7f80")
        stone = self.material("Stone", stone_color, roughness=0.8, surface_scale=12.0)
        leaf_color = {
            "SNOW": "#2f5a43", "CANDY": "#ff6fb5", "DESERT": "#6b8f3a", "ISLAND": "#2fa14a",
        }.get(theme, "#2f7d3a")
        leaves = self.material("Leaves", leaf_color, roughness=0.9)

        def tree(name):
            shape = ShapeBuilder()
            shape.use(0).cylinder(0.16, 1.7, at=(0.0, 0.0, 0.85), segments=8)
            shape.use(1, smooth=True).ico(1.05, at=(0.0, 0.0, 2.2), scale=(1.0, 1.0, 0.9))
            shape.ico(0.7, at=(0.25, 0.1, 2.95))
            return shape.finish(name, [wood, leaves])

        def pine(name):
            shape = ShapeBuilder()
            shape.use(0).cylinder(0.13, 1.0, at=(0.0, 0.0, 0.5), segments=8)
            shape.use(1)
            for radius, z in ((1.15, 1.35), (0.9, 2.05), (0.62, 2.7)):
                shape.cone(radius, 0.05, 1.3, at=(0.0, 0.0, z), segments=10)
            snow = self.material("Snowcap", "#f4f8ff", roughness=0.6)
            if theme == "SNOW":
                shape.use(2).cone(0.34, 0.02, 0.45, at=(0.0, 0.0, 3.25), segments=10)
                return shape.finish(name, [wood, leaves, snow])
            return shape.finish(name, [wood, leaves])

        def palm(name):
            shape = ShapeBuilder()
            shape.use(0).cone(0.2, 0.12, 3.4, at=(0.0, 0.0, 1.7), segments=8)
            shape.use(1)
            for index in range(6):
                angle = index * math.tau / 6.0
                shape.box((2.1, 0.42, 0.06), at=(math.cos(angle) * 0.95, math.sin(angle) * 0.95, 3.3),
                          rotation=(("Z", angle), ("Y", math.radians(18.0))))
            return shape.finish(name, [wood, leaves])

        def rock(name):
            shape = ShapeBuilder()
            shape.use(0, smooth=True).ico(0.8, scale=(1.3, 1.0, 0.7), at=(0.0, 0.0, 0.25))
            return shape.finish(name, [stone])

        def cactus(name):
            green = self.material("Cactus", "#3f8f4a", roughness=0.75)
            shape = ShapeBuilder()
            shape.use(0, smooth=True).cylinder(0.28, 2.3, at=(0.0, 0.0, 1.15), segments=10)
            shape.cylinder(0.16, 0.7, at=(0.42, 0.0, 1.2), segments=8, rotation=(("Y", math.pi / 2),))
            shape.cylinder(0.16, 0.8, at=(0.7, 0.0, 1.55), segments=8)
            shape.cylinder(0.14, 0.6, at=(-0.38, 0.0, 0.95), segments=8, rotation=(("Y", math.pi / 2),))
            shape.cylinder(0.14, 0.6, at=(-0.62, 0.0, 1.22), segments=8)
            return shape.finish(name, [green])

        def building(name):
            facade = self.material("Facade", {"NEON_CITY": "#232838"}.get(theme, "#6f6a64"), roughness=0.6,
                                   metallic=0.2, surface_scale=6.0)
            windows = self.glow("Windows", accent, strength=3.0)
            shape = ShapeBuilder()
            shape.use(0).box((4.0, 4.0, 10.0), at=(0.0, 0.0, 5.0))
            shape.use(1)
            for z in (2.2, 4.2, 6.2, 8.2):
                shape.box((4.06, 4.06, 0.22), at=(0.0, 0.0, z))
            shape.use(0).box((3.0, 3.0, 0.6), at=(0.0, 0.0, 10.3))
            return shape.finish(name, [facade, windows])

        def crystal(name):
            glow = self.glow("Crystal", accent, strength=3.2, roughness=0.15)
            shape = ShapeBuilder()
            shape.use(0).cone(0.42, 0.0, 1.9, at=(0.0, 0.0, 0.95), segments=6)
            shape.cone(0.26, 0.0, 1.1, at=(0.45, 0.1, 0.5), segments=6, rotation=(("Y", 0.45),))
            shape.cone(0.22, 0.0, 0.9, at=(-0.35, -0.2, 0.4), segments=6, rotation=(("X", 0.5),))
            return shape.finish(name, [glow])

        def pillar(name):
            shape = ShapeBuilder()
            shape.use(0).box((1.3, 1.3, 0.4), at=(0.0, 0.0, 0.2))
            shape.use(0, smooth=True).cylinder(0.45, 3.6, at=(0.0, 0.0, 2.2), segments=14)
            shape.use(0, smooth=False).box((1.3, 1.3, 0.35), at=(0.0, 0.0, 4.15))
            return shape.finish(name, [stone])

        def crate(name):
            band = self.material("CrateBand", "#3b2a1a", roughness=0.8)
            shape = ShapeBuilder()
            shape.use(0).box((1.0, 1.0, 1.0), at=(0.0, 0.0, 0.5))
            shape.use(1).box((1.04, 1.04, 0.12), at=(0.0, 0.0, 0.5))
            return shape.finish(name, [wood, band])

        def lamp(name):
            metal = self.material("Metal", "#3a3d44", roughness=0.4, metallic=0.8)
            bulb = self.glow("LampBulb", accent, strength=6.0)
            shape = ShapeBuilder()
            shape.use(0).cylinder(0.07, 3.3, at=(0.0, 0.0, 1.65), segments=8)
            shape.use(1, smooth=True).sphere(0.24, at=(0.0, 0.0, 3.4))
            return shape.finish(name, [metal, bulb])

        def mushroom(name):
            stem = self.material("MushroomStem", "#f3ead8", roughness=0.8)
            cap = self.material("MushroomCap", accent if theme == "CANDY" else "#d63a2f", roughness=0.6)
            shape = ShapeBuilder()
            shape.use(0, smooth=True).cylinder(0.2, 0.95, at=(0.0, 0.0, 0.47), segments=10)
            shape.use(1).sphere(0.75, at=(0.0, 0.0, 1.0), scale=(1.0, 1.0, 0.55))
            return shape.finish(name, [stem, cap])

        builders = {
            "TREE": tree, "PINE": pine, "PALM": palm, "ROCK": rock, "CACTUS": cactus, "BUILDING": building,
            "CRYSTAL": crystal, "PILLAR": pillar, "CRATE": crate, "LAMP": lamp, "MUSHROOM": mushroom,
        }
        return self.mesh("Prop_" + kind, builders[kind])

    def build_props(self, avoid):
        lamps = []
        for group in self.spec["props"]:
            kind = group["kind"]
            mesh = self.prop_mesh(kind)
            inner = self.half * 0.5 if kind in BIG_PROPS else 0.0
            points = self.scatter(group["count"], PROP_SPACING[kind], avoid=avoid, inner=inner,
                                  extent=self.half * 0.9, outer=self.half * 1.2)
            for index, (x, y) in enumerate(points):
                prop = self.obj("AI_%s_%02d" % (kind.title(), index + 1), mesh, (x, y, self.ground_z(x, y)), "World",
                                rotation=(0.0, 0.0, self.rng.uniform(0.0, math.tau)), scale=self.prop_scale(kind))
                optimization.mark_static_object(prop)
                optimization.mark_instancing_candidate(prop)
                if kind in {"TREE", "PINE", "PALM", "BUILDING", "ROCK"}:
                    optimization.add_lod_group(prop)
                if kind == "LAMP":
                    lamps.append(prop)
        for lamp in lamps[:3]:
            self.point_light(lamp.location + Vector((0.0, 0.0, 3.4)), self.world["accent_color"], 120.0, 6.0)

    # -- actors ------------------------------------------------------------

    def player_mesh(self, shape_name, color):
        body = self.material("Player", color, roughness=0.35, metallic=0.15)
        visor = self.glow("PlayerVisor", self.world["accent_color"], strength=3.0)

        def build(name):
            shape = ShapeBuilder()
            if shape_name == "ROBOT":
                shape.use(0).box((0.8, 0.55, 0.9), at=(0.0, 0.0, -0.05))
                shape.box((0.56, 0.5, 0.45), at=(0.0, 0.0, 0.62))
                shape.box((0.22, 0.24, 0.5), at=(-0.2, 0.0, -0.66))
                shape.box((0.22, 0.24, 0.5), at=(0.2, 0.0, -0.66))
                shape.use(1).box((0.42, 0.06, 0.12), at=(0.0, 0.26, 0.66))
            elif shape_name == "CUBE":
                shape.use(0).box((1.0, 1.0, 1.0))
                shape.use(1).box((0.6, 0.06, 0.16), at=(0.0, 0.5, 0.18))
            elif shape_name == "SPHERE":
                shape.use(0, smooth=True).sphere(0.5, segments=24, rings=12)
                shape.use(1, smooth=False).box((0.5, 0.08, 0.12), at=(0.0, 0.46, 0.14))
            else:
                shape.use(0, smooth=True).cylinder(0.4, 1.0, segments=20)
                shape.sphere(0.4, at=(0.0, 0.0, 0.5))
                shape.sphere(0.4, at=(0.0, 0.0, -0.5))
                shape.use(1, smooth=False).box((0.5, 0.1, 0.18), at=(0.0, 0.36, 0.52))
            return shape.finish(name, [body, visor])

        return self.mesh("Player_" + shape_name, build)

    def build_player(self, spawn):
        spec = self.spec["player"]
        half_height = PLAYER_HALF_HEIGHT[spec["shape"]]
        location = (spawn.x, spawn.y, spawn.z + half_height)
        player = self.obj("AI_Player", self.player_mesh(spec["shape"], spec["color"]), location, "Actors")
        player["blendengine_display_name"] = spec["name"]
        components.add_player_controller(player)
        controller = player.blendengine_object.player_controller
        controller.controller_type = {
            "THIRD_PERSON": "THIRD_PERSON", "FIRST_PERSON": "FIRST_PERSON",
            "TOP_DOWN": "TOP_DOWN", "SIDE_VIEW": "SIDE_SCROLLER",
        }[self.spec["camera"]]
        controller.walk_speed = spec["walk_speed"]
        controller.run_speed = spec["run_speed"]
        controller.jump_force = spec["jump_force"]
        controller.sprint = spec["run_speed"] > spec["walk_speed"]
        components.add_collider(player, tag="Player")
        health = components.add_health(player, max_health=spec["max_health"])
        health.game_over_on_death = True
        optimization.mark_dynamic_object(player)
        utils.ensure_basic_animation_states(player)

        enemies = spec_lib.total_count(self.spec["enemies"])
        self.add_variable(player, "Score", 0, "Points from pickups and defeated enemies.")
        self.add_variable(player, "Collected", 0, "Pickups collected this run.")
        self.add_variable(player, "Kills", 0, "Enemies defeated this run.")
        if spec["can_shoot"]:
            self.add_variable(player, "Ammo", 60 + enemies * 10, "Shots left. F or left mouse fires.")
        else:
            # An empty attack key tells the runtime this game has no attack.
            controller.attack_key = ""
        self.player = player

    def add_variable(self, obj, name, value, description):
        variable = obj.blendengine_object.variables.add()
        variable.name = name
        variable.variable_type = "INT"
        variable.int_value = int(value)
        variable.description = description
        return variable

    def enemy_mesh(self, shape_name, color):
        key = "Enemy_%s_%s" % (shape_name, color.strip("#"))
        body = self.material("Enemy_%s" % color.strip("#"), color, roughness=0.5,
                             alpha=0.65 if shape_name == "GHOST" else 1.0)
        eyes = self.glow("EnemyEyes", "#ffef5a" if self.world["time_of_day"] != "NIGHT" else "#ff3b3b", strength=4.0)

        def build(name):
            shape = ShapeBuilder()
            if shape_name == "BLOB":
                shape.use(0, smooth=True).sphere(0.5, scale=(1.0, 1.0, 0.75))
                shape.use(1).sphere(0.08, at=(-0.16, 0.42, 0.12)).sphere(0.08, at=(0.16, 0.42, 0.12))
            elif shape_name == "ROBOT":
                shape.use(0).box((0.85, 0.6, 0.95), at=(0.0, 0.0, -0.1))
                shape.box((0.6, 0.55, 0.45), at=(0.0, 0.0, 0.62))
                shape.box((0.2, 0.2, 0.75), at=(-0.55, 0.0, -0.05)).box((0.2, 0.2, 0.75), at=(0.55, 0.0, -0.05))
                shape.use(1).box((0.4, 0.06, 0.1), at=(0.0, 0.28, 0.66))
            elif shape_name == "SPIKY":
                shape.use(0, smooth=True).ico(0.5, subdivisions=2)
                shape.use(0, smooth=False)
                for axis, angle in (("X", -math.pi / 2), ("X", math.pi / 2), ("Y", math.pi / 2), ("Y", -math.pi / 2), ("X", 0.0)):
                    direction = Matrix.Rotation(angle, 4, axis) @ Vector((0.0, 0.0, 0.62))
                    shape.cone(0.14, 0.0, 0.42, at=direction, segments=6, rotation=((axis, angle),))
                shape.use(1).sphere(0.08, at=(-0.15, 0.45, 0.15)).sphere(0.08, at=(0.15, 0.45, 0.15))
            elif shape_name == "GHOST":
                shape.use(0, smooth=True).sphere(0.45, at=(0.0, 0.0, 0.3))
                shape.cone(0.48, 0.42, 0.9, at=(0.0, 0.0, -0.3), segments=16)
                shape.use(1).sphere(0.08, at=(-0.15, 0.4, 0.38)).sphere(0.08, at=(0.15, 0.4, 0.38))
            elif shape_name == "DRONE":
                shape.use(0, smooth=True).sphere(0.32)
                shape.use(1).torus(0.6, 0.05, major_segments=24, minor_segments=6)
                shape.sphere(0.07, at=(0.0, 0.3, 0.05))
            else:  # BRUTE
                shape.use(0, smooth=True).cylinder(0.38, 0.95, at=(0.0, 0.0, -0.15), segments=16)
                shape.sphere(0.38, at=(0.0, 0.0, -0.62))
                shape.sphere(0.3, at=(0.0, 0.0, 0.6))
                shape.use(0, smooth=False).box((0.18, 0.2, 0.75), at=(-0.5, 0.05, -0.05)).box((0.18, 0.2, 0.75), at=(0.5, 0.05, -0.05))
                shape.use(1).sphere(0.06, at=(-0.11, 0.27, 0.66)).sphere(0.06, at=(0.11, 0.27, 0.66))
            return shape.finish(name, [body, eyes])

        return self.mesh(key, build)

    def build_enemies(self, avoid):
        player = self.player
        enemy_avoid = list(avoid) + [(self.spawn.x, self.spawn.y, 9.0)]
        for group_index, group in enumerate(self.spec["enemies"]):
            mesh = self.enemy_mesh(group["shape"], group["color"])
            size = group["size"]
            if self.is_2d:
                xs = sorted(self.rng.uniform(10.0, self.level_length - 4.0) for _ in range(group["count"]))
                points = [(x, 0.0) for x in xs]
            else:
                points = self.scatter(group["count"], max(3.0, size * 2.5), avoid=enemy_avoid)
            behavior = group["behavior"]
            template = behavior
            if behavior == "FOLLOW_PLAYER" and group["damage"] > 0.0:
                template = "ATTACK"
            for index, (x, y) in enumerate(points):
                half = ENEMY_HALF_HEIGHT[group["shape"]] * size
                z = self.ground_z(x, y) + half + ENEMY_HOVER.get(group["shape"], 0.0) * size
                name = "AI_%s_%02d" % (_sanitize(group["name"])[:24], index + 1)
                enemy = self.obj(name, mesh, (x, y, z), "Actors", rotation=(0.0, 0.0, self.rng.uniform(0.0, math.tau)),
                                 scale=size)
                enemy["blendengine_display_name"] = group["name"]
                components.add_collider(enemy, tag="Enemy")
                components.add_health(enemy, max_health=group["health"])
                npc = components.add_npc_behavior(enemy, template, target=player)
                npc.move_speed = group["speed"]
                npc.detection_range = 26.0 if behavior == "ENEMY_BOSS" else 16.0
                npc.attack_range = max(1.2, size * 0.9 + 0.5)
                npc.patrol_radius = 2.0 + self.rng.uniform(0.0, 3.0) * (0.6 if self.is_2d else 1.0)
                npc.attack_damage = group["damage"]
                optimization.mark_dynamic_object(enemy)
                optimization.mark_instancing_candidate(enemy)
                utils.ensure_basic_animation_states(enemy)
                if template in {"PATROL", "GUARD_AREA", "IDLE", "FLEE"} and group["damage"] > 0.0:
                    self.behavior(enemy, "Contact Damage", "ON_COLLISION", tag="Player", actions=[
                        ("CHANGE_HEALTH", {"number_value": -group["damage"], "target_object": player}),
                        ("SHOW_LOG", {"text_value": "%s hit you!" % group["name"]}),
                    ])

    def behavior(self, obj, name, event_type, tag="", timer=0.0, conditions=(), actions=(), description=""):
        settings = utils.mark_game_object(obj)
        behavior = settings.behaviors.add()
        behavior.name = name
        behavior.description = description or name
        event = behavior.events.add()
        event.name = event_type.replace("_", " ").title()
        event.event_type = event_type
        event.tag = tag
        event.timer_seconds = timer
        for condition_type, values in conditions:
            condition = behavior.conditions.add()
            condition.name = condition_type.replace("_", " ").title()
            condition.condition_type = condition_type
            for key, value in values.items():
                setattr(condition, key, value)
        for action_type, values in actions:
            action = behavior.actions.add()
            action.name = action_type.replace("_", " ").title()
            action.action_type = action_type
            for key, value in values.items():
                setattr(action, key, value)
        settings.active_behavior_index = len(settings.behaviors) - 1
        return behavior

    # -- pickups & hazards -------------------------------------------------

    def collectible_mesh(self, shape_name, color):
        key = "Pickup_%s_%s" % (shape_name, color.strip("#"))
        mat = self.material("Pickup_%s" % color.strip("#"), color, roughness=0.25, metallic=0.6,
                            emission=color, emission_strength=0.9)
        accent = self.glow("PickupAccent", self.world["accent_color"], strength=2.0)

        def build(name):
            shape = ShapeBuilder()
            stand = (("X", math.pi / 2),)
            if shape_name == "GEM":
                shape.use(0).cone(0.3, 0.0, 0.42, at=(0.0, 0.0, 0.21), segments=6)
                shape.cone(0.0, 0.3, 0.3, at=(0.0, 0.0, -0.15), segments=6)
            elif shape_name == "STAR":
                shape.use(0).star(0.42, 0.18, 0.14, rotation=stand)
            elif shape_name == "ORB":
                shape.use(0, smooth=True).sphere(0.28)
                shape.use(1).torus(0.42, 0.03, major_segments=24, minor_segments=6, rotation=(("X", 1.1),))
            elif shape_name == "KEY":
                shape.use(0).torus(0.17, 0.05, major_segments=16, minor_segments=6, rotation=stand, at=(0.0, 0.0, 0.25))
                shape.box((0.08, 0.08, 0.5), at=(0.0, 0.0, -0.1))
                shape.box((0.16, 0.08, 0.06), at=(0.08, 0.0, -0.28)).box((0.12, 0.08, 0.06), at=(0.06, 0.0, -0.16))
            elif shape_name == "CRATE":
                shape.use(0).box((0.6, 0.6, 0.6))
                shape.use(1).box((0.64, 0.64, 0.08))
            else:  # COIN
                shape.use(0, smooth=True).cylinder(0.34, 0.08, segments=24, rotation=stand)
            return shape.finish(name, [mat, accent])

        return self.mesh(key, build)

    def place_trigger(self, obj, tag, visible=True):
        components.add_trigger_zone(obj)
        obj.blendengine_object.object_tag = tag
        if visible:
            obj.display_type = "TEXTURED"
            obj.show_in_front = False
            obj["blendengine_visible_trigger"] = True

    def build_collectibles(self, avoid):
        spots = list(getattr(self, "platforms", []))
        self.rng.shuffle(spots)
        for group in self.spec["collectibles"]:
            mesh = self.collectible_mesh(group["shape"], group["color"])
            count = group["count"]
            locations = []
            while spots and len(locations) < count // 3 + 1 and len(locations) < count:
                spot = spots.pop()
                locations.append(Vector((spot.x, spot.y, spot.z + 0.9)))
            remaining = count - len(locations)
            if self.is_2d:
                for _ in range(remaining):
                    x = self.rng.uniform(4.0, self.level_length - 3.0)
                    locations.append(Vector((x, 0.0, 0.9)))
            else:
                for x, y in self.scatter(remaining, 2.4, avoid=avoid):
                    locations.append(Vector((x, y, self.ground_z(x, y) + 0.9)))
            for index, location in enumerate(locations):
                name = "AI_%s_%02d" % (_sanitize(group["name"])[:24], index + 1)
                pickup = self.obj(name, mesh, location, "Pickups", rotation=(0.0, 0.0, self.rng.uniform(0.0, math.tau)))
                pickup["blendengine_display_name"] = group["name"]
                self.place_trigger(pickup, "Pickup")
                utils.ensure_component(pickup, "PICKUP_ITEM")
                optimization.mark_dynamic_object(pickup)
                optimization.mark_instancing_candidate(pickup)
                self.behavior(pickup, "Collect %s" % group["name"], "ON_ENTER_TRIGGER", tag="Player", actions=[
                    ("ADD_VARIABLE", {"variable_name": "Collected", "number_value": 1.0}),
                    ("ADD_VARIABLE", {"variable_name": "Score", "number_value": float(group["points"])}),
                    ("COLLECT_OBJECT", {}),
                    ("SHOW_LOG", {"text_value": "+%d  %s" % (group["points"], group["name"])}),
                ])
                self.behavior(pickup, "Spin", "ON_UPDATE", actions=[("ROTATE_OBJECT", {"number_value": 2.2})])

    def build_health_pickups(self, avoid):
        count = self.spec["health_pickups"]
        if not count:
            return
        mat = self.glow("HealthPickup", "#29e07a", strength=2.2)

        def build(name):
            shape = ShapeBuilder()
            shape.use(0).box((0.6, 0.18, 0.2)).box((0.2, 0.18, 0.6))
            return shape.finish(name, [mat])

        mesh = self.mesh("HealthPickup", build)
        if self.is_2d:
            points = [(self.rng.uniform(8.0, self.level_length - 6.0), 0.0) for _ in range(count)]
        else:
            points = self.scatter(count, 4.0, avoid=avoid)
        for index, (x, y) in enumerate(points):
            pickup = self.obj("AI_HealthPickup_%02d" % (index + 1), mesh, (x, y, self.ground_z(x, y) + 0.9), "Pickups")
            self.place_trigger(pickup, "Health")
            utils.ensure_component(pickup, "PICKUP_ITEM")
            optimization.mark_dynamic_object(pickup)
            self.behavior(pickup, "Heal Player", "ON_ENTER_TRIGGER", tag="Player", actions=[
                ("CHANGE_HEALTH", {"number_value": 30.0, "target_object": self.player}),
                ("COLLECT_OBJECT", {}),
                ("SHOW_LOG", {"text_value": "+30 health"}),
            ])
            self.behavior(pickup, "Spin", "ON_UPDATE", actions=[("ROTATE_OBJECT", {"number_value": 1.6})])

    def hazard_mesh(self, kind):
        def lava(name):
            mat = self.glow("Lava", "#ff5a14", strength=5.0, roughness=0.5)
            crust = self.material("LavaCrust", "#2a1a14", roughness=0.9)
            shape = ShapeBuilder()
            shape.use(1).cylinder(1.75, 0.1, segments=20, at=(0.0, 0.0, 0.02))
            shape.use(0).cylinder(1.5, 0.08, segments=20, at=(0.0, 0.0, 0.07))
            return shape.finish(name, [mat, crust])

        def spikes(name):
            base = self.material("SpikeBase", "#2b2b30", roughness=0.7)
            metal = self.material("SpikeMetal", "#b9c0c8", roughness=0.25, metallic=0.9)
            shape = ShapeBuilder()
            shape.use(0).box((2.6, 2.6, 0.12), at=(0.0, 0.0, 0.06))
            shape.use(1)
            for ix in (-0.8, 0.0, 0.8):
                for iy in (-0.8, 0.0, 0.8):
                    shape.cone(0.22, 0.0, 0.62, at=(ix, iy, 0.43), segments=6)
            return shape.finish(name, [base, metal])

        def poison(name):
            mat = self.material("Poison", "#57ff3a", roughness=0.2, alpha=0.8, emission="#2fd61c", emission_strength=1.8)
            shape = ShapeBuilder()
            shape.use(0, smooth=True).cylinder(1.6, 0.08, segments=20, at=(0.0, 0.0, 0.04))
            for x, y, r in ((0.5, 0.3, 0.16), (-0.6, -0.2, 0.12), (0.1, -0.7, 0.1)):
                shape.sphere(r, at=(x, y, 0.1))
            return shape.finish(name, [mat])

        def laser(name):
            post = self.material("LaserPost", "#30343c", roughness=0.4, metallic=0.7)
            beam = self.glow("LaserBeam", "#ff2a3c", strength=8.0)
            shape = ShapeBuilder()
            shape.use(0).box((0.22, 0.22, 1.5), at=(-1.5, 0.0, 0.75)).box((0.22, 0.22, 1.5), at=(1.5, 0.0, 0.75))
            shape.use(1).box((3.0, 0.05, 0.05), at=(0.0, 0.0, 0.5)).box((3.0, 0.05, 0.05), at=(0.0, 0.0, 1.05))
            return shape.finish(name, [post, beam])

        return self.mesh("Hazard_" + kind, {"LAVA": lava, "SPIKES": spikes, "POISON": poison, "LASER": laser}[kind])

    def build_hazards(self, avoid):
        hazard_avoid = list(avoid) + [(self.spawn.x, self.spawn.y, 6.0)]
        for group in self.spec["hazards"]:
            mesh = self.hazard_mesh(group["kind"])
            if self.is_2d:
                xs = [self.rng.uniform(8.0, self.level_length - 6.0) for _ in range(group["count"])]
                points = [(x, 0.0) for x in xs]
            else:
                points = self.scatter(group["count"], 4.5, avoid=hazard_avoid)
            for index, (x, y) in enumerate(points):
                rotation = (0.0, 0.0, 0.0 if self.is_2d else self.rng.uniform(0.0, math.pi))
                hazard = self.obj("AI_%s_%02d" % (group["kind"].title(), index + 1), mesh,
                                  (x, y, self.ground_z(x, y)), "World", rotation=rotation)
                hazard["blendengine_display_name"] = group["name"]
                self.place_trigger(hazard, "Damage")
                optimization.mark_static_object(hazard)
                optimization.mark_instancing_candidate(hazard)
                self.behavior(hazard, "Hurt Player", "ON_ENTER_TRIGGER", tag="Player", actions=[
                    ("CHANGE_HEALTH", {"number_value": -group["damage"], "target_object": self.player}),
                    ("SHOW_LOG", {"text_value": "%s: -%d health" % (group["name"], int(group["damage"]))}),
                ])

    # -- goal, director, camera, lights -------------------------------------

    def build_goal(self, exit_point):
        goal = self.spec["goal"]
        messages = self.spec["messages"]
        player = self.player
        target = goal["target_count"]

        if goal["type"] == "REACH_EXIT":
            ring = self.glow("Portal", self.world["accent_color"], strength=4.0)
            veil = self.material("PortalVeil", self.world["accent_color"], roughness=0.1, alpha=0.35,
                                 emission=self.world["accent_color"], emission_strength=1.5)

            def build(name):
                shape = ShapeBuilder()
                stand = (("X", math.pi / 2),)
                shape.use(0, smooth=True).torus(1.35, 0.14, major_segments=40, minor_segments=10, rotation=stand)
                shape.use(1, smooth=False).cylinder(1.25, 0.04, segments=32, rotation=stand)
                return shape.finish(name, [ring, veil])

            portal = self.obj("AI_Exit_Portal", self.mesh("Portal", build),
                              (exit_point.x, exit_point.y, exit_point.z + 1.6), "World")
            self.place_trigger(portal, "Goal")
            conditions = []
            if target > 0:
                conditions.append(("VARIABLE_COMPARE", {"variable_name": "Collected", "compare": "GREATER_EQUAL",
                                                        "number_value": float(target)}))
            self.behavior(portal, "Reach Exit", "ON_ENTER_TRIGGER", tag="Player", conditions=conditions,
                          actions=[("WIN_GAME", {"text_value": messages["win"]})])
            self.point_light(portal.location, self.world["accent_color"], 220.0, 3.0)
            self.label(goal["description"], portal.location + Vector((0.0, 0.0, 2.2)))
        elif goal["type"] == "COLLECT_ALL":
            self.behavior(player, "Win: Collect", "ON_UPDATE", conditions=[
                ("VARIABLE_COMPARE", {"variable_name": "Collected", "compare": "GREATER_EQUAL", "number_value": float(max(1, target))}),
            ], actions=[("WIN_GAME", {"text_value": messages["win"]})])
        elif goal["type"] == "DEFEAT_ALL":
            self.behavior(player, "Win: Defeat All", "ON_UPDATE", conditions=[
                ("VARIABLE_COMPARE", {"variable_name": "Kills", "compare": "GREATER_EQUAL", "number_value": float(max(1, target))}),
            ], actions=[("WIN_GAME", {"text_value": messages["win"]})])
        # SURVIVE is handled by the director's timer.

        label_at = self.spawn + (Vector((4.0, 1.0, 3.4)) if self.is_2d else Vector((0.0, 9.0, 3.4)))
        if goal["type"] != "REACH_EXIT":
            self.label(goal["description"], label_at)

    def build_director(self):
        director = bpy.data.objects.new("AI_GameDirector", None)
        self.collection("World").objects.link(director)
        director.location = self.spawn + Vector((0.0, 0.0, 3.0))
        director.empty_display_type = "SPHERE"
        director.empty_display_size = 0.4
        utils.mark_game_object(director, tag="Director")
        self.created.append(director)
        goal = self.spec["goal"]
        messages = self.spec["messages"]
        self.behavior(director, "Intro", "ON_START", actions=[
            ("SHOW_LOG", {"text_value": "%s — %s" % (messages["intro"], goal["description"])}),
        ])
        seconds = goal["time_limit_seconds"]
        if goal["type"] == "SURVIVE":
            self.behavior(director, "Win: Survive", "ON_TIMER", timer=seconds, actions=[
                ("WIN_GAME", {"text_value": messages["win"]}),
            ])
        elif seconds > 0.0:
            self.behavior(director, "Time Limit", "ON_TIMER", timer=seconds, actions=[
                ("GAME_OVER", {"text_value": messages["lose"]}),
            ])
        self.director = director

    def build_camera(self, spawn):
        camera_type = self.spec["camera"]
        data = bpy.data.cameras.new("AI_GameCamera")
        player_location = self.player.location.copy()
        if camera_type == "FIRST_PERSON":
            location = player_location + Vector((0.0, 0.0, 0.72))
            rotation = (math.radians(90.0), 0.0, 0.0)
            data.lens = 26
        elif camera_type == "TOP_DOWN":
            location = player_location + Vector((0.0, -5.0, 17.0))
            rotation = (player_location - location).to_track_quat("-Z", "Y").to_euler()
            data.lens = 35
        elif camera_type == "SIDE_VIEW":
            location = player_location + Vector((0.0, -20.0, 2.0))
            rotation = (math.radians(90.0), 0.0, 0.0)
            data.type = "ORTHO"
            data.ortho_scale = 15.0
        else:
            location = player_location + Vector((0.0, -8.5, 4.6))
            rotation = (player_location - location).to_track_quat("-Z", "Y").to_euler()
            data.lens = 30
        data.clip_end = max(200.0, self.world["size"] * 4.0)
        camera = self.obj("AI_GameCamera", data, location, "Actors", rotation=tuple(rotation))
        self.scene.camera = camera
        self.player.blendengine_object.player_controller.camera_follow = camera
        utils.ensure_component(camera, "CAMERA_CONTROLLER", tag="MainCamera")
        if camera_type == "FIRST_PERSON" and self.spec["player"]["can_shoot"]:
            self.build_weapon(camera)
        self.camera = camera

    def build_weapon(self, camera):
        metal = self.material("Blaster", "#2d3038", roughness=0.35, metallic=0.85)
        glow = self.glow("BlasterGlow", self.world["accent_color"], strength=4.0)

        def build(name):
            shape = ShapeBuilder()
            shape.use(0).box((0.09, 0.42, 0.11), at=(0.0, 0.0, 0.0))
            shape.box((0.07, 0.12, 0.16), at=(0.0, -0.12, -0.11), rotation=(("X", 0.25),))
            shape.use(1).box((0.1, 0.3, 0.03), at=(0.0, 0.02, 0.07))
            return shape.finish(name, [metal, glow])

        weapon = self.obj("AI_Blaster", self.mesh("Blaster", build), (0.0, 0.0, 0.0), "Actors")
        weapon.parent = camera
        # Camera space: -Z forward, +Y up.
        weapon.location = (0.2, -0.16, -0.45)
        weapon.rotation_euler = (math.radians(90.0), 0.0, 0.0)
        utils.mark_game_object(weapon, tag="Weapon")

    def point_light(self, location, color, energy, radius):
        if self.point_lights >= MAX_POINT_LIGHTS:
            return None
        self.point_lights += 1
        data = bpy.data.lights.new("AI_Light_%d" % self.point_lights, "POINT")
        data.energy = energy
        data.color = spec_lib.hex_to_linear(color) if isinstance(color, str) else color
        data.shadow_soft_size = radius
        if hasattr(data, "use_shadow"):
            data.use_shadow = False
        light = self.obj("AI_Light_%d" % self.point_lights, data, location, "Lights")
        return light

    def build_lights(self, spawn, exit_point):
        energy, color, elevation, _strength = TIME_OF_DAY_LIGHT[self.world["time_of_day"]]
        sun_data = bpy.data.lights.new("AI_Sun", "SUN")
        sun_data.energy = energy
        sun_data.color = color
        if hasattr(sun_data, "angle"):
            sun_data.angle = math.radians(4.0)
        sun = self.obj("AI_Sun", sun_data, (0.0, 0.0, 20.0), "Lights",
                       rotation=(math.radians(90.0 - elevation), 0.0, math.radians(35.0)))
        optimization.mark_baked_lighting_candidate(sun)

        fill_data = bpy.data.lights.new("AI_SkyFill", "AREA")
        fill_data.energy = {"DAY": 220.0, "SUNSET": 160.0, "NIGHT": 260.0}[self.world["time_of_day"]]
        fill_data.size = 12.0
        fill_data.color = spec_lib.hex_to_linear(self.world["sky_color"])
        if hasattr(fill_data, "use_shadow"):
            fill_data.use_shadow = False
        self.obj("AI_SkyFill", fill_data, spawn + Vector((0.0, -4.0, 9.0)), "Lights",
                 rotation=(math.radians(25.0), 0.0, 0.0))
        if self.world["time_of_day"] == "NIGHT":
            self.point_light(spawn + Vector((0.0, 2.0, 4.0)), self.world["accent_color"], 300.0, 5.0)
            if not self.is_2d:
                self.point_light(Vector((0.0, 0.0, 6.0)), self.world["accent_color"], 600.0, 8.0)

    def label(self, text, location):
        curve = bpy.data.curves.new("AI_Label", "FONT")
        curve.body = text
        curve.size = 0.5
        curve.align_x = "CENTER"
        curve.align_y = "CENTER"
        label = self.obj("AI_Label", curve, location, "World", rotation=(math.radians(80.0), 0.0, 0.0))
        label.data.materials.append(self.glow("Label", self.world["accent_color"], strength=2.0))
        utils.ensure_component(label, "UI_ELEMENT", tag="WorldLabel")
        return label

    def store_spec(self):
        text = bpy.data.texts.get(SPEC_TEXT_NAME) or bpy.data.texts.new(SPEC_TEXT_NAME)
        text.clear()
        text.write(spec_lib.dumps(self.spec))

    def select_player(self):
        try:
            view_layer = self.scene.view_layers[0]
            for obj in self.scene.objects:
                obj.select_set(False, view_layer=view_layer)
            self.player.select_set(True, view_layer=view_layer)
            view_layer.objects.active = self.player
        except (RuntimeError, IndexError, TypeError):
            pass


def build_game(scene, spec, clean_scene=True):
    """Normalize ``spec`` and build it into ``scene``. Returns a summary dict."""
    normalized, warnings = spec_lib.normalize_spec(spec)
    builder = GameBuilder(scene, normalized)
    result = builder.build(clean_scene=clean_scene)
    result["spec"] = normalized
    result["warnings"] = warnings
    return result


def load_stored_spec():
    text = bpy.data.texts.get(SPEC_TEXT_NAME)
    if text is None:
        return None
    spec, _warnings = spec_lib.normalize_spec(text.as_string())
    return spec
