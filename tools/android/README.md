# Native Android toolchain

Last Signal's Android project is `native/android_game`. Its APK embeds the Godot
4.6.3 C++ runtime and GLES renderer. It does not use a browser or WebView.

Install Godot 4.6.3 and a Java 17+ JDK, then run:

```sh
tools/android/setup_toolchain.sh
tools/android/build_apk.sh
```

The setup script downloads Google's command line tools 19.0, platform 36,
build tools 36.0.0, ADB, and the matching official Godot Android export templates.
It accepts the Android SDK development licenses. It needs no root or Android
Studio. Set `ANDROID_SDK_ROOT` to reuse an existing SDK, `JAVA_HOME` to select a
JDK, and `GODOT_BIN` to select Godot. Downloads default to
`~/.cache/blendengine/android`; `LASTSIGNAL_ANDROID_TOOLS` overrides this path.

The default output is `native/android_game/build/LastSignal-debug.apk`.
This development APK is debug signed. Install it on a connected Android device
or emulator using:

```sh
"$ANDROID_SDK_ROOT/platform-tools/adb" install -r native/android_game/build/LastSignal-debug.apk
"$ANDROID_SDK_ROOT/platform-tools/adb" shell am start -n org.blendengine.lastsignal/com.godot.game.GodotAppLauncher
```

The export includes native ARM64 for phones and x86_64 for emulators, requires
Android 7.0 (API 24) or later, and targets API 36. Standard APK export uses the
official prebuilt native runtime; Gradle, an NDK, and compilation of Godot are not
required.

Last Signal is a silent chapter with no audio assets or sources. Both its checked-in
Android preset and the editor-generated preset embed `--audio-driver Dummy`, so a
normal launcher start avoids opening an unused audio output stream. Godot's native
audio support remains available for future projects; remove this chapter-specific
argument when adding sound. Device acceptance tests must launch the exported APK
normally, without relying on ADB-injected audio arguments.

To test the actual APK on a booted, rootable 16:9 Android emulator, run:

```sh
python3 tools/android/qa_device.py --apk native/android_game/build/LastSignal-debug.apk --output build/android-qa
```

The tool verifies the signature, both native runtime libraries, bundled licenses
and exact installed APK SHA-256. It starts the normal launcher, sends real touch
input for movement, a quick jump tap, Inspect, Pause, Continue and Restart, and
checks that Android Back pauses without closing the process. It then starts the
same APK's developer-only scenario through Godot's internal activity and drives
the normal physics/input loop through all five clues and the grounded rescue
ending. The scenario needs emulator root because that activity is not exported;
ordinary users always enter the playable game through the launcher.

The output contains a machine-readable `device_report.json`, native runtime log,
screenshots and a screen recording. `--reuse-install` retains the shader cache
only after checking the installed APK against the requested APK's SHA-256.
Acceptance uses the normal launcher; the optional `--emulator-audio-dummy` flag
is for diagnosis and is not required by this silent chapter's preset. Software
emulator timings do not establish phone FPS, and ARM64 hardware needs a separate
device test.
