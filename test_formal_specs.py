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
    ("every annotated example names a spec that exists",
     test_every_annotated_example_names_a_spec_that_exists),
    ("the annotation reader accepts both spellings",
     test_the_annotation_reader_accepts_both_spellings),
    ("a malformed annotation is refused",
     test_a_malformed_annotation_is_refused),
    ("the emitter writes the two theorems",
     test_the_emitter_writes_the_two_theorems),
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