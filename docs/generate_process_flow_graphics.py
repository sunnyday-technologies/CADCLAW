"""Generate CADCLAW auto-assembly process-flow graphics.

Outputs PNG and SVG assets under docs/media/. The diagrams are source-controlled
images, not Markdown diagrams, so they can be shared on the site, in slide
decks, or in project docs.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
import math
import textwrap
from typing import Iterable, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(__file__).resolve().parent / "media"
W, H = 1600, 1000

NAVY = "#06111f"
NAVY_2 = "#0d2036"
NAVY_3 = "#183a5e"
GREEN = "#97d700"
GREEN_HI = "#b8f23f"
WHITE = "#f5f8fb"
INK = "#c9d8e5"
MUTED = "#87a4ba"
WARN = "#f0c55b"
FAIL = "#ff6b6b"
BLUE = "#38bdf8"
PANEL = "#0b1828"
PANEL_2 = "#102b45"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_TITLE = _font(44, True)
FONT_SUBTITLE = _font(22, False)
FONT_BOX_TITLE = _font(23, True)
FONT_BODY = _font(18, False)
FONT_SMALL = _font(15, False)
FONT_MONO = _font(15, False)


@dataclass
class Box:
    id: str
    x: int
    y: int
    w: int
    h: int
    title: str
    lines: Sequence[str]
    fill: str = PANEL
    stroke: str = NAVY_3
    accent: str = GREEN

    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    def edge_point_toward(self, other: "Box") -> Tuple[float, float]:
        cx, cy = self.center
        ox, oy = other.center
        dx = ox - cx
        dy = oy - cy
        if dx == 0 and dy == 0:
            return cx, cy
        scale_x = (self.w / 2) / abs(dx) if dx else math.inf
        scale_y = (self.h / 2) / abs(dy) if dy else math.inf
        scale = min(scale_x, scale_y)
        return cx + dx * scale, cy + dy * scale


@dataclass
class Arrow:
    start: str
    end: str
    label: str = ""
    color: str = GREEN


def draw_background(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.rectangle([0, 0, W, H], fill=NAVY)
    draw.rectangle([0, 0, W, 92], fill="#08213c")
    draw.rectangle([0, 92, W, 98], fill=GREEN)
    draw.text((58, 26), title, font=FONT_TITLE, fill=WHITE)
    draw.text((60, 110), subtitle, font=FONT_SUBTITLE, fill=INK)


def wrap_line(line: str, width: int) -> List[str]:
    return textwrap.wrap(line, width=width, break_long_words=False) or [""]


def draw_box(draw: ImageDraw.ImageDraw, box: Box) -> None:
    draw.rounded_rectangle(
        [box.x, box.y, box.x + box.w, box.y + box.h],
        radius=14,
        fill=box.fill,
        outline=box.stroke,
        width=2,
    )
    draw.rectangle([box.x, box.y, box.x + 9, box.y + box.h], fill=box.accent)
    draw.text((box.x + 24, box.y + 18), box.title, font=FONT_BOX_TITLE, fill=WHITE)
    y = box.y + 56
    for line in box.lines:
        for wrapped in wrap_line(line, max(24, box.w // 10)):
            draw.text((box.x + 24, y), wrapped, font=FONT_BODY, fill=INK)
            y += 23
        y += 4


def draw_arrow(draw: ImageDraw.ImageDraw, start: Tuple[float, float],
               end: Tuple[float, float], color: str, label: str = "") -> None:
    sx, sy = start
    ex, ey = end
    draw.line([sx, sy, ex, ey], fill=color, width=4)
    angle = math.atan2(ey - sy, ex - sx)
    head = 15
    left = (
        ex - head * math.cos(angle - math.pi / 6),
        ey - head * math.sin(angle - math.pi / 6),
    )
    right = (
        ex - head * math.cos(angle + math.pi / 6),
        ey - head * math.sin(angle + math.pi / 6),
    )
    draw.polygon([(ex, ey), left, right], fill=color)
    if label:
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        bbox = draw.textbbox((0, 0), label, font=FONT_SMALL)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.rounded_rectangle(
            [mx - tw / 2 - 8, my - th / 2 - 6, mx + tw / 2 + 8, my + th / 2 + 6],
            radius=6,
            fill=NAVY_2,
            outline=NAVY_3,
        )
        draw.text((mx - tw / 2, my - th / 2 - 2), label, font=FONT_SMALL, fill=WHITE)


def draw_diagram(filename: str, title: str, subtitle: str,
                 boxes: Sequence[Box], arrows: Sequence[Arrow],
                 footer: str = "") -> None:
    image = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(image)
    draw_background(draw, title, subtitle)

    by_id = {box.id: box for box in boxes}
    for arrow in arrows:
        a = by_id[arrow.start]
        b = by_id[arrow.end]
        draw_arrow(
            draw,
            a.edge_point_toward(b),
            b.edge_point_toward(a),
            arrow.color,
            arrow.label,
        )
    for box in boxes:
        draw_box(draw, box)
    if footer:
        draw.text((58, H - 48), footer, font=FONT_SMALL, fill=MUTED)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    image.save(OUT_DIR / f"{filename}.png")
    write_svg(filename, title, subtitle, boxes, arrows, footer)


def svg_text_lines(lines: Iterable[str], x: int, y: int, size: int,
                   color: str, weight: str = "400") -> str:
    out = []
    dy = 0
    for line in lines:
        out.append(
            f'<text x="{x}" y="{y + dy}" fill="{color}" '
            f'font-size="{size}" font-family="Arial, sans-serif" '
            f'font-weight="{weight}">{escape(line)}</text>'
        )
        dy += int(size * 1.35)
    return "\n".join(out)


def write_svg(filename: str, title: str, subtitle: str,
              boxes: Sequence[Box], arrows: Sequence[Arrow], footer: str) -> None:
    by_id = {box.id: box for box in boxes}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        "<defs>",
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">',
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{GREEN}" />',
        "</marker>",
        "</defs>",
        f'<rect width="{W}" height="{H}" fill="{NAVY}" />',
        f'<rect width="{W}" height="92" fill="#08213c" />',
        f'<rect y="92" width="{W}" height="6" fill="{GREEN}" />',
        svg_text_lines([title], 58, 58, 44, WHITE, "700"),
        svg_text_lines([subtitle], 60, 132, 22, INK),
    ]
    for arrow in arrows:
        a = by_id[arrow.start]
        b = by_id[arrow.end]
        sx, sy = a.edge_point_toward(b)
        ex, ey = b.edge_point_toward(a)
        parts.append(
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="{arrow.color}" stroke-width="4" marker-end="url(#arrow)" />'
        )
        if arrow.label:
            mx, my = (sx + ex) / 2, (sy + ey) / 2
            parts.append(
                f'<text x="{mx:.1f}" y="{my - 8:.1f}" fill="{WHITE}" '
                f'font-size="15" font-family="Arial, sans-serif" '
                f'text-anchor="middle">{escape(arrow.label)}</text>'
            )
    for box in boxes:
        parts.append(
            f'<rect x="{box.x}" y="{box.y}" width="{box.w}" height="{box.h}" '
            f'rx="14" fill="{box.fill}" stroke="{box.stroke}" stroke-width="2" />'
        )
        parts.append(
            f'<rect x="{box.x}" y="{box.y}" width="9" height="{box.h}" '
            f'fill="{box.accent}" />'
        )
        parts.append(svg_text_lines([box.title], box.x + 24, box.y + 42, 23, WHITE, "700"))
        text_lines: List[str] = []
        for line in box.lines:
            text_lines.extend(wrap_line(line, max(24, box.w // 10)))
            text_lines.append("")
        parts.append(svg_text_lines(text_lines, box.x + 24, box.y + 80, 18, INK))
    if footer:
        parts.append(svg_text_lines([footer], 58, H - 36, 15, MUTED))
    parts.append("</svg>")
    (OUT_DIR / f"{filename}.svg").write_text("\n".join(parts), encoding="utf-8")


def auto_assembly_loop() -> None:
    boxes = [
        Box("intent", 70, 190, 270, 160, "1. Reference Intent",
            ["photo/render", "target envelope", "known constraints"], accent=BLUE),
        Box("library", 445, 190, 300, 160, "2. Authored STEP Library",
            ["CAD/Components", "CAD/Advanced", "Custom STEP assets"], accent=GREEN),
        Box("manifest", 850, 190, 300, 160, "3. Component Manifest",
            ["id + source_path", "bbox signatures", "generation_policy"], accent=GREEN),
        Box("spec", 1255, 190, 280, 160, "4. Assembly Spec",
            ["variant: M3-2", "instances + transforms", "not_built_yet"], accent=WARN),
        Box("compiler", 1255, 465, 280, 170, "5. CadQuery Compiler",
            ["import authored STEP", "place / rotate / pattern", "stock-only generation"], accent=BLUE),
        Box("outputs", 850, 465, 300, 170, "6. Generated Outputs",
            [".step assembly", "design inventory JSON", "BOM draft"], accent=GREEN),
        Box("checks", 445, 465, 300, 170, "7. CADCLAW Checks",
            ["inventory + interference", "floating + orientation", "BOM parity"], accent=FAIL),
        Box("views", 70, 465, 270, 170, "8. Review Views",
            ["front / top / iso PNG", "detail crops", "human spots alignment"], accent=GREEN),
        Box("correct", 600, 740, 390, 150, "9. Human + LLM Correction",
            ["edit spec or connector metadata", "do not hand-edit generated STEP", "rerun the round"], accent=WARN),
    ]
    arrows = [
        Arrow("intent", "library", "select assets"),
        Arrow("library", "manifest", "inspect"),
        Arrow("manifest", "spec", "bind ids"),
        Arrow("spec", "compiler", "compile"),
        Arrow("compiler", "outputs", "export"),
        Arrow("outputs", "checks", "validate"),
        Arrow("checks", "views", "render"),
        Arrow("views", "correct", "review"),
        Arrow("correct", "spec", "revise"),
    ]
    draw_diagram(
        "cadclaw_auto_assembly_loop",
        "CADCLAW Auto-Assembly Loop",
        "General LLM-operable CadQuery harness, with M3-CRETE as the first proving project",
        boxes,
        arrows,
        "M3 targets: M3-1 = 1000 x 1000 x 1000 mm, M3-2 = 2000 x 1000 x 1000 mm, M3-4 = 2000 x 2000 x 1000 mm.",
    )


def data_contracts() -> None:
    boxes = [
        Box("step", 70, 190, 430, 178, "STEP / STP Geometry",
            ["BRep solids/shells; AP242 color optional.",
             "Hidden CAD parts can vanish on export.",
             "Inspect part counts and bbox signatures."], accent=GREEN),
        Box("manifest", 585, 190, 430, 178, "component_manifest.yaml",
            ["YAML registry of authored assets.",
             "id, source_path, category, bbox sig.",
             "Stops duplicates and unsafe generation."], accent=BLUE),
        Box("spec", 1100, 190, 430, 178, "assembly_spec.yaml",
            ["Strict YAML build contract.",
             "Variants, instances, transforms, outputs.",
             "Assumptions and not_built_yet stay visible."], accent=WARN),
        Box("connectors", 70, 465, 430, 178, "connector_metadata.yaml",
            ["Planned local frames and mates.",
             "Rail ends, mount faces, shaft axes.",
             "Replaces placement guessing with frames."], accent=FAIL),
        Box("bom", 585, 465, 430, 178, "BOM JSON + Variant Config",
            ["Public BOM plus variant overrides.",
             "M3-2 base; M3-1/M3-4 overrides.",
             "Private procurement fields stay redacted."], accent=GREEN),
        Box("reports", 1100, 465, 430, 178, "Reports + Review Images",
            ["report.json, inventory.json, PNG views.",
             "Findings plus confidence budget.",
             "Human review catches alignment misses."], accent=BLUE),
        Box("guards", 340, 768, 900, 126, "File Formatting Rules That Matter",
            ["Never overwrite CAD exports. Prefer AP242 when color matters. Missing work is not_built_yet, not a silent placeholder. File-size drops require signature, count, and view checks."],
            fill=PANEL_2, accent=GREEN_HI),
    ]
    arrows = [
        Arrow("step", "manifest", "inspect"),
        Arrow("manifest", "spec", "bind"),
        Arrow("spec", "connectors", "needs frames", WARN),
        Arrow("connectors", "bom", "derive qty", GREEN),
        Arrow("bom", "reports", "audit", GREEN),
        Arrow("spec", "reports", "validate", BLUE),
        Arrow("reports", "guards", "lessons"),
    ]
    draw_diagram(
        "cadclaw_data_contracts",
        "CADCLAW Data Contracts",
        "Explicit file types and fields that control assembly accuracy",
        boxes,
        arrows,
        "Core idea: LLMs edit structured specs and metadata; CADCLAW compiles, validates, renders, and reports.",
    )


def development_evolution() -> None:
    boxes = [
        Box("initial", 70, 210, 245, 190, "Initial Harness",
            ["STEP geometry checks", "inventory", "interference", "adjacency"], accent=BLUE),
        Box("v06", 375, 210, 245, 190, "v0.6 Honest Core",
            ["unified findings", "BOM-vs-CAD audit", "claim/publish audit"], accent=GREEN),
        Box("v07", 680, 210, 245, 190, "v0.7 Field Polish",
            ["BOM semantics", "negation-aware claims", "design vs spare qty"], accent=WARN),
        Box("v071", 985, 210, 245, 190, "v0.7.1 Usability",
            ["inspect subcommands", "interference fix vectors", "AGENTS.md guardrails"], accent=GREEN),
        Box("v08", 1290, 210, 245, 190, "v0.8 Naming",
            ["cadclaw module", "compat shim", "clear package identity"], accent=BLUE),
        Box("v09", 230, 535, 300, 190, "v0.9 Validation Gates",
            ["orientation / face mates", "floating parts", "AP242 color checks"], accent=FAIL),
        Box("today", 650, 535, 300, 190, "Current Build-Out",
            ["assembly spec schema", "component manifest", "M3 variants + BOM plan"], accent=WARN),
        Box("next", 1070, 535, 300, 190, "Next Capability",
            ["connector metadata", "CadQuery placement compiler", "review-view round trip"], accent=GREEN),
        Box("lesson", 360, 805, 880, 120, "Design Lesson Now Built Into The Tool",
            ["AI should place authored STEP parts and edit typed specs. CADCLAW checks the exported assembly, reports uncertainty, and keeps physical validation separate."],
            fill=PANEL_2, accent=GREEN_HI),
    ]
    arrows = [
        Arrow("initial", "v06", "formalize"),
        Arrow("v06", "v07", "field test"),
        Arrow("v07", "v071", "make usable"),
        Arrow("v071", "v08", "rename"),
        Arrow("v08", "v09", "new gates"),
        Arrow("v09", "today", "assemble"),
        Arrow("today", "next", "complete loop"),
        Arrow("next", "lesson", "operating rule", GREEN),
    ]
    draw_diagram(
        "cadclaw_development_evolution",
        "CADCLAW Development Evolution",
        "From STEP validation to an AI-guided assembly harness for functional structures",
        boxes,
        arrows,
        "Audience takeaway: CAD designers keep native CAD authority; novice AI users get guardrails, rendered checks, and explicit assumptions.",
    )


def capability_stack() -> None:
    boxes = [
        Box("cad", 105, 180, 340, 145, "CAD Designer Layer",
            ["native CAD authors real geometry", "exports STEP as shared interface", "CAD file remains source of truth"], accent=BLUE),
        Box("assets", 515, 180, 340, 145, "Asset Registry Layer",
            ["manifest lists authored STEP", "bbox signatures and categories", "Advanced + Components libraries"], accent=GREEN),
        Box("spec", 925, 180, 340, 145, "Intent Layer",
            ["assembly_spec.yaml", "variants: M3-1 / M3-2 / M3-4", "explicit outputs and assumptions"], accent=WARN),
        Box("llm", 515, 385, 340, 145, "AI Operator Layer",
            ["edits structured YAML", "uses inspect and reports", "does not invent contextual plates"], accent=FAIL),
        Box("compiler", 105, 590, 340, 145, "CadQuery Placement Layer",
            ["imports authored STEP", "places, rotates, mirrors, patterns", "generates stock only by policy"], accent=GREEN),
        Box("validation", 515, 590, 340, 145, "CADCLAW Check Layer",
            ["inventory, interference, floating", "orientation, color, parity", "BOM, claim, publish audits"], accent=BLUE),
        Box("outputs", 925, 590, 340, 145, "Builder Output Layer",
            ["configured STEP", "review PNG/GIF views", "public BOM and confidence report"], accent=GREEN),
        Box("novice", 1120, 385, 340, 145, "Novice Designer Value",
            ["prompt from a reference photo", "see every assumption", "iterate with visual checkpoints"], accent=GREEN_HI),
        Box("boundary", 350, 805, 900, 120, "Guardrail Boundary",
            ["CADCLAW is decision support for exported CAD and BOMs. It can find drift, omissions, and clashes, but physical performance still requires engineering and build validation."],
            fill=PANEL_2, accent=WARN),
    ]
    arrows = [
        Arrow("cad", "assets", "inspect"),
        Arrow("assets", "spec", "select"),
        Arrow("spec", "llm", "edit"),
        Arrow("llm", "compiler", "compile"),
        Arrow("compiler", "validation", "check"),
        Arrow("validation", "outputs", "emit"),
        Arrow("outputs", "novice", "review"),
        Arrow("novice", "spec", "revise"),
        Arrow("validation", "boundary", "confidence"),
    ]
    draw_diagram(
        "cadclaw_capability_stack",
        "CADCLAW Capability Stack",
        "What designers and AI-assisted beginners get from the same workflow",
        boxes,
        arrows,
        "For M3-CRETE: current focus is the M3-2 2000 x 1000 x 1000 mm target, with M3-1 and M3-4 variants tracked as configuration classes.",
    )


def cad_system_monitoring() -> None:
    boxes = [
        Box("cad", 70, 190, 330, 170, "Any CAD System",
            ["Fusion 360", "Rhino / FreeCAD", "SolidWorks / Onshape"], accent=BLUE),
        Box("export", 510, 190, 330, 170, "STEP Export",
            ["*.step / *.stp", "AP242 preferred for color", "exported state, not native truth"], accent=GREEN),
        Box("inspect", 950, 190, 330, 170, "CADCLAW Inspect",
            ["part count", "bbox signature histogram", "colors and dimensions"], accent=GREEN),
        Box("parity", 1170, 465, 330, 170, "Parity + Drift Checks",
            ["compare prior/golden STEP", "missing or extra signatures", "file-size drift signal"], accent=WARN),
        Box("findings", 730, 465, 330, 170, "Structured Findings",
            ["visibility omission", "orientation/color drift", "BOM-vs-CAD mismatch"], accent=FAIL),
        Box("actions", 290, 465, 330, 170, "Update Actions",
            ["re-export CAD", "update manifest/spec", "approve new asset"], accent=BLUE),
        Box("assembly", 290, 740, 970, 130, "Assembly Round",
            ["Compile with CadQuery, render review views, run validation, produce BOM/design inventory. If views or findings are wrong, the LLM edits the spec or connector metadata and repeats."],
            fill=PANEL_2, accent=GREEN),
    ]
    arrows = [
        Arrow("cad", "export", "export"),
        Arrow("export", "inspect", "read"),
        Arrow("inspect", "parity", "compare"),
        Arrow("parity", "findings", "emit"),
        Arrow("findings", "actions", "decide"),
        Arrow("actions", "assembly", "feed"),
        Arrow("assembly", "cad", "CAD change if needed", WARN),
    ]
    draw_diagram(
        "cadclaw_cad_system_monitoring",
        "CAD-System STEP Monitoring",
        "How CADCLAW works with any CAD system by watching exported STEP files",
        boxes,
        arrows,
        "Important lesson: a smaller STEP can be good geometry cleanup or a missing-part export. Check signatures, counts, and review views before trusting it.",
    )


def main() -> None:
    auto_assembly_loop()
    data_contracts()
    development_evolution()
    capability_stack()
    cad_system_monitoring()
    print(f"Wrote graphics to {OUT_DIR}")


if __name__ == "__main__":
    main()
