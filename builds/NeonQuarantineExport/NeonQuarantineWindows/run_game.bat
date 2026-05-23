@echo off
set BLENDER=%BLENDER%
if "%BLENDER%"=="" set BLENDER=blender
"%BLENDER%" --window-fullscreen "%~dp0NeonQuarantineWindows.blend" --python "%~dp0run_game.py"
