# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate Neon Relay without rendering an offline movie.

    blender -b --factory-startup --python tools/blendengine/create_playable_demo.py \
        -- --output-dir /workspace/artifacts/blendengine-playable

Open neon_relay.blend with the BlendEngine add-on enabled and press Run in its
native editor. The saved .blend has no auto-executing embedded scripts.
"""

import argparse
import json
from pathlib import Path
import sys

import bpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "scripts" / "addons_core"))
    import blendengine
    blendengine.register()
    from blendengine import demo_game, runtime
    result = demo_game.create_demo(bpy.context)
    scene = result["scene"]
    validation = runtime.validate_scene(scene)
    if not validation.ok:
        raise RuntimeError("Playable demo validation failed: " + "; ".join(validation.errors))
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.region_3d.view_perspective = "CAMERA"
                space.shading.type = "MATERIAL"
                space.shading.use_scene_lights = True
                space.shading.use_scene_world = True
                space.overlay.show_overlays = False
    path = (args.output_dir / "neon_relay.blend").resolve()
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    manifest = {
        "title": "Neon Relay", "source_blender": bpy.app.version_string,
        "engine": scene.render.engine, "controls": scene["demo_instructions"],
        "spawn": list(demo_game.SPAWN), "cores": list(demo_game.CORE_POSITIONS),
        "portal": list(demo_game.GOAL), "required_score": demo_game.GOAL_SCORE,
        "recording_waypoints": list(demo_game.RECORDING_WAYPOINTS),
        "objects": len(scene.objects),
        "triangles": sum(sum(len(p.vertices)-2 for p in obj.data.polygons)
                         for obj in scene.objects if obj.type == "MESH"),
        "asset_origin": scene["demo_asset_origin"],
        "validation_errors": validation.errors, "validation_warnings": validation.warnings,
        "runtime": "BlendEngine native editor runtime; not a standalone executable export",
    }
    (args.output_dir / "demo_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("BLENDENGINE_PLAYABLE: " + str(path))
    print("DEMO_OBJECTS: %d  DEMO_TRIANGLES: %d" % (manifest["objects"], manifest["triangles"]))


if __name__ == "__main__":
    main()
