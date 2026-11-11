# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure how fast this machine renders Highland Patrol frames with EEVEE.

Builds the level, walks the camera along the trail and renders one frame per
step with a single sample, the way a running game draws. Shader compilation
is kept out of the timing by rendering warm-up frames first.

Run from the repository root (the current Blender scene is replaced)::

    blender -b --factory-startup --python-exit-code 1 \
        --python tools/blendengine/measure_fps.py -- --width 1920 --height 1080

Whether the GPU or a software rasterizer did the work is printed with the
result. This times complete offline frames including reading the image back,
so an interactive viewport on the same machine is usually somewhat faster.
"""

import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import time

import bpy

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))

import blendengine
from blendengine import cinematic, highland, optimization, smart_optimizer


def renderer_name():
    try:
        import gpu
        return "%s / %s" % (gpu.platform.vendor_get(), gpu.platform.renderer_get())
    except Exception:
        return "unknown (no GPU context in this session)"


def main():
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--presets", default="CINEMATIC,HIGH,BALANCED,LOW",
                        help="comma separated quality presets to time")
    parser.add_argument("--optimize", action="store_true", help="run the Smart Optimizer first")
    parser.add_argument("--no-post", action="store_true", help="skip the cinematic compositor effects")
    options = parser.parse_args(arguments)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    blendengine.register()
    try:
        scene = bpy.context.scene
        created = highland.generate_highland_patrol(bpy.context)
        if options.optimize:
            smart_optimizer.optimize(bpy.context)
        camera = created["camera"]
        scene.render.resolution_x, scene.render.resolution_y = options.width, options.height
        scene.render.resolution_percentage = 100
        scene.render.filepath = ""
        results = {}
        for preset in options.presets.split(","):
            optimization.apply_preset(scene, preset)
            if options.no_post:
                cinematic.remove_post(scene)
            # One sample per frame, no motion blur: what a game frame costs.
            scene.eevee.taa_render_samples = 1
            scene.render.use_motion_blur = False
            for name in ("use_motion_blur", "use_bokeh_jittered"):
                if hasattr(scene.eevee, name):
                    setattr(scene.eevee, name, False)
            times = []
            for frame in range(options.warmup + options.frames):
                y = highland.SPAWN[1] + frame * 0.6
                x = 3.0 * math.sin(y / 17.0)
                camera.location = (x, y, float(highland.terrain_height(x, y)) + 1.62)
                camera.rotation_euler = (math.radians(86.0), 0.0, math.radians(-6.0 + frame * 2.0))
                start = time.perf_counter()
                bpy.ops.render.render(write_still=False)
                if frame >= options.warmup:
                    times.append(time.perf_counter() - start)
            median = statistics.median(times)
            results[preset] = {"median_ms": median * 1000.0, "fps": 1.0 / median,
                               "slowest_ms": max(times) * 1000.0}
        report = {
            "blender": bpy.app.version_string,
            "renderer": renderer_name(),
            "resolution": [options.width, options.height],
            "frames": options.frames,
            "optimized": options.optimize,
            "scene": smart_optimizer.measure(scene),
            "presets": results,
        }
        print("FPS_REPORT " + json.dumps(report))
        for preset, item in results.items():
            print("%-10s %8.1f ms/frame  %7.2f FPS" % (preset, item["median_ms"], item["fps"]))
        print("Renderer: " + report["renderer"])
    finally:
        sys.stdout.flush()
        blendengine.unregister()


if __name__ == "__main__":
    main()
