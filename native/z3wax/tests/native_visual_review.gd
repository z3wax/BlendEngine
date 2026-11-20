extends SceneTree
var game: Node3D
var output: String
func _initialize() -> void:call_deferred("review")
func review() -> void:
	output=OS.get_environment("Z3WAX_PREVIEW_DIR")
	if output.is_empty():output=OS.get_user_data_dir()+"/preview"
	DirAccess.make_dir_recursive_absolute(output)
	game=load("res://main.tscn").instantiate();root.add_child(game)
	await create_timer(2).timeout
	assert(game.lobby_stage!=null and game.lobby.visible)
	assert(game.lobby_stage.camera.current and not game.world.visible)
	await capture("06-native-lobby.png")
	game.lobby_stage.training_requested.emit()
	await create_timer(.5).timeout
	assert(game.mode=="PLAYING" and not game.lobby_stage.visible and game.camera.current)
	assert(game.world.visible and game.actors.size()==8)
	Input.action_press("forward")
	await create_timer(1.0).timeout
	Input.action_release("forward")
	await capture("07-native-training.png")
	game._disconnect("Visual integration check complete.")
	await create_timer(.3).timeout
	assert(game.lobby.visible and game.lobby_stage.camera.current and not game.world.visible)
	print("Z3WAX_NATIVE_VISUAL_PASS lobby,training,operator,return_to_lobby")
	game.queue_free();game=null
	await process_frame
	await process_frame
	quit()
func capture(filename: String) -> void:
	await RenderingServer.frame_post_draw
	assert(root.get_texture().get_image().save_png(output.path_join(filename))==OK)
