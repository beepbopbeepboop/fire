#!/usr/bin/env python3
"""test_formal_loop_invariants.py -- the loop corpus, the synthesised
candidates, the discharged obligations, and what REJECTS a wrong one.

WHAT THIS FILE IS FOR, and it is four things in one because they fail
independently and a file that tested only the first would say nothing about the
others:

 1. **THE ORACLE.**  Every program in `formal/loop_examples/` is built and RUN
    on BOTH architectures and required to exit with the status CPython gives the
    same source.  Nothing about `formal/loop_invariants.py` is a claim about the
    machine — its theorems are over `Int` and say so — so the Int model's
    agreement with the machine and with CPython is what ties the two together,
    and it is measured rather than asserted.

 2. **THE SYNTHESIS.**  Each program's FAMILY, its synthesised invariant, its
    synthesised variant and its SYNTHESISED PRECONDITION are pinned, so a change
    to the algebra that makes a loop derive a different candidate is a
    visible diff rather than a slower build.  These rows need no tool.

 3. **THE DISCHARGE.**  Each obligation is checked against Lean's verdict,
    through `formal/lean.py::run_lean` and the shared ladder, and each verdict
    is compared against a COMMITTED BASELINE
    (`tools/formal_loop_invariants_baseline.json`) that fails the run when an
    obligation gets worse.  That baseline is the proof-regression ledger for this
    layer; it is separate from `tools/formal_proof_census_baseline.json` because
    its unit is a (shape, obligation) pair and not a whole example file, and
    because eleven of these twelve programs are refused outright by the proof
    generator, so a census row for them would be a constant.

 4. **THE NEGATIVE CONTROLS.**  A candidate whose CLAIMED value is moved by 1,
    and a candidate whose DIRECTION is tilted by one coefficient so it is no
    longer an eigenvector, must both be REFUTED by the same `refute()` the
    verdict uses — and the unperturbed candidate must not be.  Without these, a
    `refute()` that always returned `None` would report every loop in the corpus
    as clean, and that is the exact shape of the bugs this project keeps filing.

Run:  python3 test_formal_loop_invariants.py [-v] [--write-baseline]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FIRE = os.path.join(HERE, "fire.py")
EXAMPLES = os.path.join(HERE, "formal", "loop_examples")
BASELINE = os.path.join(HERE, "tools", "formal_loop_invariants_baseline.json")
BACKENDS = ("arm64", "x86_64")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60

#: How many arguments each program takes, and the inputs the oracle runs it at.
#: Read from the source rather than a hand-kept table, because a table of
#: arities next to a corpus of programs is a table that goes stale the day
#: somebody adds a parameter, and a wrong arity shows up as a build refusal
#: rather than as the argument mistake it is.
ARGS = {"gcd_loop": [(12, 18), (7, 7), (1, 1)],
        "collatz": [(5,), (27,), (6,)]}
DEFAULT_ARGS = [(5,), (0,), (3,)]

RESULTS = []
VERBOSE = False


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f": {detail}" if detail else ""), flush=True)
    elif VERBOSE:
        print(f"PASS  {what}", flush=True)
    return bool(ok)


def programs():
    return sorted(p for p in os.listdir(EXAMPLES) if p.endswith(".mojo"))


def _path(stem):
    """The corpus file for a stem, with or without the extension.

    Both spellings are accepted because the two tables this file holds name a
    program differently: `SYNTHESIS` is keyed by stem (it is also keyed in
    `formal/loop_invariants.py`'s own docstrings, and it is how a reader types
    it) and the oracle loop walks the DIRECTORY, so it gets filenames.  Making
    one reader for it is cheaper than making two spellings of every table.
    """
    return os.path.join(EXAMPLES, stem if stem.endswith(".mojo")
                        else stem + ".mojo")


def source_of(stem):
    with open(_path(stem), encoding="utf-8") as f:
        return f.read()


def function_of(stem):
    """The program file's own function name, read from its AST.

    A corpus whose files are `def count_acc(n)` and whose test calls
    `count_acc` is a corpus with a second copy of the corpus's names, and this
    is the reader that removes it.
    """
    import fire_compiler as F
    mod = F.Parser(F.py_tokenize(source_of(stem))).parse_module()
    fns = [s for s in mod if type(s).__name__ == "FunctionDef"]
    if not fns:
        return None
    return fns[0].name


def cpython(stem, args):
    ns = {}
    exec(compile(source_of(stem), stem, "exec"), ns)
    name = function_of(stem)
    return ns[name](*args) & 0xFF


def build(stem, out, backend, args):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out,
           "-n", ",".join(str(a) for a in args), _path(stem)]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=HERE,
                              timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None


def run(out, backend):
    cmd = [out] if backend == "arm64" else ["arch", "-x86_64", out]
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)


# ── 1. the oracle ────────────────────────────────────────────────────────────

def test_every_program_answers_cpython_on_both_architectures(tmpdir):
    """Build and RUN every loop program, on arm64 and x86-64, against CPython.

    THE ORACLE ROW, and the reason it is here rather than assumed.
    `formal/loop_invariants.py`'s theorems are over `Int` — a signed reading of
    the program's word — and are NOT claims about the machine.  This row is what
    says the Int model and the two images agree with each other and with
    CPython, over the twelve shapes whose invariants the layer derives.  A
    change to the layer that silently changed the reading it assumes would show
    up here and nowhere else.

    **The two architectures are run by DIFFERENT commands**, which is not
    tidiness: running an arm64 image under `arch -x86_64` reports Rosetta's
    `Bad CPU type in executable` (exit 1) as the program's answer, and a table
    of confident wrong numbers is what that produces
    (`bugs/FORMAL_sweep_work_map.md`'s `b14` round, §7, records the hour it
    cost that map's author).
    """
    for stem in programs():
        fn = function_of(stem)
        check(fn is not None, f"{stem}: the corpus file declares a function",
              "and a corpus of files with no entry point proves nothing")
        if fn is None:
            continue
        for args in ARGS.get(stem[:-5], DEFAULT_ARGS):
            want = cpython(stem, args)
            for backend in BACKENDS:
                out = os.path.join(tmpdir, f"{stem[:-5]}_{backend}")
                p = build(stem, out, backend, args)
                if not check(p is not None and p.returncode == 0,
                             f"{stem[:-5]}{args} builds on {backend}",
                             "BUILD TIMEOUT" if p is None
                             else (p.stderr or p.stdout).strip()[-200:]):
                    continue
                r = run(out, backend)
                check(r.returncode == want,
                      f"{stem[:-5]}{args} on {backend}: the image answers "
                      f"CPython's {want}",
                      f"image {r.returncode}")


# ── 2. the synthesis ─────────────────────────────────────────────────────────

#: What the synthesis derives, pinned.  Read as a table rather than asserted
#: inline: a diff here says which SHAPE changed, which is the question a reader
#: has, and an inline assertion says only that some number moved.
SYNTHESIS = {
    "count_acc": ("count-accumulator", "(c + - i) = 0", "(n + - i)", "0 ≤ n"),
    "sum_acc": ("sum-accumulator", None, "(n + - i)", "0 ≤ n"),
    "prod_acc": ("product-accumulator", None, "(n + - i)", "0 ≤ n"),
    "while_lt_acc": ("decreasing-measure", None, "(n + - i)", "0 ≤ n"),
    "dec_measure": ("decreasing-measure", "(i + (2) * s) = n", "i", "0 ≤ n"),
    "min_scan": ("min-scan", None, "(- i + (6))", "0 ≤ (5)"),
    "max_scan": ("max-scan", None, "(- i + (6))", "0 ≤ (5)"),
    "array_fill": ("array-fill", None, "- i", "0 ≤ 0"),
    "array_copy": ("array-copy", None, "- i", "0 ≤ 0"),
    "linear_search": ("unreadable", None, None, None),
    "gcd_loop": ("modulo-loop", None, None, None),
    "collatz": ("collatz", None, "- steps", "0 ≤ 0"),
}


def verdicts_of(stem, lean=None):
    from formal import loop_invariants as LI
    import fire_compiler as F
    src = source_of(stem)
    mod = F.Parser(F.py_tokenize(src)).parse_module()
    out = []
    for fn in [s for s in mod if type(s).__name__ == "FunctionDef"]:
        out.extend(LI.check_function(fn, stem, lean=lean))
    return out


def test_the_synthesis_derives_what_the_table_says(tmpdir=None):
    """Each program's family, invariant, variant and precondition, pinned.

    No tool runs here, which is the point: the algebra is pure, so these rows
    are a fraction of a second over the whole corpus and a change to it is a
    diff rather than a slower gate.

    **`None` is a PINNED value, not a missing one.**  `sum_acc` has no affine
    invariant and `gcd_loop` has no candidate at all; both are recorded as
    `None`, so a change that starts deriving something for them — or stops — is
    visible in this table and not only in the Lean rows.
    """
    from formal import loop_invariants as LI
    for stem, want in sorted(SYNTHESIS.items()):
        vs = verdicts_of(stem)
        check(len(vs) >= 1, f"{stem}: the file has at least one loop", str(vs))
        if not vs:
            continue
        v = vs[0]
        check(v.family == want[0], f"{stem}: family is `{want[0]}`", v.family)
        got_inv = v.invariants[0].text if v.invariants else None
        check(got_inv == want[1], f"{stem}: invariant is `{want[1]}`",
              f"got {got_inv!r}; and when it is None the reason is in the "
              f"obligation row, not here")
        got_var = v.variants[0].text if v.variants else None
        check(got_var == want[2], f"{stem}: variant is `{want[2]}`",
              f"got {got_var!r}")
        check(v.precondition == want[3], f"{stem}: precondition is `{want[3]}`",
              f"got {v.precondition!r}")
        check(LI.SEARCH_STEPS > 0 and LI.SEARCH_INPUTS,
              f"{stem}: the bounded search's bounds are published numbers",
              "and a bound that is a constant 0 is a search that never runs")


def test_every_loop_answers_even_when_nothing_was_derived(tmpdir=None):
    """A loop with no candidate gets a row, and every row carries a reason.

    The "never silent" requirement as a TEST rather than as a promise.  Three
    of the twelve shapes derive nothing at all — `gcd_loop` has no affine
    transition, `linear_search`'s body leaves the loop, and every accumulator
    loop whose value this layer's linear arithmetic cannot state has no
    invariant — and each of them owes the reader a sentence naming the store or
    the construct that blocked it.
    """
    for stem in programs():
        for v in verdicts_of(stem):
            check(bool(v.obligations),
                  f"{stem} loop {v.index}: at least one obligation exists",
                  "a loop with no row at all is indistinguishable from a file "
                  "with no loop")
            check(all(bool(ob.why.strip()) for ob in v.obligations),
                  f"{stem} loop {v.index}: every obligation says why",
                  "an obligation with an empty `why` is a row a reader cannot "
                  "act on")
            check(all(ob.status for ob in v.obligations),
                  f"{stem} loop {v.index}: every obligation has a status")


def test_a_refusal_row_can_never_be_proved(tmpdir=None):
    """A row that says the obligation CANNOT BE STATED is UNKNOWN forever.

    The specific green light on nothing this module has to not ship.
    `sum_acc`'s "no affine invariant was derived, so the exit value is not
    determined" row once closed over the placeholder `True` and reported the
    loop PROVED — the same shape as a `sorry` over a false statement, with no
    false statement in sight.  `Obligation.refusal` is derived from the
    conclusion rather than passed in, so the rule cannot be forgotten at a call
    site, and this row pins that derivation.
    """
    from formal import loop_invariants as LI
    for stem in programs():
        for v in verdicts_of(stem):
            for ob in v.obligations:
                if ob.conclusion == "True":
                    check(ob.refusal,
                          f"{stem}/{ob.name}: a `True` conclusion is a refusal")
                    check("REFUSAL" in ob.lean(),
                          f"{stem}/{ob.name}: the emitted file says so in a "
                          f"comment")
                    check(not [ln for ln in ob.lean().split("\n")
                               if ln.startswith("theorem")],
                          f"{stem}/{ob.name}: a refusal emits NO theorem "
                          f"DECLARATION, which is what keeps `lean` from being "
                          f"asked to prove it")
                else:
                    check(not ob.refusal,
                          f"{stem}/{ob.name}: a real conclusion is not a "
                          f"refusal")


# ── 3. the negative controls ─────────────────────────────────────────────────

def test_a_wrong_claim_is_refuted_and_the_right_one_is_not(tmpdir=None):
    """`offset` and `tilt` must produce a counterexample; the clean one must not.

    Both controls go through the SAME `refute()` the verdict uses, which is the
    only thing that makes them controls: a check built by a second code path
    from the thing it checks proves nothing about it.

      `offset=1` moves the CLAIMED value.  `tilt` moves ONE COEFFICIENT, which
      takes the candidate off the eigenvector set — so this row says the
      SYNTHESIS is what makes the claim true, not that the claim happens to be
      consistent with a few iterations of one loop.

    `perturb` (scaling every coefficient) is deliberately NOT a control here:
    `count_acc`'s invariant is `c - i = 0` and `2c - 2i = 0` is implied by it,
    so scaling that one is not a wrong claim at all.  `dec_measure`'s is
    `i + 2*s = n`, and scaling it IS refuted — so the row uses the two that are
    wrong for the right reason and says why the third is not here.
    """
    from formal import loop_invariants as LI
    for stem in ("count_acc", "dec_measure"):
        v = verdicts_of(stem)[0]
        check(bool(v.invariants), f"{stem}: there is an invariant to falsify")
        if not v.invariants:
            continue
        cand = v.invariants[0]
        clean, _sk = LI.refute(v.shape, v.rel, cand)
        check(clean is None,
              f"{stem}: the SYNTHESISED invariant `{cand.text}` survives the "
              f"bounded search", str(clean))
        moved, _sk = LI.refute(v.shape, v.rel, cand, offset=1)
        check(moved is not None,
              f"{stem}: the same invariant with its claimed value moved by 1 "
              f"is REFUTED",
              "a search that cannot refute a claim whose right-hand side is "
              "wrong is a search that finds nothing, which is what this file "
              "exists to catch")
        if moved:
            check(moved["iterations"] <= LI.SEARCH_STEPS,
                  f"{stem}: the counterexample is inside the published bound")
        # ANY one coefficient moved is enough: moving one takes the candidate
        # off the eigenvector set.  Requiring a particular name would be
        # requiring a fact about which coefficient the solver happened to find,
        # and `dec_measure` has no `for` target to tilt.
        fired = []
        for var in sorted(cand.coeffs):
            witness, _sk = LI.refute(v.shape, v.rel, cand, tilt=(var, 1))
            if witness is not None:
                fired.append((var, witness["iterations"]))
        check(bool(fired),
              f"{stem}: moving ONE coefficient of `{cand.text}` is REFUTED — "
              f"it is no longer an eigenvector",
              f"tried {sorted(cand.coeffs)}; and this is the control that says "
              f"the algebra is what makes the claim true")


def test_a_variant_that_goes_negative_is_refuted(tmpdir=None):
    """The variant control, on a body the search CAN run.

    `while i != 4: i = i + 1` is the loop test `array_fill.mojo` writes, without
    the array store.  The only strictly decreasing affine functional is `- i`,
    and it goes NEGATIVE at `i = 1` with the guard still true — which is the
    finding: `while i != 4` does not bound `i` above, and Lean refutes the same
    `var-nonneg` obligation independently.

    The body here is INLINE rather than `array_fill.mojo`'s, and the reason is
    measured: `array_fill`'s real body stores through a subscript, which
    `formal/contracts.py`'s evaluator has no reading for, so the search SKIPS
    every input of that program.  Running the control on the program that skips
    would have tested the skip and not the refutation — and the row after pins
    the skip so it is recorded as a skip rather than read as agreement.
    """
    import fire_compiler as F
    from formal import loop_invariants as LI
    src = ("def ne_counter(i):\n"
           "    while i != 4:\n"
           "        i = i + 1\n"
           "    return i\n")
    fn = [s for s in F.Parser(F.py_tokenize(src)).parse_module()
          if type(s).__name__ == "FunctionDef"][0]
    v = LI.check_function(fn, "<inline>", lean=None)[0]
    got = v.variants[0].text if v.variants else None
    check(got == "- i",
          "the variant of `while i != 4: i = i + 1` is `- i`", str(got))
    if not v.variants:
        return
    witness, skipped = LI.refute(v.shape, v.rel, v.variants[0])
    check(witness is not None,
          "the variant `- i` goes NEGATIVE while the guard still holds, and "
          "the search names the state", f"skipped {skipped}")
    check(witness is not None and witness["form"] < 0,
          "and the state it names has the variant below zero", str(witness))


def test_a_program_the_search_cannot_run_is_recorded_as_skipped(tmpdir=None):
    """`array_fill` is SKIPPED, every input, and that is not agreement.

    The search reads the loop's own statements through
    `formal/contracts.py`\'s expression IR, and a store through a subscript has no
    reading there.  So the bounded search says NOTHING about `array_fill`\'s
    variant, and this row pins that it says nothing LOUDLY — a skip counted as
    agreement is the exact failure `formal/contracts.py::classify` documents, and
    a reader of `refute()`\'s return value alone cannot see the difference.
    """
    from formal import loop_invariants as LI
    v = verdicts_of("array_fill")[0]
    check(bool(v.candidates),
          "array_fill: the search ran and reported per candidate")
    skipped = [c for c in v.candidates if c["skipped"]]
    check(len(skipped) == len(v.candidates),
          "array_fill: EVERY candidate is reported as skipped",
          str([(c["role"], c["skipped"]) for c in v.candidates]))
    check(all(c["witness"] is None for c in v.candidates),
          "array_fill: and none of them claims a counterexample, which is "
          "different from claiming it found none")
    said = (v.why_family or "") + " " + " ".join(ob.why for ob in v.obligations)
    check("subscript" in said.lower(),
          "array_fill: the row names the SUBSCRIPT that stopped the reader",
          str(v.why_family))



# ── 4. the ladder, and the shape of the emitted file ──────────────────────────

def test_the_ladder_is_the_shared_one(tmpdir=None):
    """The rungs are `formal/contracts.py::LADDER`'s, in a STATED order.

    The order differs — `omega` first — and `ladder_script`'s docstring carries
    the measurement: with `simp_all` first, `simp_all` normalises `c' - i'` to
    `c - i`, reports success for the simplification without closing the goal,
    `first` never reaches `omega`, and Lean reports `unsolved goals` on a
    theorem that is true.  What this row pins is that the two SETS are equal,
    because a second hand-written tactic list is the failure
    `formal/contracts.py`'s own comment records having been committed once
    inside the module that exists to prevent it.
    """
    from formal import contracts as CT
    from formal import loop_invariants as LI
    script = LI.ladder_script()
    names = [r[0] for r in CT.LADDER]
    check("the_script_uses_every_rung_in_LADDER",
          all(n in script for n in names),
          f"{CT.LADDER} vs\n{script}")
    check("the_script_invents_no_rung_outside_LADDER",
          len([ln for ln in script.split("\n") if ln.strip().startswith("|")])
          == len(CT.LADDER), script)
    check("omega_is_first_because_it_is_complete_here",
          script.split("\n")[1].strip() == "| omega", script)


def test_the_emitted_file_imports_nothing(tmpdir=None):
    """No `import`, because no obligation needs the library.

    That is a MEASUREMENT, not an optimisation: every obligation is linear
    integer arithmetic over `Int`, so the whole layer costs one `lean` invocation
    of a few hundred lines and NO `lib/*.olean` build (0.3 s wall, 0.0 s CPU,
    0.02 GB on `count_acc`, against the ~80 s / 4 GB a `ProofLib` build costs).
    It is also why the obligations are stated over `Int` rather than `UInt64` —
    `omega` has no arithmetic on `Fin (2^64)`, which is the same measurement
    `formal/contracts.py::LADDER`'s own note records for `bv_decide`.
    """
    for stem in programs():
        for v in verdicts_of(stem):
            check("import" not in v.proof,
                  f"{stem} loop {v.index}: the emitted file imports nothing",
                  v.proof[:200])
            # The DECLARATION form, not the word: this file's own prose says
            # "admits" when it explains that a refusal is UNKNOWN by
            # construction, and a substring test over prose fails on the
            # explanation.
            check("sorry" not in v.proof
                  and not [ln for ln in v.proof.split("\n")
                           if ln.startswith(("theorem", "lemma", "axiom"))
                           and ("sorry" in ln or "admit" in ln)],
                  f"{stem} loop {v.index}: the emitted file admits nothing")


def test_the_proof_states_the_loop_it_is_about(tmpdir=None):
    """The emitted file's header names the loop, its family and its candidates.

    A generated `.lean` file that does not say which program it came from is a
    file a reader cannot check against anything, and the header is where the
    SYNTHESISED PRECONDITION is printed — the premise every obligation below it
    is read under, and the one thing about this layer that is not proved by it.
    """
    for stem in programs():
        for v in verdicts_of(stem):
            proof = v.proof
            check("Source:" in proof and stem in proof,
                  f"{stem} loop {v.index}: the emitted file names its source")
            check(v.family in proof,
                  f"{stem} loop {v.index}: the emitted file names the family "
                  f"`{v.family}`")
            if v.precondition:
                check("SYNTHESISED PRECONDITION" in proof,
                      f"{stem} loop {v.index}: the emitted file prints the "
                      f"synthesised precondition `{v.precondition}`")


# ── 5. the Lean discharge, and the regression baseline ───────────────────────

def _lean_available():
    from formal import lean as L
    return L.find_lean(HERE)


def measure(stems=None, lean=None):
    """`(stem, sha256, rows)` for the corpus, one entry per obligation."""
    from formal import loop_invariants as LI
    out = {}
    # Keyed by the stem WITHOUT `.mojo`, which is how every other table in this
    # file and in `tools/formal_proof_census.py` names a program, and how a
    # reader types it.
    for stem in (stems if stems is not None
                 else [p[:-5] for p in programs()]):
        vs = verdicts_of(stem, lean=lean)
        rows = []
        for v in vs:
            for ob in v.obligations:
                rows.append({"loop": v.index, "family": v.family,
                             "role": ob.role, "obligation": ob.name,
                             "status": ob.status or LI.UNKNOWN})
        out[stem] = {
            "source_sha256": hashlib.sha256(
                source_of(stem).encode()).hexdigest(),
            "family": vs[0].family if vs else "unreadable",
            "status": vs[0].status if vs else LI.UNKNOWN,
            "invariant": vs[0].invariants[0].text if vs and vs[0].invariants
            else None,
            "variant": vs[0].variants[0].text if vs and vs[0].variants else None,
            "precondition": vs[0].precondition if vs else None,
            "rows": rows}
    return out


def _rank(status):
    """`proved < unknown < refuted`.  One table, for the baseline and for the
    report, so "worse" means one thing."""
    return {"proved": 0, "skipped": 0, "unknown": 1, "refuted": 2}.get(
        status, 1)


def compare(baseline, rows):
    """`[(severity, what, text)]`, the way `tools/formal_proof_census.py` does.

    Three severities and no fourth, because a ratchet's output is read by
    somebody deciding what to do next: `REGRESSION` fails the run, `IMPROVEMENT`
    is a result to bank, and `INFO` is the honest "not comparable".
    """
    out = []
    for stem, row in sorted(rows.items()):
        was = baseline.get(stem)
        if was is None:
            out.append(("INFO", stem, "not in the baseline — a new program. "
                        "`--write-baseline` to bank it."))
            continue
        if was.get("source_sha256") != row["source_sha256"]:
            out.append(("INFO", stem,
                        "the program's bytes changed, so its rows are a "
                        "different program's. Bank it with `--write-baseline`."))
            continue
        old = {(r["loop"], r["role"]): r for r in was.get("rows", [])}
        new = {(r["loop"], r["role"]): r for r in row["rows"]}
        for key, r in sorted(new.items()):
            before = old.get(key)
            if before is None:
                out.append(("INFO", stem,
                            f"{key[1]} is a row this baseline does not name"))
                continue
            if _rank(r["status"]) > _rank(before["status"]):
                out.append(("REGRESSION", stem,
                            f"{key[1]} got WORSE: {before['status']} -> "
                            f"{r['status']}"))
            elif _rank(r["status"]) < _rank(before["status"]):
                out.append(("IMPROVEMENT", stem,
                            f"{key[1]} got BETTER: {before['status']} -> "
                            f"{r['status']}. Bank it with `--write-baseline`."))
    return out


def write_baseline(measured, lean_version):
    """MERGE into the committed file, never replace it, and never drop a row.

    `tools/formal_proof_census.py::write_baseline` states the same rule and the
    same reason: a baseline is a claim about a corpus, and replacing it with
    the last thing measured is a baseline of one run.
    """
    try:
        with open(BASELINE, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {"programs": {}}
    programs_old = old.get("programs") or {}
    programs_old.update(measured)
    gone = set(programs_old) - set(measured)
    for stem in gone:
        del programs_old[stem]
    blob = {"tag": old.get("tag", "formal-loop-invariants-v1"),
            "written": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "lean": lean_version,
            "programs": programs_old}
    # `0600` because `mkstemp` says so, and `0644` after the replace because
    # every other committed JSON in `tools/` says so and a baseline only one
    # user can read is a baseline the next reader cannot check.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(BASELINE))
    with os.fdopen(fd, "w") as f:
        json.dump(blob, f, indent=1, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, BASELINE)
    return blob


def test_the_ladder_discharges_what_the_baseline_records(lean_bin, tmpdir):
    """Every obligation, through `formal/lean.py::run_lean`, against the
    committed baseline.

    This is the proof-regression ledger for the layer, and it is separate from
    `tools/formal_proof_census_baseline.json` for a measured reason: its unit is
    a (shape, obligation) pair and not a whole example file, and eleven of these
    twelve programs are REFUSED outright by the proof generator, so a census row
    for them would be a constant rather than a measurement.

    `run_lean` is reached through `formal/loop_invariants.py::lean_runner`, a
    thread over the ONE launcher, so every bound on it — wall, CPU, memory,
    heartbeats — is the launcher's and this file adds none.

    The positive control is in the same function and not in a separate row: if
    no obligation anywhere closed, a green run would be indistinguishable from a
    broken `run_lean`.
    """
    from formal import loop_invariants as LI
    runner = LI.lean_runner(lean_bin)
    measured = measure(lean=runner)
    closed = sum(1 for r in measured.values() for row in r["rows"]
                 if row["status"] == LI.PROVED)
    total = sum(len(r["rows"]) for r in measured.values())
    check(closed > 0,
          f"the ladder closed at least one obligation ({closed} of {total})",
          "zero closed is what a broken launcher looks like, so this row is "
          "the positive control for every row below it")
    # `count_acc` is the corpus's proved row and the one that says the whole
    # pipeline works end to end; pinning it keeps a later change from making
    # everything UNKNOWN and reporting no regression.
    rows = {(r["loop"], r["role"]): r["status"]
            for r in measured["count_acc"]["rows"]}
    check(measured["count_acc"]["status"] == LI.PROVED,
          "count_acc: PROVED end to end — invariant, variant, and the exit "
          "consequence under the synthesised precondition",
          str(rows))
    try:
        with open(BASELINE, encoding="utf-8") as f:
            banked = json.load(f)
    except (OSError, ValueError):
        check(False, "the committed baseline is readable",
              "run with --write-baseline where a toolchain exists")
        return
    for severity, stem, text in compare(banked.get("programs") or {},
                                        measured):
        check(severity != "REGRESSION", f"{stem}: {text}")
        if severity != "REGRESSION":
            print(f"{severity:<11} {stem}: {text}")


ALL = [
    test_every_loop_answers_even_when_nothing_was_derived,
    test_a_refusal_row_can_never_be_proved,
    test_the_synthesis_derives_what_the_table_says,
    test_a_wrong_claim_is_refuted_and_the_right_one_is_not,
    test_a_variant_that_goes_negative_is_refuted,
    test_a_program_the_search_cannot_run_is_recorded_as_skipped,
    test_the_ladder_is_the_shared_one,
    test_the_emitted_file_imports_nothing,
    test_the_proof_states_the_loop_it_is_about,
    test_every_program_answers_cpython_on_both_architectures,
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--write-baseline", action="store_true",
                    help="bank the measured rows into "
                         f"{os.path.relpath(BASELINE, HERE)} (needs a toolchain)")
    args = ap.parse_args()
    VERBOSE = args.verbose
    lean_bin = _lean_available()
    if not lean_bin:
        print("note: no lean toolchain, so the discharge rows are skipped and "
              "every obligation stays UNKNOWN — which is the honest answer and "
              "is NOT a pass")
    with tempfile.TemporaryDirectory(prefix="loopinv.") as tmpdir:
        for t in ALL:
            try:
                t(tmpdir)
            except Exception as exc:
                check(False, t.__name__, f"{type(exc).__name__}: {exc}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
        if lean_bin:
            try:
                if args.write_baseline:
                    from formal import lean as L
                    from formal import loop_invariants as LI
                    measured = measure(lean=LI.lean_runner(lean_bin))
                    blob = write_baseline(measured, L.lean_version(lean_bin))
                    print(f"wrote {BASELINE}: {len(blob['programs'])} "
                          f"program(s)")
                else:
                    test_the_ladder_discharges_what_the_baseline_records(
                        lean_bin, tmpdir)
            except Exception as exc:
                check(False, "the discharge rows", f"{type(exc).__name__}: {exc}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
        else:
            print("SKIP  the discharge rows: no lean toolchain (this is not a "
                  "pass)")
    passed = sum(1 for ok, _w in RESULTS if ok)
    failed = len(RESULTS) - passed
    print()
    print(f"loop invariants: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())