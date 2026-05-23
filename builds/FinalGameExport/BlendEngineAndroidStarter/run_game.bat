@echo off
set BLENDER=%BLENDER%
if "%BLENDER%"=="" set BLENDER=blender
"%BLENDER%" "%~dp0BlendEngineAndroidStarter.blend" --python "%~dp0run_game.py"
