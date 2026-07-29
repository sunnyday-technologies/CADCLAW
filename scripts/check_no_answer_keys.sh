#!/bin/sh
# Fail if MARB answer-key material is present in this repository.
#
# CADCLAW is public and MIT-licensed. MARB (the benchmark CADCLAW grades) keeps
# its answer key in a gated Hugging Face dataset so it stays out of the open
# file tree that crawlers and training pipelines ingest. CADCLAW must never
# carry that key — not at HEAD, not transiently in a commit.
#
# This is the CADCLAW counterpart to MARB's scripts/check_no_answer_keys.sh and
# is the single source of truth for the blocked patterns here. Both the
# pre-push hook (scripts/hooks/pre-push) and CI (.github/workflows/key-guard.yml)
# call it.
#
# Two independent checks:
#
#   1. PATH  — no key-shaped file may be tracked or introduced. Covers the
#              gated MARB key filenames and the private working tree.
#   2. POSE  — examples/m3_crete/m3_reference_assembly.yaml is a deliberately
#              REDACTED spec. Its instance roster overlaps the gated key, so if
#              solved poses ever reappear in it, part of the answer is public
#              again. The part roster and counts are fine: M3-CRETE is open
#              hardware and those are published by design. The placement is not.
#
# Usage:
#   check_no_answer_keys.sh --tree                 scan all tracked paths + poses
#   check_no_answer_keys.sh --range <rev-args...>  scan every commit in the range
#   check_no_answer_keys.sh --stdin                scan newline-separated paths
#
# Exit codes: 0 clean, 1 key material detected, 64 usage error.

# Key-shaped paths. m3_reference_assembly.yaml is deliberately NOT matched here
# (the redacted example keeps that name); the POSE check governs its contents.
KEY_PATH_REGEX='(^|/)m3_reference_round1\.step$|(^|/)[^/]*reference[^/]*\.step$|(^|/)ph[0-9]+_reference|(^|/)_private/'

REDACTED_SPEC='examples/m3_crete/m3_reference_assembly.yaml'
POSE_REGEX='^[[:space:]]*(translate_mm|rotate_deg|source_origin_mm):'

fail=0

mode="${1:---tree}"
case "$mode" in
  --tree)
    paths=$(git ls-files) || exit 64
    ;;
  --range)
    shift
    [ "$#" -ge 1 ] || { echo "usage: $0 --range <rev-args...>" >&2; exit 64; }
    # --diff-merges=first-parent so an "evil merge" cannot smuggle a key in.
    paths=$(git log --pretty=format: --name-only --diff-merges=first-parent "$@" | sort -u) || exit 64
    ;;
  --stdin)
    paths=$(cat)
    ;;
  *)
    echo "usage: $0 [--tree | --range <rev-args...> | --stdin]" >&2
    exit 64
    ;;
esac

# --- check 1: key-shaped paths -------------------------------------------
hits=$(printf '%s\n' "$paths" | grep -Ei "$KEY_PATH_REGEX")
if [ -n "$hits" ]; then
  {
    echo ""
    echo "BLOCKED: answer-key path(s) detected:"
    printf '%s\n' "$hits" | sed 's/^/    /'
    echo ""
    echo "MARB answer keys live only in the gated HF dataset, and _private/"
    echo "never gets committed. Remove these from the commit(s) and retry."
    echo ""
  } >&2
  fail=1
fi

# --- check 2: solved poses in the redacted example -----------------------
# Only meaningful against the working tree / HEAD, so skip it in --stdin mode.
if [ "$mode" != "--stdin" ] && [ -f "$REDACTED_SPEC" ]; then
  posed=$(grep -nE "$POSE_REGEX" "$REDACTED_SPEC" | head -20)
  if [ -n "$posed" ]; then
    {
      echo ""
      echo "BLOCKED: solved poses found in $REDACTED_SPEC:"
      printf '%s\n' "$posed" | sed 's/^/    /'
      echo ""
      echo "That roster overlaps the gated MARB key, so publishing placement"
      echo "leaks part of the answer. Keep the roster, drop the transforms."
      echo ""
    } >&2
    fail=1
  fi
fi

exit $fail
