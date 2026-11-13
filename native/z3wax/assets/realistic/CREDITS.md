# Realistic art review — third-party credits

This art review is not the finished game. Character and weapon geometry comes from named human artists, not an image/mesh generation service.

CC BY 4.0: https://creativecommons.org/licenses/by/4.0/
CC0 1.0: https://creativecommons.org/publicdomain/zero/1.0/
Poly Haven terms: https://polyhaven.com/license

## Military tactical suit (LowPolyGameReady)

- Files: `operator_motion.glb` and `art_source/tactical.blend`
- Author: DanlyVostok
- License: CC-BY-4.0
- Original: https://sketchfab.com/3d-models/ef698ce36b1545a78ce592dd3db4c7ed
- Changes: Skin transforms baked in double precision, clean Blender rig rebuilt, optional equipment omitted, headset fitted; no AI mesh generation.

## M4A1

- Files: `rifle_real.glb`
- Author: Firewarden3D
- License: CC-BY-4.0
- Original: https://sketchfab.com/3d-models/40d8ef818c7549a896371cbb1f64fec6
- Changes: Extracted rifle meshes from attributed FP derivative; arms and their rig removed; Blender export.

## Destroyed Ford Crown Vic

- Files: `car.glb`
- Author: alexdelker
- License: CC-BY-4.0
- Original: https://sketchfab.com/3d-models/1506140c97654d759cc4c60c20d1d2a8
- Changes: Mirror version simplified and textures re-encoded.

## Bambanani Sunset

- Files: `sunset.hdr`
- Author: Dimitrios Savva, Jarod Guest / Poly Haven
- License: CC0-1.0
- Original: https://polyhaven.com/a/bambanani_sunset
- Changes: 2k HDR environment.

## Barrel 01

- Files: `barrel.glb`
- Author: Poly Haven contributors
- License: CC0-1.0
- Original: https://polyhaven.com/a/Barrel_01
- Changes: Mirror glTF derivative.

## Old Military Crate

- Files: `crate.glb`
- Author: Poly Haven contributors
- License: CC0-1.0
- Original: https://polyhaven.com/a/old_military_crate
- Changes: Mirror glTF derivative.

## Rocky Terrain 02

- Files: `ground_*.jpg`
- Author: Poly Haven contributors
- License: CC0-1.0
- Original: https://polyhaven.com/a/rocky_terrain_02
- Changes: Original 2k diffuse, OpenGL normal, roughness maps.

## Beige Wall 001

- Files: `wall_*.jpg`
- Author: Poly Haven contributors
- License: CC0-1.0
- Original: https://polyhaven.com/a/beige_wall_001
- Changes: Original 2k diffuse, OpenGL normal, roughness maps.

## Namaqualand Boulder 02

- Files: `rock/**`
- Author: Poly Haven contributors
- License: CC0-1.0
- Original: https://polyhaven.com/a/namaqualand_boulder_02
- Changes: Original 1k glTF and maps.

## Download provenance

The character, rifle, car, barrel, crate and HDR files were obtained from the CC-licensed asset copies in https://github.com/cktang88/3d-fps/tree/130ac2a5c856401ec36e7d35afcfefe40c5801f4/public/assets (its project code was not copied). Author/license data for the three Sketchfab assets was independently checked against the original Sketchfab public API. Terrain, plaster and rock files were downloaded directly from Poly Haven.

## Additional surface textures

- `RustyCorrugated_*.webp`: Poly Haven, Rusty Corrugated Iron, CC0 1.0.
  Original: https://polyhaven.com/a/rusty_corrugated_iron
- `Wood092_*.webp`: ambientCG contributors, Wood092, CC0 1.0.
  Original: https://ambientcg.com/view?id=Wood092
- The above are the re-encoded CC0 copies from the pinned mirror revision.

## Font

Barlow Condensed SemiBold, Jeremy Tribby and the Barlow Project Authors.
SIL Open Font License 1.1; see `OFL.txt`.
Source: https://github.com/google/fonts/tree/main/ofl/barlowcondensed

## Human motion and retargeted operator

`operator_motion.glb`: DanlyVostok's character (CC BY 4.0, source above), with a
reconstructed neutral bind rig, head-attached eyes and Blender-retargeted clips.

- Armed upper-body, idle, aim, jump, landing and reload clips: Quaternius,
  Universal Animation Library 1/2 (Standard), CC0. https://quaternius.com/
- Walk/run leg motion: Ian Mason, Sebastian Starke, Taku Komura, **100STYLE**,
  CC BY 4.0, https://zenodo.org/records/8127870 . Dataset authors and license were
  verified against the Zenodo record. These are recorded human-motion cycles.
- Intermediate motion/rig adaptation: the pinned `cktang88/3d-fps` asset mirror,
  `models/characters/soldier.glb`; its intermediate rig is credited to BAMEN,
  "FREE [Military Soldier] RIGGED", CC BY 4.0:
  https://sketchfab.com/3d-models/e9c56308a67d4a3db62e914fafa4d198 .
- Z3WAX changes: anatomical basis retargeting, armed upper-body/lower-body
  combination, in-place motion, grounded root height, and moving reload clips.
  This does not certify perfect foot locking, grip or all possible transitions.

## Sound

`audio/rifle_*.wav`: CC0 recordings from **The Free Firearm Sound Library**,
https://github.com/buddingmonkey/FreeFirearmsSFXLibrary . Downloaded from the
pinned mirror's `audio/guns/m4a1_world.ogg` and `audio/foley/rifle_magout.ogg`,
`rifle_magin.ogg`, then decoded to mono 44.1 kHz PCM WAV. Ogg import triggered a
Godot editor importer crash in this environment; WAV import passed.

## Distant geometry and terrain overview

`rock/distant.glb`: a 2,000-triangle geometry-only derivative of the CC0
Namaqualand Boulder 02 (97,964 original triangles). It reuses the original rock
material. This LOD is used for distant scenery, not the close rocks.

`disland_relief.png`: generated by Z3WAX from its authoritative terrain height
and biome functions. It depicts current terrain; labeled future settlements are
explicitly marked as planned. It is not a screenshot of completed cities.
