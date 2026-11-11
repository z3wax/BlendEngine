# SPDX-License-Identifier: GPL-2.0-or-later
#
# Visibility analysis for the Smart Optimizer.
#
# Everything here answers one question with ray casts against the scene's opaque
# static geometry: "from where the game camera can be, what can it see, and how
# closely?" The optimizer only removes or shrinks data this module proves unused
# for the sampled viewpoints, so a renderer never has to pay for it.
#
# The analysis is sampled, not exact: viewpoints lie on a grid (or on the
# animated camera path) and every triangle is probed at a handful of points.
# Results are padded (one ring of neighbouring faces, distance margins) to stay
# on the safe side of that sampling.

import math

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import utils


# Markers that only describe how an object may be optimized. Any other
# component means gameplay can move, hide or change the object at runtime.
_PASSIVE_COMPONENTS = {
    "COLLIDER", "STATIC_OBJECT", "OCCLUDER", "LOD_GROUP", "IMPOSTOR_CANDIDATE",
    "BAKED_LIGHTING_CANDIDATE", "COLLIDER_SIMPLIFICATION", "DISABLE_WHEN_FAR",
    "PHYSICS_SLEEP", "MERGE_CANDIDATE", "INSTANCING_CANDIDATE",
}
_DYNAMIC_TAGS = {"Player", "PlayerBody", "Weapon", "FirstPersonArms", "Enemy", "Zombie", "Coin", "Health", "Damage"}


def _settings(obj):
    return getattr(obj, "blendengine_object", None)


def action_targets(scene):
    """Objects that some no-code behavior can move, hide or otherwise change."""
    targets = set()
    for obj in scene.objects:
        settings = _settings(obj)
        if settings is None:
            continue
        for behavior in settings.behaviors:
            for action in behavior.actions:
                if action.target_object is not None:
                    targets.add(action.target_object.name)
    return targets


def is_dynamic(obj, targets=frozenset()):
    """True when the object's shape or placement cannot be trusted to stay put."""
    settings = _settings(obj)
    if settings is not None:
        opt = settings.optimization
        if opt.dynamic_object and not opt.static_object:
            return True
        if settings.player_controller.enabled or settings.npc_behavior.enabled or settings.health.enabled:
            return True
        if len(settings.behaviors) or settings.object_tag in _DYNAMIC_TAGS:
            return True
        if any(c.component_type not in _PASSIVE_COMPONENTS for c in settings.components):
            return True
    if obj.name in targets:
        return True
    rigid_body = getattr(obj, "rigid_body", None)
    if rigid_body is not None and rigid_body.type == "ACTIVE":
        return True
    animation = obj.animation_data
    if animation is not None and (animation.action is not None or len(animation.drivers) or len(animation.nla_tracks)):
        return True
    if len(obj.constraints) or len(obj.particle_systems):
        return True
    data = obj.data
    if data is not None:
        if getattr(data, "shape_keys", None) is not None:
            return True
        data_animation = getattr(data, "animation_data", None)
        if data_animation is not None and (data_animation.action is not None or len(data_animation.drivers)):
            return True
    if any(mod.type in {"ARMATURE", "CLOTH", "SOFT_BODY", "OCEAN", "WAVE", "NODES", "HOOK", "MESH_CACHE"}
           for mod in obj.modifiers):
        return True
    if obj.parent is not None:
        return obj.parent.type == "ARMATURE" or is_dynamic(obj.parent, targets)
    return False


def material_is_opaque(material):
    """Conservative: anything that might let the camera see through is not opaque."""
    if material is None:
        return True
    if hasattr(material, "surface_render_method"):
        # Blender 4.2+: dithered surfaces are solid unless their alpha says otherwise (checked below).
        if material.surface_render_method == "BLENDED":
            return False
    elif material.blend_method != "OPAQUE":
        return False
    tree = material.node_tree
    if tree is None:
        return True
    for node in tree.nodes:
        if node.type in {"BSDF_TRANSPARENT", "BSDF_GLASS", "BSDF_REFRACTION", "HOLDOUT", "GROUP",
                         "VOLUME_ABSORPTION", "VOLUME_SCATTER", "PRINCIPLED_VOLUME"}:
            return False
        if node.type == "BSDF_PRINCIPLED":
            for name, opaque_value in (("Alpha", 1.0), ("Transmission", 0.0), ("Transmission Weight", 0.0)):
                socket = node.inputs.get(name)
                if socket is None:
                    continue
                if socket.is_linked or abs(socket.default_value - opaque_value) > 1e-4:
                    return False
        if node.type == "OUTPUT_MATERIAL" and node.inputs["Displacement"].is_linked:
            if getattr(material, "displacement_method", "BUMP") != "BUMP":
                return False
    return True


def object_is_occluder(obj):
    if obj.display_type in {"WIRE", "BOUNDS"} or obj.hide_render:
        return False
    if not getattr(obj, "visible_camera", True):
        return False
    slots = obj.material_slots
    return all(material_is_opaque(slot.material) for slot in slots)


class MeshEntry:
    """World-space triangles of one evaluated mesh object."""

    __slots__ = ("obj", "name", "dynamic", "occluder", "editable", "tri_start", "tri_count",
                 "center", "radius", "poly_count")


class World:
    """All mesh triangles of a scene plus a BVH of the static opaque ones."""

    def __init__(self, scene, depsgraph):
        self.scene = scene
        self.entries = []
        targets = action_targets(scene)
        verts, tris, tri_poly, tri_entry = [], [], [], []
        vert_offset = 0
        tri_offset = 0
        for obj in scene.objects:
            if obj.type != "MESH" or obj.data is None or not obj.visible_get() and obj.hide_render:
                continue
            evaluated = obj.evaluated_get(depsgraph)
            try:
                mesh = evaluated.to_mesh()
            except RuntimeError:
                continue
            if mesh is None or not len(mesh.polygons):
                evaluated.to_mesh_clear()
                continue
            mesh.calc_loop_triangles()
            count = len(mesh.loop_triangles)
            co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3).astype(np.float64)
            matrix = np.array(obj.matrix_world, dtype=np.float64)
            co = co @ matrix[:3, :3].T + matrix[:3, 3]
            tri = np.empty(count * 3, dtype=np.int32)
            mesh.loop_triangles.foreach_get("vertices", tri)
            poly = np.empty(count, dtype=np.int32)
            mesh.loop_triangles.foreach_get("polygon_index", poly)
            poly_count = len(mesh.polygons)
            evaluated.to_mesh_clear()

            entry = MeshEntry()
            entry.obj = obj
            entry.name = obj.name
            entry.dynamic = is_dynamic(obj, targets)
            entry.occluder = not entry.dynamic and object_is_occluder(obj)
            # Face indices of the evaluated mesh only match the stored mesh
            # when nothing rebuilds the topology in between. Physics shapes
            # are built from the mesh, so those keep every face too.
            entry.editable = (not entry.dynamic and not len(obj.modifiers)
                              and poly_count == len(obj.data.polygons) and obj.data.library is None
                              and getattr(obj, "rigid_body", None) is None)
            entry.tri_start = tri_offset
            entry.tri_count = count
            entry.poly_count = poly_count
            low, high = co.min(axis=0), co.max(axis=0)
            entry.center = (low + high) * 0.5
            entry.radius = float(np.linalg.norm(high - low) * 0.5)
            self.entries.append(entry)

            verts.append(co)
            tris.append(tri.reshape(-1, 3) + vert_offset)
            tri_poly.append(poly)
            tri_entry.append(np.full(count, len(self.entries) - 1, dtype=np.int32))
            vert_offset += len(co)
            tri_offset += count

        if verts:
            self.verts = np.concatenate(verts)
            self.tris = np.concatenate(tris)
            self.tri_poly = np.concatenate(tri_poly)
            self.tri_entry = np.concatenate(tri_entry)
        else:
            self.verts = np.zeros((0, 3))
            self.tris = np.zeros((0, 3), dtype=np.int32)
            self.tri_poly = np.zeros(0, dtype=np.int32)
            self.tri_entry = np.zeros(0, dtype=np.int32)

        corners = self.verts[self.tris] if len(self.tris) else np.zeros((0, 3, 3))
        self.corners = corners
        self.centroids = corners.mean(axis=1)
        normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        lengths = np.linalg.norm(normals, axis=1)
        self.areas = lengths * 0.5
        self.normals = normals / np.maximum(lengths, 1e-20)[:, None]
        if len(corners):
            self.tri_radius = np.linalg.norm(corners - self.centroids[:, None, :], axis=2).max(axis=1)
        else:
            self.tri_radius = np.zeros(0)

        occluder_entries = np.array([entry.occluder for entry in self.entries], dtype=bool)
        mask = occluder_entries[self.tri_entry] & (self.areas > 1e-12) if len(self.tris) else np.zeros(0, dtype=bool)
        self.bvh_tris = np.nonzero(mask)[0]
        if len(self.bvh_tris):
            used = self.tris[self.bvh_tris]
            self.bvh = BVHTree.FromPolygons(self.verts.tolist(), used.tolist(), all_triangles=True)
        else:
            self.bvh = None

        if len(self.verts):
            self.bounds_min = self.verts.min(axis=0)
            self.bounds_max = self.verts.max(axis=0)
        else:
            self.bounds_min = np.zeros(3)
            self.bounds_max = np.zeros(3)
        self.diagonal = float(np.linalg.norm(self.bounds_max - self.bounds_min)) or 1.0
        self.epsilon = max(1e-4, self.diagonal * 2e-5)

    def clear(self, origin, target):
        """True when nothing opaque lies strictly between two points."""
        if self.bvh is None:
            return True
        direction = target - origin
        distance = direction.length
        if distance <= self.epsilon:
            return True
        hit = self.bvh.ray_cast(origin, direction / distance, distance - self.epsilon)
        return hit[0] is None

    def first_hit_entry(self, origin, target):
        """Index of the mesh entry blocking the segment, or -1 when it is free."""
        if self.bvh is None:
            return -1
        direction = target - origin
        distance = direction.length
        if distance <= self.epsilon:
            return -1
        hit = self.bvh.ray_cast(origin, direction / distance, distance - self.epsilon)
        if hit[0] is None:
            return -1
        return int(self.tri_entry[self.bvh_tris[hit[2]]])


_PARITY_AXES = (Vector((0.013, 0.021, 1.0)).normalized(), Vector((1.0, 0.017, 0.011)).normalized(),
                Vector((0.019, 1.0, 0.023)).normalized())


def enclosing_entries(world, point):
    """Closed meshes the point lies inside, by counting surface crossings along three rays.

    An odd number of crossings on at least two rays means inside; a single
    open sheet such as a ceiling plane never satisfies that.
    """
    votes = {}
    if world.bvh is None:
        return set()
    for axis in _PARITY_AXES:
        crossings = {}
        origin = point.copy()
        for _ in range(96):
            hit = world.bvh.ray_cast(origin, axis)
            if hit[0] is None:
                break
            entry = int(world.tri_entry[world.bvh_tris[hit[2]]])
            crossings[entry] = crossings.get(entry, 0) + 1
            origin = hit[0] + axis * world.epsilon * 2.0
        for entry, count in crossings.items():
            if count % 2:
                votes[entry] = votes.get(entry, 0) + 1
    return {entry for entry, count in votes.items() if count >= 2}


class Vantage:
    """A place something looks from: a camera position, a light or a probe."""

    __slots__ = ("position", "direction", "inverse", "tan_x", "tan_y", "far", "ortho", "cell")

    def __init__(self, position=None, direction=None):
        self.position = position
        self.direction = direction  # Unit vector towards a parallel viewer or sun.
        self.inverse = None         # World-to-camera matrix when a frustum applies.
        self.tan_x = self.tan_y = 0.0
        self.far = 0.0
        self.ortho = False
        self.cell = None            # Grid cell of a play-area vantage.

    def sees(self, point):
        """Frustum test; omnidirectional vantages see every direction."""
        if self.inverse is None:
            return True
        local = self.inverse @ point
        depth = -local.z
        if depth <= 0.0 or depth > self.far:
            return False
        if self.ortho:
            return abs(local.x) <= self.tan_x and abs(local.y) <= self.tan_y
        return abs(local.x) <= depth * self.tan_x and abs(local.y) <= depth * self.tan_y


def camera_optics(camera_obj, width, height):
    """Focal length in pixels and the worst-case off-axis magnification.

    A surface seen at the edge of a perspective image is stretched by
    1 / cos^2 of its angle from the view axis, so the frame corner decides how
    much texture detail a pixel can ever resolve.
    """
    data = camera_obj.data if camera_obj is not None and camera_obj.type == "CAMERA" else None
    angle = data.angle if data is not None and data.type != "ORTHO" else math.radians(50.0)
    half = math.tan(angle * 0.5)
    long_side, short_side = max(width, height), min(width, height)
    focal = (long_side * 0.5) / max(half, 1e-6)
    tan_short = half * short_side / long_side
    return focal, 1.0 + half * half + tan_short * tan_short


def _camera_vantage(camera_obj, aspect, margin):
    data = camera_obj.data
    matrix = camera_obj.matrix_world.copy()
    vantage = Vantage(position=matrix.translation.copy())
    vantage.inverse = matrix.inverted_safe()
    vantage.far = data.clip_end
    wide, tall = (1.0, 1.0 / aspect) if aspect >= 1.0 else (aspect, 1.0)
    if data.type == "ORTHO":
        vantage.ortho = True
        vantage.direction = (matrix.to_quaternion() @ Vector((0.0, 0.0, 1.0))).normalized()
        vantage.tan_x = data.ortho_scale * 0.5 * wide * margin
        vantage.tan_y = data.ortho_scale * 0.5 * tall * margin
    else:
        half = math.tan(data.angle * 0.5)
        vantage.tan_x = half * wide * margin
        vantage.tan_y = half * tall * margin
    return vantage


def camera_path_vantages(scene, world, frame_step=1, margin=1.15):
    """Frustum vantages along the animated scene camera, plus dynamic-object distances.

    Returns (vantages, path_margin, dynamic_distance) where path_margin is half
    the largest camera move between two sampled frames and dynamic_distance
    maps moving mesh objects to their closest approach to the camera.
    """
    camera = scene.camera
    if camera is None or camera.type != "CAMERA":
        return [], 0.0, {}
    aspect = (scene.render.resolution_x * scene.render.pixel_aspect_x) / max(
        1.0, scene.render.resolution_y * scene.render.pixel_aspect_y)
    dynamic = [entry for entry in world.entries if entry.dynamic]
    distances = {}
    vantages = []
    seen = set()
    path_margin = 0.0
    previous = None
    current = scene.frame_current
    frames = range(scene.frame_start, scene.frame_end + 1, max(1, frame_step))
    try:
        for frame in frames:
            scene.frame_set(frame)
            position = camera.matrix_world.translation.copy()
            for entry in dynamic:
                obj = entry.obj
                box = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                center = sum(box, Vector()) / 8.0
                radius = max((corner - center).length for corner in box)
                near = max(0.0, (center - position).length - radius)
                distances[entry.name] = min(distances.get(entry.name, near), near)
            key = tuple(round(value, 4) for row in camera.matrix_world for value in row)
            if previous is not None:
                path_margin = max(path_margin, (position - previous).length * 0.5)
            previous = position
            if key in seen:
                continue
            seen.add(key)
            vantages.append(_camera_vantage(camera, aspect, margin))
    finally:
        scene.frame_set(current)
    return vantages, path_margin, distances


def _ground_points(world, x, y, clearance, walkable=None):
    """Upward-facing surfaces under (x, y) with room for a viewer above them."""
    points = []
    if world.bvh is None:
        return points
    down = Vector((0.0, 0.0, -1.0))
    z = float(world.bounds_max[2]) + 1.0
    ceiling = None
    for _ in range(8):
        hit = world.bvh.ray_cast(Vector((x, y, z)), down)
        if hit[0] is None:
            break
        location, normal = hit[0], hit[1]
        entry = int(world.tri_entry[world.bvh_tris[hit[2]]])
        if (normal.z > 0.3 and (walkable is None or entry in walkable)
                and (ceiling is None or ceiling - location.z >= clearance)):
            points.append(location.copy())
        ceiling = location.z
        z = location.z - 1e-3
    return points


def play_area_vantages(scene, world, spacing=2.0, eye_height=1.6, max_vantages=96, climb_height=1.2):
    """Omnidirectional vantages wherever a player could stand.

    A grid is dropped onto the floor: objects tagged "Ground" when the scene
    has any (that is what the runtime's player walks on), otherwise every
    upward-facing static surface. Only floor connected to the player's start
    by steps of at most `climb_height` counts, so roofs and distant ledges do
    not become viewpoints. The viewer height follows the scene's own player
    and camera rig. Returns (vantages, grid) where grid describes the cell
    lattice: {"origin": (x, y), "step": (x, y)}.
    """
    if world.bvh is None:
        return [], {"origin": (0.0, 0.0), "step": (spacing, spacing)}
    player = utils.find_player_object(scene)
    camera = scene.camera
    rise = Vector((0.0, 0.0, eye_height))
    feet_position = None
    if player is not None:
        under = world.bvh.ray_cast(player.location + Vector((0.0, 0.0, 0.05)), Vector((0.0, 0.0, -1.0)))
        feet = (player.location.z - under[0].z) if under[0] is not None else player.dimensions.z * 0.5
        feet_position = player.location - Vector((0.0, 0.0, feet))
        controller = player.blendengine_object.player_controller
        follow = controller.camera_follow or camera
        if controller.controller_type == "FIRST_PERSON" or follow is None:
            rise = Vector((0.0, 0.0, feet + 0.72))
        else:
            rise = Vector((0.0, 0.0, feet)) + (follow.matrix_world.translation - player.location)
    elif camera is not None:
        feet_position = camera.matrix_world.translation - rise

    walkable = {index for index, entry in enumerate(world.entries)
                if entry.occluder and entry.obj.blendengine_object.object_tag == "Ground"} or None

    # A viewer is never sealed inside a solid, except one the player or camera starts in
    # (a room modelled as a box with outward normals).
    allowed = set()
    for start in (player, camera):
        if start is not None:
            allowed |= enclosing_entries(world, start.matrix_world.translation)

    low, high = world.bounds_min, world.bounds_max
    size_x, size_y = float(high[0] - low[0]), float(high[1] - low[1])
    while True:
        nx = max(1, int(math.ceil(size_x / spacing)))
        ny = max(1, int(math.ceil(size_y / spacing)))
        step_x, step_y = max(size_x / nx, 1e-6), max(size_y / ny, 1e-6)
        floors = {}
        for i in range(nx):
            for j in range(ny):
                x = float(low[0]) + (i + 0.5) * step_x
                y = float(low[1]) + (j + 0.5) * step_y
                points = _ground_points(world, x, y, max(1.0, rise.z), walkable)
                if points:
                    floors[(i, j)] = points

        # Keep the floor a player can walk to from the start position.
        keep = None
        if feet_position is not None:
            start = (int(math.floor((feet_position.x - float(low[0])) / step_x)),
                     int(math.floor((feet_position.y - float(low[1])) / step_y)))
            if start in floors:
                level = min(range(len(floors[start])), key=lambda k: abs(floors[start][k].z - feet_position.z))
                keep = {(start, level)}
                frontier = [(start, level)]
                while frontier:
                    (i, j), level = frontier.pop()
                    height = floors[(i, j)][level].z
                    for di in (-1, 0, 1):
                        for dj in (-1, 0, 1):
                            cell = (i + di, j + dj)
                            for other, point in enumerate(floors.get(cell, ())):
                                if (cell, other) not in keep and abs(point.z - height) <= climb_height:
                                    keep.add((cell, other))
                                    frontier.append((cell, other))

        vantages = []
        for cell, points in floors.items():
            for level, ground in enumerate(points):
                if keep is not None and (cell, level) not in keep:
                    continue
                if not enclosing_entries(world, ground + rise) <= allowed:
                    continue
                vantage = Vantage(position=ground + rise)
                vantage.cell = cell
                vantages.append(vantage)
        if len(vantages) <= max_vantages or (nx == 1 and ny == 1):
            grid = {"origin": (float(low[0]) + rise.x, float(low[1]) + rise.y), "step": (step_x, step_y)}
            return vantages, grid
        spacing *= 1.25


def light_vantages(scene, world):
    """Shadow-casting lights and light probes: what they see must stay in the scene."""
    vantages = []
    for obj in scene.objects:
        if obj.hide_render:
            continue
        if obj.type == "LIGHT_PROBE":
            vantages.append(Vantage(position=obj.matrix_world.translation.copy()))
        elif obj.type == "LIGHT" and getattr(obj.data, "use_shadow", True):
            if obj.data.type == "SUN":
                towards = (obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))).normalized()
                vantages.append(Vantage(direction=towards))
            else:
                vantages.append(Vantage(position=obj.matrix_world.translation.copy()))
    return vantages


def _sample_points(corners, centroid, longest, spacing):
    """Probe points spread over one triangle, denser on large triangles."""
    a, b, c = corners
    points = [centroid]
    for corner in (a, b, c):
        points.append(centroid + (corner - centroid) * 0.85)
    steps = min(6, int(longest / spacing))
    if steps >= 2:
        for i in range(steps + 1):
            for j in range(steps + 1 - i):
                u, v = (i + 0.25) / (steps + 0.75), (j + 0.25) / (steps + 0.75)
                if u + v < 1.0:
                    points.append(a + (b - a) * u + (c - a) * v)
    return points


def triangle_visibility(world, vantages, candidates=None, sample_spacing=0.75, progress=None):
    """Mark triangles of which at least one probe point has a free line to a vantage.

    Both faces of a triangle count, because EEVEE draws back faces unless a
    material opts out. Returns a boolean array over all world triangles.
    """
    count = len(world.tris)
    visible = np.zeros(count, dtype=bool)
    if not count or not vantages:
        return visible
    indices = np.arange(count) if candidates is None else np.nonzero(candidates)[0]
    epsilon = world.epsilon
    far = world.diagonal * 4.0 + 10.0
    positions = [v.position for v in vantages]
    last = 0
    order = list(range(len(vantages)))
    for done, tri in enumerate(indices):
        if progress is not None and done % 4096 == 0:
            progress(done / max(1, len(indices)))
        if world.areas[tri] <= 1e-12:
            continue
        corners = [Vector(corner) for corner in world.corners[tri]]
        centroid = Vector(world.centroids[tri])
        normal = Vector(world.normals[tri])
        longest = max((corners[0] - corners[1]).length, (corners[1] - corners[2]).length,
                      (corners[2] - corners[0]).length)
        points = _sample_points(corners, centroid, longest, sample_spacing)
        lifted = (normal * epsilon * 4.0, normal * -epsilon * 4.0)
        found = False
        # Neighbouring triangles are usually seen from the same place.
        for index in [last] + order:
            vantage = vantages[index]
            position = positions[index]
            if position is None or vantage.ortho:
                side = 0 if normal.dot(vantage.direction) > 0.0 else 1
            else:
                side = 0 if normal.dot(position - centroid) > 0.0 else 1
            offset = lifted[side]
            for point in points:
                if vantage.inverse is not None and not vantage.sees(point):
                    continue
                origin = point + offset
                target = origin + vantage.direction * far if (position is None or vantage.ortho) else position
                if world.clear(origin, target):
                    found = True
                    break
            if found:
                last = index
                break
        visible[tri] = found
    return visible


def dilate(world, flags, rings=1):
    """Grow a triangle selection across shared vertices of each mesh."""
    flags = flags.copy()
    for _ in range(rings):
        vertex = np.zeros(len(world.verts), dtype=bool)
        vertex[world.tris[flags].ravel()] = True
        flags |= vertex[world.tris].any(axis=1)
    return flags


def nearest_view_distance(world, vantages, margin=0.0, floor=0.05):
    """Lower bound on the camera distance of every triangle.

    Occlusion is ignored on purpose (smaller distances only keep more detail).
    `margin` covers camera positions between the sampled vantages.
    """
    count = len(world.tris)
    best = np.full(count, np.inf)
    centroids = world.centroids
    for vantage in vantages:
        if vantage.ortho or vantage.position is None:
            continue
        position = np.array(vantage.position)
        distance = np.linalg.norm(centroids - position, axis=1)
        if vantage.inverse is not None:
            inverse = np.array(vantage.inverse)
            local = centroids @ inverse[:3, :3].T + inverse[:3, 3]
            depth = -local[:, 2]
            reach = world.tri_radius
            inside = ((depth + reach > 0.0) & (depth - reach < vantage.far)
                      & (np.abs(local[:, 0]) - reach * 1.5 <= np.maximum(depth, 0.0) * vantage.tan_x)
                      & (np.abs(local[:, 1]) - reach * 1.5 <= np.maximum(depth, 0.0) * vantage.tan_y))
            distance = np.where(inside, distance, np.inf)
        best = np.minimum(best, distance)
    return np.maximum(best - world.tri_radius - margin, floor)


def build_pvs(world, vantages, grid, far, progress=None):
    """Potentially-visible sets: for every vantage cell, the static objects in sight.

    An object counts as visible when any probe on it (bounding box, centre and
    a spread of its triangles) can be reached from the cell's centre or from
    its four edge midpoints. Objects larger than a cell are always kept.
    """
    statics = [index for index, entry in enumerate(world.entries) if not entry.dynamic]
    probes = {}
    for index in statics:
        entry = world.entries[index]
        obj = entry.obj
        points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        points.append(Vector(entry.center))
        stride = max(1, entry.tri_count // 24)
        for tri in range(entry.tri_start, entry.tri_start + entry.tri_count, stride):
            points.append(Vector(world.centroids[tri]) + Vector(world.normals[tri]) * world.epsilon * 4.0)
        probes[index] = points

    step_x, step_y = grid["step"]
    cell_size = max(step_x, step_y)
    half_x, half_y = step_x * 0.45, step_y * 0.45
    offsets = (Vector((0, 0, 0)), Vector((half_x, 0, 0)), Vector((-half_x, 0, 0)),
               Vector((0, half_y, 0)), Vector((0, -half_y, 0)))
    cells = {}
    for number, vantage in enumerate(vantages):
        if progress is not None:
            progress(number / max(1, len(vantages)))
        if vantage.position is None or vantage.cell is None:
            continue
        eyes = [vantage.position + offset for offset in offsets]
        eyes = [eye for eye in eyes if eye is eyes[0] or world.clear(eyes[0], eye)]
        seen = []
        for index in statics:
            entry = world.entries[index]
            reach = (Vector(entry.center) - vantage.position).length - entry.radius
            if reach > far:
                continue
            if entry.radius >= cell_size or reach <= cell_size:
                seen.append(index)
                continue
            if any(world.first_hit_entry(eye, point) in (-1, index) for eye in eyes for point in probes[index]):
                seen.append(index)
        cells.setdefault(vantage.cell, set()).update(seen)
    names = [world.entries[index].name for index in statics]
    remap = {index: slot for slot, index in enumerate(statics)}
    return {
        "origin": list(grid["origin"]),
        "step": [step_x, step_y],
        "objects": names,
        "cells": {"%d,%d" % key: sorted(remap[index] for index in value) for key, value in cells.items()},
    }
