# SPDX-License-Identifier: GPL-2.0-or-later
#
# Per-frame optimization during a Test Run / exported desktop game.
#
# SceneCuller decides which objects the renderer receives:
#   - frustum: the object's bounding sphere is outside the camera pyramid,
#   - occlusion: the baked visible set of the camera's cell does not contain it,
#   - distance: the existing streaming radius and visible-object cap,
# and swaps in the LOD meshes built by the Smart Optimizer.
#
# QualityGovernor watches the measured frame time and trades effect resolution
# for speed only while the target frame rate is missed, then gives it back.
#
# Both record what they change and put it back when the session stops.

import json
import math

from mathutils import Vector

from . import smart_optimizer, utils


_SKIP_TAGS = {"Weapon", "FirstPersonArms"}


class SceneCuller:
    def __init__(self, scene):
        self.scene = scene
        self.items = []
        self.hidden = {}
        self.lods = {}
        self.pvs = None
        self.pvs_index = {}
        self.stats = {"hidden": 0, "occluded": 0, "lod_swaps": 0}
        # EEVEE Next honours camera ray visibility, which keeps shadows of culled objects.
        eevee = getattr(scene, "eevee", None)
        self.soft = hasattr(eevee, "use_raytracing") and scene.render.engine in {"BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"}

        raw = scene.get(smart_optimizer.PVS)
        if raw:
            try:
                self.pvs = json.loads(raw)
                self.pvs["sets"] = {key: frozenset(value) for key, value in self.pvs["cells"].items()}
                self.pvs_index = {name: index for index, name in enumerate(self.pvs["objects"])}
            except (ValueError, KeyError, TypeError):
                self.pvs = None

        player = utils.find_player_object(scene)
        for obj in scene.objects:
            if obj.type in {"CAMERA", "EMPTY", "LIGHT", "LIGHT_PROBE", "ARMATURE"} or obj == player:
                continue
            settings = obj.blendengine_object
            if settings.object_tag in _SKIP_TAGS or obj.get(smart_optimizer.CULLED):
                continue
            if settings.optimization.dynamic_object and settings.player_controller.enabled:
                continue
            if self._is_hidden(obj):
                continue  # Hidden on purpose (first-person body, editor helpers): never reveal it.
            corners = [Vector(corner) for corner in obj.bound_box]
            center = sum(corners, Vector()) / 8.0
            radius = max((corner - center).length for corner in corners)
            self.items.append((obj, center, radius, self.pvs_index.get(obj.name, -1)))
            self.hidden[obj.name] = (self._is_hidden(obj), getattr(obj, "visible_camera", True))
            names = obj.get(smart_optimizer.LOD_MESHES)
            distances = obj.get(smart_optimizer.LOD_DISTANCES)
            if names and distances and obj.type == "MESH":
                self.lods[obj.name] = (list(names), list(distances))

    @staticmethod
    def _is_hidden(obj):
        try:
            return obj.hide_get()
        except RuntimeError:
            return obj.hide_viewport

    @staticmethod
    def _set_hidden(obj, hidden):
        try:
            if obj.hide_get() != hidden:
                obj.hide_set(hidden)
        except RuntimeError:
            obj.hide_viewport = hidden

    def _visible_set(self, position):
        """Static objects in sight of the camera's cell and its neighbours, or None if unknown."""
        if self.pvs is None:
            return None
        origin, step, sets = self.pvs["origin"], self.pvs["step"], self.pvs["sets"]
        i = int(math.floor((position.x - origin[0]) / step[0]))
        j = int(math.floor((position.y - origin[1]) / step[1]))
        if "%d,%d" % (i, j) not in sets:
            return None  # The camera left the analysed area: cull nothing by occlusion.
        visible = set()
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                visible |= sets.get("%d,%d" % (i + di, j + dj), frozenset())
        return visible

    def update(self, camera, optimization):
        scene = self.scene
        matrix = camera.matrix_world
        position = matrix.translation
        inverse = matrix.inverted_safe()
        data = camera.data if camera.type == "CAMERA" else None
        # Hiding outright also removes the object's shadow, so without camera-only
        # visibility the stricter, explicitly chosen switch decides.
        frustum = optimization.hide_behind_camera or (self.soft and optimization.use_frustum_culling)
        tan_x = tan_y = 0.0
        if data is not None and data.type != "ORTHO":
            aspect = scene.render.resolution_x / max(1.0, float(scene.render.resolution_y))
            half = math.tan(data.angle * 0.5)
            tan_x, tan_y = (half, half / aspect) if aspect >= 1.0 else (half * aspect, half)
        else:
            frustum = False
        # Plane normals of the pyramid sides, to measure sphere distances exactly.
        norm_x, norm_y = math.hypot(1.0, tan_x), math.hypot(1.0, tan_y)
        max_distance = max(optimization.world_cell_size * (optimization.visible_cell_radius + 1), 24.0)
        visible_set = self._visible_set(position) if optimization.use_occlusion_culling else None
        visible_count = hidden_count = occluded_count = 0

        for obj, local_center, local_radius, pvs_slot in self.items:
            world = obj.matrix_world
            center = world @ local_center
            radius = local_radius * max(abs(value) for value in world.to_scale())
            distance = (center - position).length
            off_screen = False
            if frustum:
                local = inverse @ center
                depth = -local.z
                off_screen = (depth < -radius
                              or (abs(local.x) - depth * tan_x) / norm_x > radius
                              or (abs(local.y) - depth * tan_y) / norm_y > radius)
            occluded = visible_set is not None and pvs_slot >= 0 and pvs_slot not in visible_set
            streamed_out = optimization.camera_frustum_generation and distance - radius > max_distance
            disable_far = obj.blendengine_object.optimization.disable_when_far
            if visible_count >= optimization.max_visible_objects and disable_far:
                streamed_out = True

            if self.soft:
                # Out of the camera's sight but still in the scene, so its shadow stays.
                unseen = off_screen or occluded
                if obj.visible_camera == unseen:
                    obj.visible_camera = not unseen
                self._set_hidden(obj, streamed_out)
            else:
                self._set_hidden(obj, streamed_out or off_screen or occluded)
            if streamed_out or off_screen or occluded:
                hidden_count += 1
                occluded_count += int(occluded and not off_screen)
            else:
                visible_count += 1

            lod = self.lods.get(obj.name)
            if lod is not None and optimization.use_lod_strategy:
                names, distances = lod
                level = sum(1 for limit in distances if distance - radius > limit)
                if obj.data.name != names[level]:
                    import bpy
                    mesh = bpy.data.meshes.get(names[level])
                    if mesh is not None:
                        obj.data = mesh
                        self.stats["lod_swaps"] += 1
        self.stats["hidden"] = hidden_count
        self.stats["occluded"] = occluded_count
        return self.stats

    def restore(self):
        import bpy
        for obj, _center, _radius, _slot in self.items:
            try:
                hidden, camera_visible = self.hidden[obj.name]
                self._set_hidden(obj, hidden)
                if hasattr(obj, "visible_camera"):
                    obj.visible_camera = camera_visible
                lod = self.lods.get(obj.name)
                if lod is not None and obj.data.name != lod[0][0]:
                    mesh = bpy.data.meshes.get(lod[0][0])
                    if mesh is not None:
                        obj.data = mesh
            except ReferenceError:
                continue


def _coarser(options, value):
    """Next larger entry of an ordered enum such as resolution divisors."""
    try:
        index = options.index(value)
    except ValueError:
        return value
    return options[min(index + 1, len(options) - 1)]


class QualityGovernor:
    """Lower effect cost one notch at a time while frames are late; raise it when they are early."""

    LEVELS = 5

    def __init__(self, scene, target_fps, interval=30):
        self.scene = scene
        self.budget_ms = 1000.0 / max(1.0, float(target_fps))
        self.interval = interval
        self.level = 0
        self.average = None
        self.frames = 0
        self.calm = 0
        self.original = {}

    def _write(self, owner, name, value):
        if owner is None or not hasattr(owner, name):
            return
        key = (owner, name)
        if key not in self.original:
            self.original[key] = getattr(owner, name)
        try:
            setattr(owner, name, value)
        except (TypeError, ValueError):
            pass

    def _base(self, owner, name, default=None):
        if owner is None or not hasattr(owner, name):
            return default
        return self.original.get((owner, name), getattr(owner, name))

    def _apply(self):
        """Rewrite every governed setting from its original value for the current level."""
        for (owner, name), value in list(self.original.items()):
            try:
                setattr(owner, name, value)
            except (TypeError, ValueError, ReferenceError):
                pass
        eevee = getattr(self.scene, "eevee", None)
        tracing = getattr(eevee, "ray_tracing_options", None)
        level = self.level
        divisors = ["1", "2", "4", "8", "16"]
        if level >= 1:
            # Reflections and indirect light at a lower internal resolution.
            self._write(tracing, "resolution_scale", _coarser(divisors, self._base(tracing, "resolution_scale", "1")))
            self._write(eevee, "fast_gi_resolution", _coarser(divisors, self._base(eevee, "fast_gi_resolution", "1")))
            self._write(eevee, "use_ssr_halfres", True)
        if level >= 2:
            tiles = ["2", "4", "8", "16"]
            self._write(eevee, "volumetric_tile_size", _coarser(tiles, self._base(eevee, "volumetric_tile_size", "8")))
            self._write(eevee, "volumetric_samples", max(8, int(self._base(eevee, "volumetric_samples", 64)) // 2))
            self._write(eevee, "use_volumetric_shadows", False)
        if level >= 3:
            self._write(eevee, "shadow_ray_count", 1)
            self._write(eevee, "shadow_step_count", max(2, int(self._base(eevee, "shadow_step_count", 6)) // 2))
            self._write(eevee, "use_soft_shadows", False)
        if level >= 4:
            self._write(eevee, "fast_gi_method", "AMBIENT_OCCLUSION_ONLY")
            self._write(eevee, "use_gtao", False)
            self._write(eevee, "use_bloom", False)
            self._write(eevee, "use_motion_blur", False)
        if level >= 5:
            # Last resort: draw the viewport with 2x2 pixels where the renderer supports it.
            self._write(self.scene.render, "preview_pixel_size", "2")
            self._write(eevee, "use_raytracing", False)
            self._write(eevee, "use_ssr", False)

    def update(self, frame_ms, emergency=True):
        """Feed one frame time. Returns the new level when it changed, else None."""
        self.average = frame_ms if self.average is None else self.average * 0.9 + frame_ms * 0.1
        self.frames += 1
        if self.frames % self.interval:
            return None
        previous = self.level
        if self.average > self.budget_ms * 1.15:
            self.calm = 0
            jump = 2 if emergency and self.average > self.budget_ms * 2.0 else 1
            self.level = min(self.LEVELS, self.level + jump)
        elif self.average < self.budget_ms * 0.7 and self.level > 0:
            # Wait for sustained headroom so the picture does not flicker between levels.
            self.calm += 1
            if self.calm >= 3:
                self.calm = 0
                self.level -= 1
        else:
            self.calm = 0
        if self.level == previous:
            return None
        self._apply()
        return self.level

    def restore(self):
        self.level = 0
        self._apply()
        self.original.clear()
