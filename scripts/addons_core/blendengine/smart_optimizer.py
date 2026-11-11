# SPDX-License-Identifier: GPL-2.0-or-later
#
# Smart Optimizer: measure what the game camera can actually resolve, then drop
# everything else so the renderer can stay on its best settings.
#
# It is a rule-and-measurement planner, not a trained neural network. Each pass
# is one decision with a stated reason and a predicted saving:
#
#   materials  merge identical materials and drop unused slots (fewer draw calls)
#   meshes     let identical meshes share one datablock (instancing, less memory)
#   faces      delete faces no camera position, light or probe can see
#   objects    stop rendering static objects that are never in sight
#   textures   shrink each image to the sharpest size a screen pixel can resolve
#   pvs        bake per-cell visible sets for runtime occlusion culling
#   lods       build simplified meshes switched by on-screen triangle density
#
# The first five do not change the picture at the analysed viewpoints and target
# resolution; they are verified by rendering in tools/blendengine. LODs trade a
# bounded amount of silhouette detail and are reported separately.
#
# Meshes and images are never overwritten: originals stay in the file under a
# fake user until `purge_backups`, and `restore` puts them back.

import hashlib
import json
import math
import os

import bpy
import bmesh
import numpy as np

from . import visibility


ORIGINAL_MESH = "be_orig_mesh"
GENERATED = "be_generated"
CULLED = "be_culled"
LOD_MESHES = "be_lod_meshes"
LOD_DISTANCES = "be_lod_distances"
PVS = "be_pvs"
ORIGINAL_SIZE = "be_orig_size"
ORIGINAL_PATH = "be_orig_filepath"
ORIGINAL_PACKED = "be_orig_packed"
BACKUP_IMAGE = "be_backup_image"
BACKUP_PREFIX = "BE_ORIG_"
BACKUP_MESH = "be_backup_mesh"

# One triangle per this many pixels still reads as the original silhouette.
LOD_PIXELS_PER_TRIANGLE = 8.0
LOD_RATIOS = (0.5, 0.2)


# ---------------------------------------------------------------------------
# Small helpers

def _triangles(mesh):
    counts = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", counts)
    return int(np.maximum(counts - 2, 0).sum())


def image_bytes(image, width=None, height=None):
    """GPU memory of an image with its mip chain."""
    width = image.size[0] if width is None else width
    height = image.size[1] if height is None else height
    return width * height * (16 if image.is_float else 4) * 4.0 / 3.0


def scene_meshes(scene):
    return [obj for obj in scene.objects if obj.type == "MESH" and obj.data is not None]


def target_resolution(scene, settings):
    """Pixels the game is drawn at: the project target, or the render output if larger."""
    if settings.target_width > 0 and settings.target_height > 0:
        return settings.target_width, settings.target_height
    project = scene.blendengine_project
    scale = scene.render.resolution_percentage / 100.0
    width = max(project.resolution_x, int(scene.render.resolution_x * scale))
    height = max(project.resolution_y, int(scene.render.resolution_y * scale))
    return width, height


def _backup_mesh(obj):
    if ORIGINAL_MESH not in obj:
        obj[ORIGINAL_MESH] = obj.data.name
        if not obj.data.use_fake_user:
            obj.data.use_fake_user = True
            obj.data[BACKUP_MESH] = 1


def _new_step(identifier, title, lossless=True):
    return {"id": identifier, "title": title, "lossless": lossless, "count": 0,
            "saved_triangles": 0, "saved_texture_mb": 0.0, "detail": ""}


# ---------------------------------------------------------------------------
# Materials

_SKIP_PROPS = {
    "rna_type", "name", "name_full", "label", "location", "location_absolute", "width", "height",
    "width_hidden", "dimensions", "select", "hide", "parent", "color", "use_custom_color", "show_options",
    "show_preview", "show_texture", "tag", "users", "use_fake_user", "use_extra_user", "is_evaluated",
    "original", "preview", "asset_data", "library", "override_library", "session_uid", "is_runtime_data",
    "paint_active_slot", "paint_clone_slot", "preview_render_type", "use_preview_world", "node_tree",
    "inputs", "outputs", "internal_links", "interface", "bl_icon", "bl_label", "bl_description",
    "bl_static_type", "bl_width_default", "bl_width_min", "bl_width_max", "bl_height_default",
    "bl_height_min", "bl_height_max", "is_library_indirect", "is_missing", "is_embedded_data",
    "is_editable", "id_type", "library_weak_reference", "warning_propagation",
}


def _plain(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (bool, int, str)):
        return value
    try:
        return tuple(_plain(item) for item in value)
    except TypeError:
        return repr(value)


def _rna_signature(struct, depth=2):
    """Order-stable description of everything that makes an RNA struct render differently."""
    parts = []
    for prop in struct.bl_rna.properties:
        name = prop.identifier
        if name in _SKIP_PROPS:
            continue
        if prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            if prop.is_readonly and name != "bl_idname":
                continue
            try:
                parts.append((name, _plain(getattr(struct, name))))
            except (AttributeError, TypeError):
                continue
        elif prop.type == "POINTER":
            value = getattr(struct, name, None)
            if value is None:
                parts.append((name, None))
            elif isinstance(value, bpy.types.ID):
                parts.append((name, type(value).__name__, value.name_full))
            elif depth > 0:
                parts.append((name, _rna_signature(value, depth - 1)))
        elif prop.type == "COLLECTION" and depth > 0:
            try:
                parts.append((name, tuple(_rna_signature(item, depth - 1) for item in getattr(struct, name))))
            except (AttributeError, TypeError):
                continue
    return tuple(parts)


def _socket_value(socket):
    return _plain(socket.default_value) if hasattr(socket, "default_value") else None


def material_signature(material):
    """Hashable identity of a material, or None when it must not be merged."""
    if material.library is not None or material.animation_data is not None:
        return None
    if getattr(material, "is_grease_pencil", False):
        return None
    tree = material.node_tree
    nodes, links = (), ()
    if tree is not None:
        if tree.animation_data is not None:
            return None
        nodes = tuple(sorted(
            (node.name, node.bl_idname, _rna_signature(node),
             tuple((s.identifier, _socket_value(s)) for s in node.inputs),
             tuple((s.identifier, _socket_value(s)) for s in node.outputs))
            for node in tree.nodes))
        links = tuple(sorted(
            (link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier)
            for link in tree.links))
    return (_rna_signature(material), nodes, links)


def clean_materials(scene):
    """Merge identical materials and remove slots no face uses."""
    step = _new_step("materials", "Merge identical materials and drop unused slots")
    used = {}
    for obj in scene_meshes(scene):
        for slot in obj.material_slots:
            if slot.material is not None:
                used[slot.material.name_full] = slot.material

    groups = {}
    for material in used.values():
        signature = material_signature(material)
        if signature is not None:
            groups.setdefault(signature, []).append(material)
    merged = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda material: (-material.users, len(material.name), material.name))
        keep = group[0]
        for duplicate in group[1:]:
            duplicate.user_remap(keep)
            merged += 1

    slots_removed = 0
    objects_of = {}
    for obj in scene_meshes(scene):
        objects_of.setdefault(obj.data, []).append(obj)
    for mesh, owners in objects_of.items():
        if mesh.library is not None or not len(mesh.polygons) or not len(mesh.materials):
            continue
        if any(slot.link == "OBJECT" for obj in owners for slot in obj.material_slots):
            continue
        materials = list(mesh.materials)
        index = np.empty(len(mesh.polygons), dtype=np.int32)
        mesh.polygons.foreach_get("material_index", index)
        index = np.clip(index, 0, len(materials) - 1)
        kept, remap = [], {}
        for old in sorted(set(index.tolist())):
            material = materials[old]
            key = material.name_full if material is not None else None
            position = next((i for i, other in enumerate(kept)
                             if (other.name_full if other is not None else None) == key), None)
            if position is None:
                position = len(kept)
                kept.append(material)
            remap[old] = position
        if len(kept) == len(materials) and all(old == new for old, new in remap.items()):
            continue
        lookup = np.zeros(len(materials), dtype=np.int32)
        for old, new in remap.items():
            lookup[old] = new
        slots_removed += len(materials) - len(kept)
        mesh.materials.clear()
        for material in kept:
            mesh.materials.append(material)
        mesh.polygons.foreach_set("material_index", lookup[index])
        mesh.update()

    step["count"] = merged + slots_removed
    step["detail"] = "%d duplicate material(s) merged, %d unused slot(s) removed." % (merged, slots_removed)
    step["merged"] = merged
    step["slots_removed"] = slots_removed
    return step


# ---------------------------------------------------------------------------
# Mesh sharing

_ATTRIBUTE_FIELDS = {
    "FLOAT": ("value", 1, np.float32), "INT": ("value", 1, np.int32), "INT8": ("value", 1, np.int32),
    "BOOLEAN": ("value", 1, bool), "FLOAT_VECTOR": ("vector", 3, np.float32),
    "FLOAT2": ("vector", 2, np.float32), "FLOAT_COLOR": ("color", 4, np.float32),
    "BYTE_COLOR": ("color", 4, np.float32), "INT32_2D": ("value", 2, np.int32),
    "QUATERNION": ("value", 4, np.float32),
}


def mesh_signature(mesh):
    """Digest of all geometry a renderer reads, or None when sharing is unsafe."""
    if mesh.library is not None or mesh.shape_keys is not None or mesh.animation_data is not None:
        return None
    if not len(mesh.polygons):
        return None
    digest = hashlib.blake2b(digest_size=20)

    def feed(collection, field, size, dtype):
        data = np.empty(len(collection) * size, dtype=dtype)
        collection.foreach_get(field, data)
        digest.update(data.tobytes())

    try:
        digest.update(repr((len(mesh.vertices), len(mesh.edges), len(mesh.loops), len(mesh.polygons))).encode())
        feed(mesh.vertices, "co", 3, np.float32)
        feed(mesh.loops, "vertex_index", 1, np.int32)
        feed(mesh.polygons, "loop_total", 1, np.int32)
        feed(mesh.polygons, "material_index", 1, np.int32)
        feed(mesh.polygons, "use_smooth", 1, bool)
        feed(mesh.edges, "use_edge_sharp", 1, bool)
        for layer in mesh.uv_layers:
            digest.update(layer.name.encode())
            feed(layer.data, "uv", 2, np.float32)
        for attribute in sorted(mesh.attributes, key=lambda item: item.name):
            fields = _ATTRIBUTE_FIELDS.get(attribute.data_type)
            if fields is None:
                return None
            digest.update(repr((attribute.name, attribute.domain, attribute.data_type)).encode())
            feed(attribute.data, *fields)
        if mesh.has_custom_normals and "custom_normal" not in mesh.attributes:
            return None
    except (AttributeError, TypeError, RuntimeError):
        return None
    digest.update(repr(tuple(m.name_full if m else None for m in mesh.materials)).encode())
    digest.update(repr(_rna_signature(mesh, depth=0)).encode())
    return digest.hexdigest()


def share_meshes(scene):
    """Point objects with byte-identical meshes at a single datablock."""
    step = _new_step("meshes", "Share identical meshes between objects")
    groups = {}
    targets = visibility.action_targets(scene)
    for obj in scene_meshes(scene):
        if len(obj.vertex_groups) or ORIGINAL_MESH in obj:
            continue
        groups.setdefault(obj.data, []).append(obj)
    by_signature = {}
    for mesh, owners in groups.items():
        signature = mesh_signature(mesh)
        if signature is not None:
            # Scenery and moving objects stay apart so scenery meshes remain free to be trimmed.
            moving = any(visibility.is_dynamic(obj, targets) for obj in owners)
            by_signature.setdefault((signature, moving), []).append(mesh)
    saved_bytes = 0
    for meshes in by_signature.values():
        if len(meshes) < 2:
            continue
        meshes.sort(key=lambda mesh: (-mesh.users, mesh.name))
        keep = meshes[0]
        for duplicate in meshes[1:]:
            saved_bytes += len(duplicate.vertices) * 12 + len(duplicate.loops) * 12
            for obj in groups[duplicate]:
                _backup_mesh(obj)
                obj.data = keep
                step["count"] += 1
    step["detail"] = "%d object(s) now reuse a shared mesh (about %.1f MB of duplicate geometry)." % (
        step["count"], saved_bytes / 1048576.0)
    return step


# ---------------------------------------------------------------------------
# Analysis

class Analysis:
    """Result of one visibility pass over a scene."""

    def __init__(self):
        self.world = None
        self.mode = "PLAY_AREA"
        self.vantages = []
        self.grid = None
        self.seen = None          # Triangle seen by a camera vantage.
        self.needed = None        # Seen, lit, or next to such a triangle.
        self.distance = None      # Lower bound of camera distance per triangle.
        self.dynamic_distance = {}
        self.width = 1280
        self.height = 720
        self.focal = 1000.0
        self.edge = 1.0
        self.ortho_ppm = 0.0

    def entry_seen(self, entry):
        return bool(self.seen[entry.tri_start:entry.tri_start + entry.tri_count].any())

    def entry_needed(self, entry):
        return bool(self.needed[entry.tri_start:entry.tri_start + entry.tri_count].any())

    def pixels_per_meter(self, distance):
        if self.ortho_ppm:
            return np.full_like(np.asarray(distance, dtype=np.float64), self.ortho_ppm)
        return self.focal * self.edge / np.maximum(distance, 1e-4)


def analyze(scene, depsgraph, settings, progress=None):
    """Sample every place the camera can be and classify each triangle."""
    result = Analysis()
    world = visibility.World(scene, depsgraph)
    result.world = world
    result.width, result.height = target_resolution(scene, settings)
    camera = scene.camera
    result.focal, result.edge = visibility.camera_optics(camera, result.width, result.height)
    if camera is not None and camera.type == "CAMERA" and camera.data.type == "ORTHO":
        result.ortho_ppm = max(result.width, result.height) / max(camera.data.ortho_scale, 1e-6)

    mode = settings.viewpoint_mode
    if mode == "AUTO":
        from . import utils
        mode = "PLAY_AREA" if utils.find_player_object(scene) is not None else "CAMERA_PATH"
    margin = 0.0
    floor = 0.05
    if mode == "PLAY_AREA":
        vantages, grid = visibility.play_area_vantages(
            scene, world, settings.vantage_spacing, settings.eye_height, settings.max_vantages,
            settings.climb_height)
        result.grid = grid
        # A real camera can stand anywhere between grid points and walk up to walls.
        margin = 0.75 * max(grid["step"])
        floor = settings.min_approach
        if camera is not None:
            vantages.append(visibility.Vantage(position=camera.matrix_world.translation.copy()))
    else:
        vantages, margin, result.dynamic_distance = visibility.camera_path_vantages(
            scene, world, settings.frame_step)
        if camera is not None and camera.type == "CAMERA":
            floor = max(0.05, camera.data.clip_start)
    result.mode = mode
    result.vantages = vantages

    count = len(world.tris)
    if not vantages:
        # Without a viewpoint nothing can be proven hidden.
        result.seen = np.ones(count, dtype=bool)
        result.needed = np.ones(count, dtype=bool)
        result.distance = np.full(count, floor)
        return result

    static = np.array([not entry.dynamic for entry in world.entries], dtype=bool)
    candidates = static[world.tri_entry] if count else np.zeros(0, dtype=bool)
    seen = visibility.triangle_visibility(world, vantages, candidates, settings.sample_spacing, progress)
    lit = visibility.triangle_visibility(
        world, visibility.light_vantages(scene, world), candidates & ~seen, settings.sample_spacing)
    seen = visibility.dilate(world, seen, settings.safety_rings)
    seen |= ~candidates
    result.seen = seen
    result.needed = seen | visibility.dilate(world, lit, settings.safety_rings)
    result.distance = visibility.nearest_view_distance(world, vantages, margin, floor)
    return result


# ---------------------------------------------------------------------------
# Hidden geometry

def remove_hidden_faces(scene, analysis, min_faces=1):
    """Delete faces of static meshes that no camera position, light or probe sees."""
    step = _new_step("faces", "Remove faces nothing can see")
    world = analysis.world
    by_mesh = {}
    for entry in world.entries:
        obj = entry.obj
        if obj.type != "MESH":
            continue
        by_mesh.setdefault(obj.data, []).append(entry)
    for mesh, entries in by_mesh.items():
        if not all(entry.editable for entry in entries):
            continue
        if sum(1 for obj in bpy.data.objects if obj.data == mesh) != len(entries):
            continue  # Also used outside the analysed scene.
        keep = np.zeros(len(mesh.polygons), dtype=bool)
        for entry in entries:
            part = slice(entry.tri_start, entry.tri_start + entry.tri_count)
            np.logical_or.at(keep, world.tri_poly[part], analysis.needed[part])
        hidden = int((~keep).sum())
        if hidden < min_faces or not keep.any():
            continue  # Fully hidden objects are handled without touching their mesh.
        before = _triangles(mesh)
        reduced = mesh.copy()
        reduced[GENERATED] = 1
        bm = bmesh.new()
        bm.from_mesh(reduced)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[face for face in bm.faces if not keep[face.index]], context="FACES")
        bm.to_mesh(reduced)
        bm.free()
        reduced.update()
        for entry in entries:
            _backup_mesh(entry.obj)
            entry.obj.data = reduced
        step["count"] += hidden
        step["saved_triangles"] += (before - _triangles(reduced)) * len(entries)
    step["detail"] = "%d hidden face(s) deleted, %d triangle(s) no longer drawn." % (
        step["count"], step["saved_triangles"])
    return step


def hide_unseen_objects(scene, analysis):
    """Take static objects that are never seen and never lit out of the render."""
    step = _new_step("objects", "Stop rendering objects that are never in sight")
    for entry in analysis.world.entries:
        obj = entry.obj
        if entry.dynamic or analysis.entry_needed(entry) or obj.hide_render:
            continue
        settings = obj.blendengine_object
        if settings.object_tag == "Ground" or any(c.component_type == "COLLIDER" for c in settings.components):
            continue  # Gameplay ray casts and collisions still need it in the view layer.
        obj[CULLED] = 1
        obj.hide_render = True
        obj.hide_viewport = True
        step["count"] += 1
        step["saved_triangles"] += entry.tri_count
    step["detail"] = "%d unseen object(s) excluded from rendering (%d triangles)." % (
        step["count"], step["saved_triangles"])
    return step


# ---------------------------------------------------------------------------
# Textures

def _texture_bindings(material):
    """Image nodes of a material as (image, uv_map_or_None, uv_scale); scale None = unknown mapping."""
    bindings = []
    tree = material.node_tree
    if tree is None:
        return bindings

    def unknown_images(node_tree, seen):
        for node in node_tree.nodes:
            image = getattr(node, "image", None)
            if image is not None:
                bindings.append((image, None, None))
            group = getattr(node, "node_tree", None)
            if node.type == "GROUP" and group is not None and group.name not in seen:
                seen.add(group.name)
                unknown_images(group, seen)

    for node in tree.nodes:
        if node.type == "GROUP" and node.node_tree is not None:
            unknown_images(node.node_tree, {node.node_tree.name})
            continue
        image = getattr(node, "image", None)
        if image is None:
            continue
        if node.type != "TEX_IMAGE" or node.projection != "FLAT":
            bindings.append((image, None, None))
            continue
        scale = 1.0
        uv_map = None
        socket = node.inputs["Vector"]
        if socket.is_linked:
            link = socket.links[0]
            source = link.from_node
            if source.type == "MAPPING":
                inputs = source.inputs
                if any(inputs[name].is_linked for name in ("Location", "Rotation", "Scale")):
                    scale = None
                else:
                    sx, sy = abs(inputs["Scale"].default_value[0]), abs(inputs["Scale"].default_value[1])
                    # The less repeated axis has the fewest texels per meter and decides.
                    if source.vector_type in {"POINT", "VECTOR"} and min(sx, sy) > 1e-6:
                        scale = min(sx, sy)
                    elif source.vector_type == "TEXTURE" and max(sx, sy) > 1e-6:
                        scale = 1.0 / max(sx, sy)
                    else:
                        scale = None
                if inputs["Vector"].is_linked:
                    link = inputs["Vector"].links[0]
                    source = link.from_node
                else:
                    scale = None
            if scale is not None:
                if source.type == "UVMAP":
                    uv_map = source.uv_map or None
                elif source.type == "TEX_COORD" and link.from_socket.identifier == "UV":
                    uv_map = None
                else:
                    scale = None
        bindings.append((image, uv_map, scale))
    return bindings


def _object_texel_data(obj, mesh, uv_map):
    """Per-triangle world area, UV area, world-to-UV Jacobian, polygon and material index."""
    layer = mesh.uv_layers.get(uv_map) if uv_map else None
    if layer is None:
        layer = next((item for item in mesh.uv_layers if item.active_render), None) or mesh.uv_layers.active
    if layer is None or not len(mesh.polygons):
        return None
    mesh.calc_loop_triangles()
    count = len(mesh.loop_triangles)
    loops = np.empty(count * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", loops)
    verts = np.empty(count * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", verts)
    poly = np.empty(count, dtype=np.int32)
    mesh.loop_triangles.foreach_get("polygon_index", poly)
    material = np.empty(count, dtype=np.int32)
    mesh.loop_triangles.foreach_get("material_index", material)
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    co = co.reshape(-1, 3).astype(np.float64) @ matrix[:3, :3].T
    corners = co[verts.reshape(-1, 3)]
    side_a, side_b = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]
    world_area = np.linalg.norm(np.cross(side_a, side_b), axis=1) * 0.5
    uv = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2).astype(np.float64)[loops.reshape(-1, 3)]
    edge_a, edge_b = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    uv_area = np.abs(edge_a[:, 0] * edge_b[:, 1] - edge_a[:, 1] * edge_b[:, 0]) * 0.5

    # Express the triangle in its own plane, then solve UV = J * position.
    with np.errstate(divide="ignore", invalid="ignore"):
        length_a = np.linalg.norm(side_a, axis=1)
        along = np.einsum("ij,ij->i", side_b, side_a) / length_a
        across = 2.0 * world_area / length_a
        jacobian = np.stack((
            edge_a[:, 0] / length_a,
            (edge_b[:, 0] - edge_a[:, 0] * along / length_a) / across,
            edge_a[:, 1] / length_a,
            (edge_b[:, 1] - edge_a[:, 1] * along / length_a) / across,
        ), axis=1)
    jacobian = np.nan_to_num(jacobian, nan=0.0, posinf=0.0, neginf=0.0)
    return world_area, uv_area, jacobian, poly, material


def _texel_density(jacobian, width, height):
    """Texels per meter along the direction the mapping stretches the image most.

    That is the smaller singular value of the world-to-texel mapping: a
    texture squeezed along one axis is only as sharp as its thin direction.
    """
    j00, j01 = jacobian[:, 0] * width, jacobian[:, 1] * width
    j10, j11 = jacobian[:, 2] * height, jacobian[:, 3] * height
    total = j00 * j00 + j01 * j01 + j10 * j10 + j11 * j11
    det = j00 * j11 - j01 * j10
    root = np.sqrt(np.maximum(total * total - 4.0 * det * det, 0.0))
    return np.sqrt(np.maximum((total - root) * 0.5, 0.0))


def plan_textures(scene, analysis, settings, quality=None):
    """For every image, the smallest size that still gives each screen pixel its own texel.

    Returns {image: (new_width, new_height, needed_scale)} for images that can shrink.
    """
    quality = settings.texel_quality if quality is None else quality
    world = analysis.world
    entries = {entry.name: entry for entry in world.entries}

    scene_materials = {}
    for obj in scene_meshes(scene):
        for slot in obj.material_slots:
            if slot.material is not None:
                scene_materials[slot.material.name_full] = slot.material
    bindings = {name: _texture_bindings(material) for name, material in scene_materials.items()}

    # An image may only shrink when every one of its users was measured.
    references = {}
    blocked = set()
    for name, items in bindings.items():
        for image, _uv, scale in items:
            references[image] = references.get(image, 0) + 1
            if scale is None:
                blocked.add(image)
    for material in bpy.data.materials:
        if material.name_full in scene_materials or material.node_tree is None:
            continue
        if material.users == 0:
            continue
        for image, _uv, _scale in _texture_bindings(material):
            blocked.add(image)
    for image, count in references.items():
        orphan_nodes = sum(
            1 for material in bpy.data.materials
            if material.users == 0 and material.node_tree is not None
            for other, _uv, _scale in _texture_bindings(material) if other == image)
        users = image.users - (1 if image.use_fake_user else 0)
        if users > count + orphan_nodes:
            blocked.add(image)  # World, node group, brush or another unmeasured user.
        if image.source not in {"FILE", "GENERATED"} or image.library is not None or BACKUP_IMAGE in image:
            blocked.add(image)
        if image.name.startswith(BACKUP_PREFIX) or min(image.size) < 1:
            blocked.add(image)

    needed = {}
    measured = set()
    for obj in scene_meshes(scene):
        entry = entries.get(obj.name)
        if entry is None:
            continue
        if not entry.dynamic and not analysis.entry_seen(entry):
            continue  # Never on screen: asks nothing of its textures.
        mesh = obj.data
        cache = {}
        slot_count = max(1, len(obj.material_slots))
        if entry.editable:
            poly_distance = np.full(entry.poly_count, np.inf)
            part = slice(entry.tri_start, entry.tri_start + entry.tri_count)
            np.minimum.at(poly_distance, world.tri_poly[part], analysis.distance[part])
        else:
            if entry.dynamic:
                nearest = analysis.dynamic_distance.get(obj.name, settings.min_approach)
                nearest = max(nearest, 0.05) if analysis.mode == "CAMERA_PATH" else settings.min_approach
            else:
                nearest = float(analysis.distance[entry.tri_start:entry.tri_start + entry.tri_count].min())
            poly_distance = None
        for index, slot in enumerate(obj.material_slots):
            if slot.material is None:
                continue
            for image, uv_map, scale in bindings.get(slot.material.name_full, ()):
                if image in blocked or scale is None:
                    continue
                if uv_map not in cache:
                    cache[uv_map] = _object_texel_data(obj, mesh, uv_map)
                data = cache[uv_map]
                if data is None:
                    blocked.add(image)
                    continue
                world_area, uv_area, jacobian, poly, material = data
                chosen = np.clip(material, 0, slot_count - 1) == index
                distance = poly_distance[poly] if poly_distance is not None else np.full(len(poly), nearest)
                ppm = analysis.pixels_per_meter(distance)
                # Triangles smaller than a pixel cannot show texture detail.
                chosen &= (world_area * ppm * ppm >= 1.0) & (uv_area > 1e-14) & np.isfinite(distance)
                measured.add(image)
                if not chosen.any():
                    continue
                texels = _texel_density(jacobian[chosen], image.size[0], image.size[1]) * scale
                demand = float((ppm[chosen] * quality / np.maximum(texels, 1e-9)).max())
                needed[image] = max(needed.get(image, 0.0), demand)

    plan = {}
    for image in measured - blocked:
        demand = needed.get(image, 0.0)
        width, height = image.size[0], image.size[1]
        halvings = 0
        while (demand <= 0.5 ** (halvings + 1)
               and min(width, height) >> (halvings + 1) >= settings.min_texture_size):
            halvings += 1
        if halvings:
            plan[image] = (max(1, width >> halvings), max(1, height >> halvings), demand)
    return plan


def fit_textures(scene, analysis, settings, quality=None):
    """Resize images to the resolution the target screen can actually show."""
    quality = settings.texel_quality if quality is None else quality
    step = _new_step("textures", "Fit textures to what a screen pixel can resolve",
                     lossless=quality >= 1.0)
    saved = 0.0
    for image, (width, height, _demand) in plan_textures(scene, analysis, settings, quality).items():
        path = bpy.path.abspath(image.filepath_raw) if image.filepath_raw else ""
        on_disk = bool(path) and os.path.isfile(path)
        original = (image.size[0], image.size[1])
        if ORIGINAL_SIZE not in image:
            if on_disk:
                image[ORIGINAL_PATH] = image.filepath_raw
                image[ORIGINAL_PACKED] = image.packed_file is not None
            else:
                if image.is_float:
                    continue  # No lossless in-file backup format for unsaved float buffers.
                if image.packed_file is None or image.is_dirty:
                    image.pack()
                backup = image.copy()
                backup.name = BACKUP_PREFIX + image.name
                backup.use_fake_user = True
                backup[BACKUP_IMAGE] = 1
                image[BACKUP_IMAGE + "_name"] = backup.name
            image[ORIGINAL_SIZE] = original
        before = image_bytes(image)
        image.scale(width, height)
        image.pack()
        saved += before - image_bytes(image)
        step["count"] += 1
    step["saved_texture_mb"] = saved / 1048576.0
    step["detail"] = "%d image(s) resized at %.2f texel(s) per screen pixel, %.1f MB of texture memory freed." % (
        step["count"], quality, step["saved_texture_mb"])
    return step


def merge_duplicate_images():
    """Let materials that load the same file with the same settings share one image."""
    step = _new_step("images", "Share images loaded from the same file")
    groups = {}
    for image in bpy.data.images:
        if image.source != "FILE" or image.library is not None or not image.filepath_raw:
            continue
        if image.packed_file is not None or image.is_dirty or ORIGINAL_SIZE in image or BACKUP_IMAGE in image:
            continue
        key = (os.path.normcase(os.path.realpath(bpy.path.abspath(image.filepath_raw))),
               image.colorspace_settings.name, image.alpha_mode, tuple(image.size))
        groups.setdefault(key, []).append(image)
    saved = 0.0
    for images in groups.values():
        if len(images) < 2:
            continue
        images.sort(key=lambda image: (-image.users, image.name))
        for duplicate in images[1:]:
            if duplicate.users - (1 if duplicate.use_fake_user else 0) <= 0:
                continue
            duplicate.user_remap(images[0])
            saved += image_bytes(duplicate)
            step["count"] += 1
    step["saved_texture_mb"] = saved / 1048576.0
    step["detail"] = "%d duplicate image(s) merged, %.1f MB of texture memory freed." % (
        step["count"], step["saved_texture_mb"])
    return step


# ---------------------------------------------------------------------------
# Runtime data: visible sets and LODs

def bake_pvs(scene, analysis):
    """Store which static objects each play-area cell can see, for runtime culling."""
    step = _new_step("pvs", "Bake visible sets for runtime occlusion culling")
    if analysis.mode != "PLAY_AREA" or analysis.grid is None:
        scene.pop(PVS, None)
        step["detail"] = "Skipped: visible sets need a play area (a Player Controller)."
        return step
    camera = scene.camera
    far = camera.data.clip_end if camera is not None and camera.type == "CAMERA" else 1000.0
    data = visibility.build_pvs(analysis.world, analysis.vantages, analysis.grid, far)
    scene[PVS] = json.dumps(data, separators=(",", ":"))
    total = len(data["objects"])
    cells = data["cells"]
    step["count"] = len(cells)
    if cells and total:
        hidden = sum(total - len(visible) for visible in cells.values()) / float(len(cells))
        triangles = {entry.name: entry.tri_count for entry in analysis.world.entries}
        worst = max(sum(triangles[data["objects"][i]] for i in visible) for visible in cells.values())
        step["worst_case_triangles"] = worst
        step["detail"] = ("%d cell(s) baked; on average %.0f of %d static object(s) are occluded, "
                          "worst case %d static triangle(s) in sight.") % (len(cells), hidden, total, worst)
    return step


def _decimated(scene, source, ratio):
    holder = bpy.data.objects.new("BE_LOD_BUILD", source)
    scene.collection.objects.link(holder)
    try:
        modifier = holder.modifiers.new("Decimate", "DECIMATE")
        modifier.ratio = ratio
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        mesh = bpy.data.meshes.new_from_object(holder.evaluated_get(depsgraph))
    finally:
        bpy.data.objects.remove(holder)
    return mesh


def build_lods(scene, analysis, settings):
    """Create simplified meshes and the distances at which they become unnoticeable.

    A level is used only where it still leaves one triangle per
    LOD_PIXELS_PER_TRIANGLE pixels of the object's on-screen disc.
    """
    step = _new_step("lods", "Build distance LODs from on-screen triangle density", lossless=False)
    multiplier = scene.blendengine_quality_profile.lod_multiplier
    built = {}
    for entry in analysis.world.entries:
        obj = entry.obj
        if entry.dynamic or obj.get(CULLED) or LOD_MESHES in obj or len(obj.modifiers):
            continue
        if obj.blendengine_object.object_tag == "Ground":
            continue  # The player's ground ray cast must always meet the real surface.
        mesh = obj.data
        triangles = _triangles(mesh)
        if triangles < settings.lod_min_triangles or analysis.ortho_ppm:
            continue
        if mesh not in built:
            levels = []
            for ratio in LOD_RATIOS:
                level = _decimated(scene, mesh, ratio)
                level.name = "%s_LOD%d" % (mesh.name, len(levels) + 1)
                level[GENERATED] = 1
                level.use_fake_user = True
                levels.append(level)
            built[mesh] = levels
        levels = built[mesh]
        distances = []
        for level in levels:
            count = max(1, _triangles(level))
            radius_px = math.sqrt(LOD_PIXELS_PER_TRIANGLE * count / math.pi)
            distances.append(entry.radius * analysis.focal / radius_px * multiplier)
        obj[LOD_MESHES] = [mesh.name] + [level.name for level in levels]
        obj[LOD_DISTANCES] = distances
        obj.blendengine_object.optimization.lod_group = True
        step["count"] += 1
        step["saved_triangles"] += triangles - _triangles(levels[-1])
    step["detail"] = "%d object(s) got %d LOD level(s); up to %d triangle(s) saved when they are far away." % (
        step["count"], len(LOD_RATIOS), step["saved_triangles"])
    return step


# ---------------------------------------------------------------------------
# Orchestration

def texture_memory_mb(scene):
    images = set()
    for obj in scene_meshes(scene):
        if obj.hide_render:
            continue
        for slot in obj.material_slots:
            if slot.material is not None:
                images.update(image for image, _uv, _scale in _texture_bindings(slot.material))
    return sum(image_bytes(image) for image in images) / 1048576.0


def rendered_triangles(scene):
    return sum(_triangles(obj.data) for obj in scene_meshes(scene) if not obj.hide_render)


def draw_calls(scene):
    return sum(max(1, len(obj.material_slots)) for obj in scene_meshes(scene) if not obj.hide_render)


def measure(scene):
    return {
        "triangles": rendered_triangles(scene),
        "draw_calls": draw_calls(scene),
        "texture_mb": texture_memory_mb(scene),
        "materials": len({slot.material.name_full for obj in scene_meshes(scene)
                          for slot in obj.material_slots if slot.material is not None}),
        "meshes": len({obj.data.name_full for obj in scene_meshes(scene)}),
    }


def optimize(context, settings=None, progress=None):
    """Run every enabled pass and return a report dictionary.

    Passes that keep the picture identical always come first. Only when
    `allow_lossy` is set and a budget is still exceeded does the planner lower
    texel density evenly across the screen, the least visible way to save more.
    """
    scene = context.scene
    settings = settings or scene.blendengine_smart
    budget = scene.blendengine_performance_budget
    before = measure(scene)
    steps = []

    if settings.clean_materials:
        steps.append(clean_materials(scene))
        steps.append(merge_duplicate_images())
    if settings.share_meshes:
        steps.append(share_meshes(scene))

    context.view_layer.update()
    depsgraph = context.evaluated_depsgraph_get()
    analysis = analyze(scene, depsgraph, settings, progress)

    # Texture demand is read from the analysed geometry, so plan it before any face is deleted.
    texture_step = fit_textures(scene, analysis, settings) if settings.fit_textures else None
    pvs_step = bake_pvs(scene, analysis) if settings.bake_pvs else None
    if settings.hide_unseen_objects:
        steps.append(hide_unseen_objects(scene, analysis))
    if settings.remove_hidden_faces:
        steps.append(remove_hidden_faces(scene, analysis))
    if texture_step is not None:
        steps.append(texture_step)
    if pvs_step is not None:
        steps.append(pvs_step)
    if settings.build_lods:
        context.view_layer.update()
        steps.append(build_lods(scene, analysis, settings))

    decisions = []
    if settings.fit_textures and settings.allow_lossy and budget.max_texture_memory_mb > 0:
        for quality in (0.7, 0.5, 0.35, 0.25):
            current = texture_memory_mb(scene)
            if current <= budget.max_texture_memory_mb:
                break
            extra = fit_textures(scene, analysis, settings, quality)
            extra["title"] = "Lower texel density to meet the texture budget"
            steps.append(extra)
            decisions.append(
                "Texture memory %.0f MB was over the %d MB budget: texel density lowered to %.2f per pixel."
                % (current, budget.max_texture_memory_mb, quality))

    after = measure(scene)
    if budget.max_texture_memory_mb > 0 and after["texture_mb"] > budget.max_texture_memory_mb:
        decisions.append("Texture memory %.0f MB is still over the %d MB budget. %s" % (
            after["texture_mb"], budget.max_texture_memory_mb,
            "The remaining textures are needed at full size close to the camera."
            if settings.allow_lossy else "Enable Allow Visible Trade-offs to lower texel density evenly."))
    if budget.max_triangles_visible > 0 and after["triangles"] > budget.max_triangles_visible:
        decisions.append(
            "%d triangles remain against a budget of %d; runtime culling and LODs reduce what is drawn per frame."
            % (after["triangles"], budget.max_triangles_visible))

    report = {
        "mode": analysis.mode,
        "vantages": len(analysis.vantages),
        "resolution": [analysis.width, analysis.height],
        "before": before,
        "after": after,
        "steps": steps,
        "decisions": decisions,
    }
    settings.last_summary = summary(report)
    scene.blendengine_optimization.last_report_summary = settings.last_summary
    return report


def export_summary(scene):
    """What a build package should know about the optimized state of the scene."""
    return {
        "summary": scene.blendengine_smart.last_summary,
        "visible_sets_baked": PVS in scene,
        "lod_objects": sum(1 for obj in scene.objects if LOD_MESHES in obj),
        "objects_skipped": sum(1 for obj in scene.objects if obj.get(CULLED)),
        "originals_kept": any(ORIGINAL_MESH in obj for obj in scene.objects),
        "rendered": measure(scene),
    }


def summary(report):
    before, after = report["before"], report["after"]
    return "Triangles %d -> %d, draw calls %d -> %d, textures %.1f -> %.1f MB." % (
        before["triangles"], after["triangles"], before["draw_calls"], after["draw_calls"],
        before["texture_mb"], after["texture_mb"])


def report_text(report):
    lines = [
        "BlendEngine Smart Optimizer",
        "",
        "Viewpoints: %s, %d sampled position(s). Target screen: %d x %d." % (
            report["mode"].replace("_", " ").title(), report["vantages"],
            report["resolution"][0], report["resolution"][1]),
        summary(report),
        "",
    ]
    for step in report["steps"]:
        lines.append("[%s] %s" % ("picture unchanged" if step["lossless"] else "bounded trade-off", step["title"]))
        lines.append("    " + step["detail"])
    if report["decisions"]:
        lines.append("")
        lines.append("Budget decisions:")
        lines.extend("- " + item for item in report["decisions"])
    lines.extend((
        "",
        "Visibility is sampled from the listed viewpoints. Use Restore Originals if a",
        "surface is missing from a place the analysis did not cover.",
    ))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Undoing

def _restore_image(image):
    name = image.get(BACKUP_IMAGE + "_name")
    if name:
        backup = bpy.data.images.get(name)
        if backup is None:
            return False
        original_name = image.name
        image.user_remap(backup)
        bpy.data.images.remove(image)
        backup.name = original_name
        backup.use_fake_user = False
        del backup[BACKUP_IMAGE]
        return True
    path = image.get(ORIGINAL_PATH)
    if not path or not os.path.isfile(bpy.path.abspath(path)):
        return False
    if image.packed_file is not None:
        image.unpack(method="REMOVE")
    image.filepath = path
    image.source = "FILE"
    image.reload()
    if image.get(ORIGINAL_PACKED):
        image.pack()
    for key in (ORIGINAL_SIZE, ORIGINAL_PATH, ORIGINAL_PACKED):
        if key in image:
            del image[key]
    return True


def restore(scene):
    """Put back every original mesh and image the optimizer replaced in this scene."""
    restored = {"meshes": 0, "images": 0, "objects": 0}
    for obj in scene.objects:
        if LOD_MESHES in obj:
            base = bpy.data.meshes.get(obj[LOD_MESHES][0])
            if base is not None and ORIGINAL_MESH not in obj:
                obj.data = base
            del obj[LOD_MESHES]
            if LOD_DISTANCES in obj:
                del obj[LOD_DISTANCES]
        name = obj.get(ORIGINAL_MESH)
        if name is not None:
            original = bpy.data.meshes.get(name)
            if original is not None:
                obj.data = original
                restored["meshes"] += 1
            del obj[ORIGINAL_MESH]
        if obj.get(CULLED):
            obj.hide_render = False
            obj.hide_viewport = False
            del obj[CULLED]
            restored["objects"] += 1
    for mesh in list(bpy.data.meshes):
        if mesh.get(GENERATED) and mesh.users - (1 if mesh.use_fake_user else 0) <= 0:
            bpy.data.meshes.remove(mesh)
        elif mesh.get(BACKUP_MESH):
            mesh.use_fake_user = False
            del mesh[BACKUP_MESH]
    for image in list(bpy.data.images):
        if ORIGINAL_SIZE in image and _restore_image(image):
            restored["images"] += 1
    if PVS in scene:
        del scene[PVS]
    return restored


def purge_backups(scene):
    """Drop the kept originals so the saved file only carries optimized data."""
    removed = 0
    for obj in scene.objects:
        if ORIGINAL_MESH in obj:
            del obj[ORIGINAL_MESH]
    for mesh in list(bpy.data.meshes):
        if not mesh.get(BACKUP_MESH):
            continue
        del mesh[BACKUP_MESH]
        mesh.use_fake_user = False
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
            removed += 1
    for image in list(bpy.data.images):
        if image.get(BACKUP_IMAGE):
            bpy.data.images.remove(image)
            removed += 1
        else:
            for key in (ORIGINAL_SIZE, ORIGINAL_PATH, ORIGINAL_PACKED, BACKUP_IMAGE + "_name"):
                if key in image:
                    del image[key]
    return removed
