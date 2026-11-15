extends SceneTree
var game: Node3D
var output := ""
var recording := false
var frames := 0
var started_us := 0
func _initialize() -> void:
	call_deferred("run")
func _process(_delta: float) -> bool:
	if recording: frames += 1
	return false
func run() -> void:
	output = OS.get_environment("Z3WAX_PLAYTEST_DIR")
	DirAccess.make_dir_recursive_absolute(output)
	game = load("res://main.tscn").instantiate()
	root.add_child(game)
	await create_timer(3.0).timeout
	await capture("lobby.png")
	game.lobby_stage.training_requested.emit()
	await create_timer(2.0).timeout
	var player: CharacterBody3D = game.actors[game.local_id]
	var start := player.position
	var initial_ammo: int = player.ammo
	recording = true
	started_us = Time.get_ticks_usec()
	Input.action_press("forward")
	await create_timer(1.0).timeout
	game.jump_pending = true
	await create_timer(.35).timeout
	var jump_height: float = player.position.y - start.y
	await capture("gameplay.png")
	await create_timer(.6).timeout
	Input.action_release("forward")
	var moved: float = Vector2(player.position.x - start.x, player.position.z - start.z).length()
	game.fire_pending = true
	await create_timer(.3).timeout
	var shot: bool = player.ammo < initial_ammo
	game.reload_pending = true
	await create_timer(.2).timeout
	var reloading: bool = player.reload_left > 0
	await create_timer(2.0).timeout
	var reloaded: bool = player.ammo == 30 and player.reserve < 120
	await capture("after-reload.png")
	recording = false
	var elapsed := (Time.get_ticks_usec() - started_us) / 1000000.0
	assert(moved > .5 and jump_height > .25 and shot and reloading and reloaded and player.health > 0)
	var report := {"status":"PASS", "moved_metres":moved, "jump_height":jump_height,
		"shot":shot, "reload_started":reloading, "reload_finished":reloaded,
		"actors":game.actors.size(), "frames":frames, "elapsed_seconds":elapsed,
		"measured_fps_during_recording":frames / elapsed,
		"renderer":RenderingServer.get_current_rendering_method(), "device":RenderingServer.get_video_adapter_name(),
		"profile":game.render_budget.profile, "render_scale":root.scaling_3d_scale}
	var file := FileAccess.open(output.path_join("playtest.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "  ")); file.close()
	game._disconnect("Local gameplay test complete")
	await create_timer(.5).timeout
	print("Z3WAX_PACKAGED_GAMEPLAY_PASS ", JSON.stringify(report))
	quit()
func capture(filename: String) -> void:
	await RenderingServer.frame_post_draw
	assert(root.get_texture().get_image().save_png(output.path_join(filename)) == OK)
