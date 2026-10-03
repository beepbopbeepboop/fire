#!/usr/bin/env python3
"""`tools/formal_proof_fuzz.py`'s own regression suite: the GENERATOR, the
CLASSIFIER, and the widening that makes the corpus reachable.

    python3 test_formal_proof_fuzz.py [-v] [--run N]

Why this file exists
--------------------
The fuzzer is a measurement, and a measurement whose own machinery is untested
measures the machinery.  Three things can be wrong with it, and each would look
like a clean backend:

* **the generator emits something that is not a differential test** — a `var`
  CPython cannot parse, a local read before its first assignment, a `print` of a
  literal that agrees with CPython whatever the model says.  All three are
  checked here, with no compiler and no Lean, which is why the corpus check is
  cheap enough to cover sixty indexes.
* **the classifier's cross of the two halves is not the cross it claims** — a
  `MISMATCH` under a proof Lean never accepted reported as a soundness bug, or a
  hole count that stops mattering.  `decide` is exercised directly over the four
  interesting cells rather than inferred from a run.
* **the widening that unblocked the corpus can be undone silently.**  The commit
  that added this file took arm64 from 26 of 60 programs reaching a proof to 60
  of 60, and the reason is a rule ("a branch condition is rendered in the
  model's environment at that point in the source") that was written out at five
  places and is now at two helpers.  A corpus that quietly stops reaching Lean
  is a green run that measures nothing, so two programs are put through the real
  `compile_formal` with `check=False` — no Lean, no image — and required to
  produce a proof on BOTH architectures.

What is deliberately NOT here: a Lean run.  This file is the cheap half; the
expensive half is `tools/formal_proof_fuzz.py` itself, and its verdicts are
content-addressed in `formal/lean.py`'s CAS, so a campaign re-run is a file read
per program rather than a Lean elaboration.  The one thing a Lean run would add
that this cannot check is the hole COUNT a real proof carries, and that number
is the generator's declared design floor (`HOLES_FLOOR`), asserted here against
the generator's own docstrings rather than against a Lean run.

NOT registered in `tools/suite.py` (declared in `test_suite.py`'s
`UNREGISTERED` with that reason): it is the instrument's own suite, the way
`test_formal_fuzz.py` is, and it spawns `fire.py build` through the real
pipeline for the widening cases.
"""

import argparse
import contextlib
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import formal_proof_fuzz as P  # noqa: E402

# How many indexes the generator check covers.  The generator half costs no
# compiler and no Lean, so it is the wide one; the widening half builds two real
# programs and is the narrow one, because a build is the only thing here that
# touches the backend.
GEN_INDEXES = 60

#: The corpus words CPython is handed the generated text with, plus the argument
#: list, because this corpus's entry takes arguments (the other fuzzer's does
#: not) and the reference call is the thing being checked.
PRELUDE = P.F.PRELUDE


def _fail(name, detail, verbose):
    print(f"  FAIL  {name}: {detail}")
    if verbose:
        print("        " + str(detail).replace("\n", "\n        "))
    return 1


# ── the generator ───────────────────────────────────────────────────────────

def check_generator(indexes, verbose):
    """Every generated program is a valid differential test at its own input.

    Five properties, each a way the corpus could stop measuring the model while
    still reporting numbers:

    * **CPython parses and RUNS it** at the input it was drawn for — the
      reference call is part of the comparison, so a `NameError` or a
      `SyntaxError` there is a generator defect that costs nothing to find here
      and everything to find in a campaign.
    * **It is deterministic**, and a different index gives a different program.
    * **It says `def main(`** and **reads its own parameter**, so the image is
      built at an input the program actually uses — a program that ignores `n`
      agrees with CPython whatever the model says about `n`.
    * **The printed expression is not a literal**, for the same reason: a
      constant answer is a green run that measures nothing.
    * **It is one program, not two dialects**: no `var`, no `struct`, no `fn`,
      none of which CPython can parse — the corpus's premise is that both
      engines run the SAME TEXT.
    """
    failures = 0
    first = None
    for index in range(indexes):
        text, value, nparams = P.make_program("suite", index)
        args = ", ".join([str(value)] + ["0"] * (nparams - 1))
        if index == 0:
            first = text
        try:
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                exec(compile(PRELUDE + text + f"\nmain({args})\n",
                             f"<proof-suite {index}>", "exec"),
                     {"__name__": "__main__"})
            if not captured.getvalue().strip():
                failures += _fail(f"index_{index}_prints_nothing_at_run",
                                  "the oracle produced no output, so the "
                                  "comparison this program exists for is over "
                                  "an empty string", verbose)
        except Exception as e:                              # noqa: BLE001
            failures += _fail(f"index_{index}_does_not_run_under_cpython",
                              f"{type(e).__name__}: {e}\n{text}", verbose)
            continue
        if P.make_program("suite", index) != (text, value, nparams):
            failures += _fail(f"index_{index}_is_not_deterministic",
                              "two calls disagreed", verbose)
        if index and text == first:
            failures += _fail(f"index_{index}_equals_index_0",
                              "the index is not reaching the generator", verbose)
        if "def main(" not in text:
            failures += _fail(f"index_{index}_has_no_main", text, verbose)
        head = text.split("\n", 1)[0]
        params = head[head.index("(") + 1:head.index(")")]
        if not any(p in text for p in [x.strip() for x in params.split(",")]):
            failures += _fail(f"index_{index}_never_reads_its_parameter",
                              f"no occurrence of {params!r} outside the "
                              f"signature:\n{text}", verbose)
        printed = [ln for ln in text.splitlines() if ln.strip().startswith("print(")]
        if not printed:
            failures += _fail(f"index_{index}_prints_nothing", text, verbose)
        elif printed[-1].strip() in ("print()",) or \
                all(ch.isdigit() or ch in "() +-*" for ch in
                    printed[-1].split("(", 1)[1]):
            failures += _fail(f"index_{index}_prints_a_literal",
                              f"the observed value does not depend on the "
                              f"program's own data: {printed[-1]}", verbose)
        for banned in ("var ", "struct ", "fn ", "self."):
            if banned in text:
                failures += _fail(f"index_{index}_is_not_valid_python",
                                  f"contains {banned!r}, which CPython cannot "
                                  f"parse, or which makes it a different "
                                  f"program from what both engines run:\n{text}",
                                  verbose)
    print(f"proof fuzz: generator PASS={indexes - failures} FAIL={failures} "
          f"({indexes} indexes, no compiler, no Lean)")
    return failures


# ── the classifier ──────────────────────────────────────────────────────────

def check_classifier(verbose):
    """`decide` is the cross of the two halves, exercised over its four cells.

    The failure this guards against is over-claiming: calling a code-generator
    miscompile a soundness bug of the model.  A classifier that did that would
    make every MISMATCH in a campaign look like a proof about a wrong model, and
    the whole tool's claim would then rest on nothing.
    """
    cases = [
        # (proof cls, holes, behaviour verdict, holes_below, expected)
        ("pass", 0, "MISMATCH", 0, P.SOUNDNESS),
        ("pass", 0, "MISMATCH", 2, P.SOUNDNESS),
        ("admitted", 2, "MISMATCH", 2, P.ADMITTED_BUG),
        ("admitted", 5, "MISMATCH", 2, P.PLAIN),
        ("lean-rejected", 0, "MISMATCH", 2, P.PLAIN),
        ("proof-refused", 0, "MISMATCH", 2, P.PLAIN),
        ("not-checked", 0, "MISMATCH", 2, P.PLAIN),
        ("codegen-refused", 0, "MISMATCH", 2, P.PLAIN),
        ("pass", 0, "match", 0, "match"),
        ("admitted", 2, "refusal", 2, "refusal"),
        ("pass", 0, "trapped", 0, "trapped"),
    ]
    failures = 0
    for cls, holes, behaviour, below, want in cases:
        got = P.decide({"cls": cls, "holes": holes}, behaviour, below)
        if got != want:
            failures += _fail(f"classify_{cls}_{holes}_{behaviour}_at_{below}",
                              f"got {got!r}, expected {want!r}", verbose)
    # A Lean memory ceiling is NOT a rejection: the file was never finished
    # with, so calling it `lean-rejected` would report a fact about the machine
    # as a fact about the generator.
    if not P._lean_memory_detail(
            "libc++abi: terminating due to uncaught exception of type "
            "lean::memory_exception: excessive memory consumption detected"):
        failures += _fail("lean_memory_detail_misses_leans_own_ceiling",
                          "the census measured this as the binding constraint "
                          "on the arm64 half, so it must be its own class",
                          verbose)
    if P._lean_memory_detail("error: unsolved goals"):
        failures += _fail("lean_memory_detail_is_too_broad",
                          "a genuine rejection would be reported as a resource "
                          "outcome, which is the inference this tool must not "
                          "make", verbose)
    # The per-architecture floor, because the x86-64 half of the claim depends
    # on it being 2 and the arm64 half on it being 0.
    if P.HOLES_FLOOR.get("x86_64") != 2 or P.HOLES_FLOOR.get("arm64") != 0:
        failures += _fail("holes_floor", f"is {P.HOLES_FLOOR}, and both numbers "
                              "are load-bearing: x86-64 emits exactly two "
                              "declared trust boundaries and arm64 none",
                          verbose)
    print(f"proof fuzz: classifier PASS={len(cases) - failures} "
          f"FAIL={failures} ({len(cases)} cells)")
    return failures


# ── the widening, through the real pipeline ──────────────────────────────────

WIDENING = {
    # name -> (source, expectation, why this program was refused before).
    # An expectation may be per architecture, which is how a LIMIT that only one
    # architecture has is stated: the x86-64 walk discharges a call out of the
    # image per BLOCK rather than by one exit address, so it proves this program
    # and the two backends genuinely disagree about what is provable.
    "a local in a condition": (
        "def main(n) -> Int:\n"
        "    a = (n & 0xFFFF)\n"
        "    b = (a + 3) & 0xFFFF\n"
        "    if b > 100:\n"
        "        c = b * 2\n"
        "    else:\n"
        "        c = b - 7\n"
        "    print(c)\n"
        "    return 0\n",
        "proof",
        "`_cond_nodes` walked only IfStmt/WhileStmt/ForStmt, so a condition "
        "reading a local was rendered in an environment that had never been told "
        "about it: \"model: `b` is read here and this generator binds it to "
        "nothing\". 34 of the fuzzer's 60 plain programs."),
    "a second parameter in a condition": (
        "def main(n, m) -> Int:\n"
        "    if m > 100:\n"
        "        c = m + 1\n"
        "    else:\n"
        "        c = n - 1\n"
        "    print(c)\n"
        "    return 0\n",
        "proof",
        "the call sites that build the entry environment passed "
        "`{first_parameter: first_parameter}`, which binds the first parameter "
        "to ITSELF and leaves `m` to nothing — invisible at arity one, which is "
        "every program in `formal/examples`, and fatal for any wider entry "
        "whose condition reads a later parameter."),
    "two calls out of the image": (
        "def main(n) -> Int:\n"
        "    if n > 100:\n"
        "        print(1)\n"
        "    print(2)\n"
        "    return 0\n",
        {"arm64": "refused", "x86_64": "proof"},
        "the walk discharges a call out of the image by HALTING at it, and it "
        "halts only on the paths that pass that one address — so the `else` "
        "path reached `print(2)` and executed its BL as if it were a self-call, "
        "raising `ValueError: unsupported: recursion argument bound (not a "
        "dec1 pattern)` for a program with no recursion. A crash where the "
        "generator owes a refusal; it now refuses by name on arm64."),
}


def check_widening(tmpdir, verbose):
    """Each of these must reach the state its `expectation` names, on BOTH
    architectures.

    `check=False` on purpose: this is about the generator REACHING or REFUSING
    the proof layer, and the Lean run is a different question (and a 6 GB one).
    A corpus that quietly stops reaching Lean is a green campaign that measures
    nothing, so this is the assertion that keeps the widening from being undone
    — and a refusal that crashes instead of naming itself is a defect in the
    generator, so `expectation="refused"` asserts the CLASS of the failure too,
    not merely that something went wrong.
    """
    import formal.build as FB
    failures = 0
    for name, (src, expect, why) in sorted(WIDENING.items()):
        stem = name.replace(" ", "_")
        path = os.path.join(tmpdir, stem + ".mojo")
        with open(path, "w") as f:
            f.write(src)
        for arch in ("arm64", "x86_64"):
            want = expect[arch] if isinstance(expect, dict) else expect
            out = os.path.join(tmpdir, f"{stem}.{arch}")
            proof = None
            refusal = None
            try:
                result = FB.compile_formal(path, output=out, test_input=10,
                                           prove=True, check=False, arch=arch)
                proof = result.get("proof_path")
            except NotImplementedError as e:
                refusal = str(e)
            except Exception as e:                          # noqa: BLE001
                failures += _fail(f"{name}_crashes_on_{arch}",
                                  f"{type(e).__name__}: {e}\n\n{why}",
                                  verbose)
                continue
            if want == "proof":
                if refusal is not None:
                    failures += _fail(f"{name}_is_refused_on_{arch}",
                                      f"{refusal}\n\n{why}", verbose)
                elif not proof or not os.path.isfile(proof):
                    failures += _fail(f"{name}_emits_no_proof_on_{arch}",
                                      "the build succeeded and wrote no proof, "
                                      "so a campaign would report this program "
                                      "as covered when nothing was proved",
                                      verbose)
            else:
                if refusal is None:
                    failures += _fail(f"{name}_was_not_refused_on_{arch}",
                                      "it produces a proof, so the limit this "
                                      "case pins is gone and the case is stale: "
                                      "drop it", verbose)
                elif "2 calls this walk cannot follow" not in refusal:
                    failures += _fail(f"{name}_refused_for_another_reason_on_"
                                      f"{arch}", refusal, verbose)
    print(f"proof fuzz: widening  "
          f"{'PASS' if not failures else 'FAIL'} FAIL={failures} "
          f"({2 * len(WIDENING)} programs, no Lean)")
    return failures


# ── the run half, without Lean ──────────────────────────────────────────────

def check_run(count, verbose):
    """`count` pinned programs end to end with `--no-lean`, and every verdict
    accounted for.

    The run half of this tool is the same shape as the other fuzzer's, and so is
    the discipline: a corpus where nothing agreed is a corpus that is not
    measuring the backend, and a `generator-error` would be the generator's own
    traceback reported as a fact about the model.  `--no-lean` because the Lean
    verdict is content-addressed and the campaign is where it is measured; what
    is checked here is that the plumbing from a program to a verdict works at
    all, which is a bug this file can find in seconds.
    """
    import json
    work = os.path.join(ROOT, ".tmp", "test_formal_proof_fuzz")
    argv = [sys.executable, os.path.join(ROOT, "tools",
                                         "formal_proof_fuzz.py"),
            "--seed", "suite", "--count", str(count), "--arch", "both",
            "--no-lean", "-j", "2", "--work", work]
    if verbose:
        argv.append("-v")
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout or ""
    if verbose:
        print(out)
    failures = 0
    if proc.returncode != 0:
        failures += _fail("run_exits_zero", out.strip()[-2000:], verbose)
    ledger = os.path.join(work, "findings.json")
    if not os.path.isfile(ledger):
        return failures + _fail("run_wrote_no_ledger", out.strip()[-1000:],
                                verbose)
    with open(ledger) as f:
        data = json.load(f)
    counts = data.get("counts") or {}
    proof = data.get("proof") or {}
    if not counts.get("match"):
        failures += _fail("run_agreed_on_nothing",
                          f"a corpus of {count} programs where nothing agreed "
                          f"is a corpus that is not measuring the backend: "
                          f"{counts}", verbose)
    for arch in ("arm64", "x86_64"):
        # `--no-lean` on a corpus that reaches the proof layer must leave the
        # ONLY proof class `not-checked`; a refusal here would mean the corpus
        # had stopped reaching the model, which is the thing this file exists to
        # notice, and it would show up as a small number and a red no test sees.
        if not proof.get(f"{arch}:not-checked"):
            failures += _fail(f"run_reached_no_proof_on_{arch}",
                              f"{proof} — every program refused or the "
                              f"generator emitted nothing", verbose)
        for key, n in proof.items():
            if key.startswith(f"{arch}:") and n and \
                    key != f"{arch}:not-checked":
                failures += _fail(f"run_saw_{key}",
                                  f"{n} of {count} programs were refused, and a "
                                  f"refusal is a limit of the proof layer rather "
                                  f"than a measurement of the model", verbose)
    tally = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"proof fuzz: run       {'PASS' if not failures else 'FAIL'} "
          f"FAIL={failures} ({count} programs, no Lean) — {tally or '?'}")
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--gen-indexes", type=int, default=GEN_INDEXES)
    ap.add_argument("--run", type=int, default=4,
                    help="programs the end-to-end run covers (default 4; it "
                         "builds each one once per input per architecture)")
    ap.add_argument("--skip-run", action="store_true")
    args = ap.parse_args()

    import tempfile
    print("=" * 68)
    print("FORMAL PROOF FUZZ — the generator, the classifier, the widening")
    print("=" * 68)
    failures = check_generator(args.gen_indexes, args.verbose)
    failures += check_classifier(args.verbose)
    with tempfile.TemporaryDirectory(dir=os.path.join(ROOT, ".tmp")) as td:
        failures += check_widening(td, args.verbose)
    if not args.skip_run:
        failures += check_run(args.run, args.verbose)
    print()
    print(f"Results: {'PASS' if not failures else 'FAIL'} — "
          f"{failures} failure(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())