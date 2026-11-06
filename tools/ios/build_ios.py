#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a real unsigned ARM64 IPA with Xcode, optionally exercising iOS Simulator."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import struct
import subprocess
import tempfile
import zipfile

from project import GODOT_VERSION, prepare_project


def run(command, *, log=None, timeout=1200, check=True):
    result = subprocess.run([str(word) for word in command], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=timeout)
    if log:
        Path(log).write_text(result.stdout, encoding='utf-8')
    if check and result.returncode:
        raise RuntimeError('Command failed (%d): %s\n%s' % (
            result.returncode, command[0], '\n'.join(result.stdout.splitlines()[-30:])))
    return result.stdout


def macho_device(data):
    """Validate an executable ARM64 device Mach-O, never a simulator or text stub."""
    if data[:4] != b'\xcf\xfa\xed\xfe' or len(data) < 32:
        raise ValueError('IPA executable must be a thin ARM64 Mach-O')
    magic, cpu, _subtype, kind, count, command_bytes, _flags, _reserved = struct.unpack_from('<8I', data)
    if cpu != 0x100000c or kind != 2 or command_bytes > len(data)-32 or count > 1000:
        raise ValueError('IPA does not contain a valid ARM64 executable')
    offset, device = 32, False
    for _ in range(count):
        if offset + 8 > len(data):
            raise ValueError('Truncated Mach-O command')
        command, length = struct.unpack_from('<II', data, offset)
        if length < 8 or offset + length > len(data):
            raise ValueError('Invalid Mach-O command size')
        if command == 0x1d:
            raise ValueError('Unsigned IPA must not retain an ad-hoc code signature')
        if command == 0x32:
            if length < 24 or struct.unpack_from('<I', data, offset+8)[0] != 2:
                raise ValueError('Mach-O platform is not physical iOS')
            device = True
        offset += length
    if not device:
        raise ValueError('No physical iOS LC_BUILD_VERSION found')


def validate_ipa(path, bundle_id='org.blendengine.lastsignal'):
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError('IPA archive CRC failed')
        names = archive.namelist()
        infos = [name for name in names if name.startswith('Payload/') and name.count('/') == 2
                 and name.endswith('.app/Info.plist')]
        if len(infos) != 1:
            raise ValueError('IPA must have exactly one Payload/*.app/Info.plist')
        info = plistlib.loads(archive.read(infos[0]))
        app = infos[0].rsplit('/', 1)[0] + '/'
        executable = info.get('CFBundleExecutable', '')
        if (not executable or '/' in executable or info.get('CFBundleIdentifier') != bundle_id
                or info.get('CFBundlePackageType') != 'APPL'
                or 'iPhoneOS' not in info.get('CFBundleSupportedPlatforms', [])):
            raise ValueError('Invalid native iOS application metadata')
        macho_device(archive.read(app + executable))
        if any(name.startswith(app) and ('/_CodeSignature/' in name
                or name.endswith('embedded.mobileprovision')) for name in names):
            raise ValueError('This artifact must be explicitly unsigned, without a provisioning profile')
        packs = [name for name in names if name.startswith(app) and name.endswith('.pck')]
        if not packs or not any(archive.open(name).read(4) == b'GDPC' for name in packs):
            raise ValueError('Native Godot resource pack is missing')
        if any(name.lower().endswith(('.html', '.htm', '.js', '.mjs')) for name in names):
            raise ValueError('Unexpected browser game payload')
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'artifact': path.name, 'bytes': path.stat().st_size, 'sha256': checksum,
            'bundle_identifier': bundle_id, 'architecture': 'arm64', 'platform': 'iOS device',
            'unsigned': True, 'installable_on_stock_iphone_without_signing': False,
            'native_macho_verified': True, 'godot_pack_verified': True,
            'physical_device_tested': False}


def package_unsigned(app, output):
    # The linker can add ad-hoc signing even with CODE_SIGNING_ALLOWED=NO.
    # Remove it deliberately; this is not a counterfeit development signature.
    run(['codesign', '--remove-signature', app], check=False)
    signature = app / '_CodeSignature'
    if signature.exists():
        shutil.rmtree(signature)
    (app / 'embedded.mobileprovision').unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='blendengine-ipa-payload-') as temp:
        payload = Path(temp) / 'Payload'
        payload.mkdir()
        shutil.copytree(app, payload / app.name, symlinks=True)
        run(['/usr/bin/ditto', '-c', '-k', '--keepParent', payload, output])


def save_validation(output, result):
    (output.parent/'ipa_validation.json').write_text(json.dumps(result, indent=2)+'\n')
    output.with_suffix(output.suffix+'.sha256').write_text(
        result['sha256']+'  '+output.name+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--godot', default=os.environ.get('GODOT_BIN', shutil.which('godot') or ''))
    parser.add_argument('--bundle-id', default='org.blendengine.lastsignal')
    parser.add_argument('--version', default='1.1')
    parser.add_argument('--build', type=int, default=2)
    parser.add_argument('--qa', action='store_true')
    parser.add_argument('--proof-dir', type=Path)
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        raise SystemExit('Native IPA compilation requires macOS and Xcode. Use the native-ios-ipa workflow.')
    if not args.godot:
        raise SystemExit('Install Godot 4.6.3 and its iOS template with tools/ios/setup_toolchain.sh.')
    version = run([args.godot, '--version'], timeout=30).strip()
    if not version.startswith(GODOT_VERSION + '.stable.'):
        raise SystemExit('Use matching Godot 4.6.3 stable editor/templates; found ' + version)
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    proof = (args.proof_dir or args.output.parent / 'ios-proof').resolve()
    proof.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='blendengine-ios-') as temp:
        work = Path(temp)
        game = prepare_project(args.project, work / 'game', bundle_id=args.bundle_id,
                               version=args.version, build=args.build)
        run([args.godot, '--headless', '--path', game, '--import'], log=proof/'godot-import.log')
        export = work / 'export'
        export.mkdir()
        run([args.godot, '--headless', '--path', game, '--export-release', 'iOS', export/'LastSignal.ipa'],
            log=proof/'godot-export.log')
        project = export/'LastSignal.xcodeproj'
        if not project.is_dir():
            raise RuntimeError('Godot did not produce a native Xcode project')
        common = ['xcodebuild', '-project', project, '-scheme', 'LastSignal', '-configuration', 'Release']
        run(common + ['-sdk', 'iphoneos', '-destination', 'generic/platform=iOS',
            '-derivedDataPath', work/'device', 'ARCHS=arm64', 'ONLY_ACTIVE_ARCH=NO',
            'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO', 'DEVELOPMENT_TEAM=', 'build'],
            log=proof/'xcode-device.log', timeout=1800)
        device = work/'device/Build/Products/Release-iphoneos/LastSignal.app'
        if not device.is_dir():
            raise RuntimeError('Xcode device app output is missing')
        package_unsigned(device, args.output)
        result = validate_ipa(args.output, args.bundle_id)
        result.update({'godot_version': version, 'renderer': 'native OpenGL ES 3 Compatibility',
                       'simulator_tested': False})
        # Preserve device verification even when simulator setup or testing fails.
        save_validation(args.output, result)
        if args.qa:
            architecture = platform.machine()
            run(common + ['-sdk', 'iphonesimulator', '-destination', 'generic/platform=iOS Simulator',
                '-derivedDataPath', work/'simulator', 'ARCHS='+architecture, 'ONLY_ACTIVE_ARCH=YES',
                'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO', 'DEVELOPMENT_TEAM=', 'build'],
                log=proof/'xcode-simulator.log', timeout=1800)
            app = work/'simulator/Build/Products/Release-iphonesimulator/LastSignal.app'
            # The software GLES simulator can starve CADisplayLink's run-loop
            # drain. Godot's supported timer path changes no graphics setting.
            # Keep this loose override out of the ARM64 device app and IPA.
            (app/'override.cfg').write_text('[display.AppleEmbedded]\nuse_cadisplaylink=false\n')
            run(['codesign', '--force', '--deep', '--sign', '-', '--timestamp=none', app])
            # Keep the native simulator app available if runtime setup fails.
            run(['/usr/bin/ditto', '-c', '-k', '--keepParent', app,
                 args.output.parent/'LastSignal-AI-simulator.zip'])
            from simulator_qa import test_game
            qa = test_game(app, args.bundle_id, proof)
            result['simulator_tested'] = qa['passed']
        save_validation(args.output, result)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
