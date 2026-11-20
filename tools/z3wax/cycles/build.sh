#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
build_dir="${1:-$repo_dir/../cycles-game-build}"
cmake -S "$repo_dir" -B "$build_dir" -G Ninja \
  -C "$repo_dir/native/cycles/cpu_baseline.cmake" -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_dir" --target cycles cycles_game_worker -j "${CYCLES_BUILD_JOBS:-2}"
printf 'Built repository Cycles host: %s/bin/cycles_game_worker\n' "$build_dir"
