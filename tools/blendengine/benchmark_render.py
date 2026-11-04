# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure native Lit viewport cadence and export deterministic render evidence.

Run in a fresh Blender process. --addon-path selects the frozen baseline or
candidate package parent. No quality preset or Fast Preview is applied.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

import bpy


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def snapshot(scene):
    quality = {}
    for name in ('taa_samples', 'taa_render_samples', 'use_ssr', 'use_raytracing',
                 'use_bloom', 'bloom_intensity', 'use_gtao', 'gtao_distance',
                 'shadow_cube_size', 'shadow_cascade_size', 'volumetric_samples',
                 'use_soft_shadows', 'use_motion_blur'):
        if hasattr(scene.eevee, name):
            quality[name] = getattr(scene.eevee, name)
    objects = {o.name: {'location': list(o.location), 'rotation': list(o.rotation_euler),
                      'scale': list(o.scale), 'hidden': o.hide_render,
                      'mesh': digest([list(v.co) for v in o.data.vertices]) if o.type == 'MESH' else None}
               for o in scene.objects}
    materials = {}
    for mat in bpy.data.materials:
        nodes = []
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                values = {}
                for socket in node.inputs:
                    if hasattr(socket, 'default_value'):
                        value = socket.default_value
                        if isinstance(value, (float, int, bool, str)):
                            values[socket.name] = value
                        else:
                            try:
                                values[socket.name] = list(value)
                            except TypeError:
                                pass
                nodes.append((node.name, node.bl_idname, values))
        materials[mat.name] = nodes
    return {'quality': quality, 'engine': scene.render.engine,
            'resolution': [scene.render.resolution_x, scene.render.resolution_y,
                           scene.render.resolution_percentage],
            'color': [scene.view_settings.view_transform, scene.view_settings.look,
                      scene.view_settings.exposure, scene.view_settings.gamma],
            'objects': objects, 'materials': materials}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--addon-path', type=Path, required=True)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--frames', type=int, default=24)
    parser.add_argument('--render-evidence', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.addon_path.resolve()))
    import blendengine
    blendengine.register()
    from blendengine import runtime
    bpy.ops.wm.open_mainfile(filepath=str(args.scene.resolve()))
    scene = bpy.context.scene
    # The benchmark is a stationary scene, not an animation with frames removed.
    # The saved objects/lights/materials are untouched in both configurations.
    scene['blendengine_demo'] = 'STATIC_RENDER_BENCHMARK'
    session = runtime.GameSession(bpy.context)
    updates = []

    def observed(_scene, graph):
        for update in graph.updates:
            if isinstance(update.id, bpy.types.Object):
                updates.append(update.id.name)

    bpy.app.handlers.depsgraph_update_post.append(observed)
    for _ in range(5):
        session._update_player(1/60)
        session._update_camera()
        bpy.context.view_layer.update()
    updates.clear()
    for _ in range(30):
        session._update_player(1/60)
        session._update_camera()
        bpy.context.view_layer.update()
    report = {'blender': bpy.app.version_string, 'idle_object_updates': len(updates),
              'idle_updated_ids': sorted(set(updates)), 'settings': snapshot(scene),
              'settings_sha256': digest(snapshot(scene)), 'viewport_seconds': []}
    # Compare the entire player/camera trajectory, including a jump.
    path = []
    for frame in range(60):
        session.input_state = ({'W'} if frame < 30 else {'D'}) | ({'SPACE'} if frame == 8 else set())
        session._update_player(1/60)
        session._update_camera()
        bpy.context.view_layer.update()
        path.append([list(session.player.location), list(scene.camera.location), list(scene.camera.rotation_euler)])
    report['trajectory'] = path
    report['trajectory_sha256'] = digest(path)
    report['render_pose'] = snapshot(scene)
    session.input_state.clear()
    # Now measure repeated real Lit viewport draws at the same final pose.
    # Each draw has the identical workload: synchronize the stationary player
    # and camera, then redraw the next frame. Warm-up samples are discarded.
    ticks = []
    handle = None
    previous = None
    count = 0

    def finish():
        nonlocal handle
        if handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
            handle = None
        if observed in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(observed)
        if args.render_evidence:
            # Full saved render settings, including resolution and samples.
            scene.render.image_settings.file_format = 'PNG'
            scene.render.filepath = str((args.output/'reference.png').resolve())
            bpy.ops.render.render(write_still=True)
        (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        print('RENDER_BENCHMARK', str(args.output), flush=True)
        if not bpy.app.background:
            bpy.ops.wm.quit_blender()
        return None

    def submit():
        session._update_player(0.0)
        session._update_camera()
        bpy.context.view_layer.update()
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return None

    def draw():
        nonlocal previous, count
        now = time.perf_counter()
        if previous is not None and count > 6:
            ticks.append(now-previous)
        previous = now
        count += 1
        if count >= args.frames+7:
            report['viewport_seconds'] = ticks
            report['viewport_median_ms'] = statistics.median(ticks)*1000
            report['viewport_median_hz'] = 1/statistics.median(ticks)
            bpy.app.timers.register(finish, first_interval=0.01)
        else:
            bpy.app.timers.register(submit, first_interval=0.001)

    if args.gui:
        def setup():
            nonlocal handle
            if bpy.context.screen is None:
                return 0.1
            bpy.context.preferences.view.show_splash = False
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    space = area.spaces.active
                    space.shading.type = 'RENDERED'
                    space.overlay.show_overlays = False
                    space.show_gizmo = False
                    space.show_region_ui = False
                    space.region_3d.view_perspective = 'CAMERA'
            handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
            bpy.app.timers.register(submit, first_interval=2.0)
            return None
        bpy.app.timers.register(setup, first_interval=0.5)
    else:
        finish()


if __name__ == '__main__':
    main()
