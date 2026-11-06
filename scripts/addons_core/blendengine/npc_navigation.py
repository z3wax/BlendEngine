# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded, deterministic XY navigation without a Blender dependency.

The occupancy callback should include the actor's collision radius. Segments
are sampled at a quarter cell and conservatively check the small orthogonal
steps between samples. This avoids tunnelling through the expanded obstacles
used by the runtime, including diagonal grid corners.
"""

import heapq
import math
from numbers import Real


class _BudgetExhausted(Exception):
    pass


def _point(value):
    try:
        x, y = value
    except (TypeError, ValueError) as error:
        raise ValueError("Navigation points must contain two coordinates") from error
    if any(isinstance(v, bool) or not isinstance(v, Real) for v in (x, y)):
        raise ValueError("Navigation coordinates must be numbers")
    x, y = float(x), float(y)
    if not all(math.isfinite(v) and abs(v) <= 1_000_000 for v in (x, y)):
        raise ValueError("Navigation coordinates must be finite and bounded")
    return x, y


def _cell(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Cell size must be a number")
    value = float(value)
    if not math.isfinite(value) or not .05 <= value <= 16:
        raise ValueError("Cell size must be between 0.05 and 16")
    return value


class _Probe:
    def __init__(self, blocked, budget):
        if not callable(blocked):
            raise ValueError("An occupancy callback is required")
        self.blocked = blocked
        self.budget = budget
        self.cache = {}

    def __call__(self, x, y):
        key = (round(x, 9), round(y, 9))
        if key not in self.cache:
            if len(self.cache) >= self.budget:
                raise _BudgetExhausted()
            self.cache[key] = bool(self.blocked(x, y))
        return self.cache[key]


def _segment_clear(start, goal, probe, cell_size):
    dx, dy = goal[0] - start[0], goal[1] - start[1]
    distance = math.hypot(dx, dy)
    if distance > cell_size * 256:
        return False
    steps = max(1, math.ceil(distance / (cell_size * .25)))
    px, py = start
    if probe(px, py):
        return False
    for step in range(1, steps + 1):
        fraction = step / steps
        x, y = start[0] + dx * fraction, start[1] + dy * fraction
        if probe(x, y):
            return False
        # Check both sides of a diagonal transition instead of slipping
        # between blocked cells which meet only at a corner.
        if dx and dy and (probe(x, py) or probe(px, y)):
            return False
        px, py = x, y
    return True


def segment_clear(start, goal, blocked, cell_size=.75):
    """Check a short segment using at most 4096 cached occupancy probes."""
    start, goal, cell_size = _point(start), _point(goal), _cell(cell_size)
    try:
        return _segment_clear(start, goal, _Probe(blocked, 4096), cell_size)
    except _BudgetExhausted:
        return False


def find_path(start, goal, blocked, cell_size=.75, max_nodes=1024, margin=8.0):
    """Return XY waypoints after start, ending at the exact goal, or ``[]``.

    No more than ``max_nodes`` nodes and ``max(128, max_nodes * 32)`` unique
    occupancy queries are evaluated. Searches longer than 256 cells fail
    promptly. The additional search margin is capped at 64 cells, preventing
    large coordinates or user settings from allocating an unbounded grid.
    """
    start, goal, cell_size = _point(start), _point(goal), _cell(cell_size)
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or not 1 <= max_nodes <= 4096:
        raise ValueError("Node budget must be an integer between 1 and 4096")
    if isinstance(margin, bool) or not isinstance(margin, Real) or not math.isfinite(margin) or margin < 0:
        raise ValueError("Search margin must be a finite nonnegative number")
    probe = _Probe(blocked, max(128, max_nodes * 32))
    if math.dist(start, goal) > cell_size * 256:
        return []
    if math.dist(start, goal) < 1e-9:
        return []
    try:
        if probe(*start) or probe(*goal):
            return []
        if _segment_clear(start, goal, probe, cell_size):
            return [goal]
        padding = min(float(margin), cell_size * 64)
        low = tuple(math.floor((min(start[i], goal[i]) - padding - start[i]) / cell_size)
                    for i in (0, 1))
        high = tuple(math.ceil((max(start[i], goal[i]) + padding - start[i]) / cell_size)
                     for i in (0, 1))

        def world(node):
            return start[0] + node[0] * cell_size, start[1] + node[1] * cell_size

        frontier = [(math.dist(start, goal), 0.0, 0, (0, 0))]
        costs = {(0, 0): 0.0}
        parents = {}
        visited = set()
        sequence = 0
        # Fixed order and a monotonic tie-breaker make replay deterministic.
        neighbors = ((1, 0), (0, 1), (-1, 0), (0, -1),
                     (1, 1), (-1, 1), (-1, -1), (1, -1))
        while frontier and len(visited) < max_nodes:
            _score, cost, _sequence, node = heapq.heappop(frontier)
            if node in visited or cost != costs.get(node):
                continue
            visited.add(node)
            point = world(node)
            if math.dist(point, goal) <= cell_size * 1.5 and _segment_clear(point, goal, probe, cell_size):
                path = []
                current = node
                while current != (0, 0):
                    path.append(world(current))
                    current = parents[current]
                path.reverse()
                if not path or math.dist(path[-1], goal) > 1e-9:
                    path.append(goal)
                return path
            for dx, dy in neighbors:
                candidate = node[0] + dx, node[1] + dy
                if (candidate in visited or not low[0] <= candidate[0] <= high[0]
                        or not low[1] <= candidate[1] <= high[1]):
                    continue
                candidate_point = world(candidate)
                if probe(*candidate_point):
                    continue
                if dx and dy and (probe(*world((node[0] + dx, node[1])))
                                  or probe(*world((node[0], node[1] + dy)))):
                    continue
                if not _segment_clear(point, candidate_point, probe, cell_size):
                    continue
                new_cost = cost + cell_size * math.hypot(dx, dy)
                if new_cost >= costs.get(candidate, math.inf):
                    continue
                costs[candidate] = new_cost
                parents[candidate] = node
                sequence += 1
                heapq.heappush(frontier, (new_cost + math.dist(candidate_point, goal),
                                          new_cost, sequence, candidate))
    except _BudgetExhausted:
        return []
    return []
