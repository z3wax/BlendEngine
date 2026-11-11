extends SceneTree
func _initialize() -> void:call_deferred("test")
func test() -> void:
	var game=load("res://main.tscn").instantiate();root.add_child(game);game._start_training();game.smoke=true
	var actor=game.actors[1]
	assert(actor.visual!=null and actor.animation!=null)
	var bones=actor.visual.find_children("*","Skeleton3D",true,false);assert(bones.size()>0)
	var skeleton=bones[0];assert(skeleton.get_bone_count()>10)
	var poses=[]
	for i in range(skeleton.get_bone_count()):poses.append(skeleton.get_bone_pose_rotation(i))
	for i in range(60):await physics_frame
	var changes=0
	for i in range(skeleton.get_bone_count()):
		if not poses[i].is_equal_approx(skeleton.get_bone_pose_rotation(i)):changes+=1
	assert(changes>3)
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("/tmp/z3wax-character-proof.png")
	print("Z3WAX_VISUAL_PASS bones=",skeleton.get_bone_count()," changed=",changes," animation=",actor.animation.current_animation)
	quit()
