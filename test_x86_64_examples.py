#!/usr/bin/env python3
"""Run every formal/examples/*.mojo through the x86-64 codegen and compare the
answer with the arm64 backend's.

The arm64 formal path is the reference: it is the mature one (proofs typecheck
against lib/ProofLib.lean for it), so agreement between the two is much
stronger evidence than either being self-consistent. Both are built from the
same fire_compiler AST and the same formal/types.py integer lattice, so any
disagreement is a codegen bug in one of them.

Each example's exit status is its entry function's return value (formal's
startup stub returns it to the process), so the comparison needs no expected
values written down here — the two backends provide them.

The x86-64 binaries are Mach-O and run under Rosetta 2 on Apple Silicon;
`--arch arm64` is native. Invocation:

    python3 test_x86_64_examples.py [-n INPUT] [-j N] [-v]
"""

import argparse
import concurrent.futures
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from exec_budget import child_exit_reason   # noqa: E402

EXAMPLES = os.path.join(HERE, "formal", "examples")
DEFAULT_INPUT = 10


def examples():
    return sorted(f for f in os.listdir(EXAMPLES) if f.endswith(".mojo"))


def build_and_run(path: str, arch: str, test_input: int, keep: str = None):
    """Build one example for `arch` and return (status, detail).

    status is the process exit code, or None when the example could not be
    built or run — with `detail` saying which."""
    import formal.build as B

    outdir = keep or tempfile.mkdtemp(prefix="formal-x86-")
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(outdir, f"{stem}.aout")
    try:
        B.compile_formal(path, output=out, test_input=test_input, prove=False,
                         arch=arch)
    except Exception as e:                    # noqa: BLE001 — reported, not raised
        return None, f"build failed: {type(e).__name__}: {e}"

    argv = [out]
    if arch == "x86_64" and sys.platform == "darwin":
        # Rosetta 2, exactly as a clang `-arch x86_64` binary needs.
        argv = ["arch", "-x86_64", out]
    r = subprocess.run(argv, capture_output=True, text=True)
    # The signal's NAME, not its number: `signal 11` does not say SIGSEGV, and a
    # `SIGKILL` is a fact about the machine rather than about the example, which
    # is the distinction this line used to throw away. `exec_budget`'s wording,
    # shared with the three suites that had their own copy.
    if r.returncode < 0:
        return None, child_exit_reason(r.returncode, r.stderr)
    if "Bad CPU type" in (r.stderr or ""):
        return None, "Bad CPU type in executable"
    return r.returncode, ""


def check_one(path: str, test_input: int, verbose: bool):
    stem = os.path.splitext(os.path.basename(path))[0]
    want, want_detail = build_and_run(path, "arm64", test_input)
    got, got_detail = build_and_run(path, "x86_64", test_input)
    if want is None:
        return stem, "SKIP", f"arm64 reference unavailable ({want_detail})"
    if got is None:
        return stem, "FAIL", f"x86_64 {got_detail}"
    if want != got:
        return stem, "FAIL", f"x86_64 returned {got}, arm64 returned {want}"
    return stem, "PASS", f"both {want}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=DEFAULT_INPUT,
                    help="entry function's argument (default 10)")
    ap.add_argument("-j", type=int, default=0,
                    help="parallel workers (default: min(cpu_count, 8))")
    ap.add_argument("-v", action="store_true", help="print every example")
    args = ap.parse_args()
    verbose = args.v
    files = [os.path.join(EXAMPLES, f) for f in examples()]
    workers = args.j or max(2, min(os.cpu_count() or 4, 8))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check_one, p, args.n, verbose): p
                   for p in files}
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
    results.sort()

    for stem, status, detail in results:
        if status != "PASS" or verbose:
            print(f"{status:4} {stem:14} {detail}")

    counts = {}
    for _stem, status, _detail in results:
        counts[status] = counts.get(status, 0) + 1
    print(" ".join(f"{k}={counts[k]}" for k in sorted(counts))
          + f" of {len(results)} examples (n={args.n})")
    return 1 if counts.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
