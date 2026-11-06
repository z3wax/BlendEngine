# SPDX-License-Identifier: GPL-2.0-or-later
"""NPC adapter metadata preserves source visuals and rejects unsupported AI."""
import importlib.util
from pathlib import Path
import sys
import unittest

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/addons_core'))
import blendengine
blendengine.register()
from blendengine import ai_system, story_game

spec = importlib.util.spec_from_file_location('native_scene', ROOT / 'tools/blendengine/export_native_assets.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class AgentExportTests(unittest.TestCase):
    def test_metadata_and_shared_native_prototype(self):
        made = story_game.create_story(bpy.context)
        scout = ai_system.create_agent(bpy.context, name='Export Scout', behavior='GUIDE',
                                       location=(1.5, -8, .92), speed=3)
        bpy.context.view_layer.update()
        settings = scout.blendengine_object.npc_behavior
        settings.stop_distance = 1.8
        agents, excluded = exporter._native_agents(made['scene'])
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]['name'], scout.name)
        self.assertEqual(agents[0]['behavior'], 'GUIDE')
        self.assertAlmostEqual(agents[0]['position'][0], 1.5)
        self.assertAlmostEqual(agents[0]['stop_distance'], 1.8)
        self.assertIn(scout, excluded)
        self.assertTrue(set(scout.children_recursive).issubset(excluded))
        self.assertNotIn(made['actor'], excluded)
        original_geometry = len(made['actor'].data.vertices)
        scratch, copies = exporter._scratch_scene(made['scene'], excluded)
        try:
            self.assertNotIn(scout, copies)
            self.assertIn(made['rig'], copies)
            self.assertEqual(len(copies[made['actor']].data.vertices), original_geometry)
        finally:
            for obj in list(scratch.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.scenes.remove(scratch)
        settings.behavior_template = 'ATTACK'
        with self.assertRaisesRegex(ValueError, 'not supported'):
            exporter._native_agents(made['scene'])
        settings.behavior_template, settings.move_speed = 'GUIDE', 7
        with self.assertRaisesRegex(ValueError, 'between 0 and 6'):
            exporter._native_agents(made['scene'])


result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(AgentExportTests))
blendengine.unregister()
if not result.wasSuccessful():
    raise SystemExit(1)
