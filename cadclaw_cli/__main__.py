"""Allow `python -m cadclaw_cli` as an alternative to the `cadclaw` script."""
from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
