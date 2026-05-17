"""Generate user-approved simple M3-CRETE spacer plate STEP assets.

These are intentionally plain rectangular plates with no hole pattern. Complex
or drilled plates should still be authored in native CAD and placed from STEP.
"""
from __future__ import annotations

from pathlib import Path

import cadquery as cq


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "generated"


def export_box(name: str, dims_mm: tuple[float, float, float]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    shape = cq.Workplane("XY").box(*dims_mm)
    cq.exporters.export(shape, str(path))
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    exported = [
        export_box("M3_6mm_frame_shim_4080.step", (80.0, 6.0, 40.0)),
    ]
    for path in exported:
        print(path.as_posix())


if __name__ == "__main__":
    main()
