# Last Signal — native Android story chapter

This is a Godot 4.6.3 native 3D game. Android runs the Godot C++ engine with OpenGL ES rendering, a skinned human, `CharacterBody3D` physics and Godot UI. Gameplay renders directly in Godot, without a browser or WebView host, JavaScript game, web server or network dependency.

Maya arrives at an abandoned mountain relay after a storm. Recover five field components, follow Eli's recordings, and reach the transmitter to bring the rescue beacon online.

## Play

Use the on-screen direction pad, **JUMP** and **INSPECT**. The direction pad and jump accept simultaneous fingers. Desktop controls are **WASD/arrows**, **Space**, **E**, **Shift** to run, **Esc** to pause, and **R** to restart. Jump onto the raised terminal platform at the end of the path.

Pause and Android Back save the chapter checkpoint. Collected clues also save automatically. Restart clears progress. Saves stay in the application's private storage and load on its next launch.

This chapter has no sound assets or audio sources. Its Android preset starts with `--audio-driver Dummy`, avoiding an unused output stream. The native engine's audio support remains available for future projects; remove this chapter-specific argument when adding sound.

## Source and rendering

`assets/last_signal.glb` comes from the original Blender Last Signal scene, including Maya's existing human geometry, skinning, idle/walk animation, outpost, clues and mountains. The source scene uses Z-up; glTF uses Y-up. Source `(x,y,z)` maps to Godot `(x,z,-y)`.

Godot supplies native collision, follow camera, touch controls and story state. The original controller's node path is preserved when it becomes a `CharacterBody3D`, keeping glTF animation tracks valid. Ground and architecture use triangle collision; grass and small supply crates form a decorative batch. Maya uses a capsule and actual gravity/jump velocity.

The Android translation keeps PBR materials, warm directional shadows and a blue dawn sky. Blender procedural materials are baked for glTF. The GLB embeds the color and tangent-space normal atlases; exact duplicate image bytes share one payload without texture recompression. Godot regenerates `last_signal_native_*.png` import dependencies from this portable GLB. Loose bake atlases are removed after export. Godot's Compatibility renderer uses different lighting, tone mapping and atmospheric effects from Blender EEVEE, so pixel-identical EEVEE output is not claimed. This choice supports lightweight native OpenGL ES devices and software Android emulators.

## Build

Install Godot 4.6.3, its Android export templates, JDK 21 and the Android SDK. Configure the SDK and JDK paths in Godot's editor settings. The Android preset includes ARM64 and x86-64, targets the template's Android SDK version and supports Android 7/API 24 onward.

```sh
godot --headless --path native/android_game --editor --quit
godot --headless --path native/android_game --export-debug Android build/LastSignal-debug.apk
godot --headless --path native/android_game --export-release Android build/LastSignal.apk
```

Godot and its upstream third-party attribution notices are included under `assets/licenses/` and retained in the APK. Use your own signing keystore before distributing a production release. The BlendEngine editor's Android export prepares this project and invokes the same native build path.

## Validate

```sh
bash native/android_game/tests/smoke.sh
```

The smoke scenario drives real input actions through the normal physics loop, walks the clue route, jumps, pauses for multiple frames, restarts, checks persisted checkpoint data and reaches the rescue ending. A successful process prints `LAST_SIGNAL_SMOKE_PASS` and exits zero. It never substitutes a UI-only scene or teleports between route waypoints.

Runtime `LAST_SIGNAL_STATE` JSON messages and `user://qa_state.json` expose scene position, floor contact, distance walked, jump count, skeleton bones, active animation and story state for Android QA. Default launches always start the playable game; the automated scenario only runs with `-- --smoke-test`.

Desktop smoke tests complement installing and testing the actual Android APK with ADB. APK device testing and screenshots must be completed before publishing a build.
