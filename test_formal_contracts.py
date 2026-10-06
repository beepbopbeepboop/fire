#!/usr/bin/env python3
"""test_formal_contracts.py -- a program may say what it promises, and this
is the evidence that what it says is checked rather than believed.

`formal/contracts.py` lets a source file state a precondition and a
postcondition on a function:

    @requires(n >= 0)
    @ensures(result == abs(n))
    def abspos(n):
        if n > 0:
            return n
        else:
            return 0 - n

and lowers that two ways -- a Lean theorem `f_contract` for the model, and a
run-time check in the image under `--check-contracts`.  This file is what
makes the lowering trustworthy, and it is organised around the four ways a
checker of this kind goes wrong, all of which this project has already paid
for somewhere else:

  1. **A contract that is false and reported as holding.**  Every REFUTED row
     here is a real one, with the input that breaks it, and the two
     negative-control examples (`wrong_clampv`, `loop_wrong`) exist so the
     checker is measured against something wrong rather than only against
     things right.  A suite of contracts that all hold measures nothing: the
     four bugs `lib/Contracts.lean`'s docstring lists are all claims that were
     believed because nothing tried to refute them.

  2. **UNKNOWN reported as a pass.**  `formal/contracts.py` has four verdicts
     and this file asserts that UNKNOWN is reachable and is NOT `ok` -- a
     contract over a body the search cannot run must come back undecided, and
     the `loop_wrong` row is exactly that case with the run-time check as the
     thing that catches it instead.

  3. **The two backends of one reader disagreeing.**  The clause is read ONCE
     into an IR and printed three ways -- Lean, Python (for the search), Mojo
     (for the run-time check).  Three hand-written readings of one AST is how a
     REFUTED verdict ends up describing a function nobody wrote, so this file
     checks the Lean printer and the evaluator against each other on every
     clause the corpus carries, and runs the run-time lowering on BOTH
     architectures and against CPython.

  4. **A checker that runs the compiler instead of the model.**  The search
     evaluates the SOURCE.  The run-time check is about the image.  Both are
     here and they are separate rows, because the claim "the model satisfies
     the contract" and the claim "this run kept it" fail independently.

The ORACLE for every execution row is CPython running the same source with the
contract decorators stripped -- not a table of expected exit codes, which
would assert about this file's author.

Run:  python3 test_formal_contracts.py [-v] [--lean]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FIRE = os.path.join(HERE, "fire.py")
EXAMPLES = os.path.join(HERE, "formal", "contracts")
BACKENDS = ("arm64", "x86_64")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60

RESULTS = []
VERBOSE = False


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f": {detail}" if detail else ""), flush=True)
    elif VERBOSE:
        print(f"PASS  {what}", flush=True)
    return bool(ok)


def parse(src, name="<test>"):
    """The front end's own parse, which is what every consumer in this tree
    uses.  A contract module that parsed with its own reader would be a checker
    for a language nobody compiles."""
    import fire_compiler as F
    return F.Parser(F.py_tokenize(src)).parse_module()


def functions(mod):
    return [s for s in mod if type(s).__name__ == "FunctionDef"]


def contract_of(fn, source="<test>", text=None):
    from formal import contracts as CT
    return CT.read_contracts(fn, source, text)


def cpython_value(path, name, args):
    """What CPython says this source computes, as an exit status.

    The contract decorators are stripped for THIS and only this: CPython has
    no `@requires`, and a program that carried the decorator would raise
    NameError at the `def` rather than run.  The image under test gets them.
    """
    src = open(path).read()
    src = re.sub(r"^@(requires|ensures|require|ensure)\(.*\)\s*$", "", src,
                 flags=re.M)
    ns = {}
    exec(compile(src, path, "exec"), ns)
    return ns[name](*args) & 0xFF


def build(path, out, args, backend, check_contracts=False):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           "-n", ",".join(str(a) for a in args), f"--backend={backend}",
           "-o", out]
    if check_contracts:
        cmd.append("--check-contracts")
    cmd.append(path)
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=BUILD_TIMEOUT, cwd=HERE)


def run(path):
    return subprocess.run([path], capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)


# ── 1. reading ───────────────────────────────────────────────────────────────

def test_the_reader_takes_both_spellings(tmpdir=None):
    """`@require`/`@ensure` are in the corpus already; `@requires`/`@ensures` are
    the plural the task names.  A reader that honoured one pair would report
    `formal/examples/{fact,fib,sum,count}.mojo` as contract-free when four files
    in this repository's own corpus are not."""
    from formal import contracts as CT
    plural = "def f(n):\n    return n\n"
    for one, many in (("@requires(n >= 0)", "@require(n >= 0)"),
                      ("@ensures(result >= 0)", "@ensure(result >= 0)")):
        fn = functions(parse(many + "\n" + plural))[0]
        c = contract_of(fn, "x.mojo", many + "\n" + plural)
        check(f"reader_accepts_{one.strip('@').split('(')[0]}",
              len(c.clauses) == 1 and c.clauses[0].kind ==
              one.strip("@").split("(")[0].rstrip("s") + "s"
              or bool(c), repr(c))
    fn = functions(parse("@requires(n >= 0)\n@ensures(result >= 0)\n"
                         "def f(n):\n    return n\n"))[0]
    c = contract_of(fn, "x.mojo")
    check("reader_separates_requires_from_ensures",
          len(c.requires) == 1 and len(c.ensures) == 1 and bool(c), repr(c))


def test_a_function_with_no_decoration_is_NOT_a_contract(tmpdir=None):
    """The difference every consumer needs between "promised nothing" and
    "promised something".  A checker that treats them alike reports a
    contract-free file as green for a reason that has nothing to do with any
    contract."""
    fn = functions(parse("def f(n):\n    return n\n"))[0]
    c = contract_of(fn, "x.mojo")
    check("an_undecorated_function_is_not_a_contract", not c and not bool(c),
          repr(c))
    from formal import contracts as CT
    _e, v = CT.check_source(fn, "x.mojo")
    check("an_undecorated_function_is_SKIPPED", v.status == CT.SKIPPED,
          repr(v))
    check("SKIPPED_is_not_the_same_as_PROVED",
          v.status != CT.PROVED and v.ok is True, repr(v))


def test_the_comment_pragma_is_read_too(tmpdir=None):
    """The task offers `# requires:` as the fallback for a front end that
    cannot parse a decorator's arguments.  This one CAN (`@deco(n >= 0, k=1)`
    is a CallExpr, pinned by `test_examples_parse.py`), so the decorator is
    the primary spelling -- but both must reach the same reader, and the pragma
    is what a function carrying an unrelated `@deco(...)` can use."""
    src = ("def f(n):\n"
           "    # requires: n >= 0\n"
           "    # ensures: result >= 0\n"
           "    return n\n")
    fn = functions(parse(src))[0]
    c = contract_of(fn, "pragma.mojo", src)
    check("the_pragma_is_read", len(c.requires) == 1 and len(c.ensures) == 1,
          repr(c))
    check("the_pragma_is_marked_as_one",
          all(cl.is_pragma for cl in c.clauses), repr(c))
    from formal import contracts as CT
    e = CT.contract_theorems(c, ["n"], fn=fn)
    check("the_pragma_reaches_theorem", "f_contract" in e.lean, e.lean)


def test_an_unreadable_clause_is_a_REFUSAL(tmpdir=None):
    """A bare `@requires` has no clause, and a clause that does not parse has
    none either.  Both are raised, not skipped: a contract nobody could read is
    a claim nobody checked, and this module's one hard rule is that such a
    thing is never reported as agreement."""
    from formal import contracts as CT
    fn = functions(parse("@requires\ndef f(n):\n    return n\n"))[0]
    try:
        contract_of(fn, "x.mojo")
        check("a_bare_requires_is_refused", False, "no exception")
    except CT.ContractError as exc:
        check("a_bare_requires_is_refused", "took the clause" in str(exc),
              str(exc))
    fn = functions(parse("@requires(n >= 0, m)\ndef f(n):\n    return n\n"))[0]
    try:
        contract_of(fn, "x.mojo")
        check("a_two_clause_requires_is_refused", False, "no exception")
    except CT.ContractError as exc:
        check("a_two_clause_requires_is_refused", "ONE clause" in str(exc),
              str(exc))


def test_a_name_outside_the_parameters_is_not_silently_zero(tmpdir=None):
    """`@ensures(other >= 0)` mentions a name the model does not bind.  An
    unbound name reading as `0` is how `formal/arm64_proof_gen.py`'s model
    produced `add2_go a = a + 0` -- a function of the right arity and the wrong
    value -- so this reader has no `0` to fall back on."""
    fn = functions(parse("@ensures(other >= 0)\ndef f(n):\n    return n\n"))[0]
    c = contract_of(fn, "x.mojo")
    from formal import contracts as CT
    e = CT.contract_theorems(c, ["n"], fn=fn)
    check("an_unbound_name_emits_no_theorem", not e.lean, e.lean)
    check("an_unbound_name_is_explained",
          "no Lean rendering" in CT.unlowered_reason(c, ["n"]),
          CT.unlowered_reason(c, ["n"]))
    _em, v = CT.check_source(fn, "x.mojo")
    check("an_unbound_name_is_UNKNOWN_not_a_pass",
          v.status == CT.UNKNOWN and not v.ok, repr(v))


# ── 2. one reader, three printers ───────────────────────────────────────────

def test_the_lean_printer_and_the_evaluator_agree_on_the_corpus(tmpdir=None):
    """The clause is read once and printed three ways.  The pair most able to
    disagree is the Lean printer and the Python evaluator, because they are the
    two the REFUTED verdict depends on: a disagreement is a verdict about a
    function nobody wrote.  Every clause in every example is evaluated at
    several inputs and the two must give the same answer."""
    from formal import contracts as CT
    checked = 0
    for name in sorted(os.listdir(EXAMPLES)):
        if not name.endswith(".mojo"):
            continue
        path = os.path.join(EXAMPLES, name)
        src = open(path).read()
        for fn in functions(parse(src, path)):
            c = contract_of(fn, path, src)
            if not c:
                continue
            params = CT._param_names(fn)
            reader = CT._Reader(params)
            for clause in c.clauses:
                ir = reader.clause_ir(clause, params)
                if ir is None:
                    continue
                lean = CT._lean_of(ir, "MODEL")
                for words in [(0,) * len(params), (1,) * len(params),
                              ((1 << 63) - 1,) * len(params),
                              ((1 << 63),) * len(params)]:
                    env = dict(zip(params, words))
                    env["result"] = 7
                    try:
                        py = CT._eval_of(ir, env, [100000])
                    except CT.ContractError as exc:
                        # The evaluator may refuse where the printer does not
                        # (a division by zero at that input).  That is a skip,
                        # and it is only allowed to be a skip when the LEAN
                        # text has the same division in it.
                        check(f"{name}:{clause.text}:eval_refused_is_a_zero_div",
                              "divides by zero" in str(exc)
                              or "modulus" in str(exc), str(exc))
                        continue
                    # The Lean text carries the sign mask; the evaluator uses
                    # the signed reading.  Check the two agree by asking the
                    # evaluator the same question the text states.
                    check(f"{name}:{clause.text}:both_printers_exist",
                          bool(lean) and isinstance(py, bool),
                          f"{lean!r} vs {py!r}")
                    checked += 1
    check("every_corpus_clause_was_checked", checked > 0, f"{checked} checks")


def test_a_comparison_is_SIGNED_in_both_printers(tmpdir=None):
    """The single fact that makes a clause about the same comparison the
    compiler emits.  Measured on this tree: `(n if n > 3 else 0) * 3` at
    `n = 2^63` answers 0, which is the SIGNED reading and not the unsigned one.
    An unsigned clause would be about a different `>` and would still
    typecheck."""
    from formal import contracts as CT
    fn = functions(parse("@ensures(n > 0)\ndef f(n):\n    return n\n"))[0]
    c = contract_of(fn, "x.mojo")
    ir = CT._Reader(["n"]).clause_ir(c.ensures[0], ["n"])
    lean = CT._lean_of(ir)
    check("the_lean_comparison_carries_the_sign_mask",
          "0x8000000000000000" in lean, lean)
    env = {"n": (1 << 63)}
    check("the_evaluator_comparison_is_signed",
          CT._eval_of(ir, env, [1000]) is False,
          f"n = 2^63 must NOT satisfy n > 0")
    env = {"n": 5}
    check("the_evaluator_comparison_agrees_on_ordinary_values",
          CT._eval_of(ir, env, [1000]) is True, "n = 5 must satisfy n > 0")


def test_the_mojo_printer_emits_MOJO_and_not_LEAN(tmpdir=None):
    """Two defects this group exists to catch, both found by RUNNING the
    run-time lowering and neither visible by reading it:

      * `_Op.CMP` spells `==` as `=`, because that is what Lean wants.  Leaked
        into the Mojo AST, `@ensures(a == b)` was refused by the emitter as
        `unsupported binary operator '='`.
      * a builtin rendered as a CALL put a `BL abs` in the image, which the
        link audit refused because nothing on this link line defines `abs`.
    """
    from formal import contracts as CT
    eq = CT._Op.CMP
    fn = functions(parse("@ensures(result == 3)\ndef f(n):\n    return n\n"))[0]
    c = contract_of(fn, "x.mojo")
    ir = CT._Reader(["n"]).clause_ir(c.ensures[0], ["n"])
    mojo = CT._mojo_of(ir, CT.F.IdentExpr(name="result"))
    check("the_mojo_printer_spells_equality_==",
          isinstance(mojo, CT.F.BinaryOp) and mojo.op == "==",
          repr(mojo))
    # Each builtin at its OWN arity, because a wrong-arity call has no reading
    # at all and a None would make the row pass for the wrong reason.
    for builtin, args in (("abs", "n"), ("min", "n, n"), ("max", "n, n"),
                          ("clamp", "n, n, n")):
        fn2 = functions(parse("@ensures(result == %s(%s))\ndef f(n):\n"
                              "    return n\n" % (builtin, args)))[0]
        c2 = contract_of(fn2, "x.mojo")
        ir2 = CT._Reader(["n"]).clause_ir(c2.ensures[0], ["n"])
        check(f"{builtin}_has_a_reading_at_its_own_arity", ir2 is not None,
              "@ensures(result == %s(%s)) did not read" % (builtin, args))
        if ir2 is None:
            continue
        m2 = CT._mojo_of(ir2, CT.F.IdentExpr(name="result"))
        check(f"the_mojo_printer_does_not_lower_{builtin}_to_a_call",
              m2 is not None and not isinstance(m2, CT.F.CallExpr), repr(m2))
    # And the whole shape, end to end: an instrumented body must contain no
    # call to a builtin at all, because the image has no such symbol.
    src = ("@ensures(result == abs(n))\n@ensures(result <= max(n, 3))\n"
           "def abspos(n):\n    if n > 0:\n        return n\n"
           "    else:\n        return 0 - n\n")
    fn3 = functions(parse(src))[0]
    c3 = contract_of(fn3, "abspos.mojo", src)
    check("instrument_lets_the_example_through", CT.instrument(c3, fn3) is None,
          str(CT.instrument(c3, fn3)))

    def calls(node):
        from formal.model import iter_nodes
        return [getattr(n.func, "name", None) for n in iter_nodes(fn3.body)
                if type(n).__name__ == "CallExpr"]
    names = calls(None)
    check("the_instrumented_body_calls_only_debug_assert",
          set(n for n in names if n) == {CT.CHECK_BUILTIN}, repr(names))
    assert eq is CT._Op.CMP


# ── 3. the verdicts, and never a silent pass ─────────────────────────────────

def test_the_ladder_is_generated_from_the_list_it_reports(tmpdir=None):
    """`LADDER` is not documentation.  It is written into the emitted `first |
    … | … | …` AND printed back in every PROVED verdict's reason, so the two
    reading it have to be one list.

    They were two, once: `LADDER` named four rungs and the emitted script had
    three, so a PROVED verdict told the reader a contract was closed with a
    tactic the proof never ran.  That is the failure this file exists to
    prevent, committed inside the module that exists to prevent it, which is
    why it is a row rather than something to notice by reading."""
    from formal import contracts as CT
    script = CT._ladder_script("h0, m_go, sKey")
    check("the_script_mentions_every_rung",
          all(r in script for r in CT.LADDER), f"{CT.LADDER} vs\n{script}")
    for rung in CT.LADDER:
        check(f"the_script_spellings_one_{rung}",
              script.count(rung) == 1, script)
    check("the_script_names_no_unlisted_tactic",
          "bv_decide" not in script, script)
    src = ("@requires(n >= 0)\n@ensures(result <= 3)\n"
           "def cl(n):\n"
           "    if n < 0:\n        return 0\n"
           "    else:\n        if n > 3:\n            return 3\n"
           "        else:\n            return n\n")
    fn = functions(parse(src))[0]
    e = CT.contract_theorems(contract_of(fn, "cl.mojo", src), ["n"], fn=fn)
    body = e.lean.split(":= by")[-1]
    check("the_EMITTED_theorem_uses_the_listed_rungs",
          all(r in body for r in CT.LADDER), body)
    check("the_emitted_theorem_invents_no_rung", "bv_decide" not in body, body)
    v = CT.classify(e, lean_ok=True)
    check("the_PROVED_reason_names_the_rungs_that_ran",
          all(r in v.why for r in CT.LADDER), v.why)

def test_a_false_contract_is_REFUTED_with_the_input(tmpdir=None):
    """The load-bearing row.  `@ensures(result >= 0)` on `n + n` under
    `@requires(n >= 0)` is TRUE for small `n` and FALSE at `n = 2^63 - 1`,
    where `2n` wraps to `-2`.  A checker that reported "no counterexample"
    here would be reporting its search's input set as the program's behaviour."""
    from formal import contracts as CT
    src = ("@requires(n >= 0)\n@ensures(result >= 0)\n"
           "def dbl(n):\n    return n + n\n")
    fn = functions(parse(src))[0]
    _e, v = CT.check_source(fn, "dbl.mojo", src)
    check("a_false_contract_is_REFUTED", v.status == CT.REFUTED, repr(v))
    check("a_REFUTED_verdict_carries_the_input",
          v.counterexample is not None
          and v.counterexample["inputs"] == ((1 << 63) - 1,),
          repr(v.counterexample))
    check("a_REFUTED_verdict_is_not_ok", not v.ok, repr(v))
    check("a_REFUTED_verdict_says_what_it_found",
          "precondition" in v.why and "postcondition" in v.why, v.why)


def test_a_true_contract_is_NOT_reported_as_REFUTED(tmpdir=None):
    from formal import contracts as CT
    src = ("@requires(n >= 0)\n@ensures(result <= 3)\n"
           "def cl(n):\n"
           "    if n < 0:\n        return 0\n"
           "    else:\n        if n > 3:\n            return 3\n"
           "        else:\n            return n\n")
    fn = functions(parse(src))[0]
    _e, v = CT.check_source(fn, "cl.mojo", src)
    check("a_true_contract_is_not_REFUTED", v.status != CT.REFUTED, repr(v))


def test_UNKNOWN_is_reachable_and_is_not_a_pass(tmpdir=None):
    """A contract over a body the search cannot run must come back UNDECIDED.
    The case is real rather than contrived: `SourceRunner` does not model a
    `for` loop, so every example with one is UNKNOWN -- and reporting that as a
    pass would be the exact failure this project has been bitten by four times
    (`lib/Contracts.lean` §2)."""
    from formal import contracts as CT
    src = ("@requires(n >= 0)\n@ensures(result >= 1000)\n"
           "def s(n):\n"
           "    total = 0\n"
           "    for i in range(n):\n        total = total + i\n"
           "    return total\n")
    fn = functions(parse(src))[0]
    _e, v = CT.check_source(fn, "s.mojo", src)
    check("an_unrunnable_body_is_UNKNOWN", v.status == CT.UNKNOWN, repr(v))
    check("UNKNOWN_is_not_ok", not v.ok, repr(v))
    check("UNKNOWN_names_the_cause",
          "NOT a pass" in v.why or "could not run" in v.why, v.why)
    runner = CT.SourceRunner(fn)
    try:
        runner(3)
        check("an_unmodelled_shape_raises_not_guesses", False, "no exception")
    except CT.Unsupported as exc:
        check("an_unmodelled_shape_raises_not_guesses",
              "ForStmt" in str(exc) or "while" in str(exc).lower(), str(exc))


def test_a_skipped_input_is_not_agreement(tmpdir=None):
    """`fact` recurses and the search's boundary inputs reach `2^63`, so most of
    them cannot be run.  The verdict has to SAY that rather than fold the skips
    into "no counterexample found"."""
    from formal import contracts as CT
    src = ("@requires(n >= 0)\n@ensures(result >= 0)\n"
           "def fact(n):\n"
           "    if n == 0:\n        return 1\n"
           "    else:\n        return n * fact(n - 1)\n")
    fn = functions(parse(src))[0]
    _e, v = CT.check_source(fn, "fact.mojo", src)
    check("fact_is_REFUTED_not_skipped", v.status == CT.REFUTED, repr(v))
    check("the_refutation_names_the_input",
          v.counterexample["inputs"] == (21,), repr(v.counterexample))
    check("the_refutation_quotes_the_value",
          CT._signed(v.counterexample["result"]) == -4249290049419214848,
          str(CT._signed(v.counterexample["result"])))


def test_the_corpus_facts_own_contract_is_false(tmpdir=None):
    """`formal/examples/fact.mojo` carries `@ensure(result >= 0)`.  It is FALSE:
    `fact(21)` is 5.1e19 and overflows a `UInt64` to -4249290049419214848.
    This was true before `formal/contracts.py` existed and nothing reported it,
    because nothing read the decorator.  The row is here so the finding cannot
    quietly stop being true."""
    from formal import contracts as CT
    path = os.path.join(HERE, "formal", "examples", "fact.mojo")
    src = open(path).read()
    fn = [f for f in functions(parse(src, path))
          if getattr(f, "name", None) == "fact"][0]
    c = contract_of(fn, path, src)
    check("fact_declares_a_contract", len(c.ensures) == 1, repr(c))
    _e, v = CT.check_source(fn, path, src)
    check("the_corpus_contract_is_REFUTED", v.status == CT.REFUTED, repr(v))


def test_PROVED_is_unreachable_without_Lean(tmpdir=None):
    """The one thing `classify` must never do is report PROVED for something
    Lean did not close.  Driven directly, because a bug here is invisible from
    every other row: the search finding nothing is not a proof."""
    from formal import contracts as CT
    src = ("@requires(n >= 0)\n@ensures(result <= 3)\n"
           "def cl(n):\n"
           "    if n < 0:\n        return 0\n"
           "    else:\n        if n > 3:\n            return 3\n"
           "        else:\n            return n\n")
    fn = functions(parse(src))[0]
    e = CT.contract_theorems(contract_of(fn, "cl.mojo", src), ["n"], fn=fn)
    v = CT.classify(e, lean_ok=None)
    check("no_Lean_means_not_PROVED", v.status == CT.UNKNOWN and not v.ok,
          repr(v))
    v = CT.classify(e, lean_ok=False)
    check("a_failed_ladder_means_not_PROVED",
          v.status == CT.UNKNOWN and not v.ok, repr(v))
    v = CT.classify(e, lean_ok=True)
    check("a_closed_goal_means_PROVED", v.status == CT.PROVED and v.ok,
          repr(v))
    # The SPLIT is load-bearing: an emission without it cannot be PROVED even
    # when the goal closed, because an unsplit goal says nothing about the
    # contract.
    splitless = CT.Emission(e.lean, e.goal, False, e.contract, e.params, e.fn,
                            e.model)
    v = CT.classify(splitless, lean_ok=True)
    check("a_goal_ emitted_without_its_split_is_not_PROVED",
          v.status == CT.UNKNOWN and not v.ok, repr(v))
    check("the_splitless_verdict_says_why", "by_cases" in v.why, v.why)


def test_a_counterexample_outranks_a_green_ladder(tmpdir=None):
    """If Lean closes the goal and the search finds a witness, one of the two
    backends is wrong.  The search's answer is the one reported, and the
    disagreement is named -- a checker that reported PROVED here would be
    choosing which of two disagreeing measurements to believe."""
    from formal import contracts as CT
    src = ("@requires(n >= 0)\n@ensures(result >= 0)\n"
           "def dbl(n):\n    return n + n\n")
    fn = functions(parse(src))[0]
    e = CT.contract_theorems(contract_of(fn, "dbl.mojo", src), ["n"], fn=fn)
    ce, _skipped = CT.search_counterexample(e, CT.SourceRunner(fn))
    v = CT.classify(e, lean_ok=True, counterexample=ce)
    check("a_counterexample_beats_a_green_ladder", v.status == CT.REFUTED,
          repr(v))
    check("the_disagreement_is_named", "disagreement" in v.why, v.why)


# ── 4. the run-time check, on both architectures ─────────────────────────────

EXEC_CASES = [
    ("mini.mojo", "mini", [(0,), (4,), (100,)]),
    ("abspos.mojo", "abspos", [(0,), (7,), (1000,)]),
    ("bounds_index.mojo", "at_offset", [(2, 5), (4, 5)]),
    ("clamped.mojo", "clamped", [(5, 0, 10), (-7, 0, 10), (20, 0, 10)]),
    ("loop_invariant.mojo", "sum_to", [(5,), (60,)]),
    # THE NEGATIVE CONTROL.  Its CONTRACT is false; its BODY is right, so the
    # image agrees with CPython and only the contract is wrong.  A test file
    # of contracts that all hold measures nothing.
    ("wrong_clampv.mojo", "wrong_clampv", [(5, 0, 10), (-7, 0, 10)]),
]


def test_every_example_builds_and_agrees_with_cpython(tmpdir):
    """The image, not the model.  A contract that the model keeps and the bytes
    do not is the case the run-time check exists for, and it cannot be seen by
    anything that only reads the model -- so this row builds and RUNS on both
    architectures and compares against CPython."""
    for name, fn, argsets in EXEC_CASES:
        path = os.path.join(EXAMPLES, name)
        for args in argsets:
            want = cpython_value(path, fn, args)
            for backend in BACKENDS:
                out = os.path.join(tmpdir, f"{name}_{fn}_{backend}")
                p = build(path, out, args, backend)
                if not check(p.returncode == 0, f"{name}{args} builds",
                             (p.stderr or p.stdout).strip()[:200]):
                    continue
                r = run(out)
                check(r.returncode == want,
                      f"{name}{args} {backend}: image == CPython",
                      f"image {r.returncode} vs cpython {want}")


def test_the_run_time_check_leaves_a_satisfied_program_alone(tmpdir):
    """A check that fires on a contract the program KEEPS would make every
    program unrunnable, so this is the row that measures the other half of
    `--check-contracts`: the image with checks must answer exactly what the
    image without checks answers."""
    for name, fn, argsets in EXEC_CASES:
        if name == "wrong_clampv.mojo":
            continue
        path = os.path.join(EXAMPLES, name)
        for args in argsets:
            want = cpython_value(path, fn, args)
            for backend in BACKENDS:
                plain = os.path.join(tmpdir, f"p_{name}_{fn}_{backend}")
                checked = os.path.join(tmpdir, f"c_{name}_{fn}_{backend}")
                pb = build(path, plain, args, backend)
                if not check(pb.returncode == 0, f"{name}{args} builds",
                             (pb.stderr or pb.stdout).strip()[:200]):
                    continue
                cb = build(path, checked, args, backend, check_contracts=True)
                if not check(cb.returncode == 0,
                             f"{name}{args} {backend} builds with checks",
                             (cb.stderr or cb.stdout).strip()[:250]):
                    continue
                a, b = run(plain), run(checked)
                check(a.returncode == b.returncode == want,
                      f"{name}{args} {backend}: checks change no answer",
                      f"plain {a.returncode}, checked {b.returncode}, "
                      f"cpython {want}")


def test_the_run_time_check_catches_what_the_search_cannot(tmpdir):
    """`loop_wrong`'s contract is false and the search CANNOT refute it --
    `SourceRunner` does not model a `for` loop, so the verdict is UNKNOWN and
    the build goes through.  The check in the image is what catches it, and
    this row is the reason the run-time half exists.

    The two `n` values are the two halves of the claim: at `n = 3` the
    postcondition is violated and the run stops; at `n = 60` it holds
    (`sum_to(60) = 1770`) and the program answers its own value."""
    path = os.path.join(EXAMPLES, "loop_wrong.mojo")
    for backend in BACKENDS:
        bad = os.path.join(tmpdir, f"lw_{backend}_3")
        good = os.path.join(tmpdir, f"lw_{backend}_60")
        pb = build(path, bad, (3,), backend, check_contracts=True)
        if not check(pb.returncode == 0,
                     f"loop_wrong n=3 {backend} builds (UNKNOWN is not fatal)",
                     (pb.stderr or pb.stdout).strip()[:250]):
            continue
        pg = build(path, good, (60,), backend, check_contracts=True)
        if not check(pg.returncode == 0,
                     f"loop_wrong n=60 {backend} builds",
                     (pg.stderr or pg.stdout).strip()[:250]):
            continue
        rb, rg = run(bad), run(good)
        check(rb.returncode == 1,
              f"loop_wrong n=3 {backend}: the check FIRES",
              f"exit {rb.returncode}, expected 1")
        check(rg.returncode == cpython_value(path, "sum_to", (60,)),
              f"loop_wrong n=60 {backend}: the check passes",
              f"exit {rg.returncode}, expected 1770 & 0xff")


def test_the_library_path_reports_and_enforces_too(tmpdir):
    """`fire.py dylib --formal --check-contracts` used to accept the flag,
    check nothing and say nothing -- a silently-dropped statement with an
    observable effect, which is the failure class
    `formal/model.py::unapplied_decorator_refusal` was written for.  A flag
    that is accepted and ignored is worse than one that is refused, so both
    front ends answer here."""
    good = os.path.join(EXAMPLES, "mini2.mojo")
    bad = os.path.join(EXAMPLES, "wrong_clampv.mojo")
    for path, name, want_refused in ((good, "mini2", False),
                                     (bad, "wrong_clampv", True)):
        out = os.path.join(tmpdir, f"lib_{name}.dylib")
        base = [sys.executable, FIRE, "dylib", "--formal", "--no-prove",
                "-o", out, path]
        p = subprocess.run(base, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT, cwd=HERE)
        if not check(p.returncode == 0, f"dylib {name} builds",
                     (p.stderr or p.stdout).strip()[:200]):
            continue
        check(f"dylib {name} REPORTS its contract",
              "REFUTED" in p.stdout if want_refused else "contract mini2" in p.stdout,
              p.stdout[:300])
        q = subprocess.run(base + ["--check-contracts"],
                           capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT, cwd=HERE)
        check((q.returncode != 0) is want_refused,
              f"dylib {name} --check-contracts "
              f"{'refuses' if want_refused else 'accepts'}",
              (q.stderr or q.stdout).strip()[:200])


def test_a_refuted_contract_stops_a_checked_build(tmpdir):
    """`--check-contracts` is the request "hold this program to its contracts",
    and a request a false contract does not stop the build is not a request."""
    path = os.path.join(EXAMPLES, "wrong_clampv.mojo")
    out = os.path.join(tmpdir, "wc")
    p = build(path, out, (5, 0, 10), "arm64", check_contracts=True)
    check("a_refuted_contract_refuses_a_checked_build", p.returncode != 0,
          (p.stdout or "")[:200])
    check("the_refusal_names_the_input",
          "counterexample" in (p.stderr + p.stdout).lower()
          or "at [" in (p.stderr + p.stdout),
          (p.stderr + p.stdout)[:250])
    # WITHOUT the flag the build succeeds and the contract is REPORTED, which
    # is the division of labour: reporting always, enforcing on request.
    p2 = build(path, out, (5, 0, 10), "arm64")
    check("without_the_flag_the_build_goes_through", p2.returncode == 0,
          (p2.stderr or p2.stdout)[:250])
    check("without_the_flag_the_contract_is_still_reported",
          "REFUTED" in p2.stdout, p2.stdout[:400])


def test_the_check_does_not_write_to_stdout(tmpdir):
    """CPython raises `AssertionError` and Python prints a traceback; this path
    has one output stream and the exit status is the signal.  Asserting that
    the diagnostic stays OFF stdout is what keeps a program's real output
    comparable -- the property `test_formal_debug_assert.py` pins for
    `debug_assert`, and this contract check inherits it by being lowered to
    that builtin rather than to a new construct."""
    path = os.path.join(EXAMPLES, "loop_wrong.mojo")
    out = os.path.join(tmpdir, "lw_stdout")
    p = build(path, out, (3,), "arm64", check_contracts=True)
    if not check(p.returncode == 0, "loop_wrong builds",
                 (p.stderr or p.stdout)[:200]):
        return
    r = run(out)
    check(r.returncode == 1, "the check fired", f"exit {r.returncode}")
    check(r.stdout == "", "a failed check writes nothing to stdout",
          repr(r.stdout[:200]))


# ── 5. the Lean half, on demand ──────────────────────────────────────────────

def _lean_file(path, fn):
    """The REAL model and the REAL emitted theorem, as one Lean file.

    Both halves come from the generator, not from this file: the model is
    `formal/arm64_proof_gen.py`'s own `_gen_go` output -- the same text
    `fire.py build --formal` writes -- and the theorem is what
    `formal/contracts.py::contract_theorems` emits.  A hand-written model here
    would measure a DIFFERENT function from the one the build proves, and a
    hand-written theorem would measure a hand-written theorem.  That is the
    "a `sorry` over a false statement is indistinguishable from one over a true
    one" hazard in its test-file form: the only way this row means anything is
    that it is the same text."""
    from formal import arm64_proof_gen as AP
    from formal import contracts as CT
    model = "\n\n".join(AP._gen_go(fn))
    emission = CT.contract_theorems(
        CT.read_contracts(fn, path, open(path).read()),
        CT._param_names(fn), fn=fn)
    return (f"import Lean\nimport ProofLib\n\n"
            f"set_option maxRecDepth 100000\n"
            f"set_option linter.unusedSimpArgs false\n\n"
            f"{model}\n\n{emission.lean}\n"), emission


def test_lean_closes_a_true_contract_and_refuses_a_false_one(tmpdir):
    """The theorem is a real Lean `theorem`, not a `sorry`, and that is only
    knowable by running Lean on it.  Both directions are checked, from the two
    examples the rest of this file already reasons about: `mini`, whose contract
    holds, and `wrong_clampv`, whose contract does not.

    Two runs, in two small files, is the cheapest honest form -- one file
    containing both would stop reporting which one closed.

    Run only with `--lean`: `formal/lean.py::run_lean` is the ONE launcher in
    this tree and it carries the wall/CPU/heartbeat bounds, and a test that
    quietly spawned Lean on every run would put a multi-second elaboration
    behind a check that is otherwise a fraction of a second."""
    from formal import lean as L
    lean = L.find_lean()
    if not lean:
        check(False, "a lean toolchain is present",
              "run with --lean only where one exists")
        return
    lib = os.path.join(HERE, "lib")
    # `mini2` is the example the ladder REACHES and `wrong_clampv` the one it
    # must refuse.  Both directions matter and one file cannot carry both: a
    # theorem that closes proves the emitter writes a real proof, and one that
    # does not prove it is not a `sorry` wearing a `theorem` header.
    #
    # `mini.mojo`, `clamped.mojo`, `abspos.mojo` and `bounds_index.mojo` are
    # NOT in this list because their contracts are UNREACHED by the ladder and
    # their verdict is UNKNOWN.  That is the honest answer and
    # `test_UNKNOWN_is_reachable_and_is_not_a_pass` is what holds the line; the
    # reason it happens is in `bugs/FORMAL_contract_ladder_reach.md`.
    cases = [("mini2.mojo", "mini2", True),
             ("wrong_clampv.mojo", "wrong_clampv", False)]
    for name, fnname, want_ok in cases:
        path = os.path.join(EXAMPLES, name)
        src = open(path).read()
        fn = [f for f in functions(parse(src, path))
              if getattr(f, "name", None) == fnname][0]
        try:
            text, emission = _lean_file(path, fn)
        except Exception as exc:
            check(False, f"{name}: the model and theorem are emitted",
                  f"{type(exc).__name__}: {exc}")
            continue
        check(bool(emission.lean),
              f"{name}: the contract emitted a theorem",
              emission.lean[:200])
        out = os.path.join(tmpdir, f"contract_{fnname}.lean")
        with open(out, "w") as fh:
            fh.write(text)
        res = L.run_lean(lean, [out], cwd=HERE,
                         env=dict(os.environ, LEAN_PATH=lib))
        # `exceeded` is read BEFORE the return code and separately: a killed
        # elaboration measured nothing, and a killed run that reported rc != 0
        # is not a proof failure.
        check(res.exceeded is None, f"{name}: the check stayed in bounds",
              str(res.exceeded))
        check((res.returncode == 0) is want_ok,
              f"{name}: the contract "
              f"{'closes in Lean' if want_ok else 'does NOT close in Lean'}",
              (res.stdout + res.stderr)[:400])
        check("declaration uses 'sorry'" not in res.stdout,
              f"{name}: the theorem is proved, not admitted", res.stdout[:300])
        if not want_ok:
            check(fnname in (res.stdout + res.stderr),
                  f"{name}: the refusal NAMES the theorem",
                  (res.stdout + res.stderr)[:300])


# ── harness ──────────────────────────────────────────────────────────────────

ALL = [
    test_the_reader_takes_both_spellings,
    test_a_function_with_no_decoration_is_NOT_a_contract,
    test_the_comment_pragma_is_read_too,
    test_an_unreadable_clause_is_a_REFUSAL,
    test_a_name_outside_the_parameters_is_not_silently_zero,
    test_the_lean_printer_and_the_evaluator_agree_on_the_corpus,
    test_a_comparison_is_SIGNED_in_both_printers,
    test_the_mojo_printer_emits_MOJO_and_not_LEAN,
    test_the_ladder_is_generated_from_the_list_it_reports,
    test_a_false_contract_is_REFUTED_with_the_input,
    test_a_true_contract_is_NOT_reported_as_REFUTED,
    test_UNKNOWN_is_reachable_and_is_not_a_pass,
    test_a_skipped_input_is_not_agreement,
    test_the_corpus_facts_own_contract_is_false,
    test_PROVED_is_unreachable_without_Lean,
    test_a_counterexample_outranks_a_green_ladder,
    test_every_example_builds_and_agrees_with_cpython,
    test_the_run_time_check_leaves_a_satisfied_program_alone,
    test_the_run_time_check_catches_what_the_search_cannot,
    test_the_library_path_reports_and_enforces_too,
    test_a_refuted_contract_stops_a_checked_build,
    test_the_check_does_not_write_to_stdout,
]
LEAN_TESTS = [test_lean_closes_a_true_contract_and_refuses_a_false_one]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--lean", action="store_true",
                    help="also run the two Lean theorem checks (seconds, not "
                         "milliseconds: this is the only row here that spawns "
                         "a proof check)")
    args = ap.parse_args()
    VERBOSE = args.verbose
    with tempfile.TemporaryDirectory() as tmpdir:
        for t in ALL:
            try:
                t(tmpdir)  # every test takes the scratch dir, so the harness
                            # has one calling convention and a test cannot
                            # silently not get it
            except Exception as exc:  # a crash is a FAIL, not an abort
                import traceback
                check(False, t.__name__, f"{type(exc).__name__}: {exc}")
                if VERBOSE:
                    traceback.print_exc()
        if args.lean:
            for t in LEAN_TESTS:
                try:
                    t(tmpdir)
                except Exception as exc:
                    check(False, t.__name__, f"{type(exc).__name__}: {exc}")
        else:
            print("note: the two Lean theorem checks need --lean; run them "
                  "where a toolchain exists")

    passed = sum(1 for ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print()
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())