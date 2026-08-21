# AGENTS.md — guidance for AI assistants using CADCLAW

You are an AI assistant working inside (or on behalf of) a project that
uses CADCLAW. This file is the **load-bearing policy** for how you
should behave when adding or editing CAD geometry. Read it before any
geometry-touching work.

> **Before editing this repository at all, read [`AGENTS_GIT_PROTOCOL.md`](AGENTS_GIT_PROTOCOL.md).**
> More than one agent works here from more than one clone. GitHub is the shared
> memory; your working copy is not. Fetch first, commit what you validate, never
> force-push.

---

## What CADCLAW is, and what it is not

CADCLAW is an **assembly and validation tool** for STEP assemblies and BOMs.
Two halves, both first-class:

1. **Assemble.** `cadclaw assemble` compiles a declarative assembly spec into
   a STEP file. It resolves authored STEP sources, seats each part by
   connector frames and datum chains (`place_relative_to`), and writes the
   assembly plus a design inventory, a model-derived BOM, review renders,
   and step-by-step build sequences.
2. **Validate.** It loads a STEP file and reports findings against rules in
   `cadclaw.yaml`: inventory, interference, adjacency, dimensions,
   orientation, floating, color, structural, tolerance, BOM-vs-CAD parity,
   claim-audit, publish-audit.

CADCLAW is **not** a CAD authoring system. It does not draw parts. It
does not own bolt-circle constants, hole-drilling helpers, or NEMA
mounting templates.

Hold this distinction precisely: **assembling is in scope, authoring is not.**
Placing a part the user drew is CADCLAW's job. Creating that part's geometry
is not. Do not describe CADCLAW as "only a validator" (it builds assemblies)
or as a "CAD generator" (it never creates geometry).

---

## The core rule: place authored parts, don't generate them

**Default to placement, not generation.** The user authors complex
geometry in a native CAD package and exports a STEP. CADCLAW's own assembly
compiler (`cadclaw/assembly_compiler.py`, driven by an `assembly_spec.v0.1`
YAML) then places copies of those authored parts into the assembly, and
CADCLAW verifies the placement. An external CadQuery script still works, but
the spec-driven compiler is the supported path.

When asked to add a part, your first move is **"where is the authored
STEP for this?"** — not **"let me write a `cq.Workplane().rect(...)`
recipe."**

If no authored STEP exists yet, ask the user whether they want to
author it before you build anything parametric.

### Why this rule exists

Field-test evidence (M3-CRETE, 2026-04-26): a session pursued
parametric Y-mount, Z-mount, and bottom-mount plate generation. Three
rounds of generate → critique → strip later, the shipping code was
*less* code than the start, and the user had hand-authored the plates
in the native CAD model in the time it took to write the parametric recipe. Hole
patterns generated against assumed motor positions were uniformly
wrong.

The trap is that parametric generation **looks** like the
high-leverage move ("I'll just compute the bolt circle from the NEMA23
spec"), but in practice the constraints that survive contact with the
real assembly — clearance, motor-shaft offset, mating-part interfaces,
local extrusion-channel geometry — are not in any spec; they're in the
user's CAD model. Generating from spec produces parts that look right
in isolation and don't fit the assembly.

---

## What you may generate

A small, opinionated list. Anything outside this list, defer to
authored STEP.

- **Linear extrusion stock** — C-beam / V-slot bars cut to length.
  These are genuinely parametric: cross-section is fixed, length is
  the only variable. CADCLAW's typical projects label these as `cbeam`.
- **V-wheels** — fixed-geometry rolling elements. Same argument.
- **Belt segments** — already special-cased by `belt_heuristic`.
- **Standard fastener stand-ins** — only if the project explicitly
  declares it wants generated fastener bodies (most do not; CADCLAW's
  BOM-audit does the fastener accounting from text, not geometry).

Anything else — plates, brackets, mounts, gussets, motor adapters,
spacers with bolt patterns, idler holders — author in the native CAD
package and place via STEP.

---

## What you must not generate

- **Plates with hole patterns.** "Make a 4mm plate with NEMA23 holes"
  is the canonical wrong move. Hole positions depend on the plate's
  context in the assembly (motor shaft offset, V-slot alignment), not
  the spec.
- **Brackets.** Same reasoning.
- **NEMA bolt-circle helpers.** Don't write
  `nema23_bolt_circle()`-style functions. The bolt-circle dimensions
  are public spec data; the *positions where you'd drill them* are
  always assembly-context-dependent.
- **"Stand-in" geometry that the user didn't ask for.** Cylinder
  approximations of authored V-wheels, rectangular approximations of
  triangular gussets, etc. CADCLAW's `parity` gate exists to catch
  these; don't introduce them.

If you find yourself reaching for `cq.Workplane().box(...).faces(...).
hole(...)`, stop. Ask the user.

---

## The intended workflow

1. **User authors** the geometry in a native CAD or STEP-capable package.
2. **User exports** a STEP — typically the whole assembly, or one
   sub-assembly per file.
3. **Assembly script** (CadQuery / build123d / etc.) imports the
   authored STEP, places copies via translation/rotation, and emits a
   final assembly STEP.
4. **CADCLAW runs** against the assembly STEP: inventory, interference,
   adjacency, BOM audit, etc.
5. **Findings drive iteration.** Failed gates point at concrete fixes
   (e.g. interference clip → "shift +Y by 1.35 mm"). The user updates
   the native model, re-exports, the script re-places, CADCLAW re-runs.

Your job is steps 3 and 4. You may also help interpret the findings in
step 5 — propose specific shifts, label new bbox signatures, propose
BOM updates. You should not be doing step 1.

---

## Honesty extensions for agents

CADCLAW emphasizes a "confidence budget" — every report says what was
checked, what was not, and what was assumed. Mirror this in your work:

- When you place a part, name the authored STEP it came from.
- When you propose a fix, cite the specific finding (`interference.clip`
  with `evidence.suggest_shift`).
- When you don't know whether a part is authored or stand-in, ask.
- Don't fabricate confidence ("the bolt pattern is standard NEMA23"
  is not evidence that the holes are *in the right place* in *this*
  assembly).

The harness already gives you a `cadclaw inspect` subcommand for
reading state without writing anything. Use it. It replaces what would
otherwise be a throwaway probe script.

---

## Pointers

- **README.md** — what CADCLAW is, top-level.
- **cadclaw.yaml** — declarative project config (labels, regions,
  expected inventory, BOM rules, interference clearance).
- **examples/init_rules.py** — scaffolds a starter `cadclaw.yaml` from
  a STEP file. Read-only; observation-based; safe.
- **examples/m3_crete/check.py** — reference harness wiring. Pure
  placement + verification, no generation.

If something in CADCLAW's own docs or examples looks like it's
encouraging generation (NEMA bolt-circle helpers, hole-drilling
templates, etc.), file an issue. The bias should not exist.
