# SPDX-License-Identifier: GPL-2.0-or-later
#
# Approximate scene performance analysis for BlendEngine.
# These editor-side estimates are stored in reports and build packages.

import bpy


def _mesh_triangle_count(mesh):
    if mesh is None:
        return 0
    return sum(max(1, len(poly.vertices) - 2) for poly in mesh.polygons)


def _object_material_count(obj):
    if obj.type != "MESH" or obj.data is None:
        return 0
    return max(1, len(obj.data.materials))


def _image_memory_mb(image):
    size = getattr(image, "size", None)
    if not size or len(size) < 2:
        return 0.0
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height * 4) / (1024.0 * 1024.0)


def _particle_count(obj):
    total = 0
    systems = getattr(obj, "particle_systems", None)
    if not systems:
        return 0
    for system in systems:
        settings = getattr(system, "settings", None)
        total += int(getattr(settings, "count", 0) or 0)
    return total


def _uses_shadow(light_obj):
    data = getattr(light_obj, "data", None)
    if data is None:
        return False
    return bool(getattr(data, "use_shadow", True))


def _is_dynamic_light(light_obj):
    settings = getattr(light_obj, "blendengine_object", None)
    if settings is None:
        return True
    opt = settings.optimization
    return not opt.baked_lighting_candidate


def _has_lod_strategy(obj):
    settings = getattr(obj, "blendengine_object", None)
    if settings is None:
        return False
    return settings.optimization.lod_group


def estimate_scene(scene):
    metrics = {
        "object_count": len(scene.objects),
        "mesh_count": 0,
        "camera_count": 0,
        "triangle_count": 0,
        "draw_calls_estimated": 0,
        "material_count": 0,
        "light_count": 0,
        "dynamic_light_count": 0,
        "shadow_caster_count": 0,
        "rigidbody_count": 0,
        "particle_system_count": 0,
        "particle_count_estimated": 0,
        "bone_count_visible": 0,
        "texture_count": len(bpy.data.images),
        "texture_memory_mb": 0.0,
        "objects_without_lod": 0,
        "dynamic_object_count": 0,
        "static_rigidbody_count": 0,
        "high_poly_objects": 0,
        "max_texture_size": 0,
        "unique_material_names": set(),
    }

    high_poly_threshold = 50000
    for obj in scene.objects:
        if obj.type == "MESH" and obj.data is not None:
            metrics["mesh_count"] += 1
            triangles = _mesh_triangle_count(obj.data)
            metrics["triangle_count"] += triangles
            metrics["draw_calls_estimated"] += _object_material_count(obj)
            if triangles >= high_poly_threshold:
                metrics["high_poly_objects"] += 1
            if triangles >= 10000 and not _has_lod_strategy(obj):
                metrics["objects_without_lod"] += 1
            for material in obj.data.materials:
                if material:
                    metrics["unique_material_names"].add(material.name)

        if obj.type == "LIGHT":
            metrics["light_count"] += 1
            if _is_dynamic_light(obj):
                metrics["dynamic_light_count"] += 1
            if _uses_shadow(obj):
                metrics["shadow_caster_count"] += 1

        if obj.type == "CAMERA":
            metrics["camera_count"] += 1

        rigid_body = getattr(obj, "rigid_body", None)
        if rigid_body is not None:
            metrics["rigidbody_count"] += 1
            settings = getattr(obj, "blendengine_object", None)
            if (
                settings is not None and
                settings.optimization.static_object and
                getattr(rigid_body, "type", "") == "ACTIVE"
            ):
                metrics["static_rigidbody_count"] += 1

        systems = getattr(obj, "particle_systems", None)
        if systems:
            metrics["particle_system_count"] += len(systems)
            metrics["particle_count_estimated"] += _particle_count(obj)

        if obj.type == "ARMATURE" and getattr(obj, "visible_get", lambda: True)():
            bones = getattr(getattr(obj, "data", None), "bones", [])
            metrics["bone_count_visible"] += len(bones)

        settings = getattr(obj, "blendengine_object", None)
        if settings is not None and settings.optimization.dynamic_object:
            metrics["dynamic_object_count"] += 1

    metrics["material_count"] = len(metrics["unique_material_names"])
    if metrics["material_count"] == 0:
        metrics["material_count"] = sum(_object_material_count(obj) for obj in scene.objects if obj.type == "MESH")

    for image in bpy.data.images:
        metrics["texture_memory_mb"] += _image_memory_mb(image)
        size = getattr(image, "size", None)
        if size and len(size) >= 2:
            metrics["max_texture_size"] = max(metrics["max_texture_size"], int(size[0]), int(size[1]))

    # One mesh with several material slots often costs more than one draw in real engines.
    metrics["draw_calls_estimated"] = max(metrics["draw_calls_estimated"], metrics["mesh_count"])
    return metrics


def _add(messages, severity, message, suggested_fix=""):
    messages.append({"severity": severity, "message": message, "suggested_fix": suggested_fix})


def _budget_check(messages, label, value, budget_value, warning_ratio, warning_message, fix):
    if budget_value <= 0:
        return
    if value > budget_value:
        _add(messages, "CRITICAL", warning_message % (value, budget_value), fix)
    elif value > budget_value * warning_ratio:
        _add(messages, "WARNING", warning_message % (value, budget_value), fix)


def analyze_scene(scene, store_report=True):
    metrics = estimate_scene(scene)
    profile = scene.blendengine_quality_profile
    budget = scene.blendengine_performance_budget
    optimization = scene.blendengine_optimization
    messages = []

    _budget_check(
        messages,
        "triangles",
        metrics["triangle_count"],
        budget.max_triangles_visible,
        0.8,
        "The scene has about %d visible triangles. The selected budget is %d.",
        "Use LODs, simpler meshes, or hide distant detail to keep the game lighter.",
    )
    _budget_check(
        messages,
        "draw calls",
        metrics["draw_calls_estimated"],
        budget.max_draw_calls_estimated,
        0.8,
        "Too many separate objects/materials may make the game slower. Estimated draw calls: %d. Budget: %d.",
        "Try merging static objects, using shared materials, texture atlases, or instancing candidates.",
    )
    _budget_check(
        messages,
        "texture memory",
        int(metrics["texture_memory_mb"]),
        budget.max_texture_memory_mb,
        0.8,
        "Textures may use about %d MB of memory. The selected budget is %d MB.",
        "Compress or downsize large textures, and reuse shared texture atlases where possible.",
    )
    _budget_check(
        messages,
        "dynamic lights",
        metrics["dynamic_light_count"],
        budget.max_dynamic_lights,
        0.75,
        "There are %d dynamic lights. The selected budget is %d.",
        "Bake lighting where possible and keep only important gameplay lights dynamic.",
    )
    _budget_check(
        messages,
        "shadow casters",
        metrics["shadow_caster_count"],
        budget.max_shadow_casters,
        0.75,
        "There are %d real-time shadow-casting lights. The selected budget is %d.",
        "Disable shadows on small lights or use baked lighting for static scenes.",
    )
    _budget_check(
        messages,
        "rigidbodies",
        metrics["rigidbody_count"],
        budget.max_rigidbodies,
        0.8,
        "There are %d rigidbodies. The selected budget is %d.",
        "Use rigidbodies only where gameplay needs them, simplify colliders, and enable physics sleep.",
    )
    _budget_check(
        messages,
        "particles",
        metrics["particle_count_estimated"],
        budget.max_particles,
        0.8,
        "Particle systems may spawn about %d particles. The selected budget is %d.",
        "Reduce particle counts, shorten lifetimes, or use lower particle quality on weak computers.",
    )
    _budget_check(
        messages,
        "bones",
        metrics["bone_count_visible"],
        budget.max_bones_visible,
        0.8,
        "Visible characters may use about %d bones. The selected budget is %d.",
        "Use animation culling for far NPCs and simpler rigs for background characters.",
    )

    if metrics["high_poly_objects"] > 0:
        _add(
            messages,
            "WARNING",
            "%d objects are very high-poly for a lightweight game." % metrics["high_poly_objects"],
            "Add LOD groups, reduce mesh detail, or use impostors for distant views.",
        )

    if not optimization.use_lod_strategy and metrics["mesh_count"] > 0:
        _add(
            messages,
            "WARNING",
            "No LOD strategy is configured for this scene yet.",
            "Enable Use LOD Strategy and add LOD markers to complex objects.",
        )
    elif metrics["objects_without_lod"] > 0:
        _add(
            messages,
            "WARNING",
            "%d complex objects do not have an LOD strategy yet." % metrics["objects_without_lod"],
            "Use Auto Generate LOD placeholders, then replace placeholders with lower-detail meshes later.",
        )

    if metrics["static_rigidbody_count"] > 0:
        _add(
            messages,
            "WARNING",
            "%d static objects still have rigidbody physics enabled." % metrics["static_rigidbody_count"],
            "Static scenery usually only needs simple colliders or passive physics, not active rigidbodies.",
        )

    max_texture_limit = 2048 if profile.preset in {"ULTRA_LOW", "LOW"} else 4096
    if metrics["max_texture_size"] > max_texture_limit:
        _add(
            messages,
            "WARNING",
            "Some textures are larger than %d px, which may be heavy for the selected preset." % max_texture_limit,
            "Downsize or compress large textures, especially for mobile-style or weak-computer targets.",
        )

    if profile.volumetrics and profile.preset in {"ULTRA_LOW", "LOW"}:
        _add(
            messages,
            "CRITICAL",
            "Volumetric effects are enabled on a low performance preset.",
            "Turn off volumetrics or switch to a higher preset only for strong computers.",
        )

    if profile.preset == "CINEMATIC" and optimization.weak_hardware_target:
        _add(
            messages,
            "WARNING",
            "Cinematic settings are selected while Weak Hardware Target is enabled.",
            "Use Balanced or Low for weak computers, and keep Cinematic for screenshots or strong machines.",
        )

    if metrics["mesh_count"] > 0 and metrics["material_count"] > metrics["mesh_count"] * 1.5:
        _add(
            messages,
            "WARNING",
            "The scene uses many unique materials, which may increase draw calls.",
            "Share materials between similar objects and plan texture atlases for static props.",
        )

    if metrics["dynamic_object_count"] > 50:
        _add(
            messages,
            "WARNING",
            "Many objects are marked dynamic, which reduces future batching and culling opportunities.",
            "Mark objects Static if they do not move during gameplay.",
        )

    if not messages:
        _add(
            messages,
            "GOOD",
            "Performance estimates look healthy for the selected budget.",
            "Keep using LODs, baked lighting, shared materials, and simple colliders as the scene grows.",
        )

    status = "GOOD"
    if any(item["severity"] == "CRITICAL" for item in messages):
        status = "CRITICAL"
    elif any(item["severity"] == "WARNING" for item in messages):
        status = "WARNING"

    report = {"metrics": metrics, "messages": messages, "status": status, "summary": _summary(status, messages)}
    if store_report:
        write_report(scene, report)
    return report


def _summary(status, messages):
    if status == "GOOD":
        return "Good: estimates are inside the selected budget."
    if status == "CRITICAL":
        count = sum(1 for item in messages if item["severity"] == "CRITICAL")
        return "Critical: %d performance issue(s) should be fixed before testing on weak computers." % count
    count = sum(1 for item in messages if item["severity"] == "WARNING")
    return "Warning: %d performance issue(s) may slow weak computers." % count


def write_report(scene, result):
    report = scene.blendengine_performance_report
    metrics = result["metrics"]
    report.status = result["status"]
    report.summary = result["summary"]
    report.object_count = metrics["object_count"]
    report.mesh_count = metrics["mesh_count"]
    report.camera_count = metrics["camera_count"]
    report.triangle_count = metrics["triangle_count"]
    report.draw_calls_estimated = metrics["draw_calls_estimated"]
    report.material_count = metrics["material_count"]
    report.light_count = metrics["light_count"]
    report.dynamic_light_count = metrics["dynamic_light_count"]
    report.shadow_caster_count = metrics["shadow_caster_count"]
    report.rigidbody_count = metrics["rigidbody_count"]
    report.particle_system_count = metrics["particle_system_count"]
    report.particle_count_estimated = metrics["particle_count_estimated"]
    report.bone_count_visible = metrics["bone_count_visible"]
    report.texture_count = metrics["texture_count"]
    report.texture_memory_mb = metrics["texture_memory_mb"]
    report.objects_without_lod = metrics["objects_without_lod"]
    report.dynamic_object_count = metrics["dynamic_object_count"]

    while len(report.messages) > 0:
        report.messages.remove(0)
    for item in result["messages"]:
        message = report.messages.add()
        message.severity = item["severity"]
        message.message = item["message"]
        message.suggested_fix = item.get("suggested_fix", "")
    report.active_message_index = 0
    scene.blendengine_optimization.last_report_summary = result["summary"]


def report_as_text(scene):
    result = analyze_scene(scene, store_report=True)
    metrics = result["metrics"]
    lines = [
        "BlendEngine Optimization Report",
        "Editor-side estimates and runtime/build optimization markers.",
        "",
        result["summary"],
        "",
        "Estimates:",
        "- Objects: %d" % metrics["object_count"],
        "- Mesh objects: %d" % metrics["mesh_count"],
        "- Triangles: %d" % metrics["triangle_count"],
        "- Draw calls: %d" % metrics["draw_calls_estimated"],
        "- Unique materials: %d" % metrics["material_count"],
        "- Lights: %d dynamic / %d total" % (metrics["dynamic_light_count"], metrics["light_count"]),
        "- Real-time shadow casters: %d" % metrics["shadow_caster_count"],
        "- Rigidbodies: %d" % metrics["rigidbody_count"],
        "- Particles: %d" % metrics["particle_count_estimated"],
        "- Texture memory: %.1f MB" % metrics["texture_memory_mb"],
        "",
        "Messages:",
    ]
    for item in result["messages"]:
        lines.append("- %s: %s" % (item["severity"].title().replace("_", " "), item["message"]))
        if item.get("suggested_fix"):
            lines.append("  Suggested Fix: %s" % item["suggested_fix"])
    return "\n".join(lines)


def register():
    pass


def unregister():
    pass
