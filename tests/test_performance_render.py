"""Camera/visibility reuse tested on existing shipped authored STEP geometry."""
from pathlib import Path
import copy
import json

import cadquery as cq
import pytest
from PIL import Image
import yaml

from cadclaw import assembly_compiler as compiler
from cadclaw import render
from cadclaw.assembly_spec import Transform


SOURCE = Path(__file__).resolve().parents[1] / "examples/relative_placement/parts/plate.step"


def write_spec(root):
    data = {"schema_version": "assembly_spec.v0.1",
            "meta": {"project": "Prepared scene test", "assembly_id": "authored-fixture"},
            "outputs": {"step": (root / "assembly.step").as_posix(), "views_dir": (root / "views").as_posix()},
            "instances": [{"id": f"part_{i}", "role": "plate", "source_path": SOURCE.as_posix(),
                           "transform": {"translate_mm": [i * 100, 0, 0]}} for i in range(3)],
            "review_views": [{"name": view, "view": view, "width": 240, "height": 180}
                             for view in ("iso", "front", "top")]}
    path = root / "spec.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def pixel_count(path, predicate):
    with Image.open(path) as image:
        return sum(predicate(pixel) for pixel in image.convert("RGB").getdata())


def test_three_cameras_share_import_and_tessellation(tmp_path, monkeypatch):
    path = write_spec(tmp_path)
    compiler.run_assembly_build(path, dry_run=False)
    imports, tessellations = [], []
    original_import, original_tessellate = cq.importers.importStep, cq.Shape.toVtkPolyData
    def load(value):
        imports.append(value)
        return original_import(value)
    def tessellate(shape, **kwargs):
        tessellations.append(kwargs)
        return original_tessellate(shape, **kwargs)
    monkeypatch.setattr(cq.importers, "importStep", load)
    monkeypatch.setattr(cq.Shape, "toVtkPolyData", tessellate)
    report = compiler.render_review_views(path)
    assert report.overall.value == "pass"
    assert len(imports) == 1
    assert len(tessellations) == 3
    for output in report.meta["review_views"]:
        assert output["view_state"]["actor_count"] == 3
        assert pixel_count(output["output_path"], lambda rgb: rgb == (151, 215, 0)) > 10


def test_prepared_camera_does_not_accumulate_zoom_or_style(tmp_path):
    kwargs = {"edges": False, "background_top": (1, 1, 1), "background_bottom": (1, 1, 1),
              "use_step_colors": False, "color_map": {"printed": (0.8, 0.1, 0.2)}}
    with render.prepare_step_scene(str(SOURCE), **kwargs) as scene:
        for index, view in enumerate(("iso", "front", "iso")):
            path = tmp_path / f"shared_{index}.png"
            scene.render_to_png(path, width=240, height=180, view=view)
            control = tmp_path / f"separate_{index}.png"
            render.render_step_to_png(str(SOURCE), str(control), width=240, height=180, view=view, **kwargs)
            assert path.read_bytes() == control.read_bytes()
        assert (tmp_path / "shared_0.png").read_bytes() == (tmp_path / "shared_2.png").read_bytes()
    assert scene.closed


def test_render_failure_closes_native_scene(tmp_path):
    scene = render.prepare_step_scene(str(SOURCE))
    with pytest.raises(ValueError, match="Unknown view"):
        scene.render_to_png(tmp_path / "bad.png", view="invalid")
    assert scene.closed
    with pytest.raises(RuntimeError, match="closed"):
        scene.render_to_png(tmp_path / "again.png")


def test_unavailable_depth_peeling_fails_translucent_view(tmp_path, monkeypatch):
    source = cq.importers.importStep(str(SOURCE)).val()
    scene = render.prepare_step_scene(str(SOURCE), instance_shapes=[("part", source)])
    monkeypatch.setattr(scene.renderer, "GetLastRenderingUsedDepthPeeling", lambda: False)
    with pytest.raises(RuntimeError, match="depth peeling unavailable"):
        scene.render_to_png(tmp_path / "unsupported.png", width=240, height=180, opacity_by_instance={"part": 0.2})
    assert scene.view_state["depth_peeling_used"] is False
    assert scene.view_state["translucency_backend"] == "unavailable"
    assert scene.closed
    assert not (tmp_path / "unsupported.png").exists()


def test_explicit_step_override_requires_actual_artifact_map(tmp_path):
    path = write_spec(tmp_path)
    compiler.run_assembly_build(path, dry_run=False)
    report = compiler.render_review_views(path, step_path=SOURCE, opacity_by_instance={"part_0": 0.2})
    assert report.overall.value == "fail"
    assert all("hash-bound" in finding.message for finding in report.findings)


def test_opacity_views_reuse_named_meshes_and_report_actual_backend(tmp_path, monkeypatch):
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["review_views"][1]["opacity_by_instance"] = {"part_0": 0.2}
    path.write_text(yaml.safe_dump(data))
    compiler.run_assembly_build(path, dry_run=False)
    calls = []
    original = cq.Shape.toVtkPolyData
    def tessellate(shape, **kwargs):
        calls.append(shape)
        return original(shape, **kwargs)
    monkeypatch.setattr(cq.Shape, "toVtkPolyData", tessellate)
    report = compiler.render_review_views(path)
    assert report.overall.value == "pass", [f.message for f in report.findings]
    assert len(calls) == 3
    states = [output["view_state"] for output in report.meta["review_views"]]
    assert states[0]["opacity_by_instance"] == {}
    assert states[1]["opacity_by_instance"] == {"part_0": 0.2}
    assert states[1]["depth_peeling_used"] is True
    assert states[2]["opacity_by_instance"] == {}
    assert states[2]["translucency_requested"] is False
    assert states[0]["occurrence_ids"] == ["part_0", "part_1", "part_2"]


@pytest.mark.parametrize("tamper", ["step", "transform", "missing_map", "truncated_ids"])
def test_selective_review_rejects_stale_or_unmapped_artifact(tmp_path, tamper):
    path = write_spec(tmp_path)
    compiler.run_assembly_build(path, dry_run=False)
    output = tmp_path / "assembly.step"
    if tamper == "step":
        output.write_bytes(output.read_bytes() + b"\n")
    elif tamper == "transform":
        data = yaml.safe_load(path.read_text())
        data["instances"][0]["transform"]["translate_mm"] = [20, 0, 0]
        path.write_text(yaml.safe_dump(data))
    elif tamper == "missing_map":
        compiler._step_provenance_path(output).unlink()
    else:
        map_path = compiler._step_provenance_path(output)
        mapping = json.loads(map_path.read_text())
        mapping["occurrence_ids"].pop()
        map_path.write_text(json.dumps(mapping))
    report = compiler.render_review_views(path, opacity_by_instance={"part_0": 0.2})
    assert report.overall.value == "fail"
    assert all(not output["rendered"] for output in report.meta["review_views"])
    assert all("hash-bound" in f.message for f in report.findings)


def test_mesh_and_step_renderers_share_occlusion_and_opacity(tmp_path):
    source = cq.importers.importStep(str(SOURCE))
    center = source.val().Center().toTuple()
    outer = compiler._apply_transform(source, Transform(source_origin_mm=list(center), translate_mm=[20, 0, 0])).val()
    target = compiler._apply_transform(source, Transform(source_origin_mm=list(center), scale=0.5)).val()
    meshes = []
    for name, shape, color in (("occluder", outer, (0.1, 0.2, 0.8)), ("target", target, (0.9, 0.1, 0.1))):
        vertices, triangles = shape.tessellate(0.5)
        meshes.append(render.MeshRenderPart(name, [v.toTuple() for v in vertices], triangles, color))
    with render.prepare_mesh_scene(meshes, edges=False, background_top=(1, 1, 1), background_bottom=(1, 1, 1)) as scene:
        opaque = tmp_path / "opaque.png"
        ghost = tmp_path / "ghost.png"
        scene.render_to_png(opaque, width=240, height=180, view="side")
        scene.render_to_png(ghost, width=240, height=180, view="side", opacity_by_instance={"occluder": 0.2})
        assert scene.view_state["representation"] == "mesh visualization_only"
        assert scene.view_state["depth_peeling_used"] is True
        assert pixel_count(opaque, lambda rgb: rgb[0] > 120 and rgb[0] > rgb[2] * 1.4 and rgb[1] < 150) == 0
        assert pixel_count(ghost, lambda rgb: rgb[0] > 120 and rgb[0] > rgb[2] * 1.4 and rgb[1] < 150) > 20
        scene.render_to_png(tmp_path / "opaque_again.png", width=240, height=180, view="side", opacity_by_instance={})
        assert opaque.read_bytes() == (tmp_path / "opaque_again.png").read_bytes()
    broken = copy.copy(meshes[0])
    object.__setattr__(broken, "triangles", [(0, 1, len(meshes[0].vertices))])
    with pytest.raises(ValueError, match="in-range"):
        render.prepare_mesh_scene([broken])


def test_sequence_forwards_opacity_and_reuses_each_subset_scene(tmp_path, monkeypatch):
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["review_views"][0]["opacity_by_instance"] = {"part_0": 0.25}
    data["assembly_sequence"] = [{"id": "first", "title": "First", "instance_ids": ["part_0"]},
                                 {"id": "second", "title": "Second", "instance_ids": ["part_1", "part_2"]}]
    path.write_text(yaml.safe_dump(data))
    calls = []
    original = cq.Shape.toVtkPolyData
    def tessellate(shape, **kwargs):
        calls.append(shape)
        return original(shape, **kwargs)
    monkeypatch.setattr(cq.Shape, "toVtkPolyData", tessellate)
    report = compiler.run_assembly_sequence(path, output_dir=tmp_path / "sequence", view_names=["iso", "front"])
    assert report.overall.value != "fail", [f.message for f in report.findings]
    assert len(calls) == 4  # One first-step part plus three cumulative parts, once each.
    outputs = report.meta["steps"]
    assert outputs[0]["review_views"][0]["view_state"]["opacity_by_instance"] == {"part_0": 0.25}
    assert outputs[0]["review_views"][0]["view_state"]["occurrence_ids"] == ["part_0"]
    assert outputs[1]["review_views"][0]["view_state"]["occurrence_ids"] == ["part_0", "part_1", "part_2"]


def test_final_sequence_export_supports_standalone_selective_review(tmp_path):
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["assembly_sequence"] = [{"id": "all", "title": "Place all", "instance_ids": ["part_0", "part_1", "part_2"]}]
    path.write_text(yaml.safe_dump(data))
    sequence = compiler.run_assembly_sequence(path, output_dir=tmp_path / "sequence", render_views=False)
    assert sequence.overall.value != "fail"
    final = tmp_path / "sequence/final/final_sequence_assembly.step"
    assert json.loads(compiler._step_provenance_path(final).read_text())["scope"] == "full"
    review = compiler.render_review_views(path, step_path=final, opacity_by_instance={"part_0": 0.2})
    assert review.overall.value == "pass", [f.message for f in review.findings]
    assert all(view["view_state"]["occurrence_ids"] == ["part_0", "part_1", "part_2"]
               for view in review.meta["review_views"])
