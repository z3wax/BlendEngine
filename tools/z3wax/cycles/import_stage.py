# SPDX-License-Identifier: Apache-2.0
"""Run in Blender: --python import_stage.py -- INPUT.glb OUTPUT.blend"""
import bpy
import sys
source, output = sys.argv[sys.argv.index('--') + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
bpy.ops.wm.save_as_mainfile(filepath=output)
