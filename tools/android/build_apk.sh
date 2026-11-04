#!/usr/bin/env bash
# Build a signed development APK using the native Godot Android runtime.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_DIR="$REPO_ROOT/native/android_game"
GODOT_BIN="${GODOT_BIN:-godot}"
SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [[ -z "$SDK_ROOT" ]]; then
  if [[ -d /workspace/scratch/android/sdk ]]; then
    SDK_ROOT=/workspace/scratch/android/sdk
  else
    SDK_ROOT="${LASTSIGNAL_ANDROID_TOOLS:-${XDG_CACHE_HOME:-$HOME/.cache}/blendengine/android}/sdk"
  fi
fi
JDK_ROOT="${JAVA_HOME:-$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")}"
OUTPUT="${1:-$PROJECT_DIR/build/LastSignal-debug.apk}"
OUTPUT="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$OUTPUT")"
PRESET="${LASTSIGNAL_ANDROID_PRESET:-Android}"
[[ -x "$SDK_ROOT/platform-tools/adb" ]] || { echo "Android SDK missing; run tools/android/setup_toolchain.sh" >&2; exit 1; }
[[ -x "$JDK_ROOT/bin/keytool" ]] || { echo "A Java JDK with keytool is required." >&2; exit 1; }
[[ -f "$PROJECT_DIR/project.godot" ]] || { echo "Missing native Godot project at $PROJECT_DIR" >&2; exit 1; }
mkdir -p "$(dirname "$OUTPUT")"
DEBUG_KEYSTORE="${XDG_DATA_HOME:-$HOME/.local/share}/godot/keystores/debug.keystore"
if [[ ! -f "$DEBUG_KEYSTORE" ]]; then
  mkdir -p "$(dirname "$DEBUG_KEYSTORE")"
  "$JDK_ROOT/bin/keytool" -genkeypair -keystore "$DEBUG_KEYSTORE" \
    -storepass android -keypass android -alias androiddebugkey \
    -dname 'CN=Android Debug,O=Android,C=US' -keyalg RSA -keysize 2048 -validity 10000
  chmod 600 "$DEBUG_KEYSTORE"
fi

# Godot reads export SDK locations from editor settings, including in CLI exports.
EDITOR_VERSION="$("$GODOT_BIN" --version | cut -d. -f1-2)"
python3 - "$SDK_ROOT" "$JDK_ROOT" "$EDITOR_VERSION" "$DEBUG_KEYSTORE" <<'PY'
import json, os, pathlib, re, sys
config = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config")) / "godot"
config.mkdir(parents=True, exist_ok=True)
path = config / ("editor_settings-" + sys.argv[3] + ".tres")
text = path.read_text() if path.exists() else '[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
settings = {"export/android/android_sdk_path": sys.argv[1], "export/android/java_sdk_path": sys.argv[2],
            "export/android/debug_keystore": sys.argv[4], "export/android/debug_keystore_user": "androiddebugkey",
            "export/android/debug_keystore_pass": "android"}
for key, value in settings.items():
    line = key + " = " + json.dumps(value)
    pattern = "^" + re.escape(key) + r"\s*=.*$"
    text = re.sub(pattern, line, text, flags=re.M) if re.search(pattern, text, re.M) else text + "\n" + line + "\n"
key = "export/android/shutdown_adb_on_exit"
pattern = "^" + re.escape(key) + r"\s*=.*$"
line = key + " = false"
text = re.sub(pattern, line, text, flags=re.M) if re.search(pattern, text, re.M) else text + "\n" + line + "\n"
path.write_text(text)
PY

"$GODOT_BIN" --headless --path "$PROJECT_DIR" --import
"$GODOT_BIN" --headless --path "$PROJECT_DIR" --export-debug "$PRESET" "$OUTPUT"
"$SDK_ROOT/build-tools/36.0.0/apksigner" verify "$OUTPUT"
"$SDK_ROOT/cmdline-tools/19.0/bin/apkanalyzer" manifest application-id "$OUTPUT"
"$SDK_ROOT/cmdline-tools/19.0/bin/apkanalyzer" manifest min-sdk "$OUTPUT"
"$SDK_ROOT/cmdline-tools/19.0/bin/apkanalyzer" manifest target-sdk "$OUTPUT"
printf 'Native Android APK: %s\n' "$OUTPUT"
