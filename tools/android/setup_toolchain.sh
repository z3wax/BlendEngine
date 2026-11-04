#!/usr/bin/env bash
# Install the native Godot Android export tools, without root or Android Studio.
set -euo pipefail

TOOL_ROOT="${LASTSIGNAL_ANDROID_TOOLS:-${XDG_CACHE_HOME:-$HOME/.cache}/blendengine/android}"
SDK_ROOT="${ANDROID_SDK_ROOT:-$TOOL_ROOT/sdk}"
GODOT_VERSION="4.6.3"
TEMPLATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/godot/export_templates/$GODOT_VERSION.stable"
mkdir -p "$TOOL_ROOT/downloads" "$SDK_ROOT/cmdline-tools" "$TEMPLATE_DIR"

if [[ ! -x "$SDK_ROOT/cmdline-tools/19.0/bin/sdkmanager" ]]; then
  curl -fL --retry 3 https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip \
    -o "$TOOL_ROOT/downloads/commandline-tools-19.zip"
  python3 - "$TOOL_ROOT/downloads/commandline-tools-19.zip" "$SDK_ROOT/cmdline-tools" <<'PY'
import hashlib, pathlib, sys, zipfile
archive, root = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
assert hashlib.sha1(archive.read_bytes()).hexdigest() == "5fdcc763663eefb86a5b8879697aa6088b041e70", "SDK archive checksum mismatch"
with zipfile.ZipFile(archive) as z:
    z.extractall(root)
(root / "cmdline-tools").rename(root / "19.0")
for executable in (root / "19.0" / "bin").iterdir():
    executable.chmod(0o755)
PY
fi

# sdkmanager uses Java networking; translate the inherited HTTP proxy explicitly.
# Preserve configured TLS trust and never print proxy credentials.
python3 - "$SDK_ROOT" <<'PY'
import os, pathlib, subprocess, sys, urllib.parse
root = pathlib.Path(sys.argv[1])
args = [str(root / "cmdline-tools/19.0/bin/sdkmanager"), "--sdk_root=" + str(root)]
proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
if proxy:
    p = urllib.parse.urlparse(proxy)
    if p.username or p.password:
        raise SystemExit("sdkmanager requires a proxy without embedded credentials; configure Java networking for this environment.")
    args += ["--proxy=http", "--proxy_host=" + p.hostname, "--proxy_port=" + str(p.port or 8080)]
subprocess.run(args + ["--licenses"], input="y\n" * 100, text=True, check=True)
subprocess.run(args + ["platform-tools", "platforms;android-36", "build-tools;36.0.0"], check=True)
PY

if [[ ! -f "$TEMPLATE_DIR/android_debug.apk" || ! -f "$TEMPLATE_DIR/android_release.apk" ]]; then
  ARCHIVE="$TOOL_ROOT/downloads/Godot_v${GODOT_VERSION}-stable_export_templates.tpz"
  curl -fL --retry 3 "https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}-stable/Godot_v${GODOT_VERSION}-stable_export_templates.tpz" -o "$ARCHIVE"
  python3 - "$ARCHIVE" "$TEMPLATE_DIR" <<'PY'
import pathlib, sys, zipfile
root = pathlib.Path(sys.argv[2])
with zipfile.ZipFile(sys.argv[1]) as z:
    for name in ("android_debug.apk", "android_release.apk", "version.txt"):
        (root / name).write_bytes(z.read("templates/" + name))
PY
fi

printf 'Android SDK: %s\nGodot export templates: %s\n' "$SDK_ROOT" "$TEMPLATE_DIR"
printf 'Build with: ANDROID_SDK_ROOT=%q tools/android/build_apk.sh\n' "$SDK_ROOT"
