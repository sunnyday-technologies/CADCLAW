"""Visualization helpers for lightweight CADCLAW frame FEA results.

The plots produced here are beam-member envelopes, not solid-element
contours. Each member is colored by the peak bending stress or strain
reported by the frame solver. This is appropriate for early frame
rigidity and member-sizing decisions; local spacer, fastener, and plate
stresses still require authored detail models or later solid FEA.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Tuple

from .frame_model import FrameModel
from .solver import SolverResult


MemberDemand = Dict[str, float]


def member_demand_envelopes(
    frame: FrameModel,
    result: SolverResult,
) -> Dict[str, MemberDemand]:
    """Return peak bending stress/strain demand per frame member."""
    demands: Dict[str, MemberDemand] = {}
    for member_id, member in frame.members.items():
        member_result = result.member_results.get(member_id)
        if member_result is None:
            continue
        stress_z = (
            member_result.peak_moment_z_Nm / member.section.Sz
            if member.section.Sz else 0.0
        )
        stress_y = (
            member_result.peak_moment_y_Nm / member.section.Sy
            if member.section.Sy else 0.0
        )
        peak_stress = max(abs(stress_z), abs(stress_y))
        demands[member_id] = {
            "peak_moment_Nm": member_result.peak_moment_Nm,
            "peak_stress_Pa": peak_stress,
            "peak_stress_MPa": peak_stress / 1e6,
            "peak_strain": peak_stress / member.material.E,
            "peak_strain_microstrain": peak_stress / member.material.E * 1e6,
            "peak_deflection_mm": member_result.peak_deflection_mm,
        }
    return demands


def write_member_demand_csv(
    frame: FrameModel,
    result: SolverResult,
    path: str | Path,
) -> Path:
    """Write per-member stress/strain demand envelopes to CSV."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    demands = member_demand_envelopes(frame, result)
    fields = [
        "member_id",
        "i_node",
        "j_node",
        "length_m",
        "peak_moment_Nm",
        "peak_stress_MPa",
        "peak_strain_microstrain",
        "peak_deflection_mm",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for member_id in sorted(demands):
            member = frame.members[member_id]
            row = demands[member_id]
            writer.writerow({
                "member_id": member_id,
                "i_node": member.i_node,
                "j_node": member.j_node,
                "length_m": round(frame.member_length(member_id), 6),
                "peak_moment_Nm": round(row["peak_moment_Nm"], 6),
                "peak_stress_MPa": round(row["peak_stress_MPa"], 6),
                "peak_strain_microstrain": round(
                    row["peak_strain_microstrain"], 6),
                "peak_deflection_mm": round(row["peak_deflection_mm"], 6),
            })
    return output


def render_member_maps(
    frame: FrameModel,
    result: SolverResult,
    output_dir: str | Path,
    *,
    title_prefix: str = "Frame FEA",
) -> Tuple[Path, Path]:
    """Render stress and strain envelope maps for a solved frame.

    Returns ``(stress_png, strain_png)``. Matplotlib is imported lazily so
    the core FEA gate can remain usable in minimal environments.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import cm, colors

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    demands = member_demand_envelopes(frame, result)
    if not demands:
        raise ValueError("solver result has no member demands to plot")

    stress_values = {
        member_id: row["peak_stress_MPa"]
        for member_id, row in demands.items()
    }
    strain_values = {
        member_id: row["peak_strain_microstrain"]
        for member_id, row in demands.items()
    }

    stress_path = output / f"{frame.name}_stress_distribution.png"
    strain_path = output / f"{frame.name}_strain_map.png"
    _render_map(
        frame,
        stress_values,
        stress_path,
        title=f"{title_prefix} - member peak bending stress",
        units="MPa",
        cmap=cm.inferno,
    )
    _render_map(
        frame,
        strain_values,
        strain_path,
        title=f"{title_prefix} - member peak elastic strain",
        units="microstrain",
        cmap=cm.viridis,
    )
    return stress_path, strain_path


def _render_map(
    frame: FrameModel,
    values: Dict[str, float],
    output_path: Path,
    *,
    title: str,
    units: str,
    cmap,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib import colors

    fig = plt.figure(figsize=(12, 7), dpi=160)
    ax = fig.add_subplot(111, projection="3d")

    maximum = max(values.values()) if values else 0.0
    norm = colors.Normalize(vmin=0.0, vmax=maximum or 1.0)

    xs = [node.x for node in frame.nodes.values()]
    ys = [node.z for node in frame.nodes.values()]
    zs = [node.y for node in frame.nodes.values()]
    x_span = max(xs) - min(xs)
    y_span = max(ys) - min(ys)
    z_span = max(zs) - min(zs)
    max_span = max(x_span, y_span, z_span, 1.0)
    x_mid = (max(xs) + min(xs)) / 2.0
    y_mid = (max(ys) + min(ys)) / 2.0
    z_mid = (max(zs) + min(zs)) / 2.0

    for member_id, member in frame.members.items():
        a = frame.nodes[member.i_node]
        b = frame.nodes[member.j_node]
        value = values.get(member_id, 0.0)
        ax.plot(
            [a.x, b.x],
            [a.z, b.z],
            [a.y, b.y],
            color=cmap(norm(value)),
            linewidth=5.0,
            solid_capstyle="round",
        )

    node_x = [node.x for node in frame.nodes.values()]
    node_y = [node.z for node in frame.nodes.values()]
    node_z = [node.y for node in frame.nodes.values()]
    ax.scatter(node_x, node_y, node_z, s=12, c="#111827", depthshade=False)

    if "printhead" in frame.nodes:
        p = frame.nodes["printhead"]
        ax.scatter([p.x], [p.z], [p.y], s=70, c="#d7191c",
                   marker="v", depthshade=False)
        ax.text(p.x, p.z, p.y + 0.05, "49 N center load", color="#111827")

    ax.set_title(title)
    ax.set_xlabel("X span (m)")
    ax.set_ylabel("Y depth (m)")
    ax.set_zlabel("Z height (m)")
    ax.set_xlim(x_mid - max_span / 2.0, x_mid + max_span / 2.0)
    ax.set_ylim(y_mid - max_span / 2.0, y_mid + max_span / 2.0)
    ax.set_zlim(z_mid - max_span / 2.0, z_mid + max_span / 2.0)
    ax.view_init(elev=22, azim=-58)
    ax.grid(True, linewidth=0.2)

    scalar = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    scalar.set_array([])
    cbar = fig.colorbar(scalar, ax=ax, shrink=0.62, pad=0.08)
    cbar.set_label(units)

    fig.text(
        0.02,
        0.02,
        "Light FEA: PyNite linear beam-frame envelope. "
        "Not a solid-element stress contour or physical validation.",
        fontsize=8,
        color="#374151",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(output_path, facecolor="white")
    plt.close(fig)
