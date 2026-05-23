Neon Quarantine

Desktop run:
  Linux:   ./run_game.sh
  Windows: run_game.bat
  macOS:   ./run_game.command

Mobile/Web exports open through the generated player project, not the editor UI.

Controls:
  W/A/S/D move, Space jump, Shift sprint, F or Left Mouse attack, R or Right Mouse aim, E interact, Esc stop.

Platform export:
  Web target writes web_player/index.html.
  Android target writes android_project/build_android_apk.sh for Android Studio/SDK.
  iOS target writes ios_project files for Xcode signing/archive.

Optimization:
  This package includes editor_tools, multiplayer, runtime_optimization, and performance_budget data.
