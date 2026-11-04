extends RefCounted
## Drives the real InputMap/CharacterBody3D; no position assignment along the route.
var game
var phase = "quick_jump"
var ticks = 0
var jumped = false
var jump_tick = 0
var jump_count_before = 0
var jump_airborne = false
var jump_peak = 0.0
var landing_ticks = 0
var quick_jump_checked = false
var target_index = 0
var pause_ticks = 0
var pause_position = Vector3.ZERO
var back_checked = false
var save_checked = false
var bone_min = 100.0
var bone_max = -100.0
var start = Vector3.ZERO
var route = [Vector3(0,0,6), Vector3(-3,0,2), Vector3(-3,0,-2), Vector3(3,0,-2), Vector3(-2.5,0,-6), Vector3(0,0,-10), Vector3(0,0,-14)]

func _init(runtime) -> void:
	game = runtime
	start = game.body.position

func fail(message: String, code: int) -> void:
	push_error("LAST_SIGNAL_SMOKE_FAIL: "+message)
	game.get_tree().quit(code)

func step() -> void:
	ticks += 1
	if ticks > 15000:
		fail("physics route timed out at "+str(game.body.position),3)
		return
	if game.skeleton == null or game.clues.size() != 5:
		fail("the exported human skeleton / five scene clues are missing",4)
		return
	if game.get_tree().quit_on_go_back:
		fail("Android Back must be handled by the pause UI without quitting",15)
		return
	if phase == "quick_jump":
		if not jumped:
			if not game.body.is_on_floor():
				return
			jump_count_before = game.jump_count
			jump_tick = ticks
			jump_peak = game.body.position.y
			# Both events arrive before the next physics update, like a quick tap.
			Input.action_press("jump")
			Input.action_release("jump")
			if Input.is_action_pressed("jump"):
				fail("quick jump fixture did not release before physics",11)
				return
			jumped = true
			return
		jump_peak = maxf(jump_peak,game.body.position.y)
		if not game.body.is_on_floor():
			jump_airborne = true
		if ticks > jump_tick+1 and game.jump_count != jump_count_before+1:
			fail("press/release before physics must trigger exactly one jump",12)
			return
		if jump_airborne and game.body.is_on_floor():
			if jump_peak < start.y+.3 or game.body.position.distance_to(start) > .2:
				fail("quick jump must leave the ground and land at the spawn",13)
				return
			quick_jump_checked = true
			print("LAST_SIGNAL_QUICK_JUMP_PASS: press and release before physics; one jump; peak %.2fm; grounded landing" % jump_peak)
			phase = "jump"
			jumped = false
			jump_airborne = false
		elif ticks-jump_tick > 180:
			fail("quick jump did not complete a grounded landing",14)
		return
	if phase == "jump":
		if game.body.is_on_floor() and not jumped:
			jump_count_before = game.jump_count
			Input.action_press("jump")
			jumped = true
		elif jumped:
			if not game.body.is_on_floor():
				jump_airborne = true
			if jump_airborne and game.body.is_on_floor():
				landing_ticks += 1
				if landing_ticks <= 12:
					return
				Input.action_release("jump")
				if game.jump_count != jump_count_before+1 or game.body.position.distance_to(start) > .2:
					fail("held jump must land without automatically jumping again",5)
					return
				game.notification(Node.NOTIFICATION_WM_GO_BACK_REQUEST)
				pause_position = game.body.position
				phase = "pause"
		return
	if phase == "pause":
		pause_ticks += 1
		Input.action_press("forward")
		if not game.paused_game or not game.modal.visible or game.body.position != pause_position:
			fail("pause did not freeze movement",6)
		if pause_ticks > 10:
			game.notification(Node.NOTIFICATION_WM_GO_BACK_REQUEST)
			if game.paused_game or game.modal.visible:
				fail("Back notification did not resume the running chapter",16)
				return
			back_checked = true
			print("LAST_SIGNAL_BACK_PASS: quit_on_go_back false; Back pauses for 11 physics ticks then resumes without exiting")
			game._restart()
			if game.body.position != game.spawn or game.collected.size() != 0 or game.paused_game or game.modal.visible:
				fail("chapter restart did not restore the spawn",7)
			phase = "route"
		return
	if not save_checked and game.collected.size() > 0:
		var data = JSON.parse_string(FileAccess.get_file_as_string(game.save_path))
		if not data is Dictionary or data.get("collected",[]).size() != game.collected.size():
			fail("native checkpoint did not persist collected clues",8)
		save_checked = true
	var leg = game.skeleton.find_bone("leg.L")
	if leg >= 0 and game.elapsed > 5.0 and game.state == "RUNNING":
		var angle = game.skeleton.get_bone_pose_rotation(leg).get_angle()
		bone_min = minf(bone_min,angle)
		bone_max = maxf(bone_max,angle)
	if game.state == "WON":
		if game.collected.size() != 5 or game.distance_walked < 25 or game.jump_count < 3 or not save_checked or not quick_jump_checked or not back_checked:
			fail("rescue completion evidence is incomplete",9)
			return
		if bone_max-bone_min < .05:
			fail("human walk animation did not change skeleton poses",10)
			return
		print("LAST_SIGNAL_SMOKE_PASS: native skinned human, floor physics, input movement, quick tap jump, held jump without repeat, pause, restart, checkpoint, five clues and rescue win; walked %.2fm; jumps %d" % [game.distance_walked,game.jump_count])
		DirAccess.remove_absolute(game.save_path)
		game.get_tree().quit(0)
		return
	game._release_actions()
	var target: Vector3 = route[target_index]
	if game._horizontal_distance(game.body.position,target) < .25:
		target_index = mini(target_index+1,route.size()-1)
		target = route[target_index]
	var offset: Vector3 = target-game.body.position
	if absf(offset.x) > .15:
		Input.action_press("right" if offset.x > 0 else "left")
	if absf(offset.z) > .15:
		Input.action_press("back" if offset.z > 0 else "forward")
	if target_index == 6 and game.body.position.z < -11 and game.body.position.z > -12 and game.body.is_on_floor():
		Input.action_press("jump")
