"""Create geometry-only distant LOD; runtime reuses the original PBR material."""
import bpy,sys,pathlib
args=sys.argv[sys.argv.index('--')+1:]
if len(args)!=2:raise SystemExit('Expected INPUT.gltf OUTPUT.glb')
bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=args[0]);before=after=0
for obj in list(bpy.context.scene.objects):
 if obj.type!='MESH':continue
 obj.data.calc_loop_triangles();count=len(obj.data.loop_triangles);before+=count
 if count>2000:
  bpy.context.view_layer.objects.active=obj;mod=obj.modifiers.new('Distant silhouette','DECIMATE');mod.ratio=2000/count;mod.use_collapse_triangulate=True;bpy.ops.object.modifier_apply(modifier=mod.name)
 obj.data.calc_loop_triangles();after+=len(obj.data.loop_triangles)
bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_materials='NONE')
print('DISTANT_LOD_TRIANGLES',before,after)
