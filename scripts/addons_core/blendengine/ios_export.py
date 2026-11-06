# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare native iOS games and verify unsigned device IPA archives.

The editor can prepare a portable project on Linux/Windows. Building its real
Mach-O application requires macOS, Xcode and the matching Godot iOS template.
Only the Last Signal gameplay adapter is currently implemented.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import zipfile


SUPPORTED_ADAPTER = "LAST_SIGNAL"
DEFAULT_BUNDLE_ID = "org.blendengine.lastsignal"
NATIVE_RUNTIME = "Godot 4 native C++ / OpenGL ES 3 Compatibility"


class NativeIOSExportError(RuntimeError):
    """A native project or unsigned IPA is incomplete or unsupported."""


def require_supported_adapter(game_data):
    if game_data.get("native_adapter") != SUPPORTED_ADAPTER:
        raise NativeIOSExportError(
            "Native iOS export currently supports the LAST_SIGNAL gameplay adapter. "
            "This scene has no supported native adapter; Blender Python behaviors "
            "cannot be replaced with a browser player or automatically converted to iOS.")


def _metadata(bundle_identifier, version_name, version_code):
    if not isinstance(bundle_identifier, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z][A-Za-z0-9-]*)+", bundle_identifier):
        raise NativeIOSExportError("iOS bundle identifier must contain reverse-DNS labels.")
    if not isinstance(version_name, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", version_name):
        raise NativeIOSExportError("iOS version must be numeric, such as 1.1 or 1.1.0.")
    if type(version_code) is not int or version_code < 1:
        raise NativeIOSExportError("iOS build number must be a positive integer.")


def find_source_root(source_root=None):
    explicit = source_root or os.environ.get("BLENDENGINE_SOURCE_ROOT")
    candidates = [Path(explicit).expanduser().resolve()] if explicit else Path(__file__).resolve().parents
    for root in candidates:
        if ((root / "native/android_game/project.godot").is_file()
                and (root / "tools/ios/project.py").is_file()
                and (root / "tools/ios/build_ios.py").is_file()):
            return root
    raise NativeIOSExportError(
        "Native iOS SDK is missing. Native SDK Root (or BLENDENGINE_SOURCE_ROOT) "
        "must contain native/android_game and tools/ios/project.py + build_ios.py.")


def _ios_helper(path):
    spec = importlib.util.spec_from_file_location("blendengine_ios_project", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def prepare_native_project(package_dir, game_data, assets_dir, *, source_root=None,
                           template_dir=None, bundle_identifier=DEFAULT_BUNDLE_ID,
                           version_name="1.1", version_code=2):
    """Copy current-scene assets and native iOS tools without claiming an IPA."""
    require_supported_adapter(game_data)
    _metadata(bundle_identifier, version_name, version_code)
    root = find_source_root(source_root)
    template = Path(template_dir) if template_dir else root / "native/android_game"
    assets = Path(assets_dir)
    for name in ("project.godot", "main.tscn", "main.gd", "npc_agent.gd"):
        if not (template / name).is_file():
            raise NativeIOSExportError("Native iOS game template is missing " + name)
    for name in ("last_signal.glb", "story.json"):
        if not (assets / name).is_file() or not (assets / name).stat().st_size:
            raise NativeIOSExportError("Current-scene iOS asset export is missing " + name)
    with (assets / "last_signal.glb").open("rb") as stream:
        if stream.read(4) != b"glTF":
            raise NativeIOSExportError("Current-scene last_signal.glb is not a binary glTF asset.")
    try:
        story = json.loads((assets / "story.json").read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise NativeIOSExportError("Cannot read current-scene story.json: " + str(error)) from error
    if (not isinstance(story, dict) or story.get("adapter", story.get("native_adapter",
            story.get("story_id"))) != SUPPORTED_ADAPTER):
        raise NativeIOSExportError("Current-scene assets do not use the LAST_SIGNAL adapter.")

    helper = _ios_helper(root / "tools/ios/project.py")
    preset = helper.ios_preset(bundle_id=bundle_identifier, version=version_name, build=version_code)
    project = Path(package_dir) / "ios_project"
    if project.exists():
        shutil.rmtree(project)
    shutil.copytree(template, project, ignore=shutil.ignore_patterns(
        ".godot", ".git", ".blendengine-tools", "build", "*.import", "*.apk", "*.aab", "*.ipa",
        "*.p12", "*.p8", "*.mobileprovision", "*.keystore", "*.jks", "export_credentials.cfg",
        "last_signal.glb", "story.json", "native_color_*.png", "native_normal_*.png",
        "last_signal_native_color_*.png", "last_signal_native_normal_*.png"))
    shutil.copytree(assets, project / "assets", dirs_exist_ok=True)
    (project / "assets/game_data.json").write_text(json.dumps(game_data, indent=2) + "\n", encoding="utf-8")
    (project / "export_presets.cfg").write_text(preset, encoding="utf-8")
    tools = project / "tooling/ios"
    shutil.copytree(root / "tools/ios", tools, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    launcher = project / "build_ios_ipa.sh"
    launcher.write_text(
        '#!/usr/bin/env sh\nset -eu\nDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'exec python3 "$DIR/tooling/ios/build_ios.py" --project "$DIR" '
        '--output "$DIR/build/LastSignal-AI-unsigned.ipa" '
        '--bundle-id ' + bundle_identifier + ' --version ' + version_name +
        ' --build ' + str(version_code) + ' "$@"\n', encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | 0o111)
    (project / "README.md").write_text(
        "# Last Signal native iOS project\n\n"
        "The game uses Godot C++ and native OpenGL ES 3 rendering, with the current Blender "
        "scene's glTF assets and LAST_SIGNAL gameplay/NPC adapter.\n\n"
        "On macOS with Xcode, Godot 4.6.3 and its iOS export template installed, run "
        "`./build_ios_ipa.sh --godot /path/to/Godot`. Add `--qa` for the iOS Simulator "
        "checks. The included tooling/setup_toolchain.sh can install the matching "
        "Godot CLI and iOS template.\n\n"
        "The result is an unsigned device IPA. It requires Apple signing before "
        "installation on an ordinary physical iPhone. An exported project or successful "
        "ZIP check is not proof of device gameplay. No IPA is fabricated on Linux or "
        "Windows. General Blender Python behaviors are not automatically converted.\n",
        encoding="utf-8")
    return project


def _macho_device_arm64(data):
    """Read Mach-O headers/load commands; reject simulator and non-executable data."""
    if len(data) < 32:
        raise NativeIOSExportError("The app executable is not a complete Mach-O binary.")
    magic = data[:4]
    if magic in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        wide = magic[-1] == 0xbf
        count = struct.unpack_from(">I", data, 4)[0]
        stride = 32 if wide else 20
        if not 1 <= count <= 16 or 8 + count * stride > len(data):
            raise NativeIOSExportError("Invalid universal Mach-O architecture table.")
        arm64 = []
        for index in range(count):
            offset = 8 + index * stride
            cpu = struct.unpack_from(">I", data, offset)[0]
            start, size = struct.unpack_from(">QQ" if wide else ">II", data, offset + 8)
            if start + size > len(data) or size < 32:
                raise NativeIOSExportError("Invalid universal Mach-O slice bounds.")
            if cpu != 0x0100000c:
                raise NativeIOSExportError("Device IPA includes a non-ARM64 architecture.")
            arm64.extend(_macho_device_arm64(data[start:start + size]))
        return sorted(set(arm64))
    if magic != b"\xcf\xfa\xed\xfe":
        raise NativeIOSExportError("The app executable is not an ARM64 Mach-O binary.")
    _, cpu, _subtype, filetype, count, size, _flags, _reserved = struct.unpack_from("<8I", data)
    if cpu != 0x0100000c or filetype != 2:
        raise NativeIOSExportError("The app must contain an ARM64 Mach-O executable.")
    if not 1 <= count <= 4096 or size > len(data) - 32:
        raise NativeIOSExportError("Invalid Mach-O load-command bounds.")
    position, device = 32, False
    for _index in range(count):
        if position + 8 > 32 + size:
            raise NativeIOSExportError("Truncated Mach-O load command.")
        command, length = struct.unpack_from("<II", data, position)
        if length < 8 or position + length > 32 + size:
            raise NativeIOSExportError("Invalid Mach-O load command length.")
        if command == 0x32:
            if length < 24:
                raise NativeIOSExportError("Truncated Mach-O build-version command.")
            platform = struct.unpack_from("<I", data, position + 8)[0]
            if platform != 2:
                raise NativeIOSExportError("This Mach-O targets a simulator or another platform, not device iOS.")
            device = True
        elif command == 0x25:
            device = True
        elif command == 0x1d:
            raise NativeIOSExportError("Expected an unsigned IPA but the executable contains a code signature.")
        position += length
    if position != 32 + size:
        raise NativeIOSExportError("Mach-O command count does not match its declared bounds.")
    if not device:
        raise NativeIOSExportError("The executable has no iOS device platform declaration.")
    return ["arm64"]


def verify_unsigned_ipa(path):
    """Check a real unsigned device archive; simulator/phone execution is separate."""
    path = Path(path)
    if not path.is_file():
        raise NativeIOSExportError("The native iOS build did not create the requested IPA.")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise NativeIOSExportError("IPA contains duplicate ZIP entries.")
            if any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                   or "\\" in name for name in names):
                raise NativeIOSExportError("IPA contains an unsafe archive path.")
            roots = {"/".join(name.split("/")[:2]) + "/" for name in names
                     if name.startswith("Payload/") and len(name.split("/")) > 2
                     and name.split("/")[1].endswith(".app")}
            if len(roots) != 1:
                raise NativeIOSExportError("IPA must contain exactly one Payload/*.app application.")
            root = roots.pop()
            if root + "Info.plist" not in names:
                raise NativeIOSExportError("IPA application is missing Info.plist.")
            info = plistlib.loads(archive.read(root + "Info.plist"))
            executable = info.get("CFBundleExecutable")
            if (not isinstance(executable, str) or not executable or "/" in executable
                    or "\\" in executable or executable in {".", ".."}):
                raise NativeIOSExportError("Info.plist has no safe CFBundleExecutable filename.")
            bundle = info.get("CFBundleIdentifier")
            if (info.get("CFBundlePackageType") != "APPL" or not isinstance(bundle, str)
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z][A-Za-z0-9-]*)+", bundle)):
                raise NativeIOSExportError("Info.plist does not describe a native iOS application.")
            if (info.get("DTPlatformName", "iphoneos") != "iphoneos" or
                    info.get("CFBundleSupportedPlatforms", ["iPhoneOS"]) != ["iPhoneOS"]):
                raise NativeIOSExportError("Info.plist does not target physical iOS devices.")
            if root + executable not in names:
                raise NativeIOSExportError("IPA is missing its declared Mach-O executable.")
            data = archive.read(root + executable)
            architectures = _macho_device_arm64(data)
            if b"Godot" not in data:
                raise NativeIOSExportError("The native executable does not identify the Godot runtime.")
            packs = [name for name in names if name.startswith(root) and name.endswith(".pck")]
            pack_ok = any(archive.read(name)[:4] == b"GDPC" for name in packs)
            if not pack_ok and b"GDPC" not in data:
                raise NativeIOSExportError("IPA is missing its Godot game resource pack.")
            if any("/web_player/" in name.lower() or name.lower().endswith(
                    (".html", ".htm", ".js", ".mjs")) for name in names):
                raise NativeIOSExportError("IPA contains a browser game payload.")
            if any("/_CodeSignature/" in name or name.endswith("/embedded.mobileprovision") for name in names):
                raise NativeIOSExportError("Expected an unsigned IPA without signing or provisioning files.")
            if archive.testzip() is not None:
                raise NativeIOSExportError("IPA ZIP CRC validation failed.")
    except NativeIOSExportError:
        raise
    except (OSError, ValueError, KeyError, struct.error, zipfile.BadZipFile, plistlib.InvalidFileException) as error:
        raise NativeIOSExportError("Cannot validate native IPA: " + str(error)) from error
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"artifact": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest(),
            "runtime": NATIVE_RUNTIME, "bundle_identifier": info["CFBundleIdentifier"],
            "architectures": architectures, "ipa_structure_verified": True,
            "signed": False, "physical_device_installable": False,
            "simulator_runtime_tested": False, "physical_device_tested": False,
            "browser_payload": False}


def build_unsigned_ipa(project_dir, *, output=None, godot=None, qa=False,
                       bundle_identifier=DEFAULT_BUNDLE_ID, version_name="1.1", version_code=2):
    _metadata(bundle_identifier, version_name, version_code)
    if sys.platform != "darwin":
        raise NativeIOSExportError("Building an iOS IPA requires macOS and Xcode; this host can prepare the native project only.")
    if not shutil.which("xcodebuild"):
        raise NativeIOSExportError("Xcode command-line tools are missing (xcodebuild).")
    project = Path(project_dir).resolve()
    helper = project / "tooling/ios/build_ios.py"
    if not helper.is_file():
        raise NativeIOSExportError("The native iOS build helper is missing.")
    output = Path(output).resolve() if output else project / "build/LastSignal-AI-unsigned.ipa"
    if output.suffix.lower() != ".ipa":
        raise NativeIOSExportError("Native iOS output must use the .ipa extension.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    command = [sys.executable, str(helper), "--project", str(project), "--output", str(output),
               "--bundle-id", bundle_identifier, "--version", version_name, "--build", str(version_code)]
    if godot:
        command += ["--godot", str(godot)]
    if qa:
        command.append("--qa")
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NativeIOSExportError("Native iOS tool failed: " + str(error)) from error
    (output.parent / "ios_editor_build.log").write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise NativeIOSExportError("Native iOS build failed:\n" + "\n".join(result.stdout.splitlines()[-20:]))
    report = verify_unsigned_ipa(output)
    (output.parent / "ipa_editor_validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
