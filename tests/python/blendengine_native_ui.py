# SPDX-License-Identifier: GPL-2.0-or-later
"""Run with the fork binary --background --factory-startup --python this_file.

Use -- --ui-only on an upstream Blender to check UI logic, not the C operator.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import bpy

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Layout:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self if name in {'row', 'column'} else NS()
        return call


def draw(cls, context, method='draw'):
    layout = Layout()
    getattr(cls, method)(NS(layout=layout), context)
    assert not any(args and str(args[0]).startswith('blendengine.')
                   for _, args, _ in layout.calls), layout.calls
    return layout.calls


topbar = load('native_topbar', 'scripts/startup/bl_ui/space_topbar.py')
template = load('native_template', 'scripts/startup/bl_app_templates_system/BlendEngine/__init__.py')
# Opening or closing the compatibility template must not mutate users' work.
before = (tuple(bpy.data.objects), tuple(bpy.context.preferences.addons.keys()),
          tuple(bpy.data.workspaces), tuple(bpy.app.handlers.load_post))
template.register()
template.register()
template.unregister()
after = (tuple(bpy.data.objects), tuple(bpy.context.preferences.addons.keys()),
         tuple(bpy.data.workspaces), tuple(bpy.app.handlers.load_post))
assert before == after

# Draw the actual core UI methods with an add-on-free context. Both normal and
# saved BlendEngine preferences must retain menus, workspace access and reports.
for name in ('', 'BlendEngine'):
    context = NS(preferences=NS(app_template=name), area=NS(show_menus=True),
                 screen=NS(show_fullscreen=False, show_statusbar=False),
                 window=NS(scene=NS()))
    calls = draw(topbar.TOPBAR_MT_editor_menus, context)
    for menu in ('file', 'edit', 'render', 'realtime', 'window', 'help'):
        assert any(args == ('TOPBAR_MT_' + menu,) for _, args, _ in calls)
    topbar.TOPBAR_MT_editor_menus.draw_collapsible = staticmethod(lambda c, l: None)
    calls = draw(topbar.TOPBAR_HT_upper_bar, context, 'draw_left')
    assert any(kind == 'template_ID_tabs' for kind, _, _ in calls)
    context.screen.show_fullscreen = True
    calls = draw(topbar.TOPBAR_HT_upper_bar, context, 'draw_left')
    assert any(args == ('screen.back_to_previous',) for _, args, _ in calls)
    calls = draw(topbar.TOPBAR_HT_upper_bar, context, 'draw_right')
    assert any(kind == 'template_reports_banner' for kind, _, _ in calls)
    assert any(kind == 'template_running_jobs' for kind, _, _ in calls)
    assert any(kind == 'template_search' for kind, _, _ in calls)
    draw(topbar.TOPBAR_MT_realtime, context)
print('NATIVE_UI_LOGIC_PASS')

if '--ui-only' in sys.argv:
    print('C_OPERATOR_NOT_TESTED: upstream binary, UI-only check requested')
else:
    # Requires the compiled fork. Never silently skip a missing native operator.
    op = bpy.ops.screen.realtime_view
    op.get_rna_type()
    screen = bpy.context.screen
    views = [a.spaces.active for a in screen.areas if a.type == 'VIEW_3D']
    assert views and op.poll()
    scene = bpy.context.scene
    original = (scene.render.engine, scene.render.resolution_percentage,
                scene.render.fps, tuple(bpy.data.objects))
    saved = [v.shading.type for v in views]
    for shading in ('MATERIAL', 'SOLID'):
        assert op(shading=shading) == {'FINISHED'}
        assert all(v.shading.type == shading for v in views)
        assert original == (scene.render.engine, scene.render.resolution_percentage,
                            scene.render.fps, tuple(bpy.data.objects))
    scene.render.engine = 'BLENDER_WORKBENCH'
    assert op(shading='MATERIAL') == {'CANCELLED'}
    assert scene.render.engine == 'BLENDER_WORKBENCH'
    scene.render.engine = original[0]
    for view, shading in zip(views, saved):
        view.shading.type = shading
    areas = [a for a in screen.areas if a.type == 'VIEW_3D']
    for area in areas:
        area.type = 'TEXT_EDITOR'
    assert not op.poll()
    for area in areas:
        area.type = 'VIEW_3D'
    print('NATIVE_C_VIEWPORT_PASS')
