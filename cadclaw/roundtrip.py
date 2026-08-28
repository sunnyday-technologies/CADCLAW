"""Opt-in STEP translation round-trip gate.

``ROUNDTRIP_STEP`` imports a submitted STEP into an OCCT XCAF document,
exports that document as AP242, reimports the derivative, and compares the
two imported representations.  It deliberately separates translation
evidence from authoring-reference proxy evidence: an optional STEP proxy can
be compared to the submitted STEP, but it is never described as a proprietary
native model.  Kernel independence is only described as *declared* when the
caller declares a non-OCCT source translator.

The gate is intentionally bounded.  It compares CADCLAW's imported
renderable-shape count (solids and shells deduplicated by the existing 0.1-mm
bounding-box key), axis-aligned bounding boxes and bounding volumes within
configured tolerances, explicitly declared part-to-part interface distances,
and supported source-present semantic PMI class counts.  It does not compare
PMI element values or associations and does not establish graphical-PMI
fidelity, standards conformance, or proprietary native-model fidelity.
Minimum-cost part correspondence has a fixed method limit of 256 matched
renderable shapes so its quadratic storage and cubic runtime remain bounded.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .findings import ConfidenceBudget, Finding, Report, Severity
from .pmi import PmiExtractionError, extract_semantic_pmi


GATE_NAME = "ROUNDTRIP_STEP"
_OCCT_GLOBAL_STATE_LOCK = threading.RLock()
_MAX_INTERFACE_PAIRS = 100
_MAX_MATCHED_RENDERABLE_SHAPES = 256
_SAFE_PAIR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

BBox = Tuple[float, float, float, float, float, float]
Point3 = Tuple[float, float, float]
Signature = Tuple[float, float, float]


class RoundtripError(RuntimeError):
    """A round-trip operation could not be completed safely."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SourceTranslator:
    """Caller-declared provenance for the submitted STEP translator.

    This is a declaration, not a claim verified from the STEP header.  A
    non-OCCT declaration supports only the wording "declared independent".
    """

    family: str = "unknown"
    name: Optional[str] = None
    version: Optional[str] = None

    def __post_init__(self) -> None:
        if self.family not in {"unknown", "occt", "non_occt"}:
            raise ValueError(
                "source translator family must be unknown, occt, or non_occt"
            )
        if self.family == "non_occt" and not (self.name or "").strip():
            raise ValueError(
                "a non_occt source translator declaration requires a name"
            )


@dataclass(frozen=True)
class PartSelector:
    """Unambiguous selector for one imported part.

    ``label`` resolves through the ``label_signatures`` mapping supplied to
    the comparison.  ``signature_mm`` may instead provide the sorted,
    0.1-mm CADCLAW dimension signature directly.  When more than one part
    has that signature, ``near_mm`` plus ``max_center_distance_mm`` must
    leave exactly one candidate; nearest-candidate guessing is forbidden.
    """

    label: Optional[str] = None
    signature_mm: Optional[Signature] = None
    near_mm: Optional[Point3] = None
    max_center_distance_mm: float = 2.0

    def __post_init__(self) -> None:
        if self.label is None and self.signature_mm is None and self.near_mm is None:
            raise ValueError(
                "a part selector requires label, signature_mm, or near_mm"
            )
        if self.signature_mm is not None and len(self.signature_mm) != 3:
            raise ValueError("signature_mm must contain three dimensions")
        if self.signature_mm is not None and not all(
            math.isfinite(float(value)) for value in self.signature_mm
        ):
            raise ValueError("signature_mm values must be finite")
        if self.near_mm is not None and len(self.near_mm) != 3:
            raise ValueError("near_mm must contain three coordinates")
        if self.near_mm is not None and not all(
            math.isfinite(float(value)) for value in self.near_mm
        ):
            raise ValueError("near_mm values must be finite")
        if (
            not math.isfinite(self.max_center_distance_mm)
            or self.max_center_distance_mm < 0
        ):
            raise ValueError("max_center_distance_mm must be non-negative")


@dataclass(frozen=True)
class InterfacePair:
    """One declared interface whose exact minimum distance must survive."""

    id: str
    a: PartSelector
    b: PartSelector
    tolerance_mm: Optional[float] = None

    def __post_init__(self) -> None:
        if not _SAFE_PAIR_ID.fullmatch(self.id):
            raise ValueError(
                "interface pair id must be 1-64 ASCII letters, digits, "
                "underscores, or hyphens and start with a letter or digit"
            )
        if self.tolerance_mm is not None and (
            not math.isfinite(self.tolerance_mm) or self.tolerance_mm < 0
        ):
            raise ValueError("interface tolerance_mm must be non-negative")


@dataclass(frozen=True)
class RoundtripConfig:
    """Method configuration for a single opt-in round trip."""

    source_translator: SourceTranslator = field(default_factory=SourceTranslator)
    authoring_reference_step_proxy: Optional[str] = None
    interface_pairs: Tuple[InterfacePair, ...] = ()
    bbox_tolerance_mm: float = 0.05
    bbox_volume_relative_tolerance: float = 1e-6
    bbox_volume_absolute_tolerance_mm3: float = 1e-3
    interface_gap_tolerance_mm: float = 0.05

    def __post_init__(self) -> None:
        object.__setattr__(self, "interface_pairs", tuple(self.interface_pairs))
        tolerances = {
            "bbox_tolerance_mm": self.bbox_tolerance_mm,
            "bbox_volume_relative_tolerance": self.bbox_volume_relative_tolerance,
            "bbox_volume_absolute_tolerance_mm3": (
                self.bbox_volume_absolute_tolerance_mm3
            ),
            "interface_gap_tolerance_mm": self.interface_gap_tolerance_mm,
        }
        for name, value in tolerances.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be non-negative")
        pair_ids = [pair.id for pair in self.interface_pairs]
        if len(pair_ids) > _MAX_INTERFACE_PAIRS:
            raise ValueError(
                f"at most {_MAX_INTERFACE_PAIRS} interface pairs may be declared"
            )
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("interface pair ids must be unique")


@dataclass(frozen=True)
class PartGeometry:
    index: int
    bbox_mm: BBox
    center_mm: Point3
    signature_mm: Signature
    bbox_volume_mm3: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "bbox_mm": list(self.bbox_mm),
            "center_mm": list(self.center_mm),
            "signature_mm": list(self.signature_mm),
            "bbox_volume_mm3": self.bbox_volume_mm3,
        }


@dataclass(frozen=True)
class GeometrySnapshot:
    step_path: str
    part_count: int
    assembly_bbox_mm: BBox
    assembly_bbox_volume_mm3: float
    parts: Tuple[PartGeometry, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_path": self.step_path,
            "part_count": self.part_count,
            "assembly_bbox_mm": list(self.assembly_bbox_mm),
            "assembly_bbox_volume_mm3": self.assembly_bbox_volume_mm3,
            "parts": [part.to_dict() for part in self.parts],
        }


@dataclass(frozen=True)
class ExportResult:
    source_path: str
    output_path: str
    output_schema: str
    source_sha256: str
    output_sha256: str
    reader: str
    writer: str
    occt_version: str
    write_status: str
    write_disposition: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "output_path": self.output_path,
            "output_schema": self.output_schema,
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "reader": self.reader,
            "writer": self.writer,
            "occt_version": self.occt_version,
            "write_status": self.write_status,
            "write_disposition": self.write_disposition,
        }


@dataclass(frozen=True)
class InterfaceComparison:
    id: str
    before_gap_mm: Optional[float]
    after_gap_mm: Optional[float]
    delta_mm: Optional[float]
    tolerance_mm: float
    status: str
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "before_gap_mm": self.before_gap_mm,
            "after_gap_mm": self.after_gap_mm,
            "delta_mm": self.delta_mm,
            "tolerance_mm": self.tolerance_mm,
            "status": self.status,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class PmiComparison:
    pmi_class: str
    before_count: int
    after_count: int
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "class": self.pmi_class,
            "before_count": self.before_count,
            "after_count": self.after_count,
            "status": self.status,
        }


@dataclass(frozen=True)
class ComparisonResult:
    phase: str
    geometry_before: GeometrySnapshot
    geometry_after: GeometrySnapshot
    findings: Tuple[Finding, ...]
    geometry_summary: Dict[str, Any] = field(default_factory=dict)
    interface_results: Tuple[InterfaceComparison, ...] = ()
    pmi_status: str = "not_applicable"
    pmi_results: Tuple[PmiComparison, ...] = ()
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(finding.severity == Severity.FAIL for finding in self.findings)

    def to_dict(self) -> Dict[str, Any]:
        """Return a bounded, report-safe summary.

        Raw part snapshots remain available to direct Python callers through
        ``geometry_before`` and ``geometry_after``.  They are deliberately
        excluded here so serializing a comparison cannot publish reference
        paths, per-part geometry, or a duplicate finding tree.
        """
        if not self.interface_results:
            interface_status = "not_applicable"
        elif any(item.status == "error" for item in self.interface_results):
            interface_status = "error"
        elif any(item.status == "changed" for item in self.interface_results):
            interface_status = "changed"
        else:
            interface_status = "preserved"
        return {
            "phase": self.phase,
            "status": "pass" if self.passed else "fail",
            "geometry": self.geometry_summary,
            "interfaces": {
                "status": interface_status,
                "count": len(self.interface_results),
                "results": [
                    item.to_dict() for item in self.interface_results
                ],
            },
            "supported_semantic_pmi_class_counts": {
                "status": self.pmi_status,
                "results": [item.to_dict() for item in self.pmi_results],
                **self.meta.get("pmi", {}),
            },
        }


@dataclass
class _LoadedGeometry:
    snapshot: GeometrySnapshot
    shapes: Tuple[Any, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RoundtripError(
            "roundtrip.input_unreadable",
            "could not read the STEP artifact for hashing",
        ) from exc
    return digest.hexdigest()


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _method_limits_metadata() -> Dict[str, Any]:
    """Return bounded-method metadata safe for public reports."""
    return {
        "part_matching": {
            "strategy": "minimum_cost_one_to_one",
            "maximum_matched_renderable_shapes": (
                _MAX_MATCHED_RENDERABLE_SHAPES
            ),
            "limit_behavior": "structured_error_before_cost_matrix_allocation",
        }
    }


def _guard_output_path(source: Path, output: Path) -> None:
    if not source.is_file():
        raise RoundtripError(
            "roundtrip.input_missing",
            "submitted STEP does not exist or is not a file",
        )
    if _normalized_path(source) == _normalized_path(output):
        raise RoundtripError(
            "roundtrip.output_is_source",
            "round-trip output must not overwrite the submitted STEP",
        )
    if output.exists():
        raise RoundtripError(
            "roundtrip.output_exists",
            "round-trip output already exists; choose a new path",
        )


def _default_messenger_printers(messenger) -> list[Any]:
    sequence = messenger.Printers()
    if sequence.IsEmpty():
        return []
    return [
        sequence.Value(index)
        for index in range(sequence.Lower(), sequence.Upper() + 1)
    ]


@contextmanager
def _suppressed_occt_default_messenger():
    """Serialize one OCCT reader operation with diagnostics suppressed.

    OCCT's default messenger is process-global.  The same lock covers every
    reader path in this gate and the writer schema/messenger mutation window.
    Printer restoration is attempted for every captured printer; restoration
    failure takes precedence over an operation failure and is reported without
    paths or underlying exception text.
    """
    try:
        from OCP.Message import Message
    except ImportError as exc:
        raise RoundtripError(
            "roundtrip.reader_unavailable",
            "OCCT reader diagnostics are unavailable",
        ) from exc

    messenger = None
    printers: list[Any] = []
    restore_errors: list[str] = []
    with _OCCT_GLOBAL_STATE_LOCK:
        try:
            try:
                messenger = Message.DefaultMessenger_s()
                printers = _default_messenger_printers(messenger)
                for printer in printers:
                    messenger.RemovePrinter(printer)
            except Exception as exc:
                raise RoundtripError(
                    "roundtrip.reader_state_setup_failed",
                    "OCCT reader messenger state could not be prepared",
                ) from exc
            yield
        finally:
            if messenger is not None:
                for printer in printers:
                    try:
                        messenger.AddPrinter(printer)
                    except Exception:
                        restore_errors.append("default messenger printer")
            if restore_errors:
                raise RoundtripError(
                    "roundtrip.reader_state_restore_failed",
                    "OCCT reader messenger state could not be fully restored",
                )


def _import_xcaf(step_path: Path):
    try:
        import OCP
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDocStd import TDocStd_Document
    except ImportError as exc:
        raise RoundtripError(
            "roundtrip.reader_unavailable",
            "OCCT XCAF STEP reader is unavailable",
        ) from exc

    document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    reader = STEPCAFControl_Reader()
    reader.SetGDTMode(True)
    reader.SetMatMode(True)
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    reader.SetPropsMode(True)
    reader.SetSHUOMode(True)
    # Graphical saved views are intentionally outside the comparison method.
    reader.SetViewMode(False)
    try:
        with _suppressed_occt_default_messenger():
            try:
                status = reader.ReadFile(str(step_path))
            except Exception as exc:
                raise RoundtripError(
                    "roundtrip.read_failed",
                    "OCCT could not read the submitted STEP",
                ) from exc
            if status != IFSelect_ReturnStatus.IFSelect_RetDone:
                raise RoundtripError(
                    "roundtrip.read_failed",
                    f"OCCT could not read submitted STEP (status {status.name})",
                )
            try:
                transferred = reader.Transfer(document)
            except Exception as exc:
                raise RoundtripError(
                    "roundtrip.transfer_failed",
                    "OCCT could not transfer the submitted STEP into XCAF",
                ) from exc
            if not transferred:
                raise RoundtripError(
                    "roundtrip.transfer_failed",
                    "OCCT read the STEP container but did not transfer its XCAF "
                    "document",
                )
    except RoundtripError:
        raise
    except Exception as exc:
        raise RoundtripError(
            "roundtrip.read_failed",
            "OCCT XCAF import could not be completed",
        ) from exc
    return document, str(OCP.__version__)


def _validate_ret_error_artifact(output: Path) -> str:
    """Validate the bounded recovery case for OCCT ``IFSelect_RetError``.

    Some OCCT versions return ``IFSelect_RetError`` after reporting that the
    file write completed.  That status is never accepted by itself.  Recovery
    requires a non-empty regular artifact, an AP242 FILE_SCHEMA declaration,
    and a successful STEPCAFControl XCAF reimport.  The helper always acquires
    ``_OCCT_GLOBAL_STATE_LOCK``; callers already in the writer window reenter
    the same lock, and ``_import_xcaf`` restores its suppressed diagnostics.
    """
    with _OCCT_GLOBAL_STATE_LOCK:
        return _validate_ret_error_artifact_locked(output)


def _validate_ret_error_artifact_locked(output: Path) -> str:
    """Implementation for ``_validate_ret_error_artifact`` under the lock."""
    try:
        artifact_stat = output.lstat()
        artifact_exists = stat.S_ISREG(artifact_stat.st_mode)
        artifact_size = artifact_stat.st_size if artifact_exists else 0
    except FileNotFoundError:
        artifact_exists = False
        artifact_size = 0
    except OSError as exc:
        raise RoundtripError(
            "roundtrip.write_failed",
            "OCCT IFSelect_RetError validation could not read the derivative "
            "artifact",
        ) from exc
    if not artifact_exists or artifact_size <= 0:
        raise RoundtripError(
            "roundtrip.write_failed",
            "OCCT IFSelect_RetError did not produce a non-empty derivative",
        )

    try:
        from .pmi import _read_step_schema

        output_schema = _read_step_schema(output)
    except PmiExtractionError as exc:
        raise RoundtripError(
            "roundtrip.write_failed",
            "OCCT IFSelect_RetError derivative has no readable STEP schema",
        ) from exc
    if "AP242" not in output_schema.upper():
        raise RoundtripError(
            "roundtrip.write_failed",
            "OCCT IFSelect_RetError derivative is not AP242",
        )

    try:
        _import_xcaf(output)
    except RoundtripError as exc:
        if exc.code in {
            "roundtrip.reader_state_setup_failed",
            "roundtrip.reader_state_restore_failed",
        }:
            raise
        raise RoundtripError(
            "roundtrip.write_failed",
            "OCCT IFSelect_RetError AP242 derivative could not be reimported "
            "into XCAF",
        ) from exc
    return "ret_error_provisionally_validated"


def export_ap242(
    source_step: str | Path,
    output_step: str | Path,
) -> ExportResult:
    """Import ``source_step`` through XCAF and write a new AP242 STEP.

    The source and any existing output are never overwritten.  OCCT's STEP
    schema parameter and default messenger are global process state, so the
    whole writer mutation window is serialized.  The schema is restored to
    the caller-visible state captured immediately after OCCT's required STEP
    controller initialization (which itself may replace an uninitialized
    zero sentinel with an OCCT default), and messenger printers are restored
    before returning.  An ``IFSelect_RetError`` result is exposed honestly and
    accepted only provisionally after non-empty AP242 schema and XCAF-reimport
    checks; downstream scoped geometry and semantic-PMI comparisons still
    determine the round-trip report result.
    """
    source = Path(source_step)
    output = Path(output_step)
    _guard_output_path(source, output)
    if not output.parent.exists():
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RoundtripError(
                "roundtrip.output_parent_failed",
                "could not create the round-trip output directory",
            ) from exc

    document, occt_version = _import_xcaf(source)

    try:
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.Interface import Interface_Static
        from OCP.Message import Message
        from OCP.STEPCAFControl import STEPCAFControl_Writer
        from OCP.STEPControl import STEPControl_Controller, STEPControl_StepModelType
    except ImportError as exc:
        raise RoundtripError(
            "roundtrip.writer_unavailable",
            "OCCT XCAF STEP writer is unavailable",
        ) from exc

    previous_schema: Optional[int] = None
    messenger = None
    printers: list[Any] = []
    restore_errors: list[str] = []
    primary_error: Optional[BaseException] = None
    write_status_name: Optional[str] = None
    write_disposition: Optional[str] = None

    with _OCCT_GLOBAL_STATE_LOCK:
        try:
            if not STEPControl_Controller.Init_s():
                raise RoundtripError(
                    "roundtrip.writer_init_failed",
                    "OCCT STEP writer controller could not be initialized",
                )
            previous_schema = Interface_Static.IVal_s("write.step.schema")
            if not Interface_Static.SetIVal_s("write.step.schema", 5):
                raise RoundtripError(
                    "roundtrip.ap242_unavailable",
                    "OCCT could not select its AP242DIS writer schema",
                )

            messenger = Message.DefaultMessenger_s()
            printers = _default_messenger_printers(messenger)
            for printer in printers:
                messenger.RemovePrinter(printer)

            writer = STEPCAFControl_Writer()
            writer.SetDimTolMode(True)
            writer.SetMaterialMode(True)
            writer.SetNameMode(True)
            writer.SetColorMode(True)
            writer.SetLayerMode(True)
            writer.SetPropsMode(True)
            writer.SetSHUOMode(True)
            try:
                transferred = writer.Transfer(
                    document,
                    STEPControl_StepModelType.STEPControl_AsIs,
                )
            except Exception as exc:
                raise RoundtripError(
                    "roundtrip.export_transfer_failed",
                    "OCCT could not transfer the XCAF document to AP242",
                ) from exc
            if not transferred:
                raise RoundtripError(
                    "roundtrip.export_transfer_failed",
                    "OCCT did not transfer the XCAF document to AP242",
                )
            try:
                write_status = writer.Write(str(output))
            except Exception as exc:
                raise RoundtripError(
                    "roundtrip.write_failed",
                    "OCCT could not write the AP242 derivative",
                ) from exc
            write_status_name = write_status.name
            if write_status == IFSelect_ReturnStatus.IFSelect_RetDone:
                write_disposition = "ret_done"
            elif write_status == IFSelect_ReturnStatus.IFSelect_RetError:
                write_disposition = _validate_ret_error_artifact(output)
            else:
                raise RoundtripError(
                    "roundtrip.write_failed",
                    f"OCCT AP242 write failed (status {write_status.name})",
                )
        except BaseException as exc:
            # Delay propagation until process-global state has been restored.
            # A restoration failure is the stronger invariant and therefore
            # takes precedence below, with this primary failure chained.
            primary_error = exc
        finally:
            if previous_schema is not None:
                try:
                    schema_restored = Interface_Static.SetIVal_s(
                        "write.step.schema", previous_schema
                    )
                except Exception:
                    schema_restored = False
                if not schema_restored:
                    restore_errors.append("write.step.schema")
            if messenger is not None:
                for printer in printers:
                    # AddPrinter returning False means the printer is already
                    # present, which is also a restored state.
                    try:
                        messenger.AddPrinter(printer)
                    except Exception:
                        restore_errors.append("default messenger printer")

    if restore_errors:
        # The artifact may exist, but process-global state restoration is a
        # stronger invariant than accepting that artifact as valid evidence.
        raise RoundtripError(
            "roundtrip.writer_state_restore_failed",
            "OCCT writer state could not be fully restored",
        ) from primary_error
    if primary_error is not None:
        if isinstance(primary_error, RoundtripError):
            raise primary_error
        if isinstance(primary_error, Exception):
            raise RoundtripError(
                "roundtrip.export_failed",
                "OCCT AP242 export could not be completed",
            ) from primary_error
        raise primary_error
    if write_status_name is None or write_disposition is None:
        raise RoundtripError(
            "roundtrip.write_failed",
            "OCCT AP242 write produced no classifiable result",
        )
    if not output.is_file():
        raise RoundtripError(
            "roundtrip.output_missing",
            "OCCT reported success but no AP242 derivative was produced",
        )

    try:
        from .pmi import _read_step_schema

        output_schema = _read_step_schema(output)
    except PmiExtractionError as exc:
        raise RoundtripError(
            "roundtrip.output_schema_missing",
            "the derivative has no readable STEP schema",
        ) from exc
    if "AP242" not in output_schema.upper():
        raise RoundtripError(
            "roundtrip.output_schema_invalid",
            "OCCT derivative was not written with an AP242 schema",
        )

    return ExportResult(
        source_path=str(source),
        output_path=str(output),
        output_schema=output_schema,
        source_sha256=_sha256(source),
        output_sha256=_sha256(output),
        reader="OCCT STEPCAFControl_Reader",
        writer="OCCT STEPCAFControl_Writer",
        occt_version=occt_version,
        write_status=write_status_name,
        write_disposition=write_disposition,
    )


def _bbox_tuple(shape) -> BBox:
    try:
        bbox = shape.BoundingBox()
        values: BBox = (
            float(bbox.xmin),
            float(bbox.ymin),
            float(bbox.zmin),
            float(bbox.xmax),
            float(bbox.ymax),
            float(bbox.zmax),
        )
    except Exception as exc:
        raise RoundtripError(
            "roundtrip.bbox_failed",
            "CADCLAW could not calculate an imported part bounding box",
        ) from exc
    if not all(math.isfinite(value) for value in values):
        raise RoundtripError(
            "roundtrip.bbox_invalid",
            "an imported part bounding box contains a non-finite value",
        )
    if any(values[index] > values[index + 3] for index in range(3)):
        raise RoundtripError(
            "roundtrip.bbox_invalid",
            "an imported part bounding box has inverted bounds",
        )
    return values


def _bbox_volume(bbox: BBox) -> float:
    volume = (
        max(0.0, bbox[3] - bbox[0])
        * max(0.0, bbox[4] - bbox[1])
        * max(0.0, bbox[5] - bbox[2])
    )
    if not math.isfinite(volume):
        raise RoundtripError(
            "roundtrip.bbox_volume_invalid",
            "an imported bounding volume is non-finite",
        )
    return volume


def _load_geometry(step_path: str | Path) -> _LoadedGeometry:
    path = Path(step_path)
    if not path.is_file():
        raise RoundtripError(
            "roundtrip.geometry_input_missing",
            "geometry comparison STEP does not exist or is not a file",
        )
    try:
        from .render import _load_shapes

        with _suppressed_occt_default_messenger():
            shapes = list(_load_shapes(str(path)))
    except RoundtripError:
        raise
    except Exception as exc:
        raise RoundtripError(
            "roundtrip.geometry_import_failed",
            "CADCLAW could not import geometry from the STEP artifact",
        ) from exc
    if not shapes:
        raise RoundtripError(
            "roundtrip.geometry_empty",
            "STEP artifact contains no imported solids or shells",
        )

    raw: list[tuple[BBox, Any]] = []
    for shape in shapes:
        bbox = _bbox_tuple(shape)
        raw.append((bbox, shape))
    raw.sort(key=lambda item: item[0])

    parts: list[PartGeometry] = []
    ordered_shapes: list[Any] = []
    for index, (bbox, shape) in enumerate(raw):
        dimensions = (
            bbox[3] - bbox[0],
            bbox[4] - bbox[1],
            bbox[5] - bbox[2],
        )
        parts.append(PartGeometry(
            index=index,
            bbox_mm=bbox,
            center_mm=(
                (bbox[0] + bbox[3]) / 2.0,
                (bbox[1] + bbox[4]) / 2.0,
                (bbox[2] + bbox[5]) / 2.0,
            ),
            signature_mm=tuple(
                sorted(round(float(value), 1) for value in dimensions)
            ),
            bbox_volume_mm3=_bbox_volume(bbox),
        ))
        ordered_shapes.append(shape)

    assembly_bbox: BBox = (
        min(part.bbox_mm[0] for part in parts),
        min(part.bbox_mm[1] for part in parts),
        min(part.bbox_mm[2] for part in parts),
        max(part.bbox_mm[3] for part in parts),
        max(part.bbox_mm[4] for part in parts),
        max(part.bbox_mm[5] for part in parts),
    )
    snapshot = GeometrySnapshot(
        step_path=str(path),
        part_count=len(parts),
        assembly_bbox_mm=assembly_bbox,
        assembly_bbox_volume_mm3=_bbox_volume(assembly_bbox),
        parts=tuple(parts),
    )
    return _LoadedGeometry(snapshot=snapshot, shapes=tuple(ordered_shapes))


def snapshot_geometry(step_path: str | Path) -> GeometrySnapshot:
    """Return CADCLAW's bounded imported-geometry snapshot without writes.

    Bounding coordinates and bounding volumes retain imported floating-point
    values.  ``part_count`` follows ``render._load_shapes`` semantics: solids
    and shells deduplicated by a bounding-box key rounded to 0.1 mm.
    """
    return _load_geometry(step_path).snapshot


def _normalize_signature(values: Iterable[float]) -> Signature:
    try:
        raw = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RoundtripError(
            "roundtrip.selector_signature_invalid",
            "part selector signature must contain three finite dimensions",
        ) from exc
    if len(raw) != 3 or not all(math.isfinite(value) for value in raw):
        raise RoundtripError(
            "roundtrip.selector_signature_invalid",
            "part selector signature must contain three finite dimensions",
        )
    items = tuple(sorted(round(value, 1) for value in raw))
    if len(items) != 3:
        raise RoundtripError(
            "roundtrip.selector_signature_invalid",
            "part selector signature must contain three dimensions",
        )
    return items  # type: ignore[return-value]


def _label_signature(
    label: str,
    label_signatures: Optional[Mapping[str, Any]],
) -> Signature:
    if label_signatures is None or label not in label_signatures:
        raise RoundtripError(
            "roundtrip.selector_label_unknown",
            f"interface selector label {label!r} has no declared signature",
        )
    value = label_signatures[label]
    if hasattr(value, "sig"):
        value = value.sig
    return _normalize_signature(value)


def _resolve_selector(
    loaded: _LoadedGeometry,
    selector: PartSelector,
    label_signatures: Optional[Mapping[str, Any]],
    interface_id: str,
    side: str,
) -> tuple[PartGeometry, Any]:
    wanted_signature: Optional[Signature] = None
    if selector.label is not None:
        wanted_signature = _label_signature(selector.label, label_signatures)
    if selector.signature_mm is not None:
        direct_signature = _normalize_signature(selector.signature_mm)
        if wanted_signature is not None and direct_signature != wanted_signature:
            raise RoundtripError(
                "roundtrip.selector_signature_conflict",
                f"interface {interface_id} selector {side} label and signature disagree",
            )
        wanted_signature = direct_signature

    candidates = [
        part for part in loaded.snapshot.parts
        if wanted_signature is None or part.signature_mm == wanted_signature
    ]
    if selector.near_mm is not None:
        near = tuple(float(value) for value in selector.near_mm)
        candidates = [
            part for part in candidates
            if math.dist(part.center_mm, near) <= selector.max_center_distance_mm
        ]
    if len(candidates) != 1:
        raise RoundtripError(
            "roundtrip.selector_ambiguous" if candidates else "roundtrip.selector_missing",
            (
                f"interface {interface_id} selector {side} resolved to "
                f"{len(candidates)} parts; exactly one is required"
            ),
        )
    part = candidates[0]
    return part, loaded.shapes[part.index]


def _minimum_distance(shape_a, shape_b) -> float:
    try:
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape

        distance = BRepExtrema_DistShapeShape(shape_a.wrapped, shape_b.wrapped)
        performed = distance.Perform()
    except Exception as exc:
        raise RoundtripError(
            "roundtrip.interface_distance_failed",
            "OCCT could not calculate a declared interface distance",
        ) from exc
    if not performed or not distance.IsDone():
        raise RoundtripError(
            "roundtrip.interface_distance_failed",
            "OCCT did not complete a declared interface distance calculation",
        )
    value = float(distance.Value())
    if not math.isfinite(value) or value < 0:
        raise RoundtripError(
            "roundtrip.interface_distance_invalid",
            "OCCT returned an invalid declared interface distance",
        )
    return value


def _interface_gap(
    loaded: _LoadedGeometry,
    pair: InterfacePair,
    label_signatures: Optional[Mapping[str, Any]],
) -> float:
    part_a, shape_a = _resolve_selector(
        loaded, pair.a, label_signatures, pair.id, "a"
    )
    part_b, shape_b = _resolve_selector(
        loaded, pair.b, label_signatures, pair.id, "b"
    )
    if part_a.index == part_b.index:
        raise RoundtripError(
            "roundtrip.interface_same_part",
            f"interface {pair.id} selectors resolve to the same imported part",
        )
    return _minimum_distance(shape_a, shape_b)


def _isclose(value_a: float, value_b: float, rel_tol: float, abs_tol: float) -> bool:
    return math.isclose(value_a, value_b, rel_tol=rel_tol, abs_tol=abs_tol)


def _relative_delta(value_a: float, value_b: float) -> float:
    scale = max(abs(value_a), abs(value_b), 1e-12)
    return abs(value_a - value_b) / scale


def _part_match_cost(part_a: PartGeometry, part_b: PartGeometry) -> float:
    """Deterministic geometry/location cost for one possible part match."""
    bbox_cost = sum(
        (value_a - value_b) ** 2
        for value_a, value_b in zip(part_a.bbox_mm, part_b.bbox_mm)
    )
    bbox_volume_cost = _relative_delta(
        part_a.bbox_volume_mm3, part_b.bbox_volume_mm3
    ) ** 2
    return bbox_cost + bbox_volume_cost


def _minimum_cost_part_matching(
    before: Sequence[PartGeometry],
    after: Sequence[PartGeometry],
) -> Tuple[Tuple[int, int], ...]:
    """Return a deterministic minimum-cost one-to-one part assignment.

    The Hungarian assignment avoids relying on list or lexicographic order,
    which can change when nearly equal bounding coordinates jitter across a
    sort boundary.  Exact deltas and configured tolerances are evaluated only
    after correspondence has been established.
    """
    if len(before) != len(after):
        return ()
    count = len(before)
    if count == 0:
        return ()
    if count > _MAX_MATCHED_RENDERABLE_SHAPES:
        raise RoundtripError(
            "roundtrip.part_count_limit_exceeded",
            (
                "minimum-cost part correspondence supports at most "
                f"{_MAX_MATCHED_RENDERABLE_SHAPES} matched renderable shapes; "
                f"comparison requires {count}"
            ),
        )

    costs = [
        [_part_match_cost(part_a, part_b) for part_b in after]
        for part_a in before
    ]
    row_potential = [0.0] * (count + 1)
    col_potential = [0.0] * (count + 1)
    matched_row = [0] * (count + 1)
    predecessor = [0] * (count + 1)

    for row in range(1, count + 1):
        matched_row[0] = row
        column = 0
        min_value = [math.inf] * (count + 1)
        used = [False] * (count + 1)
        while True:
            used[column] = True
            current_row = matched_row[column]
            delta = math.inf
            next_column = 0
            for candidate in range(1, count + 1):
                if used[candidate]:
                    continue
                reduced = (
                    costs[current_row - 1][candidate - 1]
                    - row_potential[current_row]
                    - col_potential[candidate]
                )
                if reduced < min_value[candidate]:
                    min_value[candidate] = reduced
                    predecessor[candidate] = column
                if min_value[candidate] < delta:
                    delta = min_value[candidate]
                    next_column = candidate
            if not math.isfinite(delta):
                raise RoundtripError(
                    "roundtrip.part_matching_failed",
                    "imported parts could not be matched one-to-one",
                )
            for candidate in range(0, count + 1):
                if used[candidate]:
                    row_potential[matched_row[candidate]] += delta
                    col_potential[candidate] -= delta
                else:
                    min_value[candidate] -= delta
            column = next_column
            if matched_row[column] == 0:
                break
        while True:
            previous = predecessor[column]
            matched_row[column] = matched_row[previous]
            column = previous
            if column == 0:
                break

    assignment: list[tuple[int, int]] = []
    for column in range(1, count + 1):
        row = matched_row[column]
        if row <= 0:
            raise RoundtripError(
                "roundtrip.part_matching_failed",
                "imported parts could not be matched one-to-one",
            )
        assignment.append((row - 1, column - 1))
    assignment.sort(key=lambda item: item[0])
    return tuple(assignment)


def _finding(
    phase: str,
    metric: str,
    passed: bool,
    message: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> Finding:
    return Finding(
        id=f"roundtrip.{phase}.{metric}.{'preserved' if passed else 'changed'}",
        category="roundtrip_step",
        severity=Severity.PASS if passed else Severity.FAIL,
        message=message,
        evidence=evidence or {},
    )


def _compare_geometry(
    before: GeometrySnapshot,
    after: GeometrySnapshot,
    config: RoundtripConfig,
    phase: str,
) -> tuple[list[Finding], Dict[str, Any]]:
    findings: list[Finding] = []
    summary: Dict[str, Any] = {}

    part_count_ok = before.part_count == after.part_count
    findings.append(_finding(
        phase,
        "part_count",
        part_count_ok,
        (
            "CADCLAW imported renderable-shape count "
            f"(0.1-mm bbox dedup): {before.part_count} -> {after.part_count}"
        ),
        {
            "before": before.part_count,
            "after": after.part_count,
            "method": "solids_and_shells_deduplicated_by_0.1mm_bbox_key",
        },
    ))
    summary["part_count"] = {
        "status": "preserved" if part_count_ok else "changed",
        "before": before.part_count,
        "after": after.part_count,
        "delta": after.part_count - before.part_count,
        "method": "solids_and_shells_deduplicated_by_0.1mm_bbox_key",
    }

    bbox_deltas = [
        abs(value_a - value_b)
        for value_a, value_b in zip(
            before.assembly_bbox_mm, after.assembly_bbox_mm
        )
    ]
    max_bbox_delta = max(bbox_deltas)
    bbox_ok = max_bbox_delta <= config.bbox_tolerance_mm
    findings.append(_finding(
        phase,
        "assembly_bbox",
        bbox_ok,
        f"assembly bounding-box max delta: {max_bbox_delta:.9g} mm",
        {
            "max_delta_mm": max_bbox_delta,
            "tolerance_mm": config.bbox_tolerance_mm,
        },
    ))
    summary["assembly_bbox"] = {
        "status": "preserved" if bbox_ok else "changed",
        "max_delta_mm": max_bbox_delta,
        "tolerance_mm": config.bbox_tolerance_mm,
    }

    bbox_volume_ok = _isclose(
        before.assembly_bbox_volume_mm3,
        after.assembly_bbox_volume_mm3,
        config.bbox_volume_relative_tolerance,
        config.bbox_volume_absolute_tolerance_mm3,
    )
    bbox_volume_delta = abs(
        before.assembly_bbox_volume_mm3 - after.assembly_bbox_volume_mm3
    )
    bbox_volume_relative_delta = _relative_delta(
        before.assembly_bbox_volume_mm3, after.assembly_bbox_volume_mm3
    )
    findings.append(_finding(
        phase,
        "assembly_bbox_volume",
        bbox_volume_ok,
        (
            "assembly bounding-volume delta: "
            f"{bbox_volume_delta:.9g} mm3 "
            f"(relative {bbox_volume_relative_delta:.9g})"
        ),
        {
            "absolute_delta_mm3": bbox_volume_delta,
            "relative_delta": bbox_volume_relative_delta,
            "relative_tolerance": config.bbox_volume_relative_tolerance,
            "absolute_tolerance_mm3": (
                config.bbox_volume_absolute_tolerance_mm3
            ),
        },
    ))
    summary["assembly_bbox_volume"] = {
        "status": "preserved" if bbox_volume_ok else "changed",
        "absolute_delta_mm3": bbox_volume_delta,
        "relative_delta": bbox_volume_relative_delta,
        "relative_tolerance": config.bbox_volume_relative_tolerance,
        "absolute_tolerance_mm3": config.bbox_volume_absolute_tolerance_mm3,
    }

    per_part_ok = part_count_ok
    max_part_bbox_delta: Optional[float] = None
    max_part_bbox_volume_delta: Optional[float] = None
    matched_parts = 0
    if part_count_ok:
        max_part_bbox_delta = 0.0
        max_part_bbox_volume_delta = 0.0
        assignment = _minimum_cost_part_matching(before.parts, after.parts)
        matched_parts = len(assignment)
        for before_index, after_index in assignment:
            part_before = before.parts[before_index]
            part_after = after.parts[after_index]
            part_bbox_delta = max(
                abs(value_a - value_b)
                for value_a, value_b in zip(
                    part_before.bbox_mm, part_after.bbox_mm
                )
            )
            part_bbox_volume_delta = abs(
                part_before.bbox_volume_mm3 - part_after.bbox_volume_mm3
            )
            max_part_bbox_delta = max(max_part_bbox_delta, part_bbox_delta)
            max_part_bbox_volume_delta = max(
                max_part_bbox_volume_delta, part_bbox_volume_delta
            )
            if part_bbox_delta > config.bbox_tolerance_mm:
                per_part_ok = False
            if not _isclose(
                part_before.bbox_volume_mm3,
                part_after.bbox_volume_mm3,
                config.bbox_volume_relative_tolerance,
                config.bbox_volume_absolute_tolerance_mm3,
            ):
                per_part_ok = False
    findings.append(_finding(
        phase,
        "per_part_geometry",
        per_part_ok,
        (
            "per-part bounding boxes and bounding volumes preserved within "
            "configured tolerances"
            if per_part_ok
            else (
                "per-part bounding boxes or bounding volumes exceeded "
                "configured tolerances"
            )
        ),
        {
            "matching_strategy": "minimum_cost_one_to_one",
            "maximum_matched_renderable_shapes": (
                _MAX_MATCHED_RENDERABLE_SHAPES
            ),
            "parts_compared": matched_parts,
            "max_bbox_delta_mm": max_part_bbox_delta,
            "max_bbox_volume_delta_mm3": max_part_bbox_volume_delta,
        },
    ))
    summary["per_part_geometry"] = {
        "status": (
            "preserved" if per_part_ok
            else "changed" if part_count_ok
            else "not_applicable"
        ),
        "matching_strategy": "minimum_cost_one_to_one",
        "maximum_matched_renderable_shapes": _MAX_MATCHED_RENDERABLE_SHAPES,
        "matched_parts": matched_parts,
        "max_bbox_delta_mm": max_part_bbox_delta,
        "max_bbox_volume_delta_mm3": max_part_bbox_volume_delta,
    }
    return findings, summary


def _compare_interfaces(
    before: _LoadedGeometry,
    after: _LoadedGeometry,
    config: RoundtripConfig,
    label_signatures: Optional[Mapping[str, Any]],
    phase: str,
) -> tuple[list[Finding], list[InterfaceComparison]]:
    findings: list[Finding] = []
    results: list[InterfaceComparison] = []
    for pair in config.interface_pairs:
        tolerance = (
            pair.tolerance_mm
            if pair.tolerance_mm is not None
            else config.interface_gap_tolerance_mm
        )
        try:
            before_gap = _interface_gap(before, pair, label_signatures)
            after_gap = _interface_gap(after, pair, label_signatures)
        except RoundtripError as exc:
            result = InterfaceComparison(
                id=pair.id,
                before_gap_mm=None,
                after_gap_mm=None,
                delta_mm=None,
                tolerance_mm=tolerance,
                status="error",
                error_code=exc.code,
            )
            results.append(result)
            findings.append(Finding(
                id=exc.code,
                category="roundtrip_step",
                severity=Severity.FAIL,
                message=str(exc),
                evidence={"phase": phase, **result.to_dict()},
            ))
            continue
        delta = abs(after_gap - before_gap)
        passed = delta <= tolerance
        status = "preserved" if passed else "changed"
        results.append(InterfaceComparison(
            id=pair.id,
            before_gap_mm=before_gap,
            after_gap_mm=after_gap,
            delta_mm=delta,
            tolerance_mm=tolerance,
            status=status,
        ))
        findings.append(_finding(
            phase,
            f"interface.{pair.id}",
            passed,
            (
                f"declared interface {pair.id} gap: "
                f"{before_gap:.9g} -> {after_gap:.9g} mm"
            ),
            results[-1].to_dict(),
        ))
    return findings, results


def _compare_pmi(
    source_step: str | Path,
    derivative_step: str | Path,
    phase: str,
) -> tuple[list[Finding], str, list[PmiComparison], Dict[str, Any]]:
    try:
        with _suppressed_occt_default_messenger():
            before = extract_semantic_pmi(source_step)
    except PmiExtractionError as exc:
        if exc.code == "pmi.schema_unsupported":
            return [], "not_applicable", [], {
                "reason": "source STEP is not AP242",
                "scope": "supported_semantic_class_counts_only",
            }
        return [Finding(
            id=f"roundtrip.{phase}.pmi_source_error",
            category="roundtrip_step",
            severity=Severity.FAIL,
            message=(
                "source supported semantic PMI class counts could not be evaluated"
            ),
            evidence={"source_error": exc.code},
        )], "error", [], {
            "source_error": exc.code,
            "scope": "supported_semantic_class_counts_only",
        }

    present = {
        name: count for name, count in before.counts.items() if count > 0
    }
    if not present:
        return [], "not_applicable", [], {
            "reason": (
                "source AP242 contains no supported semantic PMI class counts"
            ),
            "source_counts": before.counts,
            "scope": "supported_semantic_class_counts_only",
        }
    try:
        with _suppressed_occt_default_messenger():
            after = extract_semantic_pmi(derivative_step)
    except PmiExtractionError as exc:
        return [Finding(
            id=f"roundtrip.{phase}.pmi_reimport_error",
            category="roundtrip_step",
            severity=Severity.FAIL,
            message=(
                "reimported supported semantic PMI class counts could not be "
                "evaluated"
            ),
            evidence={"reimport_error": exc.code},
        )], "error", [], {
            "reimport_error": exc.code,
            "scope": "supported_semantic_class_counts_only",
        }

    findings: list[Finding] = []
    results: list[PmiComparison] = []
    for pmi_class, before_count in present.items():
        after_count = int(after.counts.get(pmi_class, 0))
        passed = before_count == after_count
        status = "preserved" if passed else "changed"
        result = PmiComparison(
            pmi_class=pmi_class,
            before_count=before_count,
            after_count=after_count,
            status=status,
        )
        results.append(result)
        findings.append(_finding(
            phase,
            f"pmi.{pmi_class}",
            passed,
            (
                f"supported semantic PMI class count {pmi_class}: "
                f"{before_count} -> {after_count}"
            ),
            result.to_dict(),
        ))
    return findings, "compared", results, {
        "source_schema": before.step_schema,
        "reimport_schema": after.step_schema,
        "reader": before.reader,
        "reader_version": before.reader_version,
        "scope": "supported_semantic_class_counts_only",
    }


def compare_roundtrip_artifacts(
    source_step: str | Path,
    derivative_step: str | Path,
    config: RoundtripConfig = RoundtripConfig(),
    label_signatures: Optional[Mapping[str, Any]] = None,
    phase: str = "translation",
) -> ComparisonResult:
    """Compare two already-existing STEP artifacts using round-trip scope."""
    if phase not in {"translation", "proxy_comparison"}:
        raise ValueError(
            "comparison phase must be translation or proxy_comparison"
        )
    before = _load_geometry(source_step)
    after = _load_geometry(derivative_step)
    findings, geometry_summary = _compare_geometry(
        before.snapshot, after.snapshot, config, phase
    )
    interface_findings, interface_results = _compare_interfaces(
        before, after, config, label_signatures, phase
    )
    findings.extend(interface_findings)
    pmi_findings, pmi_status, pmi_results, pmi_meta = _compare_pmi(
        source_step, derivative_step, phase
    )
    findings.extend(pmi_findings)
    return ComparisonResult(
        phase=phase,
        geometry_before=before.snapshot,
        geometry_after=after.snapshot,
        findings=tuple(findings),
        geometry_summary=geometry_summary,
        interface_results=tuple(interface_results),
        pmi_status=pmi_status,
        pmi_results=tuple(pmi_results),
        meta={"pmi": pmi_meta},
    )


def classify_translation_independence(
    declaration: SourceTranslator,
) -> Dict[str, Any]:
    """Return claim-safe independence metadata for a source declaration."""
    if declaration.family == "non_occt":
        return {
            "status": "declared_independent",
            "declared_family": declaration.family,
            "name": declaration.name,
            "version": declaration.version,
            "verified": False,
            "reason": (
                "a non-OCCT source translator was declared; provenance was "
                "not independently verified"
            ),
        }
    if declaration.family == "occt":
        return {
            "status": "not_applicable",
            "declared_family": declaration.family,
            "name": declaration.name,
            "version": declaration.version,
            "verified": False,
            "reason": (
                "source and round-trip translator are OCCT; kernel "
                "independence was not established"
            ),
        }
    return {
        "status": "not_applicable",
        "declared_family": "unknown",
        "verified": False,
        "reason": (
            "source translator is unknown; kernel independence was not established"
        ),
    }


def _merge_comparison(report: Report, result: ComparisonResult) -> None:
    report.extend(list(result.findings))
    if result.phase == "translation":
        report.confidence_budget.checked.extend([
            f"{GATE_NAME}: CADCLAW-deduplicated imported renderable-shape count",
            f"{GATE_NAME}: assembly and per-part bounding boxes and bounding volumes",
        ])
        resolved_interfaces = [
            item for item in result.interface_results if item.status != "error"
        ]
        unresolved_interfaces = [
            item for item in result.interface_results if item.status == "error"
        ]
        if resolved_interfaces:
            report.confidence_budget.checked.append(
                f"{GATE_NAME}: {len(resolved_interfaces)} resolved declared "
                "interface-pair minimum distances"
            )
        if unresolved_interfaces:
            report.confidence_budget.not_checked.append(
                f"{GATE_NAME}: {len(unresolved_interfaces)} declared interface "
                "pairs unresolved"
            )
        elif not result.interface_results:
            report.confidence_budget.not_checked.append(
                f"{GATE_NAME}: interface gaps (no interface pairs declared)"
            )
        if result.pmi_status == "compared":
            report.confidence_budget.checked.append(
                f"{GATE_NAME}: source-present supported semantic PMI "
                "class-count preservation"
            )
        elif result.pmi_status == "not_applicable":
            report.confidence_budget.not_checked.append(
                f"{GATE_NAME}: supported semantic PMI class-count "
                "preservation (not applicable)"
            )


def _build_report(
    step_path: Path,
    export_result: ExportResult,
    translation: ComparisonResult,
    config: RoundtripConfig,
    label_signatures: Optional[Mapping[str, Any]],
    persisted_output: bool,
) -> Report:
    report = Report(
        meta={
            "gate": GATE_NAME,
            "applicability": "applicable",
            "method_limits": _method_limits_metadata(),
            "translation_independence": classify_translation_independence(
                config.source_translator
            ),
        },
        confidence_budget=ConfidenceBudget(),
    )
    _merge_comparison(report, translation)

    # Deliberately omit source/output paths.  The public report records
    # content hashes and method provenance, not local filesystem topology.
    export_meta = {
        "output_schema": export_result.output_schema,
        "source_sha256": export_result.source_sha256,
        "output_sha256": export_result.output_sha256,
        "reader": export_result.reader,
        "writer": export_result.writer,
        "occt_version": export_result.occt_version,
        "write_status": export_result.write_status,
        "write_disposition": export_result.write_disposition,
        "persisted": persisted_output,
    }
    report.meta["derivative"] = export_meta
    report.meta["translation_comparison"] = translation.to_dict()
    if export_result.write_disposition == "ret_error_provisionally_validated":
        report.confidence_budget.not_checked.append(
            f"{GATE_NAME}: OCCT writer-internal reference integrity and "
            "graphical PMI after provisionally validated error-status recovery"
        )

    independence = report.meta["translation_independence"]
    if independence["status"] == "declared_independent":
        report.confidence_budget.assumptions.append(independence["reason"])
    else:
        report.confidence_budget.not_checked.append(
            f"{GATE_NAME}: independent-kernel translation"
        )

    if config.authoring_reference_step_proxy is None:
        report.meta["authoring_proxy_comparison"] = {
            "status": "not_applicable",
            "reason": "no authoring-reference STEP proxy was supplied",
        }
        report.confidence_budget.not_checked.append(
            f"{GATE_NAME}: authoring-reference STEP proxy comparison"
        )
    else:
        try:
            authoring_proxy_sha256 = _sha256(
                Path(config.authoring_reference_step_proxy)
            )
            proxy_comparison = compare_roundtrip_artifacts(
                config.authoring_reference_step_proxy,
                step_path,
                config=config,
                label_signatures=label_signatures,
                phase="proxy_comparison",
            )
        except RoundtripError as exc:
            report.add(Finding(
                id=exc.code,
                category="roundtrip_step",
                severity=Severity.FAIL,
                message=str(exc),
                evidence={"phase": "proxy_comparison"},
            ))
            report.meta["authoring_proxy_comparison"] = {
                "status": "error",
                "error": exc.code,
            }
        else:
            report.extend(list(proxy_comparison.findings))
            proxy_summary = proxy_comparison.to_dict()
            proxy_summary["artifacts"] = {
                "authoring_reference_step_proxy_sha256": (
                    authoring_proxy_sha256
                ),
                "submitted_step_sha256": export_result.source_sha256,
            }
            report.meta["authoring_proxy_comparison"] = proxy_summary
            report.confidence_budget.checked.append(
                f"{GATE_NAME}: authoring-reference STEP proxy comparison"
            )

    report.confidence_budget.not_checked.extend([
        f"{GATE_NAME}: graphical PMI presentation and saved views",
        f"{GATE_NAME}: material assignment and process/general-note survival",
        f"{GATE_NAME}: semantic PMI element values, associations, and construction",
        f"{GATE_NAME}: standards conformance or proprietary native-model fidelity",
    ])
    report.overall = report.compute_overall()
    return report


def _error_report(
    step_path: str | Path | None,
    error: RoundtripError,
    started: float,
    config: RoundtripConfig,
) -> Report:
    report = Report(
        meta={
            "gate": GATE_NAME,
            "applicability": "error",
            "method_limits": _method_limits_metadata(),
            "translation_independence": classify_translation_independence(
                config.source_translator
            ),
            "authoring_proxy_comparison": (
                {"status": "not_applicable", "reason": "round trip did not complete"}
            ),
        },
        confidence_budget=ConfidenceBudget(
            not_checked=[f"{GATE_NAME}: round trip did not complete"]
        ),
    )
    report.add(Finding(
        id=error.code,
        category="roundtrip_step",
        severity=Severity.FAIL,
        message=str(error),
        evidence={"status": "error"},
    ))
    report.overall = report.compute_overall()
    report.duration_ms = (time.time() - started) * 1000
    return report


def run_roundtrip_step(
    step_path: str | Path | None,
    config: RoundtripConfig = RoundtripConfig(),
    output_path: str | Path | None = None,
    label_signatures: Optional[Mapping[str, Any]] = None,
) -> Report:
    """Run an actual import/export/reimport and return a unified report.

    With no ``output_path`` the derivative is held in a temporary directory
    and removed before this function returns.  An explicit path persists the
    derivative, but it must not exist and must not resolve to the source.
    """
    started = time.time()
    if step_path is None:
        return _error_report(
            step_path,
            RoundtripError(
                "roundtrip.input_missing",
                "ROUNDTRIP_STEP requires a submitted STEP path",
            ),
            started,
            config,
        )
    source = Path(step_path)

    try:
        if output_path is not None:
            derivative = Path(output_path)
            exported = export_ap242(source, derivative)
            translation = compare_roundtrip_artifacts(
                source,
                derivative,
                config=config,
                label_signatures=label_signatures,
                phase="translation",
            )
            report = _build_report(
                source,
                exported,
                translation,
                config,
                label_signatures,
                persisted_output=True,
            )
        else:
            try:
                temporary_directory = tempfile.TemporaryDirectory(
                    prefix="cadclaw-roundtrip-"
                )
            except OSError as exc:
                raise RoundtripError(
                    "roundtrip.temporary_directory_failed",
                    "could not create a temporary round-trip directory",
                ) from exc
            temporary_derivative = (
                Path(temporary_directory.name) / "reimport-ap242.stp"
            )
            try:
                exported = export_ap242(source, temporary_derivative)
                translation = compare_roundtrip_artifacts(
                    source,
                    temporary_derivative,
                    config=config,
                    label_signatures=label_signatures,
                    phase="translation",
                )
                report = _build_report(
                    source,
                    exported,
                    translation,
                    config,
                    label_signatures,
                    persisted_output=False,
                )
            finally:
                try:
                    temporary_directory.cleanup()
                except OSError as exc:
                    raise RoundtripError(
                        "roundtrip.temporary_cleanup_failed",
                        "temporary AP242 derivative could not be removed",
                    ) from exc
            try:
                cleanup_complete = not temporary_derivative.exists()
            except OSError as exc:
                raise RoundtripError(
                    "roundtrip.temporary_cleanup_failed",
                    "temporary AP242 derivative cleanup could not be verified",
                ) from exc
            if not cleanup_complete:
                raise RoundtripError(
                    "roundtrip.temporary_cleanup_failed",
                    "temporary AP242 derivative was not removed",
                )
            report.meta["derivative"]["temporary_cleanup"] = (
                "complete"
            )
    except RoundtripError as exc:
        return _error_report(step_path, exc, started, config)

    report.duration_ms = (time.time() - started) * 1000
    return report


__all__ = [
    "ComparisonResult",
    "ExportResult",
    "GATE_NAME",
    "GeometrySnapshot",
    "InterfaceComparison",
    "InterfacePair",
    "PartGeometry",
    "PartSelector",
    "PmiComparison",
    "RoundtripConfig",
    "RoundtripError",
    "SourceTranslator",
    "classify_translation_independence",
    "compare_roundtrip_artifacts",
    "export_ap242",
    "run_roundtrip_step",
    "snapshot_geometry",
]
