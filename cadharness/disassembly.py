"""
Disassembly Sequence Generator — explode an assembly into ordered steps.

Takes a STEP assembly and generates a sequence of disassembly steps,
where each step moves one part outward along its removal axis. Can
export individual STEP frames for animation (GIF/video).

Usage:
    from cadharness.disassembly import DisassemblySequence
    seq = DisassemblySequence("assembly.step", labels={...})
    seq.auto_sequence()  # or manually define order
    seq.export_frames("frames/", explode_distance=200)
"""
import cadquery as cq
from cadquery import Assembly, Color, Location
import os
import math
from typing import List, Tuple, Optional
from .inventory import load_and_dedup, sig


def _center(s):
    bb = s.BoundingBox()
    return ((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2)


def _bbox(s):
    bb = s.BoundingBox()
    return (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)


class DisassemblyStep:
    """One step in the disassembly sequence."""
    def __init__(self, part_index: int, label: str, center: tuple,
                 removal_axis: str, removal_direction: float):
        self.part_index = part_index
        self.label = label
        self.center = center
        self.removal_axis = removal_axis      # 'X', 'Y', or 'Z'
        self.removal_direction = removal_direction  # +1 or -1

    def offset_at(self, distance: float) -> Tuple[float, float, float]:
        """Compute the translation offset for this step at a given distance."""
        dx = dy = dz = 0.0
        if self.removal_axis == 'X':
            dx = distance * self.removal_direction
        elif self.removal_axis == 'Y':
            dy = distance * self.removal_direction
        else:
            dz = distance * self.removal_direction
        return (dx, dy, dz)


class DisassemblySequence:
    """
    Generate and export a disassembly sequence for a STEP assembly.

    The sequence removes parts from outside-in, with each part moving
    outward along its natural removal axis (determined by which face
    of the assembly centroid it's closest to).
    """

    def __init__(self, step_path: str, labels: dict = None):
        self.step_path = step_path
        self.labels = labels or {}
        self.parts = load_and_dedup(step_path)
        self.steps: List[DisassemblyStep] = []

        # Compute assembly centroid
        centers = [_center(s) for s in self.parts]
        self.centroid = (
            sum(c[0] for c in centers) / len(centers),
            sum(c[1] for c in centers) / len(centers),
            sum(c[2] for c in centers) / len(centers),
        )

    def _label_of(self, solid) -> str:
        d = sig(solid)
        return self.labels.get(d, 'part')

    def _removal_axis(self, center: tuple) -> Tuple[str, float]:
        """Determine the natural removal axis for a part based on its
        position relative to the assembly centroid."""
        dx = center[0] - self.centroid[0]
        dy = center[1] - self.centroid[1]
        dz = center[2] - self.centroid[2]

        adx, ady, adz = abs(dx), abs(dy), abs(dz)

        if adx >= ady and adx >= adz:
            return ('X', 1.0 if dx >= 0 else -1.0)
        elif ady >= adx and ady >= adz:
            return ('Y', 1.0 if dy >= 0 else -1.0)
        else:
            return ('Z', 1.0 if dz >= 0 else -1.0)

    def auto_sequence(self, priority: dict = None):
        """
        Automatically determine disassembly order.

        Parts are removed outside-in: the part furthest from the centroid
        comes off first. Optional priority dict overrides order for specific
        labels (lower number = removed first).

        Args:
            priority: Dict of label → priority number.
                      e.g. {"belt": 1, "motor": 2, "plate": 3, "cbeam": 10}
        """
        if priority is None:
            priority = {
                'belt': 1,
                'pulley': 2,
                'vwheel': 2,
                'motor': 3,
                'idler': 3,
                'zmount': 4,
                'zcap': 4,
                'bot-mount': 4,
                'ymount': 4,
                'tbracket': 4,
                'shim': 5,
                'plate': 6,
                'idler-brk': 6,
                'cbeam': 10,
            }

        entries = []
        for i, s in enumerate(self.parts):
            c = _center(s)
            label = self._label_of(s)
            dist_from_center = math.sqrt(
                (c[0] - self.centroid[0]) ** 2 +
                (c[1] - self.centroid[1]) ** 2 +
                (c[2] - self.centroid[2]) ** 2
            )
            pri = priority.get(label, 5)
            axis, direction = self._removal_axis(c)
            entries.append((pri, -dist_from_center, i, label, c, axis, direction))

        entries.sort()
        self.steps = [
            DisassemblyStep(
                part_index=i, label=label, center=c,
                removal_axis=axis, removal_direction=direction
            )
            for pri, neg_dist, i, label, c, axis, direction in entries
        ]

    def export_frames(self, output_dir: str, explode_distance: float = 200.0,
                       n_transition_frames: int = 5, color_removed: tuple = (0.5, 0.5, 0.5),
                       color_active: tuple = (0.59, 0.84, 0.0)):
        """
        Export STEP files for each disassembly frame.

        Each frame shows:
        - Already-removed parts: offset to their final exploded position (grey)
        - Currently-removing part: transitioning outward (green)
        - Remaining parts: in original position (dark)

        Args:
            output_dir: Directory to write STEP frames
            explode_distance: How far removed parts travel (mm)
            n_transition_frames: Frames per removal transition
            color_removed: RGB for already-removed parts
            color_active: RGB for the part being removed
        """
        os.makedirs(output_dir, exist_ok=True)

        frame_num = 0
        removed_steps = []

        # Frame 0: fully assembled
        self._export_frame(output_dir, frame_num, removed_steps, None, 0, explode_distance,
                           color_removed, color_active)
        frame_num += 1

        for step_idx, step in enumerate(self.steps):
            # Transition frames for this step
            for t in range(n_transition_frames):
                frac = (t + 1) / n_transition_frames
                self._export_frame(output_dir, frame_num, removed_steps,
                                   step, frac, explode_distance,
                                   color_removed, color_active)
                frame_num += 1

            removed_steps.append(step)

        # Final frame: everything exploded
        self._export_frame(output_dir, frame_num, removed_steps, None, 0,
                           explode_distance, color_removed, color_active)

        print(f"Exported {frame_num + 1} frames to {output_dir}/")
        print(f"  {len(self.steps)} disassembly steps")
        print(f"  {n_transition_frames} transition frames each")
        return frame_num + 1

    def _export_frame(self, output_dir, frame_num, removed_steps,
                       active_step, active_frac, explode_distance,
                       color_removed, color_active):
        """Export a single STEP frame."""
        assy = Assembly()
        removed_indices = {s.part_index for s in removed_steps}
        active_index = active_step.part_index if active_step else -1

        for i, part in enumerate(self.parts):
            wp = cq.Workplane().add(part)

            if i in removed_indices:
                # Already removed — at full explode distance
                step = next(s for s in removed_steps if s.part_index == i)
                offset = step.offset_at(explode_distance)
                color = Color(*color_removed)
            elif i == active_index:
                # Currently being removed — transitioning
                offset = active_step.offset_at(explode_distance * active_frac)
                color = Color(*color_active)
            else:
                # Still assembled
                offset = (0, 0, 0)
                color = Color(0.2, 0.2, 0.2)

            assy.add(wp, name=f"part_{i}", color=color,
                     loc=Location(offset))

        path = os.path.join(output_dir, f"frame_{frame_num:04d}.step")
        assy.save(path)

    def export_exploded(self, output_path: str, explode_distance: float = 300.0):
        """Export a single fully-exploded view STEP file."""
        if not self.steps:
            self.auto_sequence()

        assy = Assembly()
        for i, part in enumerate(self.parts):
            wp = cq.Workplane().add(part)
            # Find this part's step
            step = next((s for s in self.steps if s.part_index == i), None)
            if step:
                # Scale distance by priority (inner parts explode less)
                step_idx = self.steps.index(step)
                frac = (step_idx + 1) / len(self.steps)
                offset = step.offset_at(explode_distance * frac)
            else:
                offset = (0, 0, 0)

            label = self._label_of(part)
            color = Color(0.59, 0.84, 0.0) if label != 'cbeam' else Color(0.2, 0.2, 0.2)
            assy.add(wp, name=f"part_{i}", color=color,
                     loc=Location(offset))

        assy.save(output_path)
        size_kb = os.path.getsize(output_path) / 1024
        print(f"Exported exploded view: {output_path} ({size_kb:.0f} KB)")

    def summary(self) -> str:
        """Print the disassembly sequence."""
        lines = [f"DISASSEMBLY SEQUENCE: {len(self.steps)} steps", ""]
        for i, step in enumerate(self.steps):
            lines.append(f"  {i+1:3d}. Remove {step.label:15s} "
                         f"at ({step.center[0]:.0f},{step.center[1]:.0f},{step.center[2]:.0f}) "
                         f"-> pull {step.removal_axis}{'+' if step.removal_direction > 0 else '-'}")
        return '\n'.join(lines)
