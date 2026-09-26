#!/usr/bin/env python3
"""Run every formal/ example through `fire.py build --formal` + Lean 4
typecheck, in parallel (default: min(cpu_count, 20) workers).

Each example is independent: fire.py build --formal writes
output/<stem>.aout + output/<stem>_proof.lean, then pixi's lean typechecks
the proof statically (no binary execution — see tools/proof.sh for the
serial single-stem path; this is the suite runner).

Invoked via `make check-formal` or directly:
    python3 test_formal.py [-j N]

`--backend` picks the architecture; it defaults to arm64, and `--backend x86_64`
runs the same examples through the x86-64 backend and its proof generator. The
two share the examples and this runner but nothing else: the arm64 proof
generator emits a per-instruction value-flow argument, the x86-64 one emits
machine-checked run tests over the x86-64 model in lib/X86.lean, so their
KNOWN-GAP lists are separate and a gap in one says nothing about the other.
"""
import argparse
import concurrent.futures
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, "formal", "examples")
OUTDIR = os.path.join(HERE, "output")
LEAN = None
PROOFLIB = os.path.join(HERE, "lib", "ProofLib.olean")
FIRE = os.path.join(HERE, "fire.py")
LIB = os.path.join(HERE, "lib")

DEFAULT_JOBS = max(4, min(os.cpu_count() or 8, 20))
# Per-example budget for `fire.py build --formal`, which typechecks a
# ~700KB `native_decide` proof as part of the build. That check is tens of
# seconds of wall time *and more system time than user time* on an idle
# machine, so with DEFAULT_JOBS workers on the same box it is several times
# that under load. The old 120s was only ~3x one example's idle cost, so a
# merely busy machine reported dozens of examples as "timed out" — and, before
# run_group() below killed the whole process group, each such timeout left a
# 100%-CPU orphan lean behind that made the next run worse than the last.
BUILD_TIMEOUT = 900
LEAN_TIMEOUT = 600

# Examples whose proof is a genuine, documented gap rather than a regression.
#
# An entry here means "known unproven, for the stated reason" — NOT "passing".
# The proof is still expected to FAIL; the entry only stops it counting against
# the suite, so a real regression stands out against the noise. Nothing here is
# ever stubbed with `sorry` to go green: a `sorry` makes Lean accept the
# theorem, which would assert exactly the semantics these examples exist to
# check. If a stem here starts passing, it is reported as a STALE entry and
# the entry must be removed (see the stale check in main), so the list cannot
# quietly drift from reality.
EXPECTED_FAILURES = {
    # `if n > 10 or n == 0:` — a short-circuit `and`/`or` lowers to a CBZ/CBNZ
    # of its own, which closes a basic block exactly like the `if`'s own
    # branch.  The merge block therefore has TWO entry paths carrying
    # DIFFERENT values in the condition register (the left operand on the
    # short-circuit path, the right operand's CSET on the fallthrough), so a
    # single `arm64_reg 0 <state> = 0` statement cannot describe it — the
    # entry condition has to be stated per path, which the generator's per-block
    # `def` chain cannot yet express.  The CFG metadata that identifies the
    # real `if` branch is in place (`info["cond_branches"]` in
    # formal/arm64_codegen.py, consumed by _gen_universal_e2e_cfg); what is
    # missing is the path-split statement.
    "either": "short-circuit `or` condition: entry condition needs a per-path "
              "statement (merge block has two entries with different values in "
              "the condition register)",

    # Same shape as `either`, with `and`: `if n > 0 and n < 10:`.
    "both": "short-circuit `and` condition: entry condition needs a per-path "
            "statement (merge block has two entries with different values in "
            "the condition register)",

    # `fib(n) = fib(n-1) + fib(n-2)` — tree recursion, one goal left.  The
    # caller's FrameOk window read sits over the callee's store stack, whose
    # addresses the frame canonicalisation's `u64_sub_add` splits into
    # `sp - (K - 8)`.  `mem_read_write_below` peels a single store at
    # `sp - UInt64.ofNat K`, so the split has to be folded back first, and the
    # nesting depth is data-dependent.  Per-depth collapse lemmas were tried
    # and each exposed the next form; the right fix is to teach
    # `mem_read_write_below` the split form so nothing needs collapsing.
    "fib": "tree-recursion FrameOk window read over a store stack whose "
           "addresses u64_sub_add splits into sp - (K - 8); the peel needs a "
           "collapse at data-dependent nesting depth",
}


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
    from formal.lean import find_lean
    lean = find_lean(HERE)
    if not lean:
        raise SystemExit("ERROR: missing lean (run: pixi install, or install lean via elan)")
    global LEAN
    LEAN = lean
    if not os.path.isfile(PROOFLIB):
        from formal.lean import ensure_library
        try:
            ensure_library(lean, os.path.join(HERE, "lib"))
        except Exception as e:
            raise SystemExit(f"ERROR: proof library build failed: {e}")


def run_group(argv, timeout, cwd=None):
    """subprocess.run, but a timeout kills the whole process group.

    `fire.py build --formal` shells out to `lean`, so a plain
    subprocess.run(timeout=...) kill()s only fire.py and leaves the lean it
    spawned running at 100% CPU with PPID 1. Those orphans are not visible to
    the suite, they are never reaped, and they take the CPU away from the
    examples still running — so one example that runs long turns a single
    timeout into a cascade of bogus timeouts behind it, and the suite gets
    slower the more it retries. Killing the process group is the only way to
    get that CPU back.
    """
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=cwd,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.communicate()
        raise
    return proc.returncode, out, err


def run_one(stem, backend="arm64", outdir=None):
    """build --formal (which generates and checks the proof), or fail."""
    outdir = outdir or OUTDIR
    os.makedirs(outdir, exist_ok=True)
    src = os.path.join(EXAMPLES, f"{stem}.mojo")
    aout = os.path.join(outdir, f"{stem}.aout")
    proof = os.path.join(outdir, f"{stem}_proof.lean")

    try:
        code, sout, serr = run_group(
            [sys.executable, FIRE, "build", "--formal", "-o", aout,
             f"--backend={backend}", src],
            BUILD_TIMEOUT, cwd=HERE,
        )
        if code != 0:
            err = (serr or sout or "").strip()
            return False, f"build/proof failed: {err[-300:]}"
        if not os.path.isfile(proof):
            return False, "build ok but proof file missing"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


EXPECTED_FAILURES_X86_64 = {}
"""x86-64 gaps, kept separate from arm64's because the two generators prove
different things (see the module docstring).  Empty today: every example's
x86-64 proof builds and typechecks, and the run tests in them are real
`native_decide` evaluations of the model in lib/X86.lean, not `sorry`.  An
entry here would mean "known unproven, for the stated reason" — and, as with
the arm64 table, a stem that starts passing is reported as stale."""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-j", "--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"parallel workers (default {DEFAULT_JOBS})")
    ap.add_argument("--backend", default="arm64",
                    choices=("arm64", "x86_64"),
                    help="architecture to build and prove (default: arm64)")
    ap.add_argument("stems", nargs="*",
                    help="subset of example stems (default: all)")
    args = ap.parse_args()

    check_prereqs()
    backend = args.backend
    if backend == "arm64":
        # Cheap, Lean-free, and it must run before anything else: the step
        # table and ProofLib's if-chain have to agree, or `_step_facts` leaves
        # the wrong entry unconstrained and the proofs stop meaning anything.
        # The orders deliberately do NOT match globally (B.cond is model
        # position 18, table index 51), so this checks per-pair overlap
        # ordering rather than assuming a shared sequence.
        from formal.arm64_proof_gen import audit_step_table
        notes = audit_step_table(os.path.join(HERE, "lib", "ProofLib.lean"))
        print(f"step table: {len(notes)} overlapping entr"
              f"{'y' if len(notes) == 1 else 'ies'} ("
              + ", ".join(notes) + ")")
    expected_failures = (EXPECTED_FAILURES if backend == "arm64"
                         else EXPECTED_FAILURES_X86_64)
    outdir = OUTDIR if backend == "arm64" else os.path.join(HERE, "output", backend)
    stems = args.stems or find_examples()
    os.makedirs(outdir, exist_ok=True)

    jobs = max(1, args.jobs)
    total = len(stems)
    print(f"Found {total} formal examples in {EXAMPLES}")
    print(f"Running {backend} build+lean typecheck ({jobs} workers)...")

    results = [None] * total
    ok = fail = completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        fut_map = {
            ex.submit(run_one, stem, backend, outdir): i
            for i, stem in enumerate(stems)
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

    # Split failures into expected (documented above) and unexpected: only an
    # unexpected failure is a regression. An entry in EXPECTED_FAILURES that
    # unexpectedly PASSES is a stale entry and is reported as such rather than
    # silently ignored, so the list cannot drift from reality.
    expected_failed = [s for s, (passed, _) in zip(stems, results)
                       if not passed and s in expected_failures]
    unexpected_failed = [s for s, (passed, _) in zip(stems, results)
                         if not passed and s not in expected_failures]
    stale_expected = sorted(s for s, (passed, _) in zip(stems, results)
                            if passed and s in expected_failures)

    for i, (stem, (passed, detail)) in enumerate(zip(stems, results)):
        if passed:
            tag = "PASS"
        elif stem in expected_failures:
            tag = "KNOWN-GAP"
        else:
            tag = "FAIL"
        suffix = "" if passed or not detail else f"  ({detail})"
        print(f"  [{i+1}/{total}] {tag}  {stem}{suffix}")

    print(f"\nResults for {backend} formal proofs: PASS={ok} "
          f"KNOWN-GAP={len(expected_failed)} FAIL={len(unexpected_failed)}")
    if stale_expected:
        print("\nSTALE expected-failure entries (now passing — remove them):")
        for s in stale_expected:
            print(f"  {s}: {expected_failures[s]}")
    sys.exit(1 if (unexpected_failed or stale_expected) else 0)


if __name__ == "__main__":
    main()
