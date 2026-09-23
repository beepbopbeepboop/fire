#!/usr/bin/env bash
# formalbuild --prove <stem>, then typecheck the generated Lean 4 proof
# statically with pixi's lean. Does NOT execute the generated binary.
#
# usage: tools/proof.sh <example-stem> [more-stems...]
# e.g.:  tools/proof.sh const2
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LEAN="${ROOT}/.pixi/envs/default/bin/lean"
OUTDIR="${ROOT}/output"
SRC_DIR="${ROOT}/formal/examples"
LIB="${ROOT}/lib"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <example-stem> [more-stems...]" >&2
  exit 2
fi
if [[ ! -x "$LEAN" ]]; then
  echo "missing lean at $LEAN (run: pixi install)" >&2
  exit 1
fi
if [[ ! -f "${LIB}/ProofLib.olean" ]]; then
  echo "missing ${LIB}/ProofLib.olean (run: pixi run prooflib)" >&2
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
  echo "== formalbuild --prove ${stem}"
  if ! python3 "${ROOT}/fire.py" formalbuild --prove -o "${OUTDIR}/${stem}.aout" "$src"; then
    echo "FAIL build ${stem}"
    status=1
    fail=$((fail+1))
    continue
  fi
  echo "== lean typecheck ${stem}_proof.lean"
  if (cd "$OUTDIR" && LEAN_PATH=".:${LIB}" "$LEAN" "${stem}_proof.lean"); then
    echo "Proof type-checked for ${stem}."
    pass=$((pass+1))
  else
    echo "FAIL proof ${stem}"
    status=1
    fail=$((fail+1))
  fi
done
echo "== summary: pass=${pass} fail=${fail}"
exit "$status"
