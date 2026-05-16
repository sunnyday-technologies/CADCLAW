"""
`cadclaw` CLI dispatcher — argparse subcommands, stdlib only.

Subcommands:
  cadclaw doctor                                 # env diagnostic
  cadclaw bom-audit      --rules cadclaw.yaml    # BOM-vs-CAD gate
  cadclaw parity         <a.step> <b.step>       # STEP-vs-STEP comparison
  cadclaw claim-audit    --rules cadclaw.yaml    # text linter for docs/BOM notes
  cadclaw publish-audit  --rules cadclaw.yaml    # private-data boundary scan
  cadclaw inventory      --rules cadclaw.yaml    # part counts + regions
  cadclaw harness        --rules cadclaw.yaml    # union runner
  cadclaw inspect sigs|part|overlaps|cluster <step>  # diagnostic queries

Exit codes:
  0  — pass
  1  — at least one fail
  2  — warn-only (no fails, >= 1 warn)
  3  — internal error / bad rules / missing input
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from cadclaw.findings import Report, Severity
from cadclaw.reporters import render_json, render_markdown, render_text


def _exit_code_for(report: Report) -> int:
    if report.overall == Severity.FAIL:
        return 1
    if report.overall == Severity.WARN:
        return 2
    return 0


def _emit_report(report: Report, fmt: str, out: Optional[str]) -> None:
    if fmt == "json":
        body = render_json(report)
    elif fmt in ("md", "markdown"):
        body = render_markdown(report)
    else:
        body = render_text(report)

    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(body)
            if not body.endswith("\n"):
                f.write("\n")
    else:
        print(body)


def _add_format_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--report-format", choices=("text", "md", "json"), default="text")
    p.add_argument("-o", "--out", default=None,
                   help="Write report to this path instead of stdout.")


def _cmd_doctor(args: argparse.Namespace) -> int:
    from cadclaw.doctor import run_doctor
    report = run_doctor()
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_parity(args: argparse.Namespace) -> int:
    from cadclaw.parity import compare_steps
    from cadclaw.findings import Finding
    parity = compare_steps(args.step_a, args.step_b)
    findings: List[Finding] = []
    for sig, count in parity.only_in_a:
        findings.append(Finding(
            id="parity.only_in_a",
            category="parity",
            severity=Severity.FAIL,
            message=f"sig {sig} present in A by {count} more than B",
            evidence={"sig": list(sig), "delta": count, "a_path": parity.a_path},
        ))
    for sig, count in parity.only_in_b:
        findings.append(Finding(
            id="parity.only_in_b",
            category="parity",
            severity=Severity.FAIL,
            message=f"sig {sig} present in B by {count} more than A",
            evidence={"sig": list(sig), "delta": count, "b_path": parity.b_path},
        ))
    if parity.size_shrunk_warning:
        findings.append(Finding(
            id="parity.visibility_toggle",
            category="parity",
            severity=Severity.WARN,
            message=parity.size_shrunk_warning,
        ))
    report = Report(
        findings=findings,
        meta={"a": args.step_a, "b": args.step_b,
              "a_parts": parity.a_parts, "b_parts": parity.b_parts},
    )
    report.overall = report.compute_overall()
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_inventory(args: argparse.Namespace) -> int:
    from cadclaw.rules import load_rules
    from cadclaw.inventory import InventoryCheck, Region
    from cadclaw.findings import Finding

    rules = load_rules(args.rules)
    if not rules.expected_inventory:
        print("error: rule file has no `expected_inventory:` section", file=sys.stderr)
        return 3
    step_path = args.step or rules.meta.step
    if not step_path:
        print("error: --step or rules.meta.step required", file=sys.stderr)
        return 3

    sig_to_label = rules.sig_to_label()
    label_dict = {sig: name for sig, name in sig_to_label.items()}

    regions = [
        Region(
            name=r.name,
            x_range=tuple(r.x_range) if r.x_range else None,
            y_range=tuple(r.y_range) if r.y_range else None,
            z_range=tuple(r.z_range) if r.z_range else None,
            expected=dict(r.expected),
        )
        for r in rules.regions
    ] or None

    check = InventoryCheck(step_path, label_dict, dict(rules.expected_inventory),
                           belt_heuristic=rules.belt_heuristic, regions=regions)
    result = check.run()

    findings: List[Finding] = []
    for m in result.mismatches:
        findings.append(Finding(
            id="inventory.count_mismatch",
            category="inventory",
            severity=Severity.FAIL,
            message=m,
        ))
    for region_name, region_result in result.region_results.items():
        for m in region_result.mismatches:
            findings.append(Finding(
                id="inventory.region_count_mismatch",
                category="inventory",
                severity=Severity.FAIL,
                message=f"region {region_name}: {m}",
                evidence={"region": region_name},
            ))
    report = Report(
        findings=findings,
        meta={"step": step_path, "total_parts": result.total_parts,
              "inventory": result.inventory},
    )
    report.overall = report.compute_overall()
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_bom_audit(args: argparse.Namespace) -> int:
    from cadclaw.rules import load_rules
    rules = load_rules(args.rules)
    bom_path = args.bom or rules.bom_audit.bom_path
    if not bom_path:
        print("error: --bom or rules.bom_audit.bom_path required", file=sys.stderr)
        return 3
    step_path = args.step or rules.meta.step
    if not step_path:
        print("error: --step or rules.meta.step required", file=sys.stderr)
        return 3
    from cadclaw.bom_audit import run_bom_audit
    report = run_bom_audit(bom_path=bom_path, step_path=step_path, rules=rules)
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_assemble_validate_spec(args: argparse.Namespace) -> int:
    from pathlib import Path
    from cadclaw.assembly_spec import load_assembly_spec
    from cadclaw.findings import ConfidenceBudget, Finding

    try:
        spec = load_assembly_spec(args.spec)
    except Exception as exc:
        print(f"error: invalid assembly spec: {exc}", file=sys.stderr)
        return 3

    findings: List[Finding] = []

    for ref in spec.reference_assets:
        if not Path(ref.path).exists():
            findings.append(Finding(
                id="assemble.reference_missing",
                category="assemble",
                severity=Severity.WARN,
                message=f"reference asset not found: {ref.path}",
                evidence={"path": ref.path, "role": ref.role},
            ))

    for manifest in spec.manifests:
        if not Path(manifest).exists():
            findings.append(Finding(
                id="assemble.manifest_missing",
                category="assemble",
                severity=Severity.WARN,
                message=f"component manifest not found: {manifest}",
                evidence={"path": manifest},
            ))

    if spec.connector_metadata and not Path(spec.connector_metadata).exists():
        findings.append(Finding(
            id="assemble.connector_metadata_missing",
            category="assemble",
            severity=Severity.WARN,
            message=f"connector metadata not found: {spec.connector_metadata}",
            evidence={"path": spec.connector_metadata},
        ))

    for root in spec.component_roots:
        if not Path(root).exists():
            findings.append(Finding(
                id="assemble.component_root_missing",
                category="assemble",
                severity=Severity.WARN,
                message=f"component root not found: {root}",
                evidence={"path": root},
            ))

    missing_release_items = []
    for item in spec.not_built_yet:
        severity = Severity.FAIL if args.release and item.required_for_release else Severity.WARN
        if item.required_for_release:
            missing_release_items.append(item.item)
        findings.append(Finding(
            id="assemble.not_built_yet",
            category="assemble",
            severity=severity,
            message=f"{item.item}: {item.reason}",
            evidence={
                "item": item.item,
                "required_for_release": item.required_for_release,
            },
        ))

    for constraint in spec.constraints:
        if constraint.severity == "info":
            severity = Severity.PASS
        elif constraint.severity == "warn":
            severity = Severity.WARN
        else:
            # A constraint is not a failure merely by existing; it is a rule the
            # future compiler must enforce. Surface it as checked context here.
            continue
        findings.append(Finding(
            id="assemble.constraint_declared",
            category="assemble",
            severity=severity,
            message=constraint.rule,
            evidence={
                "constraint_id": constraint.id,
                "applies_to_variants": constraint.applies_to_variants,
            },
        ))

    confidence = ConfidenceBudget(
        checked=[
            "assembly spec schema",
            "protected output path validation",
            "reference asset path presence",
            "component manifest path presence",
            "connector metadata path presence",
            "component root path presence",
            "variant declaration",
        ],
        not_checked=[
            "CadQuery geometry compilation",
            "connector metadata completeness",
            "interference",
            "BOM-vs-CAD parity",
            "rendered view alignment",
        ],
        assumptions=list(spec.assumptions),
    )
    report = Report(
        findings=findings,
        confidence_budget=confidence,
        meta={
            "spec": args.spec,
            "project": spec.meta.project,
            "assembly_id": spec.meta.assembly_id,
            "active_variant": spec.active_variant,
            "variants": [
                {"id": v.id, "envelope_mm": v.envelope_mm}
                for v in spec.variants
            ],
            "instances": len(spec.instances),
            "not_built_yet": len(spec.not_built_yet),
            "missing_release_items": missing_release_items,
            "outputs": spec.outputs.model_dump(exclude_none=True),
            "connector_metadata": spec.connector_metadata,
            "bom": spec.bom.model_dump(exclude_none=True),
        },
    )
    report.overall = report.compute_overall()
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_assemble_build(args: argparse.Namespace) -> int:
    from cadclaw.assembly_compiler import run_assembly_build

    try:
        report = run_assembly_build(
            args.spec,
            connector_metadata_path=args.connector_metadata,
            dry_run=args.dry_run,
            write_inventory=args.write_design_inventory,
        )
    except Exception as exc:
        print(f"error: assembly build failed: {exc}", file=sys.stderr)
        return 3
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_assemble_inspect_component(args: argparse.Namespace) -> int:
    from cadclaw.assembly_compiler import inspect_component

    try:
        views = [v.strip() for v in args.views.split(",") if v.strip()]
        report = inspect_component(
            args.spec,
            component_id=args.component_id,
            source_path=args.source_path,
            render_views=args.render_views,
            views=views or None,
            views_dir=args.views_dir,
        )
    except Exception as exc:
        print(f"error: component inspection failed: {exc}", file=sys.stderr)
        return 3
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_assemble_render_views(args: argparse.Namespace) -> int:
    from cadclaw.assembly_compiler import render_review_views

    try:
        report = render_review_views(
            args.spec,
            step_path=args.step,
            views_dir=args.views_dir,
        )
    except Exception as exc:
        print(f"error: review view rendering failed: {exc}", file=sys.stderr)
        return 3
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_assemble_check_round(args: argparse.Namespace) -> int:
    from cadclaw.assembly_compiler import run_assembly_check_round

    try:
        report = run_assembly_check_round(
            args.spec,
            connector_metadata_path=args.connector_metadata,
            dry_run=args.dry_run,
            write_inventory=not args.no_inventory,
            render_views=not args.no_render_views,
            write_report=args.write_report,
        )
    except Exception as exc:
        print(f"error: assembly check round failed: {exc}", file=sys.stderr)
        return 3
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_assemble_render_sequence(args: argparse.Namespace) -> int:
    from cadclaw.assembly_compiler import run_assembly_sequence

    try:
        views = [v.strip() for v in args.views.split(",") if v.strip()]
        report = run_assembly_sequence(
            args.spec,
            output_dir=args.output_dir,
            view_names=views or None,
            dry_run=args.dry_run,
            render_views=not args.no_render_views,
            rotate_final=args.rotate_final,
            bom_csv_path=args.bom_csv,
            write_bom=not args.no_bom,
        )
    except Exception as exc:
        print(f"error: assembly sequence render failed: {exc}", file=sys.stderr)
        return 3
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_claim_audit(args: argparse.Namespace) -> int:
    from cadclaw.rules import load_rules
    rules = load_rules(args.rules)
    from cadclaw.claim_audit import run_claim_audit
    report = run_claim_audit(rules, repo_root=args.repo)
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_publish_audit(args: argparse.Namespace) -> int:
    from cadclaw.rules import load_rules
    rules = load_rules(args.rules)
    from cadclaw.publish_audit import run_publish_audit
    report = run_publish_audit(rules, repo_root=args.repo)
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_harness(args: argparse.Namespace) -> int:
    """Union runner — runs YAML-backed checks that the rule file configures."""
    import time
    from cadclaw.findings import Finding, ConfidenceBudget
    from cadclaw.rules import load_rules

    t0 = time.time()
    rules = load_rules(args.rules)

    only = set(args.only.split(",")) if args.only else None
    skip = set(args.skip.split(",")) if args.skip else set()

    def _wants(name: str) -> bool:
        if only is not None and name not in only:
            return False
        if name in skip:
            return False
        return True

    aggregate = Report(meta={"project": rules.meta.project or "",
                             "rules": args.rules})
    aggregate.confidence_budget = ConfidenceBudget(
        checked=[],
        not_checked=list(rules.confidence_budget.not_checked),
        assumptions=list(rules.confidence_budget.assumptions),
    )

    if _wants("inventory") and rules.expected_inventory:
        sub_args = argparse.Namespace(rules=args.rules, step=None,
                                       report_format="json", out=None)
        # Reuse the inventory subcommand's logic by importing it inline.
        # We just need the findings, so call into the same path:
        from cadclaw.inventory import InventoryCheck, Region
        sig_to_label = rules.sig_to_label()
        label_dict = {sig: name for sig, name in sig_to_label.items()}
        regions = [
            Region(
                name=r.name,
                x_range=tuple(r.x_range) if r.x_range else None,
                y_range=tuple(r.y_range) if r.y_range else None,
                z_range=tuple(r.z_range) if r.z_range else None,
                expected=dict(r.expected),
            )
            for r in rules.regions
        ] or None
        step_path = rules.meta.step
        if step_path:
            check = InventoryCheck(step_path, label_dict,
                                   dict(rules.expected_inventory),
                                   belt_heuristic=rules.belt_heuristic,
                                   regions=regions)
            result = check.run()
            for m in result.mismatches:
                aggregate.add(Finding("inventory.count_mismatch", "inventory",
                                       Severity.FAIL, m))
            for region_name, rr in result.region_results.items():
                for m in rr.mismatches:
                    aggregate.add(Finding("inventory.region_count_mismatch",
                                           "inventory", Severity.FAIL,
                                           f"region {region_name}: {m}",
                                           evidence={"region": region_name}))
            aggregate.confidence_budget.checked.append("inventory")
        else:
            aggregate.confidence_budget.not_checked.append(
                "inventory (no rules.meta.step set)"
            )
    elif _wants("inventory"):
        aggregate.confidence_budget.not_checked.append(
            "inventory (no expected_inventory in rules)"
        )

    if _wants("bom_audit") and rules.bom_audit.rules:
        from cadclaw.bom_audit import run_bom_audit
        bom_path = rules.bom_audit.bom_path
        step_path = rules.meta.step
        if bom_path and step_path:
            sub = run_bom_audit(bom_path=bom_path, step_path=step_path, rules=rules)
            aggregate.findings.extend(sub.findings)
            aggregate.confidence_budget.checked.append("bom_audit")
        else:
            aggregate.confidence_budget.not_checked.append(
                "bom_audit (missing bom_path or step path)"
            )
    elif _wants("bom_audit"):
        aggregate.confidence_budget.not_checked.append(
            "bom_audit (no rules in cadclaw.yaml)"
        )

    if _wants("claim_audit") and rules.claim_audit.scan_paths:
        from cadclaw.claim_audit import run_claim_audit
        sub = run_claim_audit(rules, repo_root=args.repo)
        aggregate.findings.extend(sub.findings)
        aggregate.confidence_budget.checked.append("claim_audit")
    elif _wants("claim_audit"):
        aggregate.confidence_budget.not_checked.append(
            "claim_audit (no scan_paths in rules)"
        )

    if _wants("publish_audit") and (rules.publish_audit.ignore_globs
                                    or rules.publish_audit.scan_globs):
        from cadclaw.publish_audit import run_publish_audit
        sub = run_publish_audit(rules, repo_root=args.repo)
        aggregate.findings.extend(sub.findings)
        aggregate.confidence_budget.checked.append("publish_audit")
    elif _wants("publish_audit"):
        aggregate.confidence_budget.not_checked.append(
            "publish_audit (no globs configured)"
        )

    # v0.9 gates need a shared label_fn + parts. Build once, reuse.
    label_specs = rules.label_specs()
    has_orientation = any(s.expected_face for s in label_specs.values())
    has_floating = bool(rules.floating_check.structural_labels)
    step_path = rules.meta.step

    _v09_parts = None
    _v09_label_fn = None

    def _ensure_v09_loaded():
        nonlocal _v09_parts, _v09_label_fn
        if _v09_parts is not None:
            return True
        if not step_path:
            return False
        from cadclaw.inventory import load_and_dedup, sig as _sig
        sig_to_label = rules.sig_to_label()
        belt_heuristic = rules.belt_heuristic

        def _label_fn(part):
            d = _sig(part)
            if d in sig_to_label:
                return sig_to_label[d]
            if belt_heuristic and len(d) >= 2 and d[0] == 1.5 and d[1] == 6.0:
                return "belt"
            return "other"

        _v09_parts = load_and_dedup(step_path)
        _v09_label_fn = _label_fn
        return True

    # v0.9 gate #1 — orientation. Runs only when at least one label has
    # `expected_face` set.
    if _wants("orientation") and has_orientation:
        from cadclaw.orientation import OrientationCheck
        from cadclaw.harness import _orientation_findings
        if _ensure_v09_loaded():
            check = OrientationCheck(_v09_parts, _v09_label_fn, label_specs)
            sub = check.run()
            aggregate.findings.extend(_orientation_findings(sub))
            aggregate.confidence_budget.checked.append("orientation")
        else:
            aggregate.confidence_budget.not_checked.append(
                "orientation (no rules.meta.step set)"
            )
    elif _wants("orientation"):
        aggregate.confidence_budget.not_checked.append(
            "orientation (no labels carry expected_face)"
        )

    # v0.9 gate #3 — floating-part. Runs only when structural_labels is
    # non-empty.
    if _wants("floating") and has_floating:
        from cadclaw.floating import FloatingCheck
        from cadclaw.harness import _floating_findings
        if _ensure_v09_loaded():
            check = FloatingCheck(
                _v09_parts, _v09_label_fn,
                structural_labels=set(rules.floating_check.structural_labels),
                max_gap_mm=rules.floating_check.max_gap_mm,
                exempt_labels=set(rules.floating_check.exempt_labels),
            )
            sub = check.run()
            aggregate.findings.extend(_floating_findings(sub))
            aggregate.confidence_budget.checked.append("floating")
        else:
            aggregate.confidence_budget.not_checked.append(
                "floating (no rules.meta.step set)"
            )
    elif _wants("floating"):
        aggregate.confidence_budget.not_checked.append(
            "floating (no structural_labels configured)"
        )

    # v0.9 gate #2 — color/material attribute check. Runs only when at
    # least one label has expected_color set.
    has_color = any(s.expected_color for s in label_specs.values())
    if _wants("color") and has_color:
        from cadclaw.color_check import ColorCheck
        from cadclaw.harness import _color_findings
        if step_path:
            check = ColorCheck(step_path, label_specs)
            sub = check.run()
            aggregate.findings.extend(_color_findings(sub))
            aggregate.confidence_budget.checked.append("color")
        else:
            aggregate.confidence_budget.not_checked.append(
                "color (no rules.meta.step set)"
            )
    elif _wants("color"):
        aggregate.confidence_budget.not_checked.append(
            "color (no labels carry expected_color)"
        )

    aggregate.overall = aggregate.compute_overall()
    aggregate.duration_ms = (time.time() - t0) * 1000
    _emit_report(aggregate, args.report_format, args.out)
    return _exit_code_for(aggregate)


def _parse_xyz(text: str, flag: str) -> tuple:
    """Parse 'X,Y,Z' (or 'X Y Z') into a 3-float tuple. Raises SystemExit on error."""
    bits = [b.strip() for b in text.replace(" ", ",").split(",") if b.strip()]
    if len(bits) != 3:
        print(f"error: {flag} expects 'X,Y,Z' (got {text!r})", file=sys.stderr)
        raise SystemExit(3)
    try:
        return tuple(float(b) for b in bits)
    except ValueError:
        print(f"error: {flag} values must be numeric (got {text!r})", file=sys.stderr)
        raise SystemExit(3)


def _resolve_label_fn(rules_path: str | None):
    """Build a label_fn from cadclaw.yaml labels, or fall back to bbox-only."""
    from cadclaw.inventory import sig

    if not rules_path:
        return lambda part: ""

    from cadclaw.rules import load_rules
    rules = load_rules(rules_path)
    sig_to_label = rules.sig_to_label()

    def label_fn(part):
        d = sig(part)
        if len(d) == 3:
            key = (d[0], d[1], d[2])
            if key in sig_to_label:
                return sig_to_label[key]
        if rules.belt_heuristic and len(d) >= 2 and d[0] == 1.5 and d[1] == 6.0:
            return "belt"
        return "other"

    return label_fn


def _cmd_inspect_sigs(args: argparse.Namespace) -> int:
    from cadclaw.inspect import histogram_signatures, load_parts

    parts = load_parts(args.step)
    label_fn = _resolve_label_fn(args.rules) if args.rules else None
    buckets = histogram_signatures(parts, label_fn=label_fn)

    if not buckets:
        print(f"{args.step}: no parts found")
        return 0

    print(f"{args.step}: {len(parts)} parts, {len(buckets)} unique signatures")
    print()
    print(f"{'count':>5}  {'signature':<28}  label")
    print(f"{'-' * 5}  {'-' * 28}  {'-' * 16}")
    for b in buckets:
        sig_str = "(" + ", ".join(f"{x:g}" for x in b.sig) + ")"
        lbl = b.label or ""
        print(f"{b.count:>5}  {sig_str:<28}  {lbl}")
    return 0


def _cmd_inspect_part(args: argparse.Namespace) -> int:
    from cadclaw.inspect import describe_parts, load_parts

    parts = load_parts(args.step)
    label_fn = _resolve_label_fn(args.rules) if args.rules else None

    at = _parse_xyz(args.at, "--at") if args.at else None
    sig_filter = _parse_xyz(args.sig, "--sig") if args.sig else None
    if sig_filter is not None:
        sig_filter = tuple(sorted(round(float(x), 1) for x in sig_filter))

    matches = describe_parts(
        parts, at=at, sig_filter=sig_filter, label=args.label,
        label_fn=label_fn, tol=args.tol,
    )

    if not matches:
        print("no parts match the given filter(s).")
        return 0

    print(f"{len(matches)} part(s) match:")
    for p in matches:
        sig_str = "(" + ", ".join(f"{x:g}" for x in p.sig) + ")"
        cx, cy, cz = p.center
        xmin, ymin, zmin, xmax, ymax, zmax = p.bbox
        bbox_str = (f"X=[{xmin:.1f},{xmax:.1f}] "
                    f"Y=[{ymin:.1f},{ymax:.1f}] "
                    f"Z=[{zmin:.1f},{zmax:.1f}]")
        label_str = p.label or "?"
        print(f"  {label_str:<12} center=({cx:.1f}, {cy:.1f}, {cz:.1f})  "
              f"sig={sig_str}  bbox={bbox_str}")
    return 0


def _cmd_inspect_overlaps(args: argparse.Namespace) -> int:
    from cadclaw.inspect import find_overlaps, load_parts
    from cadclaw.harness import _format_clip_detail

    if not args.label and not args.at:
        print("error: provide --label or --at to identify the target",
              file=sys.stderr)
        return 3

    parts = load_parts(args.step)
    if args.rules:
        label_fn = _resolve_label_fn(args.rules)
    else:
        label_fn = lambda part: ""
        if args.label:
            print("error: --label requires --rules to resolve labels",
                  file=sys.stderr)
            return 3

    target_at = _parse_xyz(args.at, "--at") if args.at else None
    skip = set(args.skip.split(",")) if args.skip else None

    clips, target_count = find_overlaps(
        parts, label_fn,
        target_label=args.label, target_at=target_at,
        skip_labels=skip,
        min_volume=args.min_volume,
        min_clearance_mm=args.clearance,
        tol=args.tol,
    )

    if target_count == 0:
        print("no parts matched the target filter.")
        return 0

    if not clips:
        target_desc = args.label or f"point ({args.at})"
        print(f"{target_count} target part(s) found; "
              f"no overlaps detected against {target_desc}.")
        return 0

    print(f"{len(clips)} clip(s) involving the target:")
    for c in clips:
        print(f"  {_format_clip_detail(c)}")
    return 1 if clips else 0


def _cmd_inspect_cluster(args: argparse.Namespace) -> int:
    from cadclaw.inspect import cluster_parts, load_parts

    parts = load_parts(args.step)
    label_fn = _resolve_label_fn(args.rules) if args.rules else None

    if args.label and label_fn is None:
        print("error: --label requires --rules to resolve labels",
              file=sys.stderr)
        return 3

    clusters = cluster_parts(
        parts, label_fn=label_fn,
        target_label=args.label, radius_mm=args.radius,
    )

    if not clusters:
        print("no parts matched the cluster target.")
        return 0

    target_desc = f"label={args.label!r}" if args.label else "all parts"
    print(f"{len(clusters)} cluster(s) of {target_desc} (radius {args.radius:g}mm):")
    print()
    for c in clusters:
        cx, cy, cz = c.centroid
        xmin, ymin, zmin, xmax, ymax, zmax = c.bbox
        print(f"  {c.name}: {len(c.members)} parts at "
              f"centroid ({cx:.0f}, {cy:.0f}, {cz:.0f})")
        print(f"    bbox  X=[{xmin:.0f},{xmax:.0f}] "
              f"Y=[{ymin:.0f},{ymax:.0f}] "
              f"Z=[{zmin:.0f},{zmax:.0f}]")
        if c.sig_histogram:
            sig_summary = ", ".join(
                f"{b.count}× ({','.join(f'{x:g}' for x in b.sig)})"
                for b in c.sig_histogram[:5]
            )
            more = "" if len(c.sig_histogram) <= 5 else f" + {len(c.sig_histogram) - 5} more"
            print(f"    sigs  {sig_summary}{more}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cadclaw",
        description="CADCLAW v0.6 — STEP / BOM validation and honesty toolchain.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    p_doctor = sub.add_parser("doctor", help="Diagnose your environment.")
    _add_format_args(p_doctor)
    p_doctor.set_defaults(func=_cmd_doctor)

    p_parity = sub.add_parser("parity", help="Compare two STEP files.")
    p_parity.add_argument("step_a")
    p_parity.add_argument("step_b")
    _add_format_args(p_parity)
    p_parity.set_defaults(func=_cmd_parity)

    p_inv = sub.add_parser("inventory", help="Run the inventory gate.")
    p_inv.add_argument("--rules", default="cadclaw.yaml")
    p_inv.add_argument("--step", default=None)
    _add_format_args(p_inv)
    p_inv.set_defaults(func=_cmd_inventory)

    p_bom = sub.add_parser("bom-audit", help="Run the BOM-vs-CAD audit.")
    p_bom.add_argument("--rules", default="cadclaw.yaml")
    p_bom.add_argument("--step", default=None)
    p_bom.add_argument("--bom", default=None)
    _add_format_args(p_bom)
    p_bom.set_defaults(func=_cmd_bom_audit)

    p_assemble = sub.add_parser(
        "assemble",
        help="Assembly-harness tools for spec validation and CadQuery builds.",
    )
    asm_sub = p_assemble.add_subparsers(
        dest="assemble_command", required=True, metavar="<query>")

    p_validate_spec = asm_sub.add_parser(
        "validate-spec",
        help="Validate an assembly spec before CadQuery compilation.",
    )
    p_validate_spec.add_argument("spec")
    p_validate_spec.add_argument(
        "--release",
        action="store_true",
        help="Treat required not_built_yet items as release-blocking failures.",
    )
    _add_format_args(p_validate_spec)
    p_validate_spec.set_defaults(func=_cmd_assemble_validate_spec)

    p_build = asm_sub.add_parser(
        "build",
        help="Resolve and optionally compile an assembly spec with CadQuery.",
    )
    p_build.add_argument("spec")
    p_build.add_argument(
        "--connector-metadata",
        default=None,
        help="Optional connector metadata YAML for local frames and mates.",
    )
    p_build.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve authored STEP paths without importing/exporting geometry.",
    )
    p_build.add_argument(
        "--write-design-inventory",
        action="store_true",
        help="Write spec.outputs.design_inventory with resolved instances.",
    )
    _add_format_args(p_build)
    p_build.set_defaults(func=_cmd_assemble_build)

    p_inspect_component = asm_sub.add_parser(
        "inspect-component",
        help="Inspect one authored STEP component from an assembly spec.",
    )
    p_inspect_component.add_argument("spec")
    selector = p_inspect_component.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--component-id",
        default=None,
        help="Component id to resolve from the spec manifests.",
    )
    selector.add_argument(
        "--source-path",
        default=None,
        help="Direct authored STEP path/source reference to resolve.",
    )
    p_inspect_component.add_argument(
        "--render-views",
        action="store_true",
        help="Render isolated component review views.",
    )
    p_inspect_component.add_argument(
        "--views",
        default="front,side,top,iso",
        help="Comma-separated views to render when --render-views is set.",
    )
    p_inspect_component.add_argument(
        "--views-dir",
        default=None,
        help="Optional output directory for component review views.",
    )
    _add_format_args(p_inspect_component)
    p_inspect_component.set_defaults(func=_cmd_assemble_inspect_component)

    p_render_views = asm_sub.add_parser(
        "render-views",
        help="Render the review_views declared by an assembly spec.",
    )
    p_render_views.add_argument("spec")
    p_render_views.add_argument(
        "--step",
        default=None,
        help="Optional STEP path to render; defaults to spec.outputs.step.",
    )
    p_render_views.add_argument(
        "--views-dir",
        default=None,
        help="Optional output directory; defaults to spec.outputs.views_dir.",
    )
    _add_format_args(p_render_views)
    p_render_views.set_defaults(func=_cmd_assemble_render_views)

    p_check_round = asm_sub.add_parser(
        "check-round",
        help="Build, inventory-check, optionally render views, and report one assembly round.",
    )
    p_check_round.add_argument("spec")
    p_check_round.add_argument(
        "--connector-metadata",
        default=None,
        help="Optional connector metadata YAML for local frames and mates.",
    )
    p_check_round.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve paths and spec inventory without importing/exporting geometry.",
    )
    p_check_round.add_argument(
        "--no-inventory",
        action="store_true",
        help="Do not write spec.outputs.design_inventory during the round.",
    )
    p_check_round.add_argument(
        "--no-render-views",
        action="store_true",
        help="Skip review-view rendering even after a successful build.",
    )
    p_check_round.add_argument(
        "--write-report",
        action="store_true",
        help="Write the round report to spec.outputs.report when declared.",
    )
    _add_format_args(p_check_round)
    p_check_round.set_defaults(func=_cmd_assemble_check_round)

    p_render_sequence = asm_sub.add_parser(
        "render-sequence",
        help="Export partial assembly STEPs, per-step review views, and BOM CSV.",
    )
    p_render_sequence.add_argument("spec")
    p_render_sequence.add_argument(
        "--output-dir",
        default=None,
        help="Directory for sequence STEPs, images, and manifest.",
    )
    p_render_sequence.add_argument(
        "--views",
        default="front,side,top,hero,iso",
        help="Comma-separated review views to render per sequence step.",
    )
    p_render_sequence.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and report sequence/BOM without exporting STEP or PNG files.",
    )
    p_render_sequence.add_argument(
        "--no-render-views",
        action="store_true",
        help="Export sequence STEPs without per-step PNG renders.",
    )
    p_render_sequence.add_argument(
        "--rotate-final",
        action="store_true",
        help="Render a final rotating GIF from the completed sequence assembly.",
    )
    p_render_sequence.add_argument(
        "--bom-csv",
        default=None,
        help="Optional BOM CSV output path; defaults to spec.bom.output_path/spec.outputs.bom.",
    )
    p_render_sequence.add_argument(
        "--no-bom",
        action="store_true",
        help="Skip BOM CSV generation.",
    )
    _add_format_args(p_render_sequence)
    p_render_sequence.set_defaults(func=_cmd_assemble_render_sequence)

    p_claim = sub.add_parser("claim-audit", help="Lint docs and BOM notes for claims.")
    p_claim.add_argument("--rules", default="cadclaw.yaml")
    p_claim.add_argument("--repo", default=".")
    _add_format_args(p_claim)
    p_claim.set_defaults(func=_cmd_claim_audit)

    p_pub = sub.add_parser("publish-audit",
                           help="Scan working tree for private data before commit.")
    p_pub.add_argument("--rules", default="cadclaw.yaml")
    p_pub.add_argument("--repo", default=".")
    _add_format_args(p_pub)
    p_pub.set_defaults(func=_cmd_publish_audit)

    p_h = sub.add_parser("harness", help="Run YAML-backed checks the rule file configures.")
    p_h.add_argument("--rules", default="cadclaw.yaml")
    p_h.add_argument("--repo", default=".")
    p_h.add_argument("--only", default=None,
                     help="comma-separated list of gates to run.")
    p_h.add_argument("--skip", default=None,
                     help="comma-separated list of gates to skip.")
    _add_format_args(p_h)
    p_h.set_defaults(func=_cmd_harness)

    p_inspect = sub.add_parser(
        "inspect",
        help="Diagnostic queries against a STEP — sigs / part / overlaps.",
        description=(
            "Diagnostic queries (read-only). Replaces the throwaway "
            "_probe_*.py scripts: signature histogram, what-is-this-part, "
            "what-overlaps-X."
        ),
    )
    insp_sub = p_inspect.add_subparsers(
        dest="inspect_command", required=True, metavar="<query>")

    p_sigs = insp_sub.add_parser(
        "sigs", help="Bbox-signature histogram of an assembly.")
    p_sigs.add_argument("step")
    p_sigs.add_argument("--rules", default=None,
                        help="Optional cadclaw.yaml for label resolution.")
    p_sigs.set_defaults(func=_cmd_inspect_sigs)

    p_part = insp_sub.add_parser(
        "part",
        help="Describe parts by location, signature, or label.",
        description=(
            "Filter parts by --at (point in bbox), --sig (exact signature), "
            "or --label (requires --rules). Filters AND together. With no "
            "filters, every part is listed."
        ),
    )
    p_part.add_argument("step")
    p_part.add_argument("--at", default=None,
                        help="Point 'X,Y,Z' — match parts whose bbox contains it.")
    p_part.add_argument("--sig", default=None,
                        help="Signature 'dx,dy,dz' (sorted+rounded to 0.1mm).")
    p_part.add_argument("--label", default=None,
                        help="Label name; requires --rules.")
    p_part.add_argument("--tol", type=float, default=0.0,
                        help="Tolerance (mm) for --at containment. Default 0.")
    p_part.add_argument("--rules", default=None,
                        help="Optional cadclaw.yaml for label resolution.")
    p_part.set_defaults(func=_cmd_inspect_part)

    p_ov = insp_sub.add_parser(
        "overlaps",
        help="Show interference clips touching a target part.",
        description=(
            "List clips where either side of the pair matches the target "
            "(--label or --at point). Uses the same fix-vector math as the "
            "interference gate."
        ),
    )
    p_ov.add_argument("step")
    p_ov.add_argument("--label", default=None,
                     help="Filter clips to those touching parts of this label.")
    p_ov.add_argument("--at", default=None,
                     help="Filter clips to those touching the part at 'X,Y,Z'.")
    p_ov.add_argument("--clearance", type=float, default=1.0,
                     help="Clearance (mm) for the suggested fix-shift. Default 1.0.")
    p_ov.add_argument("--min-volume", type=float, default=1.0,
                     help="Minimum overlap volume (mm^3) to report. Default 1.0.")
    p_ov.add_argument("--skip", default=None,
                     help="Comma-separated labels to skip in pairing (e.g. 'belt,pulley').")
    p_ov.add_argument("--tol", type=float, default=0.0,
                     help="Tolerance (mm) for --at containment. Default 0.")
    p_ov.add_argument("--rules", default=None,
                     help="cadclaw.yaml — required when using --label.")
    p_ov.set_defaults(func=_cmd_inspect_overlaps)

    p_cluster = insp_sub.add_parser(
        "cluster",
        help="Group parts by spatial proximity (single-link agglomerative).",
        description=(
            "Cluster parts into spatial regions. Useful for finding 'where "
            "are these unlabeled parts in the assembly?' — single-link "
            "groups any two parts whose bbox centers are within --radius."
        ),
    )
    p_cluster.add_argument("step")
    p_cluster.add_argument("--label", default=None,
                           help="Cluster only parts of this label (requires --rules); "
                                "default clusters every part.")
    p_cluster.add_argument("--radius", type=float, default=100.0,
                           help="Single-link radius in mm. Default 100.0.")
    p_cluster.add_argument("--rules", default=None,
                           help="Optional cadclaw.yaml for label resolution.")
    p_cluster.set_defaults(func=_cmd_inspect_cluster)

    return p


def _force_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows.

    v0.9 / P0: the v0.7.0 MED-5 aggregate-count finding text contains
    `Δ` (U+0394). On Windows, default stdout encoding is cp1252 which
    raises `UnicodeEncodeError` on Greek characters. Reports written to
    file via `-o` were unaffected (file I/O explicitly opens UTF-8) but
    plain `print(body)` to stdout crashed `cadclaw bom-audit`. Apply
    only on win32 to avoid surprising users on Linux/Mac whose terminals
    already default to UTF-8.
    """
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                # Non-text stream or already configured — leave it.
                pass


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
