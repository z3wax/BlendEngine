# SPDX-License-Identifier: GPL-2.0-or-later
"""Build native Android games with Godot's C++/OpenGL runtime.

This module intentionally has no Blender dependency, so the generated native
project can rebuild its APK with Python and a local Godot/Android toolchain.
Only the Last Signal gameplay adapter is implemented at present. Exporting an
unimplemented game must fail instead of silently replacing its gameplay.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


SUPPORTED_ADAPTER = "LAST_SIGNAL"
DEFAULT_PACKAGE_ID = "org.blendengine.lastsignal"
NATIVE_RUNTIME = "Godot 4 native C++ / OpenGL ES 3 Compatibility"


class NativeAndroidExportError(RuntimeError):
    """The native project or its build toolchain is incomplete."""


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def find_source_root(source_root=None):
    """Find source assets in either a checkout or a lean editor distribution."""
    explicit_root = source_root or os.environ.get("BLENDENGINE_SOURCE_ROOT")
    if explicit_root:
        root = Path(explicit_root).expanduser().resolve()
        if ((root / "native/android_game/project.godot").is_file()
                and (root / "tools/blendengine/export_native_assets.py").is_file()):
            return root
        raise NativeAndroidExportError(
            "Native SDK Root (or BLENDENGINE_SOURCE_ROOT) must point to an extracted BlendEngine SDK containing "
            "native/android_game and tools/blendengine/export_native_assets.py."
        )
    for parent in Path(__file__).resolve().parents:
        if (parent / "native/android_game/project.godot").is_file():
            return parent
    raise NativeAndroidExportError(
        "Native Android template is missing. Install a BlendEngine distribution "
        "containing native/android_game and tools/blendengine/export_native_assets.py. "
        "If the addon is installed separately, set BLENDENGINE_SOURCE_ROOT to that SDK directory."
    )


def require_supported_adapter(game_data):
    adapter = game_data.get("native_adapter", "")
    if adapter != SUPPORTED_ADAPTER:
        raise NativeAndroidExportError(
            "Native Android gameplay currently supports the LAST_SIGNAL story adapter. "
            "This scene has no supported native adapter; its Blender Python behaviors "
            "cannot be exported as a playable Android game."
        )
    return adapter


def export_preset(package_id=DEFAULT_PACKAGE_ID, version_name="1.0", version_code=1):
    if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", package_id):
        raise NativeAndroidExportError("Android package ID must contain lowercase Java package names separated by dots.")
    if not isinstance(version_code, int) or isinstance(version_code, bool) or version_code < 1:
        raise NativeAndroidExportError("Android version code must be a positive integer.")
    # json.dumps also quotes/escapes strings correctly for Godot ConfigFile.
    return '''[preset.0]
name="Android"
platform="Android"
runnable=true
advanced_options=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter="assets/*.json,assets/licenses/*.txt"
exclude_filter=".blendengine-tools/*,tooling/*,build/*,*.md,build_android_apk.py,build_android_apk.sh,assets/native_color_*.png,assets/native_normal_*.png"
export_path="build/LastSignal-debug.apk"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false
script_export_mode=2

[preset.0.options]
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build=false
gradle_build/export_format=0
gradle_build/min_sdk=""
gradle_build/target_sdk=""
architectures/armeabi-v7a=false
architectures/arm64-v8a=true
architectures/x86=false
architectures/x86_64=true
version/code=%s
version/name=%s
package/unique_name=%s
package/name="Last Signal"
package/signed=true
package/app_category=0
package/retain_data_on_uninstall=false
package/exclude_from_recents=false
package/show_in_android_tv=false
package/show_in_app_library=true
package/show_as_launcher_app=false
launcher_icons/main_192x192=""
launcher_icons/adaptive_foreground_432x432=""
launcher_icons/adaptive_background_432x432=""
launcher_icons/adaptive_monochrome_432x432=""
graphics/opengl_debug=false
screen/immersive_mode=true
screen/support_small=true
screen/support_normal=true
screen/support_large=true
screen/support_xlarge=true
user_data_backup/allow=false
command_line/extra_args="--audio-driver Dummy"
permissions/internet=false
permissions/access_network_state=false
''' % (version_code, json.dumps(str(version_name)), json.dumps(package_id))


def prepare_native_project(package_dir, game_data, assets_dir, *, template_dir=None,
                           package_id=DEFAULT_PACKAGE_ID, version_name="1.0", version_code=1):
    """Copy the real native runtime and the current scene's exported assets."""
    require_supported_adapter(game_data)
    preset = export_preset(package_id, version_name, version_code)
    template_dir = Path(template_dir) if template_dir else find_source_root() / "native/android_game"
    assets_dir = Path(assets_dir)
    for relative in ("project.godot", "main.tscn", "main.gd"):
        if not (template_dir / relative).is_file():
            raise NativeAndroidExportError("Native Android template is incomplete: missing " + relative)
    for relative in ("last_signal.glb", "story.json"):
        if not (assets_dir / relative).is_file() or (assets_dir / relative).stat().st_size == 0:
            raise NativeAndroidExportError("Current-scene native asset export is missing " + relative)
    with (assets_dir / "last_signal.glb").open("rb") as handle:
        if handle.read(4) != b"glTF":
            raise NativeAndroidExportError("Current-scene last_signal.glb is not a binary glTF asset.")
    try:
        story = json.loads((assets_dir / "story.json").read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise NativeAndroidExportError("Native story.json cannot be read: " + str(error)) from error
    # Do not allow a stale build for a different adapter to impersonate this scene.
    if not isinstance(story, dict):
        raise NativeAndroidExportError("Native story.json must contain an object.")
    adapter = story.get("adapter", story.get("story_id", story.get("native_adapter", "")))
    if adapter and adapter != SUPPORTED_ADAPTER:
        raise NativeAndroidExportError("Exported story assets do not use the LAST_SIGNAL adapter.")

    project_dir = Path(package_dir) / "android_project"
    if project_dir.exists():
        # This path is generated output. Remove stale browser scaffolds, imported
        # resources and old APKs rather than mixing incompatible runtime packages.
        shutil.rmtree(project_dir)
    shutil.copytree(template_dir, project_dir, ignore=shutil.ignore_patterns(
        ".godot", ".git", ".blendengine-tools", "build", "*.import", "*.apk", "*.aab",
        "last_signal.glb", "story.json", "native_color_*.png", "native_normal_*.png"))
    shutil.copytree(assets_dir, project_dir / "assets", dirs_exist_ok=True)
    _write_json(project_dir / "assets/game_data.json", game_data)
    (project_dir / "export_presets.cfg").write_text(preset, encoding="utf-8")
    (project_dir / "tooling").mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), project_dir / "tooling/android_export.py")
    (project_dir / "build_android_apk.py").write_text(
        "#!/usr/bin/env python3\nfrom pathlib import Path\nimport sys\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent / 'tooling'))\n"
        "from android_export import main\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main(['--project', str(Path(__file__).resolve().parent)] + sys.argv[1:]))\n",
        encoding="utf-8")
    launcher = project_dir / "build_android_apk.sh"
    launcher.write_text(
        '#!/usr/bin/env sh\nset -eu\nDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'exec python3 "$DIR/build_android_apk.py" "$@"\n', encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | 0o111)
    (project_dir / "README.md").write_text(
        "# Last Signal native Android project\n\n"
        "This is a Godot 4 C++ / OpenGL ES 3 game with the current Blender scene's "
        "glTF geometry, rig and materials, plus the Last Signal gameplay adapter.\n\n"
        "Run `python3 build_android_apk.py --godot /path/to/godot --sdk /path/to/android-sdk "
        "--java /path/to/jdk`. Godot 4.6.3 Android export templates, an Android SDK "
        "with platform/build tools, and a Java JDK are required. Environment variables "
        "GODOT_BIN, ANDROID_SDK_ROOT (or ANDROID_HOME), and JAVA_HOME also work.\n\n"
        "The script imports assets, exports a signed development APK, and checks its "
        "native libraries and payload. It reports build errors and does not substitute "
        "an APK. Device/emulator gameplay testing is a separate step; inspect "
        "build/apk_validation.json for the exact checks performed.\n\n"
        "Only the LAST_SIGNAL gameplay adapter is implemented. General Blender Python "
        "behaviors are not converted to Godot. Development signing is for testing; "
        "configure your own release signing for store distribution.\n", encoding="utf-8")
    return project_dir


def _command(command, *, env=None, log_path=None, timeout=900):
    try:
        result = subprocess.run([str(part) for part in command], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NativeAndroidExportError("Native Android tool failed: " + str(error)) from error
    if log_path:
        Path(log_path).write_text(result.stdout, encoding="utf-8")
    if result.returncode or re.search(r"^(?:SCRIPT )?ERROR:", result.stdout, re.MULTILINE):
        tail = "\n".join(result.stdout.splitlines()[-20:])
        raise NativeAndroidExportError("Native Android tool failed (exit %d):\n%s" % (result.returncode, tail))
    return result.stdout


def _existing_directory(value, description):
    path = Path(value).expanduser() if value else None
    if path is None or not path.is_dir():
        raise NativeAndroidExportError(description)
    return path.resolve()


def _toolchain(project_dir, godot=None, sdk=None, java=None):
    godot = godot or os.environ.get("GODOT_BIN") or shutil.which("godot") or shutil.which("godot4")
    if not godot or not (shutil.which(str(godot)) or Path(godot).is_file()):
        raise NativeAndroidExportError("Godot 4 is missing. Set the Godot executable or GODOT_BIN.")
    version = _command([godot, "--version"], timeout=30).strip()
    match = re.match(r"4\.(\d+)(?:\.\d+)?\.", version)
    if not match or int(match.group(1)) < 6:
        raise NativeAndroidExportError("Native Android export requires Godot 4.6 or newer with matching Android templates; found " + version)
    sdk = sdk or os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if not sdk:
        candidates = (Path.home() / "Android/Sdk", Path.home() / ".cache/blendengine/android/sdk")
        sdk = next((str(path) for path in candidates if path.is_dir()), None)
    sdk = _existing_directory(sdk, "Android SDK is missing. Set Android SDK Path or ANDROID_SDK_ROOT.")
    if not (sdk / "platform-tools").is_dir() or not (sdk / "build-tools").is_dir():
        raise NativeAndroidExportError("Android SDK needs platform-tools and build-tools: " + str(sdk))
    java = java or os.environ.get("JAVA_HOME")
    if not java:
        javac = shutil.which("javac")
        java = str(Path(javac).resolve().parent.parent) if javac else None
    java = _existing_directory(java, "Java JDK is missing. Set JAVA_HOME or the Java SDK path.")
    keytool = java / "bin" / ("keytool.exe" if os.name == "nt" else "keytool")
    if not keytool.is_file():
        raise NativeAndroidExportError("Java JDK is missing bin/keytool: " + str(java))

    tools_dir = project_dir / ".blendengine-tools"
    config_dir = tools_dir / "config/godot"
    config_dir.mkdir(parents=True, exist_ok=True)
    keystore = tools_dir / "debug.keystore"
    if not keystore.is_file():
        _command([keytool, "-genkeypair", "-keystore", keystore, "-storepass", "android",
                  "-alias", "androiddebugkey", "-keypass", "android", "-dname",
                  "CN=Android Debug,O=Android,C=US", "-keyalg", "RSA", "-keysize", "2048",
                  "-validity", "10000", "-noprompt"], timeout=60)
    settings = {
        "export/android/android_sdk_path": str(sdk),
        "export/android/java_sdk_path": str(java),
        "export/android/debug_keystore": str(keystore),
        "export/android/debug_keystore_user": "androiddebugkey",
        "export/android/debug_keystore_pass": "android",
        "export/android/shutdown_adb_on_exit": False,
    }
    settings_text = '[gd_resource type="EditorSettings" format=3]\n\n[resource]\n' + "\n".join(
        key + " = " + json.dumps(value) for key, value in settings.items()) + "\n"
    minor_version = "4." + match.group(1)
    (config_dir / ("editor_settings-" + minor_version + ".tres")).write_text(settings_text, encoding="utf-8")
    env = os.environ.copy()
    env.update({"XDG_CONFIG_HOME": str(tools_dir / "config"), "ANDROID_SDK_ROOT": str(sdk),
                "ANDROID_HOME": str(sdk), "JAVA_HOME": str(java)})
    return str(godot), sdk, env, version


def verify_native_apk(apk_path):
    """Verify APK structure; this deliberately makes no device-test claim."""
    apk_path = Path(apk_path)
    if not apk_path.is_file():
        raise NativeAndroidExportError("Godot did not create the requested APK: " + str(apk_path))
    try:
        with zipfile.ZipFile(apk_path) as archive:
            names = archive.namelist()
            if archive.testzip():
                raise NativeAndroidExportError("APK contains a corrupt ZIP entry.")
            for name in ("AndroidManifest.xml", "classes.dex", "assets/project.binary"):
                if name not in names or not archive.read(name):
                    raise NativeAndroidExportError("APK is incomplete: missing " + name)
            dex_files = [name for name in names if re.fullmatch(r"classes\d*\.dex", name)]
            webview_api_reference = False
            native_render_view = False
            for name in dex_files:
                dex = archive.read(name)
                if not dex.startswith(b"dex\n"):
                    raise NativeAndroidExportError("APK has an invalid Android DEX payload.")
                # AndroidX in the official native Godot template references the
                # platform WebView class. That reference does not create a
                # browser player; reject the actual old browser-player URL.
                webview_api_reference |= b"android/webkit/WebView" in dex
                native_render_view |= b"GodotGLRenderView" in dex
                if b"file:///android_asset/web_player/" in dex:
                    raise NativeAndroidExportError("APK loads a browser player instead of the native game.")
            if not native_render_view:
                raise NativeAndroidExportError("APK has no Godot OpenGL native render view.")
            libraries = [name for name in names if re.fullmatch(r"lib/[^/]+/libgodot_android\.so", name)]
            if not libraries:
                raise NativeAndroidExportError("APK has no native Godot Android library.")
            for name in libraries:
                with archive.open(name) as handle:
                    header = handle.read(4)
                if header != b"\x7fELF":
                    raise NativeAndroidExportError("APK has an invalid native ELF library: " + name)
            browser_files = [name for name in names if "/web_player/" in name.lower()
                             or name.lower().endswith((".html", ".htm", ".js", ".mjs"))]
            if browser_files:
                raise NativeAndroidExportError("APK contains a browser player payload: " + browser_files[0])
            architectures = sorted({name.split("/")[1] for name in libraries})
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        if isinstance(error, NativeAndroidExportError):
            raise
        raise NativeAndroidExportError("Cannot validate APK: " + str(error)) from error
    checksum = hashlib.sha256()
    with apk_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return {"artifact": str(apk_path), "bytes": apk_path.stat().st_size,
            "sha256": checksum.hexdigest(),
            "runtime": NATIVE_RUNTIME, "architectures": architectures,
            "apk_structure_verified": True, "webview_payload": False,
            "native_opengl_render_view": True,
            "android_webview_api_reference": webview_api_reference,
            "device_runtime_tested": False}


def build_native_apk(project_dir, *, output=None, godot=None, sdk=None, java=None):
    project_dir = Path(project_dir).resolve()
    if not (project_dir / "project.godot").is_file():
        raise NativeAndroidExportError("Native Godot project is missing: " + str(project_dir))
    godot, sdk_path, env, version = _toolchain(project_dir, godot, sdk, java)
    output = Path(output).resolve() if output else project_dir / "build/LastSignal-debug.apk"
    if output.suffix.lower() != ".apk":
        raise NativeAndroidExportError("Native Android output must use the .apk extension.")
    output.parent.mkdir(parents=True, exist_ok=True)
    validation_path = output.parent / "apk_validation.json"
    for stale in (output, validation_path):
        if stale.is_file():
            stale.unlink()
    _command([godot, "--headless", "--path", project_dir, "--import"], env=env,
             log_path=output.parent / "godot_import.log")
    _command([godot, "--headless", "--path", project_dir, "--export-debug", "Android", output],
             env=env, log_path=output.parent / "godot_export.log")
    result = verify_native_apk(output)
    signer_name = "apksigner.bat" if os.name == "nt" else "apksigner"
    signers = sorted((sdk_path / "build-tools").glob("*/" + signer_name), reverse=True)
    if not signers:
        raise NativeAndroidExportError("Android SDK build-tools does not contain apksigner.")
    _command([signers[0], "verify", output], env=env, log_path=output.parent / "apk_signature.log")
    result.update({"signature_verified": True, "godot_version": version})
    _write_json(validation_path, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a native BlendEngine Android APK with Godot.")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--godot")
    parser.add_argument("--sdk")
    parser.add_argument("--java")
    args = parser.parse_args(argv)
    try:
        result = build_native_apk(args.project, output=args.output, godot=args.godot,
                                  sdk=args.sdk, java=args.java)
    except NativeAndroidExportError as error:
        print("Native Android build failed: " + str(error), file=sys.stderr)
        return 1
    print("Native APK built and structure/signature checked: " + result["artifact"])
    print("Device/emulator gameplay testing has not been performed by this build step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
