#!/usr/bin/env bash
# `fire.py build --formal <stem>` (which generates AND checks the Lean 4 proof
# by default) for a serial single-example run. Does NOT execute the built
# binary; use `make check-formal` for the whole suite.
#
# usage: tools/proof.sh <example-stem> [more-stems...]
# e.g.:  tools/proof.sh const2
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Resolve lean exactly as the Makefile and the python paths do (formal/lean.py):
# a bare `command -v lean` on an elan machine is a shim that resolves a
# toolchain from the *current directory*, so from anywhere but the repo root it
# silently uses - and can download - elan's default instead of the version
# pinned in ./lean-toolchain.
LEAN="$(cd "$ROOT" && python3 -c 'import formal.lean as l; print(l.find_lean(".") or "")')"
OUTDIR="${ROOT}/output"
SRC_DIR="${ROOT}/formal/examples"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <example-stem> [more-stems...]" >&2
  exit 2
fi
if [[ -z "$LEAN" || ! -x "$LEAN" ]]; then
  echo "missing lean (install the version pinned in ./lean-toolchain via elan)" >&2
  exit 1
fi

mkdir -p "$OUTDIR"

status=0
pass=0
fail=0
for stem in "$@"; do
  src="${SRC_DIR}/${stem}.mojo"
  if [[ ! -f "$src" ]]; then
    echo "missing source: $src" >&2
    status=1
    continue
  fi
  echo "== build --formal ${stem}"
  if python3 "${ROOT}/fire.py" build --formal -o "${OUTDIR}/${stem}.aout" "$src"; then
    echo "Proof generated and checked for ${stem}."
    pass=$((pass+1))
  else
    echo "FAIL build/proof ${stem}"
    status=1
    fail=$((fail+1))
  fi
done
echo "== summary: pass=${pass} fail=${fail}"
exit "$status"
