# SPDX-License-Identifier: GPL-2.0-or-later
"""Export the supported Last Signal adapter to a native glTF runtime.

This runs inside Blender; it never changes the saved source .blend file.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

import bpy


def _deduplicate_embedded_images(path):
    """Share byte-identical image payloads without recompressing any pixels."""
    raw=path.read_bytes()
    json_size,json_type=struct.unpack_from('<II',raw,12)
    document=json.loads(raw[20:20+json_size])
    binary_start=20+json_size
    binary_size,binary_type=struct.unpack_from('<II',raw,binary_start)
    binary=raw[binary_start+8:binary_start+8+binary_size]
    views=document['bufferViews']
    images=[]
    image_map={}
    canonical_views={}
    seen={}
    for index,image in enumerate(document.get('images',[])):
        view=views[image['bufferView']]
        start=view.get('byteOffset',0)
        key=(image.get('mimeType'),hashlib.sha256(binary[start:start+view['byteLength']]).digest())
        if key in seen:
            image_map[index]=seen[key]
            canonical_views[image['bufferView']]=images[seen[key]]['bufferView']
        else:
            image_map[index]=len(images)
            seen[key]=len(images)
            images.append(image)
    if len(images)==len(document.get('images',[])):
        return {'duplicate_images':0,'bytes_saved':0}
    rebuilt=bytearray()
    offsets={}
    for index,view in enumerate(views):
        if view.get('buffer',0)!=0:
            raise ValueError('Expected a self-contained GLB buffer')
        canonical=canonical_views.get(index,index)
        if canonical not in offsets:
            while len(rebuilt)%4:
                rebuilt.append(0)
            original=views[canonical]
            start=original.get('byteOffset',0)
            offsets[canonical]=len(rebuilt)
            rebuilt.extend(binary[start:start+original['byteLength']])
        # Keep bufferView indices stable for geometry, skins and animations.
        view['byteOffset']=offsets[canonical]
    duplicate_count=len(document['images'])-len(images)
    document['images']=images
    for texture in document.get('textures',[]):
        if 'source' in texture:
            texture['source']=image_map[texture['source']]
    document['buffers'][0]['byteLength']=len(rebuilt)
    encoded=json.dumps(document,separators=(',',':'),ensure_ascii=False).encode('utf8')
    encoded+=b' '*((-len(encoded))%4)
    rebuilt.extend(b'\0'*((-len(rebuilt))%4))
    total=12+8+len(encoded)+8+len(rebuilt)
    result=(struct.pack('<III',0x46546c67,2,total)+struct.pack('<II',len(encoded),json_type)+encoded+
            struct.pack('<II',len(rebuilt),binary_type)+rebuilt)
    path.write_bytes(result)
    return {'duplicate_images':duplicate_count,'bytes_saved':len(raw)-len(result)}


def _native_agents(scene):
    """NPC visuals reuse the player's portable native rig instead of rebaking it."""
    supported = {'IDLE', 'PATROL', 'FOLLOW_PLAYER', 'GUARD', 'GUIDE'}
    agents, excluded = [], set()
    for obj in scene.objects:
        npc = obj.blendengine_object.npc_behavior
        if not npc.enabled:
            continue
        if npc.behavior_template not in supported:
            raise ValueError('Native NPC behavior is not supported: ' + npc.behavior_template)
        if not math.isfinite(npc.move_speed) or not 0 <= npc.move_speed <= 6:
            raise ValueError('Native NPC speed must be between 0 and 6: ' + obj.name)
        if len(agents) >= 8:
            raise ValueError('The native story adapter supports at most 8 NPC agents')
        agents.append({'name': obj.name, 'behavior': npc.behavior_template,
            'position': list(obj.matrix_world.translation), 'speed': npc.move_speed,
            'stop_distance': getattr(npc, 'stop_distance', 1.4),
            'decision_interval': getattr(npc, 'decision_interval', .15),
            'detection_range': npc.detection_range, 'patrol_radius': npc.patrol_radius})
        excluded.add(obj)
        excluded.update(obj.children_recursive)
    return agents, excluded


def _scratch_scene(source, excluded=()):
    scratch=bpy.data.scenes.new('Native asset export scratch')
    copied={}
    for obj in source.objects:
        if obj in excluded:
            continue
        clone=obj.copy()
        if obj.data is not None:
            clone.data=obj.data.copy()
        scratch.collection.objects.link(clone)
        copied[obj]=clone
    for original,clone in copied.items():
        if original.parent is not None:
            clone.parent=copied.get(original.parent)
        for modifier in clone.modifiers:
            if modifier.type=='ARMATURE' and modifier.object in copied:
                modifier.object=copied[modifier.object]
        if clone.type=='MESH':
            for i,material in enumerate(clone.data.materials):
                if material is not None:
                    clone.data.materials[i]=material.copy()
    scratch.camera=copied.get(source.camera)
    return scratch,copied


def _bake_meshes(scene,out):
    """Bake real Blender procedural color and tangent-space bump to UV atlases."""
    scene.render.engine='CYCLES'
    scene.cycles.device='CPU'
    scene.cycles.samples=1
    scene.render.bake.margin=8
    scene.render.bake.use_clear=True
    report=[]
    for index,obj in enumerate(scene.objects):
        if obj.type!='MESH' or obj.hide_render or not obj.data.polygons:
            continue
        mats=[m for m in obj.data.materials if m is not None]
        if not any(m.use_nodes and any(n.type=='TEX_NOISE' for n in m.node_tree.nodes) for m in mats):
            continue
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active=obj
        for modifier in list(obj.modifiers):
            if modifier.type!='ARMATURE':
                bpy.ops.object.modifier_apply(modifier=modifier.name)
        if not obj.data.uv_layers:
            obj.data.uv_layers.new(name='NativeUV')
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=math.radians(66),island_margin=.018)
        bpy.ops.object.mode_set(mode='OBJECT')
        size=1024
        color=bpy.data.images.new('native_color_%02d'%index,width=size,height=size,alpha=False)
        normal=bpy.data.images.new('native_normal_%02d'%index,width=size,height=size,alpha=False)
        normal.colorspace_settings.name='Non-Color'
        records=[]
        for mat in mats:
            nodes,links=mat.node_tree.nodes,mat.node_tree.links
            shader=next((n for n in nodes if n.type=='BSDF_PRINCIPLED'),None)
            output=next((n for n in nodes if n.type=='OUTPUT_MATERIAL'),None)
            if shader is None or output is None:
                continue
            target=nodes.new('ShaderNodeTexImage')
            target.image=color
            nodes.active=target
            original=output.inputs['Surface'].links[0].from_socket if output.inputs['Surface'].links else None
            emission=nodes.new('ShaderNodeEmission')
            socket=shader.inputs['Base Color']
            if socket.is_linked:
                links.new(socket.links[0].from_socket,emission.inputs['Color'])
            else:
                emission.inputs['Color'].default_value=socket.default_value
            links.new(emission.outputs[0],output.inputs['Surface'])
            records.append((mat,shader,output,original,emission,target))
        bpy.ops.object.bake(type='EMIT')
        for mat,shader,output,original,emission,target in records:
            links=mat.node_tree.links
            if original is not None:
                links.new(original,output.inputs['Surface'])
            mat.node_tree.nodes.remove(emission)
            target.image=normal
            mat.node_tree.nodes.active=target
        bpy.ops.object.bake(type='NORMAL',normal_space='TANGENT')
        for mat,shader,output,original,emission,target in records:
            nodes,links=mat.node_tree.nodes,mat.node_tree.links
            color_tex=nodes.new('ShaderNodeTexImage')
            color_tex.image=color
            links.new(color_tex.outputs['Color'],shader.inputs['Base Color'])
            normal_tex=nodes.new('ShaderNodeTexImage')
            normal_tex.image=normal
            normal_map=nodes.new('ShaderNodeNormalMap')
            links.new(normal_tex.outputs['Color'],normal_map.inputs['Color'])
            links.new(normal_map.outputs['Normal'],shader.inputs['Normal'])
            nodes.remove(target)
        for image in (color,normal):
            image.filepath_raw=str((out/(image.name+'.png')).resolve())
            image.file_format='PNG'
            image.save()
        report.append({'object':obj.name,'atlas_size':size,'base_color':color.name+'.png','normal':normal.name+'.png'})
        print('NATIVE_BAKE',obj.name,flush=True)
    return report


def _animations(rig):
    rig.animation_data_create()
    rig.animation_data.action=None
    for track in list(rig.animation_data.nla_tracks):
        rig.animation_data.nla_tracks.remove(track)
    for name in ('Idle','Walk'):
        action=bpy.data.actions.new(name)
        rig.animation_data.action=action
        for frame in range(1,26):
            phase=(frame-1)*math.tau/24
            for bone in rig.pose.bones:
                bone.rotation_mode='XYZ'
                bone.rotation_euler=(0,0,0)
            for side,sign in (('L',1),('R',-1)):
                rig.pose.bones['arm.'+side].rotation_euler.x=-1.3
                rig.pose.bones['forearm.'+side].rotation_euler.z=.10*sign
                if name=='Walk':
                    swing=math.sin(phase)*.42
                    rig.pose.bones['leg.'+side].rotation_euler.x=swing*sign
                    rig.pose.bones['calf.'+side].rotation_euler.x=max(0,-swing*sign)*1.1
                    rig.pose.bones['arm.'+side].rotation_euler.z=-swing*sign*.4
            for bone in rig.pose.bones:
                bone.keyframe_insert('rotation_euler',frame=frame,group=bone.name)
        rig.animation_data.action=None
        track=rig.animation_data.nla_tracks.new()
        track.name=name
        track.strips.new(name,1,action)
    rig.animation_data.action=None
    bpy.context.scene.frame_set(1)


def export_scene_assets(scene,output_dir):
    if scene.get('blendengine_story')!='LAST_SIGNAL':
        raise ValueError('Native Android adapter currently supports Last Signal scenes only')
    out=Path(output_dir)
    out.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'scripts/addons_core'))
    from blendengine import story_game
    path=out/'last_signal.glb'
    original_scene=bpy.context.window.scene
    owned_data={name:set(getattr(bpy.data,name)) for name in
                ('meshes','armatures','lights','cameras','materials','images','actions')}
    agents, excluded = _native_agents(scene)
    scratch,copies=_scratch_scene(scene, excluded)
    try:
        bpy.context.window.scene=scratch
        bpy.context.view_layer.update()
        baked=_bake_meshes(scratch,out)
        rig=copies[scene.objects[scene['story_rig']]]
        _animations(rig)
        bpy.ops.object.select_all(action='DESELECT')
        for obj in scratch.objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active=rig
        bpy.ops.export_scene.gltf(filepath=str(path.resolve()),export_format='GLB',use_selection=True,use_active_scene=True,
                                  export_animations=True,export_nla_strips=True,export_force_sampling=True,
                                  export_rest_position_armature=True,export_yup=True,export_skins=True,
                                  export_cameras=True,export_lights=True,export_extras=True)
        image_sharing=_deduplicate_embedded_images(path)
        # glTF embeds these exact PNG bytes. Keep one portable source artifact,
        # rather than shipping loose duplicate atlases alongside the GLB.
        for entry in baked:
            entry['embedded_in']='last_signal.glb'
            for channel in ('base_color','normal'):
                (out/entry[channel]).unlink(missing_ok=True)
    finally:
        bpy.context.window.scene=original_scene
        for obj in list(scratch.objects):
            bpy.data.objects.remove(obj,do_unlink=True)
        bpy.data.scenes.remove(scratch)
        # Export copies must not accumulate on repeated exports in the editor.
        for name,existing in owned_data.items():
            collection=getattr(bpy.data,name)
            for block in list(collection):
                if block not in existing and block.users==0:
                    collection.remove(block)
    data={'adapter':'LAST_SIGNAL','title':'Last Signal','spawn':list(story_game.SPAWN),
          'items':[list(p) for p in story_game.ITEMS],'goal':list(story_game.GOAL),
          'waypoints':[list(p) for p in story_game.WAYPOINTS],
          'journal':[list(p) for p in story_game.JOURNAL],
          'coordinate_system':'BLENDER_Z_UP',
          'npc_agents': agents,
          'baked_textures':baked,
          'lossless_image_sharing':image_sharing,
          'native_backend':'Godot C++ / OpenGL ES; not Blender EEVEE on Android',
          'source':'BlendEngine Last Signal; existing project human mesh; procedural materials'}
    (out/'story.json').write_text(json.dumps(data,indent=2)+'\n')
    return {'glb':str(path),'metadata':str(out/'story.json')}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/addons_core'))
    import blendengine
    blendengine.register()
    print(export_scene_assets(bpy.context.scene,args.output_dir))


if __name__=='__main__':
    main()
