"""Retarget attributed human-authored clips to the clean tactical skeleton.
blender -b --python retarget_motion.py -- rig.blend motion.glb output_directory
"""
import bpy, sys, pathlib, struct, json, re, math, bisect
import numpy as np
from mathutils import Matrix, Quaternion, Vector
args=sys.argv[sys.argv.index('--')+1:]
if len(args)!=3:raise SystemExit('Expected RIG.blend MOTION.glb OUTPUT_DIRECTORY')
rig_path,source_path,out=map(pathlib.Path,args);out.mkdir(parents=True,exist_ok=True)
b=source_path.read_bytes();n=struct.unpack_from('<I',b,12)[0];doc=json.loads(b[20:20+n]);blob=b[28+n:]
dtypes={5126:'<f4',5123:'<u2',5125:'<u4',5121:'u1'};components={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}
def accessor(index):
 a=doc['accessors'][index];v=doc['bufferViews'][a['bufferView']];dtype=np.dtype(dtypes[a['componentType']]);c=components[a['type']]
 return np.ndarray((a['count'],c),dtype=dtype,buffer=blob,offset=v.get('byteOffset',0)+a.get('byteOffset',0),strides=(v.get('byteStride',c*dtype.itemsize),dtype.itemsize)).copy()
parents={child:i for i,n in enumerate(doc['nodes']) for child in n.get('children',[])}
C=Matrix(((1,0,0,0),(0,0,-1,0),(0,1,0,0),(0,0,0,1)))
def node_matrix(node,overrides):
 if 'matrix' in node:return Matrix(np.array(node['matrix']).reshape(4,4).T.tolist())
 t=Vector(overrides.get('translation',node.get('translation',[0,0,0])));r=overrides.get('rotation',node.get('rotation',[0,0,0,1]));s=Vector(overrides.get('scale',node.get('scale',[1,1,1])))
 return Matrix.LocRotScale(t,Quaternion((r[3],r[0],r[1],r[2])),s)
def world_matrices(overrides):
 cache={}
 def world(i):
  if i not in cache:cache[i]=(world(parents[i]) if i in parents else Matrix.Identity(4))@node_matrix(doc['nodes'][i],overrides.get(i,{}))
  return cache[i]
 return {i:C@world(i) for i in range(len(doc['nodes']))}
def canonical(name):return re.sub(r'_\d+$','',name.split(':')[-1])
source={canonical(n.get('name','')):i for i,n in enumerate(doc['nodes']) if 'mixamorig:' in n.get('name','')}
rest_source=world_matrices({})
bpy.ops.wm.open_mainfile(filepath=str(rig_path));rig=bpy.data.objects['TacticalRig'];rig.animation_data_clear();rig.animation_data_create();scene=bpy.context.scene;scene.render.fps=30
bones=list(rig.data.bones);rest={b.name:b.matrix_local.copy() for b in bones};target={canonical(b.name):b.name for b in bones};mapping={name:source[canonical(name)] for name in rest if canonical(name) in source}
# Canonicalize anatomical directions before computing basis offsets. This avoids
# adding the source's T/A-pose offsets on top of the target's bent source pose.
offsets={}
for bone in bones:
 if bone.name not in mapping:continue
 sid=mapping[bone.name];tr=rest[bone.name].to_quaternion();child=None
 candidates=[b for b in bone.children if b.name in mapping]
 if canonical(bone.name).endswith('Hand'):
  candidates.sort(key=lambda x:0 if 'Middle1' in x.name else 1)
 if candidates:child=candidates[0]
 if child:
  td=rest[child.name].translation-rest[bone.name].translation;sd=rest_source[mapping[child.name]].translation-rest_source[sid].translation
  if td.length>.00001 and sd.length>.00001:tr=td.normalized().rotation_difference(sd.normalized())@tr
 offsets[bone.name]=rest_source[sid].to_quaternion().inverted()@tr
clips={'idle':'ready_idle','walk':'mocap_walk_F@1.1733','run':'mocap_run_F@2.8652','jump':'jump_loop','land':'jump_land','reload':'reload','aim':'aim_idle','walk_reload':'mocap_walk_F@1.1733','run_reload':'mocap_run_F@2.8652'}
hip_id=source['Hips'];hip_target=target['Hips'];target_height=rest[hip_target].translation.z
source_height=rest_source[hip_id].translation.z;ratio=target_height/source_height
saved=[]
def sampler_for(name):
 animation=next(a for a in doc['animations'] if a['name']==name);channels=[];end=0.0
 for channel in animation['channels']:
  sampler=animation['samplers'][channel['sampler']];times=accessor(sampler['input']).reshape(-1).tolist();values=accessor(sampler['output']);channels.append((channel['target']['node'],channel['target']['path'],times,values,sampler.get('interpolation','LINEAR')));end=max(end,times[-1])
 def sample(t):
  over={}
  for node,path,times,values,mode in channels:
   idx=max(0,min(len(times)-2,bisect.bisect_right(times,t)-1));nxt=min(idx+1,len(times)-1);weight=0 if mode=='STEP' or nxt==idx else max(0,min(1,(t-times[idx])/max(1e-9,times[nxt]-times[idx])))
   if path=='rotation':
    a=values[idx];b=values[nxt];q=Quaternion((a[3],*a[:3])).slerp(Quaternion((b[3],*b[:3])),weight);value=[q.x,q.y,q.z,q.w]
   else:value=(values[idx]*(1-weight)+values[nxt]*weight).tolist()
   over.setdefault(node,{})[path]=value
  return world_matrices(over)
 return sample,end
for label,name in clips.items():
 sample,end=sampler_for(name)
 moving=label in ['walk','run','walk_reload','run_reload']
 reloading=label.endswith('_reload')
 base_period=end
 upper_name='reload' if reloading else ('ready_walk' if label=='walk' else 'ready_run')
 upper_sample,upper_end=sampler_for(upper_name) if moving else (None,0)
 if reloading:end=upper_end
 first=sample(0);first_z=first[hip_id].translation.z
 rig.animation_data.action=None
 for p in rig.pose.bones:p.matrix_basis=Matrix.Identity(4)
 action=bpy.data.actions.new(label);action.use_fake_user=True;rig.animation_data.action=action
 count=max(2,round(end*30)+1)
 for frame in range(count):
  posed={};motion=sample((frame/30)%base_period if reloading else min(end,frame/30))
  if upper_sample:
   upper=upper_sample(min(upper_end,frame/30) if reloading else (frame/30)%upper_end);root_rotation=motion[hip_id].to_quaternion()@upper[hip_id].to_quaternion().inverted()
   for key,index in source.items():
    if any(part in key for part in ["Spine","Neck","Head","Shoulder","Arm","Hand"]):
     motion[index]=Matrix.LocRotScale(motion[index].translation,root_rotation@upper[index].to_quaternion(),Vector((1,1,1)))
  for bone in bones:
   parent=bone.parent
   head=(posed[parent.name]@rest[parent.name].inverted()@rest[bone.name]).translation if parent else rest[bone.name].translation.copy()
   if bone.name==hip_target:head.z+=(motion[hip_id].translation.z-first_z)*ratio
   if bone.name in mapping:rotation=motion[mapping[bone.name]].to_quaternion()@offsets[bone.name]
   else:rotation=(posed[parent.name]@rest[parent.name].inverted()@rest[bone.name]).to_quaternion() if parent else rest[bone.name].to_quaternion()
   desired=Matrix.LocRotScale(head,rotation,Vector((1,1,1)));posed[bone.name]=desired
   basis=rest[bone.name].inverted()@(rest[parent.name]@posed[parent.name].inverted() if parent else Matrix.Identity(4))@desired
   pb=rig.pose.bones[bone.name];pb.rotation_mode='QUATERNION';pb.matrix_basis=basis;pb.keyframe_insert('location',frame=frame+1);pb.keyframe_insert('rotation_quaternion',frame=frame+1)
  if label not in ['jump','land']:
   feet=[posed[target[side+'Foot']].translation.z for side in ['Left','Right']]
   sole=min(feet)-.085
   hip_bone=rig.data.bones[hip_target];parent=hip_bone.parent
   corrected=posed[hip_target].copy();corrected.translation.z-=sole
   pb=rig.pose.bones[hip_target]
   pb.matrix_basis=rest[hip_target].inverted()@(rest[parent.name]@posed[parent.name].inverted() if parent else Matrix.Identity(4))@corrected
   pb.keyframe_insert('location',frame=frame+1)
 for curve in action.fcurves:
  for key in curve.keyframe_points:key.interpolation='LINEAR'
 saved.append((label,action));print('RETARGETED',label,count,'frames',flush=True)
rig.animation_data.action=None
for label,action in saved:
 track=rig.animation_data.nla_tracks.new();track.name=label;track.strips.new(label,1,action);track.mute=True
for p in rig.pose.bones:p.matrix_basis=Matrix.Identity(4)
scene.frame_set(1);bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=str(out/'operator_motion.blend'))
for track in rig.animation_data.nla_tracks:track.mute=False
bpy.ops.export_scene.gltf(filepath=str(out/'operator_motion.glb'),export_format='GLB',export_animation_mode='NLA_TRACKS',export_force_sampling=True)
print('TACTICAL_MOTION_EXPORT_PASS',flush=True)
