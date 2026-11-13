extends SceneTree
func _initialize() -> void:
	call_deferred("export_stage")
func export_stage() -> void:
	var stage = load("res://art_review.tscn").instantiate()
	root.add_child(stage)
	await process_frame
	await process_frame
	stage.soldier.animation.pause()
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	var error := document.append_from_scene(stage, state)
	if error == OK:
		error = document.write_to_filesystem(state, OS.get_environment("Z3WAX_CYCLES_GLTF"))
	print("Z3WAX_CYCLES_STAGE_EXPORT ", error_string(error))
	quit(0 if error == OK else 1)
