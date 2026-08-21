# CADCLAW MCP Server

Connect CADCLAW to an MCP-compatible assistant as a local Model Context Protocol tool server. It exposes CADCLAW assembly, check, analysis, audit, and render functions; it does not provide native-CAD application control.

## Security boundary

This server is **not a security sandbox**. It runs with the local process account's filesystem permissions. Path-taking tools can read specified inputs, the six `assemble_*` tools can write configured assembly and render outputs, and other export/render tools may also write files. Use a least-privilege working copy, restrict host approvals, keep sensitive projects out of scope, and review tool inputs and outputs. A successful check covers only the supplied artifact and configured rules; it is not engineering certification or physical validation.

## Setup

### Generic MCP host

Add to your MCP host configuration:

```json
{
  "mcpServers": {
    "cadclaw": {
      "command": "python",
      "args": ["-m", "cadclaw_mcp"],
      "cwd": "/path/to/CADCLAW"
    }
  }
}
```

## Available Tools

Once connected, the assistant can call these tools directly:

| Tool | What it does |
|------|-------------|
| `load_assembly` | Load a STEP file, label parts by bbox signature |
| `check_inventory` | Validate part counts against expected |
| `check_interference` | Find solid-solid overlaps (BRep boolean) |
| `check_adjacency` | Validate spatial relationships between parts |
| `check_dimensions` | Check part dimensions against ranges |
| `compute_deflection` | Beam deflection analysis |
| `compute_motor_budget` | Motor torque budget |
| `compute_belt_tension` | Belt tension safety check |
| `tolerance_stack` | Worst-case, RSS, and Monte Carlo tolerance stack analysis |
| `disassembly_sequence` | Ordered disassembly plan |
| `export_exploded_view` | Radial or axial exploded STEP export |
| `doctor` | Environment diagnostics |
| `check_bom_against_cad` | BOM JSON vs STEP audit using `cadclaw.yaml` |
| `check_publish_boundary` | Privacy / publish-boundary audit |
| `check_claims` | Public-claim audit |
| `check_region_inventory` | Inventory with region constraints from `cadclaw.yaml` |
| `compare_step_parity` | STEP-vs-STEP dim-signature comparison |
| `assemble_validate_spec` | Validate an assembly spec without authoring part geometry |
| `assemble_build` | Compile configured authored parts into assembly outputs |
| `assemble_check_round` | Build, run configured checks, and produce review artifacts |
| `assemble_inspect_component` | Inspect an authored component and its declared metadata |
| `assemble_render_views` | Render configured assembly review views to files and inline content |
| `assemble_render_sequence` | Export the configured build sequence and review frames |

## Illustrative conversation

```
User: "Load my assembly and check for interference"

Assistant: I'll load your STEP file and run an interference check.

[Calls load_assembly with path="assembly.step"]
[Calls check_interference with skip_labels=["belt", "wheel"]]

Found 3 interferences:
- Plate clips beam at (102, 18, 500) by 1,003 mm³
- Bracket overlaps motor at (2080, 45, 1040) by 450 mm³  
- Mount intersects post at (0, 16, 980) by 120 mm³

Would you like me to prepare these findings for engineering review?
```

The values above are fictional examples, not measured CADCLAW or M3-CRETE results.

## Requirements

- Python 3.10+; Python 3.11 is the current CADCLAW development runtime
- CadQuery 2.7+
- An MCP-compatible host
