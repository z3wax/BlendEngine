#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
output_dir="${1:?Usage: package_ubuntu.sh OUTPUT_DIRECTORY GODOT_BINARY}"
godot_binary="${2:?Pass the official Linux x86_64 Godot 4.6.3 binary}"
mkdir -p "$output_dir/runtime" "$output_dir/licenses"
cp "$godot_binary" "$output_dir/runtime/godot"
chmod +x "$output_dir/runtime/godot"
"$godot_binary" --headless --path "$repo_dir/native/z3wax" --export-pack 'Ubuntu Preview' "$output_dir/Disland.pck"
Z3WAX_PACKAGE_DIR="$output_dir" "$godot_binary" --headless --path "$repo_dir/native/z3wax" --script "$repo_dir/tools/z3wax/realtime/export_licenses.gd"
cp "$repo_dir/doc/license/GPL-license.txt" "$output_dir/licenses/GPL-license.txt"
cp "$repo_dir/native/z3wax/assets/realistic/CREDITS.md" "$output_dir/licenses/ASSETS.md"
cp "$repo_dir/native/z3wax/assets/realistic/OFL.txt" "$output_dir/licenses/OFL.txt"
cp -R "$repo_dir/native/z3wax/assets/licenses" "$output_dir/licenses/legacy-assets"
cp "$repo_dir/tools/z3wax/realtime/README-UZ.txt" "$output_dir/README-UZ.txt"
cat > "$output_dir/play.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec ./runtime/godot --main-pack "$PWD/Disland.pck" "$@"
SH
cat > "$output_dir/play-speed.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export Z3WAX_RENDER_PROFILE=speed
exec ./runtime/godot --main-pack "$PWD/Disland.pck" "$@"
SH
cat > "$output_dir/server.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo 'Z3WAX server: UDP 28416'
hostname -I || true
exec ./runtime/godot --headless --main-pack "$PWD/Disland.pck" -- --server
SH
chmod +x "$output_dir/"*.sh
