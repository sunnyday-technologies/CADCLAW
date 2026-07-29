# Worked example: assembly by constraint

This is the shipped, tested example for `place_relative_to` — CADCLAW's
constraint-based placement. It is small on purpose: three parts, one datum, and
both lock modes, so you can read the whole chain in one screen.

Run it:

```bash
cadclaw assemble validate-spec  examples/relative_placement/gantry.yaml
cadclaw assemble build          examples/relative_placement/gantry.yaml
cadclaw assemble render-views   examples/relative_placement/gantry.yaml
```

Or all three at once, which is the normal iteration loop:

```bash
cadclaw assemble check-round examples/relative_placement/gantry.yaml
```

## The chain

```
rail_x                    the datum. The only typed position in the file.
  └── plate               lock: frame   full 3-axis seat on the rail's +X end
        └── rail_y        lock: axis    2 mm standoff off the plate's +X face
```

Only `rail_x` carries hand-typed coordinates. The plate's position is *solved*
from the rail's end face, and the gantry's X position is *solved* from the
plate's outboard face. Nothing downstream is typed.

## The two lock modes

Both appear in [gantry.yaml](gantry.yaml). They differ in how many translation
axes the resolver solves.

### `lock: frame` — the full seat (default)

```yaml
place_relative_to:
  ref: rail_x           # the parent instance
  parent_frame: end_pos_x   # a connector frame on the parent
  frame: face_neg_x         # a connector frame on THIS part
  axis: x
  side: positive
  offset_mm: 0.0
  lock: frame
```

The child's frame origin is made to coincide with the parent's frame origin,
then offset along `axis`. **All three translation components are solved**, so
the plate self-centers on the rail's end face: it lands at X 600 (flush on the
rail end) and centers in Y and Z on the rail's mid-section without anyone
computing where "centered" is.

An explicit `transform` is **rejected** in this mode. The resolver owns the
translation; orientation is authored in the placement block via `rotate_deg`.
One source of truth.

### `lock: axis` — the axis-only lock

```yaml
transform:
  translate_mm: [0.0, -180.0, 40.0]   # X is ignored; Y and Z are authored
place_relative_to:
  ref: plate
  parent_frame: face_pos_x
  frame: mount_face_neg_x
  axis: x
  side: positive
  offset_mm: 2.0
  lock: axis
```

Only the `axis` translation is solved. The instance keeps its own `transform`
for orientation and the two free axes. Use this for a part that hands off along
one axis while *spanning* the other two — a gantry beam has no single "seat" in
Y or Z, so forcing a full 3-axis solve would be wrong.

The authored value on the locked axis is ignored (it is solved), so leaving it
at `0.0` is fine and honest. In this mode `rotate_deg` / `scale` /
`source_origin_mm` must stay unset on the placement block, because orientation
lives in the instance `transform`.

## Where the frames come from

[connectors.yaml](connectors.yaml) records a connector frame per part:
extrusion ends, mount faces, and so on. This is **descriptive data about parts
you authored elsewhere** — "this part has a mounting face here." CADCLAW reads
it to seat parts against each other. It never invents geometry from it.

Because the example parts are plain boxes with a corner at the local origin
(see [make_parts.py](make_parts.py)), every frame origin can be checked by hand
against the geometry.

## What it solves to

| part | X | Y | Z |
|------|---|---|---|
| `rail_x` | 0 … 600 | 0 … 40 | 0 … 40 |
| `plate` | 600 … 610 | −40 … 80 | −40 … 80 |
| `rail_y` | 612 … 652 | −180 … 220 | 40 … 80 |

The plate sits flush at X 600 and self-centers on the rail. The gantry sits at
X 612: the plate's outboard face is at 610, plus the 2 mm standoff.

These numbers are asserted in
[`tests/test_example_relative_placement.py`](../../tests/test_example_relative_placement.py),
so this table cannot silently drift from what the example actually produces.

## Why bother

Two behaviors, both covered by tests:

**Move the datum and the chain follows.** Shift `rail_x` by +100 mm in X and
all three parts move +100 mm. Nothing else is edited.

**Change a tolerance and it propagates.** Push the plate's outboard face 5 mm
further out (a thicker plate) and the gantry moves out 5 mm. The datum and the
plate seat do not move, and no coordinate is re-typed.

With absolute coordinates, both edits mean re-deriving every downstream
position by hand. That is the failure mode this exists to remove: on the
M3-CRETE gantry, one plate swap left roughly eighteen seating failures that
could not be cleared without dragging the whole coupled stack.

## Honest limits

- The parts are simple boxes standing in for parts you would draw in Fusion,
  Rhino, or SolidWorks. CADCLAW does not author geometry; `make_parts.py` runs
  once, and its output is committed like any CAD export.
- The frames here were written by hand from known box dimensions. On a real
  project they come from the source CAD and should be checked against rendered
  views before being marked `verified: true`.
- The 2 mm standoff is illustrative, not a real mechanical clearance spec.
