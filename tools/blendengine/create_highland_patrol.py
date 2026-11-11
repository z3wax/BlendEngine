# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the Highland Patrol first-person level, optionally optimize, save and render it.

Run from the repository root in a fresh Blender 4.3 session (the scene is replaced)::

    blender -b --factory-startup --python-exit-code 1 \
        --python tools/blendengine/create_highland_patrol.py -- \
        --output-dir /tmp/highland --optimize --render

Results: ``highland_patrol.blend`` and, with ``--render``, ``highland_patrol.png``.
"""

import argparse
import os
from pathlib import Path
import sys
import time

import bpy

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))

import blendengine
from blendengine import highland, smart_optimizer


def main():
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="/tmp/blendengine-highland")
    parser.add_argument("--optimize", action="store_true", help="run the Smart Optimizer on the level")
    parser.add_argument("--render", action="store_true", help="render the spawn view with EEVEE")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--samples", type=int, default=32)
    options = parser.parse_args(arguments)
    os.makedirs(options.output_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    blendengine.register()
    try:
        scene = bpy.context.scene
        start = time.perf_counter()
        created = highland.generate_highland_patrol(bpy.context)
        print("Level built in %.1f s: %d objects, %d enemies." % (
            time.perf_counter() - start, len(scene.objects), created["enemy_count"]))
        print("Before: %s" % smart_optimizer.measure(scene))
        if options.optimize:
            report = smart_optimizer.optimize(bpy.context)
            print(smart_optimizer.report_text(report))
        scene.render.resolution_x, scene.render.resolution_y = options.width, options.height
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(options.output_dir, "highland_patrol.blend"))
        if options.render:
            scene.eevee.taa_render_samples = options.samples
            scene.render.image_settings.file_format = "PNG"
            scene.render.filepath = os.path.join(options.output_dir, "highland_patrol.png")
            bpy.ops.render.render(write_still=True)
    finally:
        sys.stdout.flush()
        blendengine.unregister()


if __name__ == "__main__":
    main()
