# Blender core UI migration

The editor controls now live in Blender source, independent of the old
`blendengine` add-on and of the selected application template:

- `source/blender/editors/screen/screen_ops.c` registers the C operator
  `screen.realtime_view`. It switches visible 3D viewports in the current window
  between Eevee material preview and solid shading, through the RNA update path.
  It does not change render engine, resolution, geometry or texture assets.
  With no visible 3D viewport it is unavailable. Workbench material preview is
  rejected with a warning rather than silently changing the scene engine.
- `scripts/startup/bl_ui/space_topbar.py` provides the built-in Realtime menu.
  File/Edit/Render/Window/Help, workspace tabs, Back to Previous, scene/view layer
  selection and error/job banners remain accessible with saved BlendEngine
  template preferences. Animation playback is explicitly labelled as animation.
- The old BlendEngine template is a compatibility entry only. It no longer
  enables the add-on, locks input, changes the theme or inserts a demo scene.
  Existing saved files are not converted or deleted. Legacy add-on-specific
  gameplay/export functions are not migrated by this change; their misleading
  Run/Ship controls are removed from the native top bar.

This is a native editor change, **not a completed native game runtime**. The
playable Z3WAX prototype still runs in Godot. Cycles is still the separate
experimental worker. This change does not make Cycles run at game frame rates,
produce APK/IPA exports, or achieve reference-image fidelity.

## Build and validate

Build this Blender 3.6 fork using its normal desktop dependencies and CMake
instructions in `doc/build_systems/cmake.rst`. The optional game feature profile
is `build_files/cmake/config/blendengine_game.cmake`. Copying Python UI files
into stock Blender will not install the new C operator; rebuild the executable.

Run with the compiled fork:

```sh
/path/to/fork/blender --background --factory-startup --python-exit-code 1 \
  --python tests/python/blendengine_native_ui.py
```

This checks native registration, shading changes, scene-setting preservation,
Workbench rejection and the no-viewport poll, as well as the UI regressions.
A missing C operator fails this test.

For the narrower Python UI regression check on an upstream binary:

```sh
blender --background --factory-startup --python-exit-code 1 \
  --python tests/python/blendengine_native_ui.py -- --ui-only
```

Validation performed here: the UI-only check passed on Blender 4.3.2 with no
BlendEngine add-on enabled. The modified Blender 3.6 executable has **not** been
built or run. A standalone C syntax attempt stops at the absent build-generated
`RNA_prototypes.h`; it is not a successful compile check. Native runtime testing
and visual review of a compiled fork remain required before a binary release.
