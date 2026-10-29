#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record real native BlendEngine editor gameplay with OS-level WASD input.

Requires a running X11 display, ffmpeg, and xdotool. The output is an unretimed
screen recording; its capture FPS is independent of measured game/viewport FPS.
Example::

    python3 tools/blendengine/record_editor_demo.py --display :92 \
        --blender /path/to/blender --scene /path/to/NeonRelay.blend \
        --output-dir /workspace/artifacts/blendengine-playable
"""

import argparse
from contextlib import suppress
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time
import uuid


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--display", default=":92")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--capture-fps", type=int, default=24)
    parser.add_argument("--xdotool", type=Path, default=None)
    parser.add_argument("--xdotool-library-dir", type=Path, default=None)
    parser.add_argument("--waypoints", type=Path, help="Optional JSON list of safe world-space XY waypoints")
    parser.add_argument("--startup-hold", type=float, default=6.0)
    parser.add_argument("--editor-hold", type=float, default=4.0)
    parser.add_argument("--win-hold", type=float, default=4.0)
    parser.add_argument("--route-timeout", type=float, default=120.0)
    parser.add_argument("--skip-pause-demo", action="store_true")
    parser.add_argument("--fast-preview", action="store_true",
                        help="Show Lit gameplay, then switch the real editor to Fast Preview before playing the route")
    parser.add_argument("--keep-open", action="store_true")
    return parser.parse_args()


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


class NativeRecording:
    def __init__(self, args):
        self.args = args
        self.repository = Path(__file__).resolve().parents[2]
        self.output = args.output_dir.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.control = self.output / "recording_control"
        self.control.mkdir(exist_ok=True)
        self.run_id = uuid.uuid4().hex
        self.sequence = 0
        self.started = time.monotonic()
        self.keys = set()
        self.samples = []
        self.events = []
        self.blender = None
        self.encoder = None
        self.capture_valid = False
        self.capture_wall_begin = None
        self.window_id = None
        self.output_handles = []
        self.environment = os.environ.copy()
        self.environment["DISPLAY"] = args.display
        self.xdo_environment = self.environment.copy()
        tool = args.xdotool or shutil.which("xdotool")
        fallback = Path("/workspace/scratch/display-tools/root/usr/bin/xdotool")
        self.xdotool = str(tool or (fallback if fallback.is_file() else "xdotool"))
        library = args.xdotool_library_dir
        if library is None and self.xdotool == str(fallback):
            library = fallback.parents[1] / "lib" / "x86_64-linux-gnu"
        if library:
            inherited = self.xdo_environment.get("LD_LIBRARY_PATH", "")
            self.xdo_environment["LD_LIBRARY_PATH"] = str(library) + (":" + inherited if inherited else "")
        self.history = (self.output / "recording_telemetry.jsonl").open("w", encoding="utf-8")

    def event(self, name, **data):
        record = {"event": name, "wall_seconds": time.monotonic() - self.started, **data}
        self.events.append(record)
        print(json.dumps(record), flush=True)

    def status(self):
        if self.blender is not None and self.blender.poll() is not None:
            raise RuntimeError("Native Blender exited unexpectedly; inspect recording_blender.log")
        path = self.control / "status.json"
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if status.get("run_id") != self.run_id:
            return None
        self.history.write(json.dumps(status) + "\n")
        self.history.flush()
        self.samples.append(status)
        if status.get("error"):
            raise RuntimeError("Blender recording bridge failed:\n" + status["error"])
        return status

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.status()
            time.sleep(min(0.15, max(0.0, deadline - time.monotonic())))

    def until(self, predicate, timeout, description):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.status()
            if status is not None and predicate(status):
                return status
            time.sleep(0.12)
        raise TimeoutError("Timed out waiting for " + description)

    def command(self, action, timeout=20.0, **values):
        self.sequence += 1
        command = {"id": self.sequence, "run_id": self.run_id, "action": action, **values}
        write_json(self.control / "command.json", command)
        status = self.until(lambda state: (state.get("last_command") or {}).get("id") == self.sequence,
                            timeout, "editor command " + action)
        result = status["last_command"]
        if result.get("error"):
            raise RuntimeError(result["error"])
        self.event("editor_command", action=action, result=result.get("result"))
        return status

    def xdo(self, *arguments):
        return subprocess.run([self.xdotool, *map(str, arguments)], env=self.xdo_environment,
                              check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=10.0).stdout.strip()

    def focus_viewport(self, status):
        areas = [area for area in status.get("areas", []) if area["type"] == "VIEW_3D"]
        if not areas:
            raise RuntimeError("No actual native 3D viewport was found")
        area = max(areas, key=lambda item: item["width"] * item["height"])
        region = next((region for region in area["regions"] if region["type"] == "WINDOW"), area)
        x = region["x"] + region["width"] // 2
        y = status["window"]["height"] - (region["y"] + region["height"] // 2)
        self.xdo("windowfocus", "--sync", self.window_id)
        self.xdo("mousemove", "--window", self.window_id, x, y)

    def set_keys(self, wanted):
        wanted = set(wanted)
        changed = wanted != self.keys
        for key in sorted(self.keys - wanted):
            self.xdo("keyup", key)
            self.keys.remove(key)
        for key in sorted(wanted - self.keys):
            self.xdo("keydown", key)
            self.keys.add(key)
        if changed:
            self.event("os_keys", keys=sorted(wanted))

    def launch(self):
        logfile = (self.output / "recording_blender.log").open("w", encoding="utf-8")
        self.output_handles.append(logfile)
        bootstrap = self.repository / "tools" / "blendengine" / "recording_bootstrap.py"
        command = [str(self.args.blender.resolve()), "--factory-startup", "-noaudio",
                   "--window-geometry", "0", "0", str(self.args.width), str(self.args.height),
                   "--python-exit-code", "1", "--python", str(bootstrap), "--",
                   "--repository", str(self.repository), "--scene", str(self.args.scene.resolve()),
                   "--control-dir", str(self.control), "--run-id", self.run_id]
        self.blender = subprocess.Popen(command, env=self.environment, stdout=logfile,
                                        stderr=subprocess.STDOUT)
        status = self.until(lambda state: state.get("ready"), 90.0, "native editor initialization")
        windows = self.xdo("search", "--onlyvisible", "--pid", self.blender.pid).splitlines()
        if not windows:
            raise RuntimeError("Blender's native X11 window was not found")
        def window_area(window):
            geometry = dict(line.split("=", 1) for line in
                            self.xdo("getwindowgeometry", "--shell", window).splitlines() if "=" in line)
            return int(geometry.get("WIDTH", 0)) * int(geometry.get("HEIGHT", 0))
        self.window_id = max(windows, key=window_area)
        self.focus_viewport(status)
        self.event("editor_ready", pid=self.blender.pid, window=self.window_id)
        self.wait(self.args.startup_hold)

    def start_capture(self):
        logfile = (self.output / "recording_ffmpeg.log").open("w", encoding="utf-8")
        self.output_handles.append(logfile)
        video = self.output / "NeonRelay-gameplay.mp4"
        command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-f", "x11grab",
                   "-framerate", str(self.args.capture_fps), "-video_size",
                   "%dx%d" % (self.args.width, self.args.height), "-draw_mouse", "1", "-i",
                   self.args.display + ".0+0,0", "-an", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "19", "-threads", "2", "-pix_fmt", "yuv420p", str(video)]
        self.encoder = subprocess.Popen(command, env=self.environment, stdin=subprocess.PIPE,
                                        stdout=logfile, stderr=subprocess.STDOUT)
        self.capture_wall_begin = time.monotonic() - self.started
        self.wait(0.75)
        if self.encoder.poll() is not None:
            raise RuntimeError("Screen capture failed; inspect recording_ffmpeg.log")
        self.event("capture_started", path=str(video), capture_fps=self.args.capture_fps,
                   note="Raw real-time X11 screen capture; no retiming")

    @staticmethod
    def waypoint_position(waypoint):
        if isinstance(waypoint, dict):
            return waypoint.get("position", waypoint.get("xy", waypoint.get("point")))
        return waypoint

    def route(self):
        state = self.command("play")
        state = self.until(lambda item: item.get("running") and item.get("session", {}).get("frame", 0) > 5,
                           30.0, "live native gameplay")
        self.focus_viewport(state)
        self.wait(2.0)
        state = self.status()
        self.focus_viewport(state)
        if self.args.fast_preview:
            self.command("fast_preview", enabled=True)
            self.wait(2.0)
            state = self.status()
            self.focus_viewport(state)
        if self.args.waypoints:
            waypoints = json.loads(self.args.waypoints.read_text(encoding="utf-8"))
        else:
            waypoints = state.get("recording_waypoints", [])
            if not waypoints:
                value = state.get("scene_metadata", {}).get("blendengine_demo_waypoints", [])
                waypoints = json.loads(value) if isinstance(value, str) else value
        if not waypoints:
            raise RuntimeError("The demo did not expose safe recording waypoints")
        route_started = time.monotonic()
        won_during_route = False
        for index, waypoint in enumerate(waypoints):
            position = self.waypoint_position(waypoint)
            if position is None or len(position) < 2:
                raise ValueError("Invalid waypoint: %r" % waypoint)
            target_x, target_y = map(float, position[:2])
            self.event("waypoint_started", index=index, target=[target_x, target_y])
            stagnant_since = time.monotonic()
            previous_position = None
            while True:
                if time.monotonic() - route_started > self.args.route_timeout:
                    raise TimeoutError("OS-input gameplay route exceeded its time limit")
                state = self.status()
                if not state or not state.get("running"):
                    raise RuntimeError("The native play session stopped during the route")
                if state.get("gameplay", {}).get("state") == "WON" or state.get("gameplay", {}).get("won") is True:
                    self.set_keys(set())
                    won_during_route = True
                    break
                actual = state.get("player", {}).get("position")
                if actual is None:
                    raise RuntimeError("The running game has no player position telemetry")
                dx, dy = target_x - actual[0], target_y - actual[1]
                if math.hypot(dx, dy) <= 0.38:
                    self.set_keys(set())
                    self.event("waypoint_reached", index=index, position=actual,
                               gameplay=state.get("gameplay"))
                    self.wait(0.45)
                    break
                keys = set()
                if abs(dx) > 0.22:
                    keys.add("d" if dx > 0.0 else "a")
                if abs(dy) > 0.22:
                    keys.add("w" if dy > 0.0 else "s")
                self.set_keys(keys)
                if previous_position is None or math.dist(actual[:2], previous_position[:2]) > 0.05:
                    stagnant_since = time.monotonic()
                    previous_position = actual
                elif time.monotonic() - stagnant_since > 12.0:
                    raise RuntimeError("Real OS-input movement stalled before waypoint %d" % index)
                time.sleep(0.12)
            if won_during_route:
                break
        self.set_keys(set())
        state = self.until(lambda item: item.get("gameplay", {}).get("state") == "WON" or
                           item.get("gameplay", {}).get("won") is True, 15.0, "visible game victory")
        self.event("game_won", gameplay=state.get("gameplay"), session=state.get("session"))
        self.wait(self.args.win_hold)
        if not self.args.skip_pause_demo:
            self.command("pause")
            self.wait(1.5)
            self.command("step")
            self.wait(0.8)
            self.command("resume")
            self.wait(1.5)
        if self.args.fast_preview:
            self.command("fast_preview", enabled=False)
        self.command("stop")
        self.until(lambda item: not item.get("running") and item.get("session") is None,
                   15.0, "native modal session cleanup and restored scene")
        self.command("layout", page="STUDIO")
        self.wait(2.5)
        self.command("save", filename="RecordedNeonRelay.blend")

    def finish_capture(self):
        if self.encoder is None:
            return
        if self.encoder.poll() is None:
            with suppress(BrokenPipeError, OSError):
                self.encoder.stdin.write(b"q\n")
                self.encoder.stdin.flush()
            try:
                self.encoder.wait(timeout=15.0)
            except subprocess.TimeoutExpired:
                self.encoder.terminate()
                self.encoder.wait(timeout=10.0)
        if self.encoder.returncode != 0:
            self.event("capture_warning", returncode=self.encoder.returncode)
        self.capture_valid = self.encoder.returncode == 0 and (self.output / "NeonRelay-gameplay.mp4").is_file()
        self.encoder = None

    def extract_stills(self):
        if not self.capture_valid:
            return
        timestamps = {"NeonRelay-editor.png": max(0.5, self.args.editor_hold / 2.0)}
        victory = next((event for event in self.events if event["event"] == "game_won"), None)
        if victory is not None:
            timestamps["NeonRelay-win.png"] = max(0.0, victory["wall_seconds"] -
                                                    self.capture_wall_begin + self.args.win_hold / 2.0)
        for name, seconds in timestamps.items():
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(seconds),
                            "-i", str(self.output / "NeonRelay-gameplay.mp4"), "-frames:v", "1",
                            "-threads", "1", str(self.output / name)], check=True, timeout=30.0)
        self.event("raw_video_stills_extracted", files=list(timestamps))

    def summary(self, success, error):
        unique = {}
        for sample in self.samples:
            if (sample.get("running") and not sample.get("paused") and
                    sample.get("session", {}).get("frame", 0) > 2 and
                    sample.get("gameplay", {}).get("state") == "RUNNING"):
                unique[(sample.get("preview_mode", "LIT"), sample["session"]["frame"])] = sample
        active = list(unique.values())

        def measured_metrics(samples):
            metrics = {}
            for key in ("fps", "viewport_fps", "logic_ms"):
                values = [sample["session"].get(key, 0.0) for sample in samples
                          if sample["session"].get(key, 0.0) > 0.0]
                if values:
                    metrics[key] = {"median": statistics.median(values), "minimum": min(values),
                                    "maximum": max(values), "samples": len(values)}
            return metrics

        metrics = measured_metrics(active)
        grouped = {mode: measured_metrics([sample for sample in active if sample.get("preview_mode", "LIT") == mode])
                   for mode in sorted({sample.get("preview_mode", "LIT") for sample in active})}
        victory = next((event for event in self.events if event["event"] == "game_won"), None)
        video_metadata = None
        if self.capture_valid:
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                    "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames:format=duration,size",
                                    "-of", "json", str(self.output / "NeonRelay-gameplay.mp4")],
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   check=True, timeout=15.0)
            video_metadata = json.loads(probe.stdout)
        result = {"success": success, "error": error, "run_id": self.run_id,
                  "game_won": victory is not None,
                  "victory_gameplay": victory.get("gameplay") if victory else None,
                  "video_metadata": video_metadata,
                  "capture_fps": self.args.capture_fps, "retimed": False,
                  "input_method": "X11 OS keyboard events using xdotool; actual runtime movement",
                  "recording": str(self.output / "NeonRelay-gameplay.mp4"),
                  "wall_seconds": time.monotonic() - self.started, "metrics": metrics,
                  "metrics_by_preview_mode": grouped,
                  "fast_preview_requested": self.args.fast_preview,
                  "metrics_notes": {"fps": "Measured simulation update cadence, not rendered frames",
                                    "viewport_fps": "Measured viewport redraw cadence",
                                    "logic_ms": "Measured CPU logic time per simulation update"},
                  "events": self.events}
        write_json(self.output / "recording_summary.json", result)
        return result

    def close(self):
        with suppress(Exception):
            self.set_keys(set())
        self.finish_capture()
        self.extract_stills()
        if self.blender is not None and not self.args.keep_open and self.blender.poll() is None:
            self.blender.terminate()
            try:
                self.blender.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                self.blender.kill()
                self.blender.wait(timeout=5.0)
        self.history.close()
        for handle in self.output_handles:
            handle.close()


def main():
    recording = NativeRecording(arguments())
    success, error = False, None
    try:
        recording.launch()
        recording.start_capture()
        recording.wait(recording.args.editor_hold)
        recording.route()
        success = True
    except Exception as exc:
        error = "%s: %s" % (type(exc).__name__, exc)
        recording.event("recording_failed", error=error)
    finally:
        recording.close()
        if success and not recording.capture_valid:
            success, error = False, "The native screen capture did not finish successfully"
        result = recording.summary(success, error)
        print(json.dumps(result, indent=2), flush=True)
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
