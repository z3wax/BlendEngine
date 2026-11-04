# SPDX-License-Identifier: GPL-2.0-or-later
"""Last Signal: a small story chapter, using the project's existing human mesh."""
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

from . import components, demo_game, graphics, input_system, optimization, render_sync, utils

SPAWN = (0.0, -10.0, 0.92)
ITEMS = ((0, -6, 0.6), (-3.0, -2, 0.6), (3, 2, 0.6), (-2.5, 6, 0.6), (0, 10, 0.6))
GOAL = (0, 14, 0.9)
WAYPOINTS = ((0, -6), (-3, -2), (-3, 2), (3, 2), (-2.5, 6), (0, 10), (0, 14))
JOURNAL = (
    ('01 / THE SILENCE', 'Maya: The storm took the relay. Someone at Station Nine is still calling.'),
    ('02 / A NAME IN THE STATIC', 'Field log: the last transmission was from your missing brother, Eli.'),
    ('03 / RESTORE THE RELAY', 'Maya: A battery. Find the regulator and patch the broken antenna.'),
    ('03 / RESTORE THE RELAY', 'Eli, recorded: If you hear this, follow the orange service lights.'),
    ('04 / THE LAST SIGNAL', 'Maya: The transmitter is alive. Reach the terminal before the storm returns.'),
    ('05 / DAWN', 'Eli: Maya? I knew you would come. Rescue is on its way.'),
)


def material(name, color, roughness=.7, metallic=0.0, emission=0.0, grain=True):
    mat = bpy.data.materials.new('Last Signal | ' + name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    shader = nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = roughness
    shader.inputs['Metallic'].default_value = metallic
    if emission:
        (shader.inputs.get('Emission Color') or shader.inputs.get('Emission')).default_value = (*color, 1)
        if shader.inputs.get('Emission Strength') is not None:
            shader.inputs['Emission Strength'].default_value = emission
    if grain:
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 32
        noise.inputs['Detail'].default_value = 2.0
        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = .16
        bump.inputs['Distance'].default_value = .018
        links.new(noise.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], shader.inputs['Normal'])
        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = (*(v*.66 for v in color), 1)
        ramp.color_ramp.elements[1].color = (*(min(1, v*1.12) for v in color), 1)
        links.new(noise.outputs['Fac'], ramp.inputs[0])
        links.new(ramp.outputs['Color'], shader.inputs['Base Color'])
    return mat


def cone(batch, center, radius, height, slot, sides=12):
    x,y,z=center
    vertices=[(x+radius*math.cos(i*math.tau/sides),y+radius*math.sin(i*math.tau/sides),z) for i in range(sides)]
    vertices.append((x,y,z+height))
    batch.add(vertices,[(i,(i+1)%sides,sides) for i in range(sides)],slot)


def human(scene, player, mats):
    """Reuse existing in-repo soldier geometry; no external downloads/textures."""
    portable = Path(__file__).parent / 'assets/last_signal_character.blend'
    if portable.is_file():
        with bpy.data.libraries.load(str(portable),link=False) as (available,loaded):
            loaded.objects=available.objects
        objects=[o for o in loaded.objects if o is not None]
        for obj in objects:
            scene.collection.objects.link(obj)
        actor=next(o for o in objects if o.type=='MESH')
        rig=next(o for o in objects if o.type=='ARMATURE')
        rig.parent=player
        actor.parent=rig
        indices=[p.material_index for p in actor.data.polygons]
        actor.data.materials.clear()
        for mat in mats:
            actor.data.materials.append(mat)
        for polygon,index in zip(actor.data.polygons,indices):
            polygon.material_index=index
        return actor,rig
    source = Path(__file__).resolve().parents[3] / 'builds/NeonQuarantineExport/NeonQuarantineWindows/NeonQuarantineWindows.blend'
    keep = ('Body_0', 'Legs_15', 'Head_4', 'Eyes_3', 'Gloves_6', 'Bootarmor_24',
            'Backpack_9', 'Pouches_11', 'Helmet_2', 'Headset_5')
    with bpy.data.libraries.load(str(source), link=False) as (available, loaded):
        loaded.objects = [name for name in available.objects if name.startswith('BE_PlayerSoldierVisual_')]
    imported = [obj for obj in loaded.objects if obj is not None]
    for obj in imported:
        scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    vertices, faces, slots, smooth = [], [], [], []
    for obj in imported:
        label = obj.parent.name if obj.parent else ''
        if obj.type != 'MESH' or not any(label.endswith(suffix) for suffix in keep):
            continue
        category = 1 if label.endswith('Head_4') else 4 if label.endswith('Eyes_3') else 2 if label.endswith(('Gloves_6', 'Bootarmor_24', 'Headset_5')) else 3 if label.endswith(('Backpack_9', 'Pouches_11')) else 0
        offset = len(vertices)
        for vertex in obj.data.vertices:
            point = obj.matrix_world @ vertex.co
            vertices.append((point.x, point.y, point.z - .9))
        for polygon in obj.data.polygons:
            faces.append(tuple(offset + index for index in polygon.vertices))
            slots.append(category)
            smooth.append(polygon.use_smooth)
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    mesh = bpy.data.meshes.new('Maya | human mesh')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    actor = bpy.data.objects.new('Maya | clothed human character', mesh)
    scene.collection.objects.link(actor)
    for mat in mats:
        mesh.materials.append(mat)
    for polygon, slot, shaded in zip(mesh.polygons, slots, smooth):
        polygon.material_index, polygon.use_smooth = slot, shaded
    rig_data = bpy.data.armatures.new('Maya | locomotion skeleton')
    rig = bpy.data.objects.new('Maya | rig', rig_data)
    scene.collection.objects.link(rig)
    rig.parent = player
    rig.rotation_euler.z = math.pi
    rig.show_in_front = False
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    definitions = {
        'root': ((0, 0, -.9), (0, 0, .1), None),
        'spine': ((0, 0, .1), (0, 0, .55), 'root'),
        'head': ((0, 0, .55), (0, 0, .88), 'spine'),
    }
    for side, sign in (('L', 1), ('R', -1)):
        definitions['arm.'+side] = ((sign*.17, 0, .48), (sign*.51, 0, .48), 'spine')
        definitions['forearm.'+side] = ((sign*.51, 0, .48), (sign*.86, 0, .48), 'arm.'+side)
        definitions['leg.'+side] = ((sign*.105, 0, -.04), (sign*.105, 0, -.47), 'root')
        definitions['calf.'+side] = ((sign*.105, 0, -.47), (sign*.105, 0, -.89), 'leg.'+side)
    for name, (head, tail, parent) in definitions.items():
        bone = rig_data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        if parent:
            bone.parent = rig_data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    for bone in rig.pose.bones:
        bone.rotation_mode='XYZ'
    actor.parent = rig
    modifier = actor.modifiers.new('Human skinning', 'ARMATURE')
    modifier.object = rig
    groups = {name: actor.vertex_groups.new(name=name) for name in definitions}
    for vertex in mesh.vertices:
        x, _y, z = vertex.co
        side = 'L' if x > 0 else 'R'
        if z > .57 and abs(x) < .23:
            name = 'head'
        elif abs(x) > .2 and z > .15:
            name = ('forearm.' if abs(x) > .5 else 'arm.')+side
        elif z < -.12:
            name = ('calf.' if z < -.47 else 'leg.')+side
        else:
            name = 'spine' if z > .1 else 'root'
        groups[name].add([vertex.index], 1.0, 'REPLACE')
    for side in ('L', 'R'):
        rig.pose.bones['arm.'+side].rotation_euler.x = -1.30
        rig.pose.bones['forearm.'+side].rotation_euler.z = .10 if side == 'L' else -.10
    actor['asset_source'] = 'Existing BlendEngine NeonQuarantine soldier geometry; procedural replacement materials'
    rig.select_set(False)
    return actor, rig


def create_story(context):
    scene = bpy.data.scenes.new('Last Signal | chapter one')
    context.window.scene = scene
    project = utils.ensure_project_defaults(scene)
    project.game_title = 'LAST SIGNAL / Chapter One'
    project.show_fps, project.show_game_variables, project.debug_mode = False, False, False
    project.resolution_x, project.resolution_y = 960, 540
    scene['blendengine_story'] = 'LAST_SIGNAL'
    scene['blendengine_demo_waypoints'] = json.dumps(WAYPOINTS)
    scene['demo_instructions'] = 'WASD move | Space jump | Shift run | E inspect terminal | R restart | Esc stop'
    graphics.configure_realtime(scene)
    optimization.apply_preset(scene, 'HIGH')
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.resolution_percentage = 100
    scene.view_settings.exposure = -.4
    scene.blendengine_optimization.camera_frustum_generation = False
    scene.blendengine_optimization.hide_behind_camera = False
    earth = material('weathered limestone', (.30, .27, .20), .9)
    concrete = material('pale concrete', (.39, .38, .32), .82)
    dark = material('aged steel', (.075, .09, .10), .43, .7)
    wood = material('cedar', (.22, .12, .065), .85)
    leaves = material('pine needles', (.055, .12, .075), .9)
    orange = material('service paint', (.63, .22, .055), .48, .15)
    glow = material('warm service lights', (1, .48, .12), .4, emission=2, grain=False)
    window = material('cold glass', (.055, .14, .18), .16, .4)
    mats = [earth, concrete, dark, wood, leaves, orange, glow, window]
    floor = demo_game.Geometry()
    floor.box((0, 2, -.18), (22, 36, .36), 0)
    ground = floor.object(scene, 'Outpost | stone ground', mats)
    components.add_collider(ground, 'Ground')
    static = demo_game.Geometry()
    # Service path, low ruins, a timber field station and a radio tower.
    for y in range(-12, 18, 2):
        static.box((0, y, .015), (4.8, 1.85, .03), 1)
    for side in (-1, 1):
        for y in (-11, -5, 1, 7, 13):
            static.box((side*6.8, y, .7), (.6, 3.3, 1.4), 1)
            static.box((side*6.8, y, 1.44), (.72, 3.4, .12), 0)
            static.box((side*5.5, y, .9), (.14, .14, 1.8), 2)
            static.box((side*5.5, y, 1.82), (.3, .3, .12), 6)
    for x, y, height in ((-8,-8,6), (8,-4,7), (-8,4,7), (8,9,6), (-8,16,8)):
        static.box((x,y,height*.35), (.3,.3,height*.7), 3)
        for layer in range(4):
            radius = 1.8-layer*.3
            cone(static,(x,y,height*.35+layer*.8),radius,2.4-layer*.2,4)
    for x in (-4.7, 4.7):
        static.box((x,4,1.5), (2.7,5.6,3), 1)
        static.box((x,4,3.1), (3.1,6,.22), 2)
        static.box((x,1.18,1.35), (1.5,.045,1.3), 7)
        static.box((x,1.12,2.45), (2.1,.06,.14), 6)
        static.box((x,6.85,.1), (3,2,.2), 3)
    static.box((0,14,.35), (5,4,.7), 1)
    for x in (-1.3,1.3):
        static.box((x,15,4.5), (.14,.14,9), 2)
        for z in (1,3,5,7,9):
            static.box((0,15,z), (2.7,.16,.12), 2)
    static.box((0,13.7,1.35), (1.4,.5,1.5), 2)
    static.box((0,13.42,1.7), (1.05,.04,.5), 7)
    static.box((0,13.38,1.7), (.83,.02,.06), 6)
    static.box((0,15,9.4), (.2,.2,.4), 5)
    building=static.object(scene, 'Outpost | batched architecture and foliage', mats)
    bevel=building.modifiers.new('Weathered masonry edge highlights','BEVEL')
    bevel.width=.035
    bevel.segments=2
    bevel.limit_method='ANGLE'
    # Distant silhouette is a tiny static batch, not a volumetric fog effect.
    mountains=demo_game.Geometry()
    for index,x in enumerate(range(-48,49,12)):
        cone(mountains,(x,43+index%3*4,-1),16,17+index%4*4,0,sides=9)
    mountains.object(scene,'Distant mountain ridge',[material('distant mountain',(.18,.24,.27),1.0,grain=False)])
    details=demo_game.Geometry()
    for index,(x,y) in enumerate(((-3.8,-8),(4.4,-5),(-4.2,3),(4.4,8),(-3.9,12))):
        details.box((x,y,.35),(.9,.7,.7),3)
        details.box((x,y,.74),(1,.8,.08),2)
        for side in (-1,1):
            details.box((x+side*.32,y-.36,.35),(.06,.04,.6),2)
    for i in range(36):
        x=(1 if i%2 else -1)*(3.1+(i%5)*.46)
        y=-11+(i*.81)%28
        for j in range(3):
            cone(details,(x+j*.045,y,0.02),.055,.24+(i%3)*.07,4,sides=4)
    details.object(scene,'Outpost | grass and supply crates',mats)
    # A proper character-shaped collider plus a skinned human visual.
    bpy.ops.mesh.primitive_cube_add(size=1, location=SPAWN)
    player = context.object
    player.name = 'Maya | player controller'
    player.dimensions = (.48,.38,1.84)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    player.hide_render, player.display_type = True, 'WIRE'
    controller = components.add_player_controller(player)
    controller.controller_type, controller.walk_speed, controller.run_speed = 'THIRD_PERSON', 3.7, 6.0
    controller.jump_force, controller.gravity = 5.5, 18
    components.add_health(player, 100)
    components.add_collider(player, 'Player')
    score = player.blendengine_object.variables.add()
    score.name, score.variable_type = 'Score', 'INT'
    cloth = material('olive field jacket', (.16,.20,.12), .83)
    skin = material('skin', (.47,.27,.17), .55)
    leather = material('boots and gloves', (.04,.033,.028), .7)
    bag = material('canvas backpack', (.28,.18,.095), .85)
    eyes = material('eyes', (.055,.035,.02), .22, grain=False)
    actor, rig = human(scene, player, [cloth, skin, leather, bag, eyes])
    scene['story_rig'] = rig.name
    scene['story_actor'] = actor.name
    pickup_mat = material('quest marker', (.7,.31,.075), .35, .7, .55, grain=False)
    for index, point in enumerate(ITEMS):
        item = demo_game.Geometry()
        item.box((0,0,0), (.38,.24,.42), 0)
        item.box((0,-.13,.04), (.22,.035,.18), 1)
        obj = item.object(scene, 'Signal clue %02d'%(index+1), [dark,pickup_mat])
        obj.location = point
    bpy.ops.object.empty_add(location=GOAL)
    context.object.name = 'Signal | terminal objective'
    bpy.ops.object.light_add(type='SUN', location=(4,-8,8))
    sun=context.object
    sun.name='Dawn | sun'
    sun.data.energy=2.6
    sun.data.color=(1,.75,.48)
    sun.data.angle=.12
    sun.rotation_euler=(math.radians(34),math.radians(-20),math.radians(-35))
    demo_game._light(scene,'Dawn | broad sky bounce','AREA',(-4,-4,8),(.48,.67,1),500,(0,2,0),False)
    world=bpy.data.worlds.new('Dawn | blue atmosphere')
    world.use_nodes=True
    world.node_tree.nodes['Background'].inputs['Color'].default_value=(.22,.32,.5,1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value=.4
    scene.world=world
    bpy.ops.object.camera_add(location=(0,-14.8,3.25))
    camera=context.object
    camera.name='Last Signal | follow camera'
    camera.data.lens=34
    camera.rotation_euler=(Vector(SPAWN)-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.camera=camera
    controller.camera_follow=camera
    input_system.ensure_defaults(scene)
    context.view_layer.objects.active=player
    bpy.ops.object.select_all(action='DESELECT')
    player.select_set(True)
    return {'scene':scene,'player':player,'actor':actor,'rig':rig,'camera':camera}


class StoryGame(demo_game.DemoGame):
    custom_hud=True

    def __init__(self, session):
        # Same small HUD/cache lifecycle as the earlier demo, with independent
        # story state; normal scenes never enter this code path.
        self.session,self.scene=session,session.scene
        self.player=session.player
        self.cores=[self.scene.objects['Signal clue %02d'%(i+1)] for i in range(5)]
        self.hazards=[]
        self.portal=self.scene.objects['Signal | terminal objective']
        self.score=next(v for v in self.player.blendengine_object.variables if v.name=='Score')
        self.health=self.player.blendengine_object.health
        self.rig=self.scene.objects[self.scene['story_rig']]
        self._handler=None
        self._shader=None
        self._initial_cores=[(o,o.location.copy(),o.rotation_euler.copy(),o.hide_viewport,o.hide_render,o.hide_get()) for o in self.cores]
        self._initial_player=(self.player.location.copy(),self.player.rotation_euler.copy(),True,self.health.current_health,0)
        self._initial_camera=(self.scene.camera.location.copy(),self.scene.camera.rotation_euler.copy())
        self._last_position=self.player.location.copy()
        self.phase=0
        self.restart()

    def restart(self):
        self.state,self.elapsed,self.collected='RUNNING',0.0,set()
        self.score.int_value=0
        self.health.current_health=100
        self.player.location=SPAWN
        self.player.blendengine_object.player_controller.enabled=True
        self.message=JOURNAL[0][1]
        self.message_until=8.0
        self._restart_held=False
        self._last_position=self.player.location.copy()
        self.phase=0.0
        self.player.rotation_euler=(0,0,0)
        self.rig.rotation_euler.z=math.pi
        self.session._vertical_velocity[self.player.name]=0.0
        for side in ('L','R'):
            self.rig.pose.bones['leg.'+side].rotation_euler.x=0
            self.rig.pose.bones['calf.'+side].rotation_euler.x=0
            self.rig.pose.bones['arm.'+side].rotation_euler.z=0
        for obj,*_rest in self._initial_cores:
            obj.hide_viewport=obj.hide_render=False
            obj.hide_set(False)

    def start(self):
        self.restart()
        if not bpy.app.background:
            self._handler=bpy.types.SpaceView3D.draw_handler_add(self.draw_hud,(), 'WINDOW','POST_PIXEL')
        self.session.log('LAST SIGNAL: Maya arrives at the abandoned mountain relay.')

    def update(self,dt):
        down='R' in self.session.input_state
        if down and not self._restart_held:
            self.restart()
        self._restart_held=down
        if self.state!='RUNNING':
            return
        self.elapsed+=dt
        for index,item in enumerate(self.cores):
            if item.name not in self.collected and (self.player.location-item.location).length<1.15:
                self.collected.add(item.name)
                item.hide_render=item.hide_viewport=True
                self.score.int_value=len(self.collected)
                self.message=JOURNAL[self.score.int_value][1]
                self.message_until=self.elapsed+8
                self.session.log(self.message)
        moved=(self.player.location-self._last_position).xy.length
        self._last_position=self.player.location.copy()
        self.phase+=moved*7
        # The imported human faces local -Y; convert the controller's yaw
        # convention so forward motion never produces a backwards walk.
        render_sync.scalar(self.rig.rotation_euler,'z',math.pi-2*self.player.rotation_euler.z)
        swing=math.sin(self.phase)*.42 if moved>.0001 else 0.0
        for side,sign in (('L',1),('R',-1)):
            render_sync.scalar(self.rig.pose.bones['leg.'+side].rotation_euler,'x',swing*sign)
            render_sync.scalar(self.rig.pose.bones['calf.'+side].rotation_euler,'x',max(0,-swing*sign)*1.1)
            render_sync.scalar(self.rig.pose.bones['arm.'+side].rotation_euler,'z',-swing*sign*.4)
        if 'E' in self.session.input_state and (self.player.location-self.portal.location).xy.length<3:
            self.message='Relay terminal: antenna patched. '+('Rescue uplink ready.' if self.score.int_value==5 else 'Find the remaining field components.')
            self.message_until=self.elapsed+5
        if self.score.int_value==5 and (self.player.location-self.portal.location).xy.length<1.5:
            self.state='WON'
            self.player.blendengine_object.player_controller.enabled=False
            self.message=JOURNAL[5][1]
            self.session.log('LAST SIGNAL: transmitter restored. Chapter one complete.')

    def stop(self):
        super().stop()
        self.rig.rotation_euler.z=math.pi
        for side in ('L','R'):
            self.rig.pose.bones['leg.'+side].rotation_euler.x=0
            self.rig.pose.bones['calf.'+side].rotation_euler.x=0
            self.rig.pose.bones['arm.'+side].rotation_euler.z=0

    def draw_hud(self):
        if bpy.context.scene!=self.scene or bpy.context.region is None:
            return
        import blf
        import gpu
        from gpu_extras.batch import batch_for_shader
        if self._shader is None:
            try:self._shader=gpu.shader.from_builtin('UNIFORM_COLOR')
            except ValueError:self._shader=gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        w,h=bpy.context.region.width,bpy.context.region.height
        def panel(x,y,width,height):
            batch=batch_for_shader(self._shader,'TRI_FAN',{'pos':((x,y),(x+width,y),(x+width,y+height),(x,y+height))})
            gpu.state.blend_set('ALPHA');self._shader.bind();self._shader.uniform_float('color',(.015,.025,.032,.88));batch.draw(self._shader);gpu.state.blend_set('NONE')
        def text(value,x,y,size=14,color=(.87,.9,.9,1)):
            try:blf.size(0,size)
            except TypeError:blf.size(0,size,72)
            blf.color(0,*color);blf.position(0,x,y,0);blf.draw(0,value)
        panel(18,h-112,510,95)
        text('LAST SIGNAL',34,h-45,23,(1,.69,.34,1))
        text(JOURNAL[self.score.int_value][0],34,h-70,15)
        text('Recovered clues %d / 5   |   Maya / field engineer'%self.score.int_value,34,h-94,13)
        panel(18,18,w-36,92)
        line=self.message
        for i in range(0,len(line),85):text(line[i:i+85],34,83-(i//85)*19,14)
        text('WASD move   SPACE jump   SHIFT run   R restart   ESC editor',34,32,12,(.65,.75,.8,1))
        if self.state=='WON':
            panel(w/2-240,h/2-78,480,160)
            text('A VOICE IN THE STATIC',w/2-215,h/2+35,22,(1,.7,.35,1))
            text('Maya found Eli. The rescue beacon is online.',w/2-215,h/2,15)
            text('CHAPTER ONE COMPLETE   |   R to replay',w/2-215,h/2-36,14)
