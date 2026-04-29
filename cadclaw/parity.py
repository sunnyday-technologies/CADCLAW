"""
STEP-to-STEP parity check — compare two STEP files by dim-signature
inventory to surface divergences between (for example) a Fusion export
and a CADQuery regen of the same design.

Motivating bug: Fusion's visibility-toggle export. Hiding a part in the
Fusion browser tree and re-exporting can silently drop it from the STEP
— the file shrinks, the part count drops, and a quick eyeball of the
render might not catch it because the assembly still looks "complete."
`visibility_toggle_warning` flags the specific failure mode (smaller
file but more unique signatures, i.e. a shape inventory that wandered
in an unexpected direction).

Usage:
    from cadclaw.parity import compare_steps, visibility_toggle_warning

    report = compare_steps("fusion_export.step", "cadquery_regen.step")
    if not report.passed:
        print(f"Only in A: {report.only_in_a}")
        print(f"Only in B: {report.only_in_b}")

    warn = visibility_toggle_warning("old.step", "new.step")
    if warn:
        print(warn)
"""
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .render import _load_shapes
from .inventory import sig

# A dim-signature is the sorted (dx, dy, dz) tuple rounded to 0.1 mm.
DimSig = Tuple[float, ...]


@dataclass
class ParityReport:
    """Result of comparing two STEP files by dim-signature inventory."""
    a_path: str
    b_path: str
    a_parts: int
    b_parts: int
    # Each entry is (dim_sig, count_delta). For only_in_a, count_delta is
    # how many more copies of that sig exist in A than in B (>=1).
    only_in_a: List[Tuple[DimSig, int]] = field(default_factory=list)
    only_in_b: List[Tuple[DimSig, int]] = field(default_factory=list)
    size_shrunk_warning: Optional[str] = None
    passed: bool = False

    def summary(self) -> str:
        """Short human-readable summary — one block, three or four lines."""
        lines = [
            f"PARITY: {os.path.basename(self.a_path)} vs "
            f"{os.path.basename(self.b_path)}",
            f"  A parts: {self.a_parts}   B parts: {self.b_parts}   "
            f"passed: {self.passed}",
        ]
        if self.only_in_a:
            lines.append(f"  only_in_a ({len(self.only_in_a)} sigs): "
                         f"{self.only_in_a[:3]}"
                         + (" ..." if len(self.only_in_a) > 3 else ""))
        if self.only_in_b:
            lines.append(f"  only_in_b ({len(self.only_in_b)} sigs): "
                         f"{self.only_in_b[:3]}"
                         + (" ..." if len(self.only_in_b) > 3 else ""))
        if self.size_shrunk_warning:
            lines.append(f"  WARN: {self.size_shrunk_warning}")
        return "\n".join(lines)


def _inventory(step_path: str) -> Counter:
    """Load a STEP and return a Counter of dim_sig -> instance count."""
    shapes = _load_shapes(step_path)
    return Counter(sig(s) for s in shapes)


def compare_steps(step_a: str, step_b: str) -> ParityReport:
    """Compare two STEP files by dim-signature inventory.

    Intended use: Fusion export vs CADQuery regen of the same design —
    surfaces missing or extra parts per side. Both files are loaded via
    `render._load_shapes` (same dedup-by-bbox behavior as `inventory`),
    then dim-signatures are counted per file. The report lists any
    signature whose counts disagree.

    `passed` is True iff the inventories match exactly — same set of
    signatures, same count per signature.
    """
    inv_a = _inventory(step_a)
    inv_b = _inventory(step_b)

    only_a: List[Tuple[DimSig, int]] = []
    only_b: List[Tuple[DimSig, int]] = []
    for s in sorted(set(inv_a) | set(inv_b)):
        delta = inv_a.get(s, 0) - inv_b.get(s, 0)
        if delta > 0:
            only_a.append((s, delta))
        elif delta < 0:
            only_b.append((s, -delta))

    report = ParityReport(
        a_path=step_a,
        b_path=step_b,
        a_parts=sum(inv_a.values()),
        b_parts=sum(inv_b.values()),
        only_in_a=only_a,
        only_in_b=only_b,
        passed=not only_a and not only_b,
    )
    report.size_shrunk_warning = visibility_toggle_warning(step_a, step_b)
    return report


def visibility_toggle_warning(old_path: str, new_path: str) -> Optional[str]:
    """Detect the Fusion visibility-toggle export bug.

    Returns a human-readable warning string if `new_path` is smaller on
    disk than `old_path` yet reports MORE unique dim-signatures —
    impossible without something weird happening on the re-export
    (parts silently dropped from the tessellated output while new ones
    appear in the signature list means the file has probably lost
    instances of common parts; a few extras won't offset that).

    More permissive secondary check: also warn when the new file is
    substantially smaller (>5 %) despite the unique-signature count
    being unchanged or higher — the classic "hid a part before export,
    re-exported, file shrank by a megabyte" footprint.

    Returns None when the files look consistent.
    """
    try:
        old_size = os.path.getsize(old_path)
        new_size = os.path.getsize(new_path)
    except OSError as e:
        return f"could not stat files: {e}"

    old_sigs = set(_inventory(old_path))
    new_sigs = set(_inventory(new_path))

    if new_size < old_size and len(new_sigs) > len(old_sigs):
        return (
            f"{os.path.basename(new_path)} is smaller "
            f"({new_size:,} B vs {old_size:,} B) but has MORE unique "
            f"dim signatures ({len(new_sigs)} vs {len(old_sigs)}). "
            "Classic Fusion visibility-toggle footprint — inspect for "
            "silently-dropped part instances."
        )

    shrink_frac = (old_size - new_size) / old_size if old_size > 0 else 0.0
    if shrink_frac > 0.05 and len(new_sigs) >= len(old_sigs):
        return (
            f"{os.path.basename(new_path)} shrank "
            f"{shrink_frac * 100:.1f} % ({old_size:,} -> {new_size:,} B) "
            f"but unique-signature count held or grew "
            f"({len(old_sigs)} -> {len(new_sigs)}). Possible visibility "
            "toggle caused duplicate instances to be dropped."
        )

    return None
