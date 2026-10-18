#!/usr/bin/env python3
"""Regression tests for the SPECIFICATION REFINEMENT layer
(`lib/Specs.lean` + `formal/specs.py` + the `@refines(...)` annotation).

    python3 test_formal_specs.py [-v]

## What is being tested, and why this file exists at all

Every generated proof in this tree compares the machine with `mojo`, the
generator's own model of the source, and `mojo` is derived from the same source
by the same front end.  That is a self-consistency theorem and it is the best
claim the tree could make until now.  `lib/Specs.lean` is the other side of the
question — reference definitions written by hand in Lean's own `Nat`/`Int`/
`List` — and `@refines(Specs.fib64; 64)` is what makes a program ask to be
checked against one.

A layer like that can fail in three ways, and only one of them is a compiler
bug:

  1. **the annotation is not read**, so nothing is emitted and the file still
     typechecks.  Silent, and the reason `an_unannotated_program_is_unchanged`
     and `every_annotated_example_names_a_spec_that_exists` exist.
  2. **the annotation is read but ignored**, so a program asks for a check and
     gets none.  Also silent.  `the_emitter_writes_the_two_theorems` pins that
     the theorems are in the file.
  3. **the specification is wrong and is believed.**  This is the one that
     matters, and the only instrument that can see it is a build that FAILS on
     a wrong specification: `a_wrong_specification_is_rejected`.  A refinement
     layer with no negative control is a layer nobody knows the sign of.

So the file is deliberately weighted towards the negative control and towards
the cheap text-level checks (every annotated example in `formal/examples/`
names a specification that exists in `lib/Specs.lean`), and it runs exactly ONE
end-to-end build-plus-Lean per direction — the right specification and the
wrong one — because each of those is a whole `fire.py build --formal`.

## The cheap ones are the ones that would rot

`lib/Specs.lean` and `formal/examples/*.mojo` are edited by hand in different
commits, so "the example names a spec" is a fact about two files and can go
stale silently: a spec renamed in one, the annotation not following.  That is a
text check and it runs in milliseconds, so it runs every time.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_formal_dylib import TestFailure, check  # noqa: E402  (one failure type)

FIRE = os.path.join(HERE, "fire.py")
LIB = os.path.join(HERE, "lib")
EXAMPLES = os.path.join(HERE, "formal", "examples")
SPECS_LEAN = os.path.join(LIB, "Specs.lean")

from formal import specs as SPECS                # noqa: E402


# ---------------------------------------------------------------------------
# the library
# ---------------------------------------------------------------------------

def spec_definitions() -> set:
    """Every public name `lib/Specs.lean` declares, from the source.

    Read from the FILE and not by importing Lean, so a check that runs in
    milliseconds can still see a specification that exists.  A name inside
    `namespace Specs` is written `Specs.foo` in an annotation, so that is the
    form returned.
    """
    from formal import admitted as A
    with open(SPECS_LEAN, encoding="utf-8") as f:
        code = A.lean_code_regions(f.read())
    names = set()
    for _line, name, public, _kind in A._declarations(code):
        if public:
            names.add(name)
            names.add(f"Specs.{name}")
    return names


def test_the_specification_library_has_no_holes_and_no_axioms(tmpdir, shared):
    """`lib/Specs.lean` is built and Lean's own census answers zero holes.

    A specification layer with a `sorry` in it is a layer whose specifications
    are partly assumptions, and this is the only assertion in the file that
    measures the elaborated form rather than the text — `library_census` asks
    Lean what admits a hole in each module, which is not the same question as
    counting the word `sorry`.
    """
    from formal.lean import find_lean, ensure_library, library_census
    lean = find_lean(HERE)
    if not lean:
        print("    SKIP: no lean found (the library is not elaborated)")
        return
    ensure_library(lean, LIB)
    census = library_census(lean, LIB)
    check("Specs" in census,
          f"lib/Specs.lean was not built or not censused: the census names "
          f"{sorted(census)}. `formal/lean.py::LIBRARY_MODULES` is what puts a "
          f"module in front of both the `.olean` build and this census, so a "
          f"module missing from it is a module nothing checks")
    n_sorries, names = census["Specs"]
    check(n_sorries == 0,
          f"lib/Specs.lean admits {n_sorries} hole(s) — {list(names)[:6]} — and "
          f"a specification whose own proof is a hole is a claim about a claim")


def _elaborate_proof_lib_snippet(text: str, stem: str, tmpdir: str):
    """Write a `ProofLib`-importing `.lean` file and run Lean on it.

    `(ok, detail)`, or `(None, None)` when there is no Lean to run.  A text pin
    can see that a lemma is PRESENT; only an elaboration can see that it is
    PROVABLE, which is the distinction that matters for a library fact whose
    whole purpose is to be applied in a proof that has not been written yet.
    `check_proof_cached` runs `ensure_library` first, so a stale `.olean` is
    rebuilt rather than recompiled inside the checker.
    """
    from formal.lean import find_lean, check_proof_cached
    if not find_lean(HERE):
        return None, None
    path = os.path.join(tmpdir, stem + ".lean")
    with open(path, "w") as f:
        f.write(text)
    ok, detail, _cached, _n = check_proof_cached(path, repo_root=HERE)
    return ok, detail


def test_the_all_inputs_refinement_has_its_multiplication_lemma(tmpdir, shared):
    """`u64_ofNat_mul` is in the library, states the analogue of `u64_ofNat_add`,
    and proves.

    The layer's refinement is stated over a FINITE `List.range N` because the
    ALL-INPUTS statement needs a `UInt64` multiplication lemma and the library
    had no analogue of `u64_ofNat_add`/`u64_ofNat_sub`
    (`bugs/FORMAL_a_specification_layer_that_stops_at_a_finite_range.md`).  The
    text pin is against a later edit that silently weakens the statement; the
    elaboration is what makes the pin mean "provable" rather than "present".
    """
    with open(os.path.join(LIB, "ProofLib.lean"), encoding="utf-8") as f:
        lib = f.read()
    check("theorem u64_ofNat_mul (a b : Nat) :\n"
          "    UInt64.ofNat a * UInt64.ofNat b = UInt64.ofNat (a * b)" in lib,
          "lib/ProofLib.lean no longer states `u64_ofNat_mul` as the "
          "unconditional analogue of `u64_ofNat_add`, so the library fact the "
          "all-inputs refinement is waiting on is gone or weakened")
    ok, detail = _elaborate_proof_lib_snippet(
        "import ProofLib\n\n"
        "example (a b : Nat) :\n"
        "    UInt64.ofNat a * UInt64.ofNat b = UInt64.ofNat (a * b) :=\n"
        "  u64_ofNat_mul a b\n",
        "all_inputs_mul_lemma", tmpdir)
    if ok is None:
        print("    SKIP: no lean found (the lemma is not elaborated)")
        return
    check(ok, f"`u64_ofNat_mul` does not elaborate: {detail[:800]}")


def test_every_annotated_example_names_a_spec_that_exists(tmpdir, shared):
    """Each `@refines` in `formal/examples/` names something `lib/Specs.lean` declares.

    The two files are edited by hand in different commits, so this can rot
    silently: rename a specification in the library and forget the nine
    annotations, and every annotated example starts failing to ELABORATE —
    which is loud, but only once somebody runs the corpus.  This is a text
    check over the annotations and it runs in milliseconds.
    """
    defined = spec_definitions()
    found = {}
    for name in sorted(os.listdir(EXAMPLES)):
        if not name.endswith(".mojo"):
            continue
        with open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
            text = f.read()
        for m in re.finditer(r"^@refines\((.*)\)\s*$", text, re.M):
            found[name] = m.group(1)
    check(found,
          "no example in formal/examples/ carries an @refines annotation, so "
          "nothing is being checked against lib/Specs.lean and the layer is "
          "infrastructure rather than coverage")
    for stem, clause in sorted(found.items()):
        spec = clause.split(";")[0].strip().replace(" . ", ".")
        check(spec in defined,
              f"{stem}.mojo asks to be refined against {spec!r}, which "
              f"`lib/Specs.lean` does not declare. A generated proof would put "
              f"that name on the right-hand side of an equation and Lean would "
              f"answer `unknown identifier` — but only in the build, not here, "
              f"and this is the check that says so at the cost of a `grep`")


def test_the_annotation_reader_accepts_both_spellings(tmpdir, shared):
    """Both documented spellings parse, and the range is the one that was asked for.

    `@refines(Name; N)` is the documented form — the range is load-bearing, so it
    is written down.  `@refines(Name)` is accepted and given
    `DEFAULT_RANGE`, for a program whose specification is total; that default is
    the thing worth pinning, because a range silently different from the one the
    author meant is a weaker theorem than they believe they asked for.
    """
    from formal.build import parse_module

    def refines_of(source):
        fns = parse_module(source)
        check(len(fns) == 1, f"expected one function, got {len(fns)}")
        return SPECS.spec_refinement(fns[0], where="<test>")

    two = refines_of("@refines(Specs.fib64; 21)\ndef f(n):\n  return n\n")
    check(two is not None and two.spec == "Specs.fib64" and two.rng == 21,
          f"@refines(Specs.fib64; 21) parsed as {two!r}")
    one = refines_of("@refines(Specs.fib64)\ndef f(n):\n  return n\n")
    check(one is not None and one.spec == "Specs.fib64"
          and one.rng == SPECS.DEFAULT_RANGE,
          f"@refines(Specs.fib64) parsed as {one!r}, so the one-clause form "
          f"does not get the documented default range {SPECS.DEFAULT_RANGE}")
    none = refines_of("def f(n):\n  return n\n")
    check(none is None,
          f"a function with no annotation read as {none!r}: every unannotated "
          f"example in the corpus would then carry a refinement section")
    # The DOTTED name: `DecoratorArgs` keeps a clause as its token text, so
    # `Specs.fib64` comes back as `Specs . fib64`.  A reader that did not join
    # the dotted pieces would refuse every documented annotation.
    check(two.spec.count(".") == 1,
          f"the dotted name was read as {two.spec!r}: the clause's token text "
          f"separates `.`, and a name that is not one is refused")


def test_a_malformed_annotation_is_refused(tmpdir, shared):
    """Every wrong shape of `@refines` is a refusal, and the refusal says why.

    The alternative to refusing is emitting the theorem against a range or a
    specification the author did not write, which is a believed falsehood with a
    proof attached — the exact defect `lib/Specs.lean`'s module docstring names
    for the layer that came before it.
    """
    from formal.build import parse_module

    def refuses(source, why):
        fns = parse_module(source)
        try:
            got = SPECS.spec_refinement(fns[0], where="<test>")
        except SPECS.RefinesRefusal as e:
            check(why in str(e),
                  f"the refusal for `{source.splitlines()[0]}` does not say "
                  f"{why!r}: {e}")
            return
        raise TestFailure(
            f"`{source.splitlines()[0]}` was accepted as {got!r} — {why} is not "
            f"something it can check, and accepting it emits a theorem nobody "
            f"asked for")

    refuses("@refines(Specs.fib64)\ndef f(n):\n  return n\n".replace(
        "@refines(Specs.fib64)", "@refines(Specs.fib64; 8; 9)"),
        "exactly two clauses")
    refuses("@refines(Specs.fib64; 0)\ndef f(n):\n  return n\n",
            "checks nothing")
    refuses(f"@refines(Specs.fib64; {SPECS.MAX_RANGE + 1})\n"
            "def f(n):\n  return n\n",
            "ceiling")
    refuses("@refines(Specs.fib64; sixty)\ndef f(n):\n  return n\n",
            "not a decimal count")
    refuses("@refines(Specs fib64; 8)\ndef f(n):\n  return n\n",
            "not a Lean name")
    refuses("@refines(Specs.fib64(), Specs.fib64())\ndef f(n):\n  return n\n",
            "takes one name")


# ---------------------------------------------------------------------------
# end to end: one build that must PASS and one that must FAIL
# ---------------------------------------------------------------------------

def _build_formal(source_text: str, stem: str, tmpdir: str):
    """`fire.py build --formal` over a one-function source, as
    `(rc, output, proof_path)`, on arm64."""
    return _build_formal_backend(source_text, stem, tmpdir, "arm64")


def _build_formal_backend(source_text: str, stem: str, tmpdir: str,
                          backend: str):
    """As `_build_formal`, with the backend named — the two generators emit
    different files from the same annotation, and the x86-64 case below is
    about that difference rather than about a second copy of this helper."""
    src = os.path.join(tmpdir, stem + ".mojo")
    with open(src, "w") as f:
        f.write(source_text)
    out = os.path.join(tmpdir, stem + ".aout")
    proc = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "-o", out,
         f"--backend={backend}", src],
        cwd=HERE, capture_output=True, text=True, timeout=900)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), \
        os.path.join(tmpdir, stem + "_proof.lean")


def test_the_emitter_writes_the_two_theorems(tmpdir, shared):
    """An annotated program gets `main_model_refines_spec` and `main_refines_spec`.

    The RIGHT specification, end to end: a real `fire.py build --formal` over a
    one-function program annotated with the identity's specification, and the
    emitted file is read for both theorems.  Reading the file rather than only
    trusting the exit code is deliberate — a layer that emitted ONE of the two
    would typecheck, and the composition is the whole point of the layer.
    """
    from formal.lean import find_lean
    if not find_lean(HERE):
        print("    SKIP: no lean found (the build does not typecheck its proof)")
        return
    rc, output, proof_path = _build_formal(
        "@refines(Specs.id64; 64)\ndef identity(n):\n  return n\n",
        "refines_identity", tmpdir)
    check(rc == 0,
          f"a program annotated with the CORRECT specification failed to build, "
          f"so the rejections below would prove nothing: {output[-500:]}")
    check(os.path.isfile(proof_path),
          "the build succeeded but wrote no proof file, so the refinement "
          "section was never emitted")
    with open(proof_path, encoding="utf-8") as f:
        text = f.read()
    check("import Specs" in text,
          "the generated file does not import `Specs`, so the name on the "
          "right-hand side of the refinement is not in scope")
    check(re.search(r"^theorem main_model_refines_spec\b", text, re.M),
          "the generated file has no `main_model_refines_spec`: the model was "
          "NOT compared against the hand-written specification, which is the "
          "half of the layer that is about `mojo`")
    check(re.search(r"^theorem main_refines_spec\b", text, re.M),
          "the generated file has no `main_refines_spec`: the MACHINE was not "
          "compared against the specification, so the layer says only that "
          "`mojo` agrees with a hand-written function")
    check("Specs.id64 (UInt64.ofNat n)" in text,
          "the refinement theorem does not mention the annotated "
          "specification, so it is stating something else")
    check(re.search(r"List\.range 64", text),
          "the refinement theorem does not mention the annotated range")
    check(re.search(r"^theorem main_refines_all_inputs\b", text, re.M),
          "the generated file has no `main_refines_all_inputs`: the model is "
          "compared with the specification only over the finite range, and the "
          "all-inputs half is the claim a reader of the example actually wants")
    check(re.search(r"\bmojo w = Specs\.id64 w\b", text),
          "`main_refines_all_inputs` does not state `mojo w = Specs.id64 w`, so "
          "it is the all-inputs theorem for some other program or "
          "specification")
    # It has TEETH, and this is what says so: the whole file was typechecked
    # (rc == 0 above), so the all-inputs theorem ELABORATED rather than being a
    # comment. A `List.range`-shaped theorem would also be true, so the theorem
    # being about the whole word (`(w : UInt64)`) is the part that separates it.
    check(re.search(r"^theorem main_refines_all_inputs \(w : UInt64\)", text, re.M),
          "`main_refines_all_inputs` is not stated over the whole word domain, "
          "so it is another ranged theorem wearing an all-inputs name")


def test_the_all_inputs_emitter_is_registered_and_shape_checked(tmpdir, shared):
    """`all_inputs_section` writes a theorem only for the shapes a row names.

    The emitter is the half of the layer that knows how to prove the all-inputs
    claim, and it is the half that can be wrong quietly: a specification with a
    row whose model is a DIFFERENT shape would get a theorem that does not
    elaborate, and an unregistered specification would get one against a
    specification the generator cannot unfold.  Both are refusals here, and the
    registered recursive shape's output is checked to name the arithmetic fact
    its step rewrites through.
    """
    identity_model = "def identity_go (n : UInt64) : UInt64 :=\n  n\n"
    fact_model = (
        "def fact_go : Nat → UInt64\n"
        "  | 0 => (UInt64.ofNat 1)\n"
        "  | k + 1 => ((UInt64.ofNat (k + 1)) * fact_go k)\n")
    # The registered identity shape: emitted, and about the whole word.
    sec = SPECS.all_inputs_section(
        "identity", SPECS.Refines("Specs.id64", 64), identity_model)
    check("main_refines_all_inputs (w : UInt64)" in sec and
          "mojo w = Specs.id64 w" in sec,
          f"the registered identity spec emitted {sec!r}")
    # The registered recursive shape: emitted, carries the no-wrap hypothesis
    # and cites the multiplication fact its induction rewrites through.
    sec = SPECS.all_inputs_section(
        "fact", SPECS.Refines("Specs.factorial64", 20), fact_model)
    check("main_refines_all_inputs" in sec, f"factorial64 emitted {sec!r}")
    check("hfits : Specs.factorial w.toNat < 2 ^ 64" in sec,
          "the factorial all-inputs theorem has no no-wrap hypothesis, so it "
          "claims the equation outside the region where it is true")
    check("Specs.u64_ofNat_mul" in sec,
          "the factorial induction does not cite the multiplication fact its "
          "step needs, so it would not elaborate")
    # A registered spec on the WRONG model shape refuses rather than emitting a
    # theorem that cannot elaborate.
    check(SPECS.all_inputs_section(
              "fact", SPECS.Refines("Specs.factorial64", 20), identity_model) == "",
          "a factorial64 annotation on an identity-shaped model still emitted "
          "an all-inputs theorem: it would fail to elaborate and take the whole "
          "proof file with it")
    # An unregistered spec is not given one either.
    check(SPECS.all_inputs_section(
              "absval", SPECS.Refines("Specs.abs64", 64), identity_model) == "",
          "an unregistered specification got an all-inputs theorem, which can "
          "only be a guessed statement about a function the generator cannot "
          "unfold")
    # No model text at all is the caller that cannot write the theorem.
    check(SPECS.all_inputs_section(
              "fact", SPECS.Refines("Specs.factorial64", 20), "") == "",
          "the emitter wrote an all-inputs theorem with no model to read")


def test_the_recursive_all_inputs_theorem_typechecks(tmpdir, shared):
    """The recursive all-inputs theorem is real Lean, on the real model.

    The example that carries `@refines(Specs.factorial64; …)` is the one the
    bug doc names, and its proof file is currently red in `fact`'s END-TO-END
    section for a reason that is not this layer's (a signed-flag leaf on the
    `if n == 0:` test).  So the theorem cannot be shown to elaborate by
    typechecking that whole file.  What CAN be checked is the theorem itself:
    the model the generated file emitted is read back out of it, the emitter's
    clause is laid beside that model with the same imports, and Lean is asked
    about that.  It is the narrowest thing that shows the emitted clause is a
    proof rather than text.
    """
    import formal.build as fb
    from formal.lean import find_lean, ensure_library, run_lean

    lean = find_lean(HERE)
    if not lean:
        print("    SKIP: no lean found (the clause is not elaborated)")
        return
    # `check=False`: this test is about the emitted CLAUSE, and the enclosing
    # file's end-to-end section is red for an unrelated reason, so asking Lean
    # about the whole file would report that reason and not this one.
    src = os.path.join(EXAMPLES, "fact.mojo")
    built = fb.compile_formal(
        src, arch="arm64", output=os.path.join(tmpdir, "fact_clause.aout"),
        prove=True, check=False)
    proof_path = built["proof_path"]
    check(os.path.isfile(proof_path),
          f"the factorial-annotated program wrote no proof: {built}")
    with open(proof_path, encoding="utf-8") as f:
        text = f.read()
    go = re.search(r"def \w+_go : Nat → UInt64\n(?:  .*\n)+", text)
    mojo = re.search(r"def mojo \(n : UInt64\) : UInt64 :=\n  .*\n", text)
    check(go and mojo,
          "the generated factorial proof does not carry the `_go` model and "
          "`mojo` this test reads, so there is nothing to lay the clause beside")
    clause = SPECS.all_inputs_section(
        "fact", SPECS.Refines("Specs.factorial64", 20),
        (go.group(0) + "\n" + mojo.group(0)))
    check(clause, "the emitter wrote no all-inputs clause for the factorial "
                  "model it just read")
    isolated = os.path.join(tmpdir, "refines_fact_clause.lean")
    with open(isolated, "w", encoding="utf-8") as f:
        f.write("import ProofLib\nimport work\nimport Refine\nimport Specs\n\n"
                + go.group(0) + "\n" + mojo.group(0) + "\n" + clause)
    ensure_library(lean, LIB)
    result = run_lean(lean, [isolated],
                      env={**os.environ, "LEAN_PATH": LIB})
    check(result.returncode == 0,
          f"the emitted all-inputs clause did not elaborate: "
          f"{(result.stdout or '')[-800:]}{(result.stderr or '')[-800:]}")


def test_a_wrong_specification_is_rejected(tmpdir, shared):
    """The control: the identity is NOT Fibonacci, and the build says so.

    This is the only test here that can tell a working refinement layer from a
    decorative one.  A layer whose `main_model_refines_spec` were `sorry`, or
    whose emitted theorem did not mention `mojo`, would pass every other case in
    this file and this one fails — and it fails with the SPECIFICATION in the
    message, which is what makes the failure actionable.
    """
    from formal.lean import find_lean
    if not find_lean(HERE):
        print("    SKIP: no lean found (the build does not typecheck its proof)")
        return
    rc, output, _proof = _build_formal(
        "@refines(Specs.fib64; 64)\ndef identity(n):\n  return n\n",
        "refines_wrong", tmpdir)
    check(rc != 0,
          "a program annotated with the WRONG specification BUILT: "
          "`main_model_refines_spec` is not being checked against the "
          "specification, so `@refines` is a comment with extra syntax")
    check("Specs.fib64" in output,
          f"the rejection does not name the specification, so it cannot be "
          f"acted on: {output[-500:]}")
    rejected = ("is false", "reduced to False", "counterexample",
                "unsolved goals")
    check(any(r in output for r in rejected),
          f"the rejection is not a refusal of the CLAIM, so this test is not "
          f"measuring what it claims: {output[-500:]}")


def test_an_unannotated_program_is_unchanged(tmpdir, shared):
    """A program with no `@refines` gets no `import Specs` and no refinement.

    The layer is optional and has to be FREE when unused: `import Specs` on
    every generated proof would make the 40-odd examples that never ask for a
    check pay to resolve a module none of them mentions, and a `main_refines_spec`
    with a guessed specification in it would be a believed falsehood.  Measured
    by building one unannotated program and looking at what came out.
    """
    rc, output, proof_path = _build_formal(
        "def plain(n):\n  return n + 1\n", "refines_plain", tmpdir)
    check(rc == 0, f"the unannotated control failed to build: {output[-500:]}")
    with open(proof_path, encoding="utf-8") as f:
        text = f.read()
    check("import Specs" not in text,
          "an unannotated program's proof imports `Specs`, so every generated "
          "file in the corpus pays for a module only some of them use")
    check("main_refines_spec" not in text,
          "an unannotated program's proof carries a refinement theorem — "
          "against which specification?")


def test_the_x86_64_backend_gets_the_model_half_only(tmpdir, shared):
    """x86-64 emits `main_model_refines_spec` and SAYS why there is no machine half.

    Both halves of one honest story, and the second is the point.  The x86-64
    generator's end-to-end theorem is a `sorry` — `test_formal.py`'s own header
    says so — so a `main_refines_spec` composed with it would be ACCEPTED by
    Lean while resting on a hole, which is exactly the "believed falsehood with
    a proof attached" the layer exists to avoid.  So the model half is emitted,
    it is a real check, and the reason the other half is missing is written into
    the file instead of being left as an absence.
    """
    rc, output, proof_path = _build_formal_backend(
        "@refines(Specs.id64; 64)\ndef identity(n):\n  return n\n",
        "refines_x86", tmpdir, "x86_64")
    check(rc == 0, f"the x86-64 control failed to build: {output[-500:]}")
    with open(proof_path, encoding="utf-8") as f:
        text = f.read()
    check("import Specs" in text,
          "the x86-64 generated file does not import `Specs`, so it cannot "
          "name a specification at all")
    check(re.search(r"^theorem main_model_refines_spec\b", text, re.M),
          "the x86-64 generated file has no `main_model_refines_spec`")
    check(not re.search(r"^theorem main_refines_spec\b", text, re.M),
          "the x86-64 generated file DOES carry `main_refines_spec`, composed "
          "with an end-to-end theorem that is a `sorry`: Lean accepts it and "
          "it establishes nothing about the machine")
    check("sorry" in text and "ADMITTED premise" in text,
          "the x86-64 file emits the model half without saying that the "
          "machine half is absent BECAUSE the end-to-end theorem is a `sorry`, "
          "so a reader sees a refinement and no explanation")


TESTS = [
    ("the specification library has no holes and no axioms",
     test_the_specification_library_has_no_holes_and_no_axioms),
    ("the all-inputs refinement has its multiplication lemma",
     test_the_all_inputs_refinement_has_its_multiplication_lemma),
    ("every annotated example names a spec that exists",
     test_every_annotated_example_names_a_spec_that_exists),
    ("the annotation reader accepts both spellings",
     test_the_annotation_reader_accepts_both_spellings),
    ("a malformed annotation is refused",
     test_a_malformed_annotation_is_refused),
    ("the emitter writes the two theorems",
     test_the_emitter_writes_the_two_theorems),
    ("the all-inputs emitter is registered and shape-checked",
     test_the_all_inputs_emitter_is_registered_and_shape_checked),
    ("the recursive all-inputs theorem typechecks",
     test_the_recursive_all_inputs_theorem_typechecks),
    ("a wrong specification is rejected",
     test_a_wrong_specification_is_rejected),
    ("an unannotated program is unchanged",
     test_an_unannotated_program_is_unchanged),
    ("the x86-64 backend gets the model half only",
     test_the_x86_64_backend_gets_the_model_half_only),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    passed = failed = 0
    with tempfile.TemporaryDirectory(prefix="formalspecs.") as tmpdir:
        shared = {}
        for name, fn in TESTS:
            try:
                fn(tmpdir, shared)
            except TestFailure as e:
                failed += 1
                print(f"  FAIL  {name}\n        {e}")
                continue
            except Exception as e:  # unexpected: report, do not mask
                failed += 1
                print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            passed += 1
            print(f"  PASS  {name}")

    print(f"\nformal specs: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())