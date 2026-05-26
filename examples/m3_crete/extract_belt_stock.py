"""Extract the authored drive-train geometry from the M3-2 source assembly.

The belts, drive pulleys, and return idlers in the M3-CRETE design are authored
geometry living inside the protected native export
``M3-CRETE/CAD/M3-2_Assembly.step``. CADCLAW does not generate belt geometry
(the spec compiler blocks generated sources), so to give the reference assembly
real belts we lift the authored belt solids out of the source into small
standalone STEP stock parts -- the same "place authored, do not generate"
pattern used for the approved ZPMM spacer one-off. Pulleys and idlers already
exist as standalone authored STEPs, so for those we only report their source
positions to drive faithful placement.

This script is READ-ONLY on the source (a protected path) and writes new belt
stock STEPs to ``examples/m3_crete/generated/``.

Source frame is corner-origin (X 0..2080, Y 0..1040); the CADCLAW reference
spec is center-origin, so positions are reported in both frames using OFFSET.

Run: ``.venv\\Scripts\\python.exe examples\\m3_crete\\extract_belt_stock.py``

NOTE (2026-05-25): the seven per-instance ``M3_NEMA23_motor_src*.step`` exports
this script once wrote are SUPERSEDED. The kit now ships one generic
``M3_NEMA23_motor.step`` placed seven times via per-instance ``rotate_deg`` in the
reference assembly (one motor SKU, not seven pre-rotated files). The motor-export
path below is retained only as historical provenance of how those exports were made.
"""
from __future__ import annotations

from pathlib import Path

import cadquery as cq

SOURCE = Path(r"D:/SunnydayTech/M3-CRETE/CAD/M3-2_Assembly.step")
OUT_DIR = Path(__file__).resolve().parent / "generated"

# Source(corner-origin) -> CADCLAW(center-origin) translation.
OFFSET = (-1040.0, -520.0, 0.0)

# Sorted-bbox signatures (mm) with tolerance.
BELT_THIN = (1.0, 2.5)
BELT_WIDTH = (5.0, 7.0)
BELT_MIN_LEN = 400.0
PULLEY_SIG = (14.0, 15.0, 15.0)   # GT2 20T drive pulley
IDLER_SIG = (12.7, 22.0, 22.0)    # smooth return idler
MOTOR_SIG = (56.4, 56.4, 76.6)    # NEMA 23 stepper
PLATE_XL_SIG = (6.0, 125.0, 125.0)  # C-Beam Gantry Plate XLarge
PLATE_SM_SIG = (3.0, 88.0, 127.0)   # V-Slot Gantry Plate 20-80
WHEEL_SIG = (10.2, 23.9, 23.9)      # Solid V Wheel
SIG_TOL = 0.6


def sdims(bb):
    return tuple(sorted([bb.xlen, bb.ylen, bb.zlen]))


def long_axis(bb):
    return max({"x": bb.xlen, "y": bb.ylen, "z": bb.zlen}.items(), key=lambda kv: kv[1])[0]


def center(bb):
    return ((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2)


def cad(c):
    return (c[0] + OFFSET[0], c[1] + OFFSET[1], c[2] + OFFSET[2])


def matches(d, sig, tol=SIG_TOL):
    return all(abs(a - b) <= tol for a, b in zip(d, sorted(sig)))


def main() -> int:
    if not SOURCE.exists():
        print(f"SOURCE missing: {SOURCE}")
        return 1
    print(f"Loading {SOURCE.name} ({SOURCE.stat().st_size / 1e6:.1f} MB) ...")
    solids = cq.importers.importStep(str(SOURCE)).solids().vals()
    print(f"Total solids in source: {len(solids)}\n")

    belts, pulleys, idlers, motors = [], [], [], []
    plates_xl, plates_sm, wheels = [], [], []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        d = sdims(bb)
        if BELT_THIN[0] <= d[0] <= BELT_THIN[1] and BELT_WIDTH[0] <= d[1] <= BELT_WIDTH[1] and d[2] >= BELT_MIN_LEN:
            belts.append({"i": i, "d": d, "c": center(bb), "axis": long_axis(bb), "solid": s})
        elif matches(d, PULLEY_SIG):
            pulleys.append({"i": i, "d": d, "c": center(bb), "axis": long_axis(bb)})
        elif matches(d, IDLER_SIG):
            idlers.append({"i": i, "d": d, "c": center(bb), "axis": long_axis(bb)})
        elif matches(d, MOTOR_SIG, tol=1.5):
            motors.append({"i": i, "d": d, "c": center(bb), "axis": long_axis(bb), "solid": s})
        elif matches(d, PLATE_XL_SIG, tol=4):
            plates_xl.append({"i": i, "d": d, "c": center(bb), "axis": long_axis(bb)})
        elif matches(d, PLATE_SM_SIG, tol=4):
            plates_sm.append({"i": i, "d": d, "c": center(bb), "axis": long_axis(bb)})
        elif matches(d, WHEEL_SIG, tol=1.5):
            wheels.append({"i": i, "d": d, "c": center(bb), "axis": long_axis(bb)})

    def report(name, items):
        print(f"== {name}: {len(items)} ==")
        for it in items:
            c, cc = it["c"], cad(it["c"])
            print(f"  #{it['i']:>4} dims={tuple(round(x,1) for x in it['d'])} axis={it['axis']} "
                  f"src=({c[0]:7.1f},{c[1]:7.1f},{c[2]:7.1f}) cad=({cc[0]:7.1f},{cc[1]:7.1f},{cc[2]:7.1f})")
        print()

    report("BELTS", belts)
    report("PULLEYS (GT2 20T)", pulleys)
    report("IDLERS (smooth)", idlers)
    report("MOTORS (NEMA 23)", motors)
    report("PLATES XLarge 125x125", plates_xl)
    report("PLATES small (V-Slot 20-80)", plates_sm)
    # Wheels near the X-gantry ends only (cad |x| in 950..1070).
    xg = [w for w in wheels if 950 <= abs(cad(w["c"])[0]) <= 1070]
    print(f"== WHEELS: {len(wheels)} total; {len(xg)} near X-gantry ends ==")
    for w in xg:
        cc = cad(w["c"])
        print(f"  #{w['i']:>4} dims={tuple(round(x,1) for x in w['d'])} "
              f"cad=({cc[0]:7.1f},{cc[1]:7.1f},{cc[2]:7.1f})")
    print()

    # Export one recentered belt stock per long axis (Z run and Y run).
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("M3_GT2_belt_*.step"):
        old.unlink()
    for axis in ("z", "y"):
        members = [b for b in belts if b["axis"] == axis]
        if not members:
            continue
        rep = members[0]
        cx, cy, cz = rep["c"]
        recentered = rep["solid"].translate(cq.Vector(-cx, -cy, -cz))
        length = round(rep["d"][2])
        out = OUT_DIR / f"M3_GT2_belt_{axis.upper()}_{length}mm.step"
        cq.exporters.export(cq.Workplane().add(recentered), str(out))
        print(f"exported {out.name} ({out.stat().st_size} bytes) -- {len(members)} instances use this stock")

    # Export each NEMA 23 motor solid recentered, preserving its source
    # orientation so the V1.0 mount/hole alignment carries into placement.
    for old in OUT_DIR.glob("M3_NEMA23_motor_*.step"):
        old.unlink()
    for m in motors:
        cx, cy, cz = m["c"]
        rec = m["solid"].translate(cq.Vector(-cx, -cy, -cz))
        out = OUT_DIR / f"M3_NEMA23_motor_src{m['i']}.step"
        cq.exporters.export(cq.Workplane().add(rec), str(out))
        cc = cad(m["c"])
        print(f"exported {out.name} ({out.stat().st_size} b) "
              f"cad=({cc[0]:.1f},{cc[1]:.1f},{cc[2]:.1f}) axis={m['axis']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
