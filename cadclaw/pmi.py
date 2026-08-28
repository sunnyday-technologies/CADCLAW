"""Semantic AP242 PMI presence gate.

``PMI_PRESENT_SEMANTIC`` checks only computer-interpretable PMI imported by
OCCT's XCAF document model.  It reports each declared PMI class separately.
It does not inspect graphical annotation presentation, validate GD&T
construction correctness, establish standards conformance, or prove that PMI
survived export from the native CAD model.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

from .findings import ConfidenceBudget, Finding, Report, Severity


GATE_NAME = "PMI_PRESENT_SEMANTIC"
SUPPORTED_PMI_CLASSES: Tuple[str, ...] = (
    "dimensions",
    "geometric_tolerances",
    "datums",
)


class PmiExtractionError(RuntimeError):
    """A STEP could not be classified or imported for semantic PMI checks."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SemanticPmiSnapshot:
    """Presence-oriented semantic PMI summary from one submitted STEP."""

    step_path: str
    step_schema: str
    counts: Dict[str, int]
    reader_version: str
    diagnostics: Dict[str, int]
    reader: str = "OCCT STEPCAFControl_Reader"
    scope: str = "semantic_only"


def _read_step_schema(step_path: Path) -> str:
    """Return the Part 21 FILE_SCHEMA value without interpreting geometry."""
    try:
        with step_path.open("r", encoding="utf-8", errors="replace") as stream:
            header = stream.read(256 * 1024)
    except OSError as exc:
        raise PmiExtractionError(
            "pmi.input_unreadable",
            f"could not read STEP input: {exc}",
        ) from exc

    # Part 21 comments and other HEADER strings are not schema declarations.
    # Limit the search to the actual HEADER section and anchor FILE_SCHEMA at
    # a statement boundary so embedded text cannot spoof AP242 applicability.
    without_comments = re.sub(r"/\*.*?\*/", "", header, flags=re.DOTALL)
    header_match = re.search(
        r"\bHEADER\s*;(.*?)\bENDSEC\s*;",
        without_comments,
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = None
    if header_match:
        match = re.search(
            r"(?im)^[ \t]*FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'",
            header_match.group(1),
        )
    if not match:
        raise PmiExtractionError(
            "pmi.schema_missing",
            "STEP header has no readable FILE_SCHEMA declaration",
        )
    raw_schema = " ".join(match.group(1).split())
    safe_schema = re.sub(r"[^A-Za-z0-9_.:{}+ -]", "?", raw_schema)
    if len(safe_schema) > 160:
        safe_schema = f"{safe_schema[:157]}..."
    return safe_schema


def _count_semantic_dimensions(
    dimension_labels,
    dimension_from_label,
    presentation_types,
) -> tuple[int, int]:
    """Return semantic and presentation-only counts from an XCAF label list."""
    semantic = 0
    presentation_only = 0
    for index in range(1, dimension_labels.Length() + 1):
        dimension_type = (
            dimension_from_label(dimension_labels.Value(index))
            .GetObject()
            .GetType()
        )
        if dimension_type in presentation_types:
            presentation_only += 1
        else:
            semantic += 1
    return semantic, presentation_only


def extract_semantic_pmi(step_path: str | Path) -> SemanticPmiSnapshot:
    """Extract supported semantic PMI class counts from an AP242 STEP.

    Import failures and unsupported schemas are errors, not evidence that PMI
    is absent.  The explicit status comparison matters because pybind enum
    instances are truthy even when OCCT returned an error status.
    """
    path = Path(step_path)
    schema = _read_step_schema(path)
    if not re.match(r"^AP242(?:_|$)", schema.upper()):
        raise PmiExtractionError(
            "pmi.schema_unsupported",
            f"semantic PMI gate requires STEP AP242; input declares {schema}",
        )

    try:
        import OCP
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDF import TDF_LabelSequence
        from OCP.TDocStd import TDocStd_Document
        from OCP.XCAFDimTolObjects import (
            XCAFDimTolObjects_DimensionType_CommonLabel,
            XCAFDimTolObjects_DimensionType_DimensionPresentation,
        )
        from OCP.XCAFDoc import XCAFDoc_Dimension, XCAFDoc_DocumentTool
    except ImportError as exc:
        raise PmiExtractionError(
            "pmi.reader_unavailable",
            "OCCT XCAF semantic PMI reader is unavailable",
        ) from exc

    try:
        document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
        reader = STEPCAFControl_Reader()
        reader.SetGDTMode(True)
        reader.SetMatMode(False)
        reader.SetNameMode(True)
        # Saved views are outside this gate.  OCCT can still place graphical
        # presentation labels in the dimension table, so those are filtered
        # explicitly after transfer below.
        reader.SetViewMode(False)
        status = reader.ReadFile(str(path))
    except Exception as exc:
        raise PmiExtractionError(
            "pmi.read_failed",
            "OCCT could not read the STEP input",
        ) from exc
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise PmiExtractionError(
            "pmi.read_failed",
            f"OCCT could not read STEP input (status {status.name})",
        )
    try:
        transferred = reader.Transfer(document)
    except Exception as exc:
        raise PmiExtractionError(
            "pmi.transfer_failed",
            "OCCT could not transfer AP242 semantic data",
        ) from exc
    if not transferred:
        raise PmiExtractionError(
            "pmi.transfer_failed",
            "OCCT read the STEP container but did not transfer its XCAF document",
        )

    try:
        dimtol_tool = XCAFDoc_DocumentTool.DimTolTool_s(document.Main())
        dimension_labels = TDF_LabelSequence()
        geometric_tolerances = TDF_LabelSequence()
        datums = TDF_LabelSequence()
        dimtol_tool.GetDimensionLabels(dimension_labels)
        dimtol_tool.GetGeomToleranceLabels(geometric_tolerances)
        dimtol_tool.GetDatumLabels(datums)

        presentation_types = {
            XCAFDimTolObjects_DimensionType_CommonLabel,
            XCAFDimTolObjects_DimensionType_DimensionPresentation,
        }
        semantic_dimensions, ignored_presentations = _count_semantic_dimensions(
            dimension_labels,
            XCAFDoc_Dimension.Set_s,
            presentation_types,
        )
    except Exception as exc:
        raise PmiExtractionError(
            "pmi.extract_failed",
            "OCCT imported the STEP but semantic PMI extraction failed",
        ) from exc

    return SemanticPmiSnapshot(
        step_path=str(path),
        step_schema=schema,
        counts={
            "dimensions": semantic_dimensions,
            "geometric_tolerances": geometric_tolerances.Length(),
            "datums": datums.Length(),
        },
        reader_version=str(OCP.__version__),
        diagnostics={
            "raw_dimension_labels": dimension_labels.Length(),
            "presentation_only_dimension_labels_ignored": ignored_presentations,
        },
    )


def run_pmi_present(
    step_path: str | Path | None,
    expected_classes: Iterable[str],
) -> Report:
    """Run ``PMI_PRESENT_SEMANTIC`` and return one result per declaration."""
    started = time.time()
    expected = tuple(dict.fromkeys(expected_classes))
    report = Report(
        meta={
            "gate": GATE_NAME,
            "scope": "semantic_only",
            "expected_classes": list(expected),
        },
        confidence_budget=ConfidenceBudget(),
    )

    if not expected:
        report.meta["applicability"] = "not_applicable"
        report.meta["class_results"] = []
        report.confidence_budget.not_checked.append(
            f"{GATE_NAME}: not applicable — task has no declared PMI requirements"
        )
        report.duration_ms = (time.time() - started) * 1000
        return report

    unknown = [name for name in expected if name not in SUPPORTED_PMI_CLASSES]
    if unknown:
        report.meta["applicability"] = "error"
        report.add(Finding(
            id="pmi.unsupported_class",
            category="pmi_present",
            severity=Severity.FAIL,
            message=f"unsupported semantic PMI classes: {', '.join(unknown)}",
            evidence={
                "unsupported_classes": unknown,
                "supported_classes": list(SUPPORTED_PMI_CLASSES),
            },
        ))
        report.overall = report.compute_overall()
        report.duration_ms = (time.time() - started) * 1000
        return report

    if step_path is None:
        report.meta["applicability"] = "error"
        report.add(Finding(
            id="pmi.input_missing",
            category="pmi_present",
            severity=Severity.FAIL,
            message="declared semantic PMI requirements need rules.meta.step or --step",
        ))
        report.overall = report.compute_overall()
        report.duration_ms = (time.time() - started) * 1000
        return report

    try:
        snapshot = extract_semantic_pmi(step_path)
    except PmiExtractionError as exc:
        report.meta["applicability"] = "error"
        report.meta["class_results"] = []
        report.add(Finding(
            id=exc.code,
            category="pmi_present",
            severity=Severity.FAIL,
            message=str(exc),
            evidence={"status": "error", "semantic_only": True},
        ))
        report.confidence_budget.not_checked.append(
            f"{GATE_NAME}: input could not be evaluated"
        )
        report.overall = report.compute_overall()
        report.duration_ms = (time.time() - started) * 1000
        return report

    class_results = []
    for pmi_class in expected:
        count = snapshot.counts[pmi_class]
        status = "present" if count > 0 else "absent"
        class_results.append({
            "class": pmi_class,
            "status": status,
            "count": count,
        })
        report.add(Finding(
            id=f"pmi.{pmi_class}.{status}",
            category="pmi_present",
            severity=Severity.PASS if count > 0 else Severity.FAIL,
            message=f"semantic PMI class {pmi_class}: {status} ({count})",
            evidence={
                "class": pmi_class,
                "status": status,
                "count": count,
                "semantic_only": True,
                "step_schema": snapshot.step_schema,
                "reader": snapshot.reader,
                "reader_version": snapshot.reader_version,
            },
        ))

    report.meta.update({
        "applicability": "applicable",
        "step": snapshot.step_path,
        "step_schema": snapshot.step_schema,
        "reader": snapshot.reader,
        "reader_version": snapshot.reader_version,
        "diagnostics": snapshot.diagnostics,
        "class_results": class_results,
    })
    report.confidence_budget.checked.append(
        f"{GATE_NAME}: declared AP242 semantic PMI class presence"
    )
    report.confidence_budget.not_checked.extend([
        f"{GATE_NAME}: graphical PMI presentation",
        f"{GATE_NAME}: material assignments",
        f"{GATE_NAME}: process and general notes",
        f"{GATE_NAME}: GD&T construction correctness or standards conformance",
        f"{GATE_NAME}: native-model-to-STEP authoring fidelity",
    ])
    report.overall = report.compute_overall()
    report.duration_ms = (time.time() - started) * 1000
    return report
