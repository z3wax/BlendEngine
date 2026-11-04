extends Node3D
## Native scene, physics, skeletal animation and UI; no browser runtime.
const SPAWN = Vector3(0, 0.94, 10)
const CLUES = [Vector3(0,.6,6), Vector3(-3,.6,2), Vector3(3,.6,-2), Vector3(-2.5,.6,-6), Vector3(0,.6,-10)]
const GOAL = Vector3(0,.9,-14)
const JOURNAL = [
	["01 / THE SILENCE", "Maya: The storm took the relay. Someone at Station Nine is still calling."],
	["02 / A NAME IN THE STATIC", "Field log: the last transmission was from your missing brother, Eli."],
	["03 / RESTORE THE RELAY", "Maya: A battery. Find the regulator and patch the broken antenna."],
	["03 / RESTORE THE RELAY", "Eli, recorded: If you hear this, follow the orange service lights."],
	["04 / THE LAST SIGNAL", "Maya: The transmitter is alive. Reach the terminal before the storm returns."],
	["05 / DAWN", "Eli: Maya? I knew you would come. Rescue is on its way."]]
var spawn = SPAWN
var clue_positions = CLUES.duplicate()
var goal = GOAL
var journal = JOURNAL.duplicate(true)
var save_path = "user://last_signal_checkpoint.json"
var body: CharacterBody3D
var camera: Camera3D
var skeleton: Skeleton3D
var animations: AnimationPlayer
var visual: Node3D
var clues: Array[Node3D] = []
var collected: Array[int] = []
var state = "RUNNING"
var elapsed = 0.0
var phase = 0.0
var distance_walked = 0.0
var jump_count = 0
var jump_held = false
var moving = false
var paused_game = false
var smoke = false
var smoke_runner: RefCounted
var telemetry_time = 0.0
var chapter: Label
var status: Label
var dialogue: Label
var objective: Label
var modal: PanelContainer
var modal_title: Label
var modal_text: Label
var resume_button: Button
var inspect_button: Button
var toast: Label
var hud: Control
var action_buttons: Dictionary = {}

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	get_tree().quit_on_go_back = false
	smoke = "--smoke-test" in OS.get_cmdline_user_args()
	_setup_input()
	_load_story_metadata()
	_load_world()
	if body == null:
		push_error("LAST_SIGNAL_FAIL: missing exported human controller")
		get_tree().quit(2)
		return
	_setup_lighting()
	_setup_ui()
	if not smoke:
		_restore_checkpoint()
	_refresh_ui()
	_report("started")
	if smoke:
		Engine.physics_ticks_per_second = 120
		Engine.max_fps = 0
		save_path = "user://last_signal_smoke_checkpoint.json"
		smoke_runner = load("res://tests/smoke_runner.gd").new(self)

func _setup_input() -> void:
	var keys = {"left":[KEY_A,KEY_LEFT], "right":[KEY_D,KEY_RIGHT], "forward":[KEY_W,KEY_UP], "back":[KEY_S,KEY_DOWN], "jump":[KEY_SPACE], "run":[KEY_SHIFT], "inspect":[KEY_E], "restart":[KEY_R], "pause":[KEY_ESCAPE]}
	for action in keys:
		InputMap.add_action(action)
		for key in keys[action]:
			var event = InputEventKey.new()
			event.physical_keycode = key
			InputMap.action_add_event(action,event)

func _load_story_metadata() -> void:
	if not FileAccess.file_exists("res://assets/story.json"):
		return
	var data = JSON.parse_string(FileAccess.get_file_as_string("res://assets/story.json"))
	if not data is Dictionary:
		push_error("LAST_SIGNAL_FAIL: story metadata is not an object")
		return
	var godot_axes = data.get("coordinate_system", "BLENDER_Z_UP") == "GODOT_Y_UP"
	if data.get("spawn",[]).size() == 3:
		spawn = _story_point(data["spawn"],godot_axes)
	if data.get("items",[]).size() == 5:
		for i in range(5):
			clue_positions[i] = _story_point(data["items"][i],godot_axes)
	if data.get("goal",[]).size() == 3:
		goal = _story_point(data["goal"],godot_axes)
	if data.get("journal",[]).size() == 6:
		journal = data["journal"]

func _story_point(value: Array, godot_axes: bool) -> Vector3:
	return Vector3(value[0],value[1],value[2]) if godot_axes else Vector3(value[0],value[2],-value[1])

func _all_nodes(root: Node) -> Array[Node]:
	var result: Array[Node] = []
	for child in root.get_children():
		result.append(child)
		result.append_array(_all_nodes(child))
	return result

func _load_world() -> void:
	var scene = load("res://assets/last_signal.glb") as PackedScene
	if scene == null:
		return
	var world = scene.instantiate()
	add_child(world)
	var controller: Node3D
	for node in _all_nodes(world):
		var label = str(node.name).to_lower()
		if "player controller" in label or "player_controller" in label:
			controller = node as Node3D
			break
	if controller == null:
		return
	var original_name = controller.name
	var parent = controller.get_parent()
	var original_transform = controller.transform
	controller.name = "DiscardedCollider"
	body = CharacterBody3D.new()
	body.name = original_name
	parent.add_child(body)
	body.transform = original_transform
	for child in controller.get_children():
		child.reparent(body, false)
	controller.queue_free()
	var collider = CollisionShape3D.new()
	var capsule = CapsuleShape3D.new()
	capsule.radius = .24
	capsule.height = 1.84
	collider.shape = capsule
	body.add_child(collider)
	body.position = spawn
	body.floor_snap_length = .25
	body.floor_max_angle = deg_to_rad(48)
	for node in _all_nodes(world):
		var label = str(node.name).to_lower()
		if node is Camera3D or node is Light3D:
			node.queue_free()
		elif node is Skeleton3D:
			skeleton = node
		elif node is AnimationPlayer:
			animations = node
		elif node is MeshInstance3D and not body.is_ancestor_of(node) and node != controller:
			if "clue" in label:
				clues.append(node)
			elif not "distant" in label and not "grass" in label:
				node.create_trimesh_collision()
	clues.sort_custom(func(a,b): return str(a.name) < str(b.name))
	if animations != null:
		for name in animations.get_animation_list():
			if "idle" in str(name).to_lower() or "walk" in str(name).to_lower():
				animations.get_animation(name).loop_mode = Animation.LOOP_LINEAR
	for child in body.get_children():
		if child is Node3D and not child is CollisionShape3D:
			visual = child
			break
	camera = Camera3D.new()
	camera.name = "NativeFollowCamera"
	camera.fov = 57
	camera.near = .1
	camera.far = 170
	add_child(camera)
	camera.current = true
	_update_camera(1.0)

func _setup_lighting() -> void:
	var sky_material = ProceduralSkyMaterial.new()
	sky_material.sky_top_color = Color("47627b")
	sky_material.sky_horizon_color = Color("c6b69b")
	sky_material.ground_horizon_color = Color("b1a58e")
	sky_material.ground_bottom_color = Color("44493f")
	sky_material.sky_energy_multiplier = .7
	sky_material.ground_energy_multiplier = .7
	var sky = Sky.new()
	sky.sky_material = sky_material
	var env = Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color("adc3d9")
	env.ambient_light_energy = .32
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.fog_enabled = true
	env.fog_light_color = Color("879ca9")
	env.fog_density = .002
	var world_env = WorldEnvironment.new()
	world_env.environment = env
	add_child(world_env)
	var sun = DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-34,-35,0)
	sun.light_color = Color("ffd9a3")
	sun.light_energy = .95
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 65
	sun.shadow_bias = .035
	add_child(sun)

func _style(color: Color, border = Color(0.8,.57,.3,.5)) -> StyleBoxFlat:
	var box = StyleBoxFlat.new()
	box.bg_color = color
	box.border_color = border
	box.set_border_width_all(1)
	box.set_corner_radius_all(12)
	box.content_margin_left = 18
	box.content_margin_right = 18
	box.content_margin_top = 12
	box.content_margin_bottom = 12
	return box

func _label(text_value: String, size: int, color = Color("e4e9e7")) -> Label:
	var node = Label.new()
	node.text = text_value
	node.add_theme_font_size_override("font_size",size)
	node.add_theme_color_override("font_color",color)
	return node

func _button(text_value: String, position_value: Vector2, size_value: Vector2, callback: Callable) -> Button:
	var button = Button.new()
	button.text = text_value
	button.position = position_value
	button.size = size_value
	button.add_theme_font_size_override("font_size",20)
	button.add_theme_stylebox_override("normal",_style(Color(.025,.045,.055,.85)))
	button.add_theme_stylebox_override("pressed",_style(Color(.43,.25,.10,.95),Color("edba77")))
	button.add_theme_stylebox_override("hover",_style(Color(.07,.10,.12,.9)))
	button.focus_mode = Control.FOCUS_NONE
	if callback.is_valid():
		button.pressed.connect(callback)
	return button

func _touch_action(button: Button, action: String) -> void:
	# TouchScreenButton processes each finger independently, including move + jump.
	var touch = TouchScreenButton.new()
	var shape = RectangleShape2D.new()
	shape.size = button.size
	touch.shape = shape
	touch.position = button.size / 2
	touch.action = action
	touch.passby_press = true
	button.add_child(touch)
	if OS.has_feature("mobile"):
		button.mouse_filter = Control.MOUSE_FILTER_IGNORE
	button.button_down.connect(func(): Input.action_press(action))
	button.button_up.connect(func(): Input.action_release(action))
	action_buttons[action] = button

func _setup_ui() -> void:
	var layer = CanvasLayer.new()
	add_child(layer)
	hud = Control.new()
	hud.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	hud.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(hud)
	var theme = Theme.new()
	theme.default_font_size = 18
	hud.theme = theme
	var header = PanelContainer.new()
	header.position = Vector2(24,24)
	header.size = Vector2(484,132)
	header.add_theme_stylebox_override("panel",_style(Color(.015,.03,.04,.88)))
	hud.add_child(header)
	var column = VBoxContainer.new()
	header.add_child(column)
	var title = HBoxContainer.new()
	column.add_child(title)
	if ResourceLoader.exists("res://assets/brand/logo.jpg"):
		var logo = TextureRect.new()
		logo.texture = load("res://assets/brand/logo.jpg")
		logo.custom_minimum_size = Vector2(46,30)
		logo.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		logo.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		title.add_child(logo)
	title.add_child(_label(" LAST SIGNAL",27,Color("f0c38b")))
	chapter = _label("",17)
	column.add_child(chapter)
	status = _label("",16,Color("a9bdbd"))
	column.add_child(status)
	objective = _label("FOLLOW THE AMBER SERVICE LIGHTS",15,Color("f0c38b"))
	objective.position = Vector2(24,174)
	hud.add_child(objective)
	var pause = _button("Ⅱ  PAUSE",Vector2(-166,24),Vector2(142,52),_toggle_pause)
	pause.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	hud.add_child(pause)
	var story = PanelContainer.new()
	story.position = Vector2(-342,-139)
	story.size = Vector2(684,112)
	story.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	story.add_theme_stylebox_override("panel",_style(Color(.015,.03,.04,.90)))
	hud.add_child(story)
	dialogue = _label("",19)
	dialogue.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	dialogue.custom_minimum_size = Vector2(642,84)
	story.add_child(dialogue)
	var directions = [["↑","forward",Vector2(103,-242)],["←","left",Vector2(24,-163)],["↓","back",Vector2(103,-163)],["→","right",Vector2(182,-163)]]
	for entry in directions:
		var button = _button(entry[0],entry[2],Vector2(72,72),Callable())
		button.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
		hud.add_child(button)
		_touch_action(button,entry[1])
	var jump = _button("JUMP",Vector2(-158,-135),Vector2(134,100),Callable())
	jump.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	hud.add_child(jump)
	_touch_action(jump,"jump")
	inspect_button = _button("INSPECT  E",Vector2(-200,-213),Vector2(176,60),_inspect)
	inspect_button.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	hud.add_child(inspect_button)
	var control_hint = "Touch pad · Jump · Inspect · Back pauses" if OS.has_feature("mobile") else "WASD / arrows · Space jump · E inspect · Esc pause"
	toast = _label(control_hint,14,Color("bac6c5"))
	toast.position = Vector2(24,-31)
	toast.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	hud.add_child(toast)
	modal = PanelContainer.new()
	modal.set_anchors_preset(Control.PRESET_CENTER)
	modal.position = Vector2(-280,-157)
	modal.size = Vector2(560,314)
	modal.add_theme_stylebox_override("panel",_style(Color(.015,.03,.04,.98),Color("d29b5a")))
	hud.add_child(modal)
	var contents = VBoxContainer.new()
	contents.add_theme_constant_override("separation",17)
	modal.add_child(contents)
	modal_title = _label("SIGNAL ON HOLD",28,Color("f0c38b"))
	contents.add_child(modal_title)
	modal_text = _label("Checkpoint saved. Maya will be here when you return.",18)
	modal_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	modal_text.custom_minimum_size = Vector2(510,60)
	contents.add_child(modal_text)
	resume_button = _button("CONTINUE",Vector2.ZERO,Vector2(500,52),_toggle_pause)
	resume_button.custom_minimum_size.y = 52
	contents.add_child(resume_button)
	var replay = _button("RESTART CHAPTER",Vector2.ZERO,Vector2(500,52),_restart)
	replay.custom_minimum_size.y = 52
	contents.add_child(replay)
	modal.hide()

func _physics_process(dt: float) -> void:
	if body == null:
		return
	for action in action_buttons:
		action_buttons[action].set_pressed_no_signal(Input.is_action_pressed(action))
	if Input.is_action_just_pressed("pause"):
		_toggle_pause()
	if Input.is_action_just_pressed("restart"):
		_restart()
	if smoke:
		smoke_runner.step()
	if paused_game or state == "WON":
		return
	elapsed += dt
	var input = Input.get_vector("left","right","forward","back")
	var direction = Vector3(input.x,0,input.y)
	var speed = 6.0 if Input.is_action_pressed("run") else 3.7
	body.velocity.x = direction.x * speed
	body.velocity.z = direction.z * speed
	if not body.is_on_floor():
		body.velocity.y -= 18 * dt
	elif body.velocity.y < 0:
		body.velocity.y = 0
	var jump_down = Input.is_action_pressed("jump")
	var jump_requested = Input.is_action_just_pressed("jump") or jump_down
	if jump_requested and not jump_held and body.is_on_floor():
		body.velocity.y = 5.5
		jump_count += 1
		_report("jump")
	jump_held = jump_down
	var previous = body.position
	body.move_and_slide()
	body.position.x = clampf(body.position.x,-10.6,10.6)
	body.position.z = clampf(body.position.z,-19.4,15.4)
	if body.position.y < -4:
		body.position = spawn
		body.velocity = Vector3.ZERO
	var moved = Vector2(body.position.x-previous.x,body.position.z-previous.z).length()
	distance_walked += moved
	phase += moved*7
	moving = moved > .0001
	if moving:
		body.rotation.y = lerp_angle(body.rotation.y,atan2(-direction.x,-direction.z),minf(dt*14,1))
	_animate_human(moving)
	_update_camera(dt*7)
	for i in range(mini(5,clues.size())):
		if not i in collected and _horizontal_distance(body.position,clue_positions[i]) < 1.05:
			collected.append(i)
			clues[i].hide()
			_refresh_ui()
			_save_checkpoint()
			_report("clue_"+str(i+1))
	if Input.is_action_just_pressed("inspect"):
		_inspect()
	if collected.size() == 5 and _horizontal_distance(body.position,goal) < 1.5 and body.is_on_floor():
		state = "WON"
		_animate_human(false)
		_refresh_ui()
		_save_checkpoint()
		_show_modal(true)
		_report("won")
	telemetry_time += dt
	if telemetry_time > 2.0:
		telemetry_time = 0
		_report("playing")

func _horizontal_distance(a: Vector3,b: Vector3) -> float:
	return Vector2(a.x-b.x,a.z-b.z).length()

func _animate_human(walk: bool) -> void:
	if animations != null:
		var desired = "walk" if walk else "idle"
		for name in animations.get_animation_list():
			if desired in str(name).to_lower():
				if animations.current_animation != name:
					animations.play(name,.18)
				return
	if skeleton == null:
		return
	var swing = sin(phase)*.42 if walk else sin(elapsed*1.7)*.012
	for side in ["L","R"]:
		var sign_value = 1 if side == "L" else -1
		for kind in ["leg","calf"]:
			var index = skeleton.find_bone(kind+"."+side)
			if index >= 0:
				var angle = swing*sign_value if kind == "leg" else maxf(0,-swing*sign_value)*1.1
				skeleton.set_bone_pose_rotation(index,Quaternion(Vector3.RIGHT,angle))

func _update_camera(weight: float) -> void:
	var desired = body.position + Vector3(0,2.7,5.5)
	camera.position = camera.position.lerp(desired,clampf(weight,0,1))
	camera.look_at(body.position+Vector3(0,.42,-.35))

func _refresh_ui() -> void:
	var count = collected.size()
	chapter.text = journal[count][0]
	status.text = "MAYA / FIELD ENGINEER       CLUES  %d / 5" % count
	dialogue.text = journal[count][1]
	objective.text = "REACH THE RELAY TERMINAL" if count == 5 else "FOLLOW THE AMBER SERVICE LIGHTS"
	if state == "WON":
		objective.text = "RESCUE BEACON ONLINE / CHAPTER COMPLETE"

func _inspect() -> void:
	if paused_game:
		return
	if _horizontal_distance(body.position,goal) < 3:
		dialogue.text = "Relay terminal: antenna patched. " + ("Rescue uplink ready." if collected.size() == 5 else "Find the remaining field components.")
	else:
		dialogue.text = "Maya: Five field components. Follow the service lights to restore the relay."
	_report("inspect")

func _toggle_pause() -> void:
	if state == "WON":
		return
	paused_game = not paused_game
	modal.visible = paused_game
	if animations != null:
		animations.speed_scale = 0.0 if paused_game else 1.0
	if paused_game:
		_release_actions()
		_save_checkpoint()
		_show_modal(false)
	_report("paused" if paused_game else "resumed")

func _show_modal(won: bool) -> void:
	modal.show()
	modal_title.text = "A VOICE IN THE STATIC" if won else "SIGNAL ON HOLD"
	modal_text.text = "Maya found Eli. The rescue beacon is online.\nCHAPTER ONE COMPLETE" if won else "Checkpoint saved. Maya will be here when you return."
	resume_button.visible = not won

func _restart() -> void:
	_release_actions()
	state = "RUNNING"
	paused_game = false
	if animations != null:
		animations.speed_scale = 1.0
	modal.hide()
	body.position = spawn
	body.rotation = Vector3.ZERO
	body.velocity = Vector3.ZERO
	collected.clear()
	elapsed = 0
	jump_held = false
	_animate_human(false)
	for clue in clues:
		clue.show()
	_refresh_ui()
	_update_camera(1)
	_save_checkpoint()
	_report("restarted")

func _release_actions() -> void:
	for action in ["left","right","forward","back","jump","run"]:
		Input.action_release(action)

func _save_checkpoint() -> void:
	var file = FileAccess.open(save_path,FileAccess.WRITE)
	file.store_string(JSON.stringify({"version":1,"collected":collected,"position":[body.position.x,body.position.y,body.position.z],"elapsed":elapsed,"state":state}))

func _restore_checkpoint() -> void:
	if not FileAccess.file_exists(save_path):
		return
	var data = JSON.parse_string(FileAccess.get_file_as_string(save_path))
	if not data is Dictionary or data.get("version") != 1:
		return
	for value in data.get("collected",[]):
		if int(value) >= 0 and int(value) < clues.size() and not int(value) in collected:
			collected.append(int(value))
			clues[int(value)].hide()
	var p = data.get("position",[])
	if p.size() == 3:
		body.position = Vector3(clampf(p[0],-10.6,10.6),clampf(p[1],.94,8),clampf(p[2],-19.4,15.4))
	elapsed = maxf(0,float(data.get("elapsed",0)))
	state = data.get("state","RUNNING")
	if state == "WON":
		_show_modal(true)
	_update_camera(1)

func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_GO_BACK_REQUEST and body != null:
		_toggle_pause()
	if what == NOTIFICATION_APPLICATION_PAUSED and body != null:
		if not paused_game and state != "WON":
			_toggle_pause()

func _report(event: String) -> void:
	var data = {"event":event,"story_id":"LAST_SIGNAL","state":state,"score":collected.size(),"health":100,"elapsed":snappedf(elapsed,.01),"source_position":[snappedf(body.position.x,.01),snappedf(-body.position.z,.01),snappedf(body.position.y,.01)],"clues":collected.size(),"position":[snappedf(body.position.x,.01),snappedf(body.position.y,.01),snappedf(body.position.z,.01)],"floor":body.is_on_floor(),"paused":paused_game,"walked":snappedf(distance_walked,.01),"jumps":jump_count,"skeleton_bones":skeleton.get_bone_count() if skeleton else 0,"animation":str(animations.current_animation) if animations else "procedural","renderer":RenderingServer.get_current_rendering_method(),"native":true}
	print("LAST_SIGNAL_STATE "+JSON.stringify(data))
	var file = FileAccess.open("user://qa_state.json",FileAccess.WRITE)
	file.store_string(JSON.stringify(data))
