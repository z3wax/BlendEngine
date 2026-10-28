# SPDX-License-Identifier: GPL-2.0-or-later
#
# Optimization architecture helpers.

import bpy

from . import graphics, utils


PRESET_VALUES = {
    "ULTRA_LOW": {
        "name": "Ultra Low",
        "target_fps": 30,
        "resolution_scale": 0.5,
        "texture_quality": "LOW",
        "shadow_quality": "OFF",
        "shadow_distance": 10.0,
        "anti_aliasing": "OFF",
        "ambient_occlusion": False,
        "bloom": False,
        "reflections": False,
        "volumetrics": False,
        "motion_blur": False,
        "lod_multiplier": 0.45,
        "max_dynamic_lights": 1,
        "max_shadow_casters": 0,
        "physics_quality": "LOW",
        "animation_update_rate": 15,
        "animation_quality": "LOW",
        "particles_quality": "LOW",
        "vegetation_density": 0.15,
        "reflection_quality": "OFF",
        "post_processing_quality": "LOW",
        "budget": (100000, 300, 128, 1, 0, 30, 3000, 250, 30),
    },
    "LOW": {
        "name": "Low",
        "target_fps": 45,
        "resolution_scale": 0.7,
        "texture_quality": "LOW",
        "shadow_quality": "LOW",
        "shadow_distance": 18.0,
        "anti_aliasing": "FXAA",
        "ambient_occlusion": False,
        "bloom": False,
        "reflections": False,
        "volumetrics": False,
        "motion_blur": False,
        "lod_multiplier": 0.65,
        "max_dynamic_lights": 2,
        "max_shadow_casters": 1,
        "physics_quality": "LOW",
        "animation_update_rate": 20,
        "animation_quality": "LOW",
        "particles_quality": "LOW",
        "vegetation_density": 0.25,
        "reflection_quality": "LOW",
        "post_processing_quality": "LOW",
        "budget": (180000, 500, 256, 2, 1, 50, 6000, 400, 45),
    },
    "BALANCED": {
        "name": "Balanced",
        "target_fps": 60,
        "resolution_scale": 1.0,
        "texture_quality": "MEDIUM",
        "shadow_quality": "MEDIUM",
        "shadow_distance": 40.0,
        "anti_aliasing": "TAA_2X",
        "ambient_occlusion": True,
        "bloom": True,
        "reflections": False,
        "volumetrics": False,
        "motion_blur": False,
        "lod_multiplier": 1.0,
        "max_dynamic_lights": 4,
        "max_shadow_casters": 2,
        "physics_quality": "MEDIUM",
        "animation_update_rate": 30,
        "animation_quality": "MEDIUM",
        "particles_quality": "MEDIUM",
        "vegetation_density": 0.6,
        "reflection_quality": "LOW",
        "post_processing_quality": "MEDIUM",
        "budget": (300000, 800, 512, 4, 2, 80, 15000, 700, 60),
    },
    "HIGH": {
        "name": "High",
        "target_fps": 60,
        "resolution_scale": 1.0,
        "texture_quality": "HIGH",
        "shadow_quality": "HIGH",
        "shadow_distance": 70.0,
        "anti_aliasing": "TAA_4X",
        "ambient_occlusion": True,
        "bloom": True,
        "reflections": True,
        "volumetrics": False,
        "motion_blur": False,
        "lod_multiplier": 1.35,
        "max_dynamic_lights": 6,
        "max_shadow_casters": 4,
        "physics_quality": "HIGH",
        "animation_update_rate": 45,
        "animation_quality": "HIGH",
        "particles_quality": "HIGH",
        "vegetation_density": 0.8,
        "reflection_quality": "MEDIUM",
        "post_processing_quality": "HIGH",
        "budget": (600000, 1200, 1024, 6, 4, 140, 30000, 1200, 60),
    },
    "CINEMATIC": {
        "name": "Cinematic",
        "target_fps": 30,
        "resolution_scale": 1.0,
        "texture_quality": "ULTRA",
        "shadow_quality": "ULTRA",
        "shadow_distance": 120.0,
        "anti_aliasing": "TAA_8X",
        "ambient_occlusion": True,
        "bloom": True,
        "reflections": True,
        "volumetrics": True,
        "motion_blur": True,
        "lod_multiplier": 1.75,
        "max_dynamic_lights": 10,
        "max_shadow_casters": 8,
        "physics_quality": "HIGH",
        "animation_update_rate": 60,
        "animation_quality": "ULTRA",
        "particles_quality": "ULTRA",
        "vegetation_density": 1.0,
        "reflection_quality": "HIGH",
        "post_processing_quality": "ULTRA",
        "budget": (1200000, 1800, 2048, 10, 8, 220, 60000, 2000, 30),
    },
}


def apply_preset(scene, preset=None):
    profile = scene.blendengine_quality_profile
    budget = scene.blendengine_performance_budget
    optimization = scene.blendengine_optimization

    preset = preset or profile.preset
    if preset == "CUSTOM":
        profile.preset = "CUSTOM"
        graphics.apply_profile(scene, profile)
        return profile

    values = PRESET_VALUES[preset]
    profile.preset = preset
    for key, value in values.items():
        if key == "budget":
            continue
        setattr(profile, key, value)

    (
        budget.max_triangles_visible,
        budget.max_draw_calls_estimated,
        budget.max_texture_memory_mb,
        budget.max_dynamic_lights,
        budget.max_shadow_casters,
        budget.max_rigidbodies,
        budget.max_particles,
        budget.max_bones_visible,
        budget.target_fps,
    ) = values["budget"]

    optimization.weak_hardware_target = preset in {"ULTRA_LOW", "LOW", "BALANCED"}
    if preset in {"HIGH", "CINEMATIC"}:
        optimization.one_gb_ram_mode = False
    optimization.prefer_baked_lighting = preset in {"ULTRA_LOW", "LOW", "BALANCED", "HIGH"}
    optimization.use_lod_strategy = True
    optimization.use_impostors = preset in {"ULTRA_LOW", "LOW", "BALANCED"}
    optimization.use_texture_atlases = True
    optimization.use_material_batching = True
    optimization.use_instancing = True
    optimization.use_animation_culling = preset in {"ULTRA_LOW", "LOW", "BALANCED"}
    optimization.use_physics_culling = True
    optimization.use_simplified_colliders = True
    optimization.camera_frustum_generation = True
    optimization.hide_behind_camera = preset in {"ULTRA_LOW", "LOW", "BALANCED"}
    optimization.hidden_surface_culling = True
    optimization.texture_streaming = True
    optimization.mesh_streaming = True
    optimization.dynamic_resolution = True
    optimization.emergency_quality_drop = True
    optimization.scalable_post_processing = True
    graphics.apply_profile(scene, profile)
    optimization.last_report_summary = "Applied %s optimization preset." % values["name"]
    return profile


def _mark_component(obj, component_type, note):
    component = utils.ensure_component(obj, component_type)
    if component is not None:
        component.notes = note
    return component


def mark_static_object(obj):
    settings = utils.mark_game_object(obj)
    opt = settings.optimization
    opt.static_object = True
    opt.dynamic_object = False
    opt.merge_candidate = True
    opt.baked_lighting_candidate = True
    _mark_component(obj, "STATIC_OBJECT", "Marked as static for future batching, culling, and baked lighting.")
    _mark_component(obj, "MERGE_CANDIDATE", "Can be merged with nearby static objects later.")
    _mark_component(obj, "BAKED_LIGHTING_CANDIDATE", "Prefer baked lighting when possible.")
    return opt


def mark_dynamic_object(obj):
    settings = utils.mark_game_object(obj)
    opt = settings.optimization
    opt.dynamic_object = True
    opt.static_object = False
    _mark_component(obj, "DYNAMIC_OBJECT", "Marked as moving or changing during gameplay.")
    return opt


def mark_instancing_candidate(obj):
    settings = utils.mark_game_object(obj)
    settings.optimization.instancing_candidate = True
    _mark_component(obj, "INSTANCING_CANDIDATE", "Future runtime can draw repeated copies more cheaply.")
    return settings.optimization


def mark_baked_lighting_candidate(obj):
    settings = utils.mark_game_object(obj)
    settings.optimization.baked_lighting_candidate = True
    _mark_component(obj, "BAKED_LIGHTING_CANDIDATE", "Prefer baked lighting over real-time lighting for this object.")
    return settings.optimization


def add_lod_group(obj, placeholders=2):
    settings = utils.mark_game_object(obj)
    opt = settings.optimization
    opt.lod_group = True
    opt.lod_placeholder_count = max(opt.lod_placeholder_count, placeholders)
    opt.disable_when_far = True
    _mark_component(obj, "LOD_GROUP", "LOD marker used by reports, runtime planning, and build packages.")
    _mark_component(obj, "DISABLE_WHEN_FAR", "Can switch to cheaper detail or disable when far away.")
    return opt


def mark_scene_static_candidates(scene):
    count = 0
    for obj in scene.objects:
        if obj.type == "MESH" and getattr(obj, "rigid_body", None) is None:
            mark_static_object(obj)
            count += 1
    return count


def generate_lod_placeholders(scene, triangle_threshold=2500):
    count = 0
    for obj in scene.objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        triangles = sum(max(1, len(poly.vertices) - 2) for poly in obj.data.polygons)
        if triangles >= triangle_threshold:
            add_lod_group(obj)
            count += 1
    return count


def make_game_lighter_suggestions(scene):
    profile = scene.blendengine_quality_profile
    optimization = scene.blendengine_optimization
    return [
        "Use the Low or Balanced preset if this game targets weak computers.",
        "Lower render resolution scale from %.2f if the frame rate is unstable." % profile.resolution_scale,
        "Keep runtime memory under %d MB with texture streaming, mesh streaming, and world cells." %
        optimization.max_runtime_ram_mb,
        "Generate only the visible camera area, then preload a small ring of nearby cells.",
        "Unload objects behind the camera and objects hidden behind large occluders.",
        "Prefer baked lighting and keep only a few real-time shadow casters.",
        "Add LOD markers to complex objects so runtime builds can show cheaper versions far away.",
        "Use shared materials or texture atlases so many small objects draw more cheaply.",
        "Mark repeated props as Instancing Candidates.",
        "Use simplified colliders and enable Physics Sleep on objects that do not move often.",
        "Update far NPC animations less often with Animation Culling.",
        "Compress or downsize very large textures before shipping.",
    ]


def apply_safe_lightweight_flags(scene):
    profile = apply_preset(scene, "LOW")
    marked_static = mark_scene_static_candidates(scene)
    lod_count = generate_lod_placeholders(scene)
    for obj in scene.objects:
        if obj.type == "MESH":
            settings = utils.mark_game_object(obj)
            settings.optimization.collider_simplification = True
            settings.optimization.physics_sleep = True
            _mark_component(obj, "COLLIDER_SIMPLIFICATION", "Use simple colliders in runtime builds.")
            _mark_component(obj, "PHYSICS_SLEEP", "Let physics sleep when this object is idle.")
    return profile, marked_static, lod_count


def apply_one_gb_runtime_plan(scene):
    profile = apply_preset(scene, "LOW")
    optimization = scene.blendengine_optimization
    optimization.one_gb_ram_mode = True
    optimization.max_runtime_ram_mb = 1024
    optimization.camera_frustum_generation = True
    optimization.hide_behind_camera = True
    optimization.hidden_surface_culling = True
    optimization.texture_streaming = True
    optimization.mesh_streaming = True
    optimization.use_occlusion_culling = True
    optimization.use_frustum_culling = True
    optimization.use_lod_strategy = True
    optimization.use_impostors = True
    optimization.use_instancing = True
    optimization.use_material_batching = True
    optimization.use_texture_atlases = True
    optimization.use_animation_culling = True
    optimization.use_physics_culling = True
    optimization.use_simplified_colliders = True
    optimization.async_asset_loading = True
    optimization.level_streaming = True
    optimization.scalable_post_processing = True
    optimization.world_cell_size = 20.0
    optimization.visible_cell_radius = 2
    optimization.max_visible_objects = 180
    optimization.generation_budget_ms = 2.0
    optimization.dynamic_resolution = True
    optimization.emergency_quality_drop = True

    marked_static = mark_scene_static_candidates(scene)
    lod_count = generate_lod_placeholders(scene, triangle_threshold=1200)
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        settings = utils.mark_game_object(obj)
        settings.optimization.disable_when_far = True
        settings.optimization.disable_distance = 60.0
        settings.optimization.collider_simplification = True
        settings.optimization.physics_sleep = True
        if not settings.optimization.dynamic_object:
            settings.optimization.baked_lighting_candidate = True
            settings.optimization.merge_candidate = True
        _mark_component(obj, "DISABLE_WHEN_FAR", "Runtime may hide or stream this object when outside the camera area.")
        _mark_component(obj, "COLLIDER_SIMPLIFICATION", "Use simple colliders to protect weak computers.")
        _mark_component(obj, "PHYSICS_SLEEP", "Sleep physics before frame rate drops.")
    for obj in scene.objects:
        if obj.type != "LIGHT":
            continue
        light = getattr(obj, "data", None)
        if light is not None and hasattr(light, "use_shadow"):
            light.use_shadow = False
        mark_baked_lighting_candidate(obj)
    return profile, marked_static, lod_count


def platform_defaults(scene, platform):
    project = scene.blendengine_project
    project.target_platform = platform
    if platform in {"ANDROID", "IOS", "WEB"}:
        project.resolution_x = 1280
        project.resolution_y = 720
        apply_one_gb_runtime_plan(scene)
    elif platform == "MACOS":
        project.resolution_x = 1600
        project.resolution_y = 900
        scene.blendengine_optimization.one_gb_ram_mode = False
        apply_preset(scene, "HIGH")
    elif platform == "LINUX":
        project.resolution_x = 1280
        project.resolution_y = 720
        scene.blendengine_optimization.one_gb_ram_mode = False
        apply_preset(scene, "HIGH")
    else:
        project.resolution_x = 1280
        project.resolution_y = 720
        scene.blendengine_optimization.one_gb_ram_mode = False
        apply_preset(scene, "HIGH")
    scene.render.resolution_x = project.resolution_x
    scene.render.resolution_y = project.resolution_y
    return project


def register():
    pass


def unregister():
    pass
