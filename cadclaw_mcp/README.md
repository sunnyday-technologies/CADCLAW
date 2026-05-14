# CADCLAW MCP Server

Connect CADCLAW to an MCP-compatible assistant as a Model Context Protocol tool server. This gives the assistant direct access to CADCLAW's validation, analysis, and audit checks; it does not grant access to your CAD application.

## Setup

### Claude Code (CLI)

Add to your project's `.claude/settings.json`:

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

### Claude Desktop

Add to `claude_desktop_config.json`:

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

## Example Conversation

```
User: "Load my assembly and check for interference"

Claude: I'll load your STEP file and run an interference check.

[Calls load_assembly with path="assembly.step"]
[Calls check_interference with skip_labels=["belt", "wheel"]]

Found 3 interferences:
- Plate clips beam at (102, 18, 500) by 1,003 mm³
- Bracket overlaps motor at (2080, 45, 1040) by 450 mm³  
- Mount intersects post at (0, 16, 980) by 120 mm³

Would you like me to analyze the severity of each?
```

## Requirements

- Python 3.10+; Python 3.11 is the current CADCLAW development runtime
- CadQuery 2.7+
- An MCP-compatible host
