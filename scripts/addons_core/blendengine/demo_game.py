# SPDX-License-Identifier: GPL-2.0-or-later
"""Neon Relay: a small original game exercising the native editor runtime.

The arena is generated from simple meshes, batched by material. Gameplay is
opt-in via the scene's ``blendengine_demo`` marker; regular projects are never
affected. No browser, network request, external asset, or offline animation is
used to run the game.
"""

import json
import math

import bpy
from mathutils import Vector

from . import components, graphics, input_system, optimization, utils


CORE_POSITIONS = ((0, -6.5, 0.95), (-3, -2.5, 0.95), (3, 1.5, 0.95),
                  (-2, 5.5, 0.95), (0, 9, 0.95))
SPAWN = (0.0, -10.0, 0.92)
GOAL = (0.0, 12.0, 1.6)
GOAL_SCORE = 5
RECORDING_WAYPOINTS = ((0, -6.5), (-3, -2.5), (-3, 1.5), (3, 1.5),
                       (-2, 5.5), (0, 9), (0, 12))


class Geometry:
    """Tiny mesh builder; many static details share one object/material batch."""

    def __init__(self):
        self.vertices = []
        self.faces = []
        self.material_indices = []

    def add(self, vertices, faces, material=0):
        offset = len(self.vertices)
        self.vertices.extend(vertices)
        self.faces.extend(tuple(offset + i for i in face) for face in faces)
        self.material_indices.extend([material] * len(faces))

    def box(self, center, size, material=0):
        x, y, z = center
        a, b, c = (value * 0.5 for value in size)
        vertices = [(x + dx, y + dy, z + dz) for dx, dy, dz in
                    ((-a, -b, -c), (a, -b, -c), (a, b, -c), (-a, b, -c),
                     (-a, -b, c), (a, -b, c), (a, b, c), (-a, b, c))]
        self.add(vertices, ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                            (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)), material)

    def octahedron(self, center, scale, material=0):
        x, y, z = center
        a, b, c = scale
        vertices = ((x+a, y, z), (x-a, y, z), (x, y+b, z),
                    (x, y-b, z), (x, y, z+c), (x, y, z-c))
        self.add(vertices, ((0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
                            (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)), material)

    def torus(self, center, radius, width, material=0, upright=False, segments=40):
        vertices, faces = [], []
        sides = 6
        for i in range(segments):
            angle = i * math.tau / segments
            for j in range(sides):
                small = j * math.tau / sides
                r = radius + width * math.cos(small)
                u, v, w = r * math.cos(angle), r * math.sin(angle), width * math.sin(small)
                local = (u, w, v) if upright else (u, v, w)
                vertices.append(tuple(center[k] + local[k] for k in range(3)))
        for i in range(segments):
            for j in range(sides):
                faces.append((i*sides+j, ((i+1) % segments)*sides+j,
                              ((i+1) % segments)*sides+(j+1) % sides, i*sides+(j+1) % sides))
        self.add(vertices, faces, material)

    def object(self, scene, name, materials):
        mesh = bpy.data.meshes.new(name + " Mesh")
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.update()
        for material in materials:
            mesh.materials.append(material)
        for polygon, index in zip(mesh.polygons, self.material_indices):
            polygon.material_index = index
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        return obj


def _material(name, color, roughness=0.6, metallic=0.0, emission=0.0):
    mat = bpy.data.materials.new("Relay | " + name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    node = mat.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (*color, 1)
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Metallic"].default_value = metallic
    if emission:
        socket = node.inputs.get("Emission Color") or node.inputs.get("Emission")
        socket.default_value = (*color, 1)
        if node.inputs.get("Emission Strength"):
            node.inputs["Emission Strength"].default_value = emission
    mat.asset_mark()
    return mat


def _light(scene, name, light_type, location, color, energy, target=None, shadow=False):
    data = bpy.data.lights.new(name, light_type)
    data.color = color
    data.energy = energy
    data.use_shadow = shadow
    if light_type == "AREA":
        data.size = 10.0
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = location
    if target:
        obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def create_demo(context):
    """Create a new playable scene, preserving the current scene and its assets."""
    scene = bpy.data.scenes.new("Neon Relay")
    if context.window is not None:
        context.window.scene = scene
    project = utils.ensure_project_defaults(scene)
    project.game_title = "Neon Relay"
    project.game_dimension = "THREE_D"
    project.target_platform = "LINUX"
    project.resolution_x, project.resolution_y = 960, 540
    project.show_logs = True
    project.show_fps = False
    project.show_game_variables = False
    project.debug_mode = False
    scene["blendengine_demo"] = "NEON_RELAY"
    scene["blendengine_goal_score"] = GOAL_SCORE
    scene["demo_instructions"] = "WASD move | Space jump | Shift sprint | Collect 5 cores, reach portal | R restart | Esc stop"
    scene["demo_asset_origin"] = "Original procedural meshes/materials generated by BlendEngine; no external assets"
    scene["demo_spawn"] = list(SPAWN)
    scene["demo_bounds"] = [-8.0, 8.0, -12.0, 13.8]
    scene["blendengine_demo_waypoints"] = json.dumps(RECORDING_WAYPOINTS)
    graphics.configure_realtime(scene)
    optimization.apply_preset(scene, "BALANCED")
    # This game deliberately prioritizes responsive raster rendering. Geometry,
    # emission and a few broad lights carry the art direction, rather than rays.
    eevee = scene.eevee
    for name, value in (("taa_samples", 16), ("taa_render_samples", 64),
                        ("use_raytracing", False), ("use_ssr", False),
                        ("gtao_distance", 1.4), ("gtao_factor", 1.1),
                        ("bloom_intensity", 0.055), ("shadow_cube_size", "1024"),
                        ("shadow_cascade_size", "1024")):
        if hasattr(eevee, name):
            setattr(eevee, name, value)
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.resolution_percentage = 100
    scene.render.fps = 60
    scene.view_settings.exposure = -0.15
    world = bpy.data.worlds.new("Relay | Midnight sky")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.055, 0.10, 0.20, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.45
    scene.world = world
    optimize = scene.blendengine_optimization
    optimize.camera_frustum_generation = False
    optimize.hide_behind_camera = False

    navy = _material("Midnight frame", (0.025, 0.05, 0.085), 0.55, 0.3)
    slate = _material("Arena slate", (0.07, 0.12, 0.17), 0.7)
    white = _material("Ceramic armor", (0.67, 0.8, 0.84), 0.42, 0.12)
    metal = _material("Copper hardware", (0.52, 0.22, 0.065), 0.4, 0.65)
    cyan = _material("Cyan energy", (0.035, 0.68, 1.0), 0.45, 0.15, 3.0)
    amber = _material("Amber energy", (1.0, 0.4, 0.045), 0.4, 0.25, 2.7)
    danger = _material("Hazard red", (1.0, 0.035, 0.095), 0.55, 0.1, 2.0)
    black = _material("Visor glass", (0.008, 0.018, 0.026), 0.23, 0.6)
    materials = (navy, slate, white, metal, cyan, amber, danger, black)
    # Index mapping above keeps all decorative geometry in one static batch.
    decor = Geometry()
    floor_geo = Geometry()
    floor_geo.box((0, 1, -0.2), (18, 28, 0.4))
    ground = floor_geo.object(scene, "Arena floor", [slate])
    components.add_collider(ground, "Ground")
    optimization.mark_static_object(ground)
    for x in range(-8, 9, 2):
        decor.box((x, 1, 0.006), (0.024, 27.8, 0.012), 0)
    for y in range(-12, 15, 2):
        decor.box((0, y, 0.007), (17.8, 0.024, 0.014), 0)
    for side in (-1, 1):
        decor.box((side * 8.7, 1, 0.25), (0.46, 28, 0.5), 0)
        decor.box((side * 8.68, 1, 0.52), (0.08, 27.7, 0.055), 4)
        decor.box((side * 6.8, 1, 0.018), (0.04, 27, 0.025), 4)
        for index, y in enumerate((-11, -6, -1, 4, 9, 14)):
            height = 2.6 if index % 2 else 3.5
            decor.box((side * 9.2, y, height * 0.5), (1.1, 1.3, height), 0)
            decor.box((side * 8.62, y - 0.3, height * 0.55), (0.035, 0.44, height * 0.7), 4)
            decor.box((side * 9.2, y, height + 0.06), (1.3, 1.5, 0.12), 3)
    decor.box((0, 14.4, 1.05), (18, 0.4, 2.1), 0)
    decor.box((0, 14.15, 1.95), (17, 0.045, 0.08), 4)
    decor.box((0, -12.5, 0.16), (17.2, 0.45, 0.32), 0)
    # Recessed guide pads make pickup and hazard locations legible at a glance.
    for x, y, _z in CORE_POSITIONS:
        decor.box((x, y, 0.04), (1.25, 1.25, 0.07), 0)
        decor.torus((x, y, 0.09), 0.52, 0.025, 5, segments=24)
    for x, y in ((-5.5, -4), (5.5, 5.7)):
        decor.box((x, y, 0.42), (1.5, 1.4, 0.84), 0)
        decor.box((x, y, 0.86), (1.58, 1.48, 0.08), 3)
        decor.box((x, y - 0.713, 0.63), (0.72, 0.02, 0.08), 4)
    decor.box((0, 12, 0.08), (5.4, 3.6, 0.16), 0)
    decor.box((0, 12, 0.18), (4.5, 3, 0.1), 3)
    decor.torus((0, 12, 1.85), 1.65, 0.13, 3, upright=True, segments=48)
    decor.torus((0, 11.94, 1.85), 1.43, 0.055, 4, upright=True, segments=48)
    decor.box((-1.8, 12, 1.0), (0.48, 0.9, 2), 0)
    decor.box((1.8, 12, 1.0), (0.48, 0.9, 2), 0)
    environment = decor.object(scene, "Arena architecture (batched)", materials)
    optimization.mark_static_object(environment)

    hero_geo = Geometry()
    hero_geo.box((0, 0, 0.05), (0.58, 0.4, 0.64), 2)
    hero_geo.box((0, -0.235, 0.16), (0.33, 0.12, 0.38), 3)
    hero_geo.box((0, -0.307, 0.16), (0.08, 0.028, 0.27), 4)
    hero_geo.box((0, 0, 0.62), (0.48, 0.45, 0.4), 2)
    hero_geo.box((0, 0.235, 0.65), (0.4, 0.025, 0.17), 7)
    hero_geo.box((0, 0.25, 0.65), (0.32, 0.012, 0.035), 4)
    for side in (-1, 1):
        hero_geo.box((side * 0.38, 0, 0.06), (0.18, 0.3, 0.58), 4)
        hero_geo.box((side * 0.17, 0, -0.51), (0.22, 0.29, 0.48), 0)
        hero_geo.box((side * 0.17, 0.07, -0.79), (0.24, 0.4, 0.15), 2)
    player = hero_geo.object(scene, "Relay Runner", materials)
    player.location = SPAWN
    controller = components.add_player_controller(player)
    controller.controller_type = "THIRD_PERSON"
    controller.walk_speed = 4.2
    controller.run_speed = 6.8
    controller.jump_force = 6.0
    controller.gravity = 18.0
    components.add_health(player, 100)
    components.add_collider(player, "Player")
    optimization.mark_dynamic_object(player)
    score = player.blendengine_object.variables.add()
    score.name, score.variable_type, score.int_value = "Score", "INT", 0
    player.asset_mark()

    core_geometry = Geometry()
    core_geometry.octahedron((0, 0, 0), (0.32, 0.32, 0.5), 0)
    core_geometry.torus((0, 0, 0), 0.43, 0.028, 1, segments=20)
    cores = []
    for index, position in enumerate(CORE_POSITIONS):
        if index == 0:
            core = core_geometry.object(scene, "Energy Core 01", [amber, white])
        else:
            core = bpy.data.objects.new("Energy Core %02d" % (index + 1), cores[0].data)
            scene.collection.objects.link(core)
        core.location = position
        utils.mark_game_object(core, "RelayCore")
        cores.append(core)
    goal_geometry = Geometry()
    goal_geometry.octahedron((0, 0, 0), (0.2, 0.2, 0.4))
    portal = goal_geometry.object(scene, "Relay Portal", [cyan])
    portal.location = GOAL
    utils.mark_game_object(portal, "RelayPortal")

    hazards = []
    for index, position in enumerate(((0, -0.5, 0.065), (-3.8, 7.2, 0.065))):
        geo = Geometry()
        geo.box((0, 0, 0), (2.0, 0.9, 0.06))
        for x in (-0.75, -0.25, 0.25, 0.75):
            geo.box((x, 0, 0.07), (0.07, 0.85, 0.08))
        hazard = geo.object(scene, "Energy Hazard %02d" % (index + 1), [danger])
        hazard.location = position
        utils.mark_game_object(hazard, "RelayHazard")
        hazards.append(hazard)

    camera_data = bpy.data.cameras.new("Runner Camera")
    camera = bpy.data.objects.new("Runner Camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = Vector(SPAWN) + Vector((0, -8.8, 6.5))
    camera.rotation_euler = (Vector(SPAWN) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 29
    camera_data.clip_end = 100
    camera_data.dof.use_dof = False
    scene.camera = camera
    controller.camera_follow = camera
    _light(scene, "Arena key", "SUN", (-5, -8, 12), (0.68, 0.84, 1), 2.0, (0, 2, 0), True)
    _light(scene, "Amber soft fill", "AREA", (4, -2, 9), (1, 0.5, 0.22), 850, (0, 2, 0))
    _light(scene, "Portal cyan fill", "AREA", (0, 10, 5), (0.1, 0.66, 1), 500, (0, 4, 0))
    input_system.ensure_defaults(scene)
    scene.blendengine_editor.input_lock_enabled = False
    log = bpy.data.texts.get("BlendEngine Runtime Log") or bpy.data.texts.new("BlendEngine Runtime Log")
    log.clear()
    log.write("NEON RELAY\nCollect five amber energy cores, then reach the cyan portal.\n"
              "WASD move | Space jump | Shift sprint | R restart | Esc return to editor\n"
              "This is a live native editor-runtime game, not a video or browser app.\n")
    if context.window is not None:
        for obj in context.selected_objects:
            obj.select_set(False)
        player.select_set(True)
        context.view_layer.objects.active = player
    return {"scene": scene, "player": player, "camera": camera,
            "cores": cores, "portal": portal, "hazards": hazards}


class DemoGame:
    """Small cached gameplay loop attached by runtime.GameSession."""

    custom_hud = True

    def __init__(self, session):
        self.session = session
        self.scene = session.scene
        self.player = session.player
        self.cores = sorted((obj for obj in self.scene.objects
                             if obj.blendengine_object.object_tag == "RelayCore"), key=lambda obj: obj.name)
        self.hazards = [obj for obj in self.scene.objects if obj.blendengine_object.object_tag == "RelayHazard"]
        self.portal = next(obj for obj in self.scene.objects if obj.blendengine_object.object_tag == "RelayPortal")
        self.score = next(var for var in self.player.blendengine_object.variables if var.name == "Score")
        self.health = self.player.blendengine_object.health
        self.collected = set()
        self.state = "READY"
        self.elapsed = 0.0
        self.message = "Collect all five amber cores"
        self.message_until = 3.0
        self._handler = None
        self._shader = None
        self._restart_held = False
        self._hazard_cooldown = 0.0
        self._initial_player = (self.player.location.copy(), self.player.rotation_euler.copy(),
                                self.player.blendengine_object.player_controller.enabled,
                                self.health.current_health, self.score.int_value)
        self._initial_camera = (self.scene.camera.location.copy(), self.scene.camera.rotation_euler.copy())
        self._initial_cores = [(obj, obj.location.copy(), obj.rotation_euler.copy(), obj.hide_viewport,
                                obj.hide_render, obj.hide_get()) for obj in self.cores]

    def start(self):
        self.restart()
        if not bpy.app.background:
            self._handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_hud, (), "WINDOW", "POST_PIXEL")
        self.session.log("Neon Relay started. Collect 5 cores and reach the cyan portal.")

    def restart(self):
        self.state, self.elapsed = "RUNNING", 0.0
        self.collected.clear()
        self.score.int_value = 0
        self.health.current_health = self.health.max_health
        self.player.location = Vector(self.scene.get("demo_spawn", SPAWN))
        self.player.rotation_euler = (0, 0, 0)
        self.player.blendengine_object.player_controller.enabled = True
        self.session._vertical_velocity[self.player.name] = 0.0
        for obj, location, rotation, _hidden, _render_hidden, _local_hidden in self._initial_cores:
            obj.hide_viewport = False
            obj.hide_render = False
            obj.hide_set(False)
            obj.location, obj.rotation_euler = location, rotation
        self.message = "Collect all five amber cores"
        self.message_until, self._hazard_cooldown = 3.0, 0.0

    def update(self, dt):
        restart_down = "R" in self.session.input_state
        if restart_down and not self._restart_held:
            self.restart()
            self.session.log("Neon Relay restarted.")
        self._restart_held = restart_down
        if self.state != "RUNNING":
            return
        self.elapsed += dt
        self._hazard_cooldown = max(0.0, self._hazard_cooldown - dt)
        bounds = self.scene.get("demo_bounds", (-8, 8, -12, 13.8))
        self.player.location.x = min(bounds[1], max(bounds[0], self.player.location.x))
        self.player.location.y = min(bounds[3], max(bounds[2], self.player.location.y))
        for index, core in enumerate(self.cores):
            if core.name in self.collected:
                continue
            core.rotation_euler.z = self.elapsed * 1.6 + index
            core.location.z = CORE_POSITIONS[index][2] + math.sin(self.elapsed * 2.8 + index) * 0.10
            if (self.player.location - core.location).length < 1.0:
                self.collected.add(core.name)
                core.hide_viewport = core.hide_render = True
                self.score.int_value = len(self.collected)
                self.message = ("All cores collected! Reach the cyan portal" if self.score.int_value == GOAL_SCORE
                                else "Energy core %d / 5 collected" % self.score.int_value)
                self.message_until = self.elapsed + 2.5
                self.session.log(self.message)
        if self._hazard_cooldown <= 0 and self.player.location.z < 1.38:
            for hazard in self.hazards:
                delta = self.player.location - hazard.location
                if abs(delta.x) < 1.2 and abs(delta.y) < 0.7:
                    self.health.current_health = max(0.0, self.health.current_health - 25)
                    self._hazard_cooldown = 1.1
                    self.message, self.message_until = "Hazard! Jump over red energy strips", self.elapsed + 2.4
                    self.session.log("Hazard hit. Health %d." % self.health.current_health)
                    if self.health.current_health <= 0:
                        self.state = "LOST"
                        self.player.blendengine_object.player_controller.enabled = False
                        self.session.log("Relay interrupted. Press R to retry.")
                    break
        portal_delta = self.player.location - self.portal.location
        if portal_delta.xy.length < 1.5:
            if self.score.int_value >= GOAL_SCORE:
                self.state = "WON"
                self.player.blendengine_object.player_controller.enabled = False
                self.session.log("RELAY ONLINE! Completed in %.2f seconds." % self.elapsed)
            elif self.elapsed > self.message_until:
                self.message = "Portal locked: collect all five amber cores"
                self.message_until = self.elapsed + 2.0

    def stop(self):
        if self._handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handler, "WINDOW")
            self._handler = None
        for obj, location, rotation, hidden, render_hidden, local_hidden in self._initial_cores:
            obj.hide_viewport, obj.hide_render = hidden, render_hidden
            obj.hide_set(local_hidden)
            obj.location, obj.rotation_euler = location, rotation
        location, rotation, enabled, health, score = self._initial_player
        self.player.location, self.player.rotation_euler = location, rotation
        self.player.blendengine_object.player_controller.enabled = enabled
        self.health.current_health, self.score.int_value = health, score
        self.scene.camera.location, self.scene.camera.rotation_euler = self._initial_camera

    def draw_hud(self):
        if bpy.context.scene != self.scene or bpy.context.region is None:
            return
        import blf
        import gpu
        from gpu_extras.batch import batch_for_shader
        region = bpy.context.region
        width, height = region.width, region.height
        if self._shader is None:
            try:
                self._shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            except ValueError:
                self._shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
        shader = self._shader

        def panel(x, y, w, h, color=(0.012, 0.025, 0.045, 0.9)):
            coords = ((x, y), (x+w, y), (x+w, y+h), (x, y+h))
            batch = batch_for_shader(shader, "TRIS", {"pos": coords}, indices=((0, 1, 2), (0, 2, 3)))
            gpu.state.blend_set("ALPHA")
            shader.bind()
            shader.uniform_float("color", color)
            batch.draw(shader)
            gpu.state.blend_set("NONE")

        def text(value, x, y, size=15, color=(0.85, 0.93, 0.97, 1)):
            try:
                blf.size(0, size)
            except TypeError:
                blf.size(0, size, 72)
            blf.color(0, *color)
            blf.position(0, x, y, 0)
            blf.draw(0, value)

        panel(18, height-116, 310, 98)
        panel(18, height-116, 4, 98, (0.02, 0.78, 1, 1))
        text("NEON RELAY", 36, height-46, 22, (0.1, 0.85, 1, 1))
        text("ENERGY CORES   %d / 5" % self.score.int_value, 36, height-72, 15)
        text("HEALTH %d     TIME %.1fs" % (self.health.current_health, self.elapsed), 36, height-96, 14)
        telemetry = "Logic %.1f ms" % getattr(self.session, "logic_ms", 0.0)
        viewport_fps = getattr(self.session, "viewport_fps", 0.0)
        if viewport_fps > 0:
            telemetry = "View redraw %.0f Hz  |  " % viewport_fps + telemetry
        text(telemetry, 24, 24, 12, (0.67, 0.79, 0.86, 1))
        panel(max(18, width-414), 17, 396, 65)
        text("WASD move   SPACE jump   SHIFT sprint", max(32, width-398), 57, 14)
        text("R restart   ESC return to editor", max(32, width-398), 34, 13, (0.64, 0.78, 0.86, 1))
        if self.state in {"WON", "LOST"}:
            panel(width/2-235, height/2-75, 470, 164)
            color = (0.1, 0.9, 1, 1) if self.state == "WON" else (1, 0.25, 0.24, 1)
            text("RELAY ONLINE" if self.state == "WON" else "RELAY INTERRUPTED", width/2-205, height/2+43, 28, color)
            text("5 energy cores delivered in %.1fs" % self.elapsed if self.state == "WON"
                 else "The red strips depleted your energy", width/2-205, height/2+9, 17)
            text("Press R to play again   |   ESC for editor", width/2-205, height/2-32, 15)
        elif self.elapsed < self.message_until:
            panel(width/2-225, 100, 450, 42)
            text(self.message, width/2-210, 115, 15, (1, 0.75, 0.34, 1))
