extends SceneTree
func _initialize() -> void:call_deferred("preview")
func preview() -> void:
	var scene=Node3D.new();root.add_child(scene)
	var op=load("res://operator_visual.gd").new();scene.add_child(op);op.rotation.y=.45
	var light=DirectionalLight3D.new();light.rotation_degrees=Vector3(-35,-40,0);light.light_energy=1.1;scene.add_child(light)
	var env=WorldEnvironment.new();env.environment=Environment.new();env.environment.background_mode=Environment.BG_COLOR;env.environment.background_color=Color(.12,.14,.16);env.environment.ambient_light_source=Environment.AMBIENT_SOURCE_COLOR;env.environment.ambient_light_energy=.6;scene.add_child(env)
	var camera=Camera3D.new();scene.add_child(camera);camera.position=Vector3(0,1.2,3.7);camera.fov=36;camera.look_at(Vector3(0,1,0))
	await create_timer(1).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(OS.get_environment("Z3WAX_OPERATOR_CAPTURE") if not OS.get_environment("Z3WAX_OPERATOR_CAPTURE").is_empty() else "user://operator-preview.png")
	print("OPERATOR_VISUAL_READY bones=",op.skeleton.get_bone_count()," clips=",op.animation.get_animation_list());quit()
