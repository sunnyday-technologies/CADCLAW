"""
Inspect — diagnostic queries against a STEP assembly.

Four pure functions, each replacing a class of throwaway probe script
that field users (humans + AI agents) keep rewriting:

- `histogram_signatures`  — bbox-signature counts. ("what's in this STEP?")
- `describe_parts`        — filter parts by location, signature, or label.
                            ("what is this part?")
- `find_overlaps`         — interference clips touching a target part.
                            ("what overlaps this plate?")
- `cluster_parts`         — group parts by spatial proximity. ("which
                            X-carriage region are these 32 'other' parts in?")

The CLI exposes these as `cadclaw inspect sigs|part|overlaps|cluster`.
Findings output is intentionally plain — these are diagnostics, not gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .inventory import center, load_and_dedup, sig


Sig3 = Tuple[float, float, float]
Point3 = Tuple[float, float, float]
BBox6 = Tuple[float, float, float, float, float, float]


@dataclass
class PartInfo:
    """A single matching part in a `describe_parts` result."""
    label: str
    sig: Sig3
    center: Point3
    bbox: BBox6


@dataclass
class SigBucket:
    """One row in a signature histogram."""
    sig: Sig3
    count: int
    label: Optional[str]  # populated if a label_fn matched this sig


def _bbox_tuple(s) -> BBox6:
    bb = s.BoundingBox()
    return (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)


def _bbox_contains(bb: BBox6, p: Point3, tol: float = 0.0) -> bool:
    xmin, ymin, zmin, xmax, ymax, zmax = bb
    px, py, pz = p
    return (xmin - tol <= px <= xmax + tol
            and ymin - tol <= py <= ymax + tol
            and zmin - tol <= pz <= zmax + tol)


def histogram_signatures(parts: list,
                         label_fn: Optional[Callable] = None) -> List[SigBucket]:
    """Return signature histogram sorted by count descending, then by sig.

    `label_fn` is optional — when provided, each bucket is tagged with the
    label the function returns for any one part of that signature (all
    parts of a signature share a label by construction).
    """
    counts: Dict[Sig3, int] = {}
    label_for: Dict[Sig3, Optional[str]] = {}
    for part in parts:
        s = sig(part)
        # `sig()` returns a sorted tuple of length 3 (dx,dy,dz post-round).
        if len(s) != 3:
            continue
        s3: Sig3 = (s[0], s[1], s[2])
        counts[s3] = counts.get(s3, 0) + 1
        if label_fn is not None and s3 not in label_for:
            try:
                label_for[s3] = label_fn(part)
            except Exception:
                label_for[s3] = None
    buckets = [
        SigBucket(sig=s, count=c, label=label_for.get(s))
        for s, c in counts.items()
    ]
    buckets.sort(key=lambda b: (-b.count, b.sig))
    return buckets


def describe_parts(parts: list,
                   at: Optional[Point3] = None,
                   sig_filter: Optional[Sig3] = None,
                   label: Optional[str] = None,
                   label_fn: Optional[Callable] = None,
                   tol: float = 0.0) -> List[PartInfo]:
    """Return parts matching the given filter(s).

    Filters:
      - `at`: include parts whose bbox contains the point (with tolerance).
      - `sig_filter`: include parts with this exact bbox signature.
      - `label`: include parts whose `label_fn(part)` equals this label.

    Multiple filters are AND-combined. Passing none is allowed and returns
    every part — useful for `cadclaw inspect part assembly.step` with no
    flags to dump everything.
    """
    out: List[PartInfo] = []
    for part in parts:
        s_raw = sig(part)
        if len(s_raw) != 3:
            continue
        s: Sig3 = (s_raw[0], s_raw[1], s_raw[2])
        if sig_filter is not None and s != sig_filter:
            continue
        bb = _bbox_tuple(part)
        if at is not None and not _bbox_contains(bb, at, tol):
            continue
        lbl = label_fn(part) if label_fn else ""
        if label is not None and lbl != label:
            continue
        out.append(PartInfo(
            label=lbl or "",
            sig=s,
            center=center(part),
            bbox=bb,
        ))
    out.sort(key=lambda p: p.center)
    return out


def find_overlaps(parts: list,
                  label_fn: Callable,
                  target_label: Optional[str] = None,
                  target_at: Optional[Point3] = None,
                  skip_labels: Optional[set] = None,
                  min_volume: float = 1.0,
                  min_clearance_mm: float = 1.0,
                  tol: float = 0.0):
    """Return interference clips touching the target part(s).

    Requires `label_fn`. Provide one of `target_label` (filter to clips
    where either side has this label) or `target_at` (filter to clips
    where either part's bbox contains the point). Both is AND.

    Returns `(clips, target_count)` — the second value lets the CLI say
    "no parts matched the target" vs "target had no overlaps".
    A matched target excluded by `skip_labels` raises the typed
    `interference.not_checked` error instead of reporting a false clear.
    Labels are resolved once per exact part identity and the same cached
    values are used by the interference check.
    """
    from .interference import InterferenceCheck, InterferenceExecutionError

    if target_label is None and target_at is None:
        raise ValueError("find_overlaps requires target_label or target_at")

    effective_skip_labels = set(skip_labels or ())
    labels_by_identity: Dict[int, Tuple[object, object]] = {}
    matching_idx = set()
    skipped_matching_idx = set()
    for i, p in enumerate(parts):
        cached = labels_by_identity.get(id(p))
        if cached is None:
            try:
                lbl = label_fn(p)
            except Exception as exc:
                raise InterferenceExecutionError(
                    "interference.label_error",
                    "target labels could not be resolved for interference inspection",
                    error_count=1,
                ) from exc
            # Keep a strong reference beside the value. This makes the cache
            # identity-based even for unhashable or equality-overloaded parts
            # and prevents object-id reuse while the inspection is running.
            labels_by_identity[id(p)] = (p, lbl)
        else:
            cached_part, lbl = cached
            if cached_part is not p:
                raise InterferenceExecutionError(
                    "interference.label_error",
                    "target label identity could not be bound for interference inspection",
                    error_count=1,
                )
        if target_label is not None and lbl != target_label:
            continue
        if target_at is not None:
            try:
                bb = _bbox_tuple(p)
            except Exception as exc:
                raise InterferenceExecutionError(
                    "interference.bounding_box_error",
                    "target bounding boxes could not be evaluated",
                    error_count=1,
                ) from exc
            if not _bbox_contains(bb, target_at, tol):
                continue
        matching_idx.add(i)
        if lbl in effective_skip_labels:
            skipped_matching_idx.add(i)

    if not matching_idx:
        return [], 0
    if skipped_matching_idx:
        raise InterferenceExecutionError(
            "interference.not_checked",
            "interference was not checked: one or more target parts are "
            "excluded by skip_labels",
        )

    def _cached_label_fn(part):
        cached = labels_by_identity.get(id(part))
        if cached is None or cached[0] is not part:
            raise InterferenceExecutionError(
                "interference.label_error",
                "cached target label is unavailable for interference inspection",
                error_count=1,
            )
        return cached[1]

    check = InterferenceCheck(parts, _cached_label_fn,
                              skip_labels=effective_skip_labels,
                              min_volume=min_volume,
                              min_clearance_mm=min_clearance_mm)
    result = check.run()
    if result.error_count:
        raise InterferenceExecutionError(
            "interference.execution_error",
            "one or more interference pair evaluations could not complete",
            error_count=result.error_count,
        )
    if result.not_checked_reason:
        raise InterferenceExecutionError(
            "interference.not_checked",
            f"interference was not checked: {result.not_checked_reason}",
        )

    matching_centers = []
    for i in matching_idx:
        matching_centers.append(center(parts[i]))

    def _matches(c) -> bool:
        # Match by center coincidence — robust to label_fn variability.
        for mc in matching_centers:
            if (abs(mc[0] - c.center_a[0]) < 0.01
                    and abs(mc[1] - c.center_a[1]) < 0.01
                    and abs(mc[2] - c.center_a[2]) < 0.01):
                return True
            if (abs(mc[0] - c.center_b[0]) < 0.01
                    and abs(mc[1] - c.center_b[1]) < 0.01
                    and abs(mc[2] - c.center_b[2]) < 0.01):
                return True
        return False

    relevant = [c for c in result.clips if _matches(c)]
    return relevant, len(matching_idx)


@dataclass
class PartCluster:
    """A spatial cluster of parts produced by `cluster_parts`."""
    name: str                       # 'cluster_1', 'cluster_2', ...
    members: List[PartInfo]         # parts in this cluster
    centroid: Point3                # arithmetic mean of member centers
    bbox: BBox6                     # axis-aligned hull of all member bboxes
    sig_histogram: List[SigBucket]  # signature counts within the cluster


def _bbox_hull(bboxes: List[BBox6]) -> BBox6:
    xmin = min(b[0] for b in bboxes)
    ymin = min(b[1] for b in bboxes)
    zmin = min(b[2] for b in bboxes)
    xmax = max(b[3] for b in bboxes)
    ymax = max(b[4] for b in bboxes)
    zmax = max(b[5] for b in bboxes)
    return (xmin, ymin, zmin, xmax, ymax, zmax)


def _euclid(a: Point3, b: Point3) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def cluster_parts(parts: list,
                  label_fn: Optional[Callable] = None,
                  target_label: Optional[str] = None,
                  radius_mm: float = 100.0) -> List[PartCluster]:
    """Group parts by spatial proximity (single-link agglomerative).

    Two parts join the same cluster if their bbox centers are within
    `radius_mm`. Single-link semantics extend transitively, so a chain
    of close-together parts ends up in one cluster even if its endpoints
    are farther apart than `radius_mm`. This matches the CAD use case:
    "find the X-carriage region" rather than "find tight ball-shaped
    clusters."

    `target_label` filters the input to one label before clustering;
    pass `None` to cluster every part. `target_label="other"` is the
    canonical use case (group the unlabeled remainder by spatial region).

    Clusters are returned sorted by member count descending. Each cluster
    carries a centroid, bbox hull, and per-signature histogram so the
    CLI / agent can quickly see "what's in this region."
    """
    candidates: List[PartInfo] = []
    for p in parts:
        s_raw = sig(p)
        if len(s_raw) != 3:
            continue
        s: Sig3 = (s_raw[0], s_raw[1], s_raw[2])
        lbl = label_fn(p) if label_fn else ""
        if target_label is not None and lbl != target_label:
            continue
        candidates.append(PartInfo(
            label=lbl or "",
            sig=s,
            center=center(p),
            bbox=_bbox_tuple(p),
        ))

    n = len(candidates)
    if n == 0:
        return []

    # Single-link agglomerative — Union-Find over pairwise center distance.
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _euclid(candidates[i].center, candidates[j].center) <= radius_mm:
                union(i, j)

    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    clusters: List[PartCluster] = []
    for member_idxs in groups.values():
        members = [candidates[i] for i in member_idxs]
        cx = sum(m.center[0] for m in members) / len(members)
        cy = sum(m.center[1] for m in members) / len(members)
        cz = sum(m.center[2] for m in members) / len(members)
        hull = _bbox_hull([m.bbox for m in members])
        sig_counts: Dict[Sig3, int] = {}
        for m in members:
            sig_counts[m.sig] = sig_counts.get(m.sig, 0) + 1
        sig_buckets = [
            SigBucket(sig=s, count=c, label=None)
            for s, c in sorted(sig_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        clusters.append(PartCluster(
            name="",  # assigned after sorting
            members=members,
            centroid=(cx, cy, cz),
            bbox=hull,
            sig_histogram=sig_buckets,
        ))

    clusters.sort(key=lambda c: (-len(c.members), c.centroid))
    for i, c in enumerate(clusters, start=1):
        c.name = f"cluster_{i}"
    return clusters


def load_parts(step_path: str) -> list:
    """Convenience wrapper for the CLI to keep imports tidy."""
    return load_and_dedup(step_path)
