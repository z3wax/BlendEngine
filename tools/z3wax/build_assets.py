# SPDX-License-Identifier: GPL-2.0-or-later
"""Run with Blender. Source art: Kenney CC0; terrain is original procedural geometry.
blender -b -t 2 --python tools/z3wax/build_assets.py -- /path/to/asset-sources
"""
import bpy, math, random, sys, pathlib, json
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'native/z3wax/assets'; OUT.mkdir(parents=True,exist_ok=True)
SRC=pathlib.Path(sys.argv[sys.argv.index('--')+1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(SRC/'animated-characters-protagonists/Model/characterMedium.fbx'))
rig=next(o for o in bpy.data.objects if o.type=='ARMATURE')
original=set(bpy.data.objects)
for name in ['idle','run','jump']:
 before=set(bpy.data.actions)
 bpy.ops.import_scene.fbx(filepath=str(SRC/f'animated-characters-protagonists/Animations/{name}.fbx'))
 action=next(a for a in set(bpy.data.actions)-before if name.lower() in a.name.lower())
 action.name=name; action.use_fake_user=True
 if not rig.animation_data: rig.animation_data_create()
 track=rig.animation_data.nla_tracks.new();track.name=name
 track.strips.new(name,1,action)
 for o in list(set(bpy.data.objects)-original): bpy.data.objects.remove(o,do_unlink=True)
for mat in bpy.data.materials:
 mat.use_nodes=True
 bs=mat.node_tree.nodes.get('Principled BSDF');bs.inputs['Roughness'].default_value=.8;bs.inputs['Alpha'].default_value=1.0;mat.diffuse_color=(1,1,1,1)
 tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(SRC/'animated-characters-protagonists/Skins/skaterMaleA.png'))
 mat.node_tree.links.new(tex.outputs['Color'],bs.inputs['Base Color'])
rig.animation_data.action=None
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'builds/Z3WAX/character.blend'))
bpy.ops.export_scene.gltf(filepath=str(OUT/'character.glb'),export_format='GLB',export_animation_mode='NLA_TRACKS',export_force_sampling=True)
# One authored Blender outpost used as the initial combat sector.
bpy.ops.wm.read_factory_settings(use_empty=True)
def mat(name,col):
 m=bpy.data.materials.new(name);m.diffuse_color=(*col,1);m.use_nodes=True;m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(*col,1);m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.88;return m
sand=mat('Sun bleached plaster',(.51,.38,.23));metal=mat('Petrol blue steel',(.12,.26,.28));dark=mat('Basalt',(.14,.17,.18));rust=mat('Rust',(.49,.20,.09))
def box(name,p,size,m):
 bpy.ops.mesh.primitive_cube_add(size=1,location=p);o=bpy.context.object;o.name=name;o.dimensions=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(m);return o
rng=random.Random(347)
for i in range(24):
 angle=i*math.tau/24;radius=45+(i%4)*23;x=math.cos(angle)*radius;y=math.sin(angle)*radius
 w=8+i%3*3;d=10;h=5+i%4*2
 # Open doorways: buildings can be entered; collision uses the same walls.
 box(f'Wall_{i}_back',(x,y+d/2,h/2),(w,.6,h),sand)
 for dx in [-w/2,w/2]:box(f'Wall_{i}_side',(x+dx,y,h/2),(.6,d,h),sand)
 for dx in [-w/3,w/3]:box(f'DoorSide_{i}',(x+dx,y-d/2,h/2),(w/3,.6,h),sand)
 box(f'Roof_{i}',(x,y,h),(w+1,d+1,.5),metal)
 for j in range(3):box(f'Cover_{i}_{j}',(x+w+2,y+j*3,1),(2,2,2),rust if j%2 else dark)
# Distinctive relay tower, a central landmark.
for x,y in [(-5,-5),(-5,5),(5,-5),(5,5)]:box('Relay_pylon',(x,y,14),(1,1,28),metal)
for z in [8,16,24]:box('Relay_ring',(0,0,z),(12,12,.5),rust)
# Merge static geometry by material: four batches instead of 223 mesh draws.
for m in [sand,metal,dark,rust]:
 objects=[o for o in bpy.data.objects if o.type=='MESH' and o.data.materials and o.data.materials[0]==m]
 bpy.ops.object.select_all(action='DESELECT')
 for o in objects:o.select_set(True)
 bpy.context.view_layer.objects.active=objects[0];bpy.ops.object.join()
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'builds/Z3WAX/disland_outpost.blend'))
bpy.ops.export_scene.gltf(filepath=str(OUT/'outpost.glb'),export_format='GLB')
print('Z3WAX_BLENDER_EXPORT_PASS')
