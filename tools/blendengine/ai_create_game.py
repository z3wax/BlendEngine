# SPDX-License-Identifier: GPL-2.0-or-later
"""Create a playable BlendEngine game from a plain-language idea, headless.

Run from the repository root with Blender 3.6 or newer::

    blender -b --factory-startup --python tools/blendengine/ai_create_game.py -- \\
        --prompt "O'rmonda 12 ta tanga yig'adigan, bo'rilardan qochadigan o'yin" \\
        --output /tmp/forest_game.blend

or with the ``bpy`` module from PyPI::

    python tools/blendengine/ai_create_game.py --prompt "2D snow platformer" --output /tmp/snow.blend

With ``--provider auto`` (the default) the game is designed by Claude when the
``anthropic`` package and an API key (``ANTHROPIC_API_KEY``) are available,
otherwise by the offline planner. ``--spec`` rebuilds a saved spec JSON
without any planning, and ``--package`` also writes a build package.
"""

import argparse
import json
import os
from pathlib import Path
import sys

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts" / "addons_core"))

import blendengine  # noqa: E402
from blendengine import (  # noqa: E402
    ai_game_creator, ai_game_planner, ai_game_spec, export_system, properties, runtime,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Create a BlendEngine game from a description.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt", help="Game idea in any language")
    source.add_argument("--spec", help="Path to a game spec JSON to build without planning")
    parser.add_argument("--output", required=True, help="Where to save the .blend file")
    parser.add_argument("--provider", choices=("auto", "claude", "offline"), default="auto")
    parser.add_argument("--model", default=ai_game_planner.DEFAULT_MODEL)
    parser.add_argument("--effort", choices=ai_game_planner.EFFORT_LEVELS, default=ai_game_planner.DEFAULT_EFFORT)
    parser.add_argument("--platform", choices=[item[0] for item in properties.TARGET_PLATFORM_ITEMS], default="WINDOWS")
    parser.add_argument("--seed", type=int, help="Layout seed; same spec + seed gives the same level")
    parser.add_argument("--spec-out", help="Also write the final game spec JSON here")
    parser.add_argument("--package", action="store_true", help="Also write a build package next to the .blend")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    return parser.parse_args(argv)


def main():
    args = parse_args()
    blendengine.register()
    try:
        context = bpy.context
        scene = context.scene
        scene.blendengine_project.target_platform = args.platform

        if args.spec:
            with open(args.spec, encoding="utf-8") as handle:
                raw = json.load(handle)
            spec, warnings = ai_game_spec.normalize_spec(raw)
            if args.seed is not None:
                spec["seed"] = args.seed
            plan = ai_game_planner.PlanResult(spec, "spec file", warnings)
            prompt = ""
        else:
            plan = ai_game_planner.generate_spec(
                args.prompt,
                provider=args.provider.upper(),
                api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                model=args.model,
                effort=args.effort,
                platform=args.platform,
                seed=args.seed,
            )
            prompt = args.prompt

        result = ai_game_creator.apply_plan(context, scene, plan, prompt)
        spec = result["spec"]
        for warning in plan.warnings + result["warnings"]:
            print("warning:", warning)

        validation = runtime.validate_scene(scene)
        for message in validation.errors:
            print("error:", message)
        if not validation.ok:
            return 1

        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(output))
        if args.spec_out:
            Path(args.spec_out).write_text(ai_game_spec.dumps(spec), encoding="utf-8")
        if args.package:
            scene.blendengine_project.build_folder = str(output.parent / "builds")
            package = export_system.prepare_build_package(context)
            print("package:", package["package_dir"])

        print("designer:", plan.source)
        print("title:", spec["title"])
        for line in ai_game_spec.summarize(spec):
            print("  " + line)
        print("saved:", output)
        return 0
    except ai_game_planner.PlannerError as ex:
        print("error:", ex)
        return 1
    finally:
        blendengine.unregister()


if __name__ == "__main__":
    sys.exit(main())
