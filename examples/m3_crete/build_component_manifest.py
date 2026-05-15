"""Build an M3-CRETE component manifest from authored STEP assets.

Default scope is `CAD/Advanced` because it contains the pre-assembled
actuator assemblies that are useful for an early configurator slice.
Pass `--include-components` when the lower-level `CAD/Components`
library is needed for part-by-part placement or parity checks.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cadclaw.component_manifest import (  # noqa: E402
    StepInspection,
    build_component_manifest,
    write_manifest,
)


DEFAULT_CAD_ROOT = ROOT.parent / "M3-CRETE" / "CAD"
DEFAULT_OUTPUT = ROOT / "examples" / "m3_crete" / "m3_component_manifest.yaml"


def _metadata_only_inspect(_path: Path) -> StepInspection:
    return StepInspection(status="not_inspected", part_count=0, signatures=[])


def _parse_libraries(args: argparse.Namespace) -> list[str]:
    libraries = [lib.strip() for lib in args.libraries.split(",") if lib.strip()]
    if args.include_components and "Components" not in libraries:
        libraries.append("Components")
    return libraries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an observational M3-CRETE STEP component manifest."
    )
    parser.add_argument(
        "--cad-root",
        default=str(DEFAULT_CAD_ROOT),
        help="Path to M3-CRETE/CAD. Default: %(default)s",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Manifest YAML output path. Default: %(default)s",
    )
    parser.add_argument(
        "--libraries",
        default="Advanced",
        help="Comma-separated CAD library names under --cad-root. Default: %(default)s",
    )
    parser.add_argument(
        "--include-components",
        action="store_true",
        help="Also scan CAD/Components for lower-level parts.",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="List STEP assets without opening each STEP file for bbox signatures.",
    )
    args = parser.parse_args(argv)

    cad_root = Path(args.cad_root)
    if not cad_root.exists():
        print(f"error: CAD root not found: {cad_root}", file=sys.stderr)
        return 3

    libraries = _parse_libraries(args)
    inspect_step = _metadata_only_inspect if args.metadata_only else None
    manifest = build_component_manifest(
        cad_root,
        libraries=libraries,
        **({"inspect_step": inspect_step} if inspect_step else {}),
    )
    write_manifest(manifest, args.output)

    count = len(manifest["components"])
    macro_count = sum(1 for c in manifest["components"] if c["kind"] == "macro_assembly")
    print(f"wrote {args.output}")
    print(f"components: {count}; macro assemblies: {macro_count}; libraries: {', '.join(libraries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
