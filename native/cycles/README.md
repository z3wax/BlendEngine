# Repository Cycles game-host integration (experimental)

This host links the **Cycles 3.6 source already in `intern/cycles`**. Godot receives
actual Cycles scene-linear RGBA float32 buffers through a local worker process.
It does not use the installed Blender 4.3 renderer, substitute a raster frame,
call a remote AI renderer, or generate replacement artwork.

**Status: Linux CPU integration and snapshot viewer; not a release game renderer.**
The normal Z3WAX game still uses Godot Compatibility. Full live mesh deformation,
material/environment synchronization, native GPU texture interoperability, Android,
iOS, GPU backends, and physical-device performance are not implemented/validated by
this baseline. An unchanged path tracer cannot promise equal-quality 30–60 FPS on
ordinary phones. The current scene also does not match the supplied concept art.

## What works

- A persistent `Session`, dynamic BVHs, camera updates and rigid-object transforms.
  The standalone XML reader normally forces static BVHs; the host explicitly
  restores dynamic mode before the first build so movement remains visible.
- Identical mesh data shares geometry/BVHs through `<instance object="index"/>`.
  Snapshot deduplication hashes exact evaluated positions, topology, normals, UVs,
  and material identity. It does not decimate or round mesh data.
- Authored normals and tangent frames survive XML export (`N`, `T`, `TS`).
- Texture limit is zero; pixel size is one; no render time cutoff, frustum deletion,
  or integrator/shader-kernel changes. Offscreen objects remain available to rays.
- Atomic float32 frames and progressive previews; Godot never reads partial files.
  Preview samples converge toward the requested final sample count. Previews are
  explicitly incomplete and do not replace the final output.
- At most one render and one coalesced pending request in Godot. Changed rigid
  transforms are batched before the next render. The game loop remains responsive;
  renderer latency is still the time needed to trace a frame.
- Local child-process lifecycle, stale-revision rejection, byte-count validation,
  timeout/error reporting, and shutdown. No network listener is opened.

## Build on Ubuntu

Use the source build on the target OS. Development binaries built on Debian 13
are not claimed to be portable Ubuntu releases. Ubuntu 24.04 CI runs the recipe
below; consult its actual result before treating that platform as verified.

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build libopenimageio-dev \
  libboost-filesystem-dev libboost-regex-dev libboost-thread-dev \
  libboost-date-time-dev libboost-system-dev libtbb-dev libpugixml-dev \
  libopenexr-dev libimath-dev libjpeg-dev libpng-dev libtiff-dev \
  libwebp-dev libzstd-dev libfmt-dev libepoxy-dev libfreetype-dev zlib1g-dev \
  python3-numpy python3-openimageio
bash tools/z3wax/cycles/build.sh ../cycles-game-build
```

The CPU profile disables optional OSL, OpenVDB, USD, denoisers and GPU devices to
build a small dependency baseline. This is **not full Blender feature parity**.
SVM path-tracing kernels and the supported material graphs remain unchanged.

## Verification

```bash
/usr/bin/python3 native/cycles/tests/verify_worker.py \
  --bin-dir ../cycles-game-build/bin --output /tmp/cycles-reference-proof
/usr/bin/python3 native/cycles/tests/verify_instancing.py \
  --bin-dir ../cycles-game-build/bin --output /tmp/cycles-instance-proof

export Z3WAX_CYCLES_WORKER="$(realpath ../cycles-game-build/bin/cycles_game_worker)"
export Z3WAX_CYCLES_SCENE="$PWD/native/cycles/tests/reference.xml"
export Z3WAX_CYCLES_OUTPUT="$(mktemp -d /tmp/z3wax-cycles-test.XXXXXX)"
godot --headless --path native/z3wax --editor --import
godot --headless --path native/z3wax --script res://tests/cycles_bridge.gd
```

`verify_worker.py` compares the worker against the standalone executable using
**matching dynamic BVH, seed, sample count and integrator settings**. It exercises
repeated renders, stale requests, invalid object indices, object movement, camera
movement and restoration. `verify_instancing.py` compares shared and duplicated
geometry with authored normals and a connected normal map. The Godot test receives
real frames, checks float-image transport and coalesces 100 requests into one pending
frame, then moves/restores an object and checks byte-identical transport. Reports are JSON, with measured differences rather than a quality assertion
based only on code inspection.

Local CPU tests on 2026-11-13: both reference comparisons had maximum absolute
error **0.0**. The actual 640×360, 64-sample lobby snapshot also matched the standalone reference with maximum error and RMSE **0.0**. These deterministic cases do not establish equality for every
scene, render device, noise realization, Blender version or display transform.

## Export and view the actual Z3WAX lobby snapshot

Requires Godot 4.6.3 and Blender 4.3+ for asset import/export. **Blender is only the
scene-authoring/conversion tool in this path; repository Cycles performs rendering.**

```bash
mkdir -p /tmp/z3wax-cycles-stage
export Z3WAX_CYCLES_GLTF=/tmp/z3wax-cycles-stage/godot.glb
godot --headless --path native/z3wax --script res://tests/export_cycles_stage.gd
python3 tools/z3wax/cycles/prepare_gltf.py \
  /tmp/z3wax-cycles-stage/godot.glb /tmp/z3wax-cycles-stage/blender.glb
blender -b --python-exit-code 1 --python tools/z3wax/cycles/import_stage.py -- \
  /tmp/z3wax-cycles-stage/blender.glb /tmp/z3wax-cycles-stage/stage.blend
blender -b /tmp/z3wax-cycles-stage/stage.blend --python-exit-code 1 \
  --python tools/z3wax/cycles/export_stage.py -- \
  /tmp/z3wax-cycles-stage/snapshot "$PWD/native/z3wax/assets/realistic/sunset.hdr"

export Z3WAX_CYCLES_WORKER="$(realpath ../cycles-game-build/bin/cycles_game_worker)"
export Z3WAX_CYCLES_SCENE=/tmp/z3wax-cycles-stage/snapshot/scene.xml
export Z3WAX_CYCLES_OUTPUT="$(mktemp -d /tmp/z3wax-cycles-view.XXXXXX)"
export Z3WAX_CYCLES_SAMPLES=64
godot --path native/z3wax res://render/cycles_viewer.tscn
```

This exports a **static evaluated pose**, not continuous character animation.
Supported connected PBR nodes are translated; unsupported nodes fail explicitly.
Godot UI, fog, custom shaders and subsequent animation are not exported. Three
unlit helper meshes are explicitly reported as omitted. Lighting uses a separate
Cycles HDRI/sun setup and does not claim raster/Blender color-management parity.
The viewer applies a display-only Reinhard/sRGB transform; raw float pixels remain
unchanged. `export-report.json` records instances and omissions.

The current lobby snapshot has 133 surfaces, 31 unique geometries, 102 instances,
and 2,273,587 placed triangles. XML size decreased from approximately 948 MiB to
68 MiB without triangle reduction. This is scene serialization/geometry reuse,
not a measured claim of equivalent total RAM reduction or FPS improvement.
A 640×360, 64-sample CPU snapshot took about 34 seconds including worker startup
on the development machine. **It is not real-time gameplay.**

## Local protocol

`cycles_game_worker SCENE.xml OUTPUT_DIR WIDTH HEIGHT SAMPLES THREADS`

Only trusted local scene XML is supported; the legacy XML scene reader is not an
untrusted-file sandbox. Give each worker a fresh, writable output directory.
The process writes `READY 1 <object-count>` and accepts newline-separated commands:

- `render REVISION`: render the existing scene/camera.
- `render REVISION M00 M01 M02 TX M10 M11 M12 TY M20 M21 M22 TZ FOV_RADIANS`:
  update the camera (Cycles local +Z), then render.
- `object INDEX M00 M01 M02 TX M10 M11 M12 TY M20 M21 M22 TZ`:
  update one rigid transform before the next render; all ray visibility is retained.
- `quit`: cleanly stop after the current render.

Completed frames: `frame.rgba32f`, little-endian `<uint32 width, uint32 height,
uint64 revision>` then top-down scene-linear RGBA float32 (16 bytes/pixel).
Progressive frames: `preview.rgba32f`, same header followed by `<uint64 sequence,
uint32 samples, uint32 reserved=0>` then pixels. Each file is replaced atomically.
Final status: `FRAME revision width height requested_samples elapsed_seconds`.
Errors are explicit `ERROR ...`; no raster fallback or manufactured frame is sent.

## Next required work before replacing the game's renderer

1. Verified scene/material parity, live skinned vertices, lights and visibility
   updates; preserving indirect contributors across streamed sector boundaries.
2. GPU device builds and shared-texture upload instead of disk-based frame transport.
3. Physical hardware profiles and frame-time/memory measurements; quality comparisons
   on representative moving scenes, not only small fixtures.
4. Platform integration and testing for Android/iOS, Apple signing and stable gameplay.

A trained AI optimizer is not included. Geometry deduplication, retained BVHs and
request coalescing are deterministic optimizations and are described as such.
