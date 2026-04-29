"""
Adjacency Gate — validates that parts that should be near each other ARE.

Catches scattered/misplaced components by checking that every part of
type A has a part of type B within a specified distance.

Usage:
    from cadclaw.adjacency import AdjacencyCheck, AdjacencyRule
    rules = [AdjacencyRule('motor', 'bracket', max_distance=50)]
    check = AdjacencyCheck(parts, label_fn, rules)
    result = check.run()
"""
import math
from dataclasses import dataclass
from typing import List, Callable, Optional


@dataclass
class AdjacencyRule:
    """A rule stating that every part of type `source` should have
    a part of type `target` within `max_distance` mm."""
    source: str
    target: str
    max_distance: float = 50.0
    source_filter: Optional[Callable] = None  # optional position filter


@dataclass
class AdjacencyViolation:
    source_label: str
    source_center: tuple
    nearest_target_label: str
    nearest_distance: float
    max_allowed: float


@dataclass
class AdjacencyResult:
    passed: bool
    violations: List[AdjacencyViolation]


def _center(s):
    bb = s.BoundingBox()
    return ((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2)


def _dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


class AdjacencyCheck:
    """
    Validate spatial relationships between part types.

    Args:
        parts: List of CadQuery solids/shells.
        label_fn: Function mapping solid → label string.
        rules: List of AdjacencyRule instances.
    """

    def __init__(self, parts: list, label_fn: Callable, rules: List[AdjacencyRule]):
        self.parts = parts
        self.label_fn = label_fn
        self.rules = rules

    def run(self) -> AdjacencyResult:
        # Group parts by label
        by_label = {}
        for s in self.parts:
            lbl = self.label_fn(s)
            by_label.setdefault(lbl, []).append(s)

        violations = []

        for rule in self.rules:
            sources = by_label.get(rule.source, [])
            targets = by_label.get(rule.target, [])

            for src in sources:
                sc = _center(src)

                # Apply optional position filter
                if rule.source_filter and not rule.source_filter(src):
                    continue

                if not targets:
                    violations.append(AdjacencyViolation(
                        source_label=rule.source,
                        source_center=sc,
                        nearest_target_label=rule.target,
                        nearest_distance=float('inf'),
                        max_allowed=rule.max_distance,
                    ))
                    continue

                nearest = min(targets, key=lambda t: _dist(sc, _center(t)))
                d = _dist(sc, _center(nearest))

                if d > rule.max_distance:
                    violations.append(AdjacencyViolation(
                        source_label=rule.source,
                        source_center=sc,
                        nearest_target_label=rule.target,
                        nearest_distance=d,
                        max_allowed=rule.max_distance,
                    ))

        return AdjacencyResult(
            passed=len(violations) == 0,
            violations=violations,
        )
