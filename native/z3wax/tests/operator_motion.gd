extends SceneTree
func _initialize() -> void:call_deferred("verify")
func verify() -> void:
	var visual=load("res://operator_visual.gd").new();root.add_child(visual)
	await process_frame
	assert(visual.socket.bone_name=="mixamorig_RightHand_011")
	assert(visual.weapon.get_parent()==visual.socket)
	var skeleton: Skeleton3D=visual.skeleton
	var head=skeleton.find_bone("mixamorig_Head_06")
	assert(head>=0)
	var changed=0
	var previous: Dictionary={}
	for clip in ["idle","walk","run","jump","land","reload","aim","walk_reload","run_reload"]:
		assert(visual.animation.has_animation(clip))
		visual.animation.play(clip)
		var animation: Animation=visual.animation.get_animation(clip)
		for sample in range(8):
			visual.animation.seek(animation.length*sample/8.0,true);skeleton.force_update_all_bone_transforms()
			for bone in range(skeleton.get_bone_count()):
				var pose=skeleton.get_bone_global_pose(bone)
				assert(pose.origin.is_finite() and pose.basis.is_finite(),"Non-finite animation pose")
				assert(pose.origin.length()<3.5,"Skeleton scale or retargeting exploded")
				if previous.has(bone) and not pose.is_equal_approx(previous[bone]):changed+=1
				previous[bone]=pose
		assert(skeleton.get_bone_global_pose(head).origin.y>.8,"Head is below torso")
	assert(changed>80,"Animation tracks are not driving the rig")
	print("Z3WAX_OPERATOR_MOTION_PASS clips=9 bones=",skeleton.get_bone_count()," changed_poses=",changed," weapon_bone_attachment=true")
	quit()
