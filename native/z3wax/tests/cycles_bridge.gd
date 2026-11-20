extends SceneTree
var bridge: Node
var started := 0
var ticks := 0
var frames := 0
var previews := 0
var original_pixels := PackedByteArray()
var directory := ""
func _initialize() -> void:
	call_deferred("run")
func run() -> void:
	bridge = load("res://render/cycles_bridge.gd").new()
	root.add_child(bridge)
	bridge.failed.connect(func(message: String): push_error(message); quit(1))
	bridge.frame_ready.connect(received)
	bridge.preview_ready.connect(func(_image: Image, _revision: int, _samples: int): previews += 1)
	directory = OS.get_environment("Z3WAX_CYCLES_OUTPUT")
	var error: Error = bridge.start_worker(OS.get_environment("Z3WAX_CYCLES_WORKER"), OS.get_environment("Z3WAX_CYCLES_SCENE"), directory, Vector2i(96, 64), 32, 2)
	if error != OK:
		push_error("Cycles start failed: " + error_string(error)); quit(1); return
	started = Time.get_ticks_msec()
	bridge.request_frame()
	# Rapid camera/frame requests collapse to a single pending render.
	for i in range(100):
		bridge.request_frame()
	bridge.queue_object_transform(0, Transform3D(Basis.IDENTITY, Vector3(.5, 0, 0)))
func _process(_delta: float) -> bool:
	ticks += 1
	if started > 0 and Time.get_ticks_msec() - started > 180000:
		push_error("Bridge test timed out"); quit(1)
	return false
func received(image: Image, revision: int) -> void:
	assert(image.get_format() == Image.FORMAT_RGBAF)
	assert(image.get_size() == Vector2i(96, 64))
	assert(revision == frames + 1)
	assert(FileAccess.get_file_as_bytes(directory.path_join("frame.rgba32f")).slice(16) == image.get_data())
	var file := FileAccess.open(directory.path_join("godot-frame-%d.rgba32f" % revision), FileAccess.WRITE)
	file.store_buffer(image.get_data()); file.close()
	frames += 1
	if frames == 1:
		original_pixels = image.get_data()
	elif frames == 2:
		assert(original_pixels != image.get_data())
		bridge.queue_object_transform(0, Transform3D.IDENTITY)
		bridge.request_frame()
	elif frames == 3:
		assert(original_pixels == image.get_data())
		assert(ticks > 1)
		bridge.stop_worker()
		print("Z3WAX_CYCLES_BRIDGE_PASS actual_cycles_frames=3 coalescing,rigid_transform,restore main_loop_ticks=", ticks, " progressive_updates=", previews)
		quit()
