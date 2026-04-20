"""STEP -> PNG -> GIF rendering helpers.

Closes the loop between the disassembly-sequence generator and an
animated output. A disassembly frame set is 3D geometry (STEP files);
to turn it into a GIF you have to rasterize each frame to a PNG, then
stitch the PNGs. This module does both.

Usage:
    from cadharness.render import render_step_to_png, render_frames_to_gif, make_disassembly_gif

    # One-shot: STEP -> disassembly frames -> PNGs -> animated GIF
    make_disassembly_gif("assembly.step", "out.gif",
                          expansion_max=0.6, n_frames=30, fps=12)

    # Or render an existing frame directory
    render_frames_to_gif("frames/", "out.gif", fps=10)

Runtime dependency: vtk (bundled with cadquery-ocp) + Pillow.
Rendering is offscreen so it works in headless environments.
"""
import glob
import os
import shutil
import tempfile

import cadquery as cq
from cadquery import Assembly, Color, Location
from PIL import Image

from .disassembly import DisassemblySequence, _center


def _load_shapes(step_path: str):
    """Return the list of cadquery Shapes in a STEP file."""
    wp = cq.importers.importStep(step_path)
    shapes = []
    for obj in wp.objects:
        if hasattr(obj, "Solids"):
            solids = obj.Solids()
            if solids:
                shapes.extend(solids)
            else:
                shapes.append(obj)
        else:
            shapes.append(obj)
    return shapes


def _combined_polydata(shapes, tolerance: float = 0.5, angular: float = 0.3):
    """Merge all shapes into a single vtkPolyData for rendering."""
    import vtk
    append = vtk.vtkAppendPolyData()
    for s in shapes:
        poly = s.toVtkPolyData(tolerance=tolerance, angularTolerance=angular)
        append.AddInputData(poly)
    append.Update()
    return append.GetOutput()


def render_step_to_png(step_path: str, output_path: str,
                        width: int = 800, height: int = 600,
                        azimuth: float = -30.0, elevation: float = 25.0,
                        background: tuple = (0.024, 0.051, 0.078),
                        part_color: tuple = (0.59, 0.84, 0.0),
                        tessellation_tol: float = 0.5):
    """Render a STEP file to a PNG via offscreen VTK.

    Args:
        step_path: Input STEP file.
        output_path: Output PNG path.
        width, height: Image size in pixels.
        azimuth, elevation: Camera angles in degrees (from the default
            orthographic-ish view).
        background: RGB 0-1 background color. Default matches Sunnyday dark.
        part_color: RGB 0-1 part color. Default matches M3-CRETE green.
        tessellation_tol: Mesh tolerance in mm. Coarser = faster, less detail.
    """
    import vtk

    shapes = _load_shapes(step_path)
    if not shapes:
        raise ValueError(f"No geometry found in {step_path}")

    poly = _combined_polydata(shapes, tolerance=tessellation_tol)

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*part_color)
    actor.GetProperty().SetAmbient(0.25)
    actor.GetProperty().SetDiffuse(0.7)
    actor.GetProperty().SetSpecular(0.2)

    renderer = vtk.vtkRenderer()
    renderer.SetBackground(*background)
    renderer.AddActor(actor)
    renderer.ResetCamera()
    cam = renderer.GetActiveCamera()
    cam.Azimuth(azimuth)
    cam.Elevation(elevation)
    renderer.ResetCameraClippingRange()

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(width, height)
    window.AddRenderer(renderer)
    window.Render()

    to_image = vtk.vtkWindowToImageFilter()
    to_image.SetInput(window)
    to_image.ReadFrontBufferOff()
    to_image.Update()

    writer = vtk.vtkPNGWriter()
    writer.SetFileName(output_path)
    writer.SetInputConnection(to_image.GetOutputPort())
    writer.Write()

    window.Finalize()
    return output_path


def render_frames_to_gif(frames_dir: str, output_gif: str,
                          fps: int = 10,
                          pattern: str = "frame_*.step",
                          width: int = 800, height: int = 600,
                          azimuth: float = -30.0, elevation: float = 25.0,
                          part_color: tuple = (0.59, 0.84, 0.0),
                          tessellation_tol: float = 0.5,
                          keep_pngs: bool = False):
    """Render every matching STEP in `frames_dir` to a PNG, then assemble an
    animated GIF.

    Returns the number of frames written. Intermediate PNGs are deleted
    unless `keep_pngs=True`.
    """
    step_paths = sorted(glob.glob(os.path.join(frames_dir, pattern)))
    if not step_paths:
        raise FileNotFoundError(
            f"No frames matching {pattern!r} in {frames_dir}")

    png_paths = []
    for step_path in step_paths:
        png_path = os.path.splitext(step_path)[0] + ".png"
        render_step_to_png(step_path, png_path,
                            width=width, height=height,
                            azimuth=azimuth, elevation=elevation,
                            part_color=part_color,
                            tessellation_tol=tessellation_tol)
        png_paths.append(png_path)

    frames = [Image.open(p).convert("P", palette=Image.ADAPTIVE)
              for p in png_paths]
    duration_ms = max(1, int(1000 / max(fps, 1)))
    frames[0].save(output_gif, save_all=True, append_images=frames[1:],
                    duration=duration_ms, loop=0, optimize=False,
                    disposal=2)

    if not keep_pngs:
        for p in png_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    return len(frames)


def make_disassembly_gif(step_path: str, output_gif: str,
                          priority: dict = None,
                          labels: dict = None,
                          explode_distance: float = 300.0,
                          n_transition_frames: int = 5,
                          fps: int = 10,
                          frames_dir: str = None,
                          keep_frames: bool = False,
                          **render_kwargs):
    """End-to-end: STEP -> disassembly frames -> PNGs -> animated GIF.

    Generates the disassembly sequence, writes STEP frames to a temp
    directory, rasterizes each to a PNG, and stitches the PNGs into a GIF.

    Args:
        step_path: Input assembly STEP.
        output_gif: Output GIF path.
        priority, labels: Passed to DisassemblySequence.
        explode_distance, n_transition_frames: Passed to export_frames.
        fps: GIF frames per second.
        frames_dir: If given, frames are written here (persisted). Otherwise
            a temporary directory is used and cleaned up unless keep_frames.
        keep_frames: Keep the frame STEP files after the GIF is built.
        **render_kwargs: Passed through to render_step_to_png (width,
            height, azimuth, elevation, part_color, tessellation_tol).
    """
    use_tmp = frames_dir is None
    if use_tmp:
        frames_dir = tempfile.mkdtemp(prefix="cadclaw_frames_")

    try:
        seq = DisassemblySequence(step_path, labels=labels)
        seq.auto_sequence(priority=priority)
        seq.export_frames(frames_dir,
                           explode_distance=explode_distance,
                           n_transition_frames=n_transition_frames)
        n = render_frames_to_gif(frames_dir, output_gif, fps=fps,
                                   **render_kwargs)
        return n
    finally:
        if use_tmp and not keep_frames:
            shutil.rmtree(frames_dir, ignore_errors=True)
