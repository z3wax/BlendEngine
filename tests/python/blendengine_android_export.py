# SPDX-License-Identifier: GPL-2.0-or-later
"""Native Android export failure handling and payload regressions (no bpy/SDK).

Run with python3 tests/python/blendengine_android_export.py. These fixtures test
the exporter boundary; they are not device or gameplay execution tests.
"""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/addons_core/blendengine/android_export.py"
SPEC = importlib.util.spec_from_file_location("blendengine_android_export", MODULE_PATH)
android = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(android)


class NativeAndroidExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="blendengine-android-test-")
        self.root = Path(self.directory.name)
        self.template = self.root / "template"
        self.template.mkdir()
        for name in ("project.godot", "main.tscn", "main.gd"):
            (self.template / name).write_text("native source\n", encoding="utf-8")
        (self.template / "assets/brand").mkdir(parents=True)
        (self.template / "assets/brand/logo.jpg").write_bytes(b"logo fixture")
        self.assets = self.root / "exported_assets"
        self.assets.mkdir()
        (self.assets / "last_signal.glb").write_bytes(b"glTFcurrent scene fixture")
        (self.assets / "story.json").write_text(json.dumps({"adapter": "LAST_SIGNAL"}), encoding="utf-8")
        self.game_data = {"native_adapter": "LAST_SIGNAL", "project": {"title": "Current scene"}}

    def tearDown(self):
        self.directory.cleanup()

    def prepare(self, data=None):
        return android.prepare_native_project(self.root / "package", data or self.game_data,
                                               self.assets, template_dir=self.template)

    def apk_fixture(self, *, entries=None, omitted=()):
        path = self.root / "fixture.apk"
        files = {
            "AndroidManifest.xml": b"binary manifest fixture",
            "classes.dex": b"dex\n035\x00GodotGLRenderView",
            "assets/project.binary": b"native project fixture",
            "lib/arm64-v8a/libgodot_android.so": b"\x7fELFfixture",
            "lib/x86_64/libgodot_android.so": b"\x7fELFfixture",
        }
        files.update(entries or {})
        with zipfile.ZipFile(path, "w") as archive:
            for name, value in files.items():
                if name not in omitted:
                    archive.writestr(name, value)
        return path

    def test_current_scene_assets_and_logo_replace_stale_player(self):
        (self.template / "assets/native_color_stale.png").write_bytes(b"old scene bake")
        stale = self.root / "package/android_project/app/src/main/assets/web_player"
        stale.mkdir(parents=True)
        (stale / "index.html").write_text("old browser player", encoding="utf-8")
        project = self.prepare()
        self.assertEqual((project / "assets/last_signal.glb").read_bytes(),
                         (self.assets / "last_signal.glb").read_bytes())
        self.assertEqual((project / "assets/brand/logo.jpg").read_bytes(), b"logo fixture")
        self.assertEqual(json.loads((project / "assets/game_data.json").read_text()), self.game_data)
        self.assertTrue((project / "tooling/android_export.py").is_file())
        self.assertTrue((project / "build_android_apk.py").is_file())
        self.assertFalse((project / "assets/native_color_stale.png").exists())
        self.assertFalse(any(p.suffix in {".html", ".js", ".java", ".kt"} for p in project.rglob("*")))
        preset = (project / "export_presets.cfg").read_text()
        self.assertIn('platform="Android"', preset)
        self.assertIn('architectures/arm64-v8a=true', preset)
        self.assertIn('gradle_build/min_sdk=""', preset)
        self.assertIn('gradle_build/target_sdk=""', preset)
        self.assertIn('assets/licenses/*.txt', preset)
        self.assertIn('assets/native_color_*.png', preset)
        self.assertIn('assets/native_normal_*.png', preset)
        self.assertIn('command_line/extra_args="--audio-driver Dummy"', preset)

    def test_unsupported_scene_fails_before_creating_project(self):
        with self.assertRaisesRegex(android.NativeAndroidExportError, "no supported native adapter"):
            self.prepare({"native_adapter": "UNKNOWN_GAME"})
        self.assertFalse((self.root / "package").exists())

    def test_stale_assets_for_different_story_are_rejected(self):
        (self.assets / "story.json").write_text('{"adapter":"OTHER_GAME"}', encoding="utf-8")
        with self.assertRaisesRegex(android.NativeAndroidExportError, "do not use the LAST_SIGNAL"):
            self.prepare()
        self.assertFalse((self.root / "package").exists())

    def test_absent_or_invalid_scene_asset_is_not_a_playable_export(self):
        (self.assets / "last_signal.glb").unlink()
        with self.assertRaisesRegex(android.NativeAndroidExportError, "missing last_signal.glb"):
            self.prepare()
        (self.assets / "last_signal.glb").write_text("not glTF", encoding="utf-8")
        with self.assertRaisesRegex(android.NativeAndroidExportError, "not a binary glTF"):
            self.prepare()

    def test_package_metadata_validation(self):
        with self.assertRaisesRegex(android.NativeAndroidExportError, "package ID"):
            android.export_preset('org.bad"\npackage')
        with self.assertRaisesRegex(android.NativeAndroidExportError, "positive integer"):
            android.export_preset(version_code=0)

    def test_native_apk_checks_never_claim_device_execution(self):
        # AndroidX in the official Godot APK refers to the WebView API even
        # though the player renders with GodotGLRenderView and native ELF libs.
        path = self.apk_fixture(entries={"classes2.dex": b"dex\n035\x00Landroid/webkit/WebView;"})
        result = android.verify_native_apk(path)
        self.assertTrue(result["native_opengl_render_view"])
        self.assertTrue(result["android_webview_api_reference"])
        self.assertFalse(result["webview_payload"])
        self.assertFalse(result["device_runtime_tested"])
        self.assertEqual(result["architectures"], ["arm64-v8a", "x86_64"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_browser_payload_or_loader_is_rejected_even_with_native_library(self):
        with self.assertRaisesRegex(android.NativeAndroidExportError, "browser player payload"):
            android.verify_native_apk(self.apk_fixture(entries={"assets/web_player/index.html": b"<canvas/>"}))
        with self.assertRaisesRegex(android.NativeAndroidExportError, "loads a browser player"):
            android.verify_native_apk(self.apk_fixture(entries={
                "classes.dex": b"dex\n035\x00GodotGLRenderView\x00file:///android_asset/web_player/index.html"}))

    def test_apk_requires_manifest_native_library_and_native_render_view(self):
        for omitted, message in (
                (("AndroidManifest.xml",), "missing AndroidManifest.xml"),
                (("lib/arm64-v8a/libgodot_android.so", "lib/x86_64/libgodot_android.so"), "no native Godot")):
            with self.subTest(omitted=omitted), self.assertRaisesRegex(android.NativeAndroidExportError, message):
                android.verify_native_apk(self.apk_fixture(omitted=omitted))
        with self.assertRaisesRegex(android.NativeAndroidExportError, "no Godot OpenGL"):
            android.verify_native_apk(self.apk_fixture(entries={"classes.dex": b"dex\n035\x00"}))

    def test_missing_godot_returns_clear_dependency_error(self):
        project = self.prepare()
        with mock.patch.dict(android.os.environ, {}, clear=True), mock.patch.object(android.shutil, "which", return_value=None):
            with self.assertRaisesRegex(android.NativeAndroidExportError, "Godot 4 is missing"):
                android.build_native_apk(project)
        self.assertFalse((project / "build/LastSignal-debug.apk").exists())

    def test_success_exit_without_real_apk_is_failure_and_old_apk_is_removed(self):
        project = self.prepare()
        output = project / "build/LastSignal-debug.apk"
        output.parent.mkdir()
        output.write_bytes(b"stale previous APK")
        with mock.patch.object(android, "_toolchain", return_value=("godot", self.root, {}, "4.6.3.stable")), \
                mock.patch.object(android, "_command", return_value="") as command:
            with self.assertRaisesRegex(android.NativeAndroidExportError, "did not create the requested APK"):
                android.build_native_apk(project)
        self.assertEqual(command.call_count, 2)
        self.assertFalse(output.exists())
        self.assertFalse((output.parent / "apk_validation.json").exists())

    def test_godot_script_error_fails_even_with_zero_process_exit(self):
        process = subprocess.CompletedProcess(["godot"], 0, "SCRIPT ERROR: Parse Error: invalid token\n")
        with mock.patch.object(android.subprocess, "run", return_value=process):
            with self.assertRaisesRegex(android.NativeAndroidExportError, "Parse Error"):
                android._command(["godot"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
