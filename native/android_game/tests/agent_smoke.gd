extends SceneTree
## Exercises a real skinned NPC, world collision and the normal player InputMap.

var game
var npc
var ticks = 0

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, message: String) -> bool:
	if condition:
		return true
	push_error("LAST_SIGNAL_AGENT_FAIL: " + message)
	quit(20)
	return false

func _ticks(count: int) -> void:
	for _index in range(count):
		await physics_frame
		await process_frame
		ticks += 1

func _distance(a: Vector3, b: Vector3) -> float:
	return Vector2(a.x-b.x, a.z-b.z).length()

func _mesh(node: Node) -> MeshInstance3D:
	for child in node.find_children("*", "MeshInstance3D", true, false):
		if child.skin != null:
			return child
	return null

func _run() -> void:
	var checkpoint = "user://last_signal_agent_smoke_checkpoint.json"
	DirAccess.remove_absolute(checkpoint)
	game = load("res://main.tscn").instantiate()
	game.save_path = checkpoint
	root.add_child(game)
	if not _check(game.npc_agents.size() == 1, "the chapter must contain one default rescue scout"):
		return
	npc = game.npc_agents[0]
	if not _check(npc.body != game.body and npc.skeleton != game.skeleton,
			"the scout must own a separate physical body and skeleton"):
		return
	if not _check(npc.skeleton != null and npc.skeleton.get_bone_count() == 11
			and npc.animations != null and npc.animations != game.animations,
			"the scout must retain the human rig and independent animation player"):
		return
	var player_mesh = _mesh(game.body)
	var scout_mesh = _mesh(npc.body)
	if not _check(player_mesh != null and scout_mesh != null and player_mesh.mesh == scout_mesh.mesh,
			"human geometry and materials must share their existing GPU resources"):
		return
	var obstacle = StaticBody3D.new()
	obstacle.name = "Agent smoke obstacle"
	var collision = CollisionShape3D.new()
	var shape = BoxShape3D.new()
	shape.size = Vector3(2.2, 2.0, .7)
	collision.shape = shape
	obstacle.add_child(collision)
	game.add_child(obstacle)
	obstacle.position = Vector3(.7, 1.0, 9.0)
	npc.set_behavior("FOLLOW_PLAYER")
	await _ticks(8)
	var origin = npc.body.position
	var went_around = false
	for _index in range(420):
		await _ticks(1)
		var p = npc.body.position
		went_around = went_around or p.x > 2.04 or p.x < -.64
		if not _check(not (p.x > -.39 and p.x < 1.79 and p.z > 8.66 and p.z < 9.34),
				"the NPC crossed through the solid test wall"):
			return
		if _distance(p, game.body.position) < 1.8 and went_around:
			break
	if not _check(went_around and _distance(npc.body.position, game.body.position) < 1.8
			and npc.walked > 1.5 and _distance(origin, npc.body.position) > .8,
			"follow must navigate around a blocking wall using actual physics movement"):
		return
	if not _check(npc.replans > 0 and npc.max_expansions <= 512,
			"obstacle planning must execute within the per-search expansion budget"):
		return
	var detour_walked = npc.walked
	print("LAST_SIGNAL_AGENT_OBSTACLE_PASS: collision-safe detour; walked %.2fm" % npc.walked)
	obstacle.queue_free()
	await _ticks(2)
	npc.set_behavior("PATROL")
	var walked_before = npc.walked
	var player_position = game.body.position
	var leg = npc.skeleton.find_bone("leg.L")
	var player_leg = game.skeleton.find_bone("leg.L")
	var bone_min = 100.0
	var bone_max = -100.0
	var player_bone_min = 100.0
	var player_bone_max = -100.0
	for _index in range(240):
		await _ticks(1)
		var angle = npc.skeleton.get_bone_pose_rotation(leg).get_angle()
		bone_min = minf(bone_min, angle)
		bone_max = maxf(bone_max, angle)
		angle = game.skeleton.get_bone_pose_rotation(player_leg).get_angle()
		player_bone_min = minf(player_bone_min, angle)
		player_bone_max = maxf(player_bone_max, angle)
	if not _check(npc.walked > walked_before + 1.0 and bone_max-bone_min > .05
			and player_bone_max-player_bone_min < .04
			and _distance(game.body.position, player_position) < .01,
			"autonomous patrol must animate the scout without moving or animating the idle player"):
		return
	game._toggle_pause()
	var paused_position = npc.body.position
	var paused_bone = npc.skeleton.get_bone_pose_rotation(leg)
	await _ticks(30)
	if not _check(game.paused_game and npc.body.position.is_equal_approx(paused_position)
			and npc.skeleton.get_bone_pose_rotation(leg).is_equal_approx(paused_bone),
			"pause must freeze both NPC physics and its independent skeleton"):
		return
	game._toggle_pause()
	walked_before = npc.walked
	await _ticks(90)
	if not _check(not game.paused_game and npc.walked > walked_before + .25,
			"resuming must restart autonomous movement"):
		return
	npc.set_behavior("FOLLOW_PLAYER")
	walked_before = npc.walked
	player_position = game.body.position
	Input.action_press("forward")
	await _ticks(90)
	Input.action_release("forward")
	await _ticks(120)
	if not _check(_distance(game.body.position, player_position) > 3.0
			and npc.walked > walked_before + 1.0
			and _distance(npc.body.position, game.body.position) < 2.1,
			"following must react to actual player input movement"):
		return
	npc.set_behavior("GUIDE")
	walked_before = npc.walked
	var clues_before = game.collected.size()
	await _ticks(240)
	if not _check(npc.walked > walked_before + .5 and game.collected.size() == clues_before,
			"guide must lead toward an objective without collecting it for the player"):
		return
	if not _check(npc.decisions > 2 and npc.decisions < ticks / 3
			and npc.max_expansions <= 512, "agent decisions must be throttled rather than running every physics tick"):
		return
	var saved = npc.snapshot()
	var saved_position = npc.body.position
	game._save_checkpoint()
	var persisted = JSON.parse_string(FileAccess.get_file_as_string(checkpoint))
	if not _check(persisted is Dictionary and persisted.get("npc_agents", []).size() == 1
			and persisted["npc_agents"][0].get("name", "") == str(npc.body.name),
			"the chapter checkpoint must persist the scout together with the player"):
		return
	npc.reset()
	if not _check(_distance(npc.body.position, npc.spawn) < .01,
			"reset must restore the NPC's configured spawn"):
		return
	npc.restore(saved)
	if not _check(npc.body.position.distance_to(saved_position) < .01,
			"checkpoint restore must recover the NPC's actual saved position"):
		return
	npc.reset()
	game._restore_checkpoint()
	if not _check(npc.body.position.distance_to(saved_position) < .01,
			"loading the on-disk chapter checkpoint must restore the scout"):
		return
	npc.set_behavior("GUARD")
	await _ticks(360)
	if not _check(_distance(npc.body.position, npc.spawn) < 2.0,
			"guard mode must return to its post"):
		return
	npc.set_behavior("IDLE")
	var idle_position = npc.body.position
	await _ticks(90)
	if not _check(_distance(npc.body.position, idle_position) < .01,
			"idle must stop horizontal movement"):
		return
	game._restart()
	if not _check(_distance(npc.body.position, npc.spawn) < .01 and game.collected.is_empty()
			and game.state == "RUNNING" and not game.paused_game,
			"chapter restart must reset the scout together with the player"):
		return
	var telemetry = game.agent_telemetry()
	if not _check(telemetry.size() == 1 and npc.max_expansions <= 512,
			"agent state must remain observable after restart"):
		return
	DirAccess.remove_absolute(checkpoint)
	print("LAST_SIGNAL_AGENT_REPORT " + JSON.stringify({"passed": true,
		"shared_human_mesh": true, "independent_skeletons": true,
		"collision_safe_detour_m": snappedf(detour_walked, .01),
		"walk_bone_angle_range": snappedf(bone_max-bone_min, .001),
		"idle_player_bone_angle_range": snappedf(player_bone_max-player_bone_min, .001),
		"pause_ticks": 30, "physics_ticks": ticks, "decisions": npc.decisions,
		"peak_path_expansions": npc.max_expansions, "disk_checkpoint_restored": true}))
	print("LAST_SIGNAL_AGENT_PASS: shared human resources, independent walking bones, obstacle detour, follow/guide/patrol/guard/idle, pause/resume, checkpoint and chapter restart")
	quit(0)
