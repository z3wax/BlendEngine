#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install pinned official Godot macOS editor and iOS export template."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import urllib.request
import zipfile

VERSION = '4.6.3'
BASE = 'https://github.com/godotengine/godot-builds/releases/download/4.6.3-stable/'
FILES = {
    'Godot_v4.6.3-stable_macos.universal.zip': '30630f3e9b11e10b35c1f90ba8814185dcec43fae1a48345159be7552c64bfe8',
    'Godot_v4.6.3-stable_export_templates.tpz': '3fbe2c0e2dec9d537ab9ec97bcf8da91dcf23357fc51f67092dd068d839290a8',
}


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path.home() / 'Library/Caches/BlendEngine/ios')
    parser.add_argument('--github-env', type=Path)
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        raise SystemExit('A macOS computer with Xcode is required for native iOS builds.')
    subprocess.run(['xcodebuild', '-version'], check=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        path = args.cache / name
        if not path.is_file() or checksum(path) != expected:
            temporary = path.with_suffix(path.suffix + '.downloading')
            with urllib.request.urlopen(BASE + name, timeout=120) as response, temporary.open('wb') as out:
                while chunk := response.read(4 * 1024 * 1024):
                    out.write(chunk)
            if checksum(temporary) != expected:
                temporary.unlink(missing_ok=True)
                raise SystemExit('Official Godot archive checksum failed: ' + name)
            temporary.replace(path)
    editor = args.cache / 'Godot.app/Contents/MacOS/Godot'
    if not editor.is_file():
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(args.cache / next(iter(FILES))), str(args.cache)], check=True)
    editor.chmod(0o755)
    templates = Path.home() / 'Library/Application Support/Godot/export_templates' / (VERSION + '.stable')
    templates.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.cache / 'Godot_v4.6.3-stable_export_templates.tpz') as archive:
        for name in ('ios.zip', 'version.txt'):
            (templates / name).write_bytes(archive.read('templates/' + name))
    if args.github_env:
        with args.github_env.open('a') as stream:
            stream.write('GODOT_BIN=' + str(editor) + '\n')
    print(json.dumps({'godot': str(editor), 'templates': str(templates), 'version': VERSION}))


if __name__ == '__main__':
    main()
