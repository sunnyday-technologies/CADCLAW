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

from cadharness.findings import Report, Severity
from cadharness.reporters import render_json, render_markdown, render_text


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
    from cadharness.doctor import run_doctor
    report = run_doctor()
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_parity(args: argparse.Namespace) -> int:
    from cadharness.parity import compare_steps
    from cadharness.findings import Finding
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
    from cadharness.rules import load_rules
    from cadharness.inventory import InventoryCheck, Region
    from cadharness.findings import Finding

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
    from cadharness.rules import load_rules
    rules = load_rules(args.rules)
    bom_path = args.bom or rules.bom_audit.bom_path
    if not bom_path:
        print("error: --bom or rules.bom_audit.bom_path required", file=sys.stderr)
        return 3
    step_path = args.step or rules.meta.step
    if not step_path:
        print("error: --step or rules.meta.step required", file=sys.stderr)
        return 3
    from cadharness.bom_audit import run_bom_audit
    report = run_bom_audit(bom_path=bom_path, step_path=step_path, rules=rules)
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_claim_audit(args: argparse.Namespace) -> int:
    from cadharness.rules import load_rules
    rules = load_rules(args.rules)
    from cadharness.claim_audit import run_claim_audit
    report = run_claim_audit(rules, repo_root=args.repo)
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_publish_audit(args: argparse.Namespace) -> int:
    from cadharness.rules import load_rules
    rules = load_rules(args.rules)
    from cadharness.publish_audit import run_publish_audit
    report = run_publish_audit(rules, repo_root=args.repo)
    _emit_report(report, args.report_format, args.out)
    return _exit_code_for(report)


def _cmd_harness(args: argparse.Namespace) -> int:
    """Union runner — runs every gate that the rule file declares."""
    from cadharness.findings import Finding, ConfidenceBudget
    from cadharness.rules import load_rules
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
        from cadharness.inventory import InventoryCheck, Region
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
        from cadharness.bom_audit import run_bom_audit
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
        from cadharness.claim_audit import run_claim_audit
        sub = run_claim_audit(rules, repo_root=args.repo)
        aggregate.findings.extend(sub.findings)
        aggregate.confidence_budget.checked.append("claim_audit")
    elif _wants("claim_audit"):
        aggregate.confidence_budget.not_checked.append(
            "claim_audit (no scan_paths in rules)"
        )

    if _wants("publish_audit") and (rules.publish_audit.ignore_globs
                                    or rules.publish_audit.scan_globs):
        from cadharness.publish_audit import run_publish_audit
        sub = run_publish_audit(rules, repo_root=args.repo)
        aggregate.findings.extend(sub.findings)
        aggregate.confidence_budget.checked.append("publish_audit")
    elif _wants("publish_audit"):
        aggregate.confidence_budget.not_checked.append(
            "publish_audit (no globs configured)"
        )

    aggregate.overall = aggregate.compute_overall()
    _emit_report(aggregate, args.report_format, args.out)
    return _exit_code_for(aggregate)


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

    p_h = sub.add_parser("harness", help="Run every gate the rule file declares.")
    p_h.add_argument("--rules", default="cadclaw.yaml")
    p_h.add_argument("--repo", default=".")
    p_h.add_argument("--only", default=None,
                     help="comma-separated list of gates to run.")
    p_h.add_argument("--skip", default=None,
                     help="comma-separated list of gates to skip.")
    _add_format_args(p_h)
    p_h.set_defaults(func=_cmd_harness)

    return p


def main(argv: Optional[List[str]] = None) -> int:
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
