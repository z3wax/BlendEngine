# Native unsigned iOS IPA

The game is the same native Godot C++ project as Android, including the human
Rescue Scout, skinning, physics and local AI. No WebView or browser player is
used. The iOS build keeps Compatibility/OpenGL ES 3: Godot 4.6.3 explicitly
disables Metal/Vulkan for its iOS Simulator libraries. Texture, material,
shadow, MSAA and scene settings are preserved.

Build on macOS with Xcode installed and its license accepted:

```sh
tools/ios/setup_toolchain.sh
python3 tools/ios/build_ios.py --project native/android_game \
  --godot "$HOME/Library/Caches/BlendEngine/ios/Godot.app/Contents/MacOS/Godot" \
  --output /tmp/LastSignal-AI-unsigned.ipa --qa
```

Godot 4.6.3 editor/template downloads are pinned to official archive SHA-256s.
The project is copied to a temporary directory; Android presets and assets
are not overwritten. Godot generates an Xcode project without archiving or
signing. The `0000000000` Team ID is an explicitly non-signing placeholder
required by Godot's project generator, then cleared for Xcode. The device app
is compiled for iOS ARM64 with signing disabled. Any linker ad-hoc signature
is removed before the real Mach-O application is packaged as `Payload/*.app`.

**The resulting IPA is unsigned and cannot be installed on a stock iPhone
until it is signed with an appropriate Apple identity/provisioning profile.**
No Apple certificate, password, paid account or private key is used by this
pipeline. The separately built simulator application is locally ad-hoc signed
only so it can execute on the simulator; that is not an iPhone signature.

`--qa` boots an iOS Simulator, verifies a normal native launch, observes the
Scout's independent movement/bones without moving the idle player, captures
PNG/video, runs the complete five-clue physical story route, then runs the
wall-detour/NPC/checkpoint test. It does not claim UIKit touch automation or
physical-device testing. Reports, build logs and SHA-256 accompany the IPA.

The GitHub workflow publishes only after the device IPA structure and actual
simulator scenarios pass. It also provides the simulator app ZIP for testing
on a Mac. Source tools can be prepared on Linux, but Xcode compilation and
iOS Simulator execution require macOS.
