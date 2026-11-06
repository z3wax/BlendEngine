# SPDX-License-Identifier: GPL-2.0-or-later
"""Local NPC perception, bounded navigation and reusable character agents.

The simulation has no network or model dependency. Decisions run at a lower
cadence than movement; immutable meshes/materials are shared between humans.
"""
import math

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import components, render_sync
from .npc_navigation import find_path, segment_clear


MOVING_BEHAVIORS = {'PATROL', 'FOLLOW_PLAYER', 'ATTACK', 'COMPANION', 'ENEMY_BOSS',
                    'FLEE', 'GUARD', 'GUARD_AREA', 'GUIDE'}


def apply_template(obj, template="IDLE", target=None):
    npc = components.add_npc_behavior(obj, template=template, target=target)
    if template == 'PATROL':
        npc.move_speed, npc.patrol_radius = 2.5, 8.0
    elif template in {'FOLLOW_PLAYER', 'COMPANION', 'GUIDE'}:
        npc.move_speed, npc.detection_range = 3.5, 20.0
    elif template == 'ATTACK':
        npc.move_speed, npc.attack_range = 4.0, 2.0
    elif template == 'QUEST_GIVER':
        npc.dialogue_text, npc.quest_id = 'I have a quest for you.', 'quest_001'
    elif template == 'SHOPKEEPER':
        npc.dialogue_text = 'Welcome to my shop.'
    elif template == 'ENEMY_BOSS':
        npc.move_speed, npc.detection_range, npc.attack_range = 3.0, 25.0, 3.0
    return npc


def create_agent(context, name='Rescue Scout', behavior='FOLLOW_PLAYER',
                 location=(1.5, -8.0, .92), speed=3.0):
    """Create a real skinned human; share visual data with an existing player."""
    from . import story_game
    scene = context.scene
    if behavior not in MOVING_BEHAVIORS | {'IDLE', 'TALK', 'QUEST_GIVER', 'SHOPKEEPER'}:
        raise ValueError('Unsupported NPC behavior: ' + str(behavior))
    point = tuple(float(v) for v in location)
    if len(point) != 3 or not all(math.isfinite(v) and abs(v) <= 10000 for v in point):
        raise ValueError('NPC location must contain three finite coordinates')
    speed = float(speed)
    if not math.isfinite(speed) or not 0 <= speed <= 6:
        raise ValueError('NPC speed must be between zero and six')
    bpy.ops.mesh.primitive_cube_add(size=1, location=point)
    root = context.object
    root.name = name[:80] or 'Rescue Scout'
    root.dimensions = (.48, .38, 1.84)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    root.hide_render = True
    root.display_type = 'WIRE'
    player = next((o for o in scene.objects if o != root and o.blendengine_object.player_controller.enabled), None)
    npc = apply_template(root, behavior, player)
    npc.move_speed = speed
    components.add_collider(root, 'NPC')
    original_actor = scene.objects.get(scene.get('story_actor', ''))
    original_rig = scene.objects.get(scene.get('story_rig', ''))
    if original_actor is None or original_rig is None:
        prototype = next((o for o in scene.objects if 'blendengine_agent_actor' in o and o != root), None)
        if prototype is not None:
            original_actor = scene.objects.get(prototype.get('blendengine_agent_actor', ''))
            original_rig = scene.objects.get(prototype.get('blendengine_agent_rig', ''))
    if original_actor is not None and original_rig is not None:
        rig = original_rig.copy()
        rig.data = original_rig.data.copy()
        rig.animation_data_clear()
        scene.collection.objects.link(rig)
        rig.parent = root
        rig.location = original_rig.location.copy()
        actor = original_actor.copy()
        actor.animation_data_clear()
        scene.collection.objects.link(actor)
        actor.parent = rig
        for modifier in actor.modifiers:
            if modifier.type == 'ARMATURE':
                modifier.object = rig
    else:
        mats = [story_game.material('scout jacket', (.12, .22, .28), .83),
                story_game.material('scout skin', (.47, .27, .17), .55),
                story_game.material('scout boots', (.04, .033, .028), .7),
                story_game.material('scout backpack', (.28, .18, .095), .85),
                story_game.material('scout eyes', (.055, .035, .02), .22, grain=False)]
        actor, rig = story_game.human(scene, root, mats)
    rig.name = root.name + ' | rig'
    actor.name = root.name + ' | human'
    root['blendengine_agent_rig'] = rig.name
    root['blendengine_agent_actor'] = actor.name
    rig.rotation_euler.z = math.pi
    for selected in context.selected_objects:
        selected.select_set(False)
    root.select_set(True)
    context.view_layer.objects.active = root
    return root


def _descendants(obj):
    yield obj
    for child in obj.children:
        yield from _descendants(child)


class NavigationWorld:
    """Spatial buckets narrow cached world-space BVH probes to nearby geometry."""
    CELL = .75
    RADIUS = .31

    def __init__(self):
        self.signature = None
        self.cells = {}
        self.large = []
        self.probes = {}
        self.last_refresh = -math.inf
        self.rebuilds = 0

    def refresh(self, session):
        if session.elapsed - self.last_refresh < .5 and self.signature is not None:
            return
        self.last_refresh = session.elapsed
        excluded = set()
        for moving in [session.player] + list(session._npcs):
            if moving is not None:
                excluded.update(_descendants(moving))
        objects = [o for o in session._objects if o.type == 'MESH' and o not in excluded
                   and (not o.hide_render or any(c.enabled and c.component_type == 'COLLIDER'
                                                for c in o.blendengine_object.components))
                   and o.blendengine_object.object_tag != 'Ground'
                   and not o.blendengine_object.npc_behavior.enabled
                   and 'clue' not in o.name.lower() and 'distant' not in o.name.lower()
                   and 'grass' not in o.name.lower()
                   and not any(c.enabled and c.component_type == 'TRIGGER_ZONE'
                               for c in o.blendengine_object.components)]
        signature = tuple((o.as_pointer(), o.data.as_pointer(), len(o.data.vertices),
                           tuple(v for row in o.matrix_world for v in row)) for o in objects)
        if signature == self.signature:
            return
        self.signature, self.cells, self.large, self.probes = signature, {}, [], {}
        self.rebuilds += 1
        for obj in objects:
            points = [obj.matrix_world @ v.co for v in obj.data.vertices]
            if not points or not obj.data.polygons:
                continue
            low = tuple(min(v[i] for v in points) for i in range(3))
            high = tuple(max(v[i] for v in points) for i in range(3))
            tree = BVHTree.FromPolygons(points, [tuple(p.vertices) for p in obj.data.polygons])
            record = (low, high, tree)
            x0, x1 = math.floor((low[0]-self.RADIUS)/self.CELL), math.floor((high[0]+self.RADIUS)/self.CELL)
            y0, y1 = math.floor((low[1]-self.RADIUS)/self.CELL), math.floor((high[1]+self.RADIUS)/self.CELL)
            if (x1-x0+1)*(y1-y0+1) > 4096:
                self.large.append(record)
                continue
            for x in range(x0, x1+1):
                for y in range(y0, y1+1):
                    self.cells.setdefault((x, y), []).append(record)

    def blocked(self, x, y, height):
        key = (round(x, 3), round(y, 3), round(height, 2))
        if key in self.probes:
            return self.probes[key]
        point = Vector((x, y, height))
        records = self.cells.get((math.floor(x/self.CELL), math.floor(y/self.CELL)), ())
        blocked = False
        for low, high, tree in (*records, *self.large):
            if not (low[0]-self.RADIUS <= x <= high[0]+self.RADIUS
                    and low[1]-self.RADIUS <= y <= high[1]+self.RADIUS
                    and low[2] <= height <= high[2]):
                continue
            nearest, normal, _index, distance = tree.find_nearest(point)
            if nearest is not None and (distance < self.RADIUS or (point-nearest).dot(normal) < -1e-5):
                blocked = True
                break
        # Queries remain bounded even if many NPCs move through a large scene.
        if len(self.probes) >= 16384:
            self.probes.clear()
        self.probes[key] = blocked
        return blocked


class AgentState:
    def __init__(self, obj):
        self.obj = obj
        self.location = obj.location.copy()
        self.rotation = obj.rotation_euler.copy()
        self.origin = obj.location.copy()
        self.rig = next((o for o in _descendants(obj) if o.type == 'ARMATURE'), None)
        self.pose = {b.name: b.rotation_euler.copy() for b in self.rig.pose.bones} if self.rig else {}
        self.rig_rotation = self.rig.rotation_euler.copy() if self.rig else None
        self.phase = 0.0
        self.deadline = -math.inf
        self.path = []
        self.goal = None
        self.mode = 'IDLE'
        self.patrol_index = 0
        self.decisions = 0
        self.walked = 0.0
        self.last_seen, self.seen_at = None, -math.inf
        self.replan_at, self.world_revision = -math.inf, -1

    def restore(self):
        self.obj.location = self.location
        self.obj.rotation_euler = self.rotation
        if self.rig:
            self.rig.rotation_euler = self.rig_rotation
            for name, rotation in self.pose.items():
                self.rig.pose.bones[name].rotation_euler = rotation
        self.origin = self.location.copy()
        self.phase, self.deadline, self.path, self.goal = 0.0, -math.inf, [], None
        self.mode, self.patrol_index, self.decisions, self.walked = 'IDLE', 0, 0, 0.0
        self.last_seen, self.seen_at = None, -math.inf
        self.replan_at, self.world_revision = -math.inf, -1


class AgentManager:
    def __init__(self, session):
        self.session = session
        self.world = NavigationWorld()
        self.agents = {}
        self.statuses = {}
        self._last_story_elapsed = 0.0
        self.sync()

    def sync(self):
        # Names are editable during Play; keep the original snapshot by object
        # identity rather than registering a second brain after a rename.
        for old_name, agent in tuple(self.agents.items()):
            try:
                name = agent.obj.name
            except ReferenceError:
                self.agents.pop(old_name, None)
                self.statuses.pop(old_name, None)
                continue
            if name != old_name:
                self.agents.pop(old_name, None)
                self.agents[name] = agent
                self.statuses.pop(old_name, None)
        for obj in self.session._npcs:
            if obj.name not in self.agents or self.agents[obj.name].obj != obj:
                self.agents[obj.name] = AgentState(obj)
        for name, agent in tuple(self.agents.items()):
            try:
                exists = agent.obj.name in self.session.scene.objects
            except ReferenceError:
                exists = False
            if not exists:
                del self.agents[name]
                self.statuses.pop(name, None)

    def reset(self):
        for agent in self.agents.values():
            try:
                if agent.obj.name in self.session.scene.objects:
                    agent.restore()
            except ReferenceError:
                pass
        self.world.probes.clear()
        self._last_story_elapsed = 0.0
        self.statuses.clear()

    def _choose_goal(self, agent, npc, player, visible=True):
        obj, origin = agent.obj, agent.origin
        target = npc.target_object or player
        behavior = npc.behavior_template
        if behavior not in MOVING_BEHAVIORS or target is obj:
            return 'IDLE', None, npc.stop_distance
        if behavior == 'GUIDE' and getattr(self.session._gameplay, 'state', '') == 'WON':
            return 'COMPLETE', None, npc.stop_distance
        if behavior == 'PATROL':
            radius = max(.3, npc.patrol_radius)
            offsets = ((radius, 0), (0, radius), (-radius, 0), (0, -radius))
            x, y = offsets[agent.patrol_index % 4]
            goal = Vector((origin.x+x, origin.y+y, origin.z))
            if (obj.location-goal).xy.length < .25:
                agent.patrol_index += 1
                x, y = offsets[agent.patrol_index % 4]
                goal = Vector((origin.x+x, origin.y+y, origin.z))
            return 'PATROL', goal, .1
        if target is None:
            return 'NO_TARGET', None, npc.stop_distance
        distance = (obj.location-target.location).xy.length
        in_range = distance <= npc.detection_range if npc.detection_range > 0 else False
        if behavior in {'GUARD', 'GUARD_AREA'}:
            if in_range and visible and (target.location-origin).xy.length <= npc.patrol_radius:
                return 'GUARD', target.location.copy(), npc.stop_distance
            if (obj.location-origin).xy.length < .2:
                return 'GUARDING', None, .15
            return 'RETURN', origin.copy(), .15
        if not in_range:
            return 'SEARCH', None, npc.stop_distance
        if behavior in {'ATTACK', 'ENEMY_BOSS'}:
            if visible:
                agent.last_seen, agent.seen_at = target.location.copy(), self.session.elapsed
            elif agent.last_seen is not None and self.session.elapsed-agent.seen_at < 3.0:
                return 'INVESTIGATE', agent.last_seen.copy(), npc.stop_distance
            else:
                return 'SEARCH', None, npc.stop_distance
        if behavior == 'FLEE':
            direction = (obj.location-target.location).xy
            if direction.length < .001:
                direction = Vector((1.0, 0.0))
            direction.normalize()
            return 'FLEE', obj.location + Vector((direction.x, direction.y, 0))*5, .1
        if behavior == 'GUIDE':
            game = self.session._gameplay
            if game is not None and hasattr(game, 'cores'):
                next_item = next((o for o in game.cores if o.name not in game.collected), None)
                goal = next_item.location.copy() if next_item else game.portal.location + Vector((0, -3.5, 0))
                if distance > 5:
                    # Wait when leading, but catch up if the player passed us.
                    if (obj.location-goal).xy.length < (target.location-goal).xy.length:
                        return 'WAIT_FOR_PLAYER', None, npc.stop_distance
                    return 'CATCH_UP', target.location.copy(), npc.stop_distance
                return 'GUIDE', goal, .6
        return ('CHASE' if behavior in {'ATTACK', 'ENEMY_BOSS'} else 'FOLLOW'), target.location.copy(), (
            max(.5, npc.attack_range) if behavior in {'ATTACK', 'ENEMY_BOSS'} else npc.stop_distance)

    def _animate(self, agent, distance):
        rig = agent.rig
        if rig is None:
            return
        agent.phase += distance*7
        render_sync.scalar(rig.rotation_euler, 'z', math.pi-2*agent.obj.rotation_euler.z)
        swing = math.sin(agent.phase)*.42 if distance > .0001 else 0.0
        for side, sign in (('L', 1), ('R', -1)):
            for prefix, value, axis in (('leg.', swing*sign, 'x'),
                                        ('calf.', max(0, -swing*sign)*1.1, 'x'),
                                        ('arm.', -swing*sign*.4, 'z')):
                bone = rig.pose.bones.get(prefix+side)
                if bone is not None:
                    render_sync.scalar(bone.rotation_euler, axis, value)

    def update(self, dt):
        self.sync()
        if not self.agents:
            return
        self.world.refresh(self.session)
        game = self.session._gameplay
        story_elapsed = getattr(game, 'elapsed', 0.0)
        if story_elapsed < self._last_story_elapsed:
            self.reset()
        self._last_story_elapsed = story_elapsed
        for name, agent in self.agents.items():
            obj, npc = agent.obj, agent.obj.blendengine_object.npc_behavior
            if not npc.enabled:
                continue
            before = obj.location.copy()
            blocked = (lambda x, y: self.world.blocked(x, y, obj.location.z-.25)) if npc.avoid_obstacles else lambda x, y: False
            completed = npc.behavior_template == 'GUIDE' and getattr(game, 'state', '') == 'WON' and agent.mode != 'COMPLETE'
            if completed or self.session.elapsed >= agent.deadline:
                target = npc.target_object or self.session.player
                visible = target is None or segment_clear(tuple(obj.location.xy), tuple(target.location.xy), blocked, cell_size=.4)
                mode, goal, stop = self._choose_goal(agent, npc, self.session.player, visible)
                previous_goal = agent.goal
                agent.mode, agent.goal = mode, goal
                agent.deadline = self.session.elapsed + npc.decision_interval
                agent.decisions += 1
                changed = (goal is None or previous_goal is None or
                           (goal-previous_goal).xy.length > .35 or
                           agent.world_revision != self.world.rebuilds)
                if goal is None or (obj.location-goal).xy.length <= stop:
                    agent.path = []
                elif changed or (not agent.path and self.session.elapsed >= agent.replan_at):
                    delta = goal-obj.location
                    delta.z = 0
                    endpoint = goal-delta.normalized()*stop
                    agent.path = find_path(tuple(obj.location.xy), tuple(endpoint.xy), blocked,
                                           cell_size=.75, max_nodes=256, margin=6.0)
                    agent.world_revision = self.world.rebuilds
                    agent.replan_at = self.session.elapsed + .6
                    if not agent.path:
                        agent.mode = 'BLOCKED'
            if agent.goal is not None and not agent.path and (obj.location-agent.goal).xy.length > max(.1, npc.stop_distance):
                agent.mode = 'BLOCKED'
            # Move through waypoints at the simulation rate, with swept probes.
            available = max(0.0, min(float(dt), .25))*max(0.0, npc.move_speed)
            while available > 1e-7 and agent.path:
                waypoint = Vector((*agent.path[0], obj.location.z))
                delta = waypoint-obj.location
                distance = delta.length
                if distance < .02:
                    agent.path.pop(0)
                    continue
                direction = delta.normalized()
                step = min(available, distance)
                candidate = obj.location + direction*step
                if npc.avoid_obstacles and not segment_clear(tuple(obj.location.xy), tuple(candidate.xy), blocked, cell_size=.25):
                    agent.path = []
                    agent.mode, agent.deadline = 'BLOCKED', min(agent.deadline, self.session.elapsed+.05)
                    break
                render_sync.vector(obj, 'location', candidate)
                render_sync.scalar(obj.rotation_euler, 'z', math.atan2(direction.x, direction.y))
                available -= step
                if step >= distance:
                    agent.path.pop(0)
            moved = (obj.location-before).xy.length
            agent.walked += moved
            self._animate(agent, moved)
            if npc.behavior_template in {'ATTACK', 'ENEMY_BOSS'} and agent.mode == 'CHASE' and self.session.player is not None:
                if segment_clear(tuple(obj.location.xy), tuple(self.session.player.location.xy), blocked, cell_size=.4):
                    self.session._try_npc_attack(obj, self.session.player, npc)
            self.statuses[name] = {'state': agent.mode, 'goal': tuple(agent.goal) if agent.goal is not None else None,
                                   'path_points': len(agent.path), 'decisions': agent.decisions,
                                   'walked': round(agent.walked, 3), 'navigation_rebuilds': self.world.rebuilds}


def register():
    pass


def unregister():
    pass
