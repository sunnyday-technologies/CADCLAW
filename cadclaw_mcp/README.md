# CADCLAW MCP Server

Connect CADCLAW to Claude as an MCP (Model Context Protocol) tool server. This gives Claude direct access to CAD assembly validation — no code generation needed.

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

Once connected, Claude can call these tools directly:

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

- Python 3.10+
- CadQuery 2.7+
- Claude Code or Claude Desktop with MCP support
