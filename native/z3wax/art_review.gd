extends Node3D
## Actual 3D art review. Deliberately separate from the unapproved gameplay prototype.
signal training_requested
signal connect_requested(host: String, token: String)
signal map_requested
var embedded=false
var world_environment: WorldEnvironment
var lighting: Environment
var server_address: LineEdit
var server_token: LineEdit
var connection_dialog: PopupPanel
const ASSET="res://assets/realistic/"
var camera: Camera3D
var soldier: Node3D
var rifle: Node3D
var ui: Control
var notice: Label
var orbit=0.0
var armory=false
var tour=false
var clock=0.0

func material(prefix: String, tiling: float=1.0) -> StandardMaterial3D:
	var m=StandardMaterial3D.new()
	m.albedo_texture=load(ASSET+prefix+"_color.jpg")
	m.normal_enabled=true;m.normal_texture=load(ASSET+prefix+"_normal.jpg")
	m.roughness_texture=load(ASSET+prefix+"_rough.jpg")
	m.uv1_scale=Vector3(tiling,tiling,tiling);m.texture_filter=BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	return m

func web_material(prefix: String, tiling: Vector3) -> StandardMaterial3D:
	var m=StandardMaterial3D.new();m.albedo_texture=load(ASSET+prefix+"_Color.webp");m.normal_enabled=true;m.normal_texture=load(ASSET+prefix+"_NormalGL.webp");m.roughness_texture=load(ASSET+prefix+"_Roughness.webp");m.uv1_scale=tiling;m.texture_filter=BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC;return m

func box(pos: Vector3, dimensions: Vector3, mat: Material) -> MeshInstance3D:
	var n=MeshInstance3D.new();var mesh=BoxMesh.new();mesh.size=dimensions;n.mesh=mesh;n.material_override=mat;add_child(n);n.position=pos;return n

func model(file: String, pos: Vector3, yaw: float=0.0, scale_factor: float=1.0) -> Node3D:
	var n=load(ASSET+file).instantiate();add_child(n);n.position=pos;n.rotation.y=yaw;n.scale=Vector3.ONE*scale_factor;return n

func _ready() -> void:
	tour="--art-tour" in OS.get_cmdline_user_args()
	world_environment=WorldEnvironment.new();var world=world_environment;var e=Environment.new();lighting=e;world.environment=e
	if not embedded:add_child(world)
	else:world.free();world_environment=null
	var sky=Sky.new();var panorama=PanoramaSkyMaterial.new();panorama.panorama=load(ASSET+"sunset.hdr");sky.sky_material=panorama;sky.radiance_size=Sky.RADIANCE_SIZE_256
	e.background_mode=Environment.BG_SKY;e.sky=sky;e.sky_rotation.y=1.15
	e.ambient_light_source=Environment.AMBIENT_SOURCE_SKY;e.ambient_light_energy=.7
	e.tonemap_mode=Environment.TONE_MAPPER_FILMIC;e.tonemap_exposure=.95
	e.fog_enabled=true;e.fog_density=.0008;e.fog_sky_affect=.08;e.fog_light_color=Color(.65,.48,.32)
	var sun=DirectionalLight3D.new();sun.rotation_degrees=Vector3(-16,-125,0);sun.light_energy=1.1;sun.light_color=Color(1,.83,.65);sun.shadow_enabled=true;sun.directional_shadow_max_distance=90;add_child(sun)
	var ground=material("ground",45);ground.albedo_color=Color(.67,.61,.51)
	box(Vector3(0,-.12,-20),Vector3(180,.2,180),ground)
	var plaster=web_material("RustyCorrugated",Vector3(3,1,1))
	var timber=web_material("Wood092",Vector3(1,2,1))
	var dark=StandardMaterial3D.new();dark.albedo_color=Color(.055,.047,.038);dark.roughness=.9
	var metal=StandardMaterial3D.new();metal.albedo_color=Color(.19,.15,.105);metal.metallic=.65;metal.roughness=.75
	# A weathered outpost frames the center without filling the scene with gameplay boxes.
	for offset in [Vector3(4.5,0,-14),Vector3(-10,0,-22)]:
		box(offset+Vector3(0,1.7,0),Vector3(7,3.4,4),plaster)
		box(offset+Vector3(0,1.15,2.015),Vector3(1.35,2.3,.035),dark)
		for x in [-2.3,2.3]:
			box(offset+Vector3(x,1.85,2.03),Vector3(1.3,1.2,.06),dark)
			box(offset+Vector3(x,1.85,2.08),Vector3(.08,1.3,.1),timber)
			box(offset+Vector3(x,1.85,2.08),Vector3(1.4,.08,.1),timber)
		for k in range(25):
			box(offset+Vector3((k-12)*.31,3.45,0),Vector3(.33,.1,4.7),timber)
		for x in [-3.3,3.3]:box(offset+Vector3(x,1.65,3.1),Vector3(.13,3.3,.13),metal)
		box(offset+Vector3(0,3.2,2.7),Vector3(7.1,.12,1.8),metal)
	model("car.glb",Vector3(-3.2,0,-5),3.4,1)
	model("crate.glb",Vector3(2.8,0,-2),-.3)
	model("crate.glb",Vector3(3.5,0,-2.5),.2)
	model("barrel.glb",Vector3(-2.6,0,-2),.4)
	model("barrel.glb",Vector3(4,0,-3),.9)
	var rng=RandomNumberGenerator.new();rng.seed=713
	for i in range(22):
		var x=rng.randf_range(-26,26);var z=rng.randf_range(-40,-8)
		model("rock/rock.gltf",Vector3(x,-.08,z),rng.randf_range(0,TAU),rng.randf_range(.35,1.6))
	var rock_source=load(ASSET+"rock/rock.gltf").instantiate()
	var rock_material=rock_source.find_children("*","MeshInstance3D",true,false)[0].mesh.surface_get_material(0)
	rock_source.free()
	for i in range(12):
		var distant=model("rock/distant.glb",Vector3((i-6)*20,-3,-100-rng.randf_range(0,25)),rng.randf_range(0,TAU),rng.randf_range(9,17))
		for mesh in distant.find_children("*","MeshInstance3D",true,false):mesh.material_override=rock_material;mesh.cast_shadow=GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	soldier=load("res://operator_visual.gd").new();add_child(soldier);soldier.rotation.y=.45
	rifle=model("rifle_real.glb",Vector3(.02,1.28,.35),-PI/2,.55)
	rifle.basis=Basis(Vector3.BACK,-.35)*Basis(Vector3.UP,-PI/2)*.55;rifle.hide()
	camera=Camera3D.new();camera.fov=34;camera.near=.05;camera.far=400;add_child(camera);camera.current=true;update_camera()
	build_ui()
	if "--capture-art" in OS.get_cmdline_user_args():
		await get_tree().create_timer(3).timeout
		await RenderingServer.frame_post_draw
		var path=OS.get_environment("Z3WAX_ART_CAPTURE")
		if path.is_empty():path="user://art-review.png"
		var err=get_viewport().get_texture().get_image().save_png(path)
		print("Z3WAX_ART_CAPTURE ",err," ",path);get_tree().quit(err)

func update_camera() -> void:
	var center=Vector3(0,1.0,0)
	camera.position=center+Vector3(sin(orbit)*3.85,.25,cos(orbit)*3.85);camera.look_at(center)

func _process(dt: float) -> void:
	if not visible:return
	clock+=dt
	if tour:
		if clock<7:orbit=sin(clock*.5)*.18;update_camera()
		elif not armory:select_tab("ARMORY")
	if armory:
		rifle.rotation.y+=dt*.15

func _unhandled_input(event: InputEvent) -> void:
	if not visible:return
	if event is InputEventKey and event.pressed:
		if event.keycode==KEY_H:ui.visible=not ui.visible
		if event.keycode==KEY_LEFT:orbit-=.12;update_camera()
		if event.keycode==KEY_RIGHT:orbit+=.12;update_camera()

func style(color: Color, cyan: bool=false) -> StyleBoxFlat:
	var s=StyleBoxFlat.new();s.bg_color=color;s.border_color=Color(.22,.60,.62,.8) if cyan else Color(.56,.54,.49,.65);s.set_border_width_all(1);s.content_margin_left=10;s.content_margin_right=10;s.content_margin_top=6;s.content_margin_bottom=6;return s

func label(text: String, pos: Vector2, font_size: int, parent: Node=null) -> Label:
	if parent==null:parent=ui
	var l=Label.new();l.text=text;l.position=pos;l.add_theme_font_size_override("font_size",font_size);l.add_theme_color_override("font_color",Color(.92,.91,.86));l.add_theme_color_override("font_shadow_color",Color(0,0,0,.9));l.add_theme_constant_override("shadow_offset_x",1);l.add_theme_constant_override("shadow_offset_y",2);parent.add_child(l);return l

func panel(pos: Vector2, size_px: Vector2, cyan: bool=false) -> Panel:
	var p=Panel.new();p.position=pos;p.size=size_px;p.add_theme_stylebox_override("panel",style(Color(.025,.032,.033,.82),cyan));ui.add_child(p);return p

func button(text: String, pos: Vector2, size_px: Vector2, action: Callable, blue: bool=false) -> Button:
	var b=Button.new();b.text=text;b.position=pos;b.size=size_px;b.add_theme_font_size_override("font_size",19);b.add_theme_stylebox_override("normal",style(Color(.055,.23,.34,.95) if blue else Color(.03,.035,.035,.84),blue));b.add_theme_stylebox_override("hover",style(Color(.12,.31,.35,.95),true));b.pressed.connect(action);ui.add_child(b);return b

func build_ui() -> void:
	var layer=CanvasLayer.new();add_child(layer);ui=Control.new();ui.theme=Theme.new();ui.theme.default_font=load(ASSET+"BarlowCondensed-SemiBold.ttf");ui.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT);ui.mouse_filter=Control.MOUSE_FILTER_IGNORE;layer.add_child(ui)
	panel(Vector2(32,18),Vector2(265,65));label("Z3WAX PLAYER",Vector2(48,24),23);label("DISLAND  /  OPERATOR 01",Vector2(48,53),13)
	panel(Vector2(32,89),Vector2(129,27));label("GOLD  —",Vector2(43,91),16)
	panel(Vector2(168,89),Vector2(129,27));label("GEMS  —",Vector2(180,91),16)
	label("Z3WAX",Vector2(542,0),43);label("B A T T L E   R O Y A L E",Vector2(518,46),14)
	var tab_x=355.0
	for i in range(5):
		var title=["HOME","MATCHMAKING","ARMORY","CREDITS","MAP"][i]
		var tab_width=155.0 if i==1 else 105.0
		button(title,Vector2(tab_x,70),Vector2(tab_width,31),func():select_tab(title));tab_x+=tab_width
	panel(Vector2(32,128),Vector2(273,136),true);label("NEWS & EVENTS",Vector2(43,133),23)
	label("DISLAND",Vector2(45,178),23);label("16 × 16 KM  •  VISUAL DEVELOPMENT",Vector2(45,213),12);label("TACTICAL OUTPOST / SUNSET",Vector2(45,237),12)
	panel(Vector2(1014,128),Vector2(233,267),true);label("MATCHMAKING",Vector2(1025,135),23)
	button("START TRAINING" if embedded else "START MATCH",Vector2(1026,176),Vector2(209,48),func():
		if embedded:training_requested.emit()
		else:notice.text="Art review only. Use the game main scene to play.",true)
	label("MODE",Vector2(1026,239),12);label("SOLO + 7 BOTS" if embedded else "BATTLE ROYALE",Vector2(1026,256),18)
	label("MAP",Vector2(1026,290),12);label("DISLAND",Vector2(1026,307),18)
	if embedded:button("CONNECT TO SERVER",Vector2(1026,348),Vector2(209,36),func():connection_dialog.popup_centered(Vector2i(360,240)))
	else:label("STATUS: ART REVIEW",Vector2(1026,357),15)
	panel(Vector2(32,544),Vector2(300,119),true);label("TEAM CHAT",Vector2(43,550),21)
	label("No server connected",Vector2(43,587),14);label("H: hide UI   ← →: orbit camera",Vector2(43,625),13)
	notice=label("DEVELOPMENT BUILD • VISUALS AND MAP IN PROGRESS" if embedded else "VISUAL REVIEW • NOT GAMEPLAY • NOT A RELEASE",Vector2(390,682),16)
	button("EXIT",Vector2(1140,20),Vector2(107,42),func():get_tree().quit())
	connection_dialog=PopupPanel.new();layer.add_child(connection_dialog)
	var form=VBoxContainer.new();form.add_theme_constant_override("separation",10);connection_dialog.add_child(form)
	var title=Label.new();title.text="CONNECT TO YOUR SERVER";form.add_child(title)
	server_address=LineEdit.new();server_address.text="127.0.0.1";server_address.placeholder_text="Ubuntu PC IP address";server_address.custom_minimum_size=Vector2(340,40);form.add_child(server_address)
	server_token=LineEdit.new();server_token.secret=true;server_token.placeholder_text="Access token, if required";form.add_child(server_token)
	var connect_button=Button.new();connect_button.text="CONNECT";connect_button.pressed.connect(func():connection_dialog.hide();connect_requested.emit(server_address.text,server_token.text));form.add_child(connect_button)
	var cancel=Button.new();cancel.text="CANCEL";cancel.pressed.connect(connection_dialog.hide);form.add_child(cancel)

func select_tab(title: String) -> void:
	if title=="ARMORY":
		armory=true;soldier.hide();soldier.animation.pause();rifle.show();rifle.position=Vector3(0,1.1,.8);rifle.rotation=Vector3(0,PI/2,-.05);rifle.scale=Vector3.ONE*.8;notice.text="M4A1 model by Firewarden3D • CC BY 4.0 • Art review"
	elif title=="HOME" or title=="MATCHMAKING":
		armory=false;soldier.show();soldier.animation.play("idle");rifle.hide();rifle.position=Vector3(.02,1.28,.35);rifle.basis=Basis(Vector3.BACK,-.35)*Basis(Vector3.UP,-PI/2)*.55;notice.text="VISUAL REVIEW • NOT GAMEPLAY • NOT A RELEASE"
	elif title=="CREDITS":notice.text="DanlyVostok • Firewarden3D • alexdelker • Poly Haven / CC BY & CC0"
	else:
		if embedded:map_requested.emit()
		else:notice.text="Disland terrain and detailed map are not finished."

func set_active(active: bool) -> void:
	visible=active;ui.visible=active;camera.current=active
	if world_environment:world_environment.environment=lighting if active else null
	if active:soldier.animation.play("idle")
	else:soldier.animation.pause();connection_dialog.hide()
