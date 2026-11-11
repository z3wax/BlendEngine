# SPDX-License-Identifier: GPL-2.0-or-later
#
# Cinematic look for Blender's own realtime renderer (EEVEE).
#
# `graphics.apply_profile` chooses how much the renderer computes. This module
# adds what makes a frame read as film: a lens (depth of field focused on the
# subject), filmic shadows and highlights, bloom, a hint of lens dispersion and
# a vignette. It is an explicit, removable action because it edits the camera
# and adds compositor nodes, which a quality preset must never do on its own.

from . import graphics, utils


NODE_TAG = "be_cinematic"


def _set(target, name, value, path, result):
    if target is None or not hasattr(target, name):
        return False
    try:
        setattr(target, name, value)
    except (TypeError, ValueError, AttributeError):
        return False
    result["applied"][path + "." + name] = value
    return True


def _renderer(scene, result):
    eevee = getattr(scene, "eevee", None)
    for name, value in (
        # Draw a border beyond the frame so screen-space effects do not fade at its edges.
        ("use_overscan", True),
        ("overscan_size", 6.0),
        # Let dim light contributions reach further before they are cut off.
        ("light_threshold", 0.005),
        ("use_soft_shadows", True),
        ("use_shadow_high_bitdepth", True),
        ("use_ssr_refraction", True),
        ("use_gtao_bent_normals", True),
        ("gi_diffuse_bounces", 3),
        # Accurate, jittered depth of field instead of the fast post-process blur.
        ("use_bokeh_jittered", True),
        ("use_bokeh_high_quality_slight_defocus", True),
        ("bokeh_overblur", 5.0),
        ("bokeh_max_size", 100.0),
        ("motion_blur_shutter", 0.5),
        ("motion_blur_steps", 4),
        ("volumetric_shadow_samples", 16),
        # Tame single-pixel sparkles from very bright reflections.
        ("clamp_surface_indirect", 10.0),
    ):
        _set(eevee, name, value, "eevee", result)
    _set(scene.render, "use_high_quality_normals", True, "render", result)
    _set(scene.render, "filter_size", 1.5, "render", result)
    _set(scene.render, "motion_blur_shutter", 0.5, "render", result)
    graphics._tone_mapping(scene, result)


def _lights(scene, result):
    count = 0
    for obj in scene.objects:
        if obj.type != "LIGHT" or not getattr(obj.data, "use_shadow", False):
            continue
        light = obj.data
        for name, value in (("use_contact_shadow", True), ("use_shadow_jitter", True),
                            ("shadow_jitter_overblur", 10.0)):
            if hasattr(light, name):
                setattr(light, name, value)
        count += 1
    result["applied"]["lights.soft_shadow_filtering"] = count


def focus_subject(scene):
    """What the lens should hold sharp: the player, when the camera looks at them from outside.

    A first-person camera sits inside the player, so focusing on the player
    would blur the whole world; there the authored focus distance is kept.
    """
    player = utils.find_player_object(scene)
    camera = scene.camera
    if player is None or camera is None:
        return None
    if player.blendengine_object.player_controller.controller_type == "FIRST_PERSON":
        return None
    reach = max(player.dimensions) if any(player.dimensions) else 1.0
    if (player.matrix_world.translation - camera.matrix_world.translation).length <= reach:
        return None
    return player


def _lens(scene, fstop, subject, result):
    camera = scene.camera
    if camera is None or camera.type != "CAMERA":
        result["unsupported"].append("Depth of field: the scene has no camera")
        return
    data = camera.data
    if data.type == "ORTHO":
        result["unsupported"].append("Depth of field: orthographic cameras have no lens blur")
        return
    dof = data.dof
    dof.use_dof = True
    dof.aperture_fstop = fstop
    dof.aperture_blades = 0
    if subject is not None and subject != camera:
        dof.focus_object = subject
        result["applied"]["camera.dof.focus_object"] = subject.name
    else:
        # Keep the authored focus object or distance; it is the artist's decision.
        result["applied"]["camera.dof.focus_distance"] = dof.focus_distance
    result["applied"]["camera.dof.aperture_fstop"] = fstop


def _compositor_tree(scene):
    """Classic scene compositor tree (Blender 3.6 - 4.x), created when missing."""
    if not hasattr(scene, "node_tree"):
        return None
    if scene.node_tree is None:
        scene.use_nodes = True
    return scene.node_tree


def _is_untouched(tree):
    """Only the default Render Layers -> Composite graph may be extended."""
    types = sorted(node.bl_idname for node in tree.nodes if not node.get(NODE_TAG))
    return types in (["CompositorNodeComposite", "CompositorNodeRLayers"], [])


def remove_post(scene):
    """Remove the nodes added by `apply_look` and reconnect the plain render."""
    tree = getattr(scene, "node_tree", None)
    if tree is None:
        return 0
    tagged = [node for node in tree.nodes if node.get(NODE_TAG)]
    for node in tagged:
        tree.nodes.remove(node)
    layers = next((node for node in tree.nodes if node.bl_idname == "CompositorNodeRLayers"), None)
    output = next((node for node in tree.nodes if node.bl_idname == "CompositorNodeComposite"), None)
    if tagged and layers is not None and output is not None and not output.inputs["Image"].is_linked:
        tree.links.new(layers.outputs["Image"], output.inputs["Image"])
    return len(tagged)


def _post(scene, bloom, vignette, dispersion, result):
    tree = _compositor_tree(scene)
    if tree is None:
        result["unsupported"].append("Compositor post effects: this Blender version uses a different compositor API")
        return
    remove_post(scene)
    if not _is_untouched(tree):
        result["unsupported"].append("Compositor post effects: the authored compositor graph is kept as it is")
        return
    scene.use_nodes = True
    nodes, links = tree.nodes, tree.links
    layers = next((node for node in nodes if node.bl_idname == "CompositorNodeRLayers"), None)
    output = next((node for node in nodes if node.bl_idname == "CompositorNodeComposite"), None)
    if layers is None:
        layers = nodes.new("CompositorNodeRLayers")
    if output is None:
        output = nodes.new("CompositorNodeComposite")
    image = layers.outputs["Image"]

    def add(kind, x):
        node = nodes.new(kind)
        node[NODE_TAG] = 1
        node.location = (layers.location.x + x, layers.location.y)
        return node

    if bloom > 0.0:
        glare = add("CompositorNodeGlare", 300)
        for glare_type in ("BLOOM", "FOG_GLOW"):
            try:
                glare.glare_type = glare_type
                break
            except TypeError:
                continue
        glare.quality = "HIGH"
        glare.threshold = 1.0
        glare.mix = max(-1.0, min(0.0, -1.0 + bloom))
        glare.size = 8
        links.new(image, glare.inputs["Image"])
        image = glare.outputs["Image"]
        result["applied"]["compositor.bloom"] = bloom

    if dispersion > 0.0:
        lens = add("CompositorNodeLensdist", 520)
        lens.use_fit = True
        socket = lens.inputs.get("Dispersion")
        if socket is not None:
            socket.default_value = dispersion
            links.new(image, lens.inputs["Image"])
            image = lens.outputs["Image"]
            result["applied"]["compositor.dispersion"] = dispersion

    if vignette > 0.0:
        mask = add("CompositorNodeEllipseMask", 520)
        mask.location.y -= 260
        mask.width, mask.height = 0.92, 0.92
        blur = add("CompositorNodeBlur", 740)
        blur.location.y -= 260
        blur.filter_type = "FAST_GAUSS"
        blur.use_relative = True
        blur.factor_x = blur.factor_y = 22.0
        mix = add("CompositorNodeMixRGB", 960)
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = vignette
        links.new(mask.outputs["Mask"], blur.inputs["Image"])
        links.new(image, mix.inputs[1])
        links.new(blur.outputs["Image"], mix.inputs[2])
        image = mix.outputs["Image"]
        result["applied"]["compositor.vignette"] = vignette

    output.location = (layers.location.x + 1200, layers.location.y)
    links.new(image, output.inputs["Image"])


def show_post_in_viewport(context):
    """Run the compositor in rendered viewports so Test Run shows the same grade."""
    screen = getattr(context, "screen", None)
    count = 0
    for area in getattr(screen, "areas", ()):
        if area.type != "VIEW_3D":
            continue
        for space in area.spaces:
            shading = getattr(space, "shading", None)
            if shading is not None and hasattr(shading, "use_compositor"):
                shading.use_compositor = "ALWAYS"
                count += 1
    return count


def apply_look(scene, fstop=2.8, bloom=0.35, vignette=0.35, dispersion=0.012, depth_of_field=True, post=True):
    """Give an EEVEE scene a film look. Returns what was written and what was not available.

    Rendering cost: depth of field and the compositor pass are paid per frame;
    everything else only changes how already computed light is filtered.
    """
    result = {"engine": scene.render.engine, "applied": {}, "unsupported": [],
              "skipped": scene.render.engine not in graphics.EEVEE_ENGINES}
    if result["skipped"]:
        result["unsupported"].append("Cinematic look targets EEVEE; the current engine is left alone")
        return result
    _renderer(scene, result)
    _lights(scene, result)
    if depth_of_field:
        _lens(scene, fstop, focus_subject(scene), result)
    if post:
        _post(scene, bloom, vignette, dispersion, result)
    return result
