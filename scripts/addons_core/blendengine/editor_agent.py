# SPDX-License-Identifier: GPL-2.0-or-later
"""Native scene assistant with bounded tools and optional background inference."""

import json
import os
import queue
import threading
import uuid

import bpy
from bpy.app.handlers import persistent

from . import agent_core, agent_provider, ai_system


_jobs = {}
_timer_active = False
_plan_refs = {}


def scene_context(context):
    scene = context.scene
    selected = list(context.selected_objects)
    if len(selected) > 32:
        raise ValueError('The scene agent edits at most 32 selected objects per plan.')
    objects = sorted(scene.objects, key=lambda obj: (obj not in selected, obj.name))
    return {
        "selected": [obj.name for obj in context.selected_objects if obj.name in scene.objects],
        "objects": [{"name": obj.name, "type": obj.type,
                     "location": list(obj.location), "scale": list(obj.scale)} for obj in objects[:64]],
        "stats": {"objects": len(objects), "triangles": sum(
            max(0, len(obj.data.loops) - 2 * len(obj.data.polygons))
            for obj in objects if obj.type == 'MESH'),
            "materials": len({mat for obj in objects if obj.type == 'MESH'
                              for mat in obj.data.materials if mat})},
    }


def _snapshot(scene, selected, names=None):
    token = uuid.uuid4().hex
    objects = {obj.name: obj for obj in scene.objects
               if names is None or obj.name in names}
    _plan_refs[token] = {'scene': scene, 'objects': objects}
    while len(_plan_refs) > 32:
        _plan_refs.pop(next(iter(_plan_refs)))
    return {"scene": scene.as_pointer(), "selected": selected, "token": token,
            "objects": {name: obj.as_pointer() for name, obj in objects.items()}}


def _forget(snapshot_json):
    try:
        _plan_refs.pop(json.loads(snapshot_json).get('token'), None)
    except (ValueError, TypeError):
        pass


def _accept_plan(scene, plan, context_data, snapshot):
    settings = scene.blendengine_agent
    plan = agent_core.validate_plan(plan, context_data)
    settings.plan_json = json.dumps(plan, ensure_ascii=False) if plan['actions'] else ''
    settings.snapshot_json = json.dumps(snapshot) if plan['actions'] else ''
    if not plan['actions']:
        _plan_refs.pop(snapshot['token'], None)
    settings.reply = plan['summary']
    settings.status = 'READY' if plan['actions'] else 'IDLE'


def _tag_redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _poll_jobs():
    global _timer_active
    for identity, job in list(_jobs.items()):
        try:
            kind, value = job['results'].get_nowait()
        except queue.Empty:
            continue
        _jobs.pop(identity, None)
        scene = job['owner']
        try:
            alive = scene.as_pointer() == identity and scene.name in bpy.data.scenes
        except ReferenceError:
            alive = False
        if not alive or job['cancel'].is_set():
            _plan_refs.pop(job['snapshot']['token'], None)
            continue
        settings = scene.blendengine_agent
        if kind == 'ok':
            try:
                _accept_plan(scene, value, job['context'], job['snapshot'])
            except (ValueError, KeyError, TypeError) as error:
                _plan_refs.pop(job['snapshot']['token'], None)
                settings.status, settings.reply = 'ERROR', str(error)
        else:
            _plan_refs.pop(job['snapshot']['token'], None)
            settings.status, settings.reply = 'ERROR', value
    _tag_redraw()
    if _jobs:
        return .1
    _timer_active = False
    return None


@persistent
def _cancel_jobs(_unused=None):
    global _timer_active
    for job in _jobs.values():
        job['cancel'].set()
    _jobs.clear()
    _plan_refs.clear()
    if bpy.app.timers.is_registered(_poll_jobs):
        bpy.app.timers.unregister(_poll_jobs)
    _timer_active = False


class BE_EditorAgentSettings(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty(name="Request", default="Sahnani tahlil qil", maxlen=2000)
    mode: bpy.props.EnumProperty(name="Planner", items=(
        ('LOCAL', 'Offline tools', 'Uzbek and English commands; no language model or network'),
        ('MODEL', 'Language model', 'Send a limited scene summary to your configured model endpoint')),
        default='LOCAL')
    endpoint: bpy.props.StringProperty(name="Model endpoint", default="http://127.0.0.1:8000/v1")
    model: bpy.props.StringProperty(name="Model", default="local-model")
    key_env: bpy.props.StringProperty(name="API key environment variable", default="BLENDENGINE_AI_API_KEY")
    status: bpy.props.StringProperty(default='IDLE', options={'SKIP_SAVE'})
    reply: bpy.props.StringProperty(options={'SKIP_SAVE'})
    plan_json: bpy.props.StringProperty(options={'SKIP_SAVE'})
    snapshot_json: bpy.props.StringProperty(options={'SKIP_SAVE'})


class BE_OT_agent_plan(bpy.types.Operator):
    bl_idname = 'blendengine.agent_plan'
    bl_label = 'Make Plan'
    bl_description = 'Plan scene tools; changes are applied only with Apply Plan'

    def execute(self, context):
        global _timer_active
        scene, settings = context.scene, context.scene.blendengine_agent
        if scene.blendengine_project.test_running:
            self.report({'WARNING'}, 'Stop Play before editing the scene.')
            return {'CANCELLED'}
        identity = scene.as_pointer()
        if identity in _jobs:
            self.report({'WARNING'}, 'A model request is already running.')
            return {'CANCELLED'}
        try:
            data = scene_context(context)
        except ValueError as error:
            settings.status, settings.reply = 'ERROR', str(error)
            return {'CANCELLED'}
        _forget(settings.snapshot_json)
        snapshot = _snapshot(scene, data['selected'], {obj['name'] for obj in data['objects']})
        settings.plan_json = settings.snapshot_json = ''
        try:
            if settings.mode == 'LOCAL':
                _accept_plan(scene, agent_core.plan_request(settings.prompt, data), data, snapshot)
            else:
                # Copy plain data on the main thread. The worker never accesses bpy.
                cancel, results = threading.Event(), queue.Queue()
                prompt, endpoint, model = settings.prompt, settings.endpoint, settings.model
                api_key = os.environ.get(settings.key_env) if settings.key_env else None

                def run():
                    try:
                        result = agent_provider.request_plan(prompt, data, endpoint=endpoint,
                            model=model, api_key=api_key, cancel_event=cancel)
                        results.put(('ok', result))
                    except Exception as error:
                        # ProviderError messages deliberately exclude credentials/raw HTTP bodies.
                        results.put(('error', str(error)))

                _jobs[identity] = {'owner': scene, 'cancel': cancel, 'results': results,
                                   'context': data, 'snapshot': snapshot}
                settings.status, settings.reply = 'RUNNING', 'Waiting for the configured model…'
                threading.Thread(target=run, daemon=True, name='BlendEngine scene agent').start()
                if not _timer_active:
                    bpy.app.timers.register(_poll_jobs, first_interval=.1)
                    _timer_active = True
        except (ValueError, TypeError) as error:
            _plan_refs.pop(snapshot['token'], None)
            settings.status, settings.reply = 'ERROR', str(error)
            return {'CANCELLED'}
        _tag_redraw()
        return {'FINISHED'}


class BE_OT_agent_cancel(bpy.types.Operator):
    bl_idname = 'blendengine.agent_cancel'
    bl_label = 'Cancel Request'

    def execute(self, context):
        job = _jobs.pop(context.scene.as_pointer(), None)
        if job:
            job['cancel'].set()
            _plan_refs.pop(job['snapshot']['token'], None)
        settings = context.scene.blendengine_agent
        _forget(settings.snapshot_json)
        settings.status, settings.reply = 'IDLE', 'Request cancelled. The scene was not changed.'
        return {'FINISHED'}


def _target_objects(scene, reference, snapshot, planned):
    names = snapshot['selected'] if reference == '@selected' else [reference]
    if not names:
        raise ValueError('Select an object before planning this operation.')
    result = []
    for name in names:
        obj = scene.objects.get(name)
        if name not in planned:
            reference = _plan_refs.get(snapshot.get('token'), {}).get('objects', {}).get(name)
            try:
                same = obj is not None and reference is not None and reference.name == name and reference == obj
            except ReferenceError:
                same = False
            if not same:
                raise ValueError('The target changed after planning: ' + name)
        result.append(obj)
    return result


_NPC_FIELDS = ('enabled', 'behavior_template', 'target_object', 'move_speed', 'patrol_radius',
               'detection_range', 'attack_range', 'dialogue_text', 'quest_id', 'stop_distance',
               'decision_interval', 'avoid_obstacles')


def _material_target(obj):
    if obj.hide_render:
        visible = next((child for child in obj.children_recursive
                        if child.type == 'MESH' and not child.hide_render), None)
        if visible is not None:
            return visible
    return obj


def _color(obj, value):
    obj = _material_target(obj)
    if obj.type == 'LIGHT':
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        obj.data.color = value
        return
    if obj.type != 'MESH':
        raise ValueError('Material tools require a mesh or light: ' + obj.name)
    # A linked duplicate should not recolor all objects sharing its mesh.
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    originals = list(obj.data.materials) or [None]
    copies = {}
    for index, original in enumerate(originals):
        if original not in copies:
            material = original.copy() if original else bpy.data.materials.new('Agent | ' + obj.name)
            material.use_nodes = True
            shader = next((node for node in material.node_tree.nodes
                           if node.type == 'BSDF_PRINCIPLED'), None)
            if shader is None:
                raise ValueError('This material uses a custom shader; edit its color in the Material Editor.')
            material.diffuse_color = (*value, 1)
            color = shader.inputs['Base Color']
            if color.is_linked:
                source = color.links[0].from_socket
                tint = material.node_tree.nodes.new('ShaderNodeMixRGB')
                tint.blend_type = 'MULTIPLY'
                tint.inputs[0].default_value = 1
                tint.inputs[2].default_value = (*value, 1)
                material.node_tree.links.new(source, tint.inputs[1])
                material.node_tree.links.new(tint.outputs[0], color)
            else:
                color.default_value = (*value, 1)
            copies[original] = material
        if index < len(obj.data.materials):
            obj.data.materials[index] = copies[original]
        else:
            obj.data.materials.append(copies[original])


def apply_plan(context, plan, snapshot):
    """Validate everything, then apply an undoable batch; roll back failed batches."""
    scene = context.scene
    owner = _plan_refs.get(snapshot.get('token'), {}).get('scene')
    try:
        same_scene = owner is not None and owner.name == scene.name and owner == scene
    except ReferenceError:
        same_scene = False
    if not same_scene or snapshot.get('scene') != scene.as_pointer():
        raise ValueError('This plan belongs to a different scene.')
    data = scene_context(context)
    data['selected'] = snapshot['selected']
    plan = agent_core.validate_plan(plan, data)
    planned = set()
    touched = {}
    for action in plan['actions']:
        tool = action['tool']
        if tool in ('create_object', 'create_npc'):
            if scene.objects.get(action['name']):
                raise ValueError('Name already exists: ' + action['name'])
            planned.add(action['name'])
        elif 'object' in action:
            for obj in _target_objects(scene, action['object'], snapshot, planned):
                if obj is None:  # Created earlier in this same plan.
                    continue
                if tool == 'set_material':
                    obj = _material_target(obj)
                if tool == 'set_material' and obj.type not in {'MESH', 'LIGHT'}:
                    raise ValueError('Select a mesh or light for material changes.')
                npc = obj.blendengine_object.npc_behavior
                touched[obj] = (obj.location.copy(), obj.data,
                    list(obj.data.materials) if obj.type == 'MESH' else None,
                    tuple(obj.data.color) if obj.type == 'LIGHT' else None,
                    {field: getattr(npc, field) for field in _NPC_FIELDS if hasattr(npc, field)},
                    len(obj.blendengine_object.components),
                    (obj.blendengine_object.is_game_object, obj.blendengine_object.object_tag,
                     obj.blendengine_object.active_component_index))
    owned = {name: set(getattr(bpy.data, name)) for name in
             ('objects', 'meshes', 'materials', 'armatures', 'lights', 'actions')}
    selection = list(context.selected_objects)
    active = context.view_layer.objects.active
    created = {}
    try:
        for action in plan['actions']:
            tool = action['tool']
            if tool == 'create_object':
                kind = action['kind']
                if kind == 'CUBE':
                    bpy.ops.mesh.primitive_cube_add()
                elif kind == 'SPHERE':
                    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8)
                elif kind == 'PLANE':
                    bpy.ops.mesh.primitive_plane_add()
                else:
                    bpy.ops.object.light_add(type='AREA')
                    context.object.data.energy = 600
                    context.object.data.size = 4
                obj = context.object
                obj.name = action['name']
                obj.location, obj.scale = action['location'], action['scale']
                _color(obj, action['color'])
                created[action['name']] = obj
            elif tool == 'create_npc':
                obj = ai_system.create_agent(context, name=action['name'], behavior=action['behavior'],
                    location=action['location'], speed=action['speed'])
                created[action['name']] = obj
            elif tool == 'audit':
                continue
            else:
                names = snapshot['selected'] if action['object'] == '@selected' else [action['object']]
                for name in names:
                    obj = created.get(name) or scene.objects[name]
                    if tool == 'transform_object':
                        obj.location = action['location']
                    elif tool == 'set_material':
                        _color(obj, action['color'])
                    elif tool == 'set_npc':
                        target = next((o for o in scene.objects
                            if o.blendengine_object.player_controller.enabled), None)
                        npc = ai_system.apply_template(obj, template=action['behavior'], target=target)
                        npc.move_speed = action['speed']
    except Exception:
        for obj, (location, original_data, materials, color, npc_values, count, role) in touched.items():
            obj.location = location
            obj.data = original_data
            if materials is not None:
                # Clearing all slots resets per-face indices, including those
                # on linked duplicates. Restore slot references in place.
                slots = obj.data.materials
                for index, material in enumerate(materials):
                    if index < len(slots):
                        slots[index] = material
                    else:
                        slots.append(material)
                while len(slots) > len(materials):
                    slots.pop(index=len(slots) - 1)
            if color is not None:
                obj.data.color = color
            for field, value in npc_values.items():
                setattr(obj.blendengine_object.npc_behavior, field, value)
            while len(obj.blendengine_object.components) > count:
                obj.blendengine_object.components.remove(len(obj.blendengine_object.components) - 1)
            (obj.blendengine_object.is_game_object, obj.blendengine_object.object_tag,
             obj.blendengine_object.active_component_index) = role
        for obj in set(bpy.data.objects) - owned['objects']:
            bpy.data.objects.remove(obj, do_unlink=True)
        for name in ('meshes', 'armatures', 'lights', 'materials', 'actions'):
            collection = getattr(bpy.data, name)
            for block in set(collection) - owned[name]:
                if block.users == 0:
                    collection.remove(block)
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in selection:
            obj.select_set(True)
        context.view_layer.objects.active = active
        _plan_refs.pop(snapshot['token'], None)
        raise
    _plan_refs.pop(snapshot['token'], None)
    return plan


class BE_OT_agent_apply(bpy.types.Operator):
    bl_idname = 'blendengine.agent_apply'
    bl_label = 'Apply Plan'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.blendengine_agent.plan_json) and not context.scene.blendengine_project.test_running

    def execute(self, context):
        settings = context.scene.blendengine_agent
        try:
            apply_plan(context, json.loads(settings.plan_json), json.loads(settings.snapshot_json))
        except Exception as error:
            _forget(settings.snapshot_json)
            settings.plan_json = ''
            settings.status, settings.reply = 'ERROR', str(error)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        settings.plan_json = ''
        settings.status = 'IDLE'
        settings.reply += ' Applied. Use Undo to restore the scene.'
        return {'FINISHED'}


class BE_OT_agent_demo(bpy.types.Operator):
    bl_idname = 'blendengine.agent_demo'
    bl_label = 'New Agent Demo'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.scene.blendengine_project.test_running:
            self.report({'WARNING'}, 'Stop Play first.')
            return {'CANCELLED'}
        from . import story_game
        made = story_game.create_story(context)
        scout = ai_system.create_agent(context, name='Rescue Scout', behavior='GUIDE',
                                       location=(1.5, -8, .92), speed=3.0)
        scout.blendengine_object.npc_behavior.target_object = made['player']
        return {'FINISHED'}


class VIEW3D_PT_blendengine_agent(bpy.types.Panel):
    bl_label = 'Scene Agent'
    bl_idname = 'VIEW3D_PT_blendengine_agent'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'AI'
    bl_ui_units_x = 24

    def draw(self, context):
        layout, settings = self.layout, context.scene.blendengine_agent
        layout.prop(settings, 'mode')
        if settings.mode == 'MODEL':
            layout.prop(settings, 'endpoint')
            layout.prop(settings, 'model')
            layout.prop(settings, 'key_env')
            layout.label(text='Sends a scene summary to this endpoint.', icon='INFO')
        layout.prop(settings, 'prompt')
        row = layout.row(align=True)
        if settings.status == 'RUNNING':
            row.operator('blendengine.agent_cancel', icon='CANCEL')
        else:
            row.operator('blendengine.agent_plan', icon='VIEWZOOM')
            row.operator('blendengine.agent_apply', icon='CHECKMARK')
        if settings.reply:
            import textwrap
            for line in textwrap.wrap(settings.reply, width=42)[:10]:
                layout.label(text=line)
        if settings.plan_json:
            try:
                for action in json.loads(settings.plan_json)['actions']:
                    labels = {'create_object': 'Create object', 'create_npc': 'Add NPC',
                              'transform_object': 'Move', 'set_material': 'Tint material',
                              'set_npc': 'Set NPC behavior', 'audit': 'Review scene'}
                    target = action.get('name', action.get('object', 'scene'))
                    if target == '@selected':
                        target = 'selected objects'
                    layout.label(text=labels[action['tool']] + ': ' + target)
            except (ValueError, KeyError):
                pass
        layout.separator()
        layout.label(text='Examples: qizil kub qo‘sh; NPC qo‘sh')
        layout.operator('blendengine.agent_demo', icon='OUTLINER_OB_ARMATURE')


CLASSES = (BE_EditorAgentSettings, BE_OT_agent_plan, BE_OT_agent_cancel,
           BE_OT_agent_apply, BE_OT_agent_demo, VIEW3D_PT_blendengine_agent)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blendengine_agent = bpy.props.PointerProperty(type=BE_EditorAgentSettings)
    bpy.app.handlers.load_pre.append(_cancel_jobs)


def unregister():
    _cancel_jobs()
    if _cancel_jobs in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_cancel_jobs)
    del bpy.types.Scene.blendengine_agent
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
