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
    # The two decrement-while shapes whose loop test is an ORDER on the counter
    # (`while n > 0`, `while n >= 1`), as opposed to `while n != 0`
    # (`wdiff`, which passes).  Both are sound CODEGEN now — a signed `int`
    # means a negative counter leaves the loop, which is what Python says —
    # and both are refused because the generated MODEL still assumes the
    # counter is a non-negative magnitude: `_gen_dec_while_block`'s
    # `pred_iff` states the loop's "keep going" test as the UNSIGNED
    # `0 < UInt64.ofNat m`, which is false for `m >= 2^63`, and the model
    # itself returns 0 where a negative counter must be returned unchanged.
    # So the obligation is genuinely unprovable, not merely unproved — which is
    # the honest shape for a known gap and why the fix is a model change, not a
    # tactic.  Same root cause as the two new holes `sum_range` reports (its
    # `loop_cond_flag` has the same unsigned `¬ (i < bound)` on the exit side).
    # See bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md.
    "countdown": "the decrement-while runF model treats the counter as a "
                 "non-negative magnitude; a signed `int` means `n <= 0` exits "
                 "immediately and returns n unchanged, which pred_iff and the "
                 "model both deny",
    "wge": "same as countdown, for the `n >= 1` spelling",

    # `a = [10,20,30]; i = 1; return a[i]` -- a subscript with a
    # RUNTIME-VARIABLE index.  The program builds, runs, and returns 20 on both
    # architectures, and the x86-64 generator proves it.  On arm64 what is now
    # proved is the per-instruction half: every `LDR`/`STR` through a non-SP
    # base gets a correct step RESULT lemma (before this wave the 0xF9400000
    # branch of the generator was a pre-index STORE OF ONE BYTE, so the emitted
    # lemma asserted the opposite of the architecture and no proof of a
    # memory-touching program could even be generated), and the block
    # certificates build.  What is left is the SOURCE half, and it is not a
    # dataflow question: the semantic model `mojo : UInt64 -> UInt64` has no
    # domain for a list, so `a[i]` has no value in it, and the list's storage
    # (a blob whose first word is its count) is never related to the source
    # literal.  The first term needs a list domain in the model and a memory
    # image for the blob; the second is a `Frame.frameToEnv`-shaped fact about
    # the blob.  `bugs/FORMAL_wide_receiver_by_reference.md` records both.
    "subscript_var": "runtime-indexed list subscript: the machine half is "
                     "proved (correct LDR/STR step lemmas, block "
                     "certificates), the source half is not -- the semantic "
                     "model has no list domain and the list blob's memory "
                     "image is not derived from the source literal",
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


# Filled by `run_one`: stem -> number of declarations that admitted a `sorry`.
# Reported by `main` as a census, because "how many holes are left" is a
# number this project has to be able to state honestly and has twice stated
# wrongly: counting the word `sorry` in the generated source counts tactic
# alternatives that were never taken (a losing `first | … | sorry` is still
# text), and reading it out of a `lean` run counts nothing at all when Lean
# serves a cached verdict.  `formal/lean.py::_run_lean` counts what Lean
# itself reports, so this is the real figure and it goes DOWN as holes close.
SORRY_CENSUS: dict = {}
# The other halves of the same census, which the generated file's own count
# cannot contain: holes in `lib/`, and declarations in it that are vacuously
# true.  `formal/lean.py::proof_census` already renders both as display lines,
# so they are carried through verbatim rather than re-derived here — the point
# of [5]'s request 5 was the opposite of a second implementation.  Keyed by
# stem; the rendering is deduplicated at print time because the library holes
# repeat identically for every proof that rests on them.
CENSUS_LINES: dict = {}


def _sorries_in(proof_path):
    """Declarations in `proof_path` that admitted a `sorry`, or None.

    Re-uses the build's own verdict rather than running Lean a second time:
    `check_proof_cached` stores the count beside the verdict, keyed on the
    proof's exact bytes, so this is a hash and a small read.
    """
    try:
        from formal.lean import check_proof_cached
        return check_proof_cached(proof_path, repo_root=HERE)[3]
    except Exception:
        return None


def _census_lines(proof_path):
    """The `lib/`-side and vacuity findings for one proof, as display lines.

    `proof_census(...).lines` is used directly. Two things that make reading
    the generated file the wrong answer, both measured here: Lean emits no
    warning for a hole in a module consumed from a pre-built `.olean`, and a
    vacuous declaration (`extern_x_step : True := by trivial`) contains no
    `sorry` to count. Scanning the 29 generated proofs for vacuity finds ZERO
    in every one — the vacuity is in `lib/`, so a generated-file scan cannot
    see it at all, and neither can the text check in test_formal_dylib.py.
    """
    try:
        from formal.lean import proof_census
        return list(proof_census(proof_path, repo_root=HERE).lines or [])
    except Exception:
        return []


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
        n = _sorries_in(proof)
        if n is not None:
            SORRY_CENSUS[stem] = n
        lines = _census_lines(proof)
        if lines:
            CENSUS_LINES[stem] = lines
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
    if SORRY_CENSUS:
        total = sum(SORRY_CENSUS.values())
        worst = sorted(SORRY_CENSUS.items(), key=lambda kv: (-kv[1], kv[0]))
        with_holes = [(s, n) for s, n in worst if n]
        print(f"proof census: {total} admitted `sorry` in the generated file, "
              f"in {len(with_holes)} of {len(SORRY_CENSUS)} proof(s) checked")
        for s, n in with_holes:
            print(f"  {s}: {n}")
        # The other two halves, which the line above cannot contain: a hole in
        # lib/ is invisible in the generated file's text (Lean emits no warning
        # for a module consumed from a pre-built .olean), and a vacuous
        # declaration emits no `sorry` at all, so it never appears in a count
        # of them.  Printed once each, deduplicated: the same library hole
        # underlies every proof that rests on it, and repeating it per proof
        # would bury the generated-file table above.
        seen = []
        for lines in CENSUS_LINES.values():
            for line in lines:
                # `.lines` renders the GENERATED half too, as a one-line
                # summary of the same number the table above already tabulated.
                # Keeping it would print each proof's sorry count twice, in two
                # formats, in the same summary.
                if line.lstrip().startswith("proof census:"):
                    continue
                if line not in seen:
                    seen.append(line)
        if seen:
            print("  the same verdicts also rest on holes OUTSIDE every "
                  "generated file:")
            for line in seen:
                print(line)

    if stale_expected:
        print("\nSTALE expected-failure entries (now passing — remove them):")
        for s in stale_expected:
            print(f"  {s}: {expected_failures[s]}")
    sys.exit(1 if (unexpected_failed or stale_expected) else 0)


if __name__ == "__main__":
    main()
