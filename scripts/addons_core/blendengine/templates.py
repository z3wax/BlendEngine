# SPDX-License-Identifier: GPL-2.0-or-later
#
# Starter content generators for beginner-friendly BlendEngine projects.

import math
import os
import zipfile

import bpy
from mathutils import Vector

from . import components, graphics, input_system, optimization, utils


MODEL_ASSET_DIR = "/home/abdulhodiy/Desktop/MODELS"
CYBERPUNK_ZIP = os.path.join(MODEL_ASSET_DIR, "cyberpunk-city.zip")
CYBERPUNK_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "builds", "model_cache", "cyberpunk-city")
SCAR_MODEL = os.path.join(MODEL_ASSET_DIR, "fn-scar_l.glb")
SOLDIER_MODEL = os.path.join(MODEL_ASSET_DIR, "soldier_infranty_1980_ex_-_wolf._youngblood.glb")
ZOMBIE_MODEL = os.path.join(MODEL_ASSET_DIR, "sexy_zombie_girl.glb")


def _material(name, color, roughness=0.72, metallic=0.0, alpha=1.0, emission=None, emission_strength=0.0,
              surface_scale=None):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    rgba = (color[0], color[1], color[2], alpha)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    mat.blend_method = "BLEND" if alpha < 1.0 else "OPAQUE"
    mat.show_transparent_back = alpha < 1.0
    node = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if node is not None:
        _set_node_input(node, ("Base Color",), rgba)
        _set_node_input(node, ("Alpha",), alpha)
        _set_node_input(node, ("Roughness",), roughness)
        _set_node_input(node, ("Metallic",), metallic)
        if emission is not None:
            _set_node_input(node, ("Emission", "Emission Color"), emission)
            _set_node_input(node, ("Emission Strength",), emission_strength)
        if surface_scale is not None:
            _surface_detail(mat, node, color, roughness, surface_scale)
    return mat


def _surface_detail(material, shader, color, roughness, scale):
    """Give generated starter surfaces relief and roughness without texture files."""
    nodes, links = material.node_tree.nodes, material.node_tree.links

    def owned_node(kind, name, location):
        name = "BE_Surface_" + name
        node = nodes.get(name)
        if node is None:
            node = nodes.new(kind)
            node.name = name
        node.location = location
        return node

    noise = owned_node("ShaderNodeTexNoise", "Grain", (-650, 120))
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 3.0
    noise.inputs["Roughness"].default_value = 0.7
    color_ramp = owned_node("ShaderNodeValToRGB", "Color", (-400, 230))
    color_ramp.color_ramp.elements[0].color = tuple(channel * 0.65 for channel in color[:3]) + (1.0,)
    color_ramp.color_ramp.elements[1].color = tuple(min(1.0, channel * 1.12) for channel in color[:3]) + (1.0,)
    roughness_map = owned_node("ShaderNodeMapRange", "Roughness", (-400, -40))
    roughness_map.inputs["To Min"].default_value = roughness * 0.72
    roughness_map.inputs["To Max"].default_value = min(1.0, roughness * 1.08)
    bump = owned_node("ShaderNodeBump", "Relief", (-150, -160))
    bump.inputs["Strength"].default_value = 0.18
    bump.inputs["Distance"].default_value = 0.06
    links.new(noise.outputs["Fac"], color_ramp.inputs["Fac"])
    links.new(noise.outputs["Fac"], roughness_map.inputs["Value"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(color_ramp.outputs["Color"], shader.inputs["Base Color"])
    links.new(roughness_map.outputs["Result"], shader.inputs["Roughness"])
    links.new(bump.outputs["Normal"], shader.inputs["Normal"])


def _set_node_input(node, names, value):
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return True
    return False


def _assign_material(obj, mat):
    if hasattr(obj.data, "materials"):
        obj.data.materials.clear()
        obj.data.materials.append(mat)


def _shade_smooth(obj):
    _select_only(bpy.context, obj)
    try:
        bpy.ops.object.shade_smooth()
    except Exception:
        pass


def _select_only(context, obj):
    for selected in context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _delete_scene_objects(context):
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _link_collection(name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def _move_to_collection(obj, collection):
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)


def _import_glb(context, filepath, prefix, collection_name, location=(0, 0, 0), scale=1.0, rotation=(0, 0, 0)):
    if not os.path.exists(filepath):
        return []
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=filepath)
    imported = [obj for obj in bpy.data.objects if obj not in before]
    collection = _link_collection(collection_name)
    root_empty = None
    if len(imported) > 1:
        root_empty = bpy.data.objects.new(prefix + "_Root", None)
        root_empty.empty_display_type = "CUBE"
        root_empty.location = location
        root_empty.rotation_euler = rotation
        root_empty.scale = (scale, scale, scale)
        collection.objects.link(root_empty)
    for obj in imported:
        obj.name = prefix + "_" + obj.name
        _move_to_collection(obj, collection)
        if root_empty is not None and obj.parent is None:
            obj.parent = root_empty
        elif root_empty is None:
            obj.location = Vector(location) + obj.location * scale
            obj.rotation_euler.rotate_axis("X", rotation[0])
            obj.rotation_euler.rotate_axis("Y", rotation[1])
            obj.rotation_euler.rotate_axis("Z", rotation[2])
            obj.scale *= scale
    if root_empty is not None:
        imported.append(root_empty)
    return imported


def _ensure_cyberpunk_city_glb():
    glb_path = os.path.join(CYBERPUNK_CACHE, "source", "scene.glb")
    if os.path.exists(glb_path):
        return glb_path
    if not os.path.exists(CYBERPUNK_ZIP):
        return ""
    os.makedirs(CYBERPUNK_CACHE, exist_ok=True)
    with zipfile.ZipFile(CYBERPUNK_ZIP, "r") as archive:
        archive.extractall(CYBERPUNK_CACHE)
    return glb_path if os.path.exists(glb_path) else ""


def _mark_imported_meshes(objects, tag, static=True):
    for obj in objects:
        if obj.type != "MESH":
            continue
        utils.ensure_component(obj, "MESH_RENDERER")
        if tag:
            obj.blendengine_object.object_tag = tag
        if static:
            optimization.mark_static_object(obj)
            optimization.add_lod_group(obj)
        else:
            optimization.mark_dynamic_object(obj)
            components.add_collider(obj, tag=tag)


def _mesh_triangle_count(mesh):
    if mesh is None:
        return 0
    return sum(max(1, len(poly.vertices) - 2) for poly in mesh.polygons)


def _simplify_mesh(context, obj, target_triangles=3000, min_ratio=0.06):
    if obj.type != "MESH" or obj.data is None:
        return 0, 0
    triangles = _mesh_triangle_count(obj.data)
    if triangles <= target_triangles:
        return triangles, triangles

    ratio = max(min_ratio, min(1.0, target_triangles / float(max(1, triangles))))
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    modifier = obj.modifiers.new("BE_Runtime_Decimate", "DECIMATE")
    modifier.ratio = ratio
    if hasattr(modifier, "use_collapse_triangulate"):
        modifier.use_collapse_triangulate = True
    _select_only(context, obj)
    try:
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    except Exception:
        obj.modifiers.remove(modifier)
    return triangles, _mesh_triangle_count(obj.data)


def _city_material_for(obj, materials):
    names = [obj.name.lower()]
    if obj.type == "MESH" and obj.data is not None:
        names.extend((mat.name.lower() for mat in obj.data.materials if mat is not None))
    text = " ".join(names)
    if "glass" in text:
        return materials["glass"]
    if "light" in text or "neon" in text or "sign" in text or "screen" in text:
        return materials["screen"]
    if "road" in text or "floor" in text or "ground" in text or "asphalt" in text:
        return materials["road"]
    if "chrom" in text or "metal" in text:
        return materials["metal"]
    return materials["wall"]


def _optimize_imported_city(context, objects, materials):
    for obj in objects:
        if obj.type != "MESH":
            continue
        _assign_material(obj, _city_material_for(obj, materials))
        _simplify_mesh(context, obj, target_triangles=760, min_ratio=0.018)
        settings = utils.mark_game_object(obj)
        settings.optimization.disable_when_far = True
        settings.optimization.disable_distance = 70.0
        settings.optimization.collider_simplification = True


def _optimize_imported_character(context, objects, material, target_triangles=2000):
    for obj in objects:
        if obj.type != "MESH":
            continue
        _assign_material(obj, material)
        _simplify_mesh(context, obj, target_triangles=target_triangles, min_ratio=0.04)
        settings = utils.mark_game_object(obj)
        settings.optimization.disable_when_far = True
        settings.optimization.disable_distance = 55.0
        settings.optimization.collider_simplification = True


def _purge_unused_import_data():
    for image in list(bpy.data.images):
        if getattr(image, "name", "").startswith("BE_"):
            continue
        try:
            bpy.data.images.remove(image, do_unlink=True)
        except TypeError:
            bpy.data.images.remove(image)
        except Exception:
            pass
    for datablocks in (bpy.data.materials, bpy.data.textures):
        for datablock in list(datablocks):
            if getattr(datablock, "name", "").startswith("BE_"):
                continue
            if datablock.users == 0:
                try:
                    datablocks.remove(datablock)
                except Exception:
                    pass


def _duplicate_character_hierarchy(source_objects, source_root, name, collection_name, location):
    collection = _link_collection(collection_name)
    mapping = {}
    source_prefix = source_root.name
    for obj in source_objects:
        duplicate = obj.copy()
        duplicate.data = obj.data
        if obj.name.startswith(source_prefix):
            duplicate.name = name + obj.name[len(source_prefix):]
        else:
            duplicate.name = name + "_" + obj.name
        collection.objects.link(duplicate)
        mapping[obj] = duplicate

    for obj, duplicate in mapping.items():
        duplicate.parent = mapping.get(obj.parent)
        if duplicate.parent is None:
            duplicate.location = Vector(location)
        else:
            duplicate.matrix_parent_inverse = obj.matrix_parent_inverse.copy()
            duplicate.location = obj.location.copy()
            duplicate.rotation_euler = obj.rotation_euler.copy()
            duplicate.scale = obj.scale.copy()

    root = mapping[source_root]
    root.name = name
    return list(mapping.values()), root


def _add_neon_set_dressing(context, cyan, magenta, green, asphalt):
    road_line = _cube(context, "BE_Neon_Road_Line", (0, -1.8, 0.02), (24.0, 0.08, 0.03), cyan, "City", static=True)
    road_line.hide_select = True
    for index, y in enumerate((-5.0, -2.4, 0.2, 2.8, 5.4)):
        mat = cyan if index % 2 == 0 else magenta
        strip = _cube(context, "BE_Neon_Crosswalk_%02d" % (index + 1), (-4.0, y, 0.03), (4.2, 0.07, 0.035), mat, "City", static=True)
        strip.hide_select = True
    sign_data = [
        ("BE_Sign_Clinic", (-8.5, -3.2, 3.0), (0.08, 1.8, 0.75), cyan),
        ("BE_Sign_Ammo", (6.4, 4.8, 3.5), (0.08, 1.7, 0.7), magenta),
        ("BE_Sign_Exit", (12.6, 0.0, 3.2), (0.08, 2.2, 0.8), green),
        ("BE_Sign_Warning", (0.0, 5.8, 2.7), (2.5, 0.08, 0.55), magenta),
    ]
    for name, loc, dims, mat in sign_data:
        sign = _cube(context, name, loc, dims, mat, "City", static=True)
        sign.hide_select = True
    wet_reflect = _cube(context, "BE_Wet_Road_Reflection", (0, 0, 0.005), (28.0, 9.0, 0.01), asphalt, "Ground", static=True)
    wet_reflect.hide_select = True


def _setup_realtime_rendering(scene):
    graphics.configure_realtime(scene)
    optimization.apply_preset(scene, "HIGH")
    scene.render.fps = 60
    scene.view_settings.exposure = -0.15
    scene.view_settings.gamma = 1.0
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BE_World")
    scene.world.color = (0.006, 0.009, 0.018)


def _cube(context, name, location, dimensions, material, tag="", static=True):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = context.object
    obj.name = name
    obj.dimensions = dimensions
    _select_only(context, obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _assign_material(obj, material)
    utils.ensure_component(obj, "MESH_RENDERER")
    if tag:
        components.add_collider(obj, tag=tag)
    if static:
        optimization.mark_static_object(obj)
    else:
        optimization.mark_dynamic_object(obj)
    return obj


def _terrain(context, name, size, divisions, material):
    half = size * 0.5
    vertices = []
    faces = []
    for y in range(divisions + 1):
        fy = -half + size * y / divisions
        for x in range(divisions + 1):
            fx = -half + size * x / divisions
            distance = (fx * fx + fy * fy) ** 0.5 / half
            edge_lift = max(0.0, distance - 0.55) * 0.85
            ripple = math.sin(fx * 0.38) * math.cos(fy * 0.31) * 0.18
            z = -0.08 + edge_lift + ripple
            if abs(fx) < 4.0 and abs(fy) < 4.0:
                z *= 0.2
            vertices.append((fx, fy, z))
    stride = divisions + 1
    for y in range(divisions):
        for x in range(divisions):
            a = y * stride + x
            faces.append((a, a + 1, a + stride + 1, a + stride))
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    context.collection.objects.link(obj)
    _assign_material(obj, material)
    utils.ensure_component(obj, "MESH_RENDERER")
    components.add_collider(obj, tag="Ground")
    optimization.mark_static_object(obj)
    optimization.add_lod_group(obj)
    return obj


def _add_tree(context, name, location, trunk_mat, leaf_mat, scale=1.0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=0.12 * scale, depth=1.4 * scale, location=(location[0], location[1], location[2] + 0.7 * scale))
    trunk = context.object
    trunk.name = name + "_Trunk"
    _assign_material(trunk, trunk_mat)
    optimization.mark_static_object(trunk)
    optimization.mark_instancing_candidate(trunk)
    components.add_collider(trunk, tag="Tree")

    bpy.ops.mesh.primitive_cone_add(vertices=14, radius1=0.85 * scale, radius2=0.18 * scale, depth=1.8 * scale, location=(location[0], location[1], location[2] + 1.75 * scale))
    leaves = context.object
    leaves.name = name + "_Leaves"
    _assign_material(leaves, leaf_mat)
    _shade_smooth(leaves)
    optimization.mark_static_object(leaves)
    optimization.mark_instancing_candidate(leaves)
    optimization.add_lod_group(leaves)
    return trunk, leaves


def _add_rock(context, name, location, material, scale=1.0):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.55 * scale, location=location)
    rock = context.object
    rock.name = name
    rock.scale = (1.2 * scale, 0.8 * scale, 0.55 * scale)
    _assign_material(rock, material)
    _shade_smooth(rock)
    optimization.mark_static_object(rock)
    optimization.add_lod_group(rock)
    return rock


def _add_gameplay_label(context, text, location):
    font_curve = bpy.data.curves.new("BE_LabelCurve", "FONT")
    font_curve.body = text
    font_curve.size = 0.38
    font_curve.align_x = "CENTER"
    font_curve.align_y = "CENTER"
    obj = bpy.data.objects.new("BE_Label_" + text.replace(" ", "_"), font_curve)
    obj.location = location
    obj.rotation_euler = (math.radians(68.0), 0.0, 0.0)
    context.collection.objects.link(obj)
    utils.ensure_component(obj, "UI_ELEMENT", tag="WorldLabel")
    return obj


def generate_basic_game_template(context, clean_scene=True):
    scene = context.scene
    project = utils.ensure_project_defaults(scene)
    project.game_title = project.game_title or "My BlendEngine Game"
    project.default_scene = scene
    project.resolution_x = 1280
    project.resolution_y = 720
    project.show_fps = True
    project.show_game_variables = True
    project.debug_mode = True
    scene.render.resolution_x = project.resolution_x
    scene.render.resolution_y = project.resolution_y
    _setup_realtime_rendering(scene)

    if clean_scene:
        _delete_scene_objects(context)
    else:
        bpy.ops.object.select_all(action="DESELECT")

    ground_mat = _material("BE_PBR_MossyGround", (0.16, 0.34, 0.22, 1.0), roughness=0.95, surface_scale=38.0)
    stone_mat = _material("BE_PBR_WetStone", (0.34, 0.36, 0.34, 1.0), roughness=0.5, surface_scale=12.0)
    wall_mat = _material("BE_PBR_RuinedWall", (0.42, 0.43, 0.39, 1.0), roughness=0.86, surface_scale=18.0)
    wood_mat = _material("BE_PBR_DarkWood", (0.23, 0.12, 0.065, 1.0), roughness=0.8, surface_scale=9.0)
    leaf_mat = _material("BE_PBR_ForestLeaves", (0.08, 0.34, 0.17, 1.0), roughness=0.9)
    water_mat = _material("BE_PBR_ShallowWater", (0.15, 0.42, 0.5, 1.0), roughness=0.28, alpha=0.55)
    player_mat = _material("BE_Hero_CyanArmor", (0.0, 0.72, 0.64, 1.0), roughness=0.35, metallic=0.1)
    enemy_mat = _material("BE_Enemy_RedArmor", (0.72, 0.08, 0.08, 1.0), roughness=0.45, metallic=0.05)
    coin_mat = _material("BE_Glowing_GoldCoin", (1.0, 0.68, 0.1, 1.0), roughness=0.32, metallic=0.75, emission=(1.0, 0.48, 0.08, 1.0), emission_strength=0.7)
    health_mat = _material("BE_Health_Emerald", (0.08, 0.9, 0.42, 1.0), roughness=0.4, emission=(0.0, 0.5, 0.16, 1.0), emission_strength=0.35)
    hazard_mat = _material("BE_Hazard_Rift", (0.7, 0.04, 0.48, 1.0), roughness=0.35, emission=(0.9, 0.05, 0.55, 1.0), emission_strength=0.8)
    marker_mat = _material("BE_Goal_Portal", (0.2, 0.82, 1.0, 1.0), roughness=0.25, alpha=0.48, emission=(0.05, 0.75, 1.0, 1.0), emission_strength=1.2)

    ground = _terrain(context, "BE_ForestRuins_Terrain", 40.0, 28, ground_mat)

    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.45, depth=1.8, location=(0.0, 0.0, 0.9))
    player = context.object
    player.name = "BE_Player"
    _assign_material(player, player_mat)
    _shade_smooth(player)
    components.add_player_controller(player)
    player.blendengine_object.player_controller.walk_speed = 5.0
    player.blendengine_object.player_controller.run_speed = 8.0
    optimization.mark_dynamic_object(player)
    components.add_collider(player, tag="Player")
    components.add_health(player, max_health=100.0)
    utils.ensure_example_behavior(player)
    utils.ensure_basic_animation_states(player)
    score = player.blendengine_object.variables.add()
    score.name = "Score"
    score.variable_type = "INT"
    score.int_value = 0
    score.description = "Collect coins to increase score."

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0.0, 0.0, 1.0))
    spawn = context.object
    spawn.name = "BE_PlayerSpawn"
    utils.ensure_component(spawn, "TRIGGER_ZONE", tag="Spawn")

    bpy.ops.mesh.primitive_torus_add(major_radius=1.0, minor_radius=0.08, major_segments=48, minor_segments=8, location=(14.0, 0.0, 1.4))
    trigger = context.object
    trigger.name = "BE_Exit_Portal"
    trigger.rotation_euler.y = math.radians(90.0)
    _assign_material(trigger, marker_mat)
    _shade_smooth(trigger)
    components.add_trigger_zone(trigger)
    optimization.add_lod_group(trigger)
    _add_gameplay_label(context, "Collect 6 coins, avoid rifts, reach portal", (0.0, -8.5, 0.2))

    # Mini-game arena: cover, gates, pickups, enemies, and hazards.
    for index, x in enumerate((-14.0, 14.0)):
        wall = _cube(context, "BE_Arena_Wall_X_%d" % index, (x, 0.0, 1.0), (0.45, 36.0, 2.0), wall_mat, "Wall")
        optimization.add_lod_group(wall)
    for index, y in enumerate((-14.0, 14.0)):
        wall = _cube(context, "BE_Arena_Wall_Y_%d" % index, (0.0, y, 1.0), (36.0, 0.45, 2.0), wall_mat, "Wall")
        optimization.add_lod_group(wall)

    cover_locations = [(-7, -4, 0.6), (-3, 5, 0.6), (4, -6, 0.6), (8, 3, 0.6), (0, 9, 0.6)]
    for index, location in enumerate(cover_locations):
        cover = _cube(context, "BE_Cover_%02d" % (index + 1), location, (2.0, 1.2, 1.2), stone_mat, "Cover")
        optimization.add_lod_group(cover)

    river = _cube(context, "BE_Shallow_River", (-4.5, 11.0, 0.05), (17.0, 2.2, 0.04), water_mat, "Water")
    river.rotation_euler.z = math.radians(-12.0)
    path = _cube(context, "BE_Player_Path", (3.0, -8.0, 0.04), (18.0, 2.0, 0.05), _material("BE_PBR_MudPath", (0.28, 0.19, 0.11, 1.0), roughness=0.98), "Path")
    path.rotation_euler.z = math.radians(17.0)

    for index, loc in enumerate(((-12, -7, 0.0), (-10, 6, 0.0), (-6, 12, 0.0), (5, 11, 0.0), (12, 6, 0.0), (11, -12, 0.0), (-13, 10, 0.0), (3, -12, 0.0))):
        _add_tree(context, "BE_Tree_%02d" % (index + 1), loc, wood_mat, leaf_mat, scale=0.85 + (index % 3) * 0.15)
    for index, loc in enumerate(((-11, 3, 0.45), (-6, -10, 0.4), (1, 12, 0.4), (13, -4, 0.35), (7, 12, 0.35))):
        _add_rock(context, "BE_Rock_%02d" % (index + 1), loc, stone_mat, scale=0.85 + index * 0.08)

    for index, location in enumerate(((-9, 2, 0.35), (-5, -8, 0.35), (2, 6, 0.35), (6, -2, 0.35), (10, 8, 0.35), (12, -7, 0.35))):
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.32, depth=0.25, location=location)
        coin = context.object
        coin.name = "BE_Coin_%02d" % (index + 1)
        _assign_material(coin, coin_mat)
        _shade_smooth(coin)
        components.add_trigger_zone(coin)
        coin.blendengine_object.object_tag = "Coin"
        optimization.mark_dynamic_object(coin)
        behavior = coin.blendengine_object.behaviors.add()
        behavior.name = "Collect Coin"
        event = behavior.events.add()
        event.name = "Player Touch"
        event.event_type = "ON_ENTER_TRIGGER"
        event.tag = "Player"
        action = behavior.actions.add()
        action.name = "Coin Log"
        action.action_type = "SHOW_LOG"
        action.text_value = "Coin collected."

    for index, location in enumerate(((-11, -10, 0.35), (9, -10, 0.35))):
        health = _cube(context, "BE_HealthPickup_%02d" % (index + 1), location, (0.7, 0.7, 0.7), health_mat, "", static=False)
        components.add_trigger_zone(health)
        health.blendengine_object.object_tag = "Health"

    for index, location in enumerate(((-2, -2, 0.12), (4, 5, 0.12), (10, 0, 0.12))):
        hazard = _cube(context, "BE_DamageZone_%02d" % (index + 1), location, (2.6, 2.6, 0.22), hazard_mat, "", static=False)
        components.add_trigger_zone(hazard)
        hazard.blendengine_object.object_tag = "Damage"
        behavior = hazard.blendengine_object.behaviors.add()
        behavior.name = "Damage Player"
        event = behavior.events.add()
        event.name = "Player Enter"
        event.event_type = "ON_ENTER_TRIGGER"
        event.tag = "Player"
        action = behavior.actions.add()
        action.name = "Damage Log"
        action.action_type = "SHOW_LOG"
        action.text_value = "Damage zone touched."

    enemy_positions = [(-8.0, 8.0, 0.9), (7.0, 7.0, 0.9), (9.0, -8.0, 0.9)]
    enemy_templates = ["PATROL", "FOLLOW_PLAYER", "ATTACK"]
    for index, location in enumerate(enemy_positions):
        bpy.ops.mesh.primitive_cylinder_add(vertices=18, radius=0.42, depth=1.7, location=location)
        enemy = context.object
        enemy.name = "BE_Enemy_%02d" % (index + 1)
        _assign_material(enemy, enemy_mat)
        _shade_smooth(enemy)
        components.add_collider(enemy, tag="Enemy")
        components.add_health(enemy, max_health=50.0 + index * 25.0)
        npc = components.add_npc_behavior(enemy, enemy_templates[index], target=player)
        npc.move_speed = 2.2 + index * 0.5
        npc.patrol_radius = 3.0 + index
        optimization.mark_dynamic_object(enemy)
        utils.ensure_basic_animation_states(enemy)

    gate = _cube(context, "BE_LockedGate", (12.5, 0.0, 1.4), (0.5, 4.0, 2.8), wall_mat, "Door")
    utils.ensure_component(gate, "DOOR", tag="Door")
    gate.blendengine_object.object_tag = "Gate"

    checkpoint = _cube(context, "BE_Checkpoint", (-12.0, 0.0, 0.6), (1.2, 1.2, 1.2), marker_mat, "", static=False)
    components.add_trigger_zone(checkpoint)
    checkpoint.blendengine_object.object_tag = "Checkpoint"

    bpy.ops.object.light_add(type="SUN", location=(0.0, -4.0, 6.0))
    sun = context.object
    sun.name = "BE_Sun"
    sun.rotation_euler = (math.radians(52.0), 0.0, math.radians(32.0))
    if hasattr(sun.data, "energy"):
        sun.data.energy = 3.0
    if hasattr(sun.data, "angle"):
        sun.data.angle = math.radians(5.0)
    optimization.mark_baked_lighting_candidate(sun)

    bpy.ops.object.light_add(type="AREA", location=(0.0, -5.0, 5.5))
    fill = context.object
    fill.name = "BE_Soft_Sky_Fill"
    fill.rotation_euler = (math.radians(65.0), 0.0, 0.0)
    fill.data.energy = 180.0
    fill.data.size = 8.0
    if hasattr(fill.data, "use_shadow"):
        fill.data.use_shadow = False

    bpy.ops.object.light_add(type="POINT", location=(14.0, 0.0, 2.4))
    portal_light = context.object
    portal_light.name = "BE_Portal_Light"
    portal_light.data.energy = 160.0
    portal_light.data.color = (0.18, 0.82, 1.0)
    portal_light.data.shadow_soft_size = 4.0
    if hasattr(portal_light.data, "use_shadow"):
        portal_light.data.use_shadow = False

    bpy.ops.object.camera_add(location=(0.0, -7.8, 4.3), rotation=(math.radians(63.0), 0.0, 0.0))
    camera = context.object
    camera.name = "BE_GameCamera"
    camera.data.lens = 28
    camera.data.dof.use_dof = True
    camera.data.dof.focus_object = player
    camera.data.dof.aperture_fstop = 7.5
    scene.camera = camera
    player.blendengine_object.player_controller.camera_follow = camera
    utils.ensure_component(camera, "CAMERA_CONTROLLER", tag="MainCamera")

    input_system.ensure_defaults(scene)

    _select_only(context, player)

    return {
        "ground": ground,
        "player": player,
        "spawn": spawn,
        "trigger": trigger,
        "sun": sun,
        "camera": camera,
    }


def _add_first_person_arms(context, camera, skin_mat):
    arms = []
    for side, x in (("L", -0.18), ("R", 0.18)):
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.045, depth=0.7, location=(0, 0, 0))
        arm = context.object
        arm.name = "BE_FP_Arm_%s" % side
        _assign_material(arm, skin_mat)
        _shade_smooth(arm)
        arm.parent = camera
        arm.location = (x, -0.24, -0.62)
        arm.rotation_euler = (math.radians(72), math.radians(9 if side == "L" else -9), 0)
        arm.blendengine_object.object_tag = "FirstPersonArms"
        utils.ensure_component(arm, "MESH_RENDERER")
        optimization.mark_dynamic_object(arm)
        arms.append(arm)
    return arms


def _add_fallback_gun(context, camera, material):
    body = _cube(context, "BE_Runtime_Rifle", (0, 0, 0), (0.22, 0.78, 0.16), material, "Weapon", static=False)
    barrel = _cube(context, "BE_Runtime_Rifle_Barrel", (0, 0, 0), (0.08, 0.62, 0.08), material, "Weapon", static=False)
    body.parent = camera
    barrel.parent = camera
    body.location = (0.23, -0.38, -0.55)
    barrel.location = (0.24, -0.78, -0.54)
    body.rotation_euler = (math.radians(82), 0, 0)
    barrel.rotation_euler = (math.radians(82), 0, 0)
    return [body, barrel]


def _setup_imported_gun(context, camera, material):
    gun_objects = _import_glb(context, SCAR_MODEL, "BE_SCAR", "BE_Weapon", scale=0.13)
    if not gun_objects:
        return _add_fallback_gun(context, camera, material)
    for obj in gun_objects:
        obj.parent = camera
        obj.location = (0.28, -0.46, -0.58)
        obj.rotation_euler = (math.radians(82), 0.0, math.radians(180))
        obj.scale *= 0.13
        obj.blendengine_object.object_tag = "Weapon"
        utils.ensure_component(obj, "WEAPON", tag="Weapon")
        optimization.mark_dynamic_object(obj)
        if obj.type == "MESH":
            _assign_material(obj, material)
            _simplify_mesh(context, obj, target_triangles=1400, min_ratio=0.08)
    _purge_unused_import_data()
    return gun_objects


def _setup_imported_character(context, filepath, prefix, collection, location, scale, tag, target=None):
    objects = _import_glb(context, filepath, prefix, collection, location=location, scale=scale)
    if not objects:
        bpy.ops.mesh.primitive_cylinder_add(vertices=18, radius=0.38 * scale, depth=1.6 * scale, location=location)
        objects = [context.object]
        context.object.name = prefix + "_Capsule"
    root = objects[-1] if objects and objects[-1].type == "EMPTY" else objects[0]
    root.location = location
    root.scale = (scale, scale, scale)
    root.blendengine_object.object_tag = tag
    for obj in objects:
        obj.blendengine_object.object_tag = tag
        if obj.type == "MESH":
            utils.ensure_component(obj, "MESH_RENDERER")
    if tag == "Zombie":
        components.add_collider(root, tag="Zombie")
        components.add_health(root, max_health=100.0)
        npc = components.add_npc_behavior(root, "ATTACK", target=target)
        npc.move_speed = 2.6
        npc.attack_range = 1.55
        npc.detection_range = 35.0
        optimization.mark_dynamic_object(root)
        utils.ensure_basic_animation_states(root)
    return objects, root


def generate_cyberpunk_shooter_template(context, clean_scene=True):
    scene = context.scene
    project = utils.ensure_project_defaults(scene)
    project.game_title = "Neon Quarantine"
    project.default_scene = scene
    project.game_dimension = "THREE_D"
    project.resolution_x = 1600
    project.resolution_y = 900
    project.show_fps = True
    project.show_game_variables = True
    project.show_logs = True
    project.debug_mode = True
    scene.render.resolution_x = project.resolution_x
    scene.render.resolution_y = project.resolution_y
    _setup_realtime_rendering(scene)

    if clean_scene:
        _delete_scene_objects(context)
    else:
        bpy.ops.object.select_all(action="DESELECT")

    neon_cyan = _material("BE_Neon_Cyan", (0.0, 0.75, 1.0, 1.0), roughness=0.25, emission=(0.0, 0.8, 1.0, 1.0), emission_strength=1.4)
    neon_magenta = _material("BE_Neon_Magenta", (1.0, 0.05, 0.48, 1.0), roughness=0.28, emission=(1.0, 0.0, 0.35, 1.0), emission_strength=1.2)
    asphalt = _material("BE_Wet_Asphalt", (0.025, 0.028, 0.032, 1.0), roughness=0.3, metallic=0.0, surface_scale=65.0)
    skin = _material("BE_FirstPerson_Sleeves", (0.12, 0.15, 0.18, 1.0), roughness=0.62)
    weapon_mat = _material("BE_SCAR_DarkMetal", (0.05, 0.055, 0.06, 1.0), roughness=0.35, metallic=0.55)
    zombie_tint = _material("BE_Zombie_Tint", (0.28, 0.46, 0.36, 1.0), roughness=0.7)
    city_materials = {
        "road": asphalt,
        "metal": _material("BE_City_DarkMetal", (0.055, 0.06, 0.075, 1.0), roughness=0.38, metallic=0.35),
        "wall": _material("BE_City_BlackConcrete", (0.035, 0.038, 0.045, 1.0), roughness=0.72, metallic=0.0, surface_scale=24.0),
        "glass": _material("BE_City_Glass_Cyan", (0.02, 0.16, 0.2, 0.58), roughness=0.16, metallic=0.0, alpha=0.58, emission=(0.0, 0.35, 0.55, 1.0), emission_strength=0.35),
        "screen": _material("BE_City_Emissive_Screen", (0.04, 0.7, 1.0, 1.0), roughness=0.25, emission=(0.0, 0.75, 1.0, 1.0), emission_strength=1.15),
    }

    city_glb = _ensure_cyberpunk_city_glb()
    city_objects = _import_glb(context, city_glb, "BE_City", "BE_CyberpunkCity", scale=1.0) if city_glb else []
    _mark_imported_meshes(city_objects, "City", static=True)
    _optimize_imported_city(context, city_objects, city_materials)
    _purge_unused_import_data()
    if city_objects:
        for obj in city_objects:
            obj.location.x -= 1.5
            obj.location.y -= 0.5
    else:
        _cube(context, "BE_Fallback_NeonStreet", (0, 0, -0.05), (42, 18, 0.1), asphalt, "Ground")
        for i, x in enumerate((-14, -8, 8, 14)):
            _cube(context, "BE_Fallback_Tower_%d" % i, (x, 6 if i % 2 else -6, 5), (3, 3, 10), asphalt, "City")

    ground = _cube(context, "BE_Shooter_Collision_Floor", (0, 0, -0.08), (36, 20, 0.12), asphalt, "Ground")
    ground.display_type = "WIRE"
    ground.hide_render = True
    _add_neon_set_dressing(context, neon_cyan, neon_magenta, _material("BE_Neon_Green", (0.1, 1.0, 0.55, 1.0), roughness=0.25, emission=(0.08, 1.0, 0.52, 1.0), emission_strength=1.25), asphalt)

    for index, (name, loc, mat) in enumerate((
        ("MED", (-8, -3, 0.5), neon_cyan),
        ("AMMO", (6, 5, 0.5), neon_magenta),
        ("EXIT", (13, 0, 1.4), neon_cyan),
    )):
        pickup = _cube(context, "BE_%s_Pickup" % name, loc, (0.6, 0.6, 0.6), mat, name.title(), static=False)
        components.add_trigger_zone(pickup)
        pickup.display_type = "WIRE"

    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.38, depth=1.8, location=(0.0, -5.0, 0.9))
    player = context.object
    player.name = "BE_Player_FirstPersonBody"
    player.display_type = "WIRE"
    player.hide_render = True
    player.blendengine_object.object_tag = "PlayerBody"
    components.add_player_controller(player)
    player.blendengine_object.player_controller.controller_type = "FIRST_PERSON"
    player.blendengine_object.player_controller.walk_speed = 5.5
    player.blendengine_object.player_controller.run_speed = 9.0
    components.add_collider(player, tag="Player")
    components.add_health(player, max_health=150.0)
    optimization.mark_dynamic_object(player)
    utils.ensure_basic_animation_states(player)
    for name, value in (("Score", 0), ("Ammo", 90), ("Kills", 0)):
        var = player.blendengine_object.variables.add()
        var.name = name
        var.variable_type = "INT"
        var.int_value = value

    bpy.ops.object.camera_add(location=(0.0, -5.0, 1.62), rotation=(math.radians(90.0), 0.0, 0.0))
    camera = context.object
    camera.name = "BE_FPS_Camera"
    camera.data.lens = 35
    camera.data.clip_end = 220.0
    camera.data.dof.use_dof = False
    scene.camera = camera
    player.blendengine_object.player_controller.camera_follow = camera
    utils.ensure_component(camera, "CAMERA_CONTROLLER", tag="MainCamera")
    _setup_imported_gun(context, camera, weapon_mat)
    _add_first_person_arms(context, camera, skin)

    zombie_positions = [(0, 1.8, 0.85), (-6, 2, 0.85), (-2, 5, 0.85), (4, 4, 0.85), (8, -2, 0.85), (-10, -1, 0.85), (10, 5, 0.85)]
    source_zombie_objects = []
    source_zombie_root = None
    for index, location in enumerate(zombie_positions):
        zombie_name = "BE_Zombie_%02d" % (index + 1)
        if index == 0 or not source_zombie_objects or source_zombie_root is None:
            objects, root = _setup_imported_character(
                context,
                ZOMBIE_MODEL,
                zombie_name,
                "BE_Zombies",
                location,
                1.65,
                "Zombie",
                target=player,
            )
            _optimize_imported_character(context, objects, zombie_tint, target_triangles=2000)
            _purge_unused_import_data()
            source_zombie_objects = objects
            source_zombie_root = root
        else:
            objects, root = _duplicate_character_hierarchy(source_zombie_objects, source_zombie_root, zombie_name, "BE_Zombies", location)
        root.name = "BE_Zombie_%02d" % (index + 1)

    for index, (loc, color, energy) in enumerate((
        ((-8, -4, 4), (0.0, 0.7, 1.0), 450),
        ((5, -1, 5), (1.0, 0.05, 0.45), 360),
        ((11, 3, 4), (0.1, 1.0, 0.55), 300),
    )):
        bpy.ops.object.light_add(type="POINT", location=loc)
        light = context.object
        light.name = "BE_Neon_Light_%02d" % (index + 1)
        light.data.energy = energy
        light.data.color = color
        light.data.shadow_soft_size = 5.0
        if hasattr(light.data, "use_shadow"):
            light.data.use_shadow = index == 0
        if index > 0:
            optimization.mark_baked_lighting_candidate(light)

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 8))
    sun = context.object
    sun.name = "BE_Moon_Sun"
    sun.rotation_euler = (math.radians(62), 0, math.radians(25))
    sun.data.energy = 0.35
    if hasattr(sun.data, "use_shadow"):
        sun.data.use_shadow = False
    if hasattr(sun.data, "angle"):
        sun.data.angle = math.radians(7)
    optimization.mark_baked_lighting_candidate(sun)

    input_system.ensure_defaults(scene)
    input_system.add_binding(scene, action="ATTACK", key="LEFTMOUSE")
    input_system.add_binding(scene, action="AIM", key="RIGHTMOUSE")
    _select_only(context, player)
    return {
        "player": player,
        "camera": camera,
        "city_objects": city_objects,
        "zombie_count": len(zombie_positions),
    }


def generate_2d_game_template(context, clean_scene=True):
    scene = context.scene
    project = utils.ensure_project_defaults(scene)
    project.game_dimension = "TWO_D"
    project.game_title = project.game_title or "My 2D BlendEngine Game"
    project.default_scene = scene
    project.resolution_x = 1280
    project.resolution_y = 720
    scene.render.resolution_x = project.resolution_x
    scene.render.resolution_y = project.resolution_y
    optimization.apply_one_gb_runtime_plan(scene)

    if clean_scene:
        _delete_scene_objects(context)
    else:
        bpy.ops.object.select_all(action="DESELECT")

    ground_mat = _material("BE_2D_Ground", (0.18, 0.45, 0.22, 1.0))
    player_mat = _material("BE_2D_Player", (0.1, 0.34, 0.95, 1.0))
    goal_mat = _material("BE_2D_Goal", (1.0, 0.78, 0.15, 1.0))

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, -0.1))
    ground = context.object
    ground.name = "BE_2D_Ground"
    ground.dimensions = (18.0, 0.25, 0.2)
    _select_only(context, ground)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _assign_material(ground, ground_mat)
    components.add_collider(ground, tag="Ground")
    optimization.mark_static_object(ground)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-5.0, 0.0, 0.65))
    player = context.object
    player.name = "BE_2D_Player"
    player.dimensions = (0.7, 0.25, 1.3)
    _select_only(context, player)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _assign_material(player, player_mat)
    components.add_player_controller(player)
    player.blendengine_object.player_controller.controller_type = "SIDE_SCROLLER"
    player.blendengine_object.player_controller.walk_speed = 5.0
    optimization.mark_dynamic_object(player)
    components.add_collider(player, tag="Player")
    components.add_health(player, max_health=100.0)
    utils.ensure_example_behavior(player)
    utils.ensure_basic_animation_states(player)

    for index, x in enumerate((-1.5, 2.0, 4.2)):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, 0.0, 0.45 + index * 0.25))
        platform = context.object
        platform.name = "BE_2D_Platform_%d" % (index + 1)
        platform.dimensions = (2.2, 0.25, 0.25)
        _select_only(context, platform)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        _assign_material(platform, ground_mat)
        components.add_collider(platform, tag="Ground")
        optimization.mark_static_object(platform)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(7.0, 0.0, 0.7))
    goal = context.object
    goal.name = "BE_2D_Goal"
    goal.dimensions = (0.8, 0.25, 1.4)
    _select_only(context, goal)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _assign_material(goal, goal_mat)
    components.add_trigger_zone(goal)
    goal.blendengine_object.object_tag = "Goal"

    bpy.ops.object.light_add(type="SUN", location=(0.0, -4.0, 6.0))
    sun = context.object
    sun.name = "BE_2D_Sun"
    sun.rotation_euler = (math.radians(50.0), 0.0, 0.0)
    optimization.mark_baked_lighting_candidate(sun)

    bpy.ops.object.camera_add(location=(0.0, -12.0, 4.0), rotation=(math.radians(72.0), 0.0, 0.0))
    camera = context.object
    camera.name = "BE_2D_Camera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 8.0
    scene.camera = camera
    player.blendengine_object.player_controller.camera_follow = camera
    utils.ensure_component(camera, "CAMERA_CONTROLLER", tag="MainCamera")

    input_system.ensure_defaults(scene)
    _select_only(context, player)

    return {
        "ground": ground,
        "player": player,
        "goal": goal,
        "sun": sun,
        "camera": camera,
    }


def register():
    pass


def unregister():
    pass
