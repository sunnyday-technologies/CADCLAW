"""STEP -> PNG -> GIF rendering helpers.

Closes the loop between the disassembly-sequence generator and an
animated output. A disassembly frame set is 3D geometry (STEP files);
to turn it into a GIF you have to rasterize each frame to a PNG, then
stitch the PNGs. This module does both.

Usage:
    from cadclaw.render import render_step_to_png, render_frames_to_gif, make_disassembly_gif

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
import sys
import tempfile

import cadquery as cq
from cadquery import Assembly, Color, Location
from PIL import Image

from .disassembly import DisassemblySequence, _center


GIF_SIZE_WARN_BYTES = 5_000_000


def _warn_if_gif_too_large(output_gif: str) -> int:
    """Warn on stderr if the rendered GIF is too large to be embedded as an
    image payload by common chat or assistant clients. Threshold set at 5 MB
    to stay conservative for multimodal payload caps; empirical 4.76 MB GIFs
    have rendered successfully in chat.
    Returns the file size in bytes."""
    try:
        size = os.path.getsize(output_gif)
    except OSError:
        return -1
    if size > GIF_SIZE_WARN_BYTES:
        sys.stderr.write(
            f"WARNING: {output_gif} is {size/1_000_000:.2f} MB, exceeds "
            f"{GIF_SIZE_WARN_BYTES/1_000_000:.1f} MB gate. Some clients may "
            f"reject it as 'Image too large'. Reduce gif_width/height, "
            f"lower gif_colors (e.g. 32), drop frames, or keep optimize=True.\n"
        )
    return size


def _rgb255(color: tuple) -> tuple[int, int, int]:
    return tuple(
        int(round(max(0.0, min(1.0, channel)) * 255))
        for channel in color
    )


def _gif_palette_image(gif_colors: int) -> Image.Image:
    """Return a fixed CADCLAW GIF palette.

    Adaptive GIF palettes are efficient, but small green parts can be rare
    enough in a frame that the encoder maps them toward gray. This fixed
    palette keeps functional CAD colors exact while still using a small
    palette for shareable artifacts.
    """
    palette_colors = max(2, min(256, gif_colors))
    fixed = [
        _rgb255(COLOR_PRINTED),
        _rgb255(COLOR_WHEEL),
        (112, 160, 0),
        (128, 184, 0),
        (170, 230, 28),
        _rgb255(COLOR_EXTRUSION),
        (32, 34, 38),
        (48, 52, 58),
        (64, 70, 78),
        _rgb255(COLOR_METAL),
        (150, 154, 160),
        (188, 192, 196),
        _rgb255(COLOR_MOTOR),
        _rgb255(COLOR_BELT),
        (97, 107, 120),
        (122, 134, 145),
        (146, 157, 168),
        (158, 168, 179),
        (180, 188, 196),
        (255, 255, 255),
        (0, 0, 0),
    ]
    bottom = (97, 107, 120)
    top = (158, 168, 179)
    ramp_slots = max(0, palette_colors - len(fixed))
    for index in range(ramp_slots):
        t = index / max(1, ramp_slots - 1)
        fixed.append(tuple(
            int(round(bottom[channel] * (1.0 - t) + top[channel] * t))
            for channel in range(3)
        ))
    fixed = fixed[:palette_colors]
    while len(fixed) < 256:
        fixed.append(fixed[-1])

    palette = Image.new("P", (1, 1))
    palette.putpalette([channel for rgb in fixed for channel in rgb])
    return palette


def quantize_gif_frames(frames: list[Image.Image], gif_colors: int) -> list[Image.Image]:
    """Quantize RGB frames with CADCLAW's fixed functional palette."""
    palette = _gif_palette_image(gif_colors)
    return [
        frame.convert("RGB").quantize(palette=palette, dither=Image.NONE)
        for frame in frames
    ]


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
# output reads like a shaded CAD viewport instead of a solid-color
# silhouette.
# ---------------------------------------------------------------

# Sunnyday M3-CRETE palette.
COLOR_EXTRUSION = (0.08, 0.08, 0.09)   # anodized black extrusions
COLOR_PRINTED = (151 / 255, 215 / 255, 0.0)  # Sunnyday brand green #97d700
COLOR_METAL = (0.72, 0.74, 0.76)       # aluminum plates / brackets
COLOR_MOTOR = (0.30, 0.30, 0.32)       # stepper body
COLOR_WHEEL = COLOR_PRINTED            # brand-green V-wheels for review
COLOR_BELT = (0.15, 0.15, 0.15)        # GT2 belt

# Label -> color defaults keyed on the M3-CRETE naming scheme.
# Printed parts explicit so they render bright-green under label-map
# priority; previously the "default fallback → green" path was bypassed
# once AP242 colors were added, causing printed parts to dim to their
# raw STEP-stored RGB (which can be a darker design-intent value).
DEFAULT_COLOR_MAP = {
    'cbeam': COLOR_EXTRUSION, 'beam': COLOR_EXTRUSION,
    'extrusion': COLOR_EXTRUSION, 'post': COLOR_EXTRUSION,
    'rail': COLOR_EXTRUSION, 'vslot_2040': COLOR_EXTRUSION,
    'vslot_2080': COLOR_EXTRUSION,
    'motor': COLOR_MOTOR,
    'vwheel': COLOR_WHEEL, 'wheel': COLOR_WHEEL, 'pulley': COLOR_WHEEL,
    'idler': COLOR_WHEEL,
    'belt': COLOR_BELT,
    'plate': COLOR_METAL, 'bracket': COLOR_METAL,
    'shim': COLOR_METAL,
    # Printed parts — bright Sunnyday green.
    'tbracket': COLOR_PRINTED, 'gusset': COLOR_PRINTED,
    'bot-mount': COLOR_PRINTED, 'ymount': COLOR_PRINTED,
    'zmount': COLOR_PRINTED, 'zcap': COLOR_PRINTED,
    'mount': COLOR_PRINTED, 'printed': COLOR_PRINTED,
    'idler-brk': COLOR_PRINTED,
}


class StepColorReadError(RuntimeError):
    """STEP color metadata could not be read through the XCAF boundary."""

    def __init__(self, code: str):
        self.code = code
        super().__init__("STEP color metadata could not be evaluated")


def _step_color_dim_sig(shape, *, strict: bool = False):
    """Return a validated color-map signature for one native shape."""
    try:
        from OCP.BRepBndLib import BRepBndLib
        from OCP.Bnd import Bnd_Box
        from .bbox import validate_bbox

        bbox = Bnd_Box()
        BRepBndLib.Add_s(shape, bbox)
        if bbox.IsVoid():
            raise ValueError("void bounding box")
        xmin, ymin, zmin, xmax, ymax, zmax = validate_bbox(bbox.Get())
    except Exception:
        if strict:
            raise StepColorReadError("color.bbox_failed") from None
        return None
    return tuple(sorted((
        round(xmax - xmin, 1),
        round(ymax - ymin, 1),
        round(zmax - zmin, 1),
    )))


def _extract_step_colors(step_path: str, *, strict: bool = False) -> dict:
    """Extract per-shape RGB colors from a STEP file's STEPCAF metadata.

    Returns a dict {dim_signature: (r, g, b)} where dim_signature is
    the sorted 3-tuple of rounded extents `(round(dx,1), round(dy,1),
    round(dz,1))` — the same signature used by `cadclaw.inventory.sig`.
    Keying by dim-sig (not bbox extents) is translation + orientation-
    invariant: `STEPCAFControl_Reader` returns leaf shapes at their
    original coordinates (at/near origin), while `cq.importers.importStep`
    returns shapes with assembly transforms applied, so full-bbox keys
    never match for parts placed away from origin. Dim-sig survives the
    transform so all instances of a shape share a color.

    When multiple shapes in the STEP share a dim-sig but carry different
    colors, last-write wins. Acceptable for v1: in practice shape
    duplicates (same extents) overwhelmingly share a color, because they
    are copies of the same part; genuine collisions are rare and resolving
    them would require per-instance tracking we don't need yet.

    Only shapes with an assigned color in the STEP appear in the dict;
    un-colored shapes are omitted so callers can fall through to
    label-based coloring.

    Returns {} after a successful read when the STEP has no color metadata.
    Rendering callers keep the legacy best-effort behavior. Validation callers
    pass ``strict=True`` so reader/import/input failures are typed errors rather
    than indistinguishable missing-color warnings.
    """
    try:
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.TDocStd import TDocStd_Document
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorType
        from OCP.TDF import TDF_LabelSequence
        from OCP.Quantity import Quantity_Color
    except ImportError:
        if strict:
            raise StepColorReadError("color.reader_unavailable") from None
        return {}

    try:
        doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
        reader = STEPCAFControl_Reader()
        reader.SetColorMode(True)
        reader.SetLayerMode(False)
        reader.SetNameMode(False)
        read_ok = reader.ReadFile(step_path)
    except Exception:
        if strict:
            raise StepColorReadError("color.read_failed") from None
        return {}
    if read_ok != IFSelect_ReturnStatus.IFSelect_RetDone:
        if strict:
            raise StepColorReadError("color.read_failed") from None
        return {}
    try:
        transferred = reader.Transfer(doc)
    except Exception:
        if strict:
            raise StepColorReadError("color.transfer_failed") from None
        return {}
    if transferred is False:
        if strict:
            raise StepColorReadError("color.transfer_failed") from None
        return {}

    try:
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    except Exception:
        if strict:
            raise StepColorReadError("color.traversal_failed") from None
        return {}

    colors = {}

    def _try_color(shape):
        c = Quantity_Color()
        for ctype in (XCAFDoc_ColorType.XCAFDoc_ColorSurf,
                      XCAFDoc_ColorType.XCAFDoc_ColorGen,
                      XCAFDoc_ColorType.XCAFDoc_ColorCurv):
            if color_tool.GetColor(shape, ctype, c):
                return (c.Red(), c.Green(), c.Blue())
        return None

    def _walk(label, inherited_color):
        """Recurse through assembly structure, recording color per leaf."""
        try:
            shape = shape_tool.GetShape_s(label)
        except Exception:
            if strict:
                raise StepColorReadError("color.traversal_failed") from None
            return
        try:
            own = _try_color(shape) if shape is not None else None
            is_assembly = shape_tool.IsAssembly_s(label)
        except Exception:
            if strict:
                raise StepColorReadError("color.traversal_failed") from None
            return
        eff = own if own is not None else inherited_color

        if is_assembly:
            try:
                children = TDF_LabelSequence()
                shape_tool.GetComponents_s(label, children)
            except Exception:
                if strict:
                    raise StepColorReadError("color.traversal_failed") from None
                return
            try:
                child_count = children.Length()
            except Exception:
                if strict:
                    raise StepColorReadError(
                        "color.traversal_failed"
                    ) from None
                return
            for j in range(1, child_count + 1):
                try:
                    child = children.Value(j)
                except Exception:
                    if strict:
                        raise StepColorReadError(
                            "color.traversal_failed"
                        ) from None
                    continue
                try:
                    from OCP.TDF import TDF_Label
                    ref_out = TDF_Label()
                    if shape_tool.GetReferredShape_s(child, ref_out):
                        _walk(ref_out, eff)
                        continue
                except Exception:
                    if strict:
                        raise StepColorReadError(
                            "color.traversal_failed"
                        ) from None
                _walk(child, eff)
        else:
            if eff is not None and shape is not None:
                sig = _step_color_dim_sig(shape, strict=strict)
                if sig is not None:
                    colors[sig] = eff

    try:
        top_labels = TDF_LabelSequence()
        shape_tool.GetFreeShapes(top_labels)
        top_count = top_labels.Length()
        for i in range(1, top_count + 1):
            try:
                top_label = top_labels.Value(i)
            except Exception:
                if strict:
                    raise StepColorReadError(
                        "color.traversal_failed"
                    ) from None
                continue
            _walk(top_label, None)
    except StepColorReadError:
        raise
    except Exception:
        if strict:
            raise StepColorReadError("color.traversal_failed") from None
        # Preserve the renderer's historical best-effort behavior and any
        # colors established before an unexpected native traversal failure.
        return colors

    return colors


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


def _color_for(shape, labels, color_map, default_color, step_colors=None):
    """Look up a shape's color.

    Priority (intentional):
      1. Caller's label map (labels[dim_sig] -> color_map[label]) —
         brand/semantic colors the user authored for visual clarity.
      2. STEP AP242 color (step_colors[dim_sig]) — raw STEP-stored
         RGB, used only when the shape has no label.
      3. default_color.

    Label map wins because exported STEP RGB does not necessarily match what
    the native CAD viewport shows users. The caller's own color map is the
    authoritative visual source when present.

    Note: step_colors must be keyed by dim-signature (sorted 3-tuple of
    rounded extents), the same signature `inventory.sig` uses.
    """
    from .inventory import sig as _sig
    s = _sig(shape)

    # Step 1: caller-authored label map
    if labels is not None:
        label = labels.get(s, None)
        if label is not None:
            cmap = color_map if color_map is not None else DEFAULT_COLOR_MAP
            lc = cmap.get(label, None)
            if lc is not None:
                return lc

    # Step 2: STEP AP242 color fallback
    if step_colors and s in step_colors:
        return step_colors[s]

    # Step 3: heuristic label + default map + default color
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
      - "iso":         front-right-above (default CAD-like)
      - "iso_left":    front-left-above
      - "iso_below":   front-right-BELOW — looks up into an open base
      - "iso_below_left": front-left-below
      - "hero":        front-right at near-eye-level, faint upward tilt.
                       Matches the M3-CRETE website hero render — the
                       full assembly silhouette reads cleanly with the
                       open base subtly visible.
      - "front":       looking along -Y (printer front face)
      - "back":        looking along +Y
      - "side":        looking along +X (right side)
      - "top":         looking down +Z
      - "bottom":      looking up +Z (camera below)
    """
    xmin, xmax, ymin, ymax, zmin, zmax = _scene_bounds(shapes)
    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2
    cz = (zmin + zmax) / 2

    # Direction unit vectors (from focal point toward camera).
    view = view.lower()
    directions = {
        "iso":              (1.0, -1.0, 0.7),
        "iso_left":         (-1.0, -1.0, 0.7),
        "iso_below":        (1.0, -1.0, -0.7),
        "iso_below_left":   (-1.0, -1.0, -0.7),
        "hero":             (1.2, -1.6, -0.05),  # M3-CRETE web hero: near eye-level
        "front":            (0.0, -1.0, 0.0),
        "back":             (0.0, 1.0, 0.0),
        "side":             (1.0, 0.0, 0.0),
        "top":              (0.0, 0.0, 1.0),
        "bottom":           (0.0, 0.0, -1.0),
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
                        tessellation_tol: float = 0.5,
                        use_step_colors: bool = True):
    """Render a STEP file to a PNG via offscreen VTK — CAD-standard Z-up,
    per-part coloring (black extrusions, green printed parts, metal
    plates), blue-grey gradient background, studio lighting, visible
    part edges. Approximates a shaded CAD viewport.

    Args:
        step_path: Input STEP file.
        output_path: Output PNG path.
        width, height: Image size in pixels.
        view: Camera preset. One of "iso" (default), "iso_left", "front",
            "back", "side", "top".
        azimuth, elevation: Fine-tuning rotations applied after the view
            preset, in degrees.
        background_top, background_bottom: RGB 0-1 gradient (top to bottom).
            Default is a CAD-like blue-grey.
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
    step_colors = _extract_step_colors(step_path) if use_step_colors else None

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
        color = _color_for(shape, labels, color_map, default_color,
                           step_colors=step_colors)
        prop.SetColor(*color)
        # Fully flat shading — colors render at their raw RGB value with no
        # lighting darkening. Depth cue comes from part-edge outlines and
        # the assembly silhouette, not from shading. Matches the CAD-
        # illustration aesthetic and preserves brand-color fidelity.
        prop.SetAmbient(1.0)
        prop.SetDiffuse(0.0)
        prop.SetSpecular(0.0)
        if edges:
            prop.EdgeVisibilityOn()
            prop.SetEdgeColor(*edge_color)
            prop.SetLineWidth(0.6)
        renderer.AddActor(actor)

    # Single headlight at full intensity. Combined with the per-actor
    # property (ambient = 1 - face_shading, diffuse = face_shading), the
    # brightest face of any part renders at exactly its assigned color
    # (1.0 contribution = ambient + diffuse * cos(0) * 1.0). Faces
    # turned away dim by `face_shading` in absolute terms — visible
    # surface cues without darkening the brand color on lit faces.
    head = vtk.vtkLight()
    head.SetLightTypeToHeadlight()
    head.SetIntensity(1.0)
    renderer.AddLight(head)

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

    # GIF encoding: optional downscale + ONE shared master palette across
    # all frames. Per-frame ADAPTIVE palettes used to drift slightly
    # between frames (the bright brand green pulsed pale → bright → pale)
    # because each frame's quantization ran independently. Building the
    # palette once from a mid-animation frame and reusing it for every
    # frame keeps colors stable.
    gw = gif_width or width
    gh = gif_height or height
    rgb_frames = []
    for p in png_paths:
        img = Image.open(p).convert("RGB")
        if (gw, gh) != img.size:
            img = img.resize((gw, gh), Image.LANCZOS)
        rgb_frames.append(img)
    frames = quantize_gif_frames(rgb_frames, gif_colors)
    duration_ms = max(1, int(1000 / max(fps, 1)))
    frames[0].save(output_gif, save_all=True, append_images=frames[1:],
                    duration=duration_ms, loop=0, optimize=optimize,
                    disposal=2)
    _warn_if_gif_too_large(output_gif)

    if not keep_pngs:
        for p in png_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    return len(frames)


_HOLE_DARK = (0.03, 0.03, 0.03)


def _is_perforated_plate(shape, min_holes=8, rmin=1.5, rmax=6.5):
    """True if a shape has >= min_holes small cylindrical bore faces (a gantry
    plate's mounting/wheel holes) - used to render hole interiors dark."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    found = 0
    for face in shape.Faces():
        try:
            surf = BRepAdaptor_Surface(face.wrapped, True)
            if surf.GetType() == GeomAbs_Cylinder and rmin <= surf.Cylinder().Radius() <= rmax:
                found += 1
                if found >= min_holes:
                    return True
        except Exception:
            continue
    return False


def _plate_body_and_holes(shape, rmin=1.5, rmax=6.5):
    """Split a perforated plate into (body_compound, bore_faces_compound)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from cadquery import Compound
    bores, body = [], []
    for face in shape.Faces():
        is_bore = False
        try:
            surf = BRepAdaptor_Surface(face.wrapped, True)
            if surf.GetType() == GeomAbs_Cylinder and rmin <= surf.Cylinder().Radius() <= rmax:
                is_bore = True
        except Exception:
            is_bore = False
        (bores if is_bore else body).append(face)
    return Compound.makeCompound(body), Compound.makeCompound(bores)


def _part_color_groups(shape, base_color, dark_holes=True):
    """Return [(sub_shape, color), ...]: one (shape, base_color) normally, or a
    body + dark-bore pair for perforated gantry plates so hole interiors render
    black. Falls back to the single shape if the split fails."""
    if dark_holes and _is_perforated_plate(shape):
        try:
            body, bores = _plate_body_and_holes(shape)
            return [(body, base_color), (bores, _HOLE_DARK)]
        except Exception:
            pass
    return [(shape, base_color)]


def render_radial_explode_gif(step_path: str, output_gif: str,
                                expansion: float = 0.5,
                                explode_frames: int = 24,
                                rotate_frames: int = 72,
                                hold_frames: int = 6,
                                fps: int = 24,
                                width: int = 960, height: int = 720,
                                view: str = "iso",
                                zoom: float = 0.95,
                                face_shading: float = 0.0,
                                labels: dict = None,
                                color_map: dict = None,
                                default_color: tuple = COLOR_PRINTED,
                                background_top: tuple = (0.62, 0.66, 0.70),
                                background_bottom: tuple = (0.38, 0.42, 0.47),
                                edges: bool = True,
                                edge_color: tuple = (0.05, 0.06, 0.06),
                                tessellation_tol: float = 0.5,
                                gif_width: int = None, gif_height: int = None,
                                gif_colors: int = 64,
                                optimize: bool = True,
                                keep_pngs: bool = False,
                                use_step_colors: bool = True,
                                separate_nested: bool = False,
                                nested_separation_mm: float = 45.0,
                                nested_lift_mm: float = 0.0,
                                nested_reveal_color: tuple = None,
                                nested_containment_tol_mm: float = 0.5,
                                reveal_bbox_signatures: list = None,
                                reveal_long_axes: list = None):
    """Build a 'cooler' exploded-view GIF in two phases:

      1. Every part moves outward from the assembly centroid simultaneously
         over `explode_frames` frames (expansion ramps 0 -> `expansion`).
      2. The fully-exploded assembly is held for `hold_frames`, then the
         camera sweeps 360 degrees around Z over `rotate_frames` frames
         for a panoramic reveal.

    This is much faster than `make_disassembly_gif` because the mesh is
    tessellated once up-front; only actor transforms and camera angles
    change per frame (no STEP file I/O, no per-frame re-tessellation).

    Args:
        step_path: Input assembly STEP.
        output_gif: Output GIF path.
        expansion: Peak outward expansion fraction. 0.5 means each part's
            distance from the centroid grows by 50%.
        explode_frames: Frames used for the outward expansion.
        rotate_frames: Frames used for the 360 camera orbit.
        hold_frames: Frames held fully-exploded before the spin starts.
        fps: GIF frames per second.
        width, height: Render resolution.
        view: Starting camera preset. Same values as render_step_to_png.
        labels, color_map, default_color: Per-part coloring, same as
            render_step_to_png.
        background_top/bottom, edges, edge_color, tessellation_tol: Styling.
        gif_width/height/colors, optimize: GIF encoding knobs.
        keep_pngs: If True, preserve the per-frame PNGs (written to a temp
            dir next to the GIF).
        separate_nested: If True, parts whose bounding boxes are contained
            inside larger parts are pulled out along +Y during the explode.
            This is intended for review artifacts where nested insert rails
            would otherwise remain hidden inside host extrusions.
        nested_separation_mm: Extra +Y reveal offset for nested parts.
        nested_lift_mm: Extra +Z reveal offset for nested parts.
        nested_reveal_color: Optional override color for nested parts in the
            review artifact.
        nested_containment_tol_mm: Bounding-box tolerance for nested detection.
        reveal_bbox_signatures: Optional list of sorted bbox length signatures
            such as (20, 40, 1000). Matching parts receive the same reveal
            offset as nested parts even when containment heuristics are
            ambiguous in an exploded assembly view.
        reveal_long_axes: Optional list of bbox long-axis indexes to limit
            reveal signatures to. Axis indexes are X=0, Y=1, Z=2.
    """
    import tempfile as _tmp
    import vtk

    shapes = _load_shapes(step_path)
    if not shapes:
        raise ValueError(f"No geometry found in {step_path}")
    step_colors = _extract_step_colors(step_path) if use_step_colors else None

    # Pre-tessellate every shape once, pair with its centroid offset vector.
    cmap = color_map if color_map is not None else DEFAULT_COLOR_MAP
    xmin, xmax, ymin, ymax, zmin, zmax = _scene_bounds(shapes)
    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2
    cz = (zmin + zmax) / 2

    def _shape_bbox(shape):
        bb = shape.BoundingBox()
        return (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)

    def _bbox_volume(bbox):
        return max(0.0, bbox[3] - bbox[0]) * max(0.0, bbox[4] - bbox[1]) * max(0.0, bbox[5] - bbox[2])

    def _bbox_contained(inner, outer, tol):
        return (
            inner[0] >= outer[0] - tol and inner[3] <= outer[3] + tol
            and inner[1] >= outer[1] - tol and inner[4] <= outer[4] + tol
            and inner[2] >= outer[2] - tol and inner[5] <= outer[5] + tol
        )

    def _bbox_lengths(bbox):
        return (bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2])

    def _bbox_signature(bbox):
        return tuple(round(length, 1) for length in sorted(_bbox_lengths(bbox)))

    def _normalise_signature(signature):
        return tuple(round(float(length), 1) for length in sorted(signature))

    def _long_axis(bbox):
        lengths = _bbox_lengths(bbox)
        return max(range(3), key=lambda axis: lengths[axis])

    def _cross_section_contained(inner, outer, long_axis, tol):
        axes = [axis for axis in range(3) if axis != long_axis]
        return all(
            inner[axis] >= outer[axis] - tol
            and inner[axis + 3] <= outer[axis + 3] + tol
            for axis in axes
        )

    def _interval_coverage(intervals, start, end, tol):
        if not intervals:
            return 0.0
        clipped = []
        for lo, hi in intervals:
            clipped_lo = max(start, lo)
            clipped_hi = min(end, hi)
            if clipped_hi > clipped_lo + tol:
                clipped.append((clipped_lo, clipped_hi))
        if not clipped:
            return 0.0
        clipped.sort()
        merged = [clipped[0]]
        for lo, hi in clipped[1:]:
            last_lo, last_hi = merged[-1]
            if lo <= last_hi + tol:
                merged[-1] = (last_lo, max(last_hi, hi))
            else:
                merged.append((lo, hi))
        return sum(hi - lo for lo, hi in merged)

    def _bbox_splice_nested(inner_index, volumes, tol):
        inner = shape_bboxes[inner_index]
        lengths = _bbox_lengths(inner)
        long_axis = _long_axis(inner)
        long_len = lengths[long_axis]
        cross_lengths = [lengths[axis] for axis in range(3) if axis != long_axis]
        if long_len < 400.0 or max(cross_lengths) > 50.0:
            return False
        intervals = []
        for outer_index, outer in enumerate(shape_bboxes):
            if inner_index == outer_index or volumes[inner_index] >= volumes[outer_index]:
                continue
            if _long_axis(outer) != long_axis:
                continue
            if not _cross_section_contained(inner, outer, long_axis, tol):
                continue
            intervals.append((outer[long_axis], outer[long_axis + 3]))
        covered = _interval_coverage(
            intervals,
            inner[long_axis],
            inner[long_axis + 3],
            tol,
        )
        return covered >= long_len - tol

    shape_bboxes = [_shape_bbox(shape) for shape in shapes]
    reveal_signatures = {
        _normalise_signature(signature)
        for signature in (reveal_bbox_signatures or [])
    }
    reveal_axis_set = set(reveal_long_axes or [])
    nested_offsets = [(0.0, 0.0, 0.0) for _ in shapes]
    nested_indexes = set()
    if separate_nested:
        volumes = [_bbox_volume(bbox) for bbox in shape_bboxes]
        for inner_index, inner_bbox in enumerate(shape_bboxes):
            nested = (
                _bbox_signature(inner_bbox) in reveal_signatures
                and (not reveal_axis_set or _long_axis(inner_bbox) in reveal_axis_set)
            )
            if not nested:
                nested = _bbox_splice_nested(inner_index, volumes, nested_containment_tol_mm)
            for outer_index, outer_bbox in enumerate(shape_bboxes):
                if inner_index == outer_index or volumes[inner_index] >= volumes[outer_index]:
                    continue
                if _bbox_contained(inner_bbox, outer_bbox, nested_containment_tol_mm):
                    nested = True
                    break
            if nested:
                nested_offsets[inner_index] = (0.0, nested_separation_mm, nested_lift_mm)
                nested_indexes.add(inner_index)

    part_entries = []  # list of (actor, radial_offset_vector, nested_offset_vector)
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(*background_bottom)
    renderer.SetBackground2(*background_top)
    renderer.GradientBackgroundOn()

    # Mostly-flat shading: face_shading (0..1) trades ambient for diffuse so
    # faces at different orientations read differently; specular always 0.
    _amb = max(0.0, min(1.0, 1.0 - face_shading))
    _dif = max(0.0, min(1.0, face_shading))
    for index, shape in enumerate(shapes):
        if nested_reveal_color is not None and index in nested_indexes:
            base_color = nested_reveal_color
        else:
            base_color = _color_for(shape, labels, color_map, default_color,
                                    step_colors=step_colors)
        bb = shape.BoundingBox()
        offset = ((bb.xmin + bb.xmax) / 2 - cx,
                  (bb.ymin + bb.ymax) / 2 - cy,
                  (bb.zmin + bb.zmax) / 2 - cz)
        # Perforated gantry plates split into a colored body + dark bore faces so
        # the hole interiors render black; everything else is one actor. Both
        # sub-actors share the part's explode offset so they move together.
        for sub_shape, sub_color in _part_color_groups(shape, base_color):
            poly = sub_shape.toVtkPolyData(tolerance=tessellation_tol,
                                           angularTolerance=0.3)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly)
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            prop = actor.GetProperty()
            prop.SetColor(*sub_color)
            prop.SetAmbient(_amb)
            prop.SetDiffuse(_dif)
            prop.SetSpecular(0.0)
            if edges:
                prop.EdgeVisibilityOn()
                prop.SetEdgeColor(*edge_color)
                prop.SetLineWidth(0.6)
            renderer.AddActor(actor)
            part_entries.append((actor, offset, nested_offsets[index]))

    # Single headlight at full intensity. Combined with the per-actor
    # property (ambient = 1 - face_shading, diffuse = face_shading), the
    # brightest face of any part renders at exactly its assigned color
    # (1.0 contribution = ambient + diffuse * cos(0) * 1.0). Faces
    # turned away dim by `face_shading` in absolute terms — visible
    # surface cues without darkening the brand color on lit faces.
    head = vtk.vtkLight()
    head.SetLightTypeToHeadlight()
    head.SetIntensity(1.0)
    renderer.AddLight(head)

    # Pre-compute the fully-exploded bounds so camera fits the expanded cloud.
    expanded_shapes = []
    for index, shape in enumerate(shapes):
        bb = shape.BoundingBox()
        pcx = (bb.xmin + bb.xmax) / 2
        pcy = (bb.ymin + bb.ymax) / 2
        pcz = (bb.zmin + bb.zmax) / 2
        nx, ny, nz = nested_offsets[index]
        ox = (pcx - cx) * expansion + nx
        oy = (pcy - cy) * expansion + ny
        oz = (pcz - cz) * expansion + nz
        class _FakeBB:
            def __init__(self, bb, ox, oy, oz):
                self.xmin = bb.xmin + ox; self.xmax = bb.xmax + ox
                self.ymin = bb.ymin + oy; self.ymax = bb.ymax + oy
                self.zmin = bb.zmin + oz; self.zmax = bb.zmax + oz
        class _FakeShape:
            def __init__(self, bb): self._bb = bb
            def BoundingBox(self): return self._bb
        expanded_shapes.append(_FakeShape(_FakeBB(bb, ox, oy, oz)))

    _aim_camera(renderer, expanded_shapes, view=view, zoom=zoom)

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetMultiSamples(8)
    window.SetSize(width, height)
    window.AddRenderer(renderer)

    tmp_dir = _tmp.mkdtemp(prefix="cadclaw_radial_")
    png_paths = []

    def _render_png(index):
        window.Render()
        to_image = vtk.vtkWindowToImageFilter()
        to_image.SetInput(window)
        to_image.ReadFrontBufferOff()
        to_image.Update()
        writer = vtk.vtkPNGWriter()
        path = os.path.join(tmp_dir, f"frame_{index:04d}.png")
        writer.SetFileName(path)
        writer.SetInputConnection(to_image.GetOutputPort())
        writer.Write()
        png_paths.append(path)

    def _set_expansion(t):
        for actor, (ox, oy, oz), (nx, ny, nz) in part_entries:
            actor.SetPosition((ox * expansion + nx) * t,
                              (oy * expansion + ny) * t,
                              (oz * expansion + nz) * t)

    # Phase 1: expansion 0 -> 1 (ease in/out with a cosine curve)
    import math as _m
    for i in range(explode_frames):
        frac = (i + 1) / explode_frames
        eased = 0.5 - 0.5 * _m.cos(_m.pi * frac)
        _set_expansion(eased)
        _render_png(len(png_paths))

    # Phase 2: hold at full explosion
    _set_expansion(1.0)
    for _ in range(hold_frames):
        _render_png(len(png_paths))

    # Phase 3: 360 camera sweep around Z through the centroid
    cam = renderer.GetActiveCamera()
    step_deg = 360.0 / max(rotate_frames, 1)
    for _ in range(rotate_frames):
        cam.Azimuth(step_deg)
        renderer.ResetCameraClippingRange()
        _render_png(len(png_paths))

    window.Finalize()

    # Assemble GIF — shared master palette across all frames so colors
    # don't drift between phases. See render_frames_to_gif for the
    # rationale. Master derived from the mid-animation frame which has
    # the richest mix of revealed colors after the explosion completes.
    gw = gif_width or width
    gh = gif_height or height
    rgb_frames = []
    for p in png_paths:
        img = Image.open(p).convert("RGB")
        if (gw, gh) != img.size:
            img = img.resize((gw, gh), Image.LANCZOS)
        rgb_frames.append(img)
    frames = quantize_gif_frames(rgb_frames, gif_colors)
    duration_ms = max(1, int(1000 / max(fps, 1)))
    frames[0].save(output_gif, save_all=True, append_images=frames[1:],
                    duration=duration_ms, loop=0, optimize=optimize,
                    disposal=2)
    _warn_if_gif_too_large(output_gif)

    if not keep_pngs:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return len(png_paths)


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
