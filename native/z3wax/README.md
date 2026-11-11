# Z3WAX / Disland — 0.1 field test

Original native third-person combat prototype built on BlendEngine's Godot 4.6.3 Android/iOS export pipeline. **This is an early field test, not a completed PUBG-scale game or a production anti-cheat service.**

## Play

`godot --path native/z3wax`

Start Training runs one human and seven server-simulated bots. WASD moves, mouse looks, left-click fires, Space jumps, R reloads, M opens the map, Escape releases/captures the pointer. Android/iOS provide independent move/look fingers and fire/jump/reload regions. Lobby returns to the menu. The closing perimeter damages players outside it; the last survivor wins.

The world coordinates cover 16 × 16 km. Relay Nine is the authored, playable 440 m combat sector. Other named regions are coarse terrain and map landmarks, **not completed cities, forests or airports**. A 16 km battlefield with 100 players, vehicles, parachutes, looting, squads, inventory progression and matchmaking is not implemented. The first match intentionally uses the small finished combat sector.

## Assets and animation

Kenney's Animated Characters Protagonists and Blaster Kit are CC0. Character/weapon meshes and idle/run/jump skeletal clips are artist-made source assets, not AI-generated characters. The character is stylized; animation blending does not constitute motion capture, realistic tactical gun handling, foot IK or a complete combat animation set. Original source links and file hashes are in `assets/provenance.json`; licenses ship with the game.

`builds/Z3WAX/character.blend` (packed skin texture) and `disland_outpost.blend` are the Blender source scenes. `tools/z3wax/build_assets.py` imports the Kenney FBXs and exports GLBs. The runtime is native Godot/OpenGL ES, **not Blender EEVEE running on a phone**.

## Dedicated server

```sh
Z3WAX_SERVER_TOKEN='your-shared-access-token' godot --headless --path native/z3wax -- --server
```

Open UDP **28416** on your own host. Enter its address and optional token in the client. Capacity is 16 peers; no public hosting or managed accounts are provisioned by this repository. ENet is not encrypted: the shared token is appropriate only for a trusted test network, not an Internet authentication system. Use a private VPN for access until account authentication and transport protections are added.

The server alone integrates movement, ammunition, firing cadence, physics hits, damage, zone and winner. Clients submit bounded input, never a damage or position claim. Snapshots use an independent ordered channel. `sentinel.gd` rejects nonfinite/out-of-range inputs, ignores reordered/repeated sequences without bans, limits command floods and disconnects repeated malformed senders. Evidence is a bounded in-memory ring plus `user://sentinel.jsonl`. This is protocol validation, not a kernel/process scanner or proof of comprehensive cheat prevention. Aimbots, lag compensation and account evasion need further work.

Manual bans: before starting a server, put a JSON array of banned IP addresses in its `user://bans.json`. There are no automatic permanent bans. IP addresses are not durable account identities; shared networks can share an address. Restart an ended server for the next multiplayer match; an empty server resets its round automatically.

## Optimization

Only nearby 1 km sectors have terrain/collision (3 × 3 on a single client). Servers keep the union around players. Static Blender outpost geometry is merged by material (four batches), with frustum/distance culling and bounded shadow distance. Textures are kept at source resolution. No claim of lossless performance scaling on every phone, trained AI optimizer, 100-player load stability or measured low-end phone FPS is made.

## Validate and build

```sh
bash tools/z3wax/test.sh
bash tools/android/setup_toolchain.sh
Z3WAX_PROJECT_DIR="$PWD/native/z3wax" bash tools/android/build_apk.sh "$PWD/dist/z3wax/Z3WAX-0.1.0-debug.apk"
```

APK is development-signed, Android 7+ / API24, ARM64 and x86_64. Use a private production keystore for a store release. iOS compilation runs on macOS with Xcode through `.github/workflows/z3wax-ios.yml`. The generated **unsigned ARM64 device IPA** is validated as an actual Mach-O app and Godot resource pack. It needs your Apple signing certificate/profile for normal iPhone installation. An unsigned IPA is not an App Store/TestFlight submission, and a successful build is not a physical device test.

Release evidence explicitly distinguishes desktop, emulator, simulator, and physical-device checks. Never label an untested device or a future feature as passed.
