extends Node3D
## Artist-authored mesh, attributed mocap legs and authored armed upper-body clips.
var model: Node3D
var skeleton: Skeleton3D
var animation: AnimationPlayer
var weapon: Node3D
var socket: BoneAttachment3D
var current_motion="idle"

func _ready() -> void:
	model=load("res://assets/realistic/operator_motion.glb").instantiate();add_child(model);model.position.x=-.18
	skeleton=model.find_children("*","Skeleton3D",true,false)[0]
	animation=model.find_children("*","AnimationPlayer",true,false)[0]
	for clip in ["idle","walk","run","aim","jump"]:
		animation.get_animation(clip).loop_mode=Animation.LOOP_LINEAR
	animation.play("idle");animation.seek(.35,true);skeleton.force_update_all_bone_transforms()
	var hand=skeleton.find_bone("mixamorig_RightHand_011")
	var knuckle=skeleton.find_bone("mixamorig_RightHandMiddle1_016")
	assert(hand>=0 and knuckle>=0,"Required weapon grip bones are missing")
	var hand_pose=skeleton.get_bone_global_pose(hand)
	var grip=hand_pose.origin.lerp(skeleton.get_bone_global_pose(knuckle).origin,.55)
	var basis=Basis(Vector3.UP,PI)*.55
	# Coordinates refer to the actual rifle model's pistol grip, not its bounding-box center.
	var rifle_pose=Transform3D(basis,grip-basis*Vector3(0,-.16,.25))
	socket=BoneAttachment3D.new();socket.bone_name=skeleton.get_bone_name(hand);skeleton.add_child(socket)
	weapon=load("res://assets/realistic/rifle_real.glb").instantiate();socket.add_child(weapon)
	weapon.transform=hand_pose.affine_inverse()*rifle_pose
	if DisplayServer.get_name()!="headless":
		var visibility=VisibleOnScreenNotifier3D.new();visibility.aabb=AABB(Vector3(-.9,-.2,-.9),Vector3(1.8,2.6,1.8));add_child(visibility)
		visibility.screen_entered.connect(func():animation.active=true)
		visibility.screen_exited.connect(func():animation.active=false)

func set_motion(motion: String, speed: float=1.0) -> void:
	if not animation or not animation.has_animation(motion):return
	animation.speed_scale=clampf(speed,.6,1.8)
	if current_motion!=motion:
		current_motion=motion;animation.play(motion,.16)
