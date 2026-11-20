import json,struct,numpy as np,pathlib,base64
from mathutils import Matrix,Vector,Quaternion
import bpy
import sys
args=sys.argv[sys.argv.index('--')+1:]
if len(args)!=2:raise SystemExit('Usage: blender -b --python normalize_tactical.py -- INPUT.glb OUTPUT_DIRECTORY')
src=pathlib.Path(args[0]);destination=pathlib.Path(args[1]);destination.mkdir(parents=True,exist_ok=True)
b=src.read_bytes();n=struct.unpack_from('<I',b,12)[0];j=json.loads(b[20:20+n]);binary=b[28+n:]
dtypes={5126:'<f4',5123:'<u2',5125:'<u4',5121:'u1'};counts={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}
def acc(i):
 a=j['accessors'][i];v=j['bufferViews'][a['bufferView']];dt=np.dtype(dtypes[a['componentType']]);c=counts[a['type']];offset=v.get('byteOffset',0)+a.get('byteOffset',0);stride=v.get('byteStride',dt.itemsize*c)
 return np.ndarray((a['count'],c),dtype=dt,buffer=binary,offset=offset,strides=(stride,dt.itemsize)).copy()
parents={c:i for i,n in enumerate(j['nodes']) for c in n.get('children',[])};world={}
def mat(i):
 if i in world:return world[i]
 nd=j['nodes'][i]
 if 'matrix' in nd:m=np.array(nd['matrix']).reshape(4,4).T
 else:
  r=nd.get('rotation',[0,0,0,1]);m=np.array(Matrix.LocRotScale(Vector(nd.get('translation',[0,0,0])),Quaternion((r[3],*r[:3])),Vector(nd.get('scale',[1,1,1]))))
 world[i]=mat(parents[i])@m if i in parents else m
 return world[i]
bpy.ops.wm.read_factory_settings(use_empty=True)
# Import only to recover the original artist-authored PBR materials.
bpy.ops.import_scene.gltf(filepath=str(src));materials=list(bpy.data.materials)
matmap={m.name:m for m in materials}
for o in list(bpy.data.objects):bpy.data.objects.remove(o,do_unlink=True)
C=np.array([[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1.]])
# Recover the neutral bind pose from inverse skin matrices, not the saved display pose.
# Original geometry uses million-unit coordinates; normalize before Blender import.
skin=j['skins'][0];joint_ids=skin['joints'];ib_all=acc(skin['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1);factor=0.9144042730331421e-6;normalizer=np.diag([factor,factor,factor,1.]);bind_world={ix:normalizer@np.linalg.inv(ib.astype(np.float64)) for ix,ib in zip(joint_ids,ib_all)};arm=bpy.data.armatures.new('TacticalRig');rig=bpy.data.objects.new('TacticalRig',arm);bpy.context.collection.objects.link(rig);bpy.context.view_layer.objects.active=rig;rig.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
for ix in joint_ids:
 name=j['nodes'][ix].get('name',str(ix));w=C@bind_world[ix];rot=w[:3,:3];rot=rot/np.linalg.norm(rot,axis=0);bone=arm.edit_bones.new(name);bone.head=Vector(w[:3,3]);bone.tail=bone.head+Vector(rot[:,1])*.08;bone.align_roll(Vector(rot[:,2]))
for ix in joint_ids:
 if parents.get(ix) in joint_ids:arm.edit_bones[j['nodes'][ix]['name']].parent=arm.edit_bones[j['nodes'][parents[ix]]['name']]
bpy.ops.object.mode_set(mode='OBJECT')
for ni,node in enumerate(j['nodes']):
 if 'mesh' not in node:continue
 if node.get('name')=='Object_121':continue # Optional equipment slot is not part of selected outfit.
 mesh=j['meshes'][node['mesh']]
 for pi,p in enumerate(mesh['primitives']):
  v=acc(p['attributes']['POSITION']).astype(np.float64);v=np.column_stack([v,np.ones(len(v))]);weights=None
  if 'skin' in node:
   s=j['skins'][node['skin']];ji=acc(p['attributes']['JOINTS_0']).astype(int);weights=acc(p['attributes']['WEIGHTS_0']);out=(normalizer@v.T).T
  else:
   out=(mat(ni)@v.T).T
   if node.get('name')=='0':
    head=next(ix for ix in joint_ids if j['nodes'][ix]['name']=='mixamorig:Head_06')
    out=(bind_world[head]@np.linalg.inv(mat(head))@out.T).T
  out=(C@out.T).T[:,:3]
  if node.get('name')=='Object_111':out[:,2]-=.22 # Fit separate headset to the selected cap.
  faces=acc(p['indices']).reshape(-1,3).tolist();data=bpy.data.meshes.new(mesh.get('name','Mesh'));data.from_pydata(out.tolist(),[],faces);data.update();o=bpy.data.objects.new(mesh.get('name','Mesh'),data);bpy.context.collection.objects.link(o)
  mn=j['materials'][p['material']]['name'];m=matmap.get(mn)
  if m:data.materials.append(m)
  if 'TEXCOORD_0' in p['attributes']:
   uv=acc(p['attributes']['TEXCOORD_0']);layer=data.uv_layers.new(name='UVMap')
   for loop in data.loops:layer.data[loop.index].uv=(uv[loop.vertex_index,0],1-uv[loop.vertex_index,1])
  for poly in data.polygons:poly.use_smooth=True
  if weights is not None:
   for bi,ix in enumerate(s['joints']):
    group=o.vertex_groups.new(name=j['nodes'][ix].get('name',str(ix)))
    for k in range(4):
     for vi in np.where((ji[:,k]==bi)&(weights[:,k]>0))[0]:group.add([int(vi)],float(weights[vi,k]),'REPLACE')
   mod=o.modifiers.new('Rig','ARMATURE');mod.object=rig;o.parent=rig
  elif node.get('name')=='0':
   group=o.vertex_groups.new(name='mixamorig:Head_06');group.add(list(range(len(data.vertices))),1.0,'REPLACE')
   mod=o.modifiers.new('Head attachment','ARMATURE');mod.object=rig;o.parent=rig
bpy.ops.wm.save_as_mainfile(filepath=str(destination/'tactical.blend'))
bpy.ops.export_scene.gltf(filepath=str(destination/'tactical.glb'),export_format='GLB')
