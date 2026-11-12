# Z3WAX / Disland 0.1.0 — native field test

A playable original third-person combat prototype, with source Blender scenes and native Godot mobile exports. This is a **prerelease**, not a production-ready 100-player battle royale.

- Local training against seven bots; walk, jump, shoot, reload, shrinking perimeter and last-survivor result.
- Dedicated ENet UDP server, up to 16 connections; server-controlled movement, damage and ammunition. No public server is provisioned.
- Sentinel rejects invalid commands and records evidence; persistent IP bans are administrator-managed. It is not a comprehensive anti-cheat or account service.
- 16 × 16 km world coordinates with streamed terrain. The authored combat area is Relay Nine (440 m diameter). Named outer regions are not yet fully built.
- Kenney CC0 character, original skeletal clips and weapons. Animation is retargeted in Blender and blends idle/run/jump; the art is stylized, not photorealistic.
- Android APK is development-signed. The ARM64 iOS IPA is **unsigned** and needs Apple provisioning/signing for normal installation.

Desktop checks cover movement/jump/grounding/reload, hits and wall occlusion, cadence/ammo, winner resolution, two simultaneous network clients and actual skeletal pose changes. Platform-specific test evidence is attached separately; build success alone does not establish phone compatibility. Physical ARM64 Android and physical iPhone testing have not been performed. No claim of a flawless release, realistic tactical animation set, low-end-phone performance, complete 16 km content or production multiplayer security is made.

The Blender archive contains source scenes, their export script and licenses. The LAN server package is distributed separately. There is currently no music/SFX, account progression, squads, loot/inventory system, vehicles or matchmaking.
