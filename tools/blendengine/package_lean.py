# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a deterministic, lean BlendEngine addon ZIP without deleting source.

Run without --output to inspect the manifest. A Blender executable and exported
games are deliberately separate artifacts; this script does not build either.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
ADDON = Path("scripts/addons_core/blendengine")
REQUIRED = (
    ADDON / "__init__.py",
    ADDON / "assets/last_signal_character.blend",
    ADDON / "assets/brand/logo.jpg",
    Path("COPYING"),
    Path("doc/license/GPL-license.txt"),
    Path("release/text/copyright.txt"),
    Path("release/license/THIRD-PARTY-LICENSES.txt"),
)
SDK_REQUIRED = (
    Path("native/android_game/project.godot"),
    Path("native/android_game/main.gd"),
    Path("native/android_game/main.tscn"),
    Path("native/android_game/export_presets.cfg"),
    Path("native/android_game/assets/last_signal.glb"),
    Path("native/android_game/assets/brand/logo.jpg"),
    Path("tools/blendengine/export_native_assets.py"),
)
SDK_TOOLS = (
    "tools/blendengine/export_native_assets.py",
    "tools/blendengine/create_story_game.py",
    "tools/blendengine/package_lean.py",
    "build_files/cmake/config/blendengine_game.cmake",
    "docs/LEAN_ENGINE.md",
    "docs/ANDROID.md",
    "docs/LAST_SIGNAL.md",
)
SDK_DIRECTORIES = ("tools/android", "docs/android", "docs/render", "docs/story")
SKIP_DIRECTORIES = {
    "__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".godot", ".gradle", ".kotlin",
    ".blendengine-tools", "build", "builds",
}
DATA_DIRECTORIES = {"assets", "native", "templates", "godot"}
INSTALL_README = """BlendEngine lean editor addon
============================

Install this ZIP from Blender 3.6 Preferences > Add-ons > Install, then enable
BlendEngine. The blendengine/ folder can also be placed in scripts/addons/.
Blender itself is required and is not included. No C++ executable or APK is
built by this package. Use the addon to create scenes and export a separate
native game; the native Android export requires the lean SDK's native project,
Godot and its Android toolchain. Create the SDK with the packager's --profile sdk.
For an installed addon, set BLENDENGINE_SOURCE_ROOT to the extracted SDK root
before starting Blender so the native project and asset-export tool can be found.

All game/editor modules, the portable Last Signal character, and brand assets
are included. Generated games, browser/WebView builds, downloaded model caches,
Python bytecode, backups, and the upstream C++ source tree are omitted.
Existing materials, textures, geometry and graphics settings are not modified.

COPYING, doc/license/, release/license/, release/text/copyright.txt and the
SPDX headers preserve the source's license and attribution notices. See
MANIFEST.json for the exact source paths, sizes and SHA-256 checksums.

Source: https://github.com/z3wax/BlendEngine
"""
SDK_README = """BlendEngine lean native-game SDK
===============================

Unpack this archive to a workspace. Copy scripts/addons_core/blendengine/ into
Blender 3.6's scripts/addons/ directory and enable the addon. The separate addon
profile ZIP supports installation through Blender Preferences.
If the addon is installed outside this SDK, set the BLENDENGINE_SOURCE_ROOT
environment variable to this extracted SDK directory before launching Blender.

native/android_game/ contains the native Godot Android project. Godot, Blender,
JDK, Android SDK, export templates and signing keys are external prerequisites.
tools/blendengine/export_native_assets.py exports source scene assets into the
native project. See docs/LEAN_ENGINE.md and native/android_game/ documentation.

No prebuilt editor, APK, engine binary, SDK cache, or signing key is included.
Test a native APK on Android before uploading changes or artifacts to GitHub.
The source checkout's copyright and third-party license notices are preserved.
See MANIFEST.json for every shipped file's source path and SHA-256 checksum.

Source: https://github.com/z3wax/BlendEngine
"""


def excluded(path):
    """Reject caches and editor backups, including versioned .blend1 files."""
    name = path.name.lower()
    return (
        any(part in SKIP_DIRECTORIES for part in path.parts)
        or name.endswith((".pyc", ".pyo", ".bak", ".tmp", ".swp", "~", ".apk", ".aab", ".pck",
                          ".keystore", ".jks", ".p12", ".log", ".import"))
        or name in {"local.properties", "keystore.properties", "export_credentials.cfg"}
        # glTF embeds these exact procedural bakes; keep one copy of the pixels.
        # The SDK's scene exporter can regenerate the intermediate PNG files.
        or (name.startswith(("native_color_", "native_normal_", "last_signal_native_color_",
                             "last_signal_native_normal_")) and name.endswith(".png"))
        or (".blend" in name and name.rsplit(".blend", 1)[1].isdigit())
    )


def reject_symlinks(path, boundary):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != boundary):
        raise ValueError("Release paths cannot contain symlinks: " + str(path))


def payload_paths(root, profile="addon"):
    """Use explicit entry points so a new build/cache cannot inflate releases."""
    for relative in REQUIRED + (SDK_REQUIRED if profile == "sdk" else ()):
        reject_symlinks(root / relative, root)
        if not (root / relative).is_file():
            raise ValueError("Required release input is missing: " + relative.as_posix())

    paths = {}

    def add(source, destination):
        if excluded(source.relative_to(root)):
            return
        reject_symlinks(source, root)
        if not source.resolve().is_relative_to(root):
            raise ValueError("Release input resolves outside source checkout: " + str(source))
        if not source.is_file():
            return
        if destination in paths:
            raise ValueError("Duplicate archive path: " + destination)
        paths[destination] = source

    addon_root = root / ADDON
    for source in sorted(addon_root.rglob("*")):
        relative = source.relative_to(addon_root)
        if source.suffix == ".py" or relative.parts[0] in DATA_DIRECTORIES:
            prefix = ADDON.as_posix() if profile == "sdk" else "blendengine"
            add(source, prefix + "/" + relative.as_posix())

    if profile == "sdk":
        for source in sorted((root / "native/android_game").rglob("*")):
            add(source, source.relative_to(root).as_posix())
        for relative in SDK_TOOLS:
            source = root / relative
            if not source.is_file():
                raise ValueError("Required SDK tool is missing: " + relative)
            add(source, relative)
        for relative in SDK_DIRECTORIES:
            for source in sorted((root / relative).rglob("*")):
                add(source, source.relative_to(root).as_posix())

    for directory in ("doc/license", "release/license", "docs/brand"):
        for source in sorted((root / directory).rglob("*")):
            add(source, source.relative_to(root).as_posix())
    for relative in ("COPYING", "release/text/copyright.txt"):
        add(root / relative, relative)
    return paths


def source_inventory(root, output_paths):
    """Count development inputs without Git or generated release artifacts."""
    totals = {"files": 0, "bytes": 0, "by_top_directory": {}}
    for directory, children, files in os.walk(root, followlinks=False):
        children[:] = sorted(child for child in children
                             if child != ".git" and not (Path(directory) == root and child == "dist"))
        for name in sorted(files):
            source = Path(directory) / name
            if source.is_symlink() or source.resolve() in output_paths:
                continue
            relative = source.relative_to(root)
            group = relative.parts[0] if len(relative.parts) > 1 else "(root files)"
            size = source.stat().st_size
            totals["files"] += 1
            totals["bytes"] += size
            totals["by_top_directory"][group] = totals["by_top_directory"].get(group, 0) + size
    totals["by_top_directory"] = dict(sorted(totals["by_top_directory"].items()))
    return totals


def encode_json(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def prepare_package(root, output_paths=(), profile="addon"):
    content = {}
    entries = []
    for destination, source in sorted(payload_paths(root, profile).items()):
        data = source.read_bytes()
        content[destination] = data
        entries.append({
            "path": destination,
            "source": source.relative_to(root).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    readme = (SDK_README if profile == "sdk" else INSTALL_README).encode("utf-8")
    content["README.txt"] = readme
    entries.append({
        "path": "README.txt", "source": "generated install instructions",
        "bytes": len(readme), "sha256": hashlib.sha256(readme).hexdigest(),
    })
    entries.sort(key=lambda entry: entry["path"])
    inventory = source_inventory(root, set(output_paths))
    payload_bytes = sum(entry["bytes"] for entry in entries)
    manifest = {
        "schema_version": 1,
        "profile": profile,
        "artifact_type": "Native game SDK source" if profile == "sdk" else "Blender editor addon",
        "source": "https://github.com/z3wax/BlendEngine",
        "preserved": [
            "All BlendEngine Python editor, runtime, graphics, story and export modules",
            "Portable Last Signal character and addon assets",
            "User-provided brand logo and upstream license/attribution notices",
        ],
        "omitted": [
            "Upstream C++ source, libraries and build tools (kept in source checkout)",
            "Generated platform games and browser/WebView export output",
            "Downloaded model caches, duplicate scene exports, backups and Python bytecode",
        ],
        "measurement": "Logical file bytes; excludes Git metadata, generated dist/ releases and current output ZIP/sidecar. "
                       "Addon payload does not represent a compiled editor or APK size.",
        "source_inventory": inventory,
        "payload_files": len(entries),
        "payload_bytes_excluding_manifest": payload_bytes,
        "payload_reduction_percent": round(100 * (1 - payload_bytes / inventory["bytes"]), 4),
        "files": entries,
    }
    if profile == "sdk":
        manifest["preserved"].append("Native Godot project, scene export tool, desktop build profile and instructions")
    content["MANIFEST.json"] = encode_json(manifest)
    return manifest, content


def write_package(output, manifest, content, force=False):
    sidecar = output.with_suffix(".manifest.json")
    for path in (output, sidecar):
        reject_symlinks(path, Path(path.anchor))
    if not force:
        for path in (output, sidecar):
            if path.exists():
                raise ValueError("Output already exists; choose another path or use --force: " + str(path))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(content.items()):
            # Fixed metadata makes identical inputs produce the same archive.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            mode = 0o100755 if name.endswith(".sh") or Path(name).name == "gradlew" else 0o100644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    archive_data = output.read_bytes()
    report = {
        "archive": {
            "filename": output.name,
            "bytes": len(archive_data),
            "sha256": hashlib.sha256(archive_data).hexdigest(),
        },
        "manifest": manifest,
    }
    sidecar.write_bytes(encode_json(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT, help="Source checkout (defaults to this repository)")
    parser.add_argument("--output", type=Path, help="Write the selected ZIP and a .manifest.json sidecar")
    parser.add_argument("--profile", choices=("addon", "sdk"), default="addon",
                        help="addon: Blender-installable ZIP; sdk: native project and source tools as well")
    parser.add_argument("--force", action="store_true", help="Replace an existing ZIP and sidecar")
    args = parser.parse_args()
    root = args.source.resolve()
    # Keep the final output path lexical until symlink checks have run.
    output = args.output.absolute() if args.output else None
    if output and output.suffix.lower() != ".zip":
        parser.error("--output must name a .zip file")
    outputs = tuple(path.resolve() for path in (output, output.with_suffix(".manifest.json"))) if output else ()
    try:
        if output:
            for path in (output, output.with_suffix(".manifest.json")):
                reject_symlinks(path, Path(path.anchor))
                if path.resolve().is_relative_to(root):
                    raise ValueError("Write release artifacts outside the source checkout: " + str(path))
            inputs = payload_paths(root, args.profile).values()
            if any(path.resolve() in outputs for path in inputs):
                raise ValueError("An output path would overwrite a release input")
        manifest, content = prepare_package(root, outputs, args.profile)
        if output:
            report = write_package(output, manifest, content, force=args.force)
            print(json.dumps({
                "output": str(output),
                "manifest": str(output.with_suffix(".manifest.json")),
                "source_bytes_excluding_git": manifest["source_inventory"]["bytes"],
                "payload_bytes": manifest["payload_bytes_excluding_manifest"],
                "payload_files": manifest["payload_files"],
                "payload_reduction_percent": manifest["payload_reduction_percent"],
                "archive": report["archive"],
            }, indent=2))
        else:
            sys.stdout.write(encode_json(manifest).decode("utf-8"))
    except (OSError, ValueError) as error:
        parser.exit(1, "Lean package failed: " + str(error) + "\n")


if __name__ == "__main__":
    main()
