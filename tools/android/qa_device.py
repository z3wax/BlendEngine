#!/usr/bin/env python3
"""Exercise the installed native APK on a rootable Android emulator.

This tests the actual APK, including its GLES renderer. It requires a booted
16:9 emulator (for example 1280x720 or 960x540); touch coordinates scale to its
logical display size. The smoke activity is started as root because Godot's
internal activity deliberately is not exported to other applications.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import zipfile

PACKAGE = "org.blendengine.lastsignal"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--sdk", type=Path, default=Path(os.environ.get("ANDROID_SDK_ROOT", "/workspace/scratch/android/sdk")))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--reuse-install", action="store_true", help="Reuse APK only after matching its installed SHA-256; retain shader cache")
    parser.add_argument("--emulator-audio-dummy", action="store_true", help="Work around the API24 emulator's broken goldfish audio HAL, keeping the APK unchanged")
    parser.add_argument("--expect-agents", type=int, default=0,
                        help="Require this many independently animated local NPCs in the actual APK")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    adb = [str(args.sdk / "platform-tools/adb"), "-s", args.serial]
    report = {"passed": False, "apk": str(args.apk), "sha256": hashlib.sha256(args.apk.read_bytes()).hexdigest(),
              "tested_device": args.serial, "physical_arm64_tested": False, "touch": {}}
    display_size = [1280, 720]

    def call(*words, timeout=90, check=True):
        result = subprocess.run(adb + list(words), capture_output=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(f"adb {words}: {result.stdout.decode(errors='replace')} {result.stderr.decode(errors='replace')}")
        return result.stdout

    def state():
        raw = call("exec-out", "run-as", PACKAGE, "cat", "files/qa_state.json", check=False)
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None

    def wait_state(predicate, limit=90):
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            value = state()
            if value and predicate(value):
                return value
            time.sleep(2)
        raise RuntimeError("Android state timeout: " + str(state()))

    def screenshot(name):
        (args.output / name).write_bytes(call("exec-out", "screencap", "-p"))

    def tap(x, y):
        call("shell", "input", "tap", str(round(x * display_size[0] / 1280)), str(round(y * display_size[1] / 720)))

    def hold(x, y, duration=3000):
        x, y = round(x * display_size[0] / 1280), round(y * display_size[1] / 720)
        call("shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration))

    def wait_event(event, limit=30):
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            log = call("logcat", "-d", "-v", "brief", "-s", "godot:I", "Godot:I", "*:S").decode(errors="replace")
            for line in reversed(log.splitlines()):
                if "LAST_SIGNAL_STATE " in line:
                    value = json.loads(line.split("LAST_SIGNAL_STATE ", 1)[1])
                    if value.get("event") == event:
                        return value
            time.sleep(1)
        raise RuntimeError("Touch did not produce native event: " + event)

    try:
        if call("shell", "getprop", "sys.boot_completed").strip() != b"1":
            raise RuntimeError("Android emulator has not finished booting")
        report["android_api"] = call("shell", "getprop", "ro.build.version.sdk").decode().strip()
        report["device_abi"] = call("shell", "getprop", "ro.product.cpu.abi").decode().strip()
        sizes = re.findall(r"(\d+)x(\d+)", call("shell", "wm", "size").decode())
        if sizes:
            display_size[:] = map(int, sizes[-1])
        report["display_size"] = display_size
        report["emulator_audio_service"] = call("shell", "getprop", "init.svc.audioserver").decode().strip()
        report["emulator_audio_override"] = "Dummy" if args.emulator_audio_dummy else None
        report["normal_launcher"] = not args.emulator_audio_dummy
        with zipfile.ZipFile(args.apk) as archive:
            names = archive.namelist()
            report["native_libraries"] = [x for x in names if x.endswith("libgodot_android.so")]
            report["licenses"] = [x for x in names if "assets/licenses/" in x]
            report["redundant_raw_atlases"] = [x for x in names if x.startswith(("assets/assets/native_color_", "assets/assets/native_normal_"))]
            assert len(report["native_libraries"]) == 2
            assert report["licenses"] and not report["redundant_raw_atlases"]
        subprocess.run([str(args.sdk / "build-tools/36.0.0/apksigner"), "verify", str(args.apk)], check=True, capture_output=True)
        report["signature_verified"] = True
        call("shell", "am", "force-stop", PACKAGE)
        if args.reuse_install:
            installed = call("shell", "pm", "path", PACKAGE).decode().strip().splitlines()[0].removeprefix("package:")
            installed_hash = hashlib.sha256(call("exec-out", "cat", installed, timeout=120)).hexdigest()
            assert installed_hash == report["sha256"], "Installed APK differs from the APK under test"
            report["installed_sha256"] = installed_hash
        else:
            print("Installing signed native APK", flush=True)
            call("install", "-r", str(args.apk), timeout=180)
            installed = call("shell", "pm", "path", PACKAGE).decode().strip().splitlines()[0].removeprefix("package:")
            report["installed_sha256"] = hashlib.sha256(call("exec-out", "cat", installed, timeout=120)).hexdigest()
            assert report["installed_sha256"] == report["sha256"], "Installed APK differs from the APK under test"
        call("shell", "am", "force-stop", PACKAGE)
        if args.reuse_install:
            call("shell", "run-as", PACKAGE, "rm", "-f", "files/qa_state.json", "files/last_signal_checkpoint.json", "files/last_signal_smoke_checkpoint.json")
        else:
            call("shell", "pm", "clear", PACKAGE)
        call("logcat", "-c")
        call("shell", "settings", "put", "system", "screen_off_timeout", "2147483647")
        call("shell", "settings", "put", "secure", "immersive_mode_confirmations", "confirmed")
        call("shell", "input", "keyevent", "82")
        if args.emulator_audio_dummy:
            call("shell", "su", "0", "am", "start", "-n", PACKAGE + "/com.godot.game.GodotApp", "--esa", "command_line_params", "--audio-driver,Dummy")
        else:
            call("shell", "am", "start", "-n", PACKAGE + "/com.godot.game.GodotAppLauncher")
        start = wait_state(lambda s: s["event"] == "playing" and s["floor"], limit=300)
        if args.expect_agents:
            agents = start.get("npc_agents", [])
            assert len(agents) == args.expect_agents
            assert all(agent["skeleton_bones"] == 11 for agent in agents)
            observed = wait_state(lambda s: len(s.get("npc_agents", [])) == args.expect_agents
                and all(agent["walked"] > .2 and agent.get("walk_pose_changes", 0) > 0
                        for agent in s["npc_agents"]), limit=180)
            assert observed["clues"] == 0, "NPCs must not collect story clues for the player"
            report["feature"] = "AGENTS"
            report["expected_npc_count"] = args.expect_agents
            report["autonomous_npc"] = {"before": start["npc_agents"],
                                        "after": observed["npc_agents"],
                                        "player_clues_unchanged": True}
        screenshot("android-start.png")
        print("Native GLES scene started; testing real touch controls", flush=True)
        recording = subprocess.Popen(adb + ["shell", "screenrecord", "--time-limit", "30", "/sdcard/lastsignal-qa.mp4"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        hold(139, 514, 8000)
        moved = wait_state(lambda s: s["walked"] > .1)
        assert moved["position"][2] < start["position"][2] - .1
        report["touch"]["direction_pad"] = {"before": start, "after": moved}
        tap(1189, 635)
        jumped = wait_state(lambda s: s["jumps"] > 0)
        report["touch"]["quick_tap_jump"] = jumped
        tap(1156, 537)
        inspected = wait_event("inspect")
        report["touch"]["inspect"] = inspected
        tap(1185, 50)
        paused = wait_state(lambda s: s["paused"])
        hold(139, 514)
        assert state()["position"] == paused["position"]
        report["touch"]["pause_freezes_movement"] = True
        screenshot("android-paused.png")
        tap(640, 392)
        wait_state(lambda s: not s["paused"])
        call("shell", "input", "keyevent", "4")
        wait_state(lambda s: s["paused"])
        assert call("shell", "pidof", PACKAGE).strip(), "Android Back closed the native app"
        report["touch"]["android_back_pauses"] = True
        tap(640, 462)
        restarted = wait_state(lambda s: not s["paused"] and s["clues"] == 0 and abs(s["position"][2] - 10) < .1, limit=12)
        assert restarted["clues"] == 0 and restarted["state"] == "RUNNING"
        report["touch"]["restart"] = restarted
        screenshot("android-playable.png")
        recording.wait(timeout=40)
        call("pull", "/sdcard/lastsignal-qa.mp4", str(args.output / "android-touch.mp4"))

        print("Testing full native physics/story route in the same APK", flush=True)
        call("shell", "am", "force-stop", PACKAGE)
        call("logcat", "-c")
        root_id = call("shell", "su", "0", "id").decode()
        if "uid=0" not in root_id:
            raise RuntimeError("Full route automation requires a rootable emulator")
        smoke_args = "--audio-driver,Dummy,--,--smoke-test" if args.emulator_audio_dummy else "--,--smoke-test"
        call("shell", "su", "0", "am", "start", "-n", PACKAGE + "/com.godot.game.GodotApp", "--esa", "command_line_params", smoke_args)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            log = call("logcat", "-d", "-v", "brief", "-s", "godot:I", "Godot:I", "AndroidRuntime:E", "*:S").decode(errors="replace")
            (args.output / "android-smoke.log").write_text(log)
            if "LAST_SIGNAL_SMOKE_FAIL" in log or "FATAL EXCEPTION" in log or "SCRIPT ERROR" in log:
                raise RuntimeError("Native Android smoke reported an error; see android-smoke.log")
            if "LAST_SIGNAL_SMOKE_PASS" in log:
                final = state()
                assert final["state"] == "WON" and final["clues"] == 5 and final["floor"]
                if args.expect_agents:
                    agents = final.get("npc_agents", [])
                    assert len(agents) == args.expect_agents
                    assert all(agent["walked"] > 1 and agent["state"] == "IDLE"
                               and agent.get("walk_pose_changes", 0) > 0 for agent in agents)
                    report["npc_mission"] = agents
                report["native_smoke"] = final
                report["passed"] = True
                print("ANDROID_APK_QA_PASS", flush=True)
                break
            value = state()
            print("Android route:", value, flush=True)
            time.sleep(10)
        else:
            raise RuntimeError("Native Android full route timed out")
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        (args.output / "device_report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
