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
    """Return the list of renderable Shapes in a STEP file.

    Matches `inventory.load_and_dedup`: both Solids and Shells count, with
    deduplication by exact bbox key. Some CAD packages export thin-walled
    parts (extrusions, sheet metal) as Shells rather than Solids, so
    a Solids-only pass drops them silently.
    """
    compound = cq.importers.importStep(step_path).val()
    raw = list(compound.Solids()) + list(compound.Shells())
    seen = set()
    shapes = []
    for s in raw:
        bb = s.BoundingBox()
        k = (round(bb.xmin, 1), round(bb.ymin, 1), round(bb.zmin, 1),
             round(bb.xmax, 1), round(bb.ymax, 1), round(bb.zmax, 1))
        if k not in seen:
            seen.add(k)
            shapes.append(s)
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


# ---------------------------------------------------------------
# Per-part coloring: distinguish extrusions from printed parts so the
# output reads like a CAD viewport (Fusion-style) instead of a solid-color
# silhouette.
# ---------------------------------------------------------------

# Sunnyday M3-CRETE palette.
COLOR_EXTRUSION = (0.08, 0.08, 0.09)   # anodized black extrusions
COLOR_PRINTED = (0.59, 0.84, 0.0)      # Sunnyday green printed parts
COLOR_METAL = (0.72, 0.74, 0.76)       # aluminum plates / brackets
COLOR_MOTOR = (0.30, 0.30, 0.32)       # stepper body
COLOR_WHEEL = (0.13, 0.13, 0.14)       # V-wheels / delrin
COLOR_BELT = (0.15, 0.15, 0.15)        # GT2 belt

# Label -> color defaults keyed on the M3-CRETE naming scheme.
DEFAULT_COLOR_MAP = {
    'cbeam': COLOR_EXTRUSION, 'beam': COLOR_EXTRUSION,
    'extrusion': COLOR_EXTRUSION, 'post': COLOR_EXTRUSION,
    'motor': COLOR_MOTOR,
    'vwheel': COLOR_WHEEL, 'wheel': COLOR_WHEEL, 'pulley': COLOR_WHEEL,
    'idler': COLOR_WHEEL,
    'belt': COLOR_BELT,
    'plate': COLOR_METAL, 'bracket': COLOR_METAL,
    'shim': COLOR_METAL,
    # Everything else (zmount, zcap, ymount, tbracket, etc.) is printed
    # and gets COLOR_PRINTED via the default fallback.
}


def _default_label_fn(shape):
    """Loose heuristic when no label map is provided.

    Classifies any shape with one dimension >= 400 mm and a small
    cross-section as an extrusion (so it renders black). Everything else
    is treated as a printed/misc part (green)."""
    bb = shape.BoundingBox()
    dims = sorted([bb.xmax - bb.xmin, bb.ymax - bb.ymin, bb.zmax - bb.zmin])
    if dims[2] >= 400 and dims[0] <= 50:
        return 'extrusion'
    return 'printed'


def _color_for(shape, labels, color_map, default_color):
    """Look up a shape's color via its bbox signature / label."""
    from .inventory import sig as _sig
    if labels is None and color_map is None:
        label = _default_label_fn(shape)
    else:
        s = _sig(shape)
        label = (labels or {}).get(s, None)
        if label is None:
            label = _default_label_fn(shape)
    cmap = color_map if color_map is not None else DEFAULT_COLOR_MAP
    return cmap.get(label, default_color)


def _scene_bounds(shapes):
    xs, ys, zs = [], [], []
    for s in shapes:
        bb = s.BoundingBox()
        xs.extend([bb.xmin, bb.xmax])
        ys.extend([bb.ymin, bb.ymax])
        zs.extend([bb.zmin, bb.zmax])
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _aim_camera(renderer, shapes, view: str = "iso", azimuth: float = 0.0,
                 elevation: float = 0.0, zoom: float = 1.1):
    """Point the camera using a CAD-standard Z-up convention.

    Sets the *direction* from the preset and then calls ResetCamera so
    VTK fits the whole scene in view at that angle. The final zoom is
    adjusted by `zoom` (>1 zooms in, <1 zooms out).

    `view` picks the starting octant:
      - "iso":  front-right-above (default, Fusion-like)
      - "iso_left": front-left-above
      - "front": looking along -Y (printer front face)
      - "back":  looking along +Y
      - "side":  looking along +X (right side)
      - "top":   looking down +Z
    """
    xmin, xmax, ymin, ymax, zmin, zmax = _scene_bounds(shapes)
    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2
    cz = (zmin + zmax) / 2

    # Direction unit vectors (from focal point toward camera).
    view = view.lower()
    directions = {
        "iso":      (1.0, -1.0, 0.7),
        "iso_left": (-1.0, -1.0, 0.7),
        "front":    (0.0, -1.0, 0.0),
        "back":     (0.0, 1.0, 0.0),
        "side":     (1.0, 0.0, 0.0),
        "top":      (0.0, 0.0, 1.0),
    }
    if view not in directions:
        raise ValueError(f"Unknown view preset: {view!r}")

    dx, dy, dz = directions[view]

    cam = renderer.GetActiveCamera()
    cam.SetFocalPoint(cx, cy, cz)
    cam.SetViewUp(0.0, 1.0, 0.0) if view == "top" else cam.SetViewUp(0.0, 0.0, 1.0)
    # Seed position — distance doesn't matter, ResetCamera re-fits after.
    cam.SetPosition(cx + dx * 1000.0, cy + dy * 1000.0, cz + dz * 1000.0)

    renderer.ResetCamera()
    if azimuth:
        cam.Azimuth(azimuth)
    if elevation:
        cam.Elevation(elevation)
    if zoom and zoom != 1.0:
        cam.Zoom(zoom)
    renderer.ResetCameraClippingRange()


def render_step_to_png(step_path: str, output_path: str,
                        width: int = 960, height: int = 720,
                        view: str = "iso",
                        azimuth: float = 0.0, elevation: float = 0.0,
                        background_top: tuple = (0.62, 0.66, 0.70),
                        background_bottom: tuple = (0.38, 0.42, 0.47),
                        labels: dict = None,
                        color_map: dict = None,
                        default_color: tuple = COLOR_PRINTED,
                        edges: bool = True,
                        edge_color: tuple = (0.05, 0.06, 0.06),
                        tessellation_tol: float = 0.5):
    """Render a STEP file to a PNG via offscreen VTK — CAD-standard Z-up,
    per-part coloring (black extrusions, green printed parts, metal
    plates), blue-grey gradient background, studio lighting, visible
    part edges. Approximates a Fusion viewport.

    Args:
        step_path: Input STEP file.
        output_path: Output PNG path.
        width, height: Image size in pixels.
        view: Camera preset. One of "iso" (default), "iso_left", "front",
            "back", "side", "top".
        azimuth, elevation: Fine-tuning rotations applied after the view
            preset, in degrees.
        background_top, background_bottom: RGB 0-1 gradient (top to bottom).
            Default is a Fusion-like blue-grey.
        labels: Optional bbox-signature -> label dict (e.g. the same dict
            used by Harness). Lets the renderer color parts consistently.
        color_map: Optional label -> RGB dict. Defaults to
            DEFAULT_COLOR_MAP (extrusions black, printed green, metal grey).
        default_color: Color used when no label matches. Defaults to green.
        edges: Draw part edges for a CAD-like silhouette.
        edge_color: RGB 0-1 for the edges.
        tessellation_tol: Mesh tolerance in mm. Coarser = faster, less detail.
    """
    import vtk

    shapes = _load_shapes(step_path)
    if not shapes:
        raise ValueError(f"No geometry found in {step_path}")

    renderer = vtk.vtkRenderer()
    renderer.SetBackground(*background_bottom)
    renderer.SetBackground2(*background_top)
    renderer.GradientBackgroundOn()

    # One actor per shape so colors can differ per part (extrusion vs printed).
    for shape in shapes:
        poly = shape.toVtkPolyData(tolerance=tessellation_tol,
                                     angularTolerance=0.3)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        color = _color_for(shape, labels, color_map, default_color)
        prop.SetColor(*color)
        prop.SetAmbient(0.22)
        prop.SetDiffuse(0.78)
        prop.SetSpecular(0.30)
        prop.SetSpecularPower(22)
        if edges:
            prop.EdgeVisibilityOn()
            prop.SetEdgeColor(*edge_color)
            prop.SetLineWidth(0.6)
        renderer.AddActor(actor)

    light_kit = vtk.vtkLightKit()
    light_kit.SetKeyLightWarmth(0.58)
    light_kit.SetKeyLightIntensity(0.95)
    light_kit.SetFillLightWarmth(0.45)
    light_kit.AddLightsToRenderer(renderer)

    _aim_camera(renderer, shapes, view=view,
                 azimuth=azimuth, elevation=elevation)

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetMultiSamples(8)
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
                          width: int = 960, height: int = 720,
                          view: str = "iso",
                          azimuth: float = 0.0, elevation: float = 0.0,
                          labels: dict = None,
                          color_map: dict = None,
                          default_color: tuple = COLOR_PRINTED,
                          background_top: tuple = (0.62, 0.66, 0.70),
                          background_bottom: tuple = (0.38, 0.42, 0.47),
                          edges: bool = True,
                          tessellation_tol: float = 0.5,
                          gif_width: int = None, gif_height: int = None,
                          gif_colors: int = 64,
                          optimize: bool = True,
                          keep_pngs: bool = False):
    """Render every matching STEP in `frames_dir` to a PNG, then assemble an
    animated GIF. See render_step_to_png for styling parameters.

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
                            view=view,
                            azimuth=azimuth, elevation=elevation,
                            labels=labels, color_map=color_map,
                            default_color=default_color,
                            background_top=background_top,
                            background_bottom=background_bottom,
                            edges=edges,
                            tessellation_tol=tessellation_tol)
        png_paths.append(png_path)

    # GIF encoding: optional downscale + adaptive palette quantization.
    # Render width/height were used for the source PNGs; gif_width/height
    # downsample for file size. gif_colors limits the palette.
    gw = gif_width or width
    gh = gif_height or height
    frames = []
    for p in png_paths:
        img = Image.open(p).convert("RGB")
        if (gw, gh) != img.size:
            img = img.resize((gw, gh), Image.LANCZOS)
        frames.append(img.convert("P", palette=Image.ADAPTIVE,
                                    colors=max(2, min(256, gif_colors))))
    duration_ms = max(1, int(1000 / max(fps, 1)))
    frames[0].save(output_gif, save_all=True, append_images=frames[1:],
                    duration=duration_ms, loop=0, optimize=optimize,
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
        render_kwargs.setdefault('labels', labels)
        n = render_frames_to_gif(frames_dir, output_gif, fps=fps,
                                   **render_kwargs)
        return n
    finally:
        if use_tmp and not keep_frames:
            shutil.rmtree(frames_dir, ignore_errors=True)
