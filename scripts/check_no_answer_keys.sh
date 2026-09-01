#!/bin/sh
# Compatibility entry point for the MARB-specific answer-key guard.
# The generic pre-publication scanner runs first in scripts/hooks/pre-push.

python_path=$(git config --local --get prepublication.python 2>/dev/null || true)
if [ -n "$python_path" ] && [ -f "$python_path" ]; then
  exec "$python_path" scripts/check_no_answer_keys.py "$@"
fi
if command -v python3 >/dev/null 2>&1; then
  exec python3 scripts/check_no_answer_keys.py "$@"
fi
if command -v python >/dev/null 2>&1; then
  exec python scripts/check_no_answer_keys.py "$@"
fi

echo "answer-key-guard: status=error surface=runtime pattern=SYSTEM-PYTHON-MISSING ordinal=1" >&2
exit 64
