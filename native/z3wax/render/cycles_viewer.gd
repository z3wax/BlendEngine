extends Control
## Desktop snapshot viewer for repository Cycles. Not the game's release renderer.
var bridge: CyclesBridge
var picture: TextureRect
var label: Label
var started_ms := 0
func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var background := ColorRect.new()
	background.color = Color(.025, .03, .035)
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(background)
	picture = TextureRect.new()
	picture.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	picture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	picture.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	add_child(picture)
	var shader := Shader.new()
	shader.code = """shader_type canvas_item;
render_mode unshaded;
void fragment() {
 vec3 linear = max(texture(TEXTURE, UV).rgb, vec3(0.0));
 // Display-only Reinhard + sRGB. The received float32 frame remains unchanged.
 vec3 mapped = linear / (vec3(1.0) + linear);
 vec3 srgb = mix(12.92 * mapped, 1.055 * pow(mapped, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), mapped));
 COLOR = vec4(srgb, 1.0);
}"""
	var material := ShaderMaterial.new()
	material.shader = shader
	picture.material = material
	label = Label.new()
	label.position = Vector2(24, 20)
	label.add_theme_font_size_override("font_size", 20)
	label.text = "Z3WAX • REPOSITORY CYCLES\nRendering snapshot…"
	add_child(label)
	bridge = CyclesBridge.new()
	add_child(bridge)
	bridge.failed.connect(func(message: String): label.text = "CYCLES ERROR\n" + message)
	bridge.frame_ready.connect(show_frame)
	bridge.preview_ready.connect(func(image: Image, _revision: int, samples: int):
		picture.texture = ImageTexture.create_from_image(image)
		label.text = "Z3WAX • REPOSITORY CYCLES • CONVERGING\n%d samples completed • final quality still rendering" % samples
	)
	var size := Vector2i(640, 360)
	var samples := 64
	if OS.has_environment("Z3WAX_CYCLES_SAMPLES"):
		samples = int(OS.get_environment("Z3WAX_CYCLES_SAMPLES"))
	var error := bridge.start_worker(OS.get_environment("Z3WAX_CYCLES_WORKER"), OS.get_environment("Z3WAX_CYCLES_SCENE"), OS.get_environment("Z3WAX_CYCLES_OUTPUT"), size, samples)
	if error != OK:
		label.text = "CYCLES START ERROR\n" + error_string(error)
		return
	started_ms = Time.get_ticks_msec()
	bridge.request_frame()
func show_frame(image: Image, _revision: int) -> void:
	picture.texture = ImageTexture.create_from_image(image)
	label.text = "Z3WAX • REPOSITORY CYCLES 3.6 • CPU SNAPSHOT\n%d × %d • %.2f s • NOT REAL-TIME GAMEPLAY" % [image.get_width(), image.get_height(), (Time.get_ticks_msec() - started_ms) / 1000.0]
	if OS.has_environment("Z3WAX_CYCLES_CAPTURE"):
		await RenderingServer.frame_post_draw
		var error := get_viewport().get_texture().get_image().save_png(OS.get_environment("Z3WAX_CYCLES_CAPTURE"))
		print("Z3WAX_CYCLES_VIEWER_CAPTURE ", error_string(error))
		get_tree().quit(0 if error == OK else 1)
