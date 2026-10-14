"""Source reuse correctness using shipped STEP bytes, never generated shapes."""
from pathlib import Path
import shutil

import cadquery as cq
import pytest
import yaml

from cadclaw import assembly_compiler as compiler
from cadclaw.assembly_spec import load_assembly_spec


SOURCE = Path(__file__).resolve().parents[1] / "examples/relative_placement/parts/plate.step"


def write_spec(tmp_path, copies=3, source=SOURCE, sequence=False):
    spec = {
        "schema_version": "assembly_spec.v0.1",
        "meta": {"project": "Source reuse test", "assembly_id": "authored-fixture"},
        "outputs": {"step": (tmp_path / "assembly.step").as_posix(),
                    "views_dir": (tmp_path / "views").as_posix(),
                    "design_inventory": (tmp_path / "inventory.json").as_posix()},
        "instances": [{"id": f"part_{i}", "role": "plate", "source_path": source.as_posix(),
                       "transform": {"translate_mm": [i * 100, 0, 0], "rotate_deg": [i * 15, 0, i * 25],
                                     "source_origin_mm": [2, 3, 1], "scale": 1 + i / 10}}
                      for i in range(copies)],
        "validation": {"run_checks": ["interference", "bbox_alignment"], "expected_inventory": {"plate": copies}},
    }
    if sequence:
        spec["assembly_sequence"] = [{"id": f"step_{i}", "title": f"Place {i}", "instance_ids": [f"part_{i}"]}
                                     for i in range(copies)]
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    return path


def signature(shape):
    bb = shape.BoundingBox()
    return [bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax,
            shape.Volume(), shape.Area(), *shape.Center().toTuple()]


def test_one_import_shared_by_export_and_validation(tmp_path, monkeypatch):
    path = write_spec(tmp_path)
    original = cq.importers.importStep
    calls = []
    def counted(source):
        calls.append(source)
        return original(source)
    monkeypatch.setattr(cq.importers, "importStep", counted)
    report = compiler.run_assembly_check_round(path, render_views=False)
    assert len(calls) == 1
    assert report.meta["geometry_cache"]["source_imports"] == 1
    assert report.meta["validation"]["interference"]["placed_instances"] == 3
    assert report.meta["geometry_cache"]["hits"] == 1
    assert (tmp_path / "assembly.step").exists()


def test_transforms_match_legacy_and_prototype_is_immutable(tmp_path):
    path = write_spec(tmp_path)
    spec = load_assembly_spec(path)
    plan = compiler.plan_assembly_build(path)
    cache = compiler.GeometryShapeCache()
    before = signature(cache.source_geometry.load(SOURCE).val())
    records, findings = compiler._placed_instance_shapes(spec, path, plan, shape_cache=cache)
    legacy, old_findings = compiler._placed_instance_shapes(spec, path, plan)
    assert [f.to_dict() for f in findings] == [f.to_dict() for f in old_findings]
    assert [r.id for r in records] == [r.id for r in legacy]
    for new, old in zip(records, legacy):
        assert signature(new.shape) == pytest.approx(signature(old.shape), rel=1e-6, abs=1e-5)
    assert signature(cache.source_geometry.load(SOURCE).val()) == pytest.approx(before, abs=1e-8)
    assert len({tuple(signature(r.shape)[:6]) for r in records}) == 3


def test_cached_subset_cannot_hide_changed_transform(tmp_path):
    path = write_spec(tmp_path)
    spec = load_assembly_spec(path)
    plan = compiler.plan_assembly_build(path)
    cache = compiler.GeometryShapeCache()
    first, _ = compiler._placed_instance_shapes(spec, path, plan, shape_cache=cache)
    edited = spec.instances[0].model_copy(update={"transform": spec.instances[0].transform.model_copy(update={"translate_mm": [50, 0, 0]})})
    changed = spec.model_copy(update={"instances": [edited, *spec.instances[1:]]})
    second, _ = compiler._placed_instance_shapes(changed, path, plan, shape_cache=cache)
    assert signature(first[0].shape) != signature(second[0].shape)
    assert cache.hits == 0
    assert cache.source_geometry.imports == 1


@pytest.mark.parametrize("change", ["bytes", "missing"])
def test_changed_source_rejected_even_on_shape_cache_hit(tmp_path, change):
    local = tmp_path / "authored.step"
    shutil.copyfile(SOURCE, local)
    path = write_spec(tmp_path, source=local)
    spec = load_assembly_spec(path)
    plan = compiler.plan_assembly_build(path)
    cache = compiler.GeometryShapeCache()
    first, _ = compiler._placed_instance_shapes(spec, path, plan, shape_cache=cache)
    assert len(first) == 3
    if change == "bytes":
        local.write_bytes(local.read_bytes() + b"\n")
    else:
        local.unlink()
    records, findings = compiler._placed_instance_shapes(spec, path, plan, shape_cache=cache)
    assert not records
    assert len(findings) == 1
    assert {finding.id for finding in findings} == {"assemble.source_snapshot_changed"}


def test_nonselected_changed_source_invalidates_invocation(tmp_path):
    a = tmp_path / "a.step"
    b = tmp_path / "b.step"
    shutil.copyfile(SOURCE, a)
    shutil.copyfile(SOURCE, b)
    path = write_spec(tmp_path, copies=2, source=a)
    spec = load_assembly_spec(path)
    spec = spec.model_copy(update={"instances": [spec.instances[0], spec.instances[1].model_copy(update={"source_path": b.as_posix()})]})
    path.write_text(yaml.safe_dump(spec.model_dump()), encoding="utf-8")
    plan = compiler.plan_assembly_build(path)
    cache = compiler.GeometryShapeCache()
    first, _ = compiler._placed_instance_shapes(spec, path, plan, instance_ids=["part_0"], shape_cache=cache)
    assert len(first) == 1
    a.write_bytes(a.read_bytes() + b"\n")
    second, findings = compiler._placed_instance_shapes(spec, path, plan, instance_ids=["part_1"], shape_cache=cache)
    assert second == []
    assert findings[0].id == "assemble.source_snapshot_changed"


def test_failed_import_is_never_cached(tmp_path, monkeypatch):
    context = compiler.SourceGeometryContext()
    def fail(_):
        raise RuntimeError("controlled import failure")
    monkeypatch.setattr(cq.importers, "importStep", fail)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="controlled import failure"):
            context.load(SOURCE)
    assert not context.prototypes
    assert context.imports == 0


def test_content_identity_reuses_identical_source_paths(tmp_path):
    local = tmp_path / "same-bytes.step"
    shutil.copyfile(SOURCE, local)
    context = compiler.SourceGeometryContext()
    a, b = context.load(SOURCE), context.load(local)
    assert signature(a.val()) == pytest.approx(signature(b.val()), abs=1e-8)
    assert context.imports == 1
    assert context.hits == 1


def test_sequence_shares_source_across_subset_exports(tmp_path, monkeypatch):
    path = write_spec(tmp_path, sequence=True)
    original = cq.importers.importStep
    calls = []
    def counted(source):
        calls.append(source)
        return original(source)
    monkeypatch.setattr(cq.importers, "importStep", counted)
    report = compiler.run_assembly_sequence(path, output_dir=tmp_path / "sequence", render_views=False)
    assert len(calls) == 1
    assert report.overall.value != "fail"
    assert (tmp_path / "sequence/final/final_sequence_assembly.step").exists()
