# BlendEngine Game Creation Guide

BlendEngine is a beginner-friendly game editor built on top of the Blender runtime. The goal is simple: open the editor, build a world, add rules, press Play Mode, then export a package.

## Start

```bash
/home/abdulhodiy/PROJECTS/N-MOTION/build_linux/bin/blendengine
```

The first screen is a game editor, not a Blender modeling workspace. The top bar has only:

- `Studio`: dashboard, viewport, hierarchy, inspector, assets, profiler.
- `World`: terrain, lighting, physics, AI, objects, optimization markers.
- `Logic`: no-code rules, visual scripting, input, generated code preview.
- `Play Mode`: test the game through the active game camera.
- `Ship`: export desktop/mobile/web packages.

Legacy Blender pages such as Modeling, Sculpting, Shading, UV Editing, and Geometry Nodes are hidden from the main workflow.

## Starter Game

The default 3D template is `Neon Quarantine`, a cyberpunk first-person zombie shooter built from the local models in `/home/abdulhodiy/Desktop/MODELS/`:

- first-person player controller and auto Play Mode camera
- FN SCAR-style weapon attached to the camera
- first-person arms so the weapon is held in view
- zombie enemies with chase/attack AI and health
- cyberpunk city environment with procedural neon materials
- cinematic real-time EEVEE lighting
- 0MB bitmap texture budget after import cleanup
- about 144k editor-estimated triangles after automatic mesh simplification
- runtime HUD: FPS, frame time, RAM, visible objects, triangles, draw calls, texture memory
- 1GB optimization markers: streaming, camera culling, LOD, instancing, simple colliders

## Basic Controls

- Move: `W/A/S/D`
- Jump: `Space`
- Sprint: `Left Shift`
- Attack: `F` or `Left Mouse`
- Aim binding: `R` or `Right Mouse`
- Interact: `E`
- Stop Play Mode: `Esc` or `Stop`

Play Mode locks gameplay input so `W/A/S/D` and attack controls do not trigger old Blender shortcuts while the game is running.

## Making A Game

1. Open `Studio`.
2. Press `New Game` or use the starter level.
3. Select an object in the world.
4. Open the right-side `Inspector`.
5. Add components:
   - Player Controller
   - Collider
   - Health
   - NPC Behavior
   - Trigger Zone
   - Door
   - Pickup Item
6. Open `Logic`.
7. Add a no-code behavior:

```txt
Event: Player Enter Trigger
Condition: Always
Action: Show Log / Set Variable / Change Health / Open Door
```

8. Press `Play Mode`.
9. Press `Run`.
10. Watch the HUD and console. Fix warnings before exporting.

## Visual Logic Pattern

A coin can be built like this:

```txt
Object: Coin
Component: Trigger Zone
Event: On Enter Trigger
Tag: Player
Action: Show Log "Coin collected"
Action: Set Variable Score + 1
```

An enemy can be built like this:

```txt
Object: Enemy
Component: NPC Controller
Behavior: Chase Player
Detection Range: 10
Attack Range: 2
Health: 75
```

## Realtime Rendering

BlendEngine uses EEVEE for fast real-time rendering:

- ambient occlusion
- soft shadows
- bloom
- optional screen-space reflections
- Filmic color management
- scalable post-processing
- material preview in editing
- rendered camera view in Play Mode

For weak computers, keep these rules:

- Use shared materials.
- Prefer baked or static lights.
- Keep dynamic shadow casters low.
- Use LOD markers on big objects.
- Use texture streaming and world cells.
- Let dynamic resolution lower render scale when FPS drops.

For cinematic look without freezing the PC:

1. Use `Balanced` for normal computers.
2. Use `High` only after profiling.
3. Use `Cinematic` for screenshots or powerful PCs.
4. Keep `1GB Optimize` available for low-RAM targets.

## Play Mode

Play Mode automatically switches the viewport to the game camera. The HUD shows:

- FPS
- frame time in ms
- runtime RAM
- visible object count
- visible triangles
- estimated draw calls
- estimated texture memory
- score and health when available

If FPS drops:

1. Open `Profiler`.
2. Press `Analyze`.
3. Fix red/yellow messages.
4. Press `1GB`.
5. Re-test in `Play Mode`.

For `Neon Quarantine`, Play Mode should start in the first-person camera, hide the player body, keep the weapon/arms visible, and let `Left Mouse` or `F` damage zombies. Three shots kill the first test zombie and update `Ammo`, `Kills`, and `Score` in the HUD.

## Export

Open `Ship`, choose a platform, then press `Build`.

Desktop targets:

- Windows: `run_game.bat`
- Linux: `run_game.sh`
- macOS: `run_game.command`

These run the exported `.blend` through BlendEngine/Blender.

Web target:

- `web_player/index.html`
- `web_player/player.js`
- `web_player/game_data.json`

Android target:

- `android_project/`
- `build_android_apk.sh`
- WebView player assets
- exported `game_data.json`

APK creation requires Android Studio/SDK and Gradle.

iOS target:

- `ios_project/`
- SwiftUI/WebKit player source
- exported `game_data.json`
- `build_ios_ipa.sh` instruction script

IPA creation requires macOS, Xcode, Apple signing, and an iOS app target.

BlendEngine does not fake APK/IPA files. If the native SDK/signing toolchain is missing, the export gives a build-ready project and clear build script instead of producing a broken fake app.

## Package Contents

Every export includes:

- `game_data.json`
- `platform_config.json`
- `manifest.json`
- `README.txt`

Desktop exports also include:

- `.blend` playable project
- game-only launchers: `run_game.sh`, `run_game.bat`, `run_game.command`

Mobile/Web exports do not include `.blend`; they include generated player projects/scaffolds so the game opens as a game player instead of the editor UI.

## Optimization Checklist

Before shipping:

- Target FPS is realistic for the platform.
- Runtime RAM is below budget.
- Draw calls are below budget.
- Texture memory is below budget.
- Heavy meshes have LOD markers.
- Static objects are marked static.
- Repeated props are instancing candidates.
- Colliders are simple.
- Only visible camera area is streamed at runtime.
- Behind-camera objects can unload.
- Mobile/Web targets use 1GB mode.

## Recommended Workflow

```txt
Create -> Build scene -> Add components -> Add logic
-> Play Mode -> Analyze -> Optimize -> Export
```

Repeat that loop until Play Mode feels smooth.
