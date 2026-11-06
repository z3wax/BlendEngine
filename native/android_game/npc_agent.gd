extends RefCounted
## Local goal-directed NPC. The imported character's immutable resources are shared.
## Decisions and bounded path searches run at a lower rate than native physics.
const MODES = ["IDLE", "FOLLOW_PLAYER", "GUIDE", "PATROL", "GUARD"]
const CELL = 0.6
const GRID_ORIGIN = Vector2(-10.4, -19.2)
const GRID_SIZE = Vector2i(36, 58)
const SEARCH_LIMIT = 512

var game
var config: Dictionary
var body: CharacterBody3D
var skeleton: Skeleton3D
var animations: AnimationPlayer
var spawn: Vector3
var behavior = "GUIDE"
var state = "IDLE"
var walked = 0.0
var decisions = 0
var replans = 0
var max_expansions = 0
var walk_pose_changes = 0
var paused = false
var _decision_time = 0.0
var _path_age = 0.0
var _stuck_time = 0.0
var _force_grid = false
var _patrol_index = 0
var _target_cell = Vector2i(-999, -999)
var _path: Array[Vector3] = []
var _cells: Dictionary = {}
var _clearance: SphereShape3D
var _speed = 3.0
var _interval = 0.15
var _stop_distance = 1.3
var _detection_range = 20.0
var _patrol_radius = 2.5
var _leg_index = -1
var _last_leg_angle = 0.0

func _init(runtime, settings: Dictionary) -> void:
	game = runtime
	config = settings.duplicate(true)
	spawn = settings.get("position", Vector3(1.5, 0.92, 8.0))
	if not spawn.is_finite():
		spawn = Vector3(1.5, 0.92, 8.0)
	spawn.x = clampf(spawn.x, -10.4, 10.4)
	spawn.z = clampf(spawn.z, -19.2, 15.2)
	spawn.y = clampf(spawn.y, 0.92, 3.0)
	_speed = _number(settings.get("speed", 3.0), 0.0, 6.0, 3.0)
	_interval = _number(settings.get("decision_interval", 0.15), 0.08, 2.0, 0.15)
	_stop_distance = _number(settings.get("stop_distance", 1.3), 0.6, 4.0, 1.3)
	_detection_range = _number(settings.get("detection_range", 20.0), 2.0, 40.0, 20.0)
	_patrol_radius = _number(settings.get("patrol_radius", 2.5), 0.6, 7.0, 2.5)
	_clearance = SphereShape3D.new()
	_clearance.radius = 0.32
	_clone_character(str(settings.get("name", "Rescue Scout")).left(60))
	set_behavior(str(settings.get("behavior", "GUIDE")))
	reset()

func _number(value, low: float, high: float, fallback: float) -> float:
	if not (value is int or value is float) or not is_finite(float(value)):
		return fallback
	return clampf(float(value), low, high)

func _clone_character(agent_name: String) -> void:
	# Mesh, Skin and PBR texture resources remain shared; skeleton nodes do not.
	body = game.body.duplicate(0) as CharacterBody3D
	body.name = agent_name.validate_node_name() if not agent_name.is_empty() else "Rescue Scout"
	game.body.get_parent().add_child(body)
	body.collision_layer = 2
	body.collision_mask = 1
	body.floor_snap_length = 0.25
	for node in game._all_nodes(body):
		if node is Skeleton3D:
			skeleton = node
			_leg_index = skeleton.find_bone("leg.L")
			break
	animations = AnimationPlayer.new()
	animations.name = "ScoutAnimation"
	body.add_child(animations)
	animations.root_node = NodePath("..")
	if game.animations != null:
		var source_root = game.animations.get_node(game.animations.root_node)
		var library = AnimationLibrary.new()
		for animation_name in game.animations.get_animation_list():
			var animation = game.animations.get_animation(animation_name).duplicate(true)
			for track in range(animation.get_track_count() - 1, -1, -1):
				var path: NodePath = animation.track_get_path(track)
				var target = source_root.get_node_or_null(NodePath(path.get_concatenated_names()))
				if target == null or not game.body.is_ancestor_of(target):
					animation.remove_track(track)
					continue
				var relative = str(game.body.get_path_to(target))
				if path.get_subname_count() > 0:
					relative += ":" + path.get_concatenated_subnames()
				animation.track_set_path(track, NodePath(relative))
			animation.loop_mode = Animation.LOOP_LINEAR
			if animation.get_track_count() > 0:
				library.add_animation(str(animation_name).replace("/", "_"), animation)
		animations.add_animation_library("", library)
	var callsign = Label3D.new()
	callsign.name = "Callsign"
	callsign.text = agent_name.to_upper()
	callsign.position.y = 1.25
	callsign.font_size = 28
	callsign.pixel_size = 0.006
	callsign.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	callsign.modulate = Color("c8e6dd")
	body.add_child(callsign)

func set_behavior(value: String) -> void:
	behavior = value if value in MODES else "IDLE"
	config["behavior"] = behavior
	_path.clear()
	_cells.clear()
	_decision_time = 0.0
	_target_cell = Vector2i(-999, -999)
	_force_grid = false
	state = "IDLE"

func reset() -> void:
	body.position = spawn
	body.rotation = Vector3.ZERO
	body.velocity = Vector3.ZERO
	walked = 0.0
	walk_pose_changes = 0
	_patrol_index = 0
	_path.clear()
	_cells.clear()
	_decision_time = 0.0
	_path_age = 0.0
	_stuck_time = 0.0
	_force_grid = false
	paused = false
	state = "IDLE"
	animations.speed_scale = 1.0
	_animate(false)
	animations.advance(0.0)

func set_paused(value: bool) -> void:
	paused = value
	var speed = 0.0 if value else 1.0
	if animations.speed_scale != speed:
		animations.speed_scale = speed
	if value:
		body.velocity = Vector3.ZERO

func step(dt: float, is_paused: bool, won: bool) -> void:
	set_paused(is_paused)
	if is_paused:
		body.velocity = Vector3.ZERO
		return
	if won:
		body.velocity = Vector3.ZERO
		state = "IDLE"
		_animate(false)
		return
	_decision_time -= dt
	_path_age += dt
	if _decision_time <= 0.0:
		_decision_time = _interval
		decisions += 1
		_decide()
	while not _path.is_empty() and _horizontal(body.position, _path[0]) < 0.18:
		_path.pop_front()
	var velocity = Vector3.ZERO
	if not _path.is_empty():
		velocity = _path[0] - body.position
		velocity.y = 0.0
		velocity = velocity.normalized() * minf(_speed, velocity.length() / maxf(dt, 0.001))
	body.velocity.x = velocity.x
	body.velocity.z = velocity.z
	if body.is_on_floor():
		body.velocity.y = minf(body.velocity.y, 0.0)
	else:
		body.velocity.y -= 18.0 * dt
	var before = body.position
	body.move_and_slide()
	var movement = _horizontal(body.position, before)
	walked += movement
	var moving = movement > 0.0001
	if moving:
		body.rotation.y = lerp_angle(body.rotation.y, atan2(-velocity.x, -velocity.z), minf(dt * 12.0, 1.0))
		_stuck_time = 0.0
	elif not _path.is_empty():
		_stuck_time += dt
	if _stuck_time > 0.6:
		_force_grid = true
		_cells.clear()
		_path.clear()
		_decision_time = 0.0
		_stuck_time = 0.0
	if body.position.y < -4.0:
		reset()
	_animate(moving)
	if moving and skeleton != null and _leg_index >= 0:
		var angle = skeleton.get_bone_pose_rotation(_leg_index).get_angle()
		if absf(angle - _last_leg_angle) > 0.00001:
			walk_pose_changes += 1
		_last_leg_angle = angle

func _decide() -> void:
	var target = body.position
	var stop = 0.25
	if behavior == "IDLE" or _speed <= 0.0:
		state = "IDLE"
		_path.clear()
		return
	var player_distance = _horizontal(body.position, game.body.position)
	if behavior == "FOLLOW_PLAYER":
		state = "FOLLOW"
		if player_distance > _detection_range:
			state = "WAITING"
			_path.clear()
			return
		target = game.body.position
		stop = _stop_distance
	elif behavior == "GUIDE":
		state = "GUIDE"
		if player_distance > minf(6.0, _detection_range):
			state = "WAITING"
			_path.clear()
			return
		target = game.goal
		for index in range(game.clue_positions.size()):
			if not index in game.collected:
				target = game.clue_positions[index]
				break
		stop = 0.7
	elif behavior == "PATROL":
		state = "PATROL"
		var offsets = [Vector3(_patrol_radius, 0, 0), Vector3(0, 0, -_patrol_radius), Vector3(-_patrol_radius, 0, 0), Vector3(0, 0, _patrol_radius)]
		target = spawn + offsets[_patrol_index]
		if _horizontal(body.position, target) < 0.35:
			_patrol_index = (_patrol_index + 1) % offsets.size()
			target = spawn + offsets[_patrol_index]
	elif behavior == "GUARD":
		state = "GUARD"
		target = spawn
		stop = 0.4
		if player_distance < _detection_range and player_distance > 0.05:
			var facing = game.body.position - body.position
			var angle = atan2(-facing.x, -facing.z)
			if absf(angle_difference(body.rotation.y, angle)) > 0.00001:
				body.rotation.y = angle
	if _horizontal(body.position, target) <= stop:
		_path.clear()
		return
	var cell = _cell(target)
	if _path.is_empty() or cell != _target_cell or _path_age > 1.0:
		_target_cell = cell
		_path = _find_path(target)
		_path_age = 0.0
		if _path.is_empty():
			state = "BLOCKED"

func _animate(walk: bool) -> void:
	var desired = "walk" if walk else "idle"
	for animation_name in animations.get_animation_list():
		if desired in str(animation_name).to_lower():
			if animations.current_animation != animation_name:
				animations.play(animation_name, 0.15)
			return

func _horizontal(a: Vector3, b: Vector3) -> float:
	return Vector2(a.x - b.x, a.z - b.z).length()

func _cell(point: Vector3) -> Vector2i:
	return Vector2i(roundi((point.x - GRID_ORIGIN.x) / CELL), roundi((point.z - GRID_ORIGIN.y) / CELL))

func _point(cell: Vector2i) -> Vector3:
	return Vector3(GRID_ORIGIN.x + cell.x * CELL, 0.95, GRID_ORIGIN.y + cell.y * CELL)

func _excluded() -> Array[RID]:
	var ids: Array[RID] = [body.get_rid(), game.body.get_rid()]
	return ids

func _info(cell: Vector2i) -> Dictionary:
	if _cells.has(cell):
		return _cells[cell]
	var result = {"walkable": false, "height": 0.0}
	if cell.x < 0 or cell.y < 0 or cell.x >= GRID_SIZE.x or cell.y >= GRID_SIZE.y:
		return result
	var point = _point(cell)
	result = _walkability(point)
	_cells[cell] = result
	return result

func _walkability(point: Vector3) -> Dictionary:
	var result = {"walkable": false, "height": 0.0}
	var ray = PhysicsRayQueryParameters3D.create(point + Vector3(0, 3, 0), point - Vector3(0, 2, 0), 1, _excluded())
	var hit = body.get_world_3d().direct_space_state.intersect_ray(ray)
	if not hit.is_empty() and hit.normal.y > 0.75 and hit.position.y >= -0.1 and hit.position.y <= 0.38:
		var shape = PhysicsShapeQueryParameters3D.new()
		shape.shape = _clearance
		shape.transform = Transform3D(Basis.IDENTITY, Vector3(point.x, hit.position.y + 0.8, point.z))
		shape.collision_mask = 1
		shape.exclude = _excluded()
		result["height"] = hit.position.y
		result["walkable"] = body.get_world_3d().direct_space_state.intersect_shape(shape, 1).is_empty()
	return result

func _clear_segment(a: Vector3, b: Vector3) -> bool:
	var query = PhysicsShapeQueryParameters3D.new()
	query.shape = _clearance
	query.transform = Transform3D(Basis.IDENTITY, a)
	query.motion = b - a
	query.collision_mask = 1
	query.exclude = _excluded()
	var motion = body.get_world_3d().direct_space_state.cast_motion(query)
	return motion[0] >= 0.999

func _nearest_walkable(cell: Vector2i) -> Vector2i:
	if _info(cell).walkable:
		return cell
	for radius in range(1, 5):
		for x in range(-radius, radius + 1):
			for z in range(-radius, radius + 1):
				if abs(x) != radius and abs(z) != radius:
					continue
				var candidate = cell + Vector2i(x, z)
				if _info(candidate).walkable:
					return candidate
	return Vector2i(-999, -999)

func _find_path(target: Vector3) -> Array[Vector3]:
	replans += 1
	var start = _nearest_walkable(_cell(body.position))
	var destination = _nearest_walkable(_cell(target))
	var empty: Array[Vector3] = []
	if start.x == -999 or destination.x == -999:
		return empty
	var end_point = _point(destination)
	end_point.y = float(_info(destination).height) + 0.92
	# Grid quantization must not strand patrols short of their real destination.
	# Preserve the exact endpoint only after checking its own floor and clearance.
	var exact = _walkability(target)
	if destination == _cell(target) and exact.walkable:
		end_point = Vector3(target.x, float(exact.height) + 0.92, target.z)
	if not _force_grid and _clear_segment(body.position, end_point):
		var direct: Array[Vector3] = [end_point]
		return direct
	var open: Array[Vector2i] = [start]
	var scores = {start: 0.0}
	var previous: Dictionary = {}
	var closed: Dictionary = {}
	var expanded = 0
	while not open.is_empty() and expanded < SEARCH_LIMIT:
		var current = open[0]
		var best_score = INF
		for candidate in open:
			var score = float(scores[candidate]) + abs(candidate.x - destination.x) + abs(candidate.y - destination.y)
			if score < best_score:
				best_score = score
				current = candidate
		open.erase(current)
		if current == destination:
			var path: Array[Vector3] = []
			while current != start:
				var point = _point(current)
				point.y = float(_info(current).height) + 0.92
				path.push_front(point)
				current = previous[current]
			if path.is_empty() or path[-1].distance_to(end_point) > 0.01:
				path.append(end_point)
			max_expansions = maxi(max_expansions, expanded)
			return path
		closed[current] = true
		expanded += 1
		for offset in [Vector2i.LEFT, Vector2i.RIGHT, Vector2i.UP, Vector2i.DOWN]:
			var neighbor = current + offset
			if closed.has(neighbor) or not _info(neighbor).walkable:
				continue
			var score = float(scores[current]) + 1.0
			if not scores.has(neighbor) or score < float(scores[neighbor]):
				scores[neighbor] = score
				previous[neighbor] = current
				if not neighbor in open:
					open.append(neighbor)
	max_expansions = maxi(max_expansions, expanded)
	return empty

func snapshot() -> Dictionary:
	return {"name": str(body.name), "position": [body.position.x, body.position.y, body.position.z], "behavior": behavior, "patrol_index": _patrol_index}

func restore(data: Dictionary) -> void:
	var position = data.get("position", [])
	if not position is Array or position.size() != 3:
		return
	for value in position:
		if not (value is int or value is float) or not is_finite(float(value)):
			return
	body.position = Vector3(clampf(float(position[0]), -10.4, 10.4), clampf(float(position[1]), 0.92, 3.0), clampf(float(position[2]), -19.2, 15.2))
	body.velocity = Vector3.ZERO
	_patrol_index = int(_number(data.get("patrol_index", 0), 0.0, 3.0, 0.0))
	set_behavior(str(data.get("behavior", behavior)))

func telemetry() -> Dictionary:
	var angle = skeleton.get_bone_pose_rotation(_leg_index).get_angle() if skeleton != null and _leg_index >= 0 else 0.0
	return {"name": str(body.name), "behavior": behavior, "state": state, "position": [body.position.x, body.position.y, body.position.z], "walked": snappedf(walked, 0.01), "decisions": decisions, "replans": replans, "max_expansions": max_expansions, "cached_cells": _cells.size(), "paused": paused, "skeleton_bones": skeleton.get_bone_count() if skeleton != null else 0, "animation": str(animations.current_animation), "leg_l_angle": snappedf(angle, 0.0001), "walk_pose_changes": walk_pose_changes}
