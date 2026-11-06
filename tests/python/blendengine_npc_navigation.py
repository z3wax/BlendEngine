# SPDX-License-Identifier: GPL-2.0-or-later
"""Behavioral navigation regressions; no Blender or rendering required."""

import importlib.util
import math
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[2] / 'scripts/addons_core/blendengine/npc_navigation.py'
SPEC = importlib.util.spec_from_file_location('npc_navigation', PATH)
navigation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(navigation)


class NavigationTests(unittest.TestCase):
    def test_direct_route_keeps_exact_unsnapped_goal(self):
        goal = (4.21, -2.13)
        self.assertEqual(navigation.find_path((.18, .31), goal, lambda x, y: False), [goal])

    def test_wall_requires_a_real_detour_with_no_blocked_crossing(self):
        blocked = lambda x, y: 1.5 <= x <= 2.5 and -1.6 <= y <= 1.6
        path = navigation.find_path((0, 0), (4.23, .1), blocked, cell_size=.5)
        self.assertTrue(path)
        self.assertEqual(path[-1], (4.23, .1))
        self.assertGreater(max(abs(y) for x, y in path), 1.6)
        previous = (0, 0)
        for point in path:
            self.assertTrue(navigation.segment_clear(previous, point, blocked, .5))
            for step in range(101):
                f = step / 100
                self.assertFalse(blocked(previous[0] + (point[0] - previous[0]) * f,
                                         previous[1] + (point[1] - previous[1]) * f))
            previous = point

    def test_enclosed_goal_fails_without_entering_a_wall(self):
        def blocked(x, y):
            radius = max(abs(x - 3), abs(y))
            return .55 < radius < 1.25
        self.assertEqual(navigation.find_path((0, 0), (3, 0), blocked, cell_size=.25), [])

    def test_diagonal_corner_is_not_a_direct_shortcut(self):
        def blocked(x, y):
            return (round(x), round(y)) in {(1, 0), (0, 1)}
        self.assertFalse(navigation.segment_clear((0, 0), (1, 1), blocked, 1))
        path = navigation.find_path((0, 0), (2, 2), blocked, cell_size=1)
        self.assertTrue(path)
        self.assertNotEqual(path, [(2., 2.)])

    def test_node_and_query_budgets_abort_instead_of_running_unbounded(self):
        calls = []
        def blocked(x, y):
            calls.append((x, y))
            return .5 <= x <= 1.5 and -20 <= y <= 20
        self.assertEqual(navigation.find_path((0, 0), (4, 0), blocked,
                                               cell_size=.5, max_nodes=1), [])
        self.assertLessEqual(len(calls), 128)
        self.assertEqual(len(calls), len(set((round(x, 9), round(y, 9)) for x, y in calls)))
        calls.clear()
        self.assertEqual(navigation.find_path((0, 0), (1000, 0), blocked), [])
        self.assertEqual(calls, [])

    def test_replay_is_deterministic(self):
        blocked = lambda x, y: 1 <= x <= 2 and -1 <= y <= 1
        first = navigation.find_path((0, 0), (4, 0), blocked, cell_size=.5)
        self.assertEqual(first, navigation.find_path((0, 0), (4, 0), blocked, cell_size=.5))
        self.assertTrue(first)

    def test_invalid_settings_fail_before_occupancy_calls(self):
        for point in ((math.nan, 0), (math.inf, 1), ('1', 0), (1e12, 0)):
            with self.assertRaises(ValueError):
                navigation.find_path(point, (1, 1), lambda x, y: False)
        for budget in (0, 4097, True, 1.5):
            with self.assertRaises(ValueError):
                navigation.find_path((0, 0), (1, 1), lambda x, y: False, max_nodes=budget)


if __name__ == '__main__':
    unittest.main(verbosity=2)
