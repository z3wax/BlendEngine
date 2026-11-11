extends CharacterBody3D
var health=100.0
var ammo=30
var reserve=120
var reload_left=0.0
var shot_left=0.0
var kills=0
var display_name="Ranger"
var visual: Node3D
var animation: AnimationPlayer
var input_move=Vector2.ZERO
var aim_yaw=0.0
var aim_pitch=0.0
var wants_fire=false
var wants_jump=false
var wants_reload=false
var bot=false
var last_input=0
var target_position=Vector3.ZERO
var last_animation=""
var hit_flash=0.0

func _ready() -> void:
	collision_layer=2;collision_mask=1|2
	var shape=CollisionShape3D.new();var capsule=CapsuleShape3D.new();capsule.radius=.35;capsule.height=1.8;shape.shape=capsule;shape.position.y=.9;add_child(shape)
	floor_snap_length=.4
	if DisplayServer.get_name()!="headless":
		visual=load("res://assets/character.glb").instantiate();add_child(visual);visual.scale=Vector3.ONE*.48
		for n in visual.find_children("*","AnimationPlayer",true,false): animation=n
		if animation:
			for a in animation.get_animation_list():
				if "idle" in a.to_lower() or "run" in a.to_lower(): animation.get_animation(a).loop_mode=Animation.LOOP_LINEAR
		var gun=load("res://assets/rifle.glb").instantiate()
		# Attach the artist-made weapon to the right hand when available.
		var attached=false
		for skeleton in visual.find_children("*","Skeleton3D",true,false):
			for i in range(skeleton.get_bone_count()):
				var bone=skeleton.get_bone_name(i).to_lower()
				if "hand" in bone and ("right" in bone or ".r" in bone):
					var socket=BoneAttachment3D.new();socket.bone_name=skeleton.get_bone_name(i);skeleton.add_child(socket);socket.add_child(gun);gun.scale=Vector3.ONE*.9;attached=true;break
			if attached: break
		if not attached: add_child(gun);gun.position=Vector3(.32,1.1,-.3);gun.scale=Vector3.ONE*.45

func simulate(dt: float) -> void:
	shot_left=maxf(0,shot_left-dt)
	if reload_left>0:
		reload_left=maxf(0,reload_left-dt)
		if reload_left==0:
			var amount=mini(30-ammo,reserve);ammo+=amount;reserve-=amount
	if wants_reload and reload_left==0 and ammo<30 and reserve>0: reload_left=1.8
	wants_reload=false
	if health<=0: velocity=Vector3.ZERO;return
	var direction=Vector3(input_move.x,0,input_move.y).rotated(Vector3.UP,aim_yaw)
	velocity.x=move_toward(velocity.x,direction.x*6.5,dt*28)
	velocity.z=move_toward(velocity.z,direction.z*6.5,dt*28)
	if not is_on_floor(): velocity.y-=22*dt
	elif wants_jump: velocity.y=7.2
	wants_jump=false
	move_and_slide()
	position.x=clampf(position.x,-7900,7900);position.z=clampf(position.z,-7900,7900)
	if position.y<-15: health=0
	animate()

func animate() -> void:
	if visual:
		visual.rotation.y=lerp_angle(visual.rotation.y,aim_yaw+PI,.18)
		visual.visible=health>0
	if not animation: return
	var desired="jump" if not is_on_floor() and absf(velocity.y)>1 else ("run" if Vector2(velocity.x,velocity.z).length()>.2 else "idle")
	if desired==last_animation:return
	for a in animation.get_animation_list():
		if desired in a.to_lower(): animation.play(a,.18);last_animation=desired;break
