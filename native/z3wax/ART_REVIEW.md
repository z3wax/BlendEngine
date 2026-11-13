# Realistic visual pass — development build

The rejected stylized prototype has been replaced in the main client with an
artist-authored tactical operator and rifle, retargeted human motion, PBR terrain,
a sunset environment and a reference-based lobby layout. Start Training and
Connect to Server operate the actual existing game. The separate `art_review.tscn`
remains available for art inspection; it is not a standalone finished game.

The current result is **not 1:1 with the supplied references**. The publish workflow
remains disabled and the existing release remains a draft.

## Ubuntu

From the repository root, with Godot 4.6.3 installed:

```sh
godot --headless --path native/z3wax --editor --import
godot --path native/z3wax
```

The Ubuntu preview ZIP bundles the runtime; use `./play-on-pc.sh`. For a local
server, use `./start-server.sh` in another terminal, then Connect to Server with
`127.0.0.1`. This is a development preview, not a production release.

## Art and motion pipeline

Full author credits, licenses and modifications are in
[assets/realistic/CREDITS.md](assets/realistic/CREDITS.md). The character, rifle and
car licenses were independently checked using the original Sketchfab public API;
100STYLE authors/license were checked using the Zenodo record.

The original character uses million-unit mesh coordinates and tiny skin scales.
`normalize_tactical.py` recovers the neutral bind pose from inverse skin matrices
in double precision, rebuilds a clean Blender rig, and attaches the eye mesh to
the head. Retargeting a saved display pose as if it were the bind pose was incorrect.

`retarget_motion.py` maps anatomical directions and basis offsets, combines recorded
walk/run legs with authored armed upper-body motion, adjusts the root to the floor,
and bakes nine clips. Moving reload variants retain locomotion. The game synchronizes
reload clip progress to its authoritative 1.8-second reload timer.

`extract_rifle.py` exports only rifle meshes from the attributed mirrored FP model
after meshopt decompression; first-person arms and import helper geometry are removed.
`build_rock_lod.py` produces a distant geometry-only LOD sharing the original material.
`bake_map.gd` produces the relief texture from `world.gd`, not from invented city imagery.

Blender 4.3.2 source files are in `art_source/`, excluded from runtime import/export.
Original inputs can be fetched with `tools/z3wax/art/fetch_sources.py`.

## Verification and remaining work

Headless checks cover protocol/combat, movement/jump/reload, finite animation poses,
limb scale and the weapon bone attachment. Native render checks exercise the real
lobby → training → lobby transition and capture actual viewports. A recorded movie
uses fixed simulation steps; its encoded frame rate is not phone-performance evidence.

Still unfinished:

- Repository Cycles renderer integration. Current screenshots/runtime use Godot Compatibility rasterization; they are not Cycles renders.

- Exact reference character, exposed face/helmet/camouflage, vehicles, weapon designs,
  lighting and environment detail; grip/foot/contact polish for all transitions.
- Detailed 16 × 16 km Disland settlements, forests, airports, traversal and content.
- Loot, squads, vehicles, parachuting, full inventory/progression and public matchmaking.
- Trained AI optimizer and verified low-end physical-phone performance.
- Android emulator shader/black-frame failures; physical Android/iOS validation.
- Apple signing/provisioning for an installable IPA.
- Private server repository creation/access and production account/anti-cheat systems.

The gameplay sector is still sparse. A green code test or a better screenshot does
not establish reference fidelity or release readiness.
