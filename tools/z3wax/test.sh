#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
project="$repo/native/z3wax"
godot --headless --path "$project" --import
godot --headless --path "$project" --script tests/protocol.gd
timeout 60 godot --headless --path "$project" -- --smoke-test
timeout 60 godot --headless --path "$project" --script tests/combat.gd
