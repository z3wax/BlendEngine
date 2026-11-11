extends Node3D
const Actor=preload("res://actor.gd")
const World=preload("res://world.gd")
const Sentinel=preload("res://sentinel.gd")
const PORT=28416
const MAX_PLAYERS=16
var world: Node3D
var actors: Dictionary={}
var sentinel=Sentinel.new()
var local_id=1
var mode="LOBBY"
var server_mode=false
var networked=false
var match_time=0.0
var zone_radius=220.0
var sequence=0
var net_tick=0.0
var sector_tick=0.0
var camera: Camera3D
var yaw=0.0
var pitch=-.16
var lobby: Control
var hud: Control
var status: Label
var notice: Label
var result: Label
var map_panel: Control
var map_view: Control
var address: LineEdit
var token_field: LineEdit
var touch_move=Vector2.ZERO
var touches: Dictionary={}
var stick_index=-1
var look_index=-1
var stick_origin=Vector2.ZERO
var touch_fire=false
var jump_pending=false
var reload_pending=false
var server_token=""
var banned_ips: Array=[]
var pending_since: Dictionary={}
var smoke=false
var smoke_steps=0
var smoke_peak=0.0
var tracer: MeshInstance3D
var tracer_time=0.0
var ui_timer=0.0
var snapshot_count=0

func _ready() -> void:
	get_tree().quit_on_go_back=false
	var args=OS.get_cmdline_user_args()
	server_mode="--server" in args
	smoke="--smoke-test" in args
	server_token=OS.get_environment("Z3WAX_SERVER_TOKEN")
	if FileAccess.file_exists("user://bans.json"):
		var data=JSON.parse_string(FileAccess.get_file_as_string("user://bans.json"))
		if data is Array: banned_ips=data
	_setup_input()
	world=World.new();add_child(world)
	_setup_scene()
	if not server_mode:_setup_ui()
	multiplayer.peer_connected.connect(_peer_connected)
	multiplayer.peer_disconnected.connect(_peer_disconnected)
	multiplayer.connected_to_server.connect(_connected)
	multiplayer.connection_failed.connect(func():_disconnect("Serverga ulanib bo‘lmadi. Manzil va UDP portni tekshiring."))
	multiplayer.server_disconnected.connect(func():_disconnect("Server bilan aloqa uzildi."))
	if server_mode:
		var peer=ENetMultiplayerPeer.new();var err=peer.create_server(PORT,MAX_PLAYERS)
		if err!=OK:push_error("Server bind failed: "+str(err));get_tree().quit(2);return
		multiplayer.multiplayer_peer=peer;networked=true;mode="WAITING"
		print("Z3WAX_SERVER_READY udp=",PORT," capacity=",MAX_PLAYERS)
	elif "--network-test" in args:
		address.text="127.0.0.1";_join()
	elif smoke: _start_training()

func _setup_input() -> void:
	for action in {"left":KEY_A,"right":KEY_D,"forward":KEY_W,"back":KEY_S,"jump":KEY_SPACE,"reload":KEY_R,"map":KEY_M,"pause":KEY_ESCAPE}:
		if not InputMap.has_action(action):InputMap.add_action(action)
		var e=InputEventKey.new();e.physical_keycode={"left":KEY_A,"right":KEY_D,"forward":KEY_W,"back":KEY_S,"jump":KEY_SPACE,"reload":KEY_R,"map":KEY_M,"pause":KEY_ESCAPE}[action];InputMap.action_add_event(action,e)

func _setup_scene() -> void:
	var environment=WorldEnvironment.new();var e=Environment.new();environment.environment=e
	e.background_mode=Environment.BG_SKY
	var sky=Sky.new();var sky_mat=ProceduralSkyMaterial.new();sky_mat.sky_top_color=Color(.09,.19,.27);sky_mat.sky_horizon_color=Color(.79,.60,.40);sky_mat.ground_horizon_color=Color(.68,.51,.35);sky.sky_material=sky_mat;e.sky=sky
	e.ambient_light_source=Environment.AMBIENT_SOURCE_COLOR;e.ambient_light_color=Color(.50,.65,.77);e.ambient_light_energy=.4
	e.tonemap_mode=Environment.TONE_MAPPER_FILMIC
	e.fog_enabled=true;e.fog_light_color=Color(.30,.36,.39);e.fog_density=.0004
	add_child(environment)
	var sun=DirectionalLight3D.new();sun.rotation_degrees=Vector3(-28,-38,0);sun.light_color=Color(1,.77,.52);sun.light_energy=1.1;sun.shadow_enabled=true;sun.directional_shadow_max_distance=130;add_child(sun)
	camera=Camera3D.new();camera.far=2300;camera.fov=65;add_child(camera);camera.position=Vector3(24,14,32);camera.look_at(Vector3(0,15,0))

func _style(bg: Color, edge: Color=Color(.22,.36,.38)) -> StyleBoxFlat:
	var s=StyleBoxFlat.new();s.bg_color=bg;s.border_color=edge;s.set_border_width_all(1);s.set_corner_radius_all(3);s.content_margin_left=18;s.content_margin_right=18;s.content_margin_top=10;s.content_margin_bottom=10;return s
func _label(text: String, size_px: int, color=Color(.88,.91,.87)) -> Label:
	var l=Label.new();l.text=text;l.add_theme_font_size_override("font_size",size_px);l.add_theme_color_override("font_color",color);return l
func _button(text: String, action: Callable) -> Button:
	var b=Button.new();b.text=text;b.custom_minimum_size=Vector2(170,48);b.add_theme_stylebox_override("normal",_style(Color(.06,.14,.16)));b.add_theme_stylebox_override("hover",_style(Color(.12,.31,.32),Color(.3,.85,.76)));b.add_theme_stylebox_override("pressed",_style(Color(.22,.42,.39)));b.pressed.connect(action);return b
func _setup_ui() -> void:
	var layer=CanvasLayer.new();add_child(layer)
	var root=Control.new();root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT);layer.add_child(root);root.mouse_filter=Control.MOUSE_FILTER_IGNORE
	lobby=Control.new();lobby.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT);root.add_child(lobby)
	var margin=MarginContainer.new();margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side in ["left","right","top","bottom"]:margin.add_theme_constant_override("margin_"+side,32)
	lobby.add_child(margin)
	var layout=VBoxContainer.new();layout.add_theme_constant_override("separation",14);margin.add_child(layout)
	var top=HBoxContainer.new();layout.add_child(top)
	var brand=_label("Z3WAX",48);brand.size_flags_horizontal=Control.SIZE_EXPAND_FILL;top.add_child(brand)
	top.add_child(_label("DISLAND  /  FIELD TEST 01",18,Color(.38,.83,.76)))
	var tabs=HBoxContainer.new();layout.add_child(tabs)
	for name in ["HOME","MAP","ARMORY","CREDITS"]:
		tabs.add_child(_button(name,func():_tab(name)))
	var space=Control.new();space.size_flags_vertical=Control.SIZE_EXPAND_FILL;layout.add_child(space)
	var bottom=HBoxContainer.new();bottom.add_theme_constant_override("separation",28);layout.add_child(bottom)
	var info=VBoxContainer.new();info.size_flags_horizontal=Control.SIZE_EXPAND_FILL;bottom.add_child(info)
	info.add_child(_label("AFTER THE SIGNAL",30,Color(.96,.77,.42)))
	info.add_child(_label("One island. A closing perimeter. Your way out.",19))
	info.add_child(_label("16 × 16 km  •  Relay Nine combat sector\nWASD move · mouse look · click fire · R reload · M map",16))
	notice=_label("Training is local. Online requires a reachable server.",16);notice.autowrap_mode=TextServer.AUTOWRAP_WORD_SMART;notice.custom_minimum_size.x=550;info.add_child(notice)
	var card=PanelContainer.new();card.add_theme_stylebox_override("panel",_style(Color(.025,.055,.065,.96)));bottom.add_child(card)
	var menu=VBoxContainer.new();menu.add_theme_constant_override("separation",8);card.add_child(menu)
	menu.add_child(_label("DEPLOY / DISLAND",24))
	menu.add_child(_button("START TRAINING",_start_training))
	address=LineEdit.new();address.placeholder_text="Server address";address.text="127.0.0.1";address.custom_minimum_size=Vector2(280,40);menu.add_child(address)
	token_field=LineEdit.new();token_field.placeholder_text="Server access token (if required)";token_field.secret=true;menu.add_child(token_field)
	menu.add_child(_button("CONNECT TO SERVER",_join))
	menu.add_child(_label("1 player + 7 bots / up to 16 online",14))
	hud=Control.new();hud.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT);hud.visible=false;root.add_child(hud);hud.mouse_filter=Control.MOUSE_FILTER_IGNORE
	status=_label("",21);status.position=Vector2(28,24);hud.add_child(status)
	result=_label("",32);result.position=Vector2(360,160);hud.add_child(result)
	var cross=_label("+",27);cross.set_anchors_and_offsets_preset(Control.PRESET_CENTER);cross.position-=Vector2(9,18);hud.add_child(cross)
	var exit_button=_button("LOBBY",func():_disconnect("Match ended."));exit_button.position=Vector2(1060,20);hud.add_child(exit_button)
	var map_button=_button("MAP",func():map_panel.visible=not map_panel.visible);map_button.position=Vector2(1060,80);hud.add_child(map_button)
	var fire=_button("FIRE",func():pass);fire.position=Vector2(1080,530);fire.custom_minimum_size=Vector2(160,100);fire.button_down.connect(func():touch_fire=true);fire.button_up.connect(func():touch_fire=false);hud.add_child(fire)
	var jump=_button("JUMP",func():jump_pending=true);jump.position=Vector2(880,600);hud.add_child(jump)
	var reload_button=_button("RELOAD",func():reload_pending=true);reload_button.position=Vector2(880,540);hud.add_child(reload_button)
	var stick_hint=_label("MOVE\n◀  ●  ▶",24,Color(.5,.8,.75,.7));stick_hint.position=Vector2(80,565);stick_hint.mouse_filter=Control.MOUSE_FILTER_IGNORE;hud.add_child(stick_hint)
	map_panel=PanelContainer.new();map_panel.position=Vector2(270,90);map_panel.size=Vector2(740,540);map_panel.add_theme_stylebox_override("panel",_style(Color(.02,.06,.08)));root.add_child(map_panel)
	var map_box=VBoxContainer.new();map_panel.add_child(map_box)
	map_box.add_child(_label("DISLAND  /  16 × 16 KM",24))
	map_view=load("res://map.gd").new();map_view.custom_minimum_size=Vector2(700,430);map_box.add_child(map_view)
	map_box.add_child(_button("CLOSE",func():map_panel.hide()));map_panel.hide()

func _tab(tab: String) -> void:
	if tab=="MAP":map_panel.show()
	elif tab=="ARMORY":notice.text="A1 / Kenney Blaster · 30 rounds · 120 reserve\nServer validates cadence, ammunition and raycast hits."
	elif tab=="CREDITS":notice.text="Character, skeletal animations and blasters: Kenney / CC0.\nScene: Blender → glTF. Runtime: Godot 4.6.3 / MIT."
	else:notice.text="Training is local. Online requires a reachable server."

func _spawn(id: int, point: Vector3, bot: bool=false) -> void:
	if actors.has(id):return
	var actor=Actor.new();actor.name="Ranger_"+str(id);actor.bot=bot;actor.display_name=("Scout " if bot else "Ranger ")+str(abs(id));add_child(actor);actor.position=point;actor.target_position=point;actors[id]=actor

func _start_training() -> void:
	_clear_actors();multiplayer.multiplayer_peer=OfflineMultiplayerPeer.new();networked=false;local_id=1;match_time=0;zone_radius=220;mode="PLAYING";_spawn(1,Vector3(20,8.1,25))
	for i in range(7):
		var angle=i*TAU/7;_spawn(-i-1,Vector3(cos(angle)*90,8.1,sin(angle)*90),true)
	lobby.hide();hud.show();result.text="";Input.mouse_mode=Input.MOUSE_MODE_CAPTURED if not OS.has_feature("mobile") else Input.MOUSE_MODE_VISIBLE

func _join() -> void:
	var host=address.text.strip_edges()
	if host.is_empty():notice.text="Server manzilini kiriting.";return
	_clear_actors();var peer=ENetMultiplayerPeer.new();var err=peer.create_client(host,PORT)
	if err!=OK:notice.text="Connection error: "+str(err);return
	multiplayer.multiplayer_peer=peer;networked=true;mode="CONNECTING";notice.text="Connecting…";sector_tick=0
func _connected() -> void:
	local_id=multiplayer.get_unique_id();register.rpc_id(1,token_field.text)
func _peer_connected(id: int) -> void:
	if server_mode:pending_since[id]=Time.get_ticks_msec()
func _peer_disconnected(id: int) -> void:
	pending_since.erase(id);sentinel.forget(id)
	if actors.has(id):actors[id].queue_free();actors.erase(id)
	if server_mode and actors.is_empty():mode="WAITING";match_time=0;zone_radius=220

@rpc("any_peer","call_remote","reliable")
func register(token: String) -> void:
	if not server_mode:return
	var id=multiplayer.get_remote_sender_id()
	if actors.has(id):return
	var remote=multiplayer.multiplayer_peer.get_peer(id)
	if remote.get_remote_address() in banned_ips or (server_token!="" and token!=server_token) or mode=="FINISHED":
		multiplayer.multiplayer_peer.disconnect_peer(id);return
	pending_since.erase(id)
	var angle=actors.size()*2.4;_spawn(id,Vector3(cos(angle)*25,8.1,sin(angle)*25))
	actors[id].last_input=Time.get_ticks_msec()
	mode="PLAYING"

@rpc("any_peer","call_remote","unreliable_ordered",1)
func command(seq: int, move: Vector2, turn: float, tilt: float, fire: bool, jump: bool, reload_weapon: bool) -> void:
	if not server_mode:return
	var id=multiplayer.get_remote_sender_id()
	if not actors.has(id):return
	if not sentinel.validate(id,seq,move,turn,tilt,Time.get_ticks_msec()):
		if sentinel.should_kick(id):multiplayer.multiplayer_peer.disconnect_peer(id)
		return
	_set_input(actors[id],move,turn,tilt,fire,jump,reload_weapon)
func _set_input(a: CharacterBody3D, move: Vector2, turn: float, tilt: float, fire: bool, jump: bool, reload_weapon: bool) -> void:
	a.input_move=move.limit_length();a.aim_yaw=turn;a.aim_pitch=tilt;a.wants_fire=fire;a.wants_jump=a.wants_jump or jump;a.wants_reload=a.wants_reload or reload_weapon;a.last_input=Time.get_ticks_msec()

@rpc("authority","call_remote","unreliable_ordered",2)
func snapshot(data: Array, elapsed: float, radius: float, phase: String) -> void:
	if server_mode:return
	snapshot_count+=1;match_time=elapsed;zone_radius=radius;mode=phase
	var ids=[]
	for entry in data:
		var id=int(entry[0]);ids.append(id)
		if not actors.has(id):_spawn(id,entry[1])
		var a=actors[id];a.target_position=entry[1];a.velocity=entry[2];a.health=entry[3];a.ammo=entry[4];a.reserve=entry[5];a.aim_yaw=entry[6];a.reload_left=entry[7];a.kills=entry[8]
	for id in actors.keys():
		if id not in ids:actors[id].queue_free();actors.erase(id)
	if actors.has(local_id):lobby.hide();hud.show()

func _physics_process(dt: float) -> void:
	if mode=="CONNECTING":
		sector_tick+=dt
		if sector_tick>10:_disconnect("Connection timed out.")
		return
	if mode!="PLAYING" and mode!="FINISHED":return
	if actors.has(local_id) and not server_mode:
		var move=Input.get_vector("left","right","forward","back")+touch_move
		var jump=jump_pending or Input.is_action_just_pressed("jump");var reload_weapon=reload_pending or Input.is_action_just_pressed("reload")
		var fire=touch_fire or (Input.mouse_mode==Input.MOUSE_MODE_CAPTURED and Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT))
		if smoke:move=Vector2(0,-1) if smoke_steps<100 else Vector2.ZERO;fire=false;jump=smoke_steps==20
		if networked:
			net_tick+=dt
			jump_pending=jump;reload_pending=reload_weapon
			if net_tick>=1.0/30:
				net_tick=0;sequence+=1;command.rpc_id(1,sequence,move.limit_length(),yaw,pitch,fire,jump,reload_weapon);jump_pending=false;reload_pending=false
		else:_set_input(actors[local_id],move,yaw,pitch,fire,jump,reload_weapon);jump_pending=false;reload_pending=false
	if not networked or server_mode:
		if mode=="PLAYING":
			match_time+=dt;zone_radius=lerpf(220,12,clampf((match_time-30)/210,0,1))
			for id in actors:
				var a=actors[id]
				if a.bot:_bot(a)
				elif server_mode and Time.get_ticks_msec()-a.last_input>350:a.input_move=Vector2.ZERO;a.wants_fire=false
				a.simulate(dt)
				if a.health>0 and Vector2(a.position.x,a.position.z).length()>zone_radius:a.health=maxf(0,a.health-dt*7)
				if a.wants_fire:_fire(id)
			var alive=actors.values().filter(func(a):return a.health>0)
			if actors.size()>1 and alive.size()<=1:mode="FINISHED"
		if server_mode:
			net_tick+=dt
			if net_tick>=.1:
				net_tick=0;var data=[]
				for id in actors:
					var a=actors[id];data.append([id,a.position,a.velocity,a.health,a.ammo,a.reserve,a.aim_yaw,a.reload_left,a.kills])
				snapshot.rpc(data,match_time,zone_radius,mode)
			for id in pending_since.keys():
				if Time.get_ticks_msec()-pending_since[id]>10000:multiplayer.multiplayer_peer.disconnect_peer(id);pending_since.erase(id)
	else:
		for a in actors.values():a.position=a.position.lerp(a.target_position,1-exp(-dt*18));a.animate()
	sector_tick+=dt
	if sector_tick>1:
		sector_tick=0
		if server_mode:world.update_regions(actors.values().map(func(a):return a.position))
		elif actors.has(local_id):world.update_sectors(actors[local_id].position)
	if not server_mode:_update_camera(dt);_update_hud()
	if smoke:_smoke()
	if "--network-test" in OS.get_cmdline_user_args() and snapshot_count>=20:
		print("Z3WAX_NETWORK_PASS snapshots=",snapshot_count," actors=",actors.size());get_tree().quit()

func _bot(a: CharacterBody3D) -> void:
	if a.health<=0:return
	var target=null;var best=INF
	for other in actors.values():
		if other==a or other.health<=0:continue
		var distance=a.position.distance_squared_to(other.position)
		if distance<best:best=distance;target=other
	if target==null:return
	var direction=target.position-a.position
	a.aim_yaw=atan2(-direction.x,-direction.z)
	a.aim_pitch=atan2(direction.y,maxf(.1,Vector2(direction.x,direction.z).length()))
	a.input_move=Vector2(sin(match_time*.7+a.get_instance_id())*.4,-.6 if best>900 else .15)
	a.wants_fire=not smoke and match_time>5 and best<16000 and sin(match_time*2+a.get_instance_id())>.94
	a.wants_reload=a.ammo==0
	if a.is_on_wall():a.wants_jump=true

func _fire(id: int) -> void:
	var a=actors[id]
	if a.health<=0 or a.ammo<=0 or a.shot_left>0 or a.reload_left>0:return
	a.ammo-=1;a.shot_left=.14
	var origin=a.position+Vector3(0,1.45,0)
	var direction=Vector3(0,0,-1).rotated(Vector3.RIGHT,a.aim_pitch).rotated(Vector3.UP,a.aim_yaw)
	var query=PhysicsRayQueryParameters3D.create(origin,origin+direction*350,3,[a.get_rid()])
	var hit=get_world_3d().direct_space_state.intersect_ray(query)
	var end=origin+direction*350
	if hit:
		end=hit.position
		if hit.collider is CharacterBody3D and hit.collider.get_script()==Actor:
			var victim=hit.collider;var before=victim.health;victim.health=maxf(0,victim.health-25)
			if before>0 and victim.health==0:a.kills+=1
	if server_mode:shot_visual.rpc(origin,end)
	else:shot_visual(origin,end)

@rpc("authority","call_remote","unreliable")
func shot_visual(from: Vector3, to: Vector3) -> void:
	if DisplayServer.get_name()=="headless":return
	if is_instance_valid(tracer):tracer.queue_free()
	tracer=MeshInstance3D.new();var line=ImmediateMesh.new();line.surface_begin(Mesh.PRIMITIVE_LINES);line.surface_add_vertex(from);line.surface_add_vertex(to);line.surface_end();tracer.mesh=line
	var mat=StandardMaterial3D.new();mat.shading_mode=BaseMaterial3D.SHADING_MODE_UNSHADED;mat.albedo_color=Color(1,.76,.25);tracer.material_override=mat;add_child(tracer);tracer_time=.05

func _update_camera(dt: float) -> void:
	if not actors.has(local_id):return
	var a=actors[local_id];var focus=a.position+Vector3(0,1.5,0)
	var offset=Vector3(.65,1.2,4.5).rotated(Vector3.RIGHT,pitch).rotated(Vector3.UP,yaw)
	var desired=focus+offset
	var hit=get_world_3d().direct_space_state.intersect_ray(PhysicsRayQueryParameters3D.create(focus,desired,1,[a.get_rid()]))
	if hit:desired=hit.position+(focus-hit.position).normalized()*.2
	camera.position=camera.position.lerp(desired,1-exp(-dt*16));camera.look_at(focus+Vector3(0,0,-18).rotated(Vector3.RIGHT,pitch).rotated(Vector3.UP,yaw))
	if is_instance_valid(tracer):tracer_time-=dt;if_tracer_expired()
func if_tracer_expired() -> void:
	if tracer_time<=0:tracer.queue_free()
func _update_hud() -> void:
	if not actors.has(local_id):return
	var a=actors[local_id];var alive=actors.values().filter(func(p):return p.health>0).size()
	status.text="DISLAND   /   %02d ALIVE   /   %d KILLS\nHP %03d    •    %02d / %03d%s\nPERIMETER %dm   •   %02d:%02d"%[alive,a.kills,ceili(a.health),a.ammo,a.reserve,"  RELOADING" if a.reload_left>0 else "",int(zone_radius),int(match_time)/60,int(match_time)%60]
	if a.health<=0:result.text="ELIMINATED\nReturn to lobby to deploy again."
	elif mode=="FINISHED":result.text="PERIMETER SECURED\nYou are the last ranger standing."
	if map_panel.visible:map_view.player=Vector2(a.position.x,a.position.z);map_view.zone_radius=zone_radius;map_view.queue_redraw()

func _unhandled_input(event: InputEvent) -> void:
	if server_mode:return
	if event.is_action_pressed("map"):map_panel.visible=not map_panel.visible
	if event.is_action_pressed("pause"):
		Input.mouse_mode=Input.MOUSE_MODE_VISIBLE if Input.mouse_mode==Input.MOUSE_MODE_CAPTURED else Input.MOUSE_MODE_CAPTURED
	if event is InputEventMouseMotion and Input.mouse_mode==Input.MOUSE_MODE_CAPTURED:
		yaw=wrapf(yaw-event.relative.x*.003,-PI,PI);pitch=clampf(pitch-event.relative.y*.003,-.8,.8)
func _notification(what: int) -> void:
	if what==NOTIFICATION_APPLICATION_FOCUS_OUT or what==NOTIFICATION_WM_GO_BACK_REQUEST:
		touch_move=Vector2.ZERO;touch_fire=false;stick_index=-1;look_index=-1;jump_pending=false;reload_pending=false;Input.mouse_mode=Input.MOUSE_MODE_VISIBLE
func _clear_actors() -> void:
	for a in actors.values():a.queue_free()
	actors.clear()
func _disconnect(message: String) -> void:
	multiplayer.multiplayer_peer=OfflineMultiplayerPeer.new();networked=false;mode="LOBBY";_clear_actors();Input.mouse_mode=Input.MOUSE_MODE_VISIBLE
	if lobby:lobby.show();hud.hide();notice.text=message;map_panel.hide()
func _smoke() -> void:
	smoke_steps+=1
	smoke_peak=maxf(smoke_peak,actors[1].position.y)
	if smoke_steps==140:
		print("SMOKE_POSITION ",actors[1].position," hp=",actors[1].health," velocity=",actors[1].velocity)
		var a=actors[1]
		if a.position.distance_to(Vector3(20,8.1,25))<4:push_error("Movement smoke failed");get_tree().quit(12);return
		if smoke_peak<8.8:push_error("Jump smoke failed");get_tree().quit(15);return
		if not a.is_on_floor():push_error("Grounding smoke failed");get_tree().quit(13);return
		a.ammo=5;a.wants_reload=true
	if smoke_steps==280:
		if actors[1].ammo!=30:push_error("Reload smoke failed");get_tree().quit(14);return
		print("Z3WAX_SMOKE_PASS movement,jump,grounding,reload sectors=",world.sectors.size());get_tree().quit()

func _input(event: InputEvent) -> void:
	if server_mode or mode not in ["PLAYING","FINISHED"] or not OS.has_feature("mobile"):return
	if event is InputEventScreenTouch and not event.pressed:
		if touches.get(event.index,"")=="fire":touch_fire=false
		touches.erase(event.index)
		if event.index==stick_index:stick_index=-1;touch_move=Vector2.ZERO
		if event.index==look_index:look_index=-1
		return
	if map_panel.visible:return
	if event is InputEventScreenTouch and event.pressed:
		var p=event.position
		if Rect2(1080,530,170,110).has_point(p):touches[event.index]="fire";touch_fire=true
		elif Rect2(880,600,180,60).has_point(p):jump_pending=true
		elif Rect2(880,540,180,55).has_point(p):reload_pending=true
		elif p.x<400 and p.y>350 and stick_index<0:stick_index=event.index;stick_origin=p
		elif p.x>400 and p.y>160 and look_index<0:look_index=event.index
	if event is InputEventScreenDrag:
		if event.index==stick_index:touch_move=((event.position-stick_origin)/70).limit_length()
		elif event.index==look_index:yaw=wrapf(yaw-event.relative.x*.005,-PI,PI);pitch=clampf(pitch-event.relative.y*.005,-.8,.8)

func _process(dt: float) -> void:
	if server_mode:return
	ui_timer+=dt
	if ui_timer<.25:return
	ui_timer=0
	var report={"mode":mode,"actors":actors.size(),"time":match_time,"sectors":world.sectors.size(),"smoke":smoke}
	if actors.has(local_id):
		var a=actors[local_id];report.merge({"position":[a.position.x,a.position.y,a.position.z],"health":a.health,"ammo":a.ammo,"reload":a.reload_left,"floor":a.is_on_floor(),"animation":a.last_animation})
	var file=FileAccess.open("user://qa_state.json",FileAccess.WRITE)
	if file:file.store_string(JSON.stringify(report))
