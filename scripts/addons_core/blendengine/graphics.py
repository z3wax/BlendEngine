# SPDX-License-Identifier: GPL-2.0-or-later
#
# Map game quality profiles to real EEVEE settings without rebuilding a scene.


EEVEE_ENGINES = {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}

_SAMPLES = {
    "OFF": (1, 1),
    # EEVEE uses temporal sampling; this is the inexpensive fallback for FXAA.
    "FXAA": (8, 16),
    "TAA_2X": (32, 64),
    "TAA_4X": (64, 128),
    "TAA_8X": (128, 256),
}

_SHADOWS = {
    # Map resolution, pool MB, ray count, steps, resolution scale.
    "OFF": ("256", "16", 1, 2, 0.25),
    "LOW": ("512", "64", 1, 4, 0.5),
    "MEDIUM": ("1024", "128", 2, 8, 0.75),
    "HIGH": ("2048", "256", 3, 12, 1.0),
    "ULTRA": ("4096", "512", 4, 16, 1.0),
}

_REFLECTIONS = {
    # Trace resolution divisor, precision, maximum traced roughness.
    "OFF": ("4", 0.25, 0.0),
    "LOW": ("4", 0.25, 0.4),
    "MEDIUM": ("2", 0.75, 0.65),
    "HIGH": ("1", 1.0, 0.8),
    "ULTRA": ("1", 1.0, 0.8),
}

_VOLUMES = {
    "OFF": (16, "16"),
    "LOW": (16, "16"),
    "MEDIUM": (32, "8"),
    "HIGH": (64, "4"),
    "ULTRA": (128, "4"),
}


def _set(target, name, value, path, result):
    """Only write properties provided by this Blender version's renderer."""
    if target is None or not hasattr(target, name):
        return False
    setattr(target, name, value)
    result["applied"][path + "." + name] = value
    return True


def _tone_mapping(scene, result):
    """Choose a highlight-preserving display transform, keeping exposure/gamma."""
    settings = scene.view_settings
    for transform, looks in (
        ("AgX", ("AgX - Medium High Contrast", "None")),
        ("Filmic", ("Medium High Contrast", "None")),
    ):
        try:
            settings.view_transform = transform
        except (TypeError, ValueError):
            continue
        result["applied"]["view_settings.view_transform"] = transform
        for look in looks:
            try:
                settings.look = look
            except (TypeError, ValueError):
                continue
            result["applied"]["view_settings.look"] = look
            break
        return
    result["unsupported"].append("AgX/Filmic display transform")


def configure_realtime(scene):
    """Explicitly select EEVEE for a new realtime scene and set tone mapping.

    Existing scene assets, lighting, compositor, exposure, gamma and frame rate
    are untouched. Applying a quality profile alone never selects an engine.
    """
    # Blender 3.6 also exposes an experimental Next engine in some builds.
    # Prefer stable legacy EEVEE there; the tracing API identifies mature Next.
    next_available = hasattr(getattr(scene, "eevee", None), "use_raytracing")
    engines = ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE") if next_available else ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT")
    for engine in engines:
        try:
            scene.render.engine = engine
        except (TypeError, ValueError):
            continue
        result = {"applied": {}, "unsupported": []}
        _tone_mapping(scene, result)
        return engine
    raise RuntimeError("This Blender build does not provide an EEVEE renderer")


def apply_profile(scene, profile):
    """Apply the supported visual settings of a BlendEngine quality profile.

    Returns the actual property writes and unavailable features for diagnostics.
    This does not create light probes or volumes, bake indirect light, modify
    materials, replace compositor nodes, or promise a target frame rate.
    """
    result = {
        "engine": scene.render.engine,
        "applied": {},
        "unsupported": [],
        "skipped": scene.render.engine not in EEVEE_ENGINES,
    }
    if result["skipped"]:
        return result

    eevee = getattr(scene, "eevee", None)
    if eevee is None:
        result["unsupported"].append("EEVEE scene settings")
        return result

    def setting(name, value):
        return _set(eevee, name, value, "eevee", result)

    _set(scene.render, "resolution_percentage", round(profile.resolution_scale * 100), "render", result)
    viewport_samples, render_samples = _SAMPLES[profile.anti_aliasing]
    setting("taa_samples", viewport_samples)
    setting("taa_render_samples", render_samples)
    setting("use_taa_reprojection", profile.anti_aliasing != "OFF")
    if profile.anti_aliasing == "FXAA":
        result["unsupported"].append("FXAA; using low-cost EEVEE temporal sampling")

    shadow_quality = profile.shadow_quality
    map_size, pool_size, shadow_rays, shadow_steps, shadow_scale = _SHADOWS[shadow_quality]
    setting("use_shadows", shadow_quality != "OFF")
    if result["engine"] == "BLENDER_EEVEE" and shadow_quality == "OFF":
        # The legacy renderer does not consume the scene-wide switch exposed
        # for experimental Next in 3.6. Keep authored per-light flags intact.
        result["unsupported"].append("Legacy EEVEE global shadow switch; authored per-light shadows are preserved")
    setting("shadow_cube_size", map_size)
    setting("shadow_cascade_size", map_size)
    setting("shadow_pool_size", pool_size)
    setting("use_soft_shadows", shadow_quality in {"MEDIUM", "HIGH", "ULTRA"})
    setting("use_shadow_high_bitdepth", shadow_quality in {"HIGH", "ULTRA"})
    setting("use_shadow_jitter_viewport", shadow_quality in {"HIGH", "ULTRA"})
    setting("shadow_ray_count", shadow_rays)
    setting("shadow_step_count", shadow_steps)
    setting("shadow_resolution_scale", shadow_scale)

    setting("use_gtao", profile.ambient_occlusion)
    setting("gtao_distance", 3.0)
    setting("gtao_factor", 1.15)
    setting("use_gtao_bent_normals", profile.ambient_occlusion)
    setting("use_gtao_bounce", profile.ambient_occlusion)

    reflect = profile.reflections and profile.reflection_quality != "OFF"
    trace_resolution, precision, roughness = _REFLECTIONS[profile.reflection_quality]
    if hasattr(eevee, "use_raytracing"):
        # Next's fast GI and screen tracing share a single module switch.
        setting("use_raytracing", reflect or profile.ambient_occlusion)
        setting("ray_tracing_method", "SCREEN")
        setting("fast_gi_method", "GLOBAL_ILLUMINATION" if reflect else "AMBIENT_OCCLUSION_ONLY")
        setting("fast_gi_resolution", trace_resolution)
        setting("fast_gi_ray_count", 4 if shadow_quality in {"HIGH", "ULTRA"} else 2)
        setting("fast_gi_step_count", 16 if shadow_quality == "ULTRA" else 8)
        setting("fast_gi_quality", precision)
        options = getattr(eevee, "ray_tracing_options", None)
        for name, value in (
            ("resolution_scale", trace_resolution),
            ("screen_trace_quality", precision),
            # A zero cutoff uses only fast GI; one disables fast GI entirely.
            ("trace_max_roughness", (roughness if profile.ambient_occlusion else 1.0) if reflect else 0.0),
            ("use_denoise", True),
            ("denoise_spatial", True),
            ("denoise_temporal", True),
            ("denoise_bilateral", True),
        ):
            _set(options, name, value, "eevee.ray_tracing_options", result)
    else:
        setting("use_ssr", reflect)
        setting("use_ssr_halfres", profile.reflection_quality in {"OFF", "LOW"})
        setting("ssr_quality", precision)
        setting("ssr_max_roughness", roughness)

    if not setting("use_bloom", profile.bloom):
        if profile.bloom:
            result["unsupported"].append("Built-in bloom; EEVEE Next needs an authored compositor effect")
    setting("bloom_intensity", 0.035)
    setting("bloom_radius", 4.0)
    setting("bloom_threshold", 1.2)

    # These tune volumes already present in the scene, without adding fog or
    # deleting authored volume materials when a cheaper profile is selected.
    volume_samples, volume_tile = _VOLUMES[profile.post_processing_quality]
    setting("volumetric_samples", volume_samples)
    setting("volumetric_tile_size", volume_tile)
    setting("use_volumetric_lights", profile.volumetrics)
    setting("use_volumetric_shadows", profile.volumetrics and shadow_quality in {"HIGH", "ULTRA"})

    setting("use_motion_blur", profile.motion_blur)
    _set(scene.render, "use_motion_blur", profile.motion_blur, "render", result)
    _tone_mapping(scene, result)
    return result
