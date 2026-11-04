#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
godot --headless --path "$project_dir" --editor --quit
godot --headless --fixed-fps 120 --path "$project_dir" -- --smoke-test
