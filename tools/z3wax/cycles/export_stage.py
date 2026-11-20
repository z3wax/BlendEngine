# SPDX-License-Identifier: Apache-2.0
"""Blender evaluated-mesh -> repository Cycles XML snapshot export.
Run inside Blender: blender -b stage.blend --python export_stage.py -- OUTPUT_DIR HDRI
Exports supported PBR node graphs; unsupported connected nodes fail explicitly.
This snapshot exporter does not export animation, Godot shaders, UI, or fog.
"""
import bpy, sys, pathlib, xml.etree.ElementTree as ET, math, json, hashlib, array, shutil
from mathutils import Matrix
args=sys.argv[sys.argv.index('--')+1:]
out=pathlib.Path(args[0]); out.mkdir(parents=True,exist_ok=True)
textures=out/'textures'; textures.mkdir(exist_ok=True)
root=ET.Element('cycles')
ET.SubElement(root,'integrator',seed='41',use_adaptive_sampling='false',use_denoise='false',
 max_bounce='12',max_diffuse_bounce='12',max_glossy_bounce='12',max_transmission_bounce='12',
 max_volume_bounce='12',transparent_max_bounce='12',sample_clamp_direct='0',sample_clamp_indirect='0')

def fmt(value):
 if isinstance(value,(int,float)):return format(value,'.9g')
 return ' '.join(format(v,'.9g') for v in value)
def node(parent,kind,**attrs):return ET.SubElement(parent,kind,{k:fmt(v) if not isinstance(v,str) else v for k,v in attrs.items()})
def connect(parent,source,target):node(parent,'connect',**{'from':source,'to':target})
def matrix_attribute(m):return fmt([m[r][c] for c in range(4) for r in range(4)])
image_paths={}
def image_path(image):
 if image.name not in image_paths:
  target=textures/(str(len(image_paths))+'.png')
  image.filepath_raw=str(target);image.file_format='PNG';image.save()
  image_paths[image.name]='textures/'+target.name
 return image_paths[image.name]

# Cycles and Blender both use Z up; Cycles camera looks along local +Z.
camera=next(o for o in bpy.data.objects if o.type=='CAMERA')
tfm=camera.matrix_world @ Matrix.Diagonal((1,1,-1,1))
t=node(root,'transform',matrix=matrix_attribute(tfm))
node(t,'camera',width=640,height=360,fov=camera.data.angle_y)
# Explicit art lighting for this Cycles snapshot, independent of Godot's raster environment.
bg=node(root,'background')
shutil.copyfile(args[1],out/'environment.hdr')
node(bg,'environment_texture',name='panorama',filename='environment.hdr',colorspace='raw')
node(bg,'background',name='sky',strength=.7)
connect(bg,'panorama color','sky color');connect(bg,'sky background','output surface')
node(root,'light',light_type='background',use_mis='true')
for obj in bpy.data.objects:
 if obj.type=='LIGHT' and obj.data.type=='SUN':
  direction=obj.matrix_world.to_quaternion() @ __import__('mathutils').Vector((0,0,-1))
  color=obj.data.color
  node(root,'light',light_type='distant',dir=fmt(direction),strength=fmt([v*obj.data.energy for v in color]),angle=obj.data.angle)

material_ids={}; warnings=set()
def material_id(material):
 if material is None:raise RuntimeError('Mesh has no material')
 if material.name in material_ids:return material_ids[material.name]
 mid='material_'+str(len(material_ids));material_ids[material.name]=mid
 shader=node(root,'shader',name=mid)
 output=next(n for n in material.node_tree.nodes if n.type=='OUTPUT_MATERIAL' and n.is_active_output)
 converted={}
 def convert(n):
  if n.name in converted:return converted[n.name]
  ident='n'+str(len(converted));converted[n.name]=ident
  links=[];outputs={};defaults={}
  def inp(blender_name,cycles_name):
   socket=n.inputs.get(blender_name)
   if socket is None:return
   if socket.is_linked:links.append((socket.links[0],cycles_name))
   elif socket.type in {'RGBA','VECTOR'}:defaults[cycles_name]=fmt(list(socket.default_value)[:3])
   else:defaults[cycles_name]=fmt(socket.default_value)
  if n.type=='BSDF_PRINCIPLED':
   kind='principled_bsdf';outputs={'BSDF':'BSDF'}
   for a,b in [('Base Color','base_color'),('Metallic','metallic'),('Roughness','roughness'),('IOR','ior'),('Specular IOR Level','specular'),('Alpha','alpha'),('Normal','normal'),('Emission Color','emission'),('Emission Strength','emission_strength')]:inp(a,b)
  elif n.type=='TEX_IMAGE':
   kind='image_texture';outputs={'Color':'color','Alpha':'alpha'}
   defaults.update(filename=image_path(n.image),colorspace='sRGB' if n.image.colorspace_settings.name=='sRGB' else 'raw')
   inp('Vector','vector')
  elif n.type=='NORMAL_MAP':
   kind='normal_map';outputs={'Normal':'normal'};inp('Color','color');inp('Strength','strength')
  elif n.type=='SEPARATE_COLOR' and n.mode=='RGB':
   kind='separate_color';outputs={'Red':'r','Green':'g','Blue':'b'};inp('Color','color')
  elif n.type=='MATH' and n.operation in {'MULTIPLY','ADD','SUBTRACT','DIVIDE'}:
   kind='math';outputs={'Value':'value'};defaults['math_type']=n.operation.lower()
   for i in range(2):
    socket=n.inputs[i];key='value'+str(i+1)
    if socket.is_linked:links.append((socket.links[0],key))
    else:defaults[key]=fmt(socket.default_value)
  elif n.type=='UVMAP':
   kind='texture_coordinate';outputs={'UV':'UV'}
  elif n.type=='MAPPING':
   kind='mapping';outputs={'Vector':'vector'};defaults['mapping_type']=n.vector_type.lower()
   for a,b in [('Vector','vector'),('Location','location'),('Rotation','rotation'),('Scale','scale')]:inp(a,b)
  elif n.type=='MIX' and n.data_type=='RGBA' and n.blend_type=='MULTIPLY':
   kind='mix';outputs={'Result':'color'};defaults['mix_type']='multiply'
   # The glTF base-color factor uses factor=1 and the active color sockets.
   defaults['fac']=fmt(n.inputs[0].default_value)
   for i,key in [(6,'color1'),(7,'color2')]:
    socket=n.inputs[i]
    if socket.is_linked:links.append((socket.links[0],key))
    else:defaults[key]=fmt(list(socket.default_value)[:3])
  elif n.type=='EMISSION':
   kind='emission';outputs={'Emission':'emission'};inp('Color','color');inp('Strength','strength')
  else:raise RuntimeError('Unsupported connected node '+material.name+': '+n.type)
  element=node(shader,kind,name=ident,**defaults)
  # Cycles XML sockets use internal names, not Blender display names with spaces.
  for link,target in links:
   previous=convert(link.from_node)
   connect(shader,previous[0]+' '+previous[1][link.from_socket.name],ident+' '+target)
  converted[n.name]=(ident,outputs)
  return converted[n.name]
 # Unlit helper meshes (billboard text) are excluded from this 3D snapshot explicitly.
 surface=output.inputs['Surface']
 if not surface.is_linked:raise RuntimeError('Unconnected material '+material.name)
 link=surface.links[0]
 result=convert(link.from_node)
 connect(shader,result[0]+' '+result[1][link.from_socket.name],'output surface')
 return mid

objects=[];shared_geometry={};deps=bpy.context.evaluated_depsgraph_get()
for obj in bpy.context.scene.objects:
 if obj.type!='MESH' or obj.hide_render:continue
 if any(m and any(n.type=='LIGHT_PATH' for n in m.node_tree.nodes) for m in obj.data.materials if m.use_nodes):
  warnings.add('Unlit helper mesh omitted: '+obj.name);continue
 evaluated=obj.evaluated_get(deps);mesh=evaluated.to_mesh()
 mesh.calc_loop_triangles()
 if mesh.uv_layers:mesh.calc_tangents()
 # Content-address identical evaluated geometry, even if glTF duplicated mesh names.
 # No rounding, simplification or approximate matching is used.
 digest=hashlib.sha256()
 for collection,attribute,count,typecode in [(mesh.vertices,'co',3,'f'),(mesh.loops,'vertex_index',1,'i'),(mesh.loops,'normal',3,'f'),(mesh.polygons,'material_index',1,'i')]:
  values=array.array(typecode,[0])*(len(collection)*count)
  collection.foreach_get(attribute,values);digest.update(values.tobytes())
 if mesh.uv_layers:
  values=array.array('f',[0])*(len(mesh.uv_layers.active.data)*2)
  mesh.uv_layers.active.data.foreach_get('uv',values);digest.update(values.tobytes())
 geometry_hash=digest.hexdigest()
 world=obj.matrix_world
 for mi,material in enumerate(mesh.materials):
  tris=[t for t in mesh.loop_triangles if t.material_index==mi]
  if not tris:continue
  mid=material_id(material)
  key=(geometry_hash,mi,material.name)
  transform=node(root,'transform',matrix=matrix_attribute(world))
  if key is not None and key in shared_geometry:
   node(transform,'instance',object=shared_geometry[key])
   objects.append(dict(name=obj.name,material=material.name,triangles=len(tris),instance_of=shared_geometry[key]))
   continue
  if key is not None:shared_geometry[key]=len(objects)
  positions=[];normals=[];uv=[];tangents=[];signs=[]
  for tri in tris:
   for li in tri.loops:
    loop=mesh.loops[li]
    positions.extend(mesh.vertices[loop.vertex_index].co)
    normals.extend(loop.normal)
    if mesh.uv_layers:
     uv.extend(mesh.uv_layers.active.data[li].uv)
     tangents.extend(loop.tangent)
     signs.append(loop.bitangent_sign)
  state=node(transform,'state',shader=mid,smooth='true')
  attrs=dict(P=fmt(positions),N=fmt(normals),verts=fmt(range(len(positions)//3)),nverts=fmt([3]*len(tris)))
  if uv:attrs.update(UV=fmt(uv),T=fmt(tangents),TS=fmt(signs))
  node(state,'mesh',**attrs)
  objects.append(dict(name=obj.name,material=material.name,triangles=len(tris)))
 evaluated.to_mesh_clear()
ET.ElementTree(root).write(out/'scene.xml',encoding='utf-8',xml_declaration=True)
(out/'export-report.json').write_text(json.dumps(dict(objects=objects,warnings=sorted(warnings),
 omitted_features=['Godot UI','Godot fog','animation after snapshot','Godot-specific shaders'],
 renderer='Repository Cycles 3.6',quality_claim='No parity claim with Godot or concept artwork'),indent=2))
print('CYCLES_SNAPSHOT_EXPORTED',len(objects),'surfaces',sum(o['triangles'] for o in objects),'triangles')
