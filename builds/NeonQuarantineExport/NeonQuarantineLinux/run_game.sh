#!/usr/bin/env sh
set -eu
BLENDER=${BLENDER:-blender}
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$BLENDER" --window-fullscreen "$DIR/NeonQuarantineLinux.blend" --python "$DIR/run_game.py"
