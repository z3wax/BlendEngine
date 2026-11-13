class_name CyclesBridge
extends Node
## Experimental desktop Cycles host. Receives the repository path tracer's
## scene-linear float32 frames; it does not substitute Godot raster rendering.
## One request in flight: pending camera updates are coalesced to avoid a backlog.
signal frame_ready(image: Image, revision: int)
signal preview_ready(image: Image, revision: int, samples: int)
signal failed(message: String)
signal render_started(revision: int)

var worker_pid := -1
var pipe: FileAccess
var error_pipe: FileAccess
var output_directory := ""
var requested_revision := 0
var received_revision := 0
var busy := false
var pending_camera: Camera3D
var pending_frame := false
var dirty_transforms: Dictionary = {}
var render_size := Vector2i.ZERO
var preview_sequence := 0
var next_preview_poll_ms := 0
var deadline_ms := 0
var timeout_ms := 300000

func start_worker(binary: String, scene_xml: String, directory: String, dimensions: Vector2i, samples: int, threads: int = 2) -> Error:
	if worker_pid > 0:
		return ERR_ALREADY_IN_USE
	if OS.get_name() != "Linux" or not FileAccess.file_exists(binary) or not FileAccess.file_exists(scene_xml):
		return ERR_UNAVAILABLE
	if dimensions.x < 1 or dimensions.y < 1 or dimensions.x > 8192 or dimensions.y > 8192 or dimensions.x * dimensions.y > 16777216 or samples < 1 or samples > 1048576 or threads < 1 or threads > 256:
		return ERR_INVALID_PARAMETER
	output_directory = directory
	var error := DirAccess.make_dir_recursive_absolute(directory)
	if error != OK:
		return error
	# Each process owns its own directory; never consume an earlier worker's frame.
	if FileAccess.file_exists(directory.path_join("frame.rgba32f")):
		return ERR_ALREADY_EXISTS
	var process := OS.execute_with_pipe(binary, PackedStringArray([scene_xml, directory, str(dimensions.x), str(dimensions.y), str(samples), str(threads)]), false)
	if process.is_empty():
		return ERR_CANT_FORK
	worker_pid = process.pid
	pipe = process.stdio
	error_pipe = process.stderr
	render_size = dimensions
	requested_revision = 0
	received_revision = 0
	preview_sequence = 0
	next_preview_poll_ms = 0
	busy = false
	return OK

static func camera_values(camera: Camera3D) -> String:
	# Cycles looks down local +Z; Godot looks down local -Z.
	var pose := camera.global_transform
	pose.basis.z = -pose.basis.z
	var b := pose.basis
	var p := pose.origin
	var fov := deg_to_rad(camera.fov)
	# Cycles auto viewplane defines FOV on the smaller image dimension.
	var viewport_size := camera.get_viewport().get_visible_rect().size
	if camera.keep_aspect == Camera3D.KEEP_WIDTH and viewport_size.x > viewport_size.y:
		fov = 2.0 * atan(tan(fov * 0.5) * viewport_size.y / viewport_size.x)
	elif camera.keep_aspect == Camera3D.KEEP_HEIGHT and viewport_size.y > viewport_size.x:
		fov = 2.0 * atan(tan(fov * 0.5) * viewport_size.x / viewport_size.y)
	return "%s %s %s %s %s %s %s %s %s %s %s %s %s" % [b.x.x, b.y.x, b.z.x, p.x, b.x.y, b.y.y, b.z.y, p.y, b.x.z, b.y.z, b.z.z, p.z, fov]

func queue_object_transform(index: int, pose: Transform3D) -> void:
	if index < 0 or not pose.is_finite() or is_zero_approx(pose.basis.determinant()):
		failed.emit("Invalid Cycles object transform")
		return
	dirty_transforms[index] = pose

func request_frame(camera: Camera3D = null) -> void:
	if worker_pid <= 0:
		failed.emit("Cycles worker is not running")
		return
	if busy:
		pending_camera = camera
		pending_frame = true
		return
	for index in dirty_transforms:
		var pose: Transform3D = dirty_transforms[index]
		var b := pose.basis
		var p := pose.origin
		pipe.store_line("object %d %s %s %s %s %s %s %s %s %s %s %s %s" % [index, b.x.x, b.y.x, b.z.x, p.x, b.x.y, b.y.y, b.z.y, p.y, b.x.z, b.y.z, b.z.z, p.z])
	dirty_transforms.clear()
	requested_revision += 1
	var command := "render %d" % requested_revision
	if is_instance_valid(camera):
		command += " " + camera_values(camera)
	pipe.store_line(command)
	pipe.flush()
	busy = true
	deadline_ms = Time.get_ticks_msec() + timeout_ms
	render_started.emit(requested_revision)

func _process(_delta: float) -> void:
	if worker_pid <= 0:
		return
	# Drain status pipes so the worker cannot block on a full stdout buffer.
	if pipe:
		var status := pipe.get_buffer(8192).get_string_from_utf8()
		if "ERROR " in status:
			_fail(status.strip_edges())
			return
	if error_pipe:
		var diagnostic := error_pipe.get_buffer(8192).get_string_from_utf8()
		if not diagnostic.is_empty():
			push_warning("Cycles: " + diagnostic.strip_edges())
	if not OS.is_process_running(worker_pid):
		_fail("Cycles worker exited before shutdown")
		return
	if not busy:
		return
	if Time.get_ticks_msec() > deadline_ms:
		_fail("Cycles render timed out; no completed frame was substituted")
		return
	_read_preview()
	if worker_pid <= 0:
		return
	var path := output_directory.path_join("frame.rgba32f")
	if not FileAccess.file_exists(path):
		return
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null or file.get_length() < 16:
		return
	var width := file.get_32()
	var height := file.get_32()
	var revision := file.get_64()
	if revision <= received_revision:
		return
	if revision != requested_revision or Vector2i(width, height) != render_size or file.get_length() != 16 + width * height * 16:
		_fail("Invalid Cycles frame header or byte count")
		return
	var image := Image.create_from_data(width, height, false, Image.FORMAT_RGBAF, file.get_buffer(width * height * 16))
	if image == null or image.is_empty():
		_fail("Could not decode Cycles float32 frame")
		return
	received_revision = revision
	busy = false
	frame_ready.emit(image, revision)
	if pending_frame and not busy:
		var next := pending_camera
		pending_camera = null
		pending_frame = false
		request_frame(next if is_instance_valid(next) else null)

func _read_preview() -> void:
	if Time.get_ticks_msec() < next_preview_poll_ms:
		return
	next_preview_poll_ms = Time.get_ticks_msec() + 100
	var path := output_directory.path_join("preview.rgba32f")
	if not FileAccess.file_exists(path):
		return
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null or file.get_length() < 32:
		return
	var width := file.get_32()
	var height := file.get_32()
	var revision := file.get_64()
	var sequence := file.get_64()
	var samples := file.get_32()
	var reserved := file.get_32()
	if revision != requested_revision or sequence <= preview_sequence:
		return
	if Vector2i(width, height) != render_size or file.get_length() != 32 + width * height * 16 or reserved != 0:
		_fail("Invalid Cycles progressive frame")
		return
	preview_sequence = sequence
	var image := Image.create_from_data(width, height, false, Image.FORMAT_RGBAF, file.get_buffer(width * height * 16))
	preview_ready.emit(image, revision, samples)

func _fail(message: String) -> void:
	stop_worker()
	failed.emit(message)

func stop_worker() -> void:
	if worker_pid > 0 and OS.is_process_running(worker_pid):
		# Do not block the game loop waiting for an expensive frame to finish.
		OS.kill(worker_pid)
	worker_pid = -1
	pipe = null
	error_pipe = null
	busy = false
	pending_camera = null
	pending_frame = false
	dirty_transforms.clear()

func _exit_tree() -> void:
	stop_worker()
