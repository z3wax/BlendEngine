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
var reload_audio: AudioStreamPlayer3D
var was_reloading=false
var magazine_inserted=false

func _ready() -> void:
	collision_layer=2;collision_mask=1|2
	var shape=CollisionShape3D.new();var capsule=CapsuleShape3D.new();capsule.radius=.35;capsule.height=1.8;shape.shape=capsule;shape.position.y=.9;add_child(shape)
	floor_snap_length=.4
	if DisplayServer.get_name()!="headless":
		visual=load("res://operator_visual.gd").new();add_child(visual)
		animation=visual.animation
		reload_audio=AudioStreamPlayer3D.new();reload_audio.position.y=1.2;reload_audio.max_distance=25;reload_audio.unit_size=3;reload_audio.volume_db=-10;add_child(reload_audio)

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
	velocity.x=move_toward(velocity.x,direction.x*4.8,dt*28)
	velocity.z=move_toward(velocity.z,direction.z*4.8,dt*28)
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
	if health<=0:animation.pause();return
	var speed=Vector2(velocity.x,velocity.z).length()
	var desired="jump" if not is_on_floor() and absf(velocity.y)>1 else ("run" if speed>2.0 else ("walk" if speed>.2 else "idle"))
	if reload_left>0:desired="run_reload" if speed>2 else ("walk_reload" if speed>.2 else "reload")
	elif shot_left>0 and speed<.2:desired="aim"
	var rate=speed/2.8652 if desired=="run" else (speed/1.1733 if desired=="walk" else 1.0)
	visual.set_motion(desired,rate);last_animation=desired
	if reload_left>0:
		animation.seek((1.0-reload_left/1.8)*animation.get_animation(desired).length,true)
		if not was_reloading:
			reload_audio.stream=load("res://assets/realistic/audio/rifle_magout.wav");reload_audio.play();magazine_inserted=false
		if reload_left<.55 and not magazine_inserted:
			reload_audio.stream=load("res://assets/realistic/audio/rifle_magin.wav");reload_audio.play();magazine_inserted=true
	was_reloading=reload_left>0
