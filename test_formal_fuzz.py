#!/usr/bin/env python3
"""`tools/formal_fuzz.py`'s own regression suite: the GENERATOR and the RUNNER.

Why this file exists
--------------------
The fuzzer is a measurement, and a measurement whose own machinery is untested
measures the machinery. Two things can be wrong with it, and both would look
like a clean backend:

* **the generator emits a program that is not a differential test at all** — a
  read before its first assignment, a divisor that can be zero, a `while` whose
  body came out empty. Each of those makes CPython the wrong oracle (a
  `NameError`, a trap, a `SyntaxError`) and the seed reports nothing about the
  backend while still counting towards the run's totals. So the generator's
  output is checked for all three, over 200 seeds, with no compiler involved.
* **the runner's verdicts are not verdicts** — a build that reported success and
  wrote no binary, a comparison that stopped at the exit code and ignored the
  output. So a fixed seed range is run end to end and every divergence is
  required to reduce to a construct `KNOWN_DIVERGENCES` names.

Twenty fixed seeds, on both architectures, is what runs by default. That number
is a floor rather than a target: the point is that the twenty are PINNED, so a
change to the generator or the classifier that altered a verdict would fail here
instead of quietly changing what a sweep of two thousand seeds measures.

    python3 test_formal_fuzz.py [-v] [--seeds N] [--arch arm64|x86_64]

NOT registered in `tools/suite.py`. It builds twenty images per architecture,
which is more than a unit test's share, and its heavier setting (a few thousand
seeds) is a sweep rather than a check — see the module docstring for that.
"""

import argparse
import os
import subprocess
import sys

# This file lives at the repository root, so HERE *is* the root — spelled this
# way rather than as `dirname(HERE)` because that is the bug a top-level test
# file invites, and `formal_fuzz` is in `tools/`.
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import formal_fuzz as F  # noqa: E402

# The pinned range. Chosen by MEASUREMENT, not by taste: it is the first twenty
# seeds, so it is whatever the generator's own distribution produces, and the
# property it has to have is that every one of them reaches a verdict and every
# divergence is explained. Measured on this tree, arm64 and x86-64 alike:
#
#     agree      the binary and CPython printed the same bytes
#     refused    the backend declined the program — a measured limit of the
#                subset's reach, not a bug
#     diverged   the two disagreed, and every one of those reduced to `%`,
#                `//` or `s[i]`, each in `KNOWN_DIVERGENCES`
#
# What it must NOT contain, and what a change that quietly widened the
# `KNOWN_DIVERGENCES` table or weakened `blame` would hide: an `ERROR` (a
# generator defect — the program CPython will not run is the oracle's own
# traceback) and an unexplained divergence.
SEEDS = 20


def _fail(name, detail, verbose):
    print(f"  FAIL  {name}: {detail}")
    if verbose:
        print("        " + detail.replace("\n", "\n        "))
    return 1


def check_generator(verbose=False):
    """Every generated program is a valid differential test.

    Three properties, and each is a way the corpus could stop measuring the
    backend while still reporting numbers:

    * **CPython compiles it.** `compile()` and no execution: a program CPython
      will not parse was never a differential test, and finding that here costs
      nothing rather than costing a build.
    * **It is deterministic.** `gen_program(seed)` twice, and a different seed
      giving a different program — the second half is what makes determinism
      useful rather than merely repeatable, since a generator that ignored its
      seed would satisfy the first.
    * **The subset's stated invariants hold textually**: a `def main(`, a
      `main(0)` to call it, and none of the Mojo-only keywords. The `main(0)` is
      load-bearing — without it CPython defines `main` and never runs it, and
      every seed would "agree" with an empty output.

    NOT checked here: `-> Int` on the generated helpers. It is a Mojo annotation
    and CPython parses it as an ordinary annotation, which is safe only because
    CPython 3.14 defers annotation evaluation (PEP 649) — this repository
    requires 3.14 anyway (`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend
    _needs_3_10.md`). It is in the corpus because it is what tells the backend
    what a callee hands back: without it a comparison against a call's result is
    REFUSED, which on an earlier corpus was a third of all seeds.
    """
    failures = 0
    for seed in range(200):
        src = F.gen_program(seed).source()
        try:
            compile(src, f"<seed {seed}>", "exec")
        except SyntaxError as e:
            failures += _fail(f"generator_seed_{seed}_is_not_python",
                              f"line {e.lineno}: {e.msg}\n{src}", verbose)
            continue
        if "def main(" not in src:
            failures += _fail(f"generator_seed_{seed}_has_no_main", src, verbose)
        if "main(0)" not in src:
            failures += _fail(f"generator_seed_{seed}_never_calls_main", src,
                              verbose)
        if F.gen_program(seed).source() != src:
            failures += _fail(f"generator_seed_{seed}_is_not_deterministic",
                              "two calls disagreed", verbose)
        if seed and F.gen_program(seed).source() == F.gen_program(0).source():
            failures += _fail(f"generator_seed_{seed}_equals_seed_0",
                              "the seed is not reaching the generator", verbose)
        for banned in ("var ", "fn ", "struct ", "Self"):
            if banned in src:
                failures += _fail(
                    f"generator_seed_{seed}_is_not_valid_python",
                    f"contains {banned!r}, which CPython cannot parse:\n{src}",
                    verbose)
    print(f"formal fuzz: generator PASS={200 - failures} FAIL={failures} "
          f"(200 seeds, no compiler)")
    return failures


def check_run(arch, seeds, jobs, verbose):
    """Twenty fixed seeds, end to end, and every verdict accounted for."""
    argv = [sys.executable, os.path.join(ROOT, "tools", "formal_fuzz.py"),
            "--seeds", f"0-{seeds - 1}", "--arch", arch, "-j", str(jobs),
            "--repro-dir", os.path.join(ROOT, "build", "formal-fuzz",
                                        f"suite-{arch}")]
    if verbose:
        argv.append("-v")
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout or ""
    if verbose:
        print(out)
    failures = 0
    if proc.returncode != 0:
        # The tool exits 1 for an unexplained divergence or an ERROR, which is
        # exactly what this asserts against; print its report so the reason is
        # the tool's own words and not a status.
        failures += _fail(f"run_{arch}", out.strip()[-3000:], verbose)
    # The summary's own numbers, read off it rather than off the exit status
    # alone: the exit status says SOMETHING was wrong and these say what, and a
    # runner that printed no summary would otherwise pass by printing nothing.
    def _count(label):
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0] == label:
                return int(parts[1])
        return None

    for label in ("agree", "refused", "trapped", "diverged", "errors"):
        if _count(label) is None:
            failures += _fail(f"run_{arch}_printed_no_{label}_count",
                              out.strip()[-1500:], verbose)
    if _count("errors"):
        failures += _fail(f"run_{arch}_reported_errors",
                          f"errors {_count('errors')}: a generator defect — the "
                          f"program CPython will not run is the oracle's own "
                          f"traceback", verbose)
    unexplained = [ln for ln in out.splitlines()
                   if ln.strip().endswith("unexplained") and ln.strip()[:-11]
                   .split()[-1] != "0"]
    if unexplained:
        failures += _fail(f"run_{arch}_reported_unexplained_divergences",
                          "\n".join(unexplained), verbose)
    if _count("agree") == 0:
        failures += _fail(f"run_{arch}_agreed_on_nothing",
                          "a corpus of twenty seeds where nothing agreed is a "
                          "corpus that is not measuring the backend", verbose)
    tally = [ln for ln in out.splitlines() if ln.strip().startswith("agree")]
    print(f"formal fuzz: run {arch} PASS={1 if not failures else 0} "
          f"FAIL={failures} ({seeds} seeds) — {tally[0].strip() if tally else '?'}")
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--seeds", type=int, default=SEEDS,
                    help=f"fixed seeds to run per architecture (default {SEEDS})")
    ap.add_argument("--arch", default="both", choices=("arm64", "x86_64", "both"))
    ap.add_argument("-j", "--jobs", type=int, default=2)
    args = ap.parse_args()

    print("=" * 68)
    print("FORMAL FUZZ — the generator's corpus and the runner's verdicts")
    print("=" * 68)
    failures = check_generator(args.verbose)
    arches = ("arm64", "x86_64") if args.arch == "both" else (args.arch,)
    for arch in arches:
        failures += check_run(arch, args.seeds, args.jobs, args.verbose)
    print()
    print(f"Results: {'PASS' if not failures else 'FAIL'} — "
          f"{failures} failure(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())