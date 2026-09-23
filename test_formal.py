#!/usr/bin/env python3
"""Run every formal/ example through formalbuild --prove + Lean 4 typecheck,
in parallel (default: min(cpu_count, 20) workers).

Each example is independent: fire.py formalbuild --prove writes
output/<stem>.aout + output/<stem>_proof.lean, then pixi's lean typechecks
the proof statically (no binary execution — see tools/proof.sh for the
serial single-stem path; this is the suite runner).

Invoked via `make check-formal` or directly:
    python3 test_formal.py [-j N]
"""
import argparse
import concurrent.futures
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, "formal", "examples")
OUTDIR = os.path.join(HERE, "output")
LEAN = os.path.join(HERE, ".pixi", "envs", "default", "bin", "lean")
PROOFLIB = os.path.join(HERE, "lib", "ProofLib.olean")
FIRE = os.path.join(HERE, "fire.py")
LIB = os.path.join(HERE, "lib")

DEFAULT_JOBS = max(4, min(os.cpu_count() or 8, 20))
BUILD_TIMEOUT = 120
LEAN_TIMEOUT = 600


def find_examples():
    if not os.path.isdir(EXAMPLES):
        raise SystemExit(f"ERROR: examples dir not found: {EXAMPLES}")
    stems = sorted(
        f[:-5]
        for f in os.listdir(EXAMPLES)
        if f.endswith(".mojo")
    )
    if not stems:
        raise SystemExit(f"ERROR: no .mojo examples in {EXAMPLES}")
    return stems


def check_prereqs():
    if not os.access(LEAN, os.X_OK):
        raise SystemExit(
            f"ERROR: missing lean at {LEAN} (run: pixi install)"
        )
    if not os.path.isfile(PROOFLIB):
        raise SystemExit(
            f"ERROR: missing {PROOFLIB} (run: pixi run prooflib)"
        )


def run_one(stem):
    """formalbuild --prove, then typecheck. Returns (ok, detail)."""
    src = os.path.join(EXAMPLES, f"{stem}.mojo")
    aout = os.path.join(OUTDIR, f"{stem}.aout")
    proof = os.path.join(OUTDIR, f"{stem}_proof.lean")

    try:
        b = subprocess.run(
            [sys.executable, FIRE, "formalbuild", "--prove",
             "-o", aout, src],
            capture_output=True, text=True, timeout=BUILD_TIMEOUT,
            cwd=HERE,
        )
        if b.returncode != 0:
            err = (b.stderr or b.stdout or "").strip()
            return False, f"build failed: {err[-300:]}"
        if not os.path.isfile(proof):
            return False, "build ok but proof file missing"

        env = os.environ.copy()
        env["LEAN_PATH"] = f".:{LIB}"
        t = subprocess.run(
            [LEAN, f"{stem}_proof.lean"],
            capture_output=True, text=True, timeout=LEAN_TIMEOUT,
            cwd=OUTDIR, env=env,
        )
        if t.returncode != 0:
            out = (t.stderr or "") + (t.stdout or "")
            # first error line is the useful one; keep a short tail too
            errs = [ln for ln in out.splitlines() if "error:" in ln]
            head = errs[0] if errs else out.strip().splitlines()[-1:]
            head = head[0] if isinstance(head, list) else (head or "lean failed")
            return False, f"lean: {head[:300]}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-j", "--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"parallel workers (default {DEFAULT_JOBS})")
    ap.add_argument("stems", nargs="*",
                    help="subset of example stems (default: all)")
    args = ap.parse_args()

    check_prereqs()
    stems = args.stems or find_examples()
    os.makedirs(OUTDIR, exist_ok=True)

    jobs = max(1, args.jobs)
    total = len(stems)
    print(f"Found {total} formal examples in {EXAMPLES}")
    print(f"Running build+lean typecheck ({jobs} workers)...")

    results = [None] * total
    ok = fail = completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        fut_map = {
            ex.submit(run_one, stem): i for i, stem in enumerate(stems)
        }
        for fut in concurrent.futures.as_completed(fut_map):
            i = fut_map[fut]
            passed, detail = fut.result()
            results[i] = (passed, detail)
            completed += 1
            if passed:
                ok += 1
            else:
                fail += 1
            if completed % 10 == 0 or completed == total:
                print(f"  [{completed}/{total}] checkpoint: P={ok} F={fail}",
                      flush=True)

    for i, (stem, (passed, detail)) in enumerate(zip(stems, results)):
        tag = "PASS" if passed else "FAIL"
        suffix = "" if passed or not detail else f"  ({detail})"
        print(f"  [{i+1}/{total}] {tag}  {stem}{suffix}")

    print(f"\nResults for formal proofs: PASS={ok} FAIL={fail}")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
