"""Join static rifle parts without decimation, texture changes or vertex welding."""
import bpy,sys,json
from mathutils.kdtree import KDTree
args=sys.argv[sys.argv.index('--')+1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=args[0])
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
before=[o.matrix_world@v.co for o in meshes for v in o.data.vertices]
triangles=sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in meshes)
bpy.ops.object.select_all(action='DESELECT')
for o in meshes:o.select_set(True)
bpy.context.view_layer.objects.active=meshes[0]
bpy.ops.object.join()
joined=bpy.context.object
assert len(joined.data.vertices)==len(before)
assert sum(len(p.vertices)-2 for p in joined.data.polygons)==triangles
kd=KDTree(len(before))
for i,p in enumerate(before):kd.insert(p,i)
kd.balance()
error=max(kd.find(joined.matrix_world@v.co)[2] for v in joined.data.vertices)
assert error<1e-6,error
bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB')
print('RIFLE_BATCH_PASS',json.dumps({'source_meshes':len(meshes),'output_meshes':1,'vertices':len(before),'triangles':triangles,'max_vertex_error':error,'materials':len(joined.data.materials)}))
