import bpy
from mathutils import Vector
import sys
from pathlib import Path
args=sys.argv[sys.argv.index('--')+1:]
if len(args)!=2:raise SystemExit('Usage: blender -b --python extract_rifle.py -- DECOMPRESSED_INPUT.glb OUTPUT.glb')
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=args[0])
meshes=[o for o in bpy.data.objects if o.type=='MESH' and o.name not in ['FPArms','Icosphere']]
for o in meshes:
 print('RIFLE',o.name,tuple(o.dimensions),tuple(o.location))
 mat=o.matrix_world.copy();o.parent=None;o.matrix_world=mat
 for mod in list(o.modifiers):o.modifiers.remove(mod)
for o in list(bpy.data.objects):
 if o not in meshes:bpy.data.objects.remove(o,do_unlink=True)
pts=[o.matrix_world@Vector(p) for o in meshes for p in o.bound_box]
print('BOUNDS',[(min(p[i] for p in pts),max(p[i] for p in pts)) for i in range(3)])
bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB')
