#!/usr/bin/env sh
set -eu
BLENDER=${BLENDER:-/Applications/BlendEngine.app/Contents/MacOS/blender}
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$BLENDER" "$DIR/BlendEngineWebStarter.blend" --python "$DIR/run_game.py"
