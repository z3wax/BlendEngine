# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure deterministic game-logic cost, without rendering or FPS claims.

    blender -b --factory-startup --python-exit-code 1 \
      --python tools/blendengine/benchmark_runtime.py -- --output report.json

The same generated playable scene and input sequence are used before and after
optimization. Logic timings exclude scene construction and explicit dependency
graph updates. They are neither GPU timings nor rendered frame rates.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

import bpy


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "addons_core"))

import blendengine
from blendengine import components, runtime, utils


def cube_mesh(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(-.5, -.5, -.5), (-.5, -.5, .5), (-.5, .5, -.5), (-.5, .5, .5),
         (.5, -.5, -.5), (.5, -.5, .5), (.5, .5, -.5), (.5, .5, .5)],
        [], [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
             (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)],
    )
    mesh.update()
    return mesh


def spawn(scene, name, mesh, location, scale=(1, 1, 1)):
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.location = location
    obj.scale = scale
    return obj


def build_scene(objects):
    scene = bpy.data.scenes.new("Runtime benchmark arena")
    bpy.context.window.scene = scene
    project = scene.blendengine_project
    project.game_title = "Runtime benchmark arena"
    project.show_logs = False
    scene.blendengine_optimization.camera_frustum_generation = False
    scene.blendengine_optimization.hide_behind_camera = False
    mesh = cube_mesh("Shared benchmark cube")
    ground = spawn(scene, "Ground", mesh, (0, 0, -.5), (100, 100, 1))
    utils.mark_game_object(ground, tag="Ground")
    player = spawn(scene, "Player", mesh, (0, 0, .9), (.7, .7, 1.8))
    components.add_player_controller(player)
    components.add_collider(player, tag="Player")
    controller = player.blendengine_object.player_controller
    controller.walk_speed = 4
    components.add_health(player, max_health=100)
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Benchmark camera"))
    scene.collection.objects.link(camera)
    camera.location = (0, -6, 4)
    scene.camera = camera
    controller.camera_follow = camera
    utils.ensure_default_input_bindings(scene)

    for index in range(objects):
        # Spatially sparse static obstacles, as in the engine's generated city.
        x = (index % 24) * 3.2 - 38
        y = (index // 24) * 3.2 + 9
        obj = spawn(scene, "Obstacle %04d" % index, mesh, (x, y, .5))
        components.add_collider(obj, tag="Obstacle")
        obj.blendengine_object.optimization.static_object = True

    for index in range(4):
        npc = spawn(scene, "Patrol %d" % index, mesh, (index * 3 - 4.5, 5, .6), (.8, .8, 1.2))
        components.add_npc_behavior(npc, template="PATROL")
        npc.blendengine_object.npc_behavior.patrol_radius = 1.5
        components.add_collider(npc, tag="NPC")
    for index in range(3):
        trigger = spawn(scene, "Route trigger %d" % index, mesh, (0, index * 3 + 1, .8), (2, 2, 1.6))
        components.add_trigger_zone(trigger)
        variable = trigger.blendengine_object.variables.add()
        variable.name = "Entered"
        variable.variable_type = 'INT'
        variable.int_value = 0
        behavior = trigger.blendengine_object.behaviors.add()
        behavior.name = "Remember player entry"
        event = behavior.events.add()
        event.event_type = 'ON_ENTER_TRIGGER'
        event.tag = 'Player'
        action = behavior.actions.add()
        action.action_type = 'SET_VARIABLE'
        action.variable_name = "Entered"
        action.number_value = 1
    bpy.context.view_layer.update()
    return scene, player


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def input_for_frame(frame):
    # Repeatable movement, sprint, jump and releases through a real session.
    keys = {'W'} if frame < 120 else ({'D'} if frame < 180 else set())
    if 35 <= frame < 65:
        keys.add('LEFT_SHIFT')
    if frame in {20, 95}:
        keys.add('SPACE')
    return keys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--objects", type=int, default=384)
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--label", default="runtime")
    parser.add_argument("--compare", type=Path, help="Compare timings and gameplay outcome with an earlier report")
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    if args.frames < 1 or args.objects < 0 or args.warmup < 0:
        parser.error("frames must be positive; objects and warmup must be non-negative")
    source_hash = hashlib.sha256(Path(runtime.__file__).read_bytes()).hexdigest()
    blendengine.register()
    scene, player = build_scene(args.objects)
    session = runtime.GameSession(bpy.context)
    print("RUNTIME_BENCHMARK_LOADED", source_hash, flush=True)
    timings = []
    for frame in range(args.frames + args.warmup):
        session.input_state = input_for_frame(frame)
        start = time.perf_counter()
        session.step(1 / 60)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if frame >= args.warmup:
            timings.append(elapsed_ms)
    colliders = sum(1 for obj in scene.objects if runtime._component_enabled(obj, 'COLLIDER'))
    report = {
        "label": args.label,
        "blender_version": bpy.app.version_string,
        "runtime_source_sha256": source_hash,
        "measurement": "GameSession.step CPU logic time; no rendering, not rendered FPS",
        "scene": {"objects": len(scene.objects), "colliders": colliders,
                  "exhaustive_collider_pairs": colliders * (colliders - 1) // 2,
                  "npc_count": 4, "trigger_count": 3},
        "sample_frames": len(timings),
        "warmup_frames": args.warmup,
        "simulation_dt_seconds": 1 / 60,
        "logic_ms": {"median": statistics.median(timings),
                     "mean": statistics.mean(timings),
                     "p95": percentile(timings, .95),
                     "max": max(timings)},
        "outcome": {
            "player_location": [round(value, 6) for value in player.location],
            "player_health": player.blendengine_object.health.current_health,
            "trigger_entries": {obj.name: obj.blendengine_object.variables['Entered'].int_value
                                for obj in scene.objects if obj.name.startswith("Route trigger")},
            "active_collision_pairs": sorted([list(pair) for pair in session._collision_overlaps]),
            "stop_requested": session.stop_requested,
        },
    }
    counters = getattr(session, "_runtime_stats", None)
    if counters is not None:
        report["runtime_counters"] = dict(counters)
    if args.compare:
        baseline = json.loads(args.compare.read_text())
        same_configuration = all(
            baseline[key] == report[key]
            for key in ("blender_version", "scene", "sample_frames", "warmup_frames", "simulation_dt_seconds")
        )
        report["comparison"] = {
            "baseline_file": str(args.compare),
            "same_configuration": same_configuration,
            "same_gameplay_outcome": baseline["outcome"] == report["outcome"],
            "logic_median_speedup": baseline["logic_ms"]["median"] / report["logic_ms"]["median"],
            "logic_p95_speedup": baseline["logic_ms"]["p95"] / report["logic_ms"]["p95"],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("RUNTIME_BENCHMARK_RESULT " + json.dumps(report), flush=True)
    blendengine.unregister()
    if args.compare and not all(report["comparison"][key] for key in ("same_configuration", "same_gameplay_outcome")):
        raise RuntimeError("The benchmark configuration or gameplay outcome differs from the baseline")


if __name__ == '__main__':
    main()
