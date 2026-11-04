# Retained graphics and source scenes

This directory keeps the original Blender scene files, scene backups, city GLB
and texture assets. Their paths and bytes are preserved so existing scene
references and the legacy character-source fallback continue to work.

Obsolete generated platform packages were removed: copied desktop launchers,
serialized game-data/config manifests, Android Java/Gradle WebView wrappers,
iOS WebView scaffolds and browser players. Those exports were generated output,
not engine source. Removing 172 generated text files saves 9,933,540 logical
bytes. All 31 graphics files, including `.blend1` backups and model-cache
textures, remain available.

The maintained native Android project is
[`native/android_game`](../native/android_game/README.md). It embeds the Godot
C++ runtime and renders the game directly through OpenGL ES. See
[`docs/ANDROID.md`](../docs/ANDROID.md) to build or install the tested APK.

Open a retained `.blend` scene using the current BlendEngine addon rather than
an old generated launcher. The portable Last Signal character is also bundled
inside the addon; new Last Signal scenes do not require these old exports.

Future generated exports stay local through the repository's ignore rules.
The lean editor/SDK packager omits this directory entirely; graphics required
by the native story are shipped as its self-contained GLB and portable asset.
