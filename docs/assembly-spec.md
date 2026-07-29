# The assembly spec

Reference for `assembly_spec.v0.1`, the declarative file `cadclaw assemble`
compiles into a STEP assembly.

A spec declares three things: **what parts** go in, **where they come from**,
and **how they seat against each other**. CADCLAW resolves it and compiles the
result with CadQuery. It places parts you authored in external CAD; it does not
generate geometry.

For a small, runnable version of everything below, see
[`examples/relative_placement/`](../examples/relative_placement/README.md).

## Minimal spec

```yaml
schema_version: assembly_spec.v0.1

meta:
  project: My Project
  assembly_id: frame_v1

component_roots:
  - examples/relative_placement       # where source_path is resolved from

outputs:
  step: build/frame.step
  views_dir: build/views

instances:
  - id: rail
    role: rail
    source_path: parts/rail_x.step
    transform:
      translate_mm: [0.0, 0.0, 0.0]
```

The schema is **strict**: an unknown key is a validation error, not a warning.
A typo in a field name fails loudly instead of being silently ignored.

Validate before compiling:

```bash
cadclaw assemble validate-spec my_spec.yaml
```

## Top-level fields

| Field | Purpose |
|-------|---------|
| `schema_version` | Must be `assembly_spec.v0.1`. |
| `meta` | `project`, `assembly_id`, `description`. |
| `component_roots` | Directories that `source_path` values resolve against. |
| `connector_metadata` | Path to the connector-frame file. Required for `place_relative_to`. |
| `manifests` | Component manifests indexing an authored STEP library. |
| `outputs` | `step`, `views_dir`, `report`, `design_inventory`, `bom`. |
| `protected_paths` | Paths a build must never overwrite. See below. |
| `instances` | The parts and their placement. |
| `review_views` | Named camera angles to render. |
| `assembly_sequence` | Ordered build steps for `render-sequence`. |
| `constraints` | Declared rules, with `severity` `info` / `warn` / `fail`. |
| `not_built_yet` | Work you know is missing, declared explicitly. |
| `assumptions` | Carried into every report's confidence budget. |
| `variants` / `active_variant` | Named configurations of the same assembly. |
| `bom` | BOM binding for the model-derived bill of materials. |

### `protected_paths`

Assembly outputs are non-authoritative by design. `protected_paths` stops a
build from writing over your real CAD exports — if an output path resolves
inside a protected path, validation fails before anything is written.

### `not_built_yet`

Rather than letting an incomplete assembly look finished, declare what is
missing:

```yaml
not_built_yet:
  - item: belt routing
    reason: Requires explicit path geometry and drive selection.
    required_for_release: true
```

These surface as warnings normally. Run
`cadclaw assemble validate-spec --release` and any item marked
`required_for_release: true` becomes a **failure**. That is the gate between
"in progress" and "shippable."

## Instances

Every instance needs an `id`, a `role`, and either a `component_id` (resolved
through a manifest) or a `source_path` (resolved against `component_roots`).

```yaml
- id: rail_x
  role: rail
  source_path: parts/rail_x.step
  transform:
    translate_mm: [0.0, 0.0, 0.0]
    rotate_deg: [0.0, 0.0, 0.0]
    scale: 1.0
  color_label: frame_black
  notes: Datum rail.
```

Position comes from **either** an absolute `transform` **or** a
`place_relative_to` block. Prefer the latter for everything except your datum.

## Constraint-based placement

`place_relative_to` seats a part against another part's connector frame instead
of typing its coordinates. Positions are then *solved* from the geometry in
front of them, so a change upstream carries the whole chain instead of
invalidating every number downstream.

```yaml
place_relative_to:
  ref: rail_x             # parent instance id
  parent_frame: end_pos_x # connector frame on the parent
  frame: face_neg_x       # connector frame on THIS part
  axis: x                 # handoff axis: x, y, or z
  side: positive          # positive or negative along that axis
  offset_mm: 0.0          # gap along the handoff axis
  lock: frame             # frame (3-axis seat) or axis (axis-only)
```

| Field | Default | Meaning |
|-------|---------|---------|
| `ref` | required | The parent instance's `id`. |
| `parent_frame` | required | Connector frame on the parent. |
| `frame` | required | Connector frame on this instance. |
| `axis` | required | Handoff axis: `x`, `y`, or `z`. |
| `side` | `positive` | Direction of `offset_mm` along `axis`. |
| `offset_mm` | `0.0` | Gap between the seated frames. |
| `lock` | `frame` | How many axes to solve. |
| `rotate_deg` | `[0,0,0]` | Orientation. `lock: frame` only. |
| `scale` | `1.0` | Scale. `lock: frame` only. |
| `source_origin_mm` | `[0,0,0]` | Source-origin correction. `lock: frame` only. |

### `lock: frame` — full 3-axis seat

The child frame origin is made to coincide with the parent frame origin, then
offset along `axis`. All three translation components are solved, so the part
self-centers on the parent's frame.

The instance must **not** also carry an explicit `transform`; author
orientation in the placement block instead. This keeps one source of truth for
where the part is.

### `lock: axis` — axis-only lock

Only the `axis` translation is solved. The instance keeps its own `transform`
for orientation and the two free axes. Use it for a part that hands off along
one axis while spanning the other two, such as a gantry beam that has no
meaningful "seat" in the spanning directions.

The authored value on the locked axis is ignored, since it is solved. In this
mode `rotate_deg`, `scale`, and `source_origin_mm` must stay unset on the
placement block, because orientation lives in the instance `transform`.

### How the chain resolves

`resolve_relative_placements()` walks the datum chain in topological order, so
a parent is always solved before its children and chains can be any depth. The
resolver reports these as findings rather than raising:

| Finding | Cause |
|---------|-------|
| `assemble.relative_placement_cycle` | The chain loops back on itself. |
| `assemble.relative_placement_ref_missing` | `ref` names an instance that does not exist. |
| `assemble.relative_placement_parent_frame_missing` | Parent has no such connector frame. |
| `assemble.relative_placement_frame_missing` | This part has no such connector frame. |

Absolute transforms still work, so migrating an existing assembly is
incremental: convert the parts that are actually coupled and leave the rest.

## Connector metadata

Connector frames are **descriptive data about parts you authored elsewhere**:
extrusion ends, mount faces, rail slots, wheel contacts, shaft axes, belt
planes. CADCLAW reads them to seat parts. It never generates geometry from them.

```yaml
schema_version: connector_metadata.v0.1
components:
  - id: rail_x
    source_path: parts/rail_x.step
    frames:
      - id: end_pos_x
        kind: extrusion_end
        origin_mm: [600.0, 20.0, 20.0]   # in the part's LOCAL coordinates
        tags: [datum, extrusion_end]
        verified: true
```

`verified: false` means the frame is a first pass that has not been checked
against the source CAD. Verify frames against rendered views before trusting
them for placement.

## Review views

`review_views` declares named camera angles. `cadclaw assemble render-views`
renders them to PNG; `check-round` renders them after a successful build.

```yaml
review_views:
  - name: iso
    view: iso        # front, back, side, top, bottom, hero,
                     # iso, iso_left, iso_below, iso_below_left
    width: 1280
    height: 720
    azimuth: 0.0
    elevation: 0.0
```

These renders serve two audiences. For a person, they are the traceability
artifact for a round: what the assembly looked like at that point. For an AI
assistant driving CADCLAW over MCP, the render-producing tools return the PNGs
as inline images, so the model can *see* what it built rather than trusting a
report. See [the MCP server](../README.md#mcp-server).

## The iteration loop

```bash
cadclaw assemble check-round my_spec.yaml
```

One round: build, run the inventory and placement checks, render the review
views, and report. Edit the spec, run it again, look at the renders, repeat.

Exit codes are `0` pass, `1` fail, `2` warn-only, `3` internal error, so the
same command works unchanged in CI.

## Commands

| Command | What it does |
|---------|--------------|
| `assemble validate-spec` | Schema and path checks, no geometry. `--release` gates on `not_built_yet`. |
| `assemble build` | Resolve sources and compile. `--dry-run` resolves without touching geometry. |
| `assemble check-round` | Build, check, render, report. The main loop. |
| `assemble inspect-component` | One component's signature, part count, isolated renders. |
| `assemble render-views` | Render the declared `review_views`. |
| `assemble render-sequence` | Per-step STEPs, per-step renders, BOM CSV, optional GIF. |

Each has an `assemble_*` MCP equivalent.
