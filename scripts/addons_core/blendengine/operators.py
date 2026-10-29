# SPDX-License-Identifier: GPL-2.0-or-later
#
# BlendEngine operators.

import bpy
import time
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator

from . import (
    ai_system,
    animation_system,
    components,
    export_system,
    input_system,
    optimization,
    performance,
    properties,
    runtime,
    templates,
    utils,
)


def _require_active_object(context, operator):
    obj = utils.active_object(context)
    if obj is None:
        operator.report({"ERROR"}, "Select an object first.")
        return None
    return obj


def _active_behavior(obj):
    settings = obj.blendengine_object
    if not settings.behaviors:
        behavior = settings.behaviors.add()
        behavior.name = "New Behavior"
        behavior.description = "Beginner no-code gameplay behavior."
        settings.active_behavior_index = len(settings.behaviors) - 1
        return behavior
    return utils.active_item(settings.behaviors, settings.active_behavior_index)


class BE_OT_create_workspace(Operator):
    bl_idname = "blendengine.create_workspace"
    bl_label = "Create BlendEngine Workspace"
    bl_description = "Create or activate a beginner-friendly BlendEngine workspace"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        utils.ensure_project_defaults(context.scene)
        workspace = utils.activate_engine_page(context, "STUDIO")
        if workspace is None:
            self.report({"ERROR"}, "Could not create a BlendEngine workspace from the current workspace.")
            return {"CANCELLED"}
        self.report({"INFO"}, "BlendEngine workspace is ready.")
        return {"FINISHED"}


class BE_OT_create_playable_demo(Operator):
    bl_idname = "blendengine.create_playable_demo"
    bl_label = "New Neon Relay Demo"
    bl_description = "Create a separate playable Neon Relay scene and open the game editor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if runtime.ACTIVE_SESSION is not None:
            self.report({"WARNING"}, "Stop the current game before creating a new demo.")
            return {"CANCELLED"}
        from . import demo_game
        demo_game.create_demo(context)
        utils.activate_engine_page(context, "STUDIO")
        self.report({"INFO"}, "Neon Relay ready. Press Play; WASD moves, Space jumps.")
        return {"FINISHED"}


class BE_OT_toggle_fast_preview(Operator):
    bl_idname = "blendengine.toggle_fast_preview"
    bl_label = "Fast Preview"
    bl_description = "Use Workbench material colors, studio lighting and cavity for faster prototyping; toggle off to restore authored lighting"

    @classmethod
    def poll(cls, context):
        return context.screen is not None

    def execute(self, context):
        from . import editor
        enabled = editor.toggle_fast_preview(context)
        self.report({"INFO"}, "Fast Preview: studio lighting" if enabled else "Authored lighting restored")
        return {"FINISHED"}


class BE_OT_open_engine_page(Operator):
    bl_idname = "blendengine.open_page"
    bl_label = "Open BlendEngine Page"
    bl_description = "Switch to a clean game-engine page"
    bl_options = {"REGISTER", "UNDO"}

    page: EnumProperty(
        name="Page",
        items=(
            ("STUDIO", "Studio", "Dashboard, viewport, world, inspector, and assets"),
            ("WORLD", "World", "Scene building, terrain, lighting, physics, and AI"),
            ("LOGIC", "Logic", "No-code gameplay rules, visual scripting, and code preview"),
            ("PLAY", "Play Mode", "Dedicated test-run page"),
            ("BUILD", "Ship", "Build, export, optimization, and platform settings"),
        ),
        default="STUDIO",
    )

    def execute(self, context):
        utils.ensure_project_defaults(context.scene)
        workspace = utils.activate_engine_page(context, self.page)
        if workspace is None:
            self.report({"ERROR"}, "Could not open BlendEngine page.")
            return {"CANCELLED"}
        self.report({"INFO"}, "%s page is ready." % utils.ENGINE_PAGE_LABELS.get(workspace.name, workspace.name))
        return {"FINISHED"}


class BE_OT_open_play_mode_workspace(Operator):
    bl_idname = "blendengine.open_play_mode_workspace"
    bl_label = "Open Play Mode Page"
    bl_description = "Switch to a dedicated Play Mode page for testing the game"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        utils.ensure_project_defaults(context.scene)
        workspace = utils.activate_engine_page(context, "PLAY")
        if workspace is None:
            self.report({"ERROR"}, "Could not create the Play Mode page.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Play Mode page is ready.")
        return {"FINISHED"}


class BE_OT_generate_basic_template(Operator):
    bl_idname = "blendengine.generate_basic_template"
    bl_label = "Generate Basic Game Template"
    bl_description = "Create a player, camera, ground, light, input map, and starter BlendEngine data"
    bl_options = {"REGISTER", "UNDO"}

    clean_scene: BoolProperty(
        name="Clean Current Scene",
        default=True,
        description="Remove current scene objects before creating the starter template",
    )

    def execute(self, context):
        try:
            created = templates.generate_basic_game_template(context, clean_scene=self.clean_scene)
        except Exception as ex:
            self.report({"ERROR"}, "Template generation failed: %s" % ex)
            return {"CANCELLED"}
        self.report({"INFO"}, "Created starter template with player '%s'." % created["player"].name)
        return {"FINISHED"}


class BE_OT_generate_cyberpunk_shooter_template(Operator):
    bl_idname = "blendengine.generate_cyberpunk_shooter_template"
    bl_label = "Create Cyberpunk Shooter"
    bl_description = "Create a first-person cyberpunk zombie shooter from the models folder"
    bl_options = {"REGISTER", "UNDO"}

    clean_scene: BoolProperty(
        name="Clean Current Scene",
        default=True,
        description="Remove current scene objects before creating the cyberpunk shooter",
    )

    def execute(self, context):
        try:
            created = templates.generate_cyberpunk_shooter_template(context, clean_scene=self.clean_scene)
        except Exception as ex:
            self.report({"ERROR"}, "Cyberpunk shooter failed: %s" % ex)
            return {"CANCELLED"}
        self.report({"INFO"}, "Cyberpunk shooter ready with %d zombies." % created.get("zombie_count", 0))
        return {"FINISHED"}


class BE_OT_generate_2d_template(Operator):
    bl_idname = "blendengine.generate_2d_template"
    bl_label = "Create 2D Game"
    bl_description = "Create a simple 2D platform game with player, camera, platforms, and goal"
    bl_options = {"REGISTER", "UNDO"}

    clean_scene: BoolProperty(
        name="Clean Current Scene",
        default=True,
        description="Remove current scene objects before creating the 2D starter template",
    )

    def execute(self, context):
        try:
            created = templates.generate_2d_game_template(context, clean_scene=self.clean_scene)
        except Exception as ex:
            self.report({"ERROR"}, "2D template failed: %s" % ex)
            return {"CANCELLED"}
        self.report({"INFO"}, "Created 2D game with player '%s'." % created["player"].name)
        return {"FINISHED"}


class BE_OT_easy_create_game(Operator):
    bl_idname = "blendengine.easy_create_game"
    bl_label = "Magic Create Game"
    bl_description = "One-click beginner workflow: create a ready scene, controls, optimization, and build settings"
    bl_options = {"REGISTER", "UNDO"}

    template: EnumProperty(
        name="Template",
        items=properties.EASY_GAME_TEMPLATE_ITEMS,
        default="THREE_D_ADVENTURE",
    )
    target_platform: EnumProperty(
        name="Platform",
        items=properties.TARGET_PLATFORM_ITEMS,
        default="WINDOWS",
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=380)

    def execute(self, context):
        if self.template == "TWO_D_PLATFORMER":
            created = templates.generate_2d_game_template(context, clean_scene=True)
        elif self.template == "CYBERPUNK_SHOOTER":
            created = templates.generate_cyberpunk_shooter_template(context, clean_scene=True)
        else:
            created = templates.generate_basic_game_template(context, clean_scene=True)
            context.scene.blendengine_project.game_dimension = "THREE_D"

        optimization.platform_defaults(context.scene, self.target_platform)
        utils.activate_engine_page(context, "STUDIO")
        self.report({"INFO"}, "Game is ready: %s" % created["player"].name)
        return {"FINISHED"}


class BE_OT_apply_platform_profile(Operator):
    bl_idname = "blendengine.apply_platform_profile"
    bl_label = "Apply Platform Profile"
    bl_description = "Apply safe build and optimization defaults for the selected platform"
    bl_options = {"REGISTER", "UNDO"}

    platform: EnumProperty(
        name="Platform",
        items=properties.TARGET_PLATFORM_ITEMS,
        default="WINDOWS",
    )

    def execute(self, context):
        optimization.platform_defaults(context.scene, self.platform)
        self.report({"INFO"}, "Applied %s platform profile." % self.platform.title())
        return {"FINISHED"}


class BE_OT_add_component(Operator):
    bl_idname = "blendengine.add_component"
    bl_label = "Add Game Component"
    bl_description = "Add a BlendEngine component to the selected object"
    bl_options = {"REGISTER", "UNDO"}

    component_type: EnumProperty(
        name="Component",
        items=properties.COMPONENT_TYPE_ITEMS,
        default="TRANSFORM",
    )

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        utils.ensure_component(obj, self.component_type)
        self.report({"INFO"}, "Added %s to %s." % (utils.component_label(self.component_type), obj.name))
        return {"FINISHED"}


class BE_OT_add_player_controller(Operator):
    bl_idname = "blendengine.add_player_controller"
    bl_label = "Add Player Controller"
    bl_description = "Make the selected object a configurable player"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        components.add_player_controller(obj, camera=context.scene.camera)
        input_system.ensure_defaults(context.scene)
        self.report({"INFO"}, "Player Controller added to %s." % obj.name)
        return {"FINISHED"}


class BE_OT_add_collider(Operator):
    bl_idname = "blendengine.add_collider"
    bl_label = "Add Collider"
    bl_description = "Add a gameplay collider component to the selected object"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        components.add_collider(obj)
        self.report({"INFO"}, "Collider added to %s." % obj.name)
        return {"FINISHED"}


class BE_OT_add_rigidbody(Operator):
    bl_idname = "blendengine.add_rigidbody"
    bl_label = "Add Rigidbody"
    bl_description = "Add a gameplay rigidbody component and Blender rigid body data"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        try:
            components.add_rigidbody(context, obj)
        except Exception as ex:
            self.report({"ERROR"}, "Could not add rigidbody: %s" % ex)
            return {"CANCELLED"}
        self.report({"INFO"}, "Rigidbody added to %s." % obj.name)
        return {"FINISHED"}


class BE_OT_add_npc_behavior(Operator):
    bl_idname = "blendengine.add_npc_behavior"
    bl_label = "Add NPC Behavior"
    bl_description = "Add a beginner AI behavior template to the selected object"
    bl_options = {"REGISTER", "UNDO"}

    behavior_template: EnumProperty(
        name="Behavior",
        items=properties.AI_TEMPLATE_ITEMS,
        default="IDLE",
    )

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        player = utils.find_player_object(context.scene)
        ai_system.apply_template(obj, self.behavior_template, target=player)
        self.report({"INFO"}, "NPC Behavior added to %s." % obj.name)
        return {"FINISHED"}


class BE_OT_add_trigger_zone(Operator):
    bl_idname = "blendengine.add_trigger_zone"
    bl_label = "Add Trigger Zone"
    bl_description = "Make the selected object a gameplay trigger zone"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        components.add_trigger_zone(obj)
        self.report({"INFO"}, "Trigger Zone added to %s." % obj.name)
        return {"FINISHED"}


class BE_OT_add_health_component(Operator):
    bl_idname = "blendengine.add_health_component"
    bl_label = "Add Health Component"
    bl_description = "Add health settings to the selected object"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        components.add_health(obj)
        self.report({"INFO"}, "Health Component added to %s." % obj.name)
        return {"FINISHED"}


class BE_OT_add_game_behavior(Operator):
    bl_idname = "blendengine.add_game_behavior"
    bl_label = "Add Game Behavior"
    bl_description = "Add a no-code gameplay behavior to the selected object"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        settings = utils.mark_game_object(obj)
        behavior = settings.behaviors.add()
        behavior.name = "On Start Behavior"
        behavior.description = "Choose events, conditions, and actions without code."
        event = behavior.events.add()
        event.name = "On Start"
        event.event_type = "ON_START"
        action = behavior.actions.add()
        action.name = "Show Log"
        action.action_type = "SHOW_LOG"
        action.text_value = "Hello from BlendEngine."
        settings.active_behavior_index = len(settings.behaviors) - 1
        self.report({"INFO"}, "Game Behavior added to %s." % obj.name)
        return {"FINISHED"}


class BE_OT_remove_game_behavior(Operator):
    bl_idname = "blendengine.remove_game_behavior"
    bl_label = "Remove Game Behavior"
    bl_description = "Remove the selected no-code behavior"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        settings = obj.blendengine_object
        if not utils.remove_active_item(settings.behaviors, settings, "active_behavior_index"):
            self.report({"WARNING"}, "No behavior to remove.")
            return {"CANCELLED"}
        return {"FINISHED"}


class BE_OT_behavior_item_add(Operator):
    bl_idname = "blendengine.behavior_item_add"
    bl_label = "Add Behavior Item"
    bl_description = "Add an event, condition, or action to the selected behavior"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(
        name="Kind",
        items=(
            ("EVENT", "Event", "Add an event"),
            ("CONDITION", "Condition", "Add a condition"),
            ("ACTION", "Action", "Add an action"),
        ),
        default="ACTION",
    )

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        behavior = _active_behavior(obj)
        if self.kind == "EVENT":
            item = behavior.events.add()
            item.name = "On Start"
            item.event_type = "ON_START"
            behavior.active_event_index = len(behavior.events) - 1
        elif self.kind == "CONDITION":
            item = behavior.conditions.add()
            item.name = "Always"
            item.condition_type = "ALWAYS"
            behavior.active_condition_index = len(behavior.conditions) - 1
        else:
            item = behavior.actions.add()
            item.name = "Show Log"
            item.action_type = "SHOW_LOG"
            behavior.active_action_index = len(behavior.actions) - 1
        return {"FINISHED"}


class BE_OT_behavior_item_remove(Operator):
    bl_idname = "blendengine.behavior_item_remove"
    bl_label = "Remove Behavior Item"
    bl_description = "Remove the selected event, condition, or action"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(
        name="Kind",
        items=(
            ("EVENT", "Event", "Remove an event"),
            ("CONDITION", "Condition", "Remove a condition"),
            ("ACTION", "Action", "Remove an action"),
        ),
        default="ACTION",
    )

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        behavior = _active_behavior(obj)
        if self.kind == "EVENT":
            removed = utils.remove_active_item(behavior.events, behavior, "active_event_index")
        elif self.kind == "CONDITION":
            removed = utils.remove_active_item(behavior.conditions, behavior, "active_condition_index")
        else:
            removed = utils.remove_active_item(behavior.actions, behavior, "active_action_index")
        if not removed:
            self.report({"WARNING"}, "Nothing to remove.")
            return {"CANCELLED"}
        return {"FINISHED"}


class BE_OT_variable_add(Operator):
    bl_idname = "blendengine.variable_add"
    bl_label = "Add Game Variable"
    bl_description = "Add a game variable to the selected object"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        settings = utils.mark_game_object(obj)
        variable = settings.variables.add()
        variable.name = "NewVariable"
        settings.active_variable_index = len(settings.variables) - 1
        return {"FINISHED"}


class BE_OT_variable_remove(Operator):
    bl_idname = "blendengine.variable_remove"
    bl_label = "Remove Game Variable"
    bl_description = "Remove the selected game variable"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        settings = obj.blendengine_object
        if not utils.remove_active_item(settings.variables, settings, "active_variable_index"):
            self.report({"WARNING"}, "No variable to remove.")
            return {"CANCELLED"}
        return {"FINISHED"}


class BE_OT_input_defaults(Operator):
    bl_idname = "blendengine.input_defaults"
    bl_label = "Create Default Input Map"
    bl_description = "Create beginner default WASD, jump, interact, and mouse bindings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        input_system.ensure_defaults(context.scene)
        self.report({"INFO"}, "Default input map is ready.")
        return {"FINISHED"}


class BE_OT_input_binding_add(Operator):
    bl_idname = "blendengine.input_binding_add"
    bl_label = "Add Input Binding"
    bl_description = "Add a new input binding"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        input_system.add_binding(context.scene, action="CUSTOM", key="")
        return {"FINISHED"}


class BE_OT_input_binding_remove(Operator):
    bl_idname = "blendengine.input_binding_remove"
    bl_label = "Remove Input Binding"
    bl_description = "Remove the selected input binding"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not input_system.remove_active_binding(context.scene):
            self.report({"WARNING"}, "No input binding to remove.")
            return {"CANCELLED"}
        return {"FINISHED"}


class BE_OT_animation_state_add(Operator):
    bl_idname = "blendengine.animation_state_add"
    bl_label = "Add Animation State"
    bl_description = "Add an animation state to the selected object"
    bl_options = {"REGISTER", "UNDO"}

    state_type: EnumProperty(
        name="State",
        items=properties.ANIMATION_STATE_ITEMS,
        default="CUSTOM",
    )

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        name = self.state_type.replace("_", " ").title()
        animation_system.add_state(obj, name=name, state_type=self.state_type)
        return {"FINISHED"}


class BE_OT_animation_state_remove(Operator):
    bl_idname = "blendengine.animation_state_remove"
    bl_label = "Remove Animation State"
    bl_description = "Remove the selected animation state"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        if not animation_system.remove_active_state(obj):
            self.report({"WARNING"}, "No animation state to remove.")
            return {"CANCELLED"}
        return {"FINISHED"}


class BE_OT_animation_transition_add(Operator):
    bl_idname = "blendengine.animation_transition_add"
    bl_label = "Add Animation Transition"
    bl_description = "Add a no-code animation transition"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        controller = animation_system.ensure_controller(obj)
        from_state = controller.default_state or "Idle"
        to_state = "Walk" if from_state != "Walk" else "Idle"
        animation_system.add_transition(obj, from_state=from_state, to_state=to_state)
        return {"FINISHED"}


class BE_OT_animation_transition_remove(Operator):
    bl_idname = "blendengine.animation_transition_remove"
    bl_label = "Remove Animation Transition"
    bl_description = "Remove the selected animation transition"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _require_active_object(context, self)
        if obj is None:
            return {"CANCELLED"}
        if not animation_system.remove_active_transition(obj):
            self.report({"WARNING"}, "No animation transition to remove.")
            return {"CANCELLED"}
        return {"FINISHED"}


class BE_OT_test_run_scene(Operator):
    bl_idname = "blendengine.test_run_scene"
    bl_label = "Test Run Current Scene"
    bl_description = "Validate the current scene and start an interactive editor play session"
    bl_options = {"REGISTER"}

    _timer = None
    _session = None
    _last_tick = 0.0

    @classmethod
    def poll(cls, context):
        return context.window is not None and not context.scene.blendengine_project.test_running

    def execute(self, context):
        context.scene.blendengine_project.test_paused = False
        previous_workspace = context.window.workspace if context.window else None
        utils.activate_engine_page(context, "PLAY")
        self._session, result = runtime.start_test_run(context)
        if not result.ok and context.window and previous_workspace is not None:
            context.window.workspace = previous_workspace
        for message in result.all_messages():
            print("[BlendEngine] " + message)
        if not result.ok:
            self.report({"ERROR"}, result.errors[0])
            return {"CANCELLED"}

        self._timer = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)
        self._last_tick = time.perf_counter()
        context.window_manager.modal_handler_add(self)
        if result.warnings:
            self.report({"WARNING"}, result.summary())
        else:
            self.report({"INFO"}, "BlendEngine Test Run started.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC" and event.value == "PRESS":
            runtime.request_stop(context.scene)
            return {"RUNNING_MODAL"}

        if self._session is None:
            return self._finish(context, "Stopped")

        if event.type == "TIMER":
            if getattr(event, "timer", self._timer) != self._timer:
                return {"PASS_THROUGH"}
            now = time.perf_counter()
            dt = min(max(now - self._last_tick, 0.0), 0.1)
            self._last_tick = now
            if not context.scene.blendengine_project.test_paused:
                self._session.step(dt)
            if self._session.stop_requested or not context.scene.blendengine_project.test_running:
                return self._finish(context, "Stopped")
            return {"PASS_THROUGH"}

        if event.value in {"PRESS", "RELEASE"}:
            # Header and inspector clicks must reach Play/Pause/Stop controls.
            # Releases still reach the session after the pointer leaves Game.
            in_game = any(
                area.type == "VIEW_3D" and any(
                    region.type == "WINDOW" and
                    region.x <= event.mouse_x < region.x + region.width and
                    region.y <= event.mouse_y < region.y + region.height
                    for region in area.regions
                ) for area in context.screen.areas
            ) if context.screen else False
            if context.scene.blendengine_project.test_paused:
                return {"PASS_THROUGH"}
            if (in_game or event.value == "RELEASE") and self._session.handle_event(event):
                return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def _finish(self, context, status):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        runtime.finish_active_session(status)
        context.scene.blendengine_project.test_paused = False
        self._session = None
        return {"FINISHED"}


class BE_OT_stop_test_run(Operator):
    bl_idname = "blendengine.stop_test_run"
    bl_label = "Stop Test Run"
    bl_description = "Stop the interactive editor play session"
    bl_options = {"REGISTER"}

    def execute(self, context):
        runtime.request_stop(context.scene)
        self.report({"INFO"}, "BlendEngine Test Run stopped.")
        return {"FINISHED"}


class BE_OT_pause_test_run(Operator):
    bl_idname = "blendengine.pause_test_run"
    bl_label = "Pause / Resume Game"
    bl_description = "Pause simulation without leaving the Game view"

    @classmethod
    def poll(cls, context):
        return context.scene.blendengine_project.test_running

    def execute(self, context):
        project = context.scene.blendengine_project
        project.test_paused = not project.test_paused
        project.test_status = "Paused" if project.test_paused else "Running"
        if runtime.ACTIVE_SESSION is not None:
            runtime.ACTIVE_SESSION.input_state.clear()
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        return {"FINISHED"}


class BE_OT_step_test_run(Operator):
    bl_idname = "blendengine.step_test_run"
    bl_label = "Step Simulation"
    bl_description = "Advance a paused game by one 1/60 second simulation step"

    @classmethod
    def poll(cls, context):
        project = context.scene.blendengine_project
        return project.test_running and project.test_paused

    def execute(self, context):
        if runtime.ACTIVE_SESSION is not None:
            runtime.ACTIVE_SESSION.step(1.0 / 60.0)
        return {"FINISHED"}


class BE_OT_editor_input_lock(Operator):
    bl_idname = "blendengine.editor_input_lock"
    bl_label = "Game Input Lock"
    bl_description = "Keep gameplay keys from triggering Blender modeling shortcuts inside BlendEngine"
    bl_options = {"REGISTER"}

    _editor_events = {
        "W", "A", "S", "D", "Q", "E", "R", "F",
        "SPACE",
        "UP_ARROW", "DOWN_ARROW", "LEFT_ARROW", "RIGHT_ARROW",
    }

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.scene is not None

    def execute(self, context):
        editor = context.scene.blendengine_editor
        if editor.input_lock_running:
            self.report({"INFO"}, "BlendEngine input lock is already running.")
            return {"FINISHED"}
        editor.input_lock_enabled = True
        editor.input_lock_running = True
        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "BlendEngine game input lock enabled.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        scene = context.scene
        if scene is None or not hasattr(scene, "blendengine_editor"):
            return {"FINISHED"}

        editor = scene.blendengine_editor
        if not editor.input_lock_enabled:
            editor.input_lock_running = False
            return {"FINISHED"}

        if event.type == "TIMER":
            return {"PASS_THROUGH"}

        workspace_name = context.window.workspace.name if context.window and context.window.workspace else ""
        if workspace_name not in {"BlendEngine", "World Builder", "Logic Lab", "Play Mode"}:
            return {"PASS_THROUGH"}

        if scene.blendengine_project.test_running:
            return {"PASS_THROUGH"}

        if event.ctrl or event.oskey or event.alt:
            return {"PASS_THROUGH"}

        if event.value in {"PRESS", "RELEASE"} and event.type in self._editor_events:
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}


class BE_OT_disable_editor_input_lock(Operator):
    bl_idname = "blendengine.disable_editor_input_lock"
    bl_label = "Disable Game Input Lock"
    bl_description = "Allow Blender modeling shortcuts again"
    bl_options = {"REGISTER"}

    def execute(self, context):
        context.scene.blendengine_editor.input_lock_enabled = False
        context.scene.blendengine_editor.input_lock_running = False
        self.report({"INFO"}, "BlendEngine input lock disabled.")
        return {"FINISHED"}


class BE_OT_apply_optimization_preset(Operator):
    bl_idname = "blendengine.apply_optimization_preset"
    bl_label = "Apply Optimization Preset"
    bl_description = "Apply a beginner-friendly performance and visual quality preset"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(
        name="Preset",
        items=properties.OPTIMIZATION_PRESET_ITEMS,
        default="BALANCED",
    )

    def execute(self, context):
        preset = self.preset
        optimization.apply_preset(context.scene, preset)
        self.report({"INFO"}, "Applied %s optimization preset." % preset.replace("_", " ").title())
        return {"FINISHED"}


class BE_OT_analyze_scene_performance(Operator):
    bl_idname = "blendengine.analyze_scene_performance"
    bl_label = "Analyze Scene Performance"
    bl_description = "Estimate scene cost and compare it with the selected performance budget"
    bl_options = {"REGISTER"}

    def execute(self, context):
        result = performance.analyze_scene(context.scene, store_report=True)
        print("[BlendEngine] " + result["summary"])
        for item in result["messages"]:
            print("[BlendEngine] %s: %s" % (item["severity"], item["message"]))
            if item.get("suggested_fix"):
                print("[BlendEngine] Suggested Fix: %s" % item["suggested_fix"])
        if result["status"] == "CRITICAL":
            self.report({"WARNING"}, result["summary"])
        elif result["status"] == "WARNING":
            self.report({"WARNING"}, result["summary"])
        else:
            self.report({"INFO"}, result["summary"])
        return {"FINISHED"}


class BE_OT_generate_optimization_report(Operator):
    bl_idname = "blendengine.generate_optimization_report"
    bl_label = "Generate Optimization Report"
    bl_description = "Create a text report with performance estimates and suggested fixes"
    bl_options = {"REGISTER"}

    def execute(self, context):
        text = performance.report_as_text(context.scene)
        datablock = bpy.data.texts.get("BlendEngine Optimization Report")
        if datablock is None:
            datablock = bpy.data.texts.new("BlendEngine Optimization Report")
        datablock.clear()
        datablock.write(text)
        self.report({"INFO"}, "Optimization report written to Text Editor.")
        return {"FINISHED"}


class BE_OT_make_game_lighter(Operator):
    bl_idname = "blendengine.make_game_lighter"
    bl_label = "Make Game Lighter"
    bl_description = "Suggest safe ways to make the game run faster. Optional safe markers require confirmation"
    bl_options = {"REGISTER", "UNDO"}

    apply_safe_changes: BoolProperty(
        name="Apply Safe Markers",
        default=False,
        description="Apply non-destructive BlendEngine markers and the Low preset",
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, _context):
        layout = self.layout
        layout.label(text="No assets will be destructively changed.")
        layout.prop(self, "apply_safe_changes")
        layout.label(text="Suggestions will be written to a Text block.")

    def execute(self, context):
        suggestions = optimization.make_game_lighter_suggestions(context.scene)
        lines = [
            "BlendEngine Make Game Lighter",
            "Safe editor-side markers and quality settings for a lighter playable scene.",
            "",
        ]
        lines.extend("- " + item for item in suggestions)

        if self.apply_safe_changes:
            _profile, marked_static, lod_count = optimization.apply_safe_lightweight_flags(context.scene)
            lines.extend((
                "",
                "Applied safe markers:",
                "- Low optimization preset",
                "- Static candidates marked: %d" % marked_static,
                "- LOD placeholders marked: %d" % lod_count,
                "- Collider simplification and physics sleep markers added to mesh objects",
            ))

        datablock = bpy.data.texts.get("BlendEngine Make Game Lighter")
        if datablock is None:
            datablock = bpy.data.texts.new("BlendEngine Make Game Lighter")
        datablock.clear()
        datablock.write("\n".join(lines))
        performance.analyze_scene(context.scene, store_report=True)
        self.report({"INFO"}, "Make Game Lighter suggestions written to Text Editor.")
        return {"FINISHED"}


class BE_OT_optimize_for_one_gb(Operator):
    bl_idname = "blendengine.optimize_for_one_gb"
    bl_label = "Optimize For 1 GB RAM"
    bl_description = "Apply strict streaming, culling, LOD, physics, and quality limits for weak computers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _profile, marked_static, lod_count = optimization.apply_one_gb_runtime_plan(context.scene)
        performance.analyze_scene(context.scene, store_report=True)
        self.report(
            {"INFO"},
            "1 GB runtime plan applied: %d static, %d LOD markers." % (marked_static, lod_count),
        )
        return {"FINISHED"}


class BE_OT_add_lod_group(Operator):
    bl_idname = "blendengine.add_lod_group"
    bl_label = "Add LOD Group"
    bl_description = "Mark selected objects as needing level-of-detail variants"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = context.selected_objects or [utils.active_object(context)]
        count = 0
        for obj in objects:
            if obj and obj.type == "MESH":
                optimization.add_lod_group(obj)
                count += 1
        if count == 0:
            self.report({"ERROR"}, "Select at least one mesh object.")
            return {"CANCELLED"}
        self.report({"INFO"}, "LOD Group marker added to %d object(s)." % count)
        return {"FINISHED"}


class BE_OT_mark_static_object(Operator):
    bl_idname = "blendengine.mark_static_object"
    bl_label = "Mark Static Objects"
    bl_description = "Mark selected objects as static optimization candidates"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = context.selected_objects or [utils.active_object(context)]
        count = 0
        for obj in objects:
            if obj and obj.type == "MESH":
                optimization.mark_static_object(obj)
                count += 1
        if count == 0:
            self.report({"ERROR"}, "Select at least one mesh object.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Marked %d object(s) as static." % count)
        return {"FINISHED"}


class BE_OT_mark_instancing_candidate(Operator):
    bl_idname = "blendengine.mark_instancing_candidate"
    bl_label = "Mark Instancing Candidate"
    bl_description = "Mark selected objects as future instancing candidates"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = context.selected_objects or [utils.active_object(context)]
        count = 0
        for obj in objects:
            if obj and obj.type == "MESH":
                optimization.mark_instancing_candidate(obj)
                count += 1
        if count == 0:
            self.report({"ERROR"}, "Select at least one mesh object.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Marked %d object(s) as instancing candidates." % count)
        return {"FINISHED"}


class BE_OT_mark_baked_lighting_candidate(Operator):
    bl_idname = "blendengine.mark_baked_lighting_candidate"
    bl_label = "Mark Baked Lighting Candidate"
    bl_description = "Mark selected objects as baked lighting candidates"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = context.selected_objects or [utils.active_object(context)]
        count = 0
        for obj in objects:
            if obj:
                optimization.mark_baked_lighting_candidate(obj)
                count += 1
        if count == 0:
            self.report({"ERROR"}, "Select at least one object.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Marked %d object(s) for baked lighting." % count)
        return {"FINISHED"}


class BE_OT_generate_lod_placeholders(Operator):
    bl_idname = "blendengine.generate_lod_placeholders"
    bl_label = "Auto Generate LOD Placeholders"
    bl_description = "Mark complex meshes with LOD placeholders for build and runtime planning"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = optimization.generate_lod_placeholders(context.scene)
        self.report({"INFO"}, "LOD placeholders marked on %d object(s)." % count)
        return {"FINISHED"}


class BE_OT_prepare_build(Operator):
    bl_idname = "blendengine.prepare_build"
    bl_label = "Prepare Build Package"
    bl_description = "Validate and write a BlendEngine build package"
    bl_options = {"REGISTER"}

    def execute(self, context):
        result = runtime.validate_scene(context.scene)
        print("[BlendEngine] Build profile: " + export_system.build_profile_summary(context.scene))
        for message in result.all_messages():
            print("[BlendEngine] " + message)
        if result.errors:
            self.report({"ERROR"}, result.errors[0])
            return {"CANCELLED"}
        try:
            package = export_system.prepare_build_package(context)
        except Exception as ex:
            self.report({"ERROR"}, "Build package failed: %s" % ex)
            return {"CANCELLED"}
        self.report({"INFO"}, "Build package written to %s" % package["package_dir"])
        return {"FINISHED"}


classes = (
    BE_OT_create_workspace,
    BE_OT_create_playable_demo,
    BE_OT_toggle_fast_preview,
    BE_OT_open_engine_page,
    BE_OT_open_play_mode_workspace,
    BE_OT_generate_basic_template,
    BE_OT_generate_cyberpunk_shooter_template,
    BE_OT_generate_2d_template,
    BE_OT_easy_create_game,
    BE_OT_apply_platform_profile,
    BE_OT_add_component,
    BE_OT_add_player_controller,
    BE_OT_add_collider,
    BE_OT_add_rigidbody,
    BE_OT_add_npc_behavior,
    BE_OT_add_trigger_zone,
    BE_OT_add_health_component,
    BE_OT_add_game_behavior,
    BE_OT_remove_game_behavior,
    BE_OT_behavior_item_add,
    BE_OT_behavior_item_remove,
    BE_OT_variable_add,
    BE_OT_variable_remove,
    BE_OT_input_defaults,
    BE_OT_input_binding_add,
    BE_OT_input_binding_remove,
    BE_OT_animation_state_add,
    BE_OT_animation_state_remove,
    BE_OT_animation_transition_add,
    BE_OT_animation_transition_remove,
    BE_OT_test_run_scene,
    BE_OT_stop_test_run,
    BE_OT_pause_test_run,
    BE_OT_step_test_run,
    BE_OT_editor_input_lock,
    BE_OT_disable_editor_input_lock,
    BE_OT_apply_optimization_preset,
    BE_OT_analyze_scene_performance,
    BE_OT_generate_optimization_report,
    BE_OT_make_game_lighter,
    BE_OT_optimize_for_one_gb,
    BE_OT_add_lod_group,
    BE_OT_mark_static_object,
    BE_OT_mark_instancing_candidate,
    BE_OT_mark_baked_lighting_candidate,
    BE_OT_generate_lod_placeholders,
    BE_OT_prepare_build,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
