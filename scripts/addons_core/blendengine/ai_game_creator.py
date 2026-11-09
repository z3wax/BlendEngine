# SPDX-License-Identifier: GPL-2.0-or-later
#
# AI Game Creator: preferences, operators, and the sidebar panel.
#
# Flow: the creator types an idea -> a worker thread asks Claude (or the
# offline planner) for a game spec -> a timer on Blender's main thread builds
# the spec into the scene. Blender stays responsive while Claude thinks.

import importlib
import json
import os
import subprocess
import sys
import threading
import traceback

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup

from . import ai_game_builder, ai_game_planner as planner, ai_game_spec as spec_lib
from . import optimization, utils


ADDON_ID = __package__

PROVIDER_ITEMS = (
    ("AUTO", "Auto", "Design with Claude when an API key is set up, otherwise use the offline planner"),
    ("CLAUDE", "Claude", "Always design with Claude (needs internet and an Anthropic API key)"),
    ("OFFLINE", "Offline", "Keyword planner that works without internet or an API key"),
)

EFFORT_ITEMS = (
    ("low", "Fast", "Quickest designs"),
    ("medium", "Balanced", "Good designs at a moderate wait (default)"),
    ("high", "Thorough", "Most considered designs; slower"),
)

EXAMPLE_PROMPTS = (
    ("O'rmon", "O'rmonda 12 ta tanga yig'adigan, bo'rilardan qochadigan 3D sarguzasht o'yin"),
    ("Neon FPS", "First-person zombie shooter in a neon city at night. Defeat every zombie."),
    ("2D Qor", "2D platformer in a snowy world: collect 15 stars, avoid ice spikes, reach the portal"),
    ("Kosmos", "Kosmosda 90 soniya omon qolish: o'zga sayyoraliklar, lazer to'siqlari va boss"),
)

_JOB = None
_SDK_STATUS = {"installing": False, "message": ""}


# ---------------------------------------------------------------------------
# Preferences and scene data.
# ---------------------------------------------------------------------------

class BE_AIGameCreatorPreferences(AddonPreferences):
    bl_idname = ADDON_ID

    api_key: StringProperty(
        name="Anthropic API Key",
        subtype="PASSWORD",
        default="",
        description="Key from platform.claude.com. Stored in your Blender preferences, never in .blend files. "
                    "Leave empty to use the ANTHROPIC_API_KEY environment variable",
    )
    model: StringProperty(
        name="Model",
        default=planner.DEFAULT_MODEL,
        description="Claude model that designs the games",
    )
    effort: EnumProperty(
        name="Design Effort",
        items=EFFORT_ITEMS,
        default=planner.DEFAULT_EFFORT,
        description="How long Claude may think about each design",
    )

    def draw(self, _context):
        layout = self.layout
        layout.label(text="AI Game Creator", icon="SHADERFX")
        layout.prop(self, "api_key")
        row = layout.row()
        row.prop(self, "model")
        row.prop(self, "effort")
        box = layout.box()
        if planner.sdk_available():
            box.label(text="Anthropic SDK installed.", icon="CHECKMARK")
        elif _SDK_STATUS["installing"]:
            box.label(text="Installing the Anthropic SDK...", icon="TIME")
        else:
            box.label(text="The Anthropic SDK is not installed in Blender's Python.", icon="ERROR")
            box.operator("blendengine.ai_install_sdk", icon="IMPORT")
        if _SDK_STATUS["message"]:
            box.label(text=_SDK_STATUS["message"])
        col = layout.column(align=True)
        col.label(text="Your game idea and the current game spec are sent to Anthropic when Claude designs a game.", icon="INFO")
        col.label(text="Without a key, the offline planner builds games from keywords (Uzbek, English, Russian).")


class BE_AIGameCreatorSettings(PropertyGroup):
    prompt: StringProperty(
        name="Game Idea",
        default="",
        description="Describe the game in any language: world, hero, enemies, what to collect, how to win",
    )
    refine_prompt: StringProperty(
        name="Change",
        default="",
        description="Describe what to change, e.g. 'more enemies, make it night, add a boss'",
    )
    provider: EnumProperty(name="Designer", items=PROVIDER_ITEMS, default="AUTO")
    replace_scene: BoolProperty(
        name="Replace Scene",
        default=True,
        description="Remove the current scene objects before building the new game",
    )
    busy: BoolProperty(name="Busy", default=False)
    status: StringProperty(name="Status", default="")
    status_icon: StringProperty(name="Status Icon", default="INFO")
    last_source: StringProperty(name="Designed By", default="")
    last_prompt: StringProperty(name="Last Idea", default="")
    last_spec_json: StringProperty(name="Spec", default="")
    games_created: IntProperty(name="Games Created", default=0, min=0)
    chat_json: StringProperty(name="Chat", default="[]", description="AI Studio conversation (JSON)")
    chat_input: StringProperty(
        name="Message",
        default="",
        description="Describe a new game, or what to change in the current one",
    )
    chat_mode: EnumProperty(
        name="Send As",
        items=(
            ("CHANGE", "Change current game", "Edit the game on the right"),
            ("NEW", "New game", "Design a new game from scratch"),
        ),
        default="CHANGE",
    )


def addon_preferences(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_ID)
    return getattr(addon, "preferences", None) if addon is not None else None


def _claude_settings(context):
    prefs = addon_preferences(context)
    if prefs is None:
        return "", planner.DEFAULT_MODEL, planner.DEFAULT_EFFORT
    return prefs.api_key.strip(), (prefs.model.strip() or planner.DEFAULT_MODEL), prefs.effort


def designer_status(context):
    """(text, icon) describing which designer will run."""
    settings = context.scene.blendengine_ai
    api_key, model, _effort = _claude_settings(context)
    if settings.provider == "OFFLINE":
        return "Offline planner", "UNLINKED"
    if not planner.sdk_available():
        if settings.provider == "CLAUDE":
            return "Install the Anthropic SDK (Preferences > Add-ons > BlendEngine)", "ERROR"
        return "Offline planner (Claude SDK not installed)", "UNLINKED"
    if not planner.credentials_available(api_key):
        if settings.provider == "CLAUDE":
            return "Add an Anthropic API key in the add-on preferences", "ERROR"
        return "Offline planner (no Claude API key)", "UNLINKED"
    return "Claude · %s" % model, "LINKED"


def _stored_spec(scene):
    settings = scene.blendengine_ai
    if settings.last_spec_json:
        try:
            spec, _ = spec_lib.normalize_spec(json.loads(settings.last_spec_json))
            return spec
        except ValueError:
            pass
    return ai_game_builder.load_stored_spec()


MAX_CHAT_MESSAGES = 80


def chat_messages(scene):
    try:
        messages = json.loads(scene.blendengine_ai.chat_json or "[]")
    except ValueError:
        messages = []
    return messages if isinstance(messages, list) else []


def record_chat(scene, role, text, **data):
    """Append a message to the AI Studio conversation (user, assistant, error)."""
    messages = chat_messages(scene)
    entry = {"role": role, "text": str(text)[:1200]}
    entry.update(data)
    messages.append(entry)
    scene.blendengine_ai.chat_json = json.dumps(messages[-MAX_CHAT_MESSAGES:], ensure_ascii=False)


def _set_status(scene, text, icon="INFO"):
    settings = scene.blendengine_ai
    settings.status = text[:500]
    settings.status_icon = icon


def _tag_redraw():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in {"VIEW_3D", "PROPERTIES"}:
                area.tag_redraw()


# ---------------------------------------------------------------------------
# Applying a plan on the main thread.
# ---------------------------------------------------------------------------

def ensure_can_build(scene):
    """Raise PlannerError when replacing the scene now would be unsafe."""
    if scene.blendengine_project.test_running:
        raise planner.PlannerError("Stop the running game before building a new one.")
    if getattr(bpy.context, "mode", "OBJECT") != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass
        if getattr(bpy.context, "mode", "OBJECT") != "OBJECT":
            raise planner.PlannerError("Switch to Object Mode before building a game.")


def _studio_show_new_game(window):
    """Keep the AI Studio open and point its game panel at the new camera."""
    from . import ai_studio

    for area in utils.studio_view_areas(window.screen)[1:]:
        if window.scene.camera is not None:
            area.spaces.active.region_3d.view_perspective = "CAMERA"
            ai_studio._fit_camera(window, area)


def apply_plan(context, scene, plan, prompt, replace_scene=True):
    """Build ``plan.spec`` into ``scene`` and record it in the AI settings."""
    ensure_can_build(scene)
    settings = scene.blendengine_ai
    platform = scene.blendengine_project.target_platform
    result = ai_game_builder.build_game(scene, plan.spec, clean_scene=replace_scene)
    optimization.platform_defaults(scene, platform)
    spec = result["spec"]
    settings.last_spec_json = json.dumps(spec, ensure_ascii=False)
    settings.last_source = plan.source
    settings.last_prompt = prompt[:1000]
    settings.games_created += 1
    warnings = list(plan.warnings) + list(result["warnings"])
    designer = "Claude" if plan.source == "claude" else "offline planner"
    message = "Built '%s' with the %s: %d objects." % (spec["title"], designer, result["object_count"])
    if warnings:
        message += " Note: " + warnings[0]
    _set_status(scene, message, "ERROR" if warnings and plan.source == "offline" and settings.provider != "OFFLINE" else "CHECKMARK")
    # The offline planner uses the idea itself as the tagline; don't echo
    # the user's own words back in the chat.
    said = {str(m.get("text", "")).strip().casefold() for m in chat_messages(scene) if m.get("role") == "user"}
    said.add(str(prompt).strip().casefold())
    tagline = spec["tagline"] if spec["tagline"].strip().casefold() not in said else ""
    record_chat(scene, "assistant", tagline, title=spec["title"], facts=spec_lib.summarize(spec),
                notes=spec.get("design_notes", [])[:3], source=plan.source, objects=result["object_count"],
                warning=warnings[0] if warnings else "")
    for warning in warnings:
        print("[BlendEngine AI] " + warning)
    print("[BlendEngine AI] " + message)
    try:
        window = getattr(context, "window", None) if context is not None else None
        if window is not None and getattr(window.workspace, "name", "") != utils.STUDIO_WORKSPACE:
            utils.activate_engine_page(context, "STUDIO")
        for candidate in getattr(bpy.context.window_manager, "windows", ()):
            if getattr(candidate.workspace, "name", "") == utils.STUDIO_WORKSPACE:
                _studio_show_new_game(candidate)
    except Exception:
        pass
    try:
        bpy.ops.ed.undo_push(message="AI Create Game")
    except Exception:
        pass
    return result


class _PlanJob:
    def __init__(self, scene_name, prompt, kwargs, replace_scene):
        self.scene_name = scene_name
        self.prompt = prompt
        self.kwargs = kwargs
        self.replace_scene = replace_scene
        self.result = None
        self.error = None
        self.done = False
        self.cancelled = False

    def run(self):
        try:
            self.result = planner.generate_spec(self.prompt, **self.kwargs)
        except planner.PlannerError as ex:
            self.error = str(ex)
        except Exception as ex:  # Never let a worker thread die silently.
            traceback.print_exc()
            self.error = "Unexpected error while designing: %s" % ex
        finally:
            self.done = True


def _poll_job():
    global _JOB
    job = _JOB
    if job is None:
        return None
    if not job.done:
        _tag_redraw()
        return 0.25
    _JOB = None
    scene = bpy.data.scenes.get(job.scene_name)
    if scene is None:
        return None
    settings = scene.blendengine_ai
    settings.busy = False
    if job.cancelled:
        _set_status(scene, "Cancelled.", "CANCEL")
    elif job.error:
        _set_status(scene, job.error, "ERROR")
        record_chat(scene, "error", job.error)
    else:
        try:
            apply_plan(bpy.context, scene, job.result, job.prompt, replace_scene=job.replace_scene)
        except planner.PlannerError as ex:
            _set_status(scene, str(ex), "ERROR")
            record_chat(scene, "error", str(ex))
        except Exception as ex:
            traceback.print_exc()
            _set_status(scene, "Building the game failed: %s" % ex, "ERROR")
    _tag_redraw()
    return None


def start_design(context, prompt, base_spec=None, replace_scene=True):
    """Plan in the background (or synchronously in background mode)."""
    global _JOB
    scene = context.scene
    settings = scene.blendengine_ai
    ensure_can_build(scene)
    record_chat(scene, "user", prompt, kind="change" if base_spec is not None else "create")
    api_key, model, effort = _claude_settings(context)
    kwargs = {
        "provider": settings.provider,
        "api_key": api_key,
        "model": model,
        "effort": effort,
        "base_spec": base_spec,
        "platform": scene.blendengine_project.target_platform,
    }
    if bpy.app.background:
        plan = planner.generate_spec(prompt, **kwargs)
        return apply_plan(context, scene, plan, prompt, replace_scene=replace_scene)

    job = _PlanJob(scene.name, prompt, kwargs, replace_scene)
    _JOB = job
    settings.busy = True
    label, _icon = designer_status(context)
    _set_status(scene, "Designing with %s..." % label.split(" (")[0], "TIME")
    threading.Thread(target=job.run, name="BlendEngineAIDesign", daemon=True).start()
    if not bpy.app.timers.is_registered(_poll_job):
        bpy.app.timers.register(_poll_job, first_interval=0.25)
    return None


# ---------------------------------------------------------------------------
# Operators.
# ---------------------------------------------------------------------------

class BE_OT_ai_generate_game(Operator):
    bl_idname = "blendengine.ai_generate_game"
    bl_label = "AI Create Game"
    bl_description = "Describe a game in plain words and let AI build a playable level with rules, enemies, and a goal"
    bl_options = {"REGISTER"}

    prompt: StringProperty(name="Game Idea", default="", options={"SKIP_SAVE"})
    replace_scene: BoolProperty(name="Replace Current Scene", default=True)

    def invoke(self, context, _event):
        settings = context.scene.blendengine_ai
        if not self.prompt:
            self.prompt = settings.prompt
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Describe your game (any language):", icon="SHADERFX")
        layout.prop(self, "prompt", text="")
        label, icon = designer_status(context)
        layout.label(text="Designer: " + label, icon=icon)
        layout.prop(self, "replace_scene")

    def execute(self, context):
        if _JOB is not None:
            self.report({"WARNING"}, "AI is still designing the previous game.")
            return {"CANCELLED"}
        prompt = (self.prompt or context.scene.blendengine_ai.prompt).strip()
        if not prompt:
            self.report({"ERROR"}, "Describe the game you want first.")
            return {"CANCELLED"}
        context.scene.blendengine_ai.prompt = prompt
        context.scene.blendengine_ai.replace_scene = self.replace_scene
        try:
            result = start_design(context, prompt, replace_scene=self.replace_scene)
        except planner.PlannerError as ex:
            _set_status(context.scene, str(ex), "ERROR")
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        if result is not None:
            self.report({"INFO"}, context.scene.blendengine_ai.status)
        else:
            self.report({"INFO"}, "Designing your game...")
        return {"FINISHED"}


class BE_OT_ai_refine_game(Operator):
    bl_idname = "blendengine.ai_refine_game"
    bl_label = "Apply Change"
    bl_description = "Ask AI to change the current game, e.g. 'more enemies, night time, add a boss'"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.blendengine_ai
        if _JOB is not None:
            self.report({"WARNING"}, "AI is still designing the previous game.")
            return {"CANCELLED"}
        change = settings.refine_prompt.strip()
        if not change:
            self.report({"ERROR"}, "Describe what to change first.")
            return {"CANCELLED"}
        base = _stored_spec(context.scene)
        if base is None:
            self.report({"ERROR"}, "Create a game with AI first.")
            return {"CANCELLED"}
        try:
            start_design(context, change, base_spec=base, replace_scene=True)
        except planner.PlannerError as ex:
            _set_status(context.scene, str(ex), "ERROR")
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        settings.refine_prompt = ""
        return {"FINISHED"}


class BE_OT_ai_variation(Operator):
    bl_idname = "blendengine.ai_variation"
    bl_label = "New Layout"
    bl_description = "Rebuild the same game design with a different random layout (no AI call)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        spec = _stored_spec(context.scene)
        if spec is None:
            self.report({"ERROR"}, "Create a game with AI first.")
            return {"CANCELLED"}
        spec["seed"] = planner.random_seed()
        plan = planner.PlanResult(spec, context.scene.blendengine_ai.last_source or "offline")
        try:
            apply_plan(context, context.scene, plan, context.scene.blendengine_ai.last_prompt)
        except planner.PlannerError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        self.report({"INFO"}, "New layout for '%s'." % spec["title"])
        return {"FINISHED"}


class BE_OT_ai_rebuild_from_spec(Operator):
    bl_idname = "blendengine.ai_rebuild_from_spec"
    bl_label = "Rebuild From Spec Text"
    bl_description = "Rebuild the game from the '%s' text block after editing it by hand" % ai_game_builder.SPEC_TEXT_NAME
    bl_options = {"REGISTER"}

    def execute(self, context):
        text = bpy.data.texts.get(ai_game_builder.SPEC_TEXT_NAME)
        if text is None:
            self.report({"ERROR"}, "No AI game spec text found. Create a game with AI first.")
            return {"CANCELLED"}
        try:
            raw = json.loads(text.as_string())
        except ValueError as ex:
            self.report({"ERROR"}, "The spec text is not valid JSON: %s" % ex)
            return {"CANCELLED"}
        spec, warnings = spec_lib.normalize_spec(raw)
        plan = planner.PlanResult(spec, "manual", warnings)
        try:
            apply_plan(context, context.scene, plan, context.scene.blendengine_ai.last_prompt)
        except planner.PlannerError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        self.report({"INFO"}, context.scene.blendengine_ai.status)
        return {"FINISHED"}


class BE_OT_ai_show_spec(Operator):
    bl_idname = "blendengine.ai_show_spec"
    bl_label = "Show Game Spec"
    bl_description = "Open the generated game spec (JSON) in a Text Editor"
    bl_options = {"REGISTER"}

    def execute(self, context):
        text = bpy.data.texts.get(ai_game_builder.SPEC_TEXT_NAME)
        if text is None:
            self.report({"ERROR"}, "Create a game with AI first.")
            return {"CANCELLED"}
        screen = getattr(context, "screen", None)
        areas = list(screen.areas) if screen is not None else []
        target = next((area for area in areas if area.type == "TEXT_EDITOR"), None)
        if target is None:
            target = next((area for area in areas if area.type in {"OUTLINER", "PROPERTIES", "CONSOLE"}), None)
            if target is not None:
                target.type = "TEXT_EDITOR"
        if target is None:
            self.report({"INFO"}, "Open a Text Editor and pick '%s'." % text.name)
            return {"FINISHED"}
        target.spaces.active.text = text
        return {"FINISHED"}


class BE_OT_ai_use_example(Operator):
    bl_idname = "blendengine.ai_use_example"
    bl_label = "Use Example Idea"
    bl_description = "Fill the game idea with an example"
    bl_options = {"REGISTER", "INTERNAL"}

    index: IntProperty(default=0, min=0, max=len(EXAMPLE_PROMPTS) - 1)

    def execute(self, context):
        context.scene.blendengine_ai.prompt = EXAMPLE_PROMPTS[self.index][1]
        return {"FINISHED"}


class BE_OT_ai_cancel(Operator):
    bl_idname = "blendengine.ai_cancel"
    bl_label = "Cancel"
    bl_description = "Stop waiting for the current design; its result will be discarded"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        global _JOB
        if _JOB is not None:
            # The request cannot be interrupted; its result is simply dropped.
            _JOB.cancelled = True
            _JOB = None
        context.scene.blendengine_ai.busy = False
        _set_status(context.scene, "Cancelled.", "CANCEL")
        return {"FINISHED"}


def _sdk_target_dir():
    return bpy.utils.user_resource("SCRIPTS", path="modules", create=True)


def _install_sdk(target):
    try:
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True, timeout=600)
        process = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--target", target, "anthropic"],
            capture_output=True, text=True, timeout=1200)
        if process.returncode != 0:
            tail = (process.stderr or process.stdout or "").strip().splitlines()[-1:]
            _SDK_STATUS["message"] = "Install failed: %s" % (tail[0] if tail else "pip error")
        else:
            _SDK_STATUS["message"] = "Installed. Claude is ready."
    except Exception as ex:
        _SDK_STATUS["message"] = "Install failed: %s" % ex
    finally:
        if target not in sys.path:
            sys.path.append(target)
        importlib.invalidate_caches()
        planner.sdk_available(refresh=True)
        _SDK_STATUS["installing"] = False


def _poll_sdk_install():
    _tag_redraw()
    return 0.5 if _SDK_STATUS["installing"] else None


class BE_OT_ai_install_sdk(Operator):
    bl_idname = "blendengine.ai_install_sdk"
    bl_label = "Install Claude SDK"
    bl_description = "Download the official Anthropic Python SDK into Blender's user modules folder with pip"
    bl_options = {"REGISTER"}

    def execute(self, _context):
        if _SDK_STATUS["installing"]:
            return {"CANCELLED"}
        target = _sdk_target_dir()
        _SDK_STATUS.update({"installing": True, "message": "Installing into %s ..." % target})
        threading.Thread(target=_install_sdk, args=(target,), name="BlendEngineSDKInstall", daemon=True).start()
        bpy.app.timers.register(_poll_sdk_install, first_interval=0.5)
        self.report({"INFO"}, "Installing the Anthropic SDK in the background...")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# UI.
# ---------------------------------------------------------------------------

def draw_ai_creator(layout, context, compact=False):
    scene = context.scene
    settings = scene.blendengine_ai
    project = scene.blendengine_project

    col = layout.column(align=True)
    col.label(text="Describe your game:", icon="SHADERFX")
    col.prop(settings, "prompt", text="")
    if not compact:
        row = col.row(align=True)
        for index, (label, _text) in enumerate(EXAMPLE_PROMPTS):
            op = row.operator("blendengine.ai_use_example", text=label)
            op.index = index

    row = layout.row(align=True)
    row.prop(settings, "provider", expand=True)
    if not compact:
        layout.prop(project, "target_platform", text="Platform")
    label, icon = designer_status(context)
    layout.label(text=label, icon=icon)

    if settings.busy:
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.label(text="Designing your game...", icon="TIME")
        row.operator("blendengine.ai_cancel", text="", icon="CANCEL")
    else:
        row = layout.row(align=True)
        row.scale_y = 1.6
        row.operator_context = "EXEC_DEFAULT"
        op = row.operator("blendengine.ai_generate_game", text="Create Game with AI", icon="SHADERFX")
        op.prompt = settings.prompt
        op.replace_scene = settings.replace_scene
    if not compact:
        layout.prop(settings, "replace_scene")

    if settings.status:
        box = layout.box()
        for index, line in enumerate(_wrap(settings.status, 52)[:4]):
            box.label(text=line, icon=settings.status_icon if index == 0 else "BLANK1")

    spec = _stored_spec(scene) if settings.last_spec_json else None
    if spec is None:
        return
    box = layout.box()
    box.label(text=spec["title"], icon="FILE_3D")
    for line in _wrap(spec["tagline"], 52)[:2]:
        box.label(text=line)
    for line in spec_lib.summarize(spec):
        box.label(text=line, icon="DOT")
    if not compact:
        for note in spec.get("design_notes", [])[:3]:
            for index, line in enumerate(_wrap(note, 52)[:3]):
                box.label(text=line, icon="LIGHT" if index == 0 else "BLANK1")

    row = layout.row(align=True)
    row.scale_y = 1.3
    if project.test_running:
        row.operator("blendengine.stop_test_run", text="Stop", icon="PAUSE")
    else:
        row.operator("blendengine.test_run_scene", text="Play", icon="PLAY")
    row.operator("blendengine.ai_variation", text="New Layout", icon="FILE_REFRESH")
    row.operator("blendengine.ai_show_spec", text="Spec", icon="TEXT")

    col = layout.column(align=True)
    col.label(text="Change something:", icon="MODIFIER")
    row = col.row(align=True)
    row.prop(settings, "refine_prompt", text="")
    row.operator("blendengine.ai_refine_game", text="", icon="PLAY")
    if not compact:
        layout.operator("blendengine.ai_rebuild_from_spec", icon="FILE_REFRESH")
        layout.operator("blendengine.prepare_build", text="Build Game Package", icon="EXPORT")


def _wrap(text, width):
    words = (text or "").split()
    lines, current = [], ""
    for word in words:
        if current and len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    return lines


class VIEW3D_PT_blendengine_ai_creator(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendEngine"
    bl_label = "AI Game Creator"

    def draw(self, context):
        draw_ai_creator(self.layout, context)


classes = (
    BE_AIGameCreatorPreferences,
    BE_AIGameCreatorSettings,
    BE_OT_ai_generate_game,
    BE_OT_ai_refine_game,
    BE_OT_ai_variation,
    BE_OT_ai_rebuild_from_spec,
    BE_OT_ai_show_spec,
    BE_OT_ai_use_example,
    BE_OT_ai_cancel,
    BE_OT_ai_install_sdk,
    VIEW3D_PT_blendengine_ai_creator,
)


def _add_user_modules_to_path():
    try:
        path = bpy.utils.user_resource("SCRIPTS", path="modules")
    except Exception:
        return
    if path and os.path.isdir(path) and path not in sys.path:
        sys.path.append(path)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blendengine_ai = bpy.props.PointerProperty(type=BE_AIGameCreatorSettings)
    _add_user_modules_to_path()


def unregister():
    global _JOB
    if _JOB is not None:
        _JOB.cancelled = True
        _JOB = None
    if bpy.app.timers.is_registered(_poll_job):
        bpy.app.timers.unregister(_poll_job)
    del bpy.types.Scene.blendengine_ai
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
