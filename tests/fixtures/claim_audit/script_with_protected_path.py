"""Fixture script that writes to a native-CAD reserved output path."""
import cadquery as cq

assy = cq.Workplane("XY").box(10, 10, 10)
cq.exporters.export(assy, "CAD/M3-2_Assembly.step")
