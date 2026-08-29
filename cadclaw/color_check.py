"""
Color/material attribute Gate — verifies each labeled part's STEP color
attribute matches the rule's expected color within a per-channel tolerance.

v0.9 gate #2. Closes V1.0 manual fixes #1 + #6: a motor mount and top
braces that were authored black instead of Sunnyday green. Inventory +
orientation + interference all passed for those parts (the bbox + bolt
holes were correct; only the color was wrong) so the manual fix landed
without any harness signal.

Spec — per the user 2026-04-29: keep the math minimal. NO CIELAB ΔE.
Just per-channel RGB equality with an integer tolerance in 0-255 space:

    color_matches(actual, expected, tol=5):
        return all(abs(a - e) <= tol for a, e in zip(actual_255, expected_255))

The check reads colors from STEP AP242 metadata via `_extract_step_colors`
in `cadclaw/render.py`, which keys by the same sorted dim-sig as
`inventory.sig`. Parts whose label has `expected_color` set get checked;
all others are skipped.

Usage:
    from cadclaw.color_check import ColorCheck
    check = ColorCheck(step_path, label_specs)
    result = check.run()
    for v in result.violations:
        print(f"{v.label}: expected {v.expected_hex}, got {v.actual_hex}")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .rules import LabelSpec


RGB255 = Tuple[int, int, int]


@dataclass
class ColorViolation:
    """One color-mismatch finding."""
    label: str
    expected_hex: str          # e.g. "#969F00"
    actual_hex: str            # e.g. "#000000"
    delta_per_channel: Tuple[int, int, int]   # signed (R, G, B) diff in 0-255
    tolerance_rgb: int


@dataclass
class ColorMissing:
    """A part whose label expected_color is set but the STEP carries no color."""
    label: str
    expected_hex: str


@dataclass
class ColorResult:
    passed: bool
    checked: int
    violations: List[ColorViolation] = field(default_factory=list)
    missing: List[ColorMissing] = field(default_factory=list)


def hex_to_rgb255(hex_str: str) -> RGB255:
    """'#969F00' → (150, 159, 0). LabelSpec validation already enforces
    the 6-hex-digit shape; we trust input here."""
    s = hex_str.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def rgb01_to_rgb255(rgb01: Tuple[float, float, float]) -> RGB255:
    """Direct float-to-byte (no gamma). Used for tests + cases where the
    toolchain stores sRGB values directly without linear-light conversion."""
    return (
        max(0, min(255, round(rgb01[0] * 255))),
        max(0, min(255, round(rgb01[1] * 255))),
        max(0, min(255, round(rgb01[2] * 255))),
    )


def _linear_to_srgb_channel(linear: float) -> float:
    """W3C sRGB transfer function — linear-light [0,1] → sRGB [0,1]."""
    if linear <= 0.0031308:
        return 12.92 * linear
    return 1.055 * (linear ** (1.0 / 2.4)) - 0.055


def rgb01_linear_to_rgb255_srgb(rgb01: Tuple[float, float, float]) -> RGB255:
    """STEP AP242 stores linear-light RGB. Hex strings like '#969F00' are
    conventionally sRGB (display-space). This helper applies the W3C sRGB
    transfer to convert linear → sRGB byte so user-readable hex matches
    what their toolchain shows on screen.

    If your toolchain stores sRGB directly without gamma (rare but
    possible), tolerance compensates: bump `color_tolerance_rgb` until
    matches stick. The gamma path is the standards-compliant default
    because OCCT's `Quantity_Color` treats RGB as linear-light.
    """
    return tuple(
        max(0, min(255, round(_linear_to_srgb_channel(c) * 255)))
        for c in rgb01
    )


def rgb255_to_hex(rgb: RGB255) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def color_matches(actual: RGB255, expected: RGB255, tol: int = 5) -> bool:
    """Per-channel RGB equality with tolerance — minimal version of v0.9 gate #2."""
    return all(abs(a - e) <= tol for a, e in zip(actual, expected))


class ColorCheck:
    """Verify each labeled part's STEP color matches its label's expected_color.

    Reads color metadata from `step_path` via the existing AP242 helper.
    Compares against `LabelSpec.expected_color` for each label that has
    one set; emits `cad.color_mismatch` (FAIL) on diff, `cad.color_missing`
    (WARN) when the label expects a color but the STEP carries none.

    Args:
        step_path: path to the assembly STEP. Re-reads AP242 metadata
            via `_extract_step_colors`; not shared with the v0.9 parts
            loader because the color extraction needs the full XCAF
            document, not just the leaf shapes.
        label_specs: Dict[label, LabelSpec] from `RuleSet.label_specs()`.
    """

    def __init__(self, step_path: str, label_specs: Dict[str, LabelSpec]):
        self.step_path = step_path
        self.label_specs = label_specs

    def run(self) -> ColorResult:
        # Filter to labels that opted into color check.
        active = {name: spec for name, spec in self.label_specs.items()
                  if spec.expected_color is not None}
        if not active:
            return ColorResult(passed=True, checked=0)

        from .render import _extract_step_colors
        from .inventory import sig as _sig
        step_colors = _extract_step_colors(self.step_path, strict=True)
        # step_colors is keyed by the same sorted-tuple as inventory.sig;
        # build a parallel label->sig map for our active labels.
        label_to_sig = {
            name: tuple(sorted(round(float(x), 1) for x in spec.sig))
            for name, spec in active.items()
        }

        violations: List[ColorViolation] = []
        missing: List[ColorMissing] = []
        checked = 0

        for label, spec in active.items():
            sig_key = label_to_sig[label]
            checked += 1
            expected_rgb = hex_to_rgb255(spec.expected_color)

            actual_rgb01 = step_colors.get(sig_key)
            if actual_rgb01 is None:
                missing.append(ColorMissing(
                    label=label,
                    expected_hex=spec.expected_color,
                ))
                continue

            actual_rgb = rgb01_linear_to_rgb255_srgb(actual_rgb01)
            if not color_matches(actual_rgb, expected_rgb,
                                 tol=spec.color_tolerance_rgb):
                delta = tuple(int(a) - int(e)
                              for a, e in zip(actual_rgb, expected_rgb))
                violations.append(ColorViolation(
                    label=label,
                    expected_hex=spec.expected_color,
                    actual_hex=rgb255_to_hex(actual_rgb),
                    delta_per_channel=delta,
                    tolerance_rgb=spec.color_tolerance_rgb,
                ))

        return ColorResult(
            passed=len(violations) == 0,
            checked=checked,
            violations=violations,
            missing=missing,
        )
