extends Node
## Frame-budget controller for the live raster game. No offline renderer or AI.
## Native retains resolution/shadows. Balanced and Speed explicitly trade render
## resolution and shadow range for frame time; texture assets stay unchanged.
const PROFILES := ["native", "balanced", "speed"]
var profile := "native"
var target_fps := 60.0
var minimum_scale := 1.0
var elapsed := 0.0
var frame_times: Array[float] = []
var warmup := 2.0
var fps := 0.0
var p95_ms := 0.0
var slow_windows := 0
var fast_windows := 0
var game: Node3D
var readout: Label
var selector: Button
var last_tick := 0
func _ready() -> void:
	game = get_parent()
	var requested := OS.get_environment("Z3WAX_RENDER_PROFILE")
	if requested in PROFILES: profile = requested
	var layer := CanvasLayer.new()
	layer.layer = 20
	add_child(layer)
	selector = Button.new()
	selector.position = Vector2(1060, 140) if OS.has_feature("mobile") else Vector2(14, 675)
	selector.custom_minimum_size = Vector2(200, 32)
	selector.pressed.connect(func(): set_profile(PROFILES[(PROFILES.find(profile) + 1) % PROFILES.size()]))
	layer.add_child(selector)
	readout = Label.new()
	readout.position = Vector2(650, 145) if OS.has_feature("mobile") else Vector2(225, 682)
	readout.add_theme_font_size_override("font_size", 16)
	readout.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(readout)
	set_profile(profile)
	last_tick = Time.get_ticks_usec()
func set_profile(value: String) -> void:
	if value not in PROFILES: return
	profile = value
	target_fps = 30.0 if profile == "balanced" else 60.0
	minimum_scale = 1.0 if profile == "native" else (.75 if profile == "balanced" else .5)
	var viewport := get_viewport()
	viewport.scaling_3d_scale = 1.0
	viewport.msaa_3d = Viewport.MSAA_2X if profile == "native" else Viewport.MSAA_DISABLED
	var range_m := 130.0 if profile == "native" else (70.0 if profile == "balanced" else 40.0)
	if game.match_sun: game.match_sun.directional_shadow_max_distance = range_m
	slow_windows = 0
	fast_windows = 0
	warmup = 2.0
	selector.text = "GRAPHICS: " + profile.to_upper()
	selector.tooltip_text = "Native: original resolution and shadows. Balanced/Speed: adaptive 3D resolution and shorter shadow range. UI and texture files retain their resolution. Target FPS is not guaranteed. Desktop: Escape releases the mouse to change this option."
func _process(_delta: float) -> void:
	var now := Time.get_ticks_usec()
	var seconds := (now - last_tick) / 1000000.0
	last_tick = now
	if seconds <= 0.0: return
	if warmup > 0:
		warmup -= seconds
		return
	frame_times.append(seconds * 1000.0)
	elapsed += seconds
	if elapsed < .5: return
	fps = frame_times.size() / elapsed
	frame_times.sort()
	p95_ms = frame_times[mini(frame_times.size() - 1, ceili(frame_times.size() * .95) - 1)]
	var mean_ms := elapsed * 1000.0 / frame_times.size()
	frame_times.clear()
	elapsed = 0.0
	if profile != "native":
		var budget := 1000.0 / target_fps
		slow_windows = slow_windows + 1 if mean_ms > budget * 1.15 else 0
		fast_windows = fast_windows + 1 if mean_ms < budget * .75 else 0
		if slow_windows >= 2:
			get_viewport().scaling_3d_scale = maxf(minimum_scale, get_viewport().scaling_3d_scale - .1)
			slow_windows = 0
		elif fast_windows >= 6:
			get_viewport().scaling_3d_scale = minf(1.0, get_viewport().scaling_3d_scale + .05)
			fast_windows = 0
	readout.text = "%.1f FPS  •  p95 %.1f ms  •  3D %d%%" % [fps, p95_ms, roundi(get_viewport().scaling_3d_scale * 100)]
	for actor in game.actors.values():
		if actor.visual and actor.visual.weapon:
			var distant: bool = actor.global_position.distance_squared_to(game.camera.global_position) > 400
			for mesh in actor.visual.weapon.find_children("*", "MeshInstance3D", true, false):
				mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF if profile == "speed" and distant else GeometryInstance3D.SHADOW_CASTING_SETTING_ON
