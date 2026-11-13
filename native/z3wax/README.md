> **Release blocked — visual requirements not met.** The stylized field test below was rejected. The [realistic visual pass](ART_REVIEW.md) is now integrated into the playable prototype, but it does not yet meet the supplied reference or release requirements.

# Z3WAX / Disland — 0.1 field test

Original native third-person combat prototype built on BlendEngine's Godot 4.6.3 Android/iOS export pipeline. **This is an early field test, not a completed PUBG-scale game or a production anti-cheat service.**

## Play

`godot --path native/z3wax`

Start Training runs one human and seven server-simulated bots. WASD moves, mouse looks, left-click fires, Space jumps, R reloads, M opens the map, Escape releases/captures the pointer. Android/iOS provide independent move/look fingers and fire/jump/reload regions. Lobby returns to the menu. The closing perimeter damages players outside it; the last survivor wins.

The world coordinates cover 16 × 16 km. Relay Nine is the authored, playable 440 m combat sector. Other named regions are coarse terrain and map landmarks, **not completed cities, forests or airports**. A 16 km battlefield with 100 players, vehicles, parachutes, looting, squads, inventory progression and matchmaking is not implemented. The first match uses the existing small combat layout; its environmental art is still unfinished. Recorded rifle and reload sounds are included; music, full ambience and footstep audio are not.

## Assets and animation

The active operator is **DanlyVostok's Military Tactical Suit**, and the rifle is
**Firewarden3D's M4A1**, both CC BY 4.0. These are attributed artist-created meshes.
The current character/weapon are not the rejected Kenney prototype models.
Source links, modifications and licenses are in [the credits](assets/realistic/CREDITS.md).

Walk/run legs use the recorded **100STYLE** dataset (CC BY 4.0), combined with
Quaternius's authored armed upper-body clips (CC0). Blender reconstructs the
neutral bind rig and retargets nine clips, including standing/moving reloads.
The rifle follows a right-hand bone socket. This is not a claim of complete
foot IK, perfect grips, or all final combat transitions.

Blender sources are in `art_source/`; the build scripts are in `tools/z3wax/art/`.
The runtime is native Godot/OpenGL ES, not Blender EEVEE running on a phone.
The new lobby starts offline training and opens a working server connection form.
The map derives from the actual terrain and explicitly marks unfinished settlements.

## Dedicated server

```sh
Z3WAX_SERVER_TOKEN='your-shared-access-token' godot --headless --path native/z3wax -- --server
```

Open UDP **28416** on your own host. Enter its address and optional token in the client. Capacity is 16 peers; no public hosting or managed accounts are provisioned by this repository. ENet is not encrypted: the shared token is appropriate only for a trusted test network, not an Internet authentication system. Use a private VPN for access until account authentication and transport protections are added.

The server alone integrates movement, ammunition, firing cadence, physics hits, damage, zone and winner. Clients submit bounded input, never a damage or position claim. Snapshots use an independent ordered channel. `sentinel.gd` rejects nonfinite/out-of-range inputs, ignores reordered/repeated sequences without bans, limits command floods and disconnects repeated malformed senders. Evidence is a bounded in-memory ring plus `user://sentinel.jsonl`. This is protocol validation, not a kernel/process scanner or proof of comprehensive cheat prevention. Aimbots, lag compensation and account evasion need further work.

Manual bans: before starting a server, put a JSON array of banned IP addresses in its `user://bans.json`. There are no automatic permanent bans. IP addresses are not durable account identities; shared networks can share an address. Restart an ended server for the next multiplayer match; an empty server resets its round automatically.

## Optimization

Only nearby 1 km sectors have terrain/collision (3 × 3 on a single client). Servers keep the union around players. Static Blender outpost geometry is merged by material (four batches), with frustum/distance culling and bounded shadow distance. Distant lobby rocks use a 2,000-triangle LOD instead of 97,964 triangles; close rocks retain the original mesh. Off-screen operator animations stop updating. Mipmaps reduce distant texture aliasing; input texture resolution is retained. No claim of lossless performance scaling on every phone, trained AI optimizer, 100-player load stability or measured low-end phone FPS is made.

## Validate and build

```sh
bash tools/z3wax/test.sh
bash tools/android/setup_toolchain.sh
Z3WAX_PROJECT_DIR="$PWD/native/z3wax" bash tools/android/build_apk.sh "$PWD/dist/z3wax/Z3WAX-0.1.0-debug.apk"
```

APK is development-signed, Android 7+ / API24, ARM64 and x86_64. Use a private production keystore for a store release. iOS compilation runs on macOS with Xcode through `.github/workflows/z3wax-ios.yml`. The generated **unsigned ARM64 device IPA** is validated as an actual Mach-O app and Godot resource pack. It needs your Apple signing certificate/profile for normal iPhone installation. An unsigned IPA is not an App Store/TestFlight submission, and a successful build is not a physical device test.

Release evidence explicitly distinguishes desktop, emulator, simulator, and physical-device checks. Never label an untested device or a future feature as passed.
