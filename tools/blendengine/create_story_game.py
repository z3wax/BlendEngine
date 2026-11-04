# SPDX-License-Identifier: GPL-2.0-or-later
"""Create Last Signal as a native, playable story chapter."""
import argparse
import json
from pathlib import Path
import sys
import bpy

parser=argparse.ArgumentParser()
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.output_dir.mkdir(parents=True,exist_ok=True)
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'scripts/addons_core'))
import blendengine
blendengine.register()
from blendengine import story_game,runtime
result=story_game.create_story(bpy.context)
scene=result['scene']
asset=root/'scripts/addons_core/blendengine/assets/last_signal_character.blend'
if not asset.is_file():
    asset.parent.mkdir(parents=True,exist_ok=True)
    rig=result['rig']
    parent=rig.parent
    rig.parent=None
    try:
        bpy.data.libraries.write(str(asset),{result['actor'],rig},fake_user=True,compress=True)
    finally:
        rig.parent=parent
validation=runtime.validate_scene(scene)
assert validation.ok,validation.errors
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.shading.type='RENDERED'
            area.spaces.active.region_3d.view_perspective='CAMERA'
            area.spaces.active.overlay.show_overlays=False
# Remove only orphan data from the temporary import, never data used by a scene.
for collection in (bpy.data.meshes,bpy.data.materials,bpy.data.armatures):
    for data in list(collection):
        if data.users==0:
            collection.remove(data)
path=(args.output_dir/'LastSignal.blend').resolve()
bpy.ops.wm.save_as_mainfile(filepath=str(path))
manifest={'title':'Last Signal','chapter':'A voice in the static','player':'Maya / field engineer',
          'story':'After a storm destroys a mountain relay, Maya follows five clues to find her missing brother Eli and restore the rescue beacon.',
          'renderer':scene.render.engine,'quality':scene.blendengine_quality_profile.preset,
          'objects':len(scene.objects),'triangles':sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in scene.objects if o.type=='MESH'),
          'human_mesh_source':'Existing BlendEngine NeonQuarantine soldier geometry; procedural replacement clothing and skin materials',
          'waypoints':story_game.WAYPOINTS,'native_runtime':True,'validation_errors':validation.errors}
(args.output_dir/'story_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('STORY_READY',path,manifest['objects'],manifest['triangles'])
