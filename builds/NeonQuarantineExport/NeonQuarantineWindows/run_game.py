import bpy
import addon_utils

addon_utils.enable('blendengine', default_set=False, persistent=True)
bpy.context.preferences.view.show_splash = False

def _fullscreen_view3d():
    screen = bpy.context.screen
    if screen is None:
        return
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            continue
        with bpy.context.temp_override(area=area, region=region):
            try:
                bpy.ops.screen.screen_full_area(use_hide_panels=True)
            except Exception:
                pass
        break

def _start_game_only():
    from blendengine import utils
    utils.activate_engine_page(bpy.context, 'PLAY')
    def _after_workspace():
        from blendengine import utils
        utils.configure_current_screen_for_blendengine(bpy.context)
        utils.enter_camera_view(bpy.context)
        _fullscreen_view3d()
        bpy.ops.blendengine.test_run_scene()
        return None
    bpy.app.timers.register(_after_workspace, first_interval=0.35)
    return None

bpy.app.timers.register(_start_game_only, first_interval=0.10)
