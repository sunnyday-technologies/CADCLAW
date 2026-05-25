"""Generate shareable M3-CRETE sequence GIFs from the latest assembly outputs.

Outputs:
- assembly_progress_360.gif: cumulative assembly steps 02-06 over one slow orbit.
- final_explode_slow_rotate.gif: final assembly exploded outward, then slow 360.

These are generated artifacts under examples/m3_crete/build/ and are not
intended to be committed.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile

from PIL import Image

from cadclaw.render import (
    COLOR_PRINTED,
    DEFAULT_COLOR_MAP,
    _aim_camera,
    _color_for,
    _load_shapes,
    _part_color_groups,
    quantize_gif_frames,
    render_radial_explode_gif,
)


STEP_SEQUENCE = [
    "02_x_carriage.step",
    "03_y_gantry.step",
    "04_z_carriages.step",
    "05_z_posts.step",
    "06_frame_completion.step",
]

REVEAL_2040_SIGNATURE = (20.0, 40.0, 1000.0)
REVEAL_2040_LIFT_MM = -300.0


def _shape_size_signature(shape) -> tuple[float, float, float]:
    bb = shape.BoundingBox()
    return tuple(round(length, 1) for length in sorted((bb.xlen, bb.ylen, bb.zlen)))


def _shape_is_x_2040_insert(shape) -> bool:
    bb = shape.BoundingBox()
    return (
        _shape_size_signature(shape) == REVEAL_2040_SIGNATURE
        and round(bb.xlen, 1) == 1000.0
    )


def _render_step_orbit_frames(
    step_path: Path,
    reference_shapes,
    output_dir: Path,
    start_frame: int,
    frame_count: int,
    start_azimuth: float,
    step_degrees: float,
    *,
    width: int,
    height: int,
    view: str,
    zoom: float,
    tessellation_tol: float,
    gif_width: int,
    gif_height: int,
    gif_colors: int,
    edges: bool,
    reveal_2040: bool,
) -> list[Image.Image]:
    import vtk

    shapes = _load_shapes(str(step_path))
    # Use the CADCLAW semantic palette for shareable M3 artifacts. STEP-stored
    # AP242 colors vary by source asset and made the brand green drift in GIFs.
    step_colors = None
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.38, 0.42, 0.47)
    renderer.SetBackground2(0.62, 0.66, 0.70)
    renderer.GradientBackgroundOn()

    for shape in shapes:
        base_color = _color_for(
            shape,
            labels=None,
            color_map=DEFAULT_COLOR_MAP,
            default_color=COLOR_PRINTED,
            step_colors=step_colors,
        )
        lift = reveal_2040 and _shape_is_x_2040_insert(shape)
        # Perforated gantry plates render with dark bore faces (black holes).
        for sub_shape, sub_color in _part_color_groups(shape, base_color):
            poly = sub_shape.toVtkPolyData(tolerance=tessellation_tol, angularTolerance=0.3)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly)
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            if lift:
                actor.SetPosition(0.0, 0.0, REVEAL_2040_LIFT_MM)
            prop = actor.GetProperty()
            prop.SetColor(*sub_color)
            prop.SetAmbient(1.0)
            prop.SetDiffuse(0.0)
            prop.SetSpecular(0.0)
            if edges:
                prop.EdgeVisibilityOn()
                prop.SetEdgeColor(0.05, 0.06, 0.06)
                prop.SetLineWidth(0.6)
            renderer.AddActor(actor)

    head = vtk.vtkLight()
    head.SetLightTypeToHeadlight()
    head.SetIntensity(1.0)
    renderer.AddLight(head)

    _aim_camera(renderer, reference_shapes, view=view, zoom=zoom)
    cam = renderer.GetActiveCamera()
    if start_azimuth:
        cam.Azimuth(start_azimuth)
    renderer.ResetCameraClippingRange()

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetMultiSamples(0)
    window.SetSize(width, height)
    window.AddRenderer(renderer)

    frames: list[Image.Image] = []
    for local_index in range(frame_count):
        window.Render()
        to_image = vtk.vtkWindowToImageFilter()
        to_image.SetInput(window)
        to_image.ReadFrontBufferOff()
        to_image.Update()
        writer = vtk.vtkPNGWriter()
        png_path = output_dir / f"assembly_progress_{start_frame + local_index:04d}.png"
        writer.SetFileName(str(png_path))
        writer.SetInputConnection(to_image.GetOutputPort())
        writer.Write()
        img = Image.open(png_path).convert("RGB")
        if (gif_width, gif_height) != img.size:
            img = img.resize((gif_width, gif_height), Image.LANCZOS)
        frames.append(img)
        cam.Azimuth(step_degrees)
        renderer.ResetCameraClippingRange()

    window.Finalize()
    return frames


def build_assembly_progress_gif(
    steps_dir: Path,
    output_gif: Path,
    *,
    total_frames: int = 80,
    fps: int = 8,
    width: int = 960,
    height: int = 540,
    gif_width: int = 960,
    gif_height: int = 540,
    gif_colors: int = 64,
    view: str = "hero",
) -> dict:
    output_gif.parent.mkdir(parents=True, exist_ok=True)
    step_paths = [steps_dir / name for name in STEP_SEQUENCE]
    missing = [str(path) for path in step_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing sequence STEP files: {missing}")

    reference_shapes = _load_shapes(str(step_paths[-1]))
    tmp_dir = Path(tempfile.mkdtemp(prefix="cadclaw_assembly_progress_"))
    frames: list[Image.Image] = []
    try:
        base = total_frames // len(step_paths)
        remainder = total_frames % len(step_paths)
        step_degrees = 360.0 / max(total_frames, 1)
        frame_index = 0
        for step_index, step_path in enumerate(step_paths):
            frame_count = base + (1 if step_index < remainder else 0)
            frames.extend(_render_step_orbit_frames(
                step_path,
                reference_shapes,
                tmp_dir,
                frame_index,
                frame_count,
                frame_index * step_degrees,
                step_degrees,
                width=width,
                height=height,
                view=view,
                zoom=0.92,
                tessellation_tol=0.8,
                gif_width=gif_width,
                gif_height=gif_height,
                gif_colors=gif_colors,
                edges=False,
                reveal_2040=True,
            ))
            frame_index += frame_count

        paletted = quantize_gif_frames(frames, gif_colors)
        duration_ms = max(1, int(1000 / max(fps, 1)))
        paletted[0].save(
            output_gif,
            save_all=True,
            append_images=paletted[1:],
            duration=duration_ms,
            loop=0,
            optimize=True,
            disposal=2,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "output": str(output_gif),
        "frames": len(frames),
        "fps": fps,
        "source_steps": [str(path) for path in step_paths],
    }


def build_explode_gif(final_step: Path, output_gif: Path) -> dict:
    output_gif.parent.mkdir(parents=True, exist_ok=True)
    frame_count = render_radial_explode_gif(
        str(final_step),
        str(output_gif),
        expansion=0.22,
        explode_frames=24,
        hold_frames=8,
        rotate_frames=90,
        fps=8,
        width=768,
        height=432,
        view="hero",
        zoom=0.9,
        tessellation_tol=0.8,
        gif_width=768,
        gif_height=432,
        gif_colors=64,
        edges=False,
        use_step_colors=False,
        separate_nested=True,
        nested_separation_mm=0.0,
        nested_lift_mm=REVEAL_2040_LIFT_MM,
        reveal_bbox_signatures=[REVEAL_2040_SIGNATURE],
        reveal_long_axes=[0],
    )
    return {"output": str(output_gif), "frames": frame_count, "fps": 8}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate M3-CRETE sequence GIFs.")
    parser.add_argument(
        "--sequence-dir",
        default="examples/m3_crete/build/sequence",
        help="Existing render-sequence output directory.",
    )
    parser.add_argument("--assembly-frames", type=int, default=80)
    parser.add_argument("--assembly-fps", type=int, default=8)
    parser.add_argument("--skip-explode", action="store_true")
    parser.add_argument("--skip-assembly", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    sequence_dir = Path(args.sequence_dir)
    steps_dir = sequence_dir / "steps"
    final_dir = sequence_dir / "final"
    summaries = []
    if not args.skip_assembly:
        summaries.append(build_assembly_progress_gif(
            steps_dir,
            final_dir / "assembly_progress_360.gif",
            total_frames=args.assembly_frames,
            fps=args.assembly_fps,
        ))
    if not args.skip_explode:
        summaries.append(build_explode_gif(
            final_dir / "final_sequence_assembly.step",
            final_dir / "final_explode_slow_rotate.gif",
        ))
    for summary in summaries:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
