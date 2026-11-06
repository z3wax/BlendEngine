# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare the existing native game for an unsigned iOS Xcode build."""

import json
from pathlib import Path
import re
import shutil


GODOT_VERSION = '4.6.3'
SUPPORTED_BEHAVIORS = {'IDLE', 'FOLLOW_PLAYER', 'PATROL', 'GUARD', 'GUIDE'}


def ios_preset(bundle_id='org.blendengine.lastsignal', version='1.1', build=2):
    if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z0-9-]+)+', bundle_id):
        raise ValueError('Enter a valid reverse-domain iOS bundle identifier')
    if not re.fullmatch(r'\d+(?:\.\d+){0,2}', version):
        raise ValueError('iOS version must contain one to three numeric components')
    if type(build) is not int or build < 1:
        raise ValueError('iOS build must be a positive integer')
    # Godot requires a nonempty Team ID even for project-only generation. This
    # placeholder is NOT an Apple team and is cleared by the unsigned build.
    return '''[preset.0]
name="iOS"
platform="iOS"
runnable=true
advanced_options=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter="assets/*.json,assets/licenses/*.txt"
exclude_filter=".blendengine-tools/*,tooling/*,build/*,*.md,*.py,*.sh,assets/native_color_*.png,assets/native_normal_*.png"
export_path="build/LastSignal.ipa"
script_export_mode=2

[preset.0.options]
custom_template/debug=""
custom_template/release=""
architectures/arm64=true
application/app_store_team_id="0000000000"
application/export_method_debug=1
application/export_method_release=1
application/code_sign_identity_debug="-"
application/code_sign_identity_release="-"
application/bundle_identifier=%s
application/short_version=%s
application/version=%s
application/min_ios_version="14.0"
application/targeted_device_family=2
application/export_project_only=true
application/delete_old_export_files_unconditionally=true
application/additional_plist_content="<key>godot_cmdline</key><array><string>--audio-driver</string><string>Dummy</string></array>"
''' % (json.dumps(bundle_id), json.dumps(version), json.dumps(str(build)))


def prepare_project(source, destination, *, bundle_id='org.blendengine.lastsignal', version='1.1', build=2):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise ValueError('The prepared iOS project must be outside the source game directory')
    for required in ('project.godot', 'main.tscn', 'main.gd', 'assets/last_signal.glb', 'assets/story.json'):
        if not (source / required).is_file():
            raise ValueError('Native game source is missing ' + required)
    if destination.exists():
        raise ValueError('Prepared iOS destination already exists: ' + str(destination))

    def ignore(_directory, names):
        return [name for name in names if name in {'.git', '.godot', 'build', 'tooling', '__pycache__', '.blendengine-tools'}
                or name.endswith(('.import', '.apk', '.ipa', '.p12', '.keystore', '.jks', '.pyc'))
                or (name.endswith('.png') and name.startswith(('native_color_', 'native_normal_',
                    'last_signal_native_color_', 'last_signal_native_normal_')))]

    shutil.copytree(source, destination, ignore=ignore)
    (destination / 'export_presets.cfg').write_text(ios_preset(bundle_id, version, build), encoding='utf-8')
    project = (destination / 'project.godot').read_text(encoding='utf-8')
    # Official 4.6.3 simulator templates disable Metal/Vulkan, so use the same
    # native GLES3 renderer for device and simulator. No quality setting drops.
    project = re.sub(r'^renderer/rendering_method(?:\.mobile)?=.*$',
        lambda match: match.group(0).split('=')[0] + '="gl_compatibility"', project, flags=re.M)
    (destination / 'project.godot').write_text(project, encoding='utf-8')
    return destination
