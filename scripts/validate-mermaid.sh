#!/usr/bin/env bash
# Validate every mermaid block in the repo with mermaid-cli (mmdc).
# Usage: scripts/validate-mermaid.sh [path ...]
#   no args  → README.md + specs/*.md + skills/*/SKILL.md + system-prompt.md
#   args     → the given files
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MMDC="$(command -v mmdc || true)"
if [ -z "$MMDC" ]; then
  echo "mmdc not found. Install: npm install -g @mermaid-js/mermaid-cli" >&2
  exit 2
fi

files=("$@")
if [ ${#files[@]} -eq 0 ]; then
  # portable: build the file list without mapfile (not available on macOS bash 3.2)
  files=()
  while IFS= read -r f; do
    files+=("$f")
  done < <(cd "$ROOT" && printf '%s\n' README.md system-prompt.md specs/*.md skills/*/SKILL.md)
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
total=0
for f in "${files[@]}"; do
  # resolve: absolute paths pass through, relative resolve under ROOT
  case "$f" in
    /*) path="$f" ;;
    *)  path="$ROOT/$f" ;;
  esac
  [ -f "$path" ] || { echo "SKIP (missing): $f"; continue; }
  # clean per-file so stale blocks from a previous file are never re-validated
  rm -f "$TMP"/*.mmd "$TMP/out.svg" 2>/dev/null
  # extract mermaid blocks with python (regex, re.DOTALL) — awk can't do blocks
  "$ROOT/scripts/extract-mermaid.py" "$path" "$TMP" 2>/dev/null || {
    echo "FAIL (extract): $f"; fail=$((fail+1)); continue; }
  for mmd in "$TMP"/*.mmd; do
    [ -e "$mmd" ] || continue
    total=$((total+1))
    if "$MMDC" -i "$mmd" -o "$TMP/out.svg" --quiet 2>/dev/null; then
      echo "PASS: $f → $(basename "$mmd")"
      rm -f "$TMP/out.svg"
    else
      echo "FAIL: $f → $(basename "$mmd")"
      fail=$((fail+1))
    fi
  done
done

echo "----"
echo "$total blocks, $fail failed"
[ "$fail" -eq 0 ] && exit 0 || exit 1
