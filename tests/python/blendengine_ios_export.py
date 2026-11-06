# SPDX-License-Identifier: GPL-2.0-or-later
"""Native iOS export boundary tests; fixture archives are not runnable builds."""

import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile


PATH = Path(__file__).resolve().parents[2] / 'scripts/addons_core/blendengine/ios_export.py'
SPEC = importlib.util.spec_from_file_location('blendengine_ios_export', PATH)
ios = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ios)


def macho(*, cpu=0x0100000c, filetype=2, platform=2, signed=False):
    commands = struct.pack('<6I', 0x32, 24, platform, 0x0d0000, 0x110000, 0)
    if signed:
        commands += struct.pack('<4I', 0x1d, 16, 0, 0)
    return (struct.pack('<8I', 0xfeedfacf, cpu, 0, filetype, 2 if signed else 1,
                        len(commands), 0, 0) + commands + b'Godot Engine fixture')


class IOSExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='blendengine-ios-test-')
        self.root = Path(self.directory.name)
        self.source = self.root / 'sdk'
        self.template = self.source / 'native/android_game'
        self.template.mkdir(parents=True)
        for name in ('project.godot', 'main.tscn', 'main.gd', 'npc_agent.gd'):
            (self.template / name).write_text('native game fixture\n')
        (self.template / 'assets/brand').mkdir(parents=True)
        (self.template / 'assets/brand/logo.jpg').write_bytes(b'logo fixture')
        (self.template / 'assets/licenses').mkdir()
        (self.template / 'assets/licenses/GODOT_LICENSE.txt').write_text('license fixture')
        self.tools = self.source / 'tools/ios'
        self.tools.mkdir(parents=True)
        (self.tools / 'project.py').write_text(
            'def ios_preset(bundle_id, version, build):\n'
            '    return \'[preset.0]\\nname="iOS"\\nplatform="iOS"\\n[preset.0.options]\\n\' + '
            '\'application/bundle_identifier="\' + bundle_id + \'"\\n\'\n')
        (self.tools / 'build_ios.py').write_text('# native Xcode helper fixture\n')
        (self.tools / 'setup_toolchain.sh').write_text('# native toolchain fixture\n')
        self.assets = self.root / 'scene'
        self.assets.mkdir()
        (self.assets / 'last_signal.glb').write_bytes(b'glTF current-scene fixture')
        (self.assets / 'story.json').write_text(json.dumps({
            'adapter': 'LAST_SIGNAL', 'npc_agents': [{'name': 'Current Scout', 'behavior': 'GUIDE'}]}))
        self.game = {'native_adapter': 'LAST_SIGNAL', 'project': {'title': 'Current scene'}}

    def tearDown(self):
        self.directory.cleanup()

    def prepare(self, game=None, **kwargs):
        return ios.prepare_native_project(self.root / 'output', game or self.game,
                                          self.assets, source_root=self.source, **kwargs)

    def archive(self, *, binary=None, info=None, extra=None, omit=(), duplicate=False):
        data = {'CFBundleExecutable': 'LastSignal', 'CFBundleIdentifier': 'org.blendengine.lastsignal',
                'CFBundlePackageType': 'APPL', 'CFBundleSupportedPlatforms': ['iPhoneOS']}
        data.update(info or {})
        prefix = 'Payload/LastSignal.app/'
        files = {prefix+'Info.plist': plistlib.dumps(data), prefix+'LastSignal': binary or macho(),
                 prefix+'LastSignal.pck': b'GDPC fixture resource pack'}
        files.update(extra or {})
        path = self.root / 'fixture.ipa'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w') as archive:
                for name, value in files.items():
                    if name not in omit:
                        archive.writestr(name, value)
                if duplicate:
                    archive.writestr(prefix+'LastSignal.pck', b'GDPC duplicate')
        return path

    def test_prepares_current_native_assets_and_build_tools_without_browser(self):
        stale = self.root / 'output/ios_project/web_player'
        stale.mkdir(parents=True)
        (stale/'index.html').write_text('old WebView player')
        (self.template/'assets/native_color_stale.png').write_bytes(b'duplicate bake')
        (self.template/'assets/last_signal_native_color_stale.png').write_bytes(b'extracted bake')
        project = self.prepare()
        self.assertEqual((project/'assets/last_signal.glb').read_bytes(),
                         (self.assets/'last_signal.glb').read_bytes())
        self.assertEqual(json.loads((project/'assets/story.json').read_text())['npc_agents'][0]['name'],
                         'Current Scout')
        self.assertTrue((project/'npc_agent.gd').is_file())
        self.assertTrue((project/'assets/brand/logo.jpg').is_file())
        self.assertTrue((project/'assets/licenses/GODOT_LICENSE.txt').is_file())
        self.assertTrue((project/'tooling/ios/build_ios.py').is_file())
        self.assertIn('--project "$DIR"', (project/'build_ios_ipa.sh').read_text())
        self.assertIn('platform="iOS"', (project/'export_presets.cfg').read_text())
        self.assertFalse(any(p.suffix in {'.html', '.js', '.swift'} for p in project.rglob('*')))
        self.assertFalse((project/'assets/native_color_stale.png').exists())
        self.assertFalse((project/'assets/last_signal_native_color_stale.png').exists())
        self.assertFalse(list(project.rglob('*.ipa')))

    def test_rejects_unsupported_scene_before_creating_output(self):
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'no supported native adapter'):
            self.prepare({'native_adapter': 'OTHER'})
        self.assertFalse((self.root/'output').exists())

    def test_bad_metadata_and_stale_or_missing_scene_assets_fail(self):
        for kwargs in ({'bundle_identifier': 'invalid"bundle'}, {'version_name': '1.1-agent'},
                       {'version_code': True}, {'version_code': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ios.NativeIOSExportError):
                self.prepare(**kwargs)
        (self.assets/'story.json').write_text('{}')
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'do not use'):
            self.prepare()
        (self.assets/'story.json').write_text('{broken')
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'Cannot read'):
            self.prepare()
        (self.assets/'last_signal.glb').write_bytes(b'not a GLB')
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'not a binary glTF'):
            self.prepare()
        (self.assets/'last_signal.glb').unlink()
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'missing last_signal.glb'):
            self.prepare()

    def test_native_ipa_validation_does_not_claim_signing_or_execution(self):
        result = ios.verify_unsigned_ipa(self.archive())
        self.assertTrue(result['ipa_structure_verified'])
        self.assertEqual(result['architectures'], ['arm64'])
        self.assertEqual(len(result['sha256']), 64)
        for field in ('signed', 'physical_device_installable', 'simulator_runtime_tested',
                      'physical_device_tested', 'browser_payload'):
            self.assertFalse(result[field])

    def test_renamed_zip_or_non_device_binary_is_not_an_ipa(self):
        for data, message in ((b'plain file', 'Mach-O'),
                              (macho(cpu=0x01000007), 'ARM64'),
                              (macho(platform=7), 'simulator'),
                              (macho(filetype=6), 'executable')):
            with self.subTest(message=message), self.assertRaisesRegex(ios.NativeIOSExportError, message):
                ios.verify_unsigned_ipa(self.archive(binary=data))

    def test_native_ipa_requires_one_app_info_and_declared_executable(self):
        for options in ({'omit': ('Payload/LastSignal.app/Info.plist',)},
                        {'omit': ('Payload/LastSignal.app/LastSignal',)},
                        {'info': {'CFBundleExecutable': '../outside'}},
                        {'info': {'CFBundlePackageType': 'BNDL'}},
                        {'info': {'CFBundleIdentifier': 123}},
                        {'info': {'CFBundleSupportedPlatforms': ['iPhoneSimulator']}},
                        {'extra': {'Payload/Other.app/Info.plist': b'other'}}):
            with self.subTest(options=options), self.assertRaises(ios.NativeIOSExportError):
                ios.verify_unsigned_ipa(self.archive(**options))

    def test_no_resource_pack_or_godot_runtime_is_failure(self):
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'resource pack'):
            ios.verify_unsigned_ipa(self.archive(omit=('Payload/LastSignal.app/LastSignal.pck',)))
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'Godot runtime'):
            ios.verify_unsigned_ipa(self.archive(binary=macho().replace(b'Godot', b'Other')))

    def test_browser_payload_signatures_and_provisioning_rejected(self):
        for extra in ({'Payload/LastSignal.app/web_player/index.html': b'<canvas/>'},
                      {'Payload/LastSignal.app/_CodeSignature/CodeResources': b'signed'},
                      {'Payload/LastSignal.app/embedded.mobileprovision': b'profile'}):
            with self.subTest(extra=extra), self.assertRaises(ios.NativeIOSExportError):
                ios.verify_unsigned_ipa(self.archive(extra=extra))
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'code signature'):
            ios.verify_unsigned_ipa(self.archive(binary=macho(signed=True)))

    def test_malformed_load_commands_universal_slices_and_zip_paths(self):
        data = bytearray(macho())
        struct.pack_into('<I', data, 36, 99999)
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'length'):
            ios.verify_unsigned_ipa(self.archive(binary=bytes(data)))
        slice_data = macho()
        universal = struct.pack('>2I5I', 0xcafebabe, 1, 0x0100000c, 0, 28, len(slice_data), 0) + slice_data
        self.assertEqual(ios.verify_unsigned_ipa(self.archive(binary=universal))['architectures'], ['arm64'])
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'duplicate'):
            ios.verify_unsigned_ipa(self.archive(duplicate=True))
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'unsafe'):
            ios.verify_unsigned_ipa(self.archive(extra={'Payload/../outside': b'bad'}))

    def test_missing_or_bad_zip_is_not_validated(self):
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'did not create'):
            ios.verify_unsigned_ipa(self.root/'missing.ipa')
        path = self.root/'invalid.ipa'
        path.write_text('not a ZIP')
        with self.assertRaisesRegex(ios.NativeIOSExportError, 'Cannot validate'):
            ios.verify_unsigned_ipa(path)

    def test_linux_does_not_manufacture_or_replace_an_ipa(self):
        output = self.root/'old.ipa'
        output.write_bytes(b'old artifact')
        with mock.patch.object(ios.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(ios.NativeIOSExportError, 'requires macOS'):
                ios.build_unsigned_ipa(self.prepare(), output=output)
        self.assertEqual(output.read_bytes(), b'old artifact')

    def test_success_exit_without_ipa_is_not_a_successful_build(self):
        project = self.prepare()
        output = self.root/'old.ipa'
        output.write_bytes(b'stale')
        process = subprocess.CompletedProcess([], 0, 'Xcode fixture exited without output\n')
        with mock.patch.object(ios.sys, 'platform', 'darwin'), \
                mock.patch.object(ios.shutil, 'which', return_value='/fixture/xcodebuild'), \
                mock.patch.object(ios.subprocess, 'run', return_value=process):
            with self.assertRaisesRegex(ios.NativeIOSExportError, 'did not create'):
                ios.build_unsigned_ipa(project, output=output)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
