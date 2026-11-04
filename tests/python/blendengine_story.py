# SPDX-License-Identifier: GPL-2.0-or-later
"""Input-driven story completion, human skinning and replay regressions."""
from pathlib import Path
import sys
import unittest
import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/addons_core'))
import blendengine
blendengine.register()
from blendengine import story_game,runtime


class StoryTests(unittest.TestCase):
    def test_human_character_and_real_input_complete_chapter(self):
        made=story_game.create_story(bpy.context)
        self.assertGreater(len(made['actor'].data.vertices),1000)
        self.assertGreaterEqual(len({p.material_index for p in made['actor'].data.polygons}),4)
        self.assertEqual(made['actor'].modifiers[0].type,'ARMATURE')
        self.assertGreater(len(made['rig'].pose.bones),8)
        bpy.context.view_layer.update()
        # Euler channels must actually deform the mesh, not leave a T-pose
        # because pose bones silently retained their Quaternion mode.
        self.assertEqual(made['rig'].pose.bones['arm.L'].rotation_mode,'XYZ')
        self.assertLess(made['rig'].pose.bones['forearm.L'].tail.z,.2)
        session=runtime.GameSession(bpy.context)
        session.start()
        game=session._gameplay
        self.assertEqual(game.state,'RUNNING')
        for x,y in story_game.WAYPOINTS:
            for _ in range(600):
                if game.state=='WON':break
                dx,dy=x-session.player.location.x,y-session.player.location.y
                if dx*dx+dy*dy<.16:break
                session.input_state=set()
                if abs(dx)>.12:session.input_state.add('D' if dx>0 else 'A')
                if abs(dy)>.12:session.input_state.add('W' if dy>0 else 'S')
                session.step(1/60)
            else:self.fail('input route stalled')
        self.assertEqual(game.score.int_value,5)
        self.assertEqual(game.state,'WON')
        self.assertEqual(game.health.current_health,100)
        self.assertTrue(any('Chapter one complete' in s for s in session.logs))
        game.restart()
        self.assertEqual(game.state,'RUNNING')
        self.assertEqual(game.score.int_value,0)
        self.assertTrue(all(not o.hide_render for o in game.cores))
        session.stop()
        self.assertEqual(list(session.player.location),list(game._initial_player[0]))
        self.assertEqual(list(made['camera'].location),list(game._initial_camera[0]))


result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StoryTests))
blendengine.unregister()
if not result.wasSuccessful():raise SystemExit(1)
