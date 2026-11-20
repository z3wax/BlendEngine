extends SceneTree
var game: Node3D
var samples: Array[float] = []
var last_us := 0
var began_us := 0
var measuring := false
var initial_position := Vector3.ZERO
var draw_calls := 0
var primitives := 0
func _initialize() -> void:
	call_deferred("run")
func run() -> void:
	if DisplayServer.get_name() == "headless":
		push_error("Benchmark requires an actual rendered viewport"); quit(1); return
	Engine.max_fps = 0
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	game = load("res://main.tscn").instantiate()
	root.add_child(game)
	game._start_training()
	await create_timer(2.0).timeout
	initial_position = game.actors[game.local_id].position
	Input.action_press("forward")
	began_us = Time.get_ticks_usec()
	last_us = began_us
	measuring = true
func _process(_delta: float) -> bool:
	if not measuring: return false
	var now := Time.get_ticks_usec()
	var elapsed := (now - began_us) / 1000000.0
	samples.append((now - last_us) / 1000.0)
	last_us = now
	draw_calls = maxi(draw_calls, int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)))
	primitives = maxi(primitives, int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)))
	if elapsed > 1.0: game.fire_pending = true
	if elapsed > 2.0: Input.action_release("forward")
	if elapsed > 3.0 and elapsed < 3.5: game.reload_pending = true
	if elapsed >= 6.0:
		measuring = false
		finish(elapsed)
	return false
func finish(elapsed: float) -> void:
	var distance: float = initial_position.distance_to(game.actors[game.local_id].position)
	samples.sort()
	var report := {
		"renderer": RenderingServer.get_current_rendering_method(),
		"device": RenderingServer.get_video_adapter_name(),
		"viewport": [root.size.x, root.size.y],
		"frames": samples.size(), "elapsed_seconds": elapsed,
		"average_fps": samples.size() / elapsed,
		"median_frame_ms": samples[samples.size() / 2],
		"p95_frame_ms": samples[mini(samples.size() - 1, ceili(samples.size() * .95) - 1)],
		"max_draw_calls": draw_calls, "max_primitives": primitives,
		"moved_metres": distance, "actors": game.actors.size(),
		"cycles_worker_used": false,
	}
	if "render_budget" in game and game.render_budget:
		report["profile"] = game.render_budget.profile
		report["render_scale"] = root.scaling_3d_scale
	var directory := OS.get_environment("Z3WAX_BENCHMARK_DIR")
	DirAccess.make_dir_recursive_absolute(directory)
	var file := FileAccess.open(directory.path_join("benchmark.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "  ")); file.close()
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(directory.path_join("gameplay.png"))
	print("Z3WAX_REALTIME_BENCHMARK ", JSON.stringify(report))
	assert(distance > .5 and game.actors.size() == 8)
	quit()
