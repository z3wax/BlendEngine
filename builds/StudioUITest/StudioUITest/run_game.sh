#!/usr/bin/env sh
set -eu
BLENDER=${BLENDER:-blender}
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$BLENDER" "$DIR/StudioUITest.blend" --python "$DIR/run_game.py"
