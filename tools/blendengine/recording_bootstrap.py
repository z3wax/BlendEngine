# SPDX-License-Identifier: GPL-2.0-or-later
"""Native Blender-side controls and observation for record_editor_demo.py.

The control file accepts named editor operations only. Gameplay movement comes
from operating-system keyboard events sent by the recorder, never this module.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback

import bpy


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def json_value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "variable_type"):
        field = {"BOOL": "bool_value", "INT": "int_value", "STRING": "string_value"}.get(
            value.variable_type, "float_value")
        return getattr(value, field)
    if hasattr(value, "to_dict"):
        return {key: json_value(item) for key, item in value.to_dict().items()}
    if hasattr(value, "to_list"):
        return [json_value(item) for item in value.to_list()]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(item) for item in value]
    return str(value)


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


class RecordingBridge:
    def __init__(self, args):
        self.args = args
        self.root = args.control_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.last_command_id = None
        self.last_command = None
        self.ready = False
        self.error = None
        self.started = time.monotonic()
        self.runtime = None
        self.utils = None

    def initialize(self):
        try:
            bpy.context.preferences.view.show_splash = False
            bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
            sys.path.insert(0, str(self.args.repository.resolve() / "scripts" / "addons_core"))
            import blendengine
            from blendengine import runtime, utils
            self.runtime, self.utils = runtime, utils
            blendengine.register()
            bpy.ops.wm.open_mainfile(filepath=str(self.args.scene.resolve()))
            bpy.app.timers.register(self.prepare_editor, first_interval=0.8)
        except Exception:
            self.error = traceback.format_exc()
            self.write_status()
            raise

    def prepare_editor(self):
        try:
            bpy.ops.blendengine.create_workspace()
            for window in bpy.context.window_manager.windows:
                window.scene = bpy.context.scene
            self.ready = True
            bpy.app.timers.register(self.tick, first_interval=0.2, persistent=True)
        except Exception:
            self.error = traceback.format_exc()
            self.write_status()
            raise
        self.write_status()
        return None

    def viewport_override(self):
        context = bpy.context
        area = max((area for area in context.screen.areas if area.type == "VIEW_3D"),
                   key=lambda item: item.width * item.height, default=None)
        if area is None:
            raise RuntimeError("The editor has no native 3D viewport")
        region = next((region for region in area.regions if region.type == "WINDOW"), None)
        return context.temp_override(window=context.window, area=area, region=region)

    def execute(self, command):
        action = command.get("action")
        project = bpy.context.scene.blendengine_project
        if action == "inspect":
            return "Observed current editor state"
        if action == "fast_preview":
            enabled = bool(command.get("enabled", True))
            if bool(bpy.context.screen.get("blendengine_fast_preview", False)) != enabled:
                bpy.ops.blendengine.toggle_fast_preview()
            return "Fast Preview" if bpy.context.screen.get("blendengine_fast_preview", False) else "Lit Preview"
        if action == "play":
            if project.test_running:
                return "Already running"
            with self.viewport_override():
                result = bpy.ops.blendengine.test_run_scene('INVOKE_DEFAULT')
            if 'CANCELLED' in result:
                raise RuntimeError("The native Play operator rejected the scene")
            return sorted(result)
        if action in {"pause", "resume"}:
            wanted = action == "pause"
            if project.test_running and project.test_paused != wanted:
                bpy.ops.blendengine.pause_test_run()
            return "Paused" if project.test_paused else "Running"
        if action == "step":
            return sorted(bpy.ops.blendengine.step_test_run())
        if action == "stop":
            return sorted(bpy.ops.blendengine.stop_test_run())
        if action == "layout":
            page = command.get("page", "STUDIO")
            if page not in {"STUDIO", "WORLD", "LOGIC", "PLAY", "BUILD"}:
                raise ValueError("Unsupported editor page")
            return sorted(bpy.ops.blendengine.open_page(page=page))
        if action == "save":
            # Captured files belong beside the recording; never overwrite the
            # source project or execute a filename supplied as Python code.
            destination = (self.root.parent / command.get("filename", "CapturedSession.blend")).resolve()
            destination.relative_to(self.root.parent)
            if destination.suffix != ".blend":
                raise ValueError("A saved native scene must use the .blend extension")
            return sorted(bpy.ops.wm.save_as_mainfile(filepath=str(destination), check_existing=False))
        if action == "quit":
            bpy.ops.wm.quit_blender('EXEC_DEFAULT')
            return "Quitting"
        raise ValueError("Unsupported recording action: %r" % action)

    def status(self):
        context = bpy.context
        scene = context.scene
        project = getattr(scene, "blendengine_project", None)
        session = self.runtime.ACTIVE_SESSION if self.runtime else None
        player = self.utils.find_player_object(scene) if self.utils else None
        state = {
            "run_id": self.args.run_id,
            "pid": os.getpid(),
            "ready": self.ready,
            "error": self.error,
            "bridge_elapsed": time.monotonic() - self.started,
            "timestamp": time.time(),
            "scene": scene.name,
            "workspace": context.window.workspace.name if context.window else None,
            "running": bool(project and project.test_running),
            "paused": bool(project and project.test_paused),
            "test_status": getattr(project, "test_status", ""),
            "last_command": self.last_command,
            "fast_preview": bool(context.screen and context.screen.get("blendengine_fast_preview", False)),
            "scene_metadata": {key: json_value(value) for key, value in scene.items()
                               if key.startswith(("blendengine", "neon", "relay"))},
            "areas": [],
        }
        if context.window:
            state["window"] = {"width": context.window.width, "height": context.window.height}
        for area in context.screen.areas if context.screen else ():
            state["areas"].append({
                "type": area.type, "x": area.x, "y": area.y, "width": area.width, "height": area.height,
                "regions": [{"type": region.type, "x": region.x, "y": region.y,
                             "width": region.width, "height": region.height} for region in area.regions],
            })
        views = [area for area in context.screen.areas if area.type == "VIEW_3D"] if context.screen else []
        if views:
            main = max(views, key=lambda area: area.width * area.height)
            state["viewport_shading"] = main.spaces.active.shading.type
            state["preview_mode"] = "FAST" if state["viewport_shading"] == "SOLID" else "LIT"
        if player is not None:
            controller = player.blendengine_object.player_controller
            state["player"] = {"name": player.name, "position": list(player.location),
                               "yaw": player.rotation_euler.z, "controller_type": controller.controller_type,
                               "walk_speed": controller.walk_speed}
        if session is not None:
            state["session"] = {name: json_value(getattr(session, name, None)) for name in (
                "elapsed", "frame", "fps", "frame_ms", "logic_ms", "viewport_fps", "stop_requested",
                "input_state", "_runtime_stats",
            )}
            state["session"]["logs"] = list(session.logs[-12:])
            gameplay = getattr(session, "_gameplay", None)
            if gameplay is not None:
                state["gameplay"] = {name: json_value(getattr(gameplay, name, None)) for name in (
                    "state", "score", "collected", "elapsed",
                )}
                health = getattr(gameplay, "health", None)
                if health is not None:
                    state["gameplay"]["health"] = getattr(health, "current_health", None)
        try:
            from blendengine import demo_game
            state["recording_waypoints"] = json_value(getattr(demo_game, "RECORDING_WAYPOINTS", []))
        except ImportError:
            state["recording_waypoints"] = []
        return state

    def write_status(self):
        atomic_json(self.root / "status.json", self.status())

    def tick(self):
        try:
            command_path = self.root / "command.json"
            if command_path.exists():
                command = json.loads(command_path.read_text(encoding="utf-8"))
                if command.get("run_id") == self.args.run_id and command.get("id") != self.last_command_id:
                    self.last_command_id = command.get("id")
                    try:
                        result = self.execute(command)
                        self.last_command = {"id": self.last_command_id, "action": command.get("action"),
                                             "result": json_value(result), "error": None}
                    except Exception:
                        self.last_command = {"id": self.last_command_id, "action": command.get("action"),
                                             "error": traceback.format_exc()}
            self.write_status()
        except Exception:
            self.error = traceback.format_exc()
            try:
                self.write_status()
            except Exception:
                traceback.print_exc()
        return 0.15


if __name__ == "__main__":
    bridge = RecordingBridge(arguments())
    bridge.initialize()
