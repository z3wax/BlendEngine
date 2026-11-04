# Tested Last Signal artifacts

[Native Android APK](https://github.com/z3wax/BlendEngine/releases/download/last-signal-native-048fbac2/LastSignal-debug.apk)
and [all release downloads](https://github.com/z3wax/BlendEngine/releases/tag/last-signal-native-048fbac2).

| Artifact | Purpose |
|---|---|
| LastSignal-debug.apk | Native Godot C++ / OpenGL ES game, ARM64 + x86_64, Android 7/API 24+ |
| BlendEngine-lean-addon.zip | Blender editor addon; Blender itself is required |
| BlendEngine-lean-sdk.zip | Native game source, addon, graphics assets and export tools |
| LastSignal-Android-gameplay.mp4 | Actual Android story gameplay capture |
| LastSignal-Android.mp4 | Actual Android touch-control capture |
| LastSignal-Android-route-raw.mp4 | Original unretimed Android route recording |
| LastSignal-editor-gameplay.mp4 | Native Blender editor story recording |

The APK passed normal-launcher testing on an Android API 24 x86_64 emulator:
touch movement, quick jump, Inspect, pause/resume, Android Back, restart and a
five-clue grounded mission victory. It is development signed. Physical ARM64
hardware remains untested. Video capture uses CPU emulation and software GLES;
its frame rate is not a phone performance measurement.

APK: 63,349,156 bytes. SHA-256:
`048fbac2b1a68fefbb5f83be651b6b5b47d0351d96f1ef534296f0414ea09308`.

The addon is 959,985 bytes; the SDK is 10,797,460 bytes. Checksums and exact
package inventories accompany the downloads. These ZIPs do not include a
compiled desktop Blender executable. See [Android instructions](../docs/ANDROID.md),
[QA report](../docs/android/qa_report.json) and [lean packaging](../docs/LEAN_ENGINE.md).

The release workflow assembles the APK from verified Git blobs, checks that it
matches the installed and tested SHA-256, verifies its signature, and publishes
those exact bytes. It does not rebuild the APK. Generated APKs remain outside
the source tree; the small manifest records their immutable blob identifiers.
