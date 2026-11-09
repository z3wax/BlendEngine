# SPDX-License-Identifier: GPL-2.0-or-later
#
# Runtime validation and editor play-session support.

import math
import time

from mathutils import Vector

from . import performance, utils


ACTIVE_SESSION = None
HUD_HANDLER = None


GAME_INPUT_EVENTS = {
    "W", "A", "S", "D", "Q", "E", "R", "F",
    "UP_ARROW", "DOWN_ARROW", "LEFT_ARROW", "RIGHT_ARROW",
    "SPACE", "LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_CTRL", "RIGHT_CTRL",
    "LEFTMOUSE", "RIGHTMOUSE",
}


class ValidationResult:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []

    @property
    def ok(self):
        return not self.errors

    def summary(self):
        if self.ok:
            if self.warnings:
                return "Ready with %d warning(s)" % len(self.warnings)
            return "Ready"
        return "Blocked by %d error(s)" % len(self.errors)

    def all_messages(self):
        messages = []
        messages.extend(("ERROR: " + item) for item in self.errors)
        messages.extend(("WARNING: " + item) for item in self.warnings)
        messages.extend(("INFO: " + item) for item in self.info)
        return messages


def _component_enabled(obj, component_type):
    component = utils.find_component(obj, component_type)
    return component is not None and component.enabled


def validate_scene(scene):
    result = ValidationResult()

    if scene is None:
        result.errors.append("No active scene is available.")
        return result

    project = utils.ensure_project_defaults(scene)
    if not project.game_title:
        result.warnings.append("Game title is empty.")

    if scene.camera is None:
        result.errors.append("Set a scene camera before Test Run.")

    player = utils.find_player_object(scene)
    if player is None:
        result.errors.append("Add a Player Controller to one object.")
    else:
        result.info.append("Player object: %s" % player.name)
        controller = player.blendengine_object.player_controller
        if controller.camera_follow is None and scene.camera is not None:
            result.warnings.append("Player Controller has no camera follow object; scene camera will be used.")
        if controller.walk_speed <= 0.0:
            result.warnings.append("Player walk speed is zero.")

    input_map = scene.blendengine_input_map
    if not input_map.bindings:
        result.errors.append("Create input bindings before Test Run.")
    else:
        action_names = {binding.action for binding in input_map.bindings}
        for action in ("MOVE_FORWARD", "MOVE_BACKWARD", "MOVE_LEFT", "MOVE_RIGHT", "JUMP"):
            if action not in action_names:
                result.warnings.append("Input action %s is not bound." % action.replace("_", " ").title())

    game_objects = 0
    behavior_count = 0
    for obj in scene.objects:
        settings = obj.blendengine_object
        if settings.is_game_object or settings.components:
            game_objects += 1
            behavior_count += len(settings.behaviors)
            if (_component_enabled(obj, "TRIGGER_ZONE") and obj.type == "MESH" and obj.display_type != "WIRE"
                    and not obj.get("blendengine_visible_trigger")):
                result.warnings.append("Trigger %s is visible; set Display As Wire if it should be hidden." % obj.name)
    if game_objects == 0:
        result.warnings.append("No BlendEngine game objects were found.")
    else:
        result.info.append("Game objects: %d" % game_objects)
    result.info.append("No-code behaviors: %d" % behavior_count)

    performance_result = performance.analyze_scene(scene, store_report=True)
    for item in performance_result["messages"]:
        if item["severity"] == "GOOD":
            result.info.append(item["message"])
        elif item["severity"] == "CRITICAL":
            result.warnings.append("Critical performance estimate: " + item["message"])
            if item.get("suggested_fix"):
                result.warnings.append("Suggested fix: " + item["suggested_fix"])
        else:
            result.warnings.append(item["message"])
            if item.get("suggested_fix"):
                result.warnings.append("Suggested fix: " + item["suggested_fix"])

    return result


def world_matrix(obj):
    """World matrix from the parent chain; ``matrix_world`` is not refreshed
    for objects that are hidden, which culling itself does."""
    matrix = obj.matrix_basis.copy()
    while obj.parent is not None:
        matrix = obj.matrix_parent_inverse @ matrix
        obj = obj.parent
        matrix = obj.matrix_basis @ matrix
    return matrix


def world_bounds_sphere(obj):
    """(center, radius) of the object's bounding box in world space."""
    world = world_matrix(obj)
    corners = [world @ Vector(corner) for corner in obj.bound_box]
    center = sum(corners, Vector()) / len(corners)
    return center, max((corner - center).length for corner in corners)


def yaw_towards(x, y):
    """Z rotation that turns an object's local +Y toward the direction (x, y).

    Blender rotates +Y to (-sin(yaw), cos(yaw)), so the angle is
    atan2(-x, y); atan2(x, y) mirrors the facing whenever x is not zero."""
    return math.atan2(-x, y)


def _world_bounds(scene):
    """Optional (min_x, min_y, max_x, max_y) play area stored on the scene."""
    bounds = scene.get("blendengine_world_bounds")
    try:
        values = tuple(float(value) for value in bounds)
    except (TypeError, ValueError):
        return None
    return values if len(values) == 4 else None


def _compare(left, operator, right):
    if operator == "EQUAL":
        return left == right
    if operator == "NOT_EQUAL":
        return left != right
    if operator == "LESS":
        return left < right
    if operator == "LESS_EQUAL":
        return left <= right
    if operator == "GREATER":
        return left > right
    if operator == "GREATER_EQUAL":
        return left >= right
    return False


def _variable_lookup(obj, variable_name):
    settings = obj.blendengine_object
    for variable in settings.variables:
        if variable.name == variable_name:
            return variable
    return None


def _variable_value(variable):
    if variable.variable_type == "BOOL":
        return variable.bool_value
    if variable.variable_type == "INT":
        return variable.int_value
    if variable.variable_type == "STRING":
        return variable.string_value
    return variable.float_value


def _set_variable_value(variable, value):
    if variable.variable_type == "BOOL":
        variable.bool_value = bool(value)
    elif variable.variable_type == "INT":
        variable.int_value = int(value)
    elif variable.variable_type == "STRING":
        variable.string_value = str(value)
    else:
        variable.float_value = float(value)


class GameSession:
    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.input_state = set()
        self.elapsed = 0.0
        self.frame = 0
        self.fps = 0.0
        self.frame_ms = 0.0
        self.logs = []
        self.stop_requested = False
        self._last_wall_time = time.perf_counter()
        self._metrics = {}
        self._vertical_velocity = {}
        self._ground_z = {}
        self._camera_offsets = {}
        self._patrol_origins = {}
        self._npc_attack_timers = {}
        self._attack_cooldown = 0.0
        self._muzzle_flash_until = 0.0
        self._last_hit_name = ""
        self._timer_state = {}
        self._trigger_overlaps = set()
        self._collision_overlaps = set()
        self.end_status = ""
        self._removed = set()
        self._spawned = []
        self._player = utils.find_player_object(self.scene)
        self._bounds = _world_bounds(self.scene)
        self._two_d = self.scene.blendengine_project.game_dimension == "TWO_D"
        self._snapshot = self._capture_state()

        for obj in self.scene.objects:
            self._ground_z[obj.name] = obj.location.z
            if obj.type == "CAMERA":
                player = utils.find_player_object(self.scene)
                if player is not None:
                    self._camera_offsets[obj.name] = obj.location - player.location

    def start(self):
        project = self.scene.blendengine_project
        project.test_running = True
        project.test_status = "Running"
        self._prepare_play_view()
        self._set_first_person_player_visibility(False)
        _add_hud_handler()
        self.log("Test Run started for %s." % project.game_title)
        self.execute_behaviors("ON_START", 0.0)
        self._update_runtime_metrics(force=True)
        self.flush_log()

    def stop(self, status="Stopped"):
        project = self.scene.blendengine_project
        project.test_running = False
        project.test_status = status
        self._restore_state()
        self._set_first_person_player_visibility(True)
        _remove_hud_handler()
        self.log("Test Run %s." % status.lower())
        self.flush_log()

    def _capture_state(self):
        """Remember what Play Mode changes so Stop returns the editor scene."""
        state = {}
        for obj in self.scene.objects:
            settings = obj.blendengine_object
            entry = {
                "location": obj.location.copy(),
                "rotation": obj.rotation_euler.copy(),
                "hide_viewport": obj.hide_viewport,
                "hide_render": obj.hide_render,
            }
            try:
                entry["hidden"] = obj.hide_get()
            except Exception:
                entry["hidden"] = None
            if settings.health.enabled:
                entry["health"] = settings.health.current_health
            if settings.variables:
                entry["variables"] = [(variable.name, _variable_value(variable)) for variable in settings.variables]
            state[obj.name] = entry
        return state

    def _restore_state(self):
        import bpy
        for duplicate in self._spawned:
            try:
                bpy.data.objects.remove(duplicate, do_unlink=True)
            except Exception:
                pass
        self._spawned = []
        for name, entry in self._snapshot.items():
            obj = self.scene.objects.get(name)
            if obj is None:
                continue
            obj.location = entry["location"]
            obj.rotation_euler = entry["rotation"]
            obj.hide_viewport = entry["hide_viewport"]
            obj.hide_render = entry["hide_render"]
            if entry["hidden"] is not None:
                try:
                    obj.hide_set(entry["hidden"])
                except Exception:
                    pass
            if "health" in entry:
                obj.blendengine_object.health.current_health = entry["health"]
            for variable_name, value in entry.get("variables", ()):
                variable = _variable_lookup(obj, variable_name)
                if variable is not None:
                    _set_variable_value(variable, value)

    def _remove_from_play(self, obj):
        """Hide a collected pickup or defeated enemy for the rest of the run."""
        self._removed.add(obj.name)
        obj.hide_viewport = True
        obj.hide_render = True
        try:
            obj.hide_set(True)
        except Exception:
            pass

    def finish_with(self, status, message=""):
        if message:
            self.log(message)
        if not self.end_status:
            self.end_status = status
        self.stop_requested = True

    def lookup_variable(self, owner, variable_name):
        """Owner's variable, falling back to the player's (score, inventory)."""
        variable = _variable_lookup(owner, variable_name)
        if variable is None and self._player is not None and self._player != owner:
            variable = _variable_lookup(self._player, variable_name)
        return variable

    def _prepare_play_view(self):
        def _apply():
            context = self.context
            if context.window:
                workspace = getattr(context.window, "workspace", None)
                if workspace is not None and workspace.name != "Play Mode":
                    utils.activate_engine_page(context, "PLAY")
            utils.configure_current_screen_for_blendengine(context)
            utils.enter_camera_view(context)
            return None

        try:
            _apply()
            import bpy
            bpy.app.timers.register(_apply, first_interval=0.15)
        except Exception:
            pass

    def _set_first_person_player_visibility(self, visible):
        player = utils.find_player_object(self.scene)
        if player is None:
            return
        controller = player.blendengine_object.player_controller
        if controller.controller_type != "FIRST_PERSON":
            return
        for obj in self.scene.objects:
            tag = obj.blendengine_object.object_tag
            if obj == player or tag == "PlayerBody":
                try:
                    obj.hide_set(not visible)
                except Exception:
                    obj.hide_viewport = not visible

    def log(self, message):
        line = "[%06.2f] %s" % (self.elapsed, message)
        self.logs.append(line)
        print("[BlendEngine] " + line)

    def flush_log(self):
        if not self.scene.blendengine_project.show_logs:
            return
        import bpy

        datablock = bpy.data.texts.get("BlendEngine Runtime Log")
        if datablock is None:
            datablock = bpy.data.texts.new("BlendEngine Runtime Log")
        datablock.clear()
        datablock.write("\n".join(self.logs[-300:]))

    def handle_event(self, event):
        if event.type not in GAME_INPUT_EVENTS:
            return False
        if event.value == "PRESS":
            self.input_state.add(event.type)
            if event.type in {"F", "LEFTMOUSE"}:
                self._shoot_weapon()
            self.execute_behaviors("ON_KEY_PRESS", 0.0, key=event.type)
            return True
        elif event.value == "RELEASE" and event.type in self.input_state:
            self.input_state.remove(event.type)
            return True
        return event.type in GAME_INPUT_EVENTS

    def step(self, dt):
        now = time.perf_counter()
        real_dt = max(now - self._last_wall_time, 1.0 / 240.0)
        self._last_wall_time = now
        self.fps = 1.0 / real_dt
        self.frame_ms = real_dt * 1000.0
        self._attack_cooldown = max(0.0, self._attack_cooldown - dt)
        self.elapsed += dt
        self.frame += 1
        self._player = utils.find_player_object(self.scene)
        self._update_player(dt)
        self._update_npcs(dt)
        self.execute_behaviors("ON_UPDATE", dt)
        self.execute_behaviors("ON_TIMER", dt)
        self._update_collisions(dt)
        self._update_triggers(dt)
        self._update_camera()
        if self.frame % 5 == 0:
            self._update_visibility_culling()
        if self.frame % 10 == 0:
            self._update_runtime_metrics()
        if self.frame % 15 == 0:
            self.flush_log()

    def _update_runtime_metrics(self, force=False):
        project = self.scene.blendengine_project
        metrics = performance.estimate_scene(self.scene)
        visible_objects = 0
        visible_triangles = 0
        for obj in self.scene.objects:
            hidden = False
            try:
                hidden = obj.hide_get()
            except Exception:
                hidden = obj.hide_viewport
            if hidden:
                continue
            visible_objects += 1
            if obj.type == "MESH" and obj.data is not None:
                visible_triangles += sum(max(1, len(poly.vertices) - 2) for poly in obj.data.polygons)

        target_fps = getattr(self.scene.blendengine_performance_budget, "target_fps", 60)
        project.runtime_fps = self.fps if not force else max(self.fps, float(target_fps))
        project.runtime_frame_ms = self.frame_ms
        project.runtime_memory_mb = _memory_usage_mb()
        project.runtime_visible_objects = visible_objects
        project.runtime_draw_calls_estimated = metrics["draw_calls_estimated"]
        project.runtime_triangles_visible = visible_triangles
        project.runtime_texture_memory_mb = metrics["texture_memory_mb"]
        self._metrics = {
            "visible_objects": visible_objects,
            "visible_triangles": visible_triangles,
            "draw_calls": metrics["draw_calls_estimated"],
            "texture_memory_mb": metrics["texture_memory_mb"],
            "memory_mb": project.runtime_memory_mb,
        }

    def _bindings_for_action(self):
        actions = {}
        for binding in self.scene.blendengine_input_map.bindings:
            name = binding.custom_action if binding.action == "CUSTOM" and binding.custom_action else binding.action
            actions.setdefault(name, set()).add(binding.key.upper())
        return actions

    def _action_down(self, actions, action):
        return bool(actions.get(action, set()) & self.input_state)

    def _update_player(self, dt):
        player = utils.find_player_object(self.scene)
        if player is None:
            return

        controller = player.blendengine_object.player_controller
        if not controller.enabled:
            return

        actions = self._bindings_for_action()
        axis_x = 0.0
        axis_y = 0.0
        if self._action_down(actions, "MOVE_LEFT"):
            axis_x -= 1.0
        if self._action_down(actions, "MOVE_RIGHT"):
            axis_x += 1.0
        if self._action_down(actions, "MOVE_FORWARD"):
            axis_y += 1.0
        if self._action_down(actions, "MOVE_BACKWARD"):
            axis_y -= 1.0
        if controller.controller_type == "SIDE_SCROLLER":
            # Side view: W/S would walk into or out of the screen.
            axis_y = 0.0

        movement = Vector((axis_x, axis_y, 0.0))
        if movement.length > 1.0:
            movement.normalize()

        speed = controller.run_speed if controller.sprint and self._action_down(actions, "SPRINT") else controller.walk_speed
        if controller.controller_type == "FIRST_PERSON":
            yaw = player.rotation_euler.z
            # Local +Y and +X of the player (and of the camera that copies its yaw).
            forward = Vector((-math.sin(yaw), math.cos(yaw), 0.0))
            right = Vector((math.cos(yaw), math.sin(yaw), 0.0))
            player.location += (right * axis_x + forward * axis_y) * speed * dt
            if movement.length > 0.001:
                player.rotation_euler.z = yaw_towards(movement.x, movement.y)
        else:
            player.location += movement * speed * dt
            if movement.length > 0.001:
                player.rotation_euler.z = yaw_towards(movement.x, movement.y)
        self._clamp_to_bounds(player)

        ground_z = self._ground_height_at(player, default=self._ground_z.get(player.name, player.location.z))
        velocity = self._vertical_velocity.get(player.name, 0.0)
        grounded = player.location.z <= ground_z + 0.001
        if grounded:
            player.location.z = ground_z
            velocity = 0.0
            if self._action_down(actions, "JUMP") and controller.jump_force > 0.0:
                velocity = controller.jump_force
        velocity -= controller.gravity * dt
        player.location.z += velocity * dt
        if player.location.z < ground_z:
            player.location.z = ground_z
            velocity = 0.0
        self._vertical_velocity[player.name] = velocity

    def _update_camera(self):
        player = utils.find_player_object(self.scene)
        if player is None:
            return
        controller = player.blendengine_object.player_controller
        camera = controller.camera_follow or self.scene.camera
        if camera is None:
            return
        if controller.controller_type == "FIRST_PERSON":
            camera.location = player.location + Vector((0.0, 0.0, 0.72))
            camera.rotation_euler = (math.radians(90.0), 0.0, player.rotation_euler.z)
            for obj in self.scene.objects:
                if obj.blendengine_object.object_tag == "Weapon":
                    obj.hide_viewport = False
                    obj.hide_render = False
            return
        offset = self._camera_offsets.get(camera.name)
        if offset is None:
            offset = Vector((0.0, -6.0, 3.2))
            self._camera_offsets[camera.name] = offset
        camera.location = player.location + offset
        direction = player.location - camera.location
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    def _update_visibility_culling(self):
        optimization = self.scene.blendengine_optimization
        if not optimization.camera_frustum_generation and not optimization.hide_behind_camera:
            return
        camera = self.scene.camera
        player = utils.find_player_object(self.scene)
        if camera is None:
            return
        camera_world = world_matrix(camera)
        camera_forward = camera_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
        camera_location = camera_world.translation
        max_distance = max(optimization.world_cell_size * (optimization.visible_cell_radius + 1), 24.0)
        visible_count = 0
        for obj in self.scene.objects:
            if obj == camera or obj == player or obj.type in {"CAMERA", "EMPTY"}:
                continue
            if obj.blendengine_object.object_tag in {"Weapon", "FirstPersonArms"} or obj.name in self._removed:
                continue
            settings = obj.blendengine_object
            if settings.optimization.dynamic_object and settings.player_controller.enabled:
                continue
            hidden = False
            # Test the world-space bounding sphere: a big building whose
            # origin is far away (or a child of a moved/scaled parent) can
            # still fill the view.
            center, radius = world_bounds_sphere(obj)
            to_obj = center - camera_location
            distance = max(0.0, to_obj.length - radius)
            if optimization.hide_behind_camera and to_obj.length > radius:
                hidden = camera_forward.dot(to_obj) < -radius - 0.08 * to_obj.length
            if not hidden and optimization.camera_frustum_generation:
                hidden = distance > max_distance
            if visible_count >= optimization.max_visible_objects and settings.optimization.disable_when_far:
                hidden = True
            if not hidden:
                visible_count += 1
            try:
                obj.hide_set(hidden)
            except Exception:
                obj.hide_viewport = hidden

    def _update_npcs(self, dt):
        player = utils.find_player_object(self.scene)
        if player is None:
            return
        for obj in self.scene.objects:
            npc = obj.blendengine_object.npc_behavior
            if not npc.enabled or obj.name in self._removed:
                continue
            target = npc.target_object or player
            if npc.behavior_template == "PATROL":
                origin = self._patrol_origins.setdefault(obj.name, obj.location.copy())
                angle = self.elapsed * max(0.2, npc.move_speed) / max(1.0, npc.patrol_radius)
                if self._two_d:
                    # Pace back and forth along the side-view lane.
                    obj.location.x = origin.x + math.sin(angle) * npc.patrol_radius
                else:
                    obj.location.x = origin.x + math.cos(angle) * npc.patrol_radius
                    obj.location.y = origin.y + math.sin(angle) * npc.patrol_radius
            elif target is not None and npc.behavior_template in {"FOLLOW_PLAYER", "ATTACK", "COMPANION", "ENEMY_BOSS"}:
                self._move_toward(obj, target.location, npc.move_speed, dt, stop_distance=max(0.5, npc.attack_range))
                if npc.behavior_template in {"ATTACK", "ENEMY_BOSS"}:
                    self._try_npc_attack(obj, player, npc)
            elif target is not None and npc.behavior_template == "FLEE":
                away = obj.location + (obj.location - target.location)
                self._move_toward(obj, away, npc.move_speed, dt, stop_distance=0.0)
            if self._two_d:
                obj.location.y = self._patrol_origins.setdefault(obj.name, obj.location.copy()).y
            self._clamp_to_bounds(obj)

    def _try_npc_attack(self, npc_obj, player, npc):
        if (npc_obj.location - player.location).length > max(0.8, npc.attack_range):
            return
        cooldown_until = self._npc_attack_timers.get(npc_obj.name, 0.0)
        if self.elapsed < cooldown_until:
            return
        self._npc_attack_timers[npc_obj.name] = self.elapsed + 1.1
        health = player.blendengine_object.health
        if health.enabled:
            damage = getattr(npc, "attack_damage", 8.0)
            health.current_health = max(0.0, health.current_health - damage)
            self.log("%s hit player. Health %.0f." % (npc_obj.name, health.current_health))
            if health.current_health <= 0.0:
                self.finish_with("Game Over", "Player eliminated.")

    def _shoot_weapon(self):
        if self._attack_cooldown > 0.0:
            return
        player = utils.find_player_object(self.scene)
        camera = self.scene.camera
        if player is None or camera is None:
            return
        if not player.blendengine_object.player_controller.attack_key:
            # An empty Attack Key means this game has no attack.
            return
        ammo = _variable_lookup(player, "Ammo")
        if ammo is not None and _variable_value(ammo) <= 0:
            self.log("No ammo.")
            self._attack_cooldown = 0.25
            return
        if ammo is not None:
            _set_variable_value(ammo, max(0, _variable_value(ammo) - 1))
        self._attack_cooldown = 0.18
        self._muzzle_flash_until = self.elapsed + 0.08

        origin = camera.location.copy()
        direction = camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
        hit_obj = self._raycast_enemy(origin, direction, 80.0)
        if hit_obj is None:
            self.log("Shot fired.")
            return
        self._damage_enemy(hit_obj, 38.0, player)

    def _raycast_enemy(self, origin, direction, distance):
        try:
            depsgraph = self.context.evaluated_depsgraph_get()
            hit, _loc, _normal, _index, obj, _matrix = self.scene.ray_cast(depsgraph, origin, direction, distance=distance)
            if hit and obj is not None:
                candidate = self._enemy_owner(obj)
                if candidate is not None:
                    return candidate
        except Exception:
            pass
        best_obj = None
        best_score = distance
        for obj in self.scene.objects:
            candidate = self._enemy_owner(obj)
            if candidate is None:
                continue
            aim_point = candidate.location + Vector((0.0, 0.0, max(0.55, candidate.dimensions.z * 0.45)))
            to_obj = aim_point - origin
            forward = to_obj.dot(direction)
            if forward <= 0.0 or forward > distance:
                continue
            lateral = (to_obj - direction * forward).length
            radius = max(0.85, max(candidate.dimensions.x, candidate.dimensions.y, candidate.dimensions.z) * 0.55)
            if lateral <= radius and forward < best_score:
                best_score = forward
                best_obj = candidate
        return best_obj

    def _enemy_owner(self, obj):
        current = obj
        fallback = None
        while current is not None:
            if current.name in self._removed:
                return None
            if current.blendengine_object.object_tag in {"Zombie", "Enemy"}:
                fallback = current
                health = current.blendengine_object.health
                npc = current.blendengine_object.npc_behavior
                if health.enabled or npc.enabled:
                    return current
            current = current.parent
        return fallback

    def _damage_enemy(self, enemy, amount, player):
        health = enemy.blendengine_object.health
        if not health.enabled or enemy.name in self._removed:
            return
        health.current_health = max(0.0, health.current_health - amount)
        self._last_hit_name = enemy.name
        if health.current_health <= 0.0:
            self._remove_from_play(enemy)
            kills = _variable_lookup(player, "Kills")
            score = _variable_lookup(player, "Score")
            if kills is not None:
                _set_variable_value(kills, _variable_value(kills) + 1)
            if score is not None:
                _set_variable_value(score, _variable_value(score) + 100)
            self.log("%s eliminated." % enemy.name)
        else:
            self.log("%s hit. Health %.0f." % (enemy.name, health.current_health))

    def _ground_height_at(self, obj, default):
        """Height to stand at: the first Ground-tagged surface below the
        object's middle. Casting from the middle (not from far above) lets the
        player walk under platforms and step down off them; hits on the
        object itself or on non-ground objects are skipped."""
        half_height = max(0.1, obj.dimensions.z * 0.5)
        origin = Vector((obj.location.x, obj.location.y, obj.location.z + 0.25))
        direction = Vector((0.0, 0.0, -1.0))
        try:
            depsgraph = self.context.evaluated_depsgraph_get()
            for _attempt in range(8):
                hit, loc, _normal, _index, hit_obj, _matrix = self.scene.ray_cast(depsgraph, origin, direction, distance=40.0)
                if not hit:
                    break
                if hit_obj is not None and hit_obj.name != obj.name and hit_obj.blendengine_object.object_tag == "Ground":
                    return loc.z + half_height
                origin = loc + direction * 0.02
        except Exception:
            pass
        return default

    def _clamp_to_bounds(self, obj):
        if self._bounds is None:
            return
        min_x, min_y, max_x, max_y = self._bounds
        obj.location.x = min(max(obj.location.x, min_x), max_x)
        obj.location.y = min(max(obj.location.y, min_y), max_y)

    def _move_toward(self, obj, target_location, speed, dt, stop_distance=0.0):
        delta = Vector((target_location.x - obj.location.x, target_location.y - obj.location.y, 0.0))
        distance = delta.length
        if distance <= stop_distance or distance <= 0.0001:
            return
        delta.normalize()
        obj.location += delta * min(speed * dt, max(0.0, distance - stop_distance))
        obj.rotation_euler.z = yaw_towards(delta.x, delta.y)

    def execute_behaviors(self, event_type, dt, key=None):
        for obj in self.scene.objects:
            settings = obj.blendengine_object
            for behavior in settings.behaviors:
                if not behavior.enabled:
                    continue
                if behavior.events and not self._behavior_event_matches(obj, behavior, event_type, key=key):
                    continue
                if not behavior.events and event_type != "ON_UPDATE":
                    continue
                if not self._conditions_pass(obj, behavior.conditions):
                    continue
                for action in behavior.actions:
                    self._execute_action(obj, action, dt)

    def _behavior_event_matches(self, obj, behavior, event_type, key=None, tag=""):
        for event in behavior.events:
            if event.event_type != event_type:
                continue
            if event_type == "ON_KEY_PRESS" and key and event.key.upper() != key.upper():
                continue
            if event_type in {"ON_ENTER_TRIGGER", "ON_COLLISION"} and event.tag and event.tag != tag:
                continue
            if event_type == "ON_TIMER":
                timer_key = (obj.name, behavior.name, event.name)
                deadline = self._timer_state.setdefault(timer_key, self.elapsed + event.timer_seconds)
                if self.elapsed < deadline:
                    continue
                self._timer_state[timer_key] = self.elapsed + max(0.01, event.timer_seconds)
            return True
        return False

    def _execute_behaviors_on_object(self, obj, event_type, dt, tag=""):
        settings = obj.blendengine_object
        for behavior in settings.behaviors:
            if not behavior.enabled:
                continue
            if behavior.events and not self._behavior_event_matches(obj, behavior, event_type, tag=tag):
                continue
            if not behavior.events and event_type != "ON_UPDATE":
                continue
            if not self._conditions_pass(obj, behavior.conditions):
                continue
            for action in behavior.actions:
                self._execute_action(obj, action, dt)

    def _update_triggers(self, dt):
        active_pairs = set()
        objects = [obj for obj in self.scene.objects if obj.name not in self._removed]
        triggers = [obj for obj in objects if _component_enabled(obj, "TRIGGER_ZONE")]
        # Static objects never move into a trigger, so only moving game objects are tested.
        game_objects = [
            obj for obj in objects
            if obj.blendengine_object.is_game_object
            and not obj.blendengine_object.optimization.static_object
            and not _component_enabled(obj, "TRIGGER_ZONE")
        ]
        for trigger in triggers:
            for other in game_objects:
                if trigger == other:
                    continue
                pair = (trigger.name, other.name)
                if self._objects_overlap(trigger, other):
                    active_pairs.add(pair)
                    if pair not in self._trigger_overlaps:
                        other_tag = other.blendengine_object.object_tag
                        trigger_tag = trigger.blendengine_object.object_tag
                        self._execute_behaviors_on_object(trigger, "ON_ENTER_TRIGGER", dt, tag=other_tag)
                        self._execute_behaviors_on_object(other, "ON_ENTER_TRIGGER", dt, tag=trigger_tag)
        self._trigger_overlaps = active_pairs

    def _update_collisions(self, dt):
        colliders = [
            obj for obj in self.scene.objects
            if obj.name not in self._removed and _component_enabled(obj, "COLLIDER")
        ]
        active_pairs = set()
        for index, first in enumerate(colliders):
            for second in colliders[index + 1:]:
                pair = tuple(sorted((first.name, second.name)))
                if self._objects_overlap(first, second):
                    active_pairs.add(pair)
                    if pair not in self._collision_overlaps:
                        first_tag = first.blendengine_object.object_tag
                        second_tag = second.blendengine_object.object_tag
                        self._execute_behaviors_on_object(first, "ON_COLLISION", dt, tag=second_tag)
                        self._execute_behaviors_on_object(second, "ON_COLLISION", dt, tag=first_tag)
        self._collision_overlaps = active_pairs

    def _objects_overlap(self, first, second):
        first_radius = max(first.dimensions.x, first.dimensions.y, first.dimensions.z, 0.1) * 0.5
        second_radius = max(second.dimensions.x, second.dimensions.y, second.dimensions.z, 0.1) * 0.5
        return (first.location - second.location).length <= first_radius + second_radius

    def _conditions_pass(self, obj, conditions):
        for condition in conditions:
            if condition.condition_type == "ALWAYS":
                continue
            if condition.condition_type == "KEY_HELD":
                if condition.text_value.upper() not in self.input_state:
                    return False
            elif condition.condition_type == "VARIABLE_COMPARE":
                variable = self.lookup_variable(obj, condition.variable_name)
                if variable is None:
                    return False
                right = condition.number_value
                if variable.variable_type == "BOOL":
                    right = condition.bool_value
                elif variable.variable_type == "STRING":
                    right = condition.text_value
                if not _compare(_variable_value(variable), condition.compare, right):
                    return False
            elif condition.condition_type == "HEALTH_COMPARE":
                health = obj.blendengine_object.health
                if not health.enabled or not _compare(health.current_health, condition.compare, condition.number_value):
                    return False
            elif condition.condition_type == "TIMER_FINISHED":
                key = (obj.name, condition.name)
                deadline = self._timer_state.setdefault(key, self.elapsed + condition.number_value)
                if self.elapsed < deadline:
                    return False
                self._timer_state[key] = self.elapsed + condition.number_value
            else:
                continue
        return True

    def _execute_action(self, owner, action, dt):
        target = action.target_object or owner
        if action.action_type == "SHOW_LOG":
            self.log(action.text_value or ("%s ran %s" % (owner.name, action.name)))
        elif action.action_type == "MOVE_FORWARD":
            target.location.y += action.number_value * dt
        elif action.action_type == "MOVE_OBJECT":
            target.location += Vector(action.vector_value) * (dt if dt > 0.0 else 1.0)
        elif action.action_type == "ROTATE_OBJECT":
            target.rotation_euler.z += action.number_value * dt
        elif action.action_type == "SET_VARIABLE":
            variable = self.lookup_variable(owner, action.variable_name)
            if variable is not None:
                _set_variable_value(variable, action.number_value if variable.variable_type != "STRING" else action.text_value)
        elif action.action_type == "ADD_VARIABLE":
            variable = self.lookup_variable(owner, action.variable_name)
            if variable is not None and variable.variable_type in {"INT", "FLOAT"}:
                _set_variable_value(variable, _variable_value(variable) + action.number_value)
        elif action.action_type == "COLLECT_OBJECT":
            self._remove_from_play(target)
        elif action.action_type == "WIN_GAME":
            self.finish_with("Victory", action.text_value or "You win!")
        elif action.action_type == "CHANGE_HEALTH":
            health = target.blendengine_object.health
            if health.enabled:
                health.current_health = max(0.0, min(health.max_health, health.current_health + action.number_value))
                if health.current_health <= 0.0 and health.game_over_on_death:
                    self.finish_with("Game Over", "%s was defeated." % target.name)
        elif action.action_type == "PLAY_ANIMATION":
            if action.animation is not None:
                if target.animation_data is None:
                    target.animation_data_create()
                target.animation_data.action = action.animation
        elif action.action_type == "OPEN_DOOR":
            target.rotation_euler.z = math.radians(90.0)
        elif action.action_type == "SPAWN_OBJECT" and target is not None:
            duplicate = target.copy()
            if target.data is not None:
                duplicate.data = target.data.copy()
            duplicate.location += Vector(action.vector_value)
            self.scene.collection.objects.link(duplicate)
            self._spawned.append(duplicate)
        elif action.action_type == "GAME_OVER":
            self.finish_with("Game Over", action.text_value or "Game Over")


def start_test_run(context):
    global ACTIVE_SESSION
    if ACTIVE_SESSION is not None:
        ACTIVE_SESSION.stop("Restarted")
    result = validate_scene(context.scene)
    if not result.ok:
        context.scene.blendengine_project.test_running = False
        context.scene.blendengine_project.test_status = result.summary()
        return None, result
    session = GameSession(context)
    ACTIVE_SESSION = session
    session.start()
    return session, result


def request_stop(scene):
    if ACTIVE_SESSION is not None:
        ACTIVE_SESSION.stop_requested = True
    if scene is not None:
        scene.blendengine_project.test_running = False
        scene.blendengine_project.test_status = "Stopping"


def finish_active_session(status="Stopped"):
    global ACTIVE_SESSION
    if ACTIVE_SESSION is not None:
        ACTIVE_SESSION.stop(status)
        ACTIVE_SESSION = None


def _memory_usage_mb():
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return float(usage) / 1024.0
    except Exception:
        return 0.0


def _draw_runtime_hud():
    if ACTIVE_SESSION is None:
        return
    scene = ACTIVE_SESSION.scene
    project = scene.blendengine_project
    if not (project.show_fps or project.debug_mode or project.show_game_variables):
        return
    try:
        import blf
    except Exception:
        return

    lines = [
        "BlendEngine Play Mode",
    ]
    goal_text = scene.get("blendengine_goal_text")
    if goal_text:
        lines.append("Goal: %s" % goal_text)
    lines += [
        "FPS %.0f  %.1f ms" % (project.runtime_fps, project.runtime_frame_ms),
        "RAM %.0f MB  Visible %d" % (project.runtime_memory_mb, project.runtime_visible_objects),
        "Tris %d  Draw %d  Tex %.1f MB" % (
            project.runtime_triangles_visible,
            project.runtime_draw_calls_estimated,
            project.runtime_texture_memory_mb,
        ),
        "WASD move  Space jump  Shift sprint  F attack  R aim  Esc stop",
    ]
    player = utils.find_player_object(scene)
    if player is not None and project.show_game_variables:
        score = _variable_lookup(player, "Score")
        ammo = _variable_lookup(player, "Ammo")
        kills = _variable_lookup(player, "Kills")
        health = player.blendengine_object.health
        if score is not None:
            lines.append("Score %s" % _variable_value(score))
        if ammo is not None:
            lines.append("Ammo %s" % _variable_value(ammo))
        if kills is not None:
            lines.append("Kills %s" % _variable_value(kills))
        collected = _variable_lookup(player, "Collected")
        target = scene.get("blendengine_goal_target", 0)
        if collected is not None and target:
            lines.append("Collected %s / %s" % (_variable_value(collected), target))
        if scene.get("blendengine_ai_generated"):
            lines.append("Time %.0f s" % ACTIVE_SESSION.elapsed)
        if health.enabled:
            lines.append("Health %.0f / %.0f" % (health.current_health, health.max_health))
    if ACTIVE_SESSION._last_hit_name:
        lines.append("Last hit: %s" % ACTIVE_SESSION._last_hit_name)

    font_id = 0
    x = 18
    y = 92 + len(lines) * 18
    try:
        blf.size(font_id, 14)
    except TypeError:
        blf.size(font_id, 14, 72)
    for index, line in enumerate(lines):
        if index == 0:
            color = (0.0, 0.92, 0.76, 1.0)
        elif "FPS" in line and project.runtime_fps < max(30.0, scene.blendengine_performance_budget.target_fps * 0.75):
            color = (1.0, 0.45, 0.18, 1.0)
        else:
            color = (0.88, 0.94, 0.96, 1.0)
        try:
            blf.color(font_id, *color)
        except Exception:
            pass
        blf.position(font_id, x, y - index * 18, 0)
        blf.draw(font_id, line)


def _add_hud_handler():
    global HUD_HANDLER
    if HUD_HANDLER is not None:
        return
    try:
        import bpy
        if bpy.app.background:
            return
        HUD_HANDLER = bpy.types.SpaceView3D.draw_handler_add(_draw_runtime_hud, (), "WINDOW", "POST_PIXEL")
    except Exception:
        HUD_HANDLER = None


def _remove_hud_handler():
    global HUD_HANDLER
    if HUD_HANDLER is None:
        return
    try:
        import bpy
        bpy.types.SpaceView3D.draw_handler_remove(HUD_HANDLER, "WINDOW")
    except Exception:
        pass
    HUD_HANDLER = None


def register():
    pass


def unregister():
    finish_active_session("Stopped")
