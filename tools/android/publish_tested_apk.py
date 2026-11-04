#!/usr/bin/env python3
"""Reassemble the already-tested APK from verified Git blobs; never rebuild it."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
import zipfile


REPOSITORY = "z3wax/BlendEngine"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_evidence(manifest, qa):
    require(manifest.get("repository") == REPOSITORY, "Unexpected artifact repository")
    require(manifest.get("artifact") == "LastSignal-debug.apk", "Unexpected artifact filename")
    require(re.fullmatch(r"[0-9a-f]{64}", manifest.get("sha256", "")), "Invalid artifact SHA-256")
    require(type(manifest.get("bytes")) is int and manifest["bytes"] > 0, "Invalid artifact size")
    chunks = manifest.get("chunks", [])
    require(chunks and all(isinstance(c, dict) for c in chunks), "Missing APK chunks")
    for chunk in chunks:
        require(re.fullmatch(r"[0-9a-f]{40}", chunk.get("sha", "")), "Invalid Git blob SHA")
        require(type(chunk.get("bytes")) is int and 0 < chunk["bytes"] <= 16 * 1024 * 1024,
                "Invalid chunk size")
    require(sum(c["bytes"] for c in chunks) == manifest["bytes"], "Chunk sizes do not match APK size")
    require(qa.get("passed") is True and qa.get("normal_launcher") is True,
            "Normal Android launcher gameplay must pass before publication")
    require(qa.get("emulator_audio_override") is None,
            "Publication requires the normal launch without injected emulator audio arguments")
    require(qa.get("signature_verified") is True, "Android signature was not verified")
    require(qa.get("sha256") == qa.get("installed_sha256") == manifest["sha256"],
            "Manifest must identify the exact installed and tested APK")
    smoke = qa.get("native_smoke", {})
    require(smoke.get("native") is True and smoke.get("state") == "WON"
            and smoke.get("floor") is True and smoke.get("clues") == 5
            and smoke.get("jumps", 0) >= 3 and smoke.get("walked", 0) >= 25
            and smoke.get("skeleton_bones") == 11,
            "Complete native physics, character and grounded mission victory are required")
    touch = qa.get("touch", {})
    require(touch.get("pause_freezes_movement") is True
            and touch.get("android_back_pauses") is True
            and touch.get("quick_tap_jump", {}).get("jumps", 0) >= 1
            and touch.get("inspect", {}).get("event") == "inspect"
            and touch.get("restart", {}).get("clues") == 0,
            "Android touch, quick jump, pause, Back, Inspect and Restart must pass")


def git_blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def fetch_blob(repository, chunk, token):
    request = urllib.request.Request(
        "https://api.github.com/repos/%s/git/blobs/%s" % (repository, chunk["sha"]),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "BlendEngine-tested-APK",
                 "Authorization": "Bearer " + token, "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    require(result.get("sha") == chunk["sha"] and result.get("encoding") == "base64",
            "GitHub returned an unexpected blob")
    require(result.get("size") == chunk["bytes"], "GitHub blob size mismatch")
    return base64.b64decode("".join(result["content"].split()), validate=True)


def validate_native_zip(path):
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, "APK ZIP CRC failed")
        names = archive.namelist()
        require("AndroidManifest.xml" in names and "classes.dex" in names, "Missing Android application files")
        libraries = ["lib/arm64-v8a/libgodot_android.so", "lib/x86_64/libgodot_android.so"]
        for name in libraries:
            with archive.open(name) as library:
                require(library.read(4) == b"\x7fELF", "Invalid native ELF library: " + name)
        require(not any(n.lower().endswith((".html", ".htm", ".js", ".mjs"))
                        or "/web_player/" in n.lower() for n in names), "Unexpected browser game payload")
        for notice in ("GODOT_LICENSE.txt", "GODOT_COPYRIGHT.txt", "GODOT_AUTHORS.txt"):
            require(any(n.endswith("/licenses/" + notice) for n in names), "Missing " + notice)
        require(any(b"GodotGLRenderView" in archive.read(n)
                    for n in names if re.fullmatch(r"classes\d*\.dex", n)), "Missing Godot native GLES view")


def assemble(manifest, qa, output, local_chunks=None):
    validate_evidence(manifest, qa)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    require(local_chunks is not None or token, "GitHub token is required for Git blob downloads")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".assembling")
    digest = hashlib.sha256()
    try:
        with temporary.open("wb") as stream:
            for index, chunk in enumerate(manifest["chunks"]):
                data = ((Path(local_chunks) / ("chunk%02d.bin" % index)).read_bytes()
                        if local_chunks is not None else fetch_blob(manifest["repository"], chunk, token))
                require(len(data) == chunk["bytes"] and git_blob_sha(data) == chunk["sha"],
                        "Chunk %d failed size or Git object SHA verification" % index)
                stream.write(data)
                digest.update(data)
                print("Verified APK chunk %d/%d" % (index + 1, len(manifest["chunks"])), flush=True)
        require(temporary.stat().st_size == manifest["bytes"] and digest.hexdigest() == manifest["sha256"],
                "Assembled APK differs from the installed, tested APK")
        validate_native_zip(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    output.with_name(output.name + ".sha256").write_text(
        manifest["sha256"] + "  " + output.name + "\n", encoding="ascii")
    print("VERIFIED_TESTED_APK: " + manifest["sha256"], flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("dist/android/apk-parts.json"))
    parser.add_argument("--qa", type=Path, default=Path("docs/android/qa_report.json"))
    parser.add_argument("--output", type=Path, default=Path("dist/android/LastSignal-debug.apk"))
    parser.add_argument("--local-chunks", type=Path,
                        help="Read local chunkNN.bin files for offline assembly verification")
    args = parser.parse_args()
    assemble(read_json(args.manifest), read_json(args.qa), args.output, args.local_chunks)


if __name__ == "__main__":
    main()
