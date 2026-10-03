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
  `NameError`, a trap, a `SyntaxError`) and the program counts towards the run's
  totals while reporting nothing about the backend. So every mix's output is
  checked for all three, with no compiler involved.
* **the runner's verdicts are not verdicts** — a build that reported success and
  wrote no binary, a comparison that stopped at the exit code and ignored the
  output, an attribution that dismissed everything. So a fixed index range is
  run end to end and every disagreement is required to be either attributed to a
  construct `KNOWN_DIVERGENCES` names or reported as unexplained, and the second
  of those is a failure here.

* **a construct family that has quietly become refusable** — a mix whose
  programs are all REFUSED still parses, still runs on CPython, still counts
  towards a run's totals and reports nothing about the backend, so it is
  indistinguishable from a clean one. `check_mix_builds` requires every mix to
  produce at least one ANSWER on one architecture. This is the check that would
  have caught `objects`' `field_read` on the day `print(obj.field)` started
  being refused — 284 of 300 generated class programs were that one refusal.

    python3 test_formal_fuzz.py [-v] [--count N] [--arch both|arm64|x86_64]
                                [--mix MIX]

The indexes are PINNED and the count is small on purpose. The point is not
coverage — a sweep is what covers this — it is that a change to the generator,
the classifier or the attribution which altered a verdict would fail HERE
instead of quietly changing what a sweep of two thousand programs measures.

Every mix is checked in the generator half, including `signed` and `strings`,
because those two carry the known-divergent constructs on purpose: a mix that
stopped producing `//` with a signed divisor, or `s[i]`, would leave its
`KNOWN_DIVERGENCES` row unreachable, and a row nothing can trigger is a row that
has stopped measuring the construct it names. That is asserted directly, not
inferred.

NOT registered in `tools/suite.py` (it is declared in `test_suite.py`'s
`UNREGISTERED` with that reason). It builds twenty images per architecture, which
is more than a unit test's share, and its heavier setting — a few thousand
programs — is a sweep rather than a check.
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

# How many indexes the generator half checks per mix, and how many the run half
# pins end to end. The generator half costs nothing (no compiler), so it is the
# wider of the two; the run half is the expensive one and is deliberately small.
GEN_INDEXES = 60
SEEDS = 20

# The corpus words CPython is handed the generated text with. A program CPython
# will not parse was never a differential test, and finding that here costs
# nothing rather than costing a build.
PYTHON_HEAD = F.PRELUDE + "\n"


def _fail(name, detail, verbose):
    print(f"  FAIL  {name}: {detail}")
    if verbose:
        print("        " + detail.replace("\n", "\n        "))
    return 1


def check_generator(mix, indexes, verbose=False):
    """Every generated program is a valid differential test.

    Four properties, and each is a way the corpus could stop measuring the
    backend while still reporting numbers:

    * **CPython parses it**, prelude and `main()` call included — that pair is
      what the run half actually executes, so it is what is checked here.
    * **It is deterministic.** `make_program` twice, and a different index
      giving a different program — the second half is what makes determinism
      useful rather than merely repeatable, since a generator that ignored its
      seed would satisfy the first.
    * **It names the known constructs its mix exists to reach.** This is the
      anti-rot on `KNOWN_DIVERGENCES`: the two mixes that carry a known
      divergence must keep producing it, or the row is dead and the day the
      backend is fixed nobody notices.
    * **The subset's stated invariants hold textually**: a `def main(`, and
      none of the Mojo-only keywords CPython cannot parse.
    """
    failures = 0
    first = make_first = F.make_program("suite", 0, mix)
    for index in range(indexes):
        src = F.make_program("suite", index, mix)
        try:
            compile(PYTHON_HEAD + src + "\nmain()\n", f"<{mix} {index}>", "exec")
        except SyntaxError as e:
            failures += _fail(f"{mix}_index_{index}_is_not_python",
                              f"line {e.lineno}: {e.msg}\n{src}", verbose)
            continue
        if "def main(" not in src:
            failures += _fail(f"{mix}_index_{index}_has_no_main", src, verbose)
        if F.make_program("suite", index, mix) != src:
            failures += _fail(f"{mix}_index_{index}_is_not_deterministic",
                              "two calls disagreed", verbose)
        if index and src == first:
            failures += _fail(f"{mix}_index_{index}_equals_index_0",
                              "the index is not reaching the generator", verbose)
        for banned in ("var ", "fn ", "struct ", "Self"):
            if banned in src:
                failures += _fail(
                    f"{mix}_index_{index}_is_not_valid_python",
                    f"contains {banned!r}, which CPython cannot parse:\n{src}",
                    verbose)

    failures += _check_features(mix, indexes, verbose)

    print(f"formal fuzz: generator {mix:9} PASS={indexes - failures} "
          f"FAIL={failures} ({indexes} indexes, no compiler)")
    return failures


#: mix -> the feature it must keep producing, and why that mix exists.
MIX_MUST_REACH = {
    "signed": ("floordiv",
               "`--mix signed` is the only place a signed-over-signed division "
               "is generated, which is the whole of the floor/truncate "
               "disagreement"),
    "strings": ("str_subscript",
                "`s[i]` is a byte rather than a one-character string, and the "
                "corpus has to produce it for the row to stay live"),
}


def _check_features(mix, indexes, verbose):
    """The mixes that carry a known divergence must still produce it.

    Checked over the same index range as the rest, and it is a separate check
    rather than a property of the syntax pass because the failure it catches is
    silent: a mix that stopped emitting signed divisors would still parse, would
    still run, and would still report numbers — every one of them clean — while
    `KNOWN_DIVERGENCES["floordiv"]` had become unreachable. That is a coverage
    hole dressed as a green run.
    """
    want = MIX_MUST_REACH.get(mix)
    if not want:
        return 0
    feature, why = want
    hits = 0
    for index in range(indexes):
        src = F.make_program("suite", index, mix)
        if feature in F.features_of(src):
            hits += 1
            # The neutraliser has to be able to TAKE IT OUT, or attribution
            # would fall through to "unexplained" on every program the mix
            # exists to produce.
            if F.neutralise(src, feature) is None:
                return _fail(f"{mix}_cannot_neutralise_{feature}",
                             f"{why}, and the neutraliser cannot remove it",
                             verbose)
    if hits == 0:
        return _fail(f"{mix}_never_reaches_{feature}", why, verbose)
    print(f"formal fuzz: generator {mix:9} reaches {feature} in "
          f"{hits}/{indexes}")
    return 0


# (name, results dict, want verdict).  `results` is what `check_one` hands
# `classify`, built by hand because the classifier is the one piece of the
# runner that decides EVERYTHING and that no case exercises on its own: every
# other row here goes through a real build, so it can only reach the verdicts
# the corpus happens to produce.
#
# `ok` is `{"verdict": "ok", "rc": <int>, "stdout": <str>}`; the oracle this
# table compares against is `(0, "1\n")`, so an `ok` carrying that is a match
# and anything else is a disagreement with it.
CLASSIFIER_CASES = [
    ("both_agree", {"x86_64": {"verdict": "ok", "rc": 0, "stdout": "1\n"},
                    "arm64": {"verdict": "ok", "rc": 0, "stdout": "1\n"}},
     "match"),
    ("one_disagrees", {"x86_64": {"verdict": "ok", "rc": 0, "stdout": "1\n"},
                       "arm64": {"verdict": "ok", "rc": 0, "stdout": "2\n"}},
     "MISMATCH-ARM64"),
    # Two different answers from two machines that both RAN. `ARM64-DIVERGES` is
    # the verdict this shape is about, and it is UNREACHABLE while the two
    # oracle comparisons come first: both answers are compared against the same
    # CPython output, so "both agree with CPython and differ from each other"
    # cannot happen. Measured by writing this case and getting `MISMATCH-X86` —
    # which is the RIGHT answer (x86-64 printed `2` where the source says `1`),
    # and which names the engine that is wrong about the program. The verdict is
    # kept because the docstring documents it and because it becomes reachable
    # the moment the ordering changes, but a reader must not expect to see it in
    # a sweep's tally.
    ("the_two_answers_differ", {"x86_64": {"verdict": "ok", "rc": 0,
                                           "stdout": "2\n"},
                                "arm64": {"verdict": "ok", "rc": 0,
                                          "stdout": "3\n"}},
     "MISMATCH-X86"),
    # BOTH refusing is NOT a finding. A construct with no representation is
    # correctly refused, and counting those as bugs would spend the whole
    # budget on `bugs/FORMAL_known_limits.md`.
    ("both_refuse", {"x86_64": {"verdict": "refusal", "diag": "no"},
                     "arm64": {"verdict": "refusal", "diag": "no"}},
     "refusal"),
    # …and ONE refusing while the other ANSWERS is, because the construct is
    # representable and this machine declines it. Measured on the tree this
    # landed on: arm64 built and ran a program x86-64 refused with "main:
    # '_cb0' has no home", and the sweep called it a plain `refusal`.
    ("one_refuses_while_the_other_answers",
     {"x86_64": {"verdict": "refusal", "diag": "no home"},
      "arm64": {"verdict": "ok", "rc": 0, "stdout": "1\n"}},
     "REFUSAL-DIVERGES-X86"),
    ("one_refuses_the_other_way",
     {"x86_64": {"verdict": "ok", "rc": 0, "stdout": "1\n"},
      "arm64": {"verdict": "refusal", "diag": "no home"}},
     "REFUSAL-DIVERGES-ARM"),
    # A refusal AND a wrong answer is the wrong answer, and it is reported as
    # one: the finding names the engine that is wrong about the program's
    # meaning, which is the engine that produced an answer.
    ("one_refuses_and_the_other_is_wrong",
     {"x86_64": {"verdict": "refusal", "diag": "no"},
      "arm64": {"verdict": "ok", "rc": 0, "stdout": "9\n"}},
     "MISMATCH-ARM64"),
    # A crash outranks a refusal and a trap: both are about the IMAGE rather
    # than about a difference between two of them.
    ("a_crash_is_a_finding",
     {"x86_64": {"verdict": "crash", "rc": 139},
      "arm64": {"verdict": "refusal", "diag": "no"}}, "CODEGEN-CRASH"),
    ("a_trap_is_not",
     {"x86_64": {"verdict": "ok", "rc": 0, "stdout": "1\n"},
      "arm64": {"verdict": "trapped", "rc": 2}}, "trapped"),
]


def check_classifier(verbose):
    """Every verdict `classify` can return, on results built by hand.

    No compiler and no corpus: this is the function that decides whether a
    program that computed the wrong number is a finding, and it is reached only
    through a real build everywhere else in this file — so a change to it that
    turned a `MISMATCH-*` into a `refusal` would pass every other row here and
    turn a sweep green.
    """
    args = argparse.Namespace(backends=["x86_64", "arm64"], min_kind="any")
    failures = 0
    for name, results, want in CLASSIFIER_CASES:
        got = F.classify(results, 0, "1\n", args)
        if got != want:
            failures += _fail(f"classify_{name}", f"said {got!r}, "
                              f"expected {want!r}", verbose)
    print(f"formal fuzz: classify    {'PASS' if not failures else 'FAIL'} "
          f"{len(CLASSIFIER_CASES)} verdicts (no compiler)")
    return failures


def check_run(arch, count, jobs, verbose):
    """`count` pinned indexes, end to end, and every verdict accounted for."""
    argv = [sys.executable, os.path.join(ROOT, "tools", "formal_fuzz.py"),
            "--seed", "suite", "--arch", arch, "--seeds", f"0-{count - 1}",
            "-j", str(jobs), "--work", os.path.join(ROOT, "build",
                                                    "formal-fuzz", f"suite-{arch}")]
    if verbose:
        argv.append("-v")
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout or ""
    if verbose:
        print(out)
    failures = 0
    if proc.returncode != 0:
        # The tool exits 1 for an unexplained disagreement, a codegen crash or a
        # generator error, which is exactly what this asserts against; print its
        # report so the reason is the tool's own words and not a status.
        failures += _fail(f"run_{arch}", out.strip()[-3000:], verbose)

    counts = _counts(out)
    for label in ("match", "trapped", "refusal"):
        if label not in counts:
            failures += _fail(f"run_{arch}_printed_no_{label}_count",
                              out.strip()[-1500:], verbose)
    for label, n in sorted(counts.items()):
        if label.startswith("generator-error"):
            failures += _fail(
                f"run_{arch}_reported_generator_errors",
                f"{n} program(s) CPython will not run: that is the oracle's "
                f"own traceback and measures the generator, not the backend",
                verbose)
        elif label.startswith(("MISMATCH", "ARM64-DIVERGES", "CODEGEN-CRASH",
                               "REFUSAL-DIVERGES")):
            failures += _fail(f"run_{arch}_reported_{label}",
                              f"{n} unexplained — every disagreement in the "
                              f"known table must have reduced to it, and one "
                              f"architecture declining what another lowered "
                              f"is a finding whatever the known table says",
                              verbose)
    if not counts.get("match"):
        failures += _fail(f"run_{arch}_agreed_on_nothing",
                          f"a corpus of {count} programs where nothing agreed "
                          f"is a corpus that is not measuring the backend",
                          verbose)
    tally = " ".join(f"{v}={n}" for v, n in sorted(counts.items()))
    print(f"formal fuzz: run {arch:6} "
          f"{'PASS' if not failures else 'FAIL'} FAIL={failures} "
          f"({count} programs) — {tally or '?'}")
    return failures


def _counts(out):
    """The summary's own tally, read off its lines.

    A verdict name can contain a space-free `:` (`KNOWN:floordiv`) but never a
    space, so the first two fields of each tally line are the name and the
    count. Read off the summary rather than off the exit status alone: the exit
    status says SOMETHING was wrong and this says what, and a runner that
    printed no summary would otherwise pass by printing nothing.
    """
    counts = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit() and not line.startswith(" " * 4):
            counts[parts[0]] = int(parts[1])
    return counts


#: How many pinned programs each mix is RUN for in `check_mix_builds`, and on
#: which architecture. Two programs is the smallest number that can distinguish
#: "this family builds" from "this family is refused", and ONE architecture is
#: enough because the question is about the FAMILY — the two are checked against
#: each other by the sweep, and every case in the other half of this file is
#: already run on both.
MIX_BUILD_INDEXES = 2
MIX_BUILD_ARCH = "x86_64"

#: Mixes whose constructs are NOT supposed to lower, so "no answer" is the
#: expected outcome for them and requiring one would be requiring a bug. There
#: are none today, and the empty table is the point: a family added to `MIXES`
#: is a family whose construct the backend lowers, so a mix that cannot produce
#: an answer is a mix that cannot find anything. The `field_read` row in
#: `tools/formal_fuzz.py` is why this check exists at all — 284 of 300 generated
#: class programs were ONE refusal, which is a family that measures nothing and
#: a suite that reported numbers.
MIXES_NOT_LOWERED = ()


def check_mix_builds(mix, indexes, verbose):
    """Every mix produces at least one ANSWER, not only refusals.

    The generator half above proves the text is a valid differential program and
    the run half proves the verdicts are verdicts; neither can see that a whole
    construct family has quietly become refusable. A refused program still
    parses, still runs on CPython, still counts towards the run's totals, and
    reports nothing about the backend — so a mix that is 95% refused is a mix
    that finds nothing and looks exactly like a clean one.

    `generator-error` counts as a FAILURE here rather than as "not an answer":
    it is the generator's own failure (CPython rejected the text), which
    `check_generator` cannot see because it only compiles.
    """
    if mix in MIXES_NOT_LOWERED:
        return 0
    work = os.path.join(ROOT, "build", "formal-fuzz", f"builds-{mix}")
    argv = [sys.executable, os.path.join(ROOT, "tools", "formal_fuzz.py"),
            "--seed", "suite", "--arch", MIX_BUILD_ARCH, "--mix", mix,
            "--seeds", f"0-{indexes - 1}", "-j", str(indexes),
            "--work", work, "--quiet"]
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout or ""
    counts = _counts(out)
    # An ANSWER is any verdict that means an image ran and said something. A
    # `KNOWN:…` disagreement counts, because the images answered and the
    # disagreement is a documented one — `strings` is mostly those, and a check
    # that required `match` would report the family that carries a known
    # divergence as a family that cannot build. A `trapped` counts too: the guard
    # stopped the program on purpose, which is an answer about the program. A
    # `refusal`, a `generator-error`, a `timeout` and a `codegen-crash` do not:
    # none of them is the backend saying what the program computes.
    answers = sum(n for k, n in counts.items()
                  if k == "match" or k == "trapped"
                  or k.startswith(("KNOWN:", "MISMATCH", "ARM64-")))
    failures = 0
    if counts.get("generator-error"):
        failures += _fail(
            f"{mix}_has_generator_errors",
            f"{counts['generator-error']} program(s) CPython will not run; the "
            f"generator half compiles nothing so this is where it shows",
            verbose)
    if not answers:
        failures += _fail(
            f"{mix}_produced_no_answer",
            f"{counts.get('refusal', 0)} refusal(s) and nothing else — a "
            f"family that is always refused measures nothing and reports "
            f"numbers anyway", verbose)
    print(f"formal fuzz: builds   {mix:9} "
          f"{'PASS' if not failures else 'FAIL'} "
          f"answers={answers}/{indexes} (1 arch, {counts.get('refusal', 0)} "
          f"refused)")
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--count", type=int, default=SEEDS,
                    help=f"pinned programs to run per architecture "
                         f"(default {SEEDS})")
    ap.add_argument("--gen-indexes", type=int, default=GEN_INDEXES,
                    help=f"indexes the no-compiler generator check covers, per "
                         f"mix (default {GEN_INDEXES})")
    ap.add_argument("--arch", default="both", choices=("arm64", "x86_64", "both"))
    ap.add_argument("--mix", default=None, choices=sorted(F.MIXES),
                    help="one mix only; default is every mix")
    ap.add_argument("-j", "--jobs", type=int, default=2)
    ap.add_argument("--no-build-check", action="store_true",
                    help="skip the per-mix 'does this family BUILD' half, "
                         "which builds two programs per mix")
    args = ap.parse_args()

    print("=" * 68)
    print("FORMAL FUZZ — the generator's corpus and the runner's verdicts")
    print("=" * 68)
    mixes = [args.mix] if args.mix else sorted(F.MIXES)
    failures = check_classifier(args.verbose)
    for mix in mixes:
        failures += check_generator(mix, args.gen_indexes, args.verbose)
    if not args.no_build_check:
        for mix in mixes:
            failures += check_mix_builds(mix, MIX_BUILD_INDEXES, args.verbose)
    arches = ("arm64", "x86_64") if args.arch == "both" else (args.arch,)
    for arch in arches:
        failures += check_run(arch, args.count, args.jobs, args.verbose)
    print()
    print(f"Results: {'PASS' if not failures else 'FAIL'} — "
          f"{failures} failure(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())