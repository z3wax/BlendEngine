extends SceneTree
var game: Node3D
var output: String
func _initialize() -> void:call_deferred("record")
func record() -> void:
	output=OS.get_environment("Z3WAX_PREVIEW_DIR")
	if output.is_empty():output=OS.get_user_data_dir()+"/preview"
	DirAccess.make_dir_recursive_absolute(output)
	game=load("res://main.tscn").instantiate();root.add_child(game)
	await create_timer(2).timeout
	await capture("06-native-lobby.png")
	game.lobby_stage.training_requested.emit()
	await create_timer(.5).timeout
	Input.action_press("forward")
	await create_timer(1.2).timeout
	await capture("07-native-training.png")
	game.jump_pending=true
	await create_timer(.8).timeout
	Input.action_release("forward")
	game.fire_pending=true
	await create_timer(.3).timeout
	game.reload_pending=true
	await create_timer(1.9).timeout
	game.map_panel.show()
	await create_timer(.3).timeout
	await capture("08-disland-relief.png")
	await create_timer(.8).timeout
	game._disconnect("Development preview — full Disland content is still in progress.")
	await create_timer(.5).timeout
	print("Z3WAX_GAMEPLAY_RECORD_PASS native_lobby,walk,jump,fire,reload,map,return")
	game.queue_free();game=null
	await process_frame
	await process_frame
	quit()
func capture(filename: String) -> void:
	await RenderingServer.frame_post_draw
	assert(root.get_texture().get_image().save_png(output.path_join(filename))==OK)
