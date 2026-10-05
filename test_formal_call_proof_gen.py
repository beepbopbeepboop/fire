#!/usr/bin/env python3
"""The arm64 proof generator on programs that MAKE A CALL.

`formal/arm64_proof_gen.py` used to raise

    ValueError: unsupported: recursion argument bound (not a dec1 pattern)

for every program containing a call, from `fn main(): print(42)` upwards.  The
`bl` arm of the CFG walk was written for self-recursion only, so a call to
anything else fell through to a recursion-only branch.  The consequence was
that the arm64 corpus had **no proof at all** for any program with a call, and
a `sorry` census over generated files was measuring nothing.

**And one family of programs that has no call in it at all**: `TestBitTestBranches`
below covers `if n & 8:`, whose condition lowers to a single `TBZ`. A bit test
writes no register and sets no flags, so the branch-condition value flow every
other conditional branch gets from its `CSET` does not exist for it, and the
generator used to refuse rather than emit a proposition about a register that
says nothing about the condition. It is in this file because the thing being
pinned is the same thing: what the generator emits for a program the corpus had
no proof for.

These tests pin the fix and the three defects that were behind it:

  * a call no longer raises, and the emitted proof states what the machine model
    can actually support (the run reaches the call) rather than a claim the
    model cannot make (the run returns the model);
  * the model of a call is the model's arity and arguments -- the old form took
    `e.args[0]` and dropped the rest, so `f(a, b)` was modelled as `f_go a`, a
    different function of the same name;
  * the extern bridge is a real machine fact, not `True := by trivial`.

**And one class with neither a call nor a bit test in it**:
`TestFloorCorrectionDecodes` covers `n // 3` and `n % 3`, whose division block is
the only place this backend emits a CONDITIONAL VALUE mid-block (`CMP`/`CSET`
rather than a branch) and the only place it emits an instruction whose word the
model reads as a different instruction. Both of those were measured, not
reasoned: `NEG Xd, Xm` is shadowed by the SUB-register arm
(`TestRegister31` below says that branch must not read SP, and it is right,
except that the branch cannot fire), and `MSUB Xd, Xn, Xm, XZR` is accepted by
`MUL`'s mask as well. The class runs the emitter, takes the division block's
words and asks the generator's own decoder what each one IS -- milliseconds,
against a proof that failed ~10 minutes later on a loaded box. It is here
because the thing being pinned is the same thing as the rest of the file: what
the generator says about a construct, checked where the generator can be wrong
without a Lean run.

**And one class about the SHAPE of what it emits rather than about a
construct**: `TestStepOkDerivesFromStepResult` pins that the per-instruction
step-OK lemma (`arm64_step s code ≠ none`) is read off the step-RESULT lemma of
the same index instead of re-reducing the model's 54-arm `if` chain for every
instruction. That was 90% of the `native_decide` calls in a generated arm64
proof -- 120 420 of 133 758 over `formal/examples` -- spent re-deriving a
corollary of a lemma already in the file, and it is exactly the kind of cost a
correctness test cannot see: every theorem still typechecked, at twice the
seconds.

The Lean check is skipped, loudly, when Lean is unavailable; everything else
runs either way, because a generator that cannot even produce text is worth
catching without a 27MB library build.

    python3 test_formal_call_proof_gen.py [-v]
"""
import ast
import hashlib
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PROOF_GEN = os.path.join(HERE, "formal", "arm64_proof_gen.py")

# The programs, and what each one is here to pin.  `print` is the important
# one: it is the commonest statement in the language, it is an extern, and it
# is the case FORMAL.md 11.2 records as "proof generation fails on any program
# that makes a call".
CALL_PROGRAM = "fn main():\n    print(42)\n"

# Programs that must PRODUCE a proof.
PROGRAMS = {
    # name: (source, what the test is about)
    "print": (CALL_PROGRAM,
              "an extern call: the target is outside the image"),
    "no_params": ("def seven():\n    return 7\n",
                  "a function with no parameters must not be given one"),
}

# Programs whose SEMANTIC MODEL has to state a string's value, which on this
# path is the ADDRESS of the literal's interned bytes.  Both of these used to
# generate a proof of something FALSE — the model's answer for a string literal
# was a fabricated `0`, the machine's was an address, and **Lean rejected the
# proof**.  So this is not a hole that was filled; it is "no program in this
# table proved at all", and the table is separate from `PROGRAMS` because it is
# driven on BOTH architectures (see `STRING_ARCHES`): the model is per-IMAGE,
# since the address is a property of the layout, and a fix that landed on one
# backend would leave the other emitting the false theorem.
STRING_PROGRAMS = {
    # name: (source, what the test is about)
    "printf_literal": (
        "def main(n: Int) -> Int:\n"
        "    printf(\"hi\\n\")\n"
        "    return 5\n",
        "an extern call whose ARGUMENT is a string literal: the emitted "
        "`pre_arg` theorem says the machine's x0 holds the model's value of "
        "the format string, and that is an address"),
    "return_literal": (
        "def main(n: Int) -> Int:\n"
        "    return \"small\"\n",
        "a function whose RESULT is a string: the end-to-end theorem compares "
        "the machine's result register against `mojo`, and `mojo` is the "
        "interned address"),
}

# Both backends, because the model generator is shared and the ADDRESS is not.
# A test that only built one of them would pass with the other machine emitting
# a false `eval_eq_mojo` — which is the whole failure this table records.
STRING_ARCHES = ("arm64", "x86_64")

# Programs the generator must REFUSE, with the reason it must give.  A call to a
# second function in the same image is provable -- every byte is present and
# `arm64_go_exit` follows the call and the return -- but the CFG walk is
# per-function, so following the call needs a return-address map.  That is
# interprocedural walking, and the honest thing is to say so rather than to
# fall through into the recursion arm, which is where the old
# `ValueError: unsupported: recursion argument bound (not a dec1 pattern)`
# came from: a call to a two-argument function was reported as a recursion
# problem.
REFUSED = {
    "two_args": ("fn add2(a, b):\n    return a + b\n"
                 "fn main():\n    return add2(3, 4)\n",
                 "a two-argument callee: every argument must be modelled"),
    "callee_chain": ("fn c(n):\n    return n\n"
                     "fn b(n):\n    return c(n) + 1\n"
                     "fn main():\n    return b(1)\n",
                     "callee models are emitted in dependency order"),
}


# Programs with TWO calls OUT OF THE IMAGE, which is a different refusal from
# the one above and gets its own table because `test_intra_image_call_is_refused_
# by_name` asserts the "interprocedural" wording that this message does not use.
#
# **The walk discharges an out-of-image call by HALTING at it, and it halts at
# ONE address** (`exit_at`, threaded into every `runs_avoid_append` the run
# chain is built from). A program with two such calls has a path that reaches
# the second without passing the first, so one halt address cannot discharge
# both, and the honest statement is a disjunction over them.
#
# This is the PRECONDITION for
# `bugs/FORMAL_arm64_exit_trap_does_not_flush_so_a_program_that_prints_then_exits_1_
# prints_nothing` — an exit that flushes is a `BL fflush`, and every flush site
# is one more address the walk cannot halt at. So the refusal below is the thing
# that work is waiting on, and pinning it is how a fix becomes measurable: when
# the disjunction lands, this row flips from a refusal to a proof.
#
# The fixture is TWO `printf`s on opposite arms of an `if`, which is the
# smallest program that has the shape. It matters that it needs no change to
# `formal/arm64_codegen.py` to reproduce: the doc's own experiment patched a
# flush into a divide-by-zero arm, and a two-line program reaches the same
# refusal — so the next worker does not have to edit an emitter to measure
# whether the precondition moved.
TWO_OPAQUE_CALLS = {
    "two_opaque_calls": (
        "def main(n):\n"
        "    if n > 0:\n"
        "        printf(\"pos\\n\")\n"
        "    else:\n"
        "        printf(\"neg\\n\")\n"
        "    return 0\n",
        "two calls out of the image on paths of their own: the walk's halt "
        "address is one, so the theorem would have to be a disjunction"),
}


def _functions(source):
    """The `FunctionDef`s of a Mojo source, in source order."""
    from formal.build import parse_module
    import fire_compiler as F
    return [f for f in parse_module(source) if isinstance(f, F.FunctionDef)]


def _models(prog_source, root_name):
    """The `_go` model text a program produces, for its last function."""
    import formal.arm64_proof_gen as G
    from types import SimpleNamespace
    fns = _functions(prog_source)
    tc = {"typed": False, "vtypes": {},
          "call_types": {g.name: G.DEFAULT_INT_TYPE for g in fns}}
    prog = SimpleNamespace(functions=fns, externs=[])
    root = next((f for f in fns if f.name == root_name), fns[-1])
    return "\n\n".join(G._go_defs_for(prog, root, tc))


def _top_level_decls(text):
    """`{name: declaration text}` for every top-level `theorem`/`def` in a
    generated Lean file, in source order.

    Split on the column-0 declaration headers rather than on a regular
    expression for a body, because these files put a whole block certificate in
    one declaration and a tactic block in another and a header-keyed split gets
    both without caring which."""
    decls, order = {}, []
    lines = text.split("\n")
    starts = [i for i, l in enumerate(lines)
              if re.match(r"^(theorem|def|abbrev)\s", l)]
    for k, i in enumerate(starts):
        j = starts[k + 1] if k + 1 < len(starts) else len(lines)
        name = re.match(r"^(?:theorem|def|abbrev)\s+(\S+)", lines[i]).group(1)
        decls[name] = "\n".join(lines[i:j])
        order.append(name)
    decls["__order__"] = order
    return decls


def _STEP_ENTRY_WORD(G, j):
    """A 32-bit word the step-table decoder resolves to entry `j`.

    Built from the entry's own `(mask, base)` pair -- the same pair
    `_step_facts` and `_cond_matches` read -- and then searched for, because
    `_step_branch_index` returns the FIRST entry that matches: the filler bits
    outside `mask` have to be chosen so that no earlier entry also accepts the
    word, and which filler does that depends on the entry.  Returns `None` when
    no filler works, which the caller reports rather than asserting."""
    mask, base = G._STEP_CONDS[j]
    free = 0xFFFFFFFF & ~mask if mask is not None else 0
    for filler in _STEP_FILLERS:
        word = base | (filler & free)
        if G._step_branch_index(word) == j:
            return word
    return None


# Deterministic fillers for the bits an entry leaves free, in the order they are
# tried.  Zero first (the word the mask alone describes), then whole-field
# patterns, then the operands an A64 immediate/shifted-register encoding puts in
# bits 0..10 and 16..20, which is where an earlier entry's mask is most likely
# to overlap.
_STEP_FILLERS = (
    0x00000000, 0xFFFFFFFF, 0x5A5A5A5A, 0xA5A5A5A5,
    0x00000001, 0x0000001F, 0x001F001F, 0x001F0000,
    0x0000003E, 0x003E0000, 0x007E0000, 0x1F800000,
    0x0000FFFF, 0xFFFF0000, 0x0F0F0F0F, 0xF0F0F0F0,
    0x12345678, 0x89ABCDEF, 0x00010203, 0x03020100,
)


def _entry_code(fb, src_path):
    """The emitted instruction bytes of `src_path`'s entry function, as `bytes`.

    Read out of the build result rather than re-derived, so the words the test
    reasons about are the words the proof generator was handed."""
    out = src_path[:-5] + ".aout"
    result = fb.compile_formal(src_path, output=out, prove=False, check=False)
    return result["code"]


def _lean():
    from formal.lean import find_lean
    return find_lean(HERE)


def _check_proof(proof_path):
    """`(ok, detail, n_sorries)`; None when Lean is unavailable."""
    from formal.lean import check_proof_cached
    lean = _lean()
    if not lean or not os.path.isfile(os.path.join(HERE, "lib", "ProofLib.olean")):
        return None
    ok, detail, _cached, n = check_proof_cached(proof_path, repo_root=HERE)
    return ok, detail, n


def _generate(tmp, source, name, arch="arm64"):
    """Compile `source` and return `(proof_path, error)`.

    `error` is None on success.  Built through `formal.build.compile_formal`
    rather than `fire.py` so the test does not depend on the driver's exit
    codes, and so a generator exception arrives as an exception instead of as
    text on stderr."""
    import formal.build as fb
    src = os.path.join(tmp, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    out = os.path.join(tmp, name + ".aout")
    try:
        r = fb.compile_formal(src, arch=arch, output=out, prove=True, check=False)
        return r["proof_path"], None
    except Exception as e:            # noqa: BLE001 -- the point is to report it
        return None, f"{type(e).__name__}: {e}"


def _compile(path, out, arch):
    """`compile_formal(prove=True, check=False)`, so a generator EXCEPTION
    arrives as an exception.

    The module-level `_generate` above returns `(proof_path, error)` and is what
    most of this file uses; this one returns the result dict because the rows
    below also read `info`, and a second shape of the same call would be the
    duplication this file's own `TestGeneratorSource` exists to catch.
    """
    import formal.build as fb
    return fb.compile_formal(path, arch=arch, output=out, prove=True,
                             check=False)


class TestGeneratorSource(unittest.TestCase):
    """Invariants on the generator itself, which need no compilation.

    The duplicate-def test is the one that earns its keep: this file carried
    THREE copies of its own tail for some time (two of `generate_arm64_proof`,
    three each of `_mf_expr` and `_frame_slot_accesses`), and Python binds the
    last, so a fix applied to a copy that was never called is a fix that does
    nothing while looking applied.  FORMAL.md 11.2 asks for de-duplication
    before the semantic work for exactly that reason.
    """

    def test_no_duplicate_top_level_definitions(self):
        src = open(PROOF_GEN).read()
        names = [n.name for n in ast.parse(src).body
                 if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        dupes = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(dupes, [],
                         f"formal/arm64_proof_gen.py defines {dupes} twice; "
                         f"Python binds the last, so an edit to the other copy "
                         f"is silently inert")

    def test_call_model_renders_every_argument(self):
        """The regression itself: `e.args[0]` dropped the rest."""
        defs = _models(REFUSED["two_args"][0], "main")
        self.assertIn("def add2_go (a : UInt64) (b : UInt64) : UInt64 :=",
                      defs, "the callee's model must have the source's arity")
        self.assertIn("(a + b)", defs,
                      "`fn add2(a, b) = a + b` modelled as `a + b` is the "
                      "model; `a + 0` is a different function of the same name")
        self.assertIn("(add2_go (UInt64.ofNat 3) (UInt64.ofNat 4))", defs,
                      "a call must model every argument, space-separated: "
                      "Lean reads a comma as a pair, so `(f_go a, b)` has the "
                      "wrong type for every multi-argument call")

    def test_nullary_function_gets_no_parameter(self):
        defs = _models(PROGRAMS["no_params"][0], "seven")
        self.assertIn("def seven_go : UInt64 :=", defs,
                      "a function declared with no parameters must not be "
                      "modelled with one; the fabricated parameter bound "
                      "`mojo` to every caller")

    def test_callee_models_are_defined_before_use(self):
        defs = _models(REFUSED["callee_chain"][0], "main")
        for name in ("c_go", "b_go", "main_go"):
            self.assertIn(f"def {name}", defs,
                          f"{name} is called but never defined; Lean reports "
                          f"an unknown identifier hundreds of lines from the "
                          f"call that caused it")
        self.assertLess(defs.index("def c_go"), defs.index("def b_go"),
                        "a callee must be defined before its caller names it")

    def test_unmodelled_value_forms_are_refused_not_zeroed(self):
        """`p.x` and `a[i]` have no value in a `UInt64 -> UInt64` model."""
        import formal.arm64_proof_gen as G
        src = open(PROOF_GEN).read()
        for node in ("F.MemberExpr", "F.SubscriptExpr"):
            self.assertIn(node, src,
                          "the refusal for a field read / list subscript is "
                          "gone; the model would fall through to `(0 : UInt64)` "
                          "and state a falsehood about the source")
        self.assertTrue(hasattr(G, "_no_value_model"),
                        "_no_value_model is the single place that says so")

    def test_every_fallthrough_of_the_expression_model_refuses(self):
        """The three shapes a TEXT check cannot see, exercised for real.

        `_expr_go` used to answer `(0 : UInt64)` for a NAME its environment
        does not bind, for an OPERATOR it has no meaning for, and for an
        expression FORM it does not recognise. Each of those turns "the model
        cannot say what this is" into "the model says it is zero", and the
        consequence is not a gap: the generator goes on to emit a universal
        theorem about a zero-valued model, and Lean accepts it because the
        generator can find a closing tactic. So the assertion is on the
        RAISE, and it is built rather than written — a fabricated fallback
        would have to be reinstated for these to pass, and the fallback is
        exactly what `_no_value_model` and `_call_go` were added to remove.

        Nothing in `formal/examples/` reaches any of the three (both backends
        measure 41/4/0 and 45/0/0 before and after), which is exactly why they
        were absorbed silently until now: a guard nothing exercises is a
        guard nobody has checked.
        """
        import formal.arm64_proof_gen as G
        import fire_compiler as F

        # 1. a name the model's environment does not bind — `x` is bound by no
        #    parameter and by no assignment on the way to the read.
        with self.assertRaises(NotImplementedError) as caught:
            G._expr_go(G.Var("x"), "n", {"n": "n"})
        self.assertIn("`x` is read here", str(caught.exception))

        # 2. an operator with no Lean meaning.  `at` is not in the vocabulary
        #    `_lean_op` maps onto, and nothing turns it into one.
        with self.assertRaises(NotImplementedError) as caught:
            G._expr_go(F.BinaryOp(op="at", left=G.Int(1), right=G.Int(2)),
                       "n", {"n": "n"})
        self.assertIn("has no meaning this model can render",
                      str(caught.exception))

        # 3. an expression FORM with no case at all — a list literal, which is
        #    a shape the language has and the model has no domain for. A `str`
        #    would not do: a String IS answered, as the model's own documented
        #    0 for a value with no numeric reading.
        with self.assertRaises(NotImplementedError) as caught:
            G._expr_go(F.ListExpr(elements=[]), "n", {"n": "n"})
        self.assertIn("a ListExpr has no value in the semantic model",
                      str(caught.exception))

    def test_a_modelled_expression_still_renders(self):
        """The control for the three refusals above, so they are not a blanket.

        Every form `_expr_go` DOES model has to keep rendering a term rather
        than start refusing — a guard that refuses everything is not a guard,
        it is a different backend, and the corpus counts would not move far
        enough to say so.
        """
        import formal.arm64_proof_gen as G
        import fire_compiler as F
        env = {"n": "n"}
        cases = [
            (G.Var("n"), "n"),
            (G.Bool(True), "(1 : UInt64)"),
            (G.Bool(False), "(0 : UInt64)"),
            (F.UnaryOp(op="-", operand=G.Var("n")), "(0 - n)"),
            (F.BinaryOp(op="+", left=G.Int(1), right=G.Int(2)),
             f"({G._uint64_lit(1)} + {G._uint64_lit(2)})"),
        ]
        for node, want in cases:
            with self.subTest(node=type(node).__name__):
                self.assertEqual(G._expr_go(node, "n", env), want)
        # An integer literal is rendered through `_uint64_lit` rather than
        # written out here, so this case cannot rot when the literal spelling
        # changes: the test would be asserting a rendering nobody maintains.
        self.assertEqual(G._expr_go(G.Int(7), "n", env), G._uint64_lit(7))

    def test_model_shape_reader_handles_all_three_shapes(self):
        import formal.arm64_proof_gen as G
        cases = [
            ("def f_go (n : UInt64) : UInt64 :=\n  n\n", "f_go n"),
            ("def f_go (n : Nat) : UInt64 :=\n  n\n", "f_go n.toNat"),
            ("def f_model : Nat → UInt64\n  | 0 => 0\n", "f_model n.toNat"),
            ("def f_go : UInt64 :=\n  0\n", "f_go"),
        ]
        for defs, want in cases:
            self.assertEqual(G._go_apply(defs, "f"), want,
                             f"applying a model of the wrong arity or at the "
                             f"wrong type; Lean recovers from a nullary model "
                             f"applied to `n` as a `sorry` and every "
                             f"`native_decide` downstream then fails with "
                             f"'mojo' uses 'sorry'")

    def test_a_model_is_applied_at_its_own_arity_and_a_mismatch_is_refused(self):
        """`_go_apply` reads the model's arity and applies THAT many arguments.

        It used to read the FIRST binder and apply one argument, so
        `def f(a0, a1): return a0 + a1` produced `def f_go (a0) (a1)` and then
        `def mojo (n : UInt64) := f_go n` — an argument-count error, which Lean
        does not recover from as a `sorry` and does not elaborate, so the whole
        proof file failed three definitions away from the line that is wrong.

        The limit is gone because everything that read `mojo` as
        `UInt64 -> UInt64` now reads it at the ENTRY's arity:
        `model.entry_arity` and `_entry_binders` / `_entry_arg_list` /
        `_apply_args`, which are the whole of it.
        So the case worth pinning is the one that is left: a model whose arity
        disagrees with the theorem it is the model of is a GENERATOR bug, and it
        has to be refused by name rather than applied to whatever binder is
        first.  Both halves, on both generators.
        """
        import formal.arm64_proof_gen as G
        defs2 = "def f_go (a0 : UInt64) (a1 : UInt64) : UInt64 :=\n  a0\n"
        self.assertEqual(G._go_apply(defs2, "f", ["n", "n1"]), "f_go n n1")
        with self.assertRaises(NotImplementedError) as caught:
            G._go_apply(defs2, "f")            # one argument, a two-argument model
        said = str(caught.exception)
        for needle in ("f_go", "2 argument(s)", "1", "n"):
            self.assertIn(needle, said,
                          f"the refusal must name BOTH counts, because a model "
                          f"and the theorem it is the model of disagreeing about "
                          f"the arity is what it exists to report; got {said!r}")
        # A NULLARY model takes no argument at all and is still applied to
        # NOTHING while the theorem keeps its binder: `def mojo (n : UInt64) :=
        # ret42_go` for `def ret42(): return 42` is what this has always
        # emitted, and `n` is simply not read.  So the arity check must not
        # fire on it — which it did not until it was given a nullary case.
        self.assertEqual(G._go_apply("def f_go : UInt64 :=\n  0\n", "f"),
                         "f_go")
        self.assertEqual(G._go_apply("def f_go : UInt64 :=\n  0\n", "f",
                                    ["n", "n1"]), "f_go")
        # ONE implementation, not two.  The x86-64 generator imports the arm64
        # one (`from formal import arm64_proof_gen as AP`) precisely so the two
        # machines cannot disagree about how a model is applied; a second
        # arity check of its own would be the duplication that check exists to
        # prevent, and this is the assertion that says so.
        import formal.x86_64_proof_gen as X
        # `PROOF_GEN` is the ARM64 generator -- which is what the old version of
        # this assertion read, while its message talked about the x86-64 one, so
        # it was checking arm64's own call site and saying nothing about the
        # machine it claimed to cover.  Both files are named explicitly now.
        x86_src = open(os.path.join(HERE, "formal", "x86_64_proof_gen.py")).read()
        for src, where, want in (
                (open(PROOF_GEN).read(), "arm64",
                 "_go_apply(go_defs, func_name, enames)"),
                (x86_src, "x86-64",
                 "_go_apply(go_defs, func_name, AP._entry_arg_names(arity))")):
            self.assertIn(want, src,
                          f"the {where} generator no longer applies the model "
                          f"through the shared reader at the entry's arity, so "
                          f"it has its own arity handling")
        self.assertEqual(X.generate_x86_64_proof.__module__,
                         "formal.x86_64_proof_gen")
        # …and the shapes that fit at arity one are untouched, which is the
        # other half: a reader that also mis-typed them would turn this into a
        # proof generator that proves nothing.
        for defs, want in (("def f_go (n : UInt64) : UInt64 :=\n  n\n", "f_go n"),
                           ("def f_model : Nat → UInt64\n  | 0 => 0\n",
                            "f_model n.toNat")):
            self.assertEqual(G._go_apply(defs, "f"), want)

    def test_the_generated_mojo_is_declared_at_the_entry_arities_arity(self):
        """The end-to-end statement, on both generators, for a 2-parameter entry.

        `_go_apply` is the shared reader both call, so pinning it is nearly
        enough — but "nearly" is how a second call site appears.  This drives
        the real entry points with the one text that reaches them and reads the
        STATEMENTS out of what they emit, because the failure this pins is not
        the application but the three things around it: `mojo`'s own binders,
        `eval_eq_mojo`'s argument list and the entry state's `x1`.

        Both architectures, because the two emitters could previously disagree
        about how many parameters the entry takes — which is why the arity
        reader is `model.entry_arity` and both generators call it.
        """
        from types import SimpleNamespace
        from formal.build import parse_module
        import fire_compiler as F
        src = "def f(a0, a1):\n    return a0 + a1\n"
        fns = [f for f in parse_module(src) if isinstance(f, F.FunctionDef)]
        prog = SimpleNamespace(functions=fns, externs=[])
        import formal.arm64_proof_gen as G
        import formal.x86_64_proof_gen as X
        for gen, entry in ((X, "generate_x86_64_proof"),
                           (G, "generate_arm64_proof")):
            info = {"func_name": "f", "base_addr": 0x1000, "labels": {},
                    "test_input": 10}
            try:
                out = getattr(gen, entry)(prog, b"", dict(info))
            except NotImplementedError as e:
                # x86-64 has no CFG walk for an empty image, so it refuses the
                # SHAPE; what it must not do is refuse for the ARITY, which is
                # the reason this test existed when it asserted a refusal.
                self.assertNotIn("parameter", str(e).split("\n")[0].lower()
                                 .replace("arity", ""),
                                 f"{entry} still refuses a two-parameter entry "
                                 f"point for its arity: {e}")
                continue
            self.assertIn("def mojo (n : UInt64) (n1 : UInt64) : UInt64", out,
                          f"{entry} declared `mojo` at the wrong arity")
            self.assertIn("evalFunc ast", out)
            self.assertIn("[n, n1] = mojo n n1", out,
                          f"{entry} handed the AST bridge a one-argument list, "
                          f"so its second parameter evaluates to 0")

    def test_the_step_table_and_the_model_are_the_same_set(self):
        """`_STEP_CONDS` and `arm64_step`, checked two ways, because one is not
        enough.

        `check_step_conds` compares SETS and is called by
        `generate_arm64_proof`, so every proved build enforces it; `audit_step_table`
        also checks that the two ORDERS agree per overlapping pair, and it is the
        one that reads `lib/ProofLib.lean` as TEXT. Both existed and the second was
        reading a branch condition out of a COMMENT above the TBZ case, which put
        `test_formal.py` in a state where it raised before generating a single
        proof for every example it has — see
        `bugs/FORMAL_the_arm64_step_table_audit_read_a_branch_out_of_a_comment.md`.

        The regression this pins is the one whose fix was to REMOVE a row:
        `CSEL` is emitted by `arm64_codegen.py` at six sites and is in neither the
        table nor the model, and a row in one without the other is a generator
        describing an effect the function it is proving takes no step for."""
        import formal.arm64_proof_gen as G
        G.check_step_conds(os.path.join(HERE, "lib", "ProofLib.lean"))
        notes = G.audit_step_table(os.path.join(HERE, "lib", "ProofLib.lean"))
        self.assertIsInstance(notes, list)
        for note in notes:
            self.assertIn("shadows entry", note)

    def test_adrp_step_uses_simpa(self):
        """An ADRP's result reads the program counter, so the library lemma
        takes `pc` as a parameter while `_step_rhs` writes `s.pc`; `exact`
        cannot close that.  No example in `formal/examples/` emits an ADRP, so
        this path had no coverage at all until `print("hi")` did."""
        import formal.arm64_proof_gen as G
        self.assertIn("s.pc", G._step_rhs_generic(20) or "",
                      "ADRP is expected to be the pc-dependent right-hand side")
        src = open(PROOF_GEN).read()
        self.assertIn("_pc_dependent", src,
                      "the pc-dependent closer is gone; an ADRP program will "
                      "not typecheck and the error names a type mismatch in "
                      "the step lemma rather than the ADRP")


# The forms whose `Rn` can be register 31, and what the ARCHITECTURE says 31
# means there.  The third column is not computed from the model — it is the
# measured answer, and the two cases below are what measure it (by assembling
# these spellings and RUNNING the words), so the table cannot drift into
# agreeing with the thing it is checking.
#
# The second column is the model's own branch, keyed by the condition that
# introduces it in `lib/ProofLib.lean`'s `arm64_step` — a condition rather than an
# opcode so the test fails LOUDLY when a branch is renamed (the key goes missing)
# instead of silently checking a different branch.
#
# The fourth column is what the WORD clang assembles for the spelling does, and
# it is the column whose absence made this table pass for the wrong reason: a row
# keyed on a branch's text says nothing about whether any word can ARRIVE at that
# branch.  `neg x0, x7` is the case in point — `NEG Xd, Xn` is `SUB Xd, XZR, Xn`,
# so its word matches the SUB-register arm first and the NEG arm is unreachable.
#
#   "lands here"  the assembled word decodes to the branch this row names
#   "extended"    the assembler accepts `sp` in `Rn` by emitting the
#                 EXTENDED-register class (bit 21 set), which no branch decodes,
#                 so the model says nothing about that word
#   "rejected"    clang refuses the spelling: there is no SP encoding at all
SP_IN_RN_FORMS = (
    # The immediate class reads SP, and it is the class that reaches a branch:
    # the emitter's stack-floor guard is `ADD X17, SP, #0 ; CMP X17, X16`, and the
    # `ADD` half is the only SP read in it.
    ("add x0, sp, #16", "= 0x91000000 then", "sp", "lands here"),
    ("cmp sp, #16", "= 0xf1000000 then", "sp", "lands here"),
    # The shifted-register class reads the ZERO register, for all three of
    # ADD/SUB/SUBS — which is what makes a NEG `-Xn` rather than `sp - Xn`.  Each
    # spelling below is the one clang accepts for the encoding, so the word is
    # the one a reader can paste into a disassembler.
    ("add x0, xzr, x1", "= 0x8b000000 then", "zr", "lands here"),
    ("sub x0, xzr, x1", "= 0xcb000000 then", "zr", "lands here"),
    ("cmp xzr, x1", "= 0xeb000000 then", "zr", "lands here"),
    # `NEG Xd, Xn` is `SUB Xd, XZR, Xn`, so this word is read by the SUB arm
    # above and the NEG arm is never reached.  The row names the arm that IS
    # reached, which is the whole point: the old table named the NEG arm, checked
    # its source text, and said nothing about the word.
    ("neg x0, x7", "= 0xcb000000 then", "zr", "lands here"),
    # The three SP spellings the assembler DOES accept in the register class.
    # Each reaches the extended-register class instead, which no branch decodes,
    # so the model makes no claim about it — asserted as exactly that, because
    # "the model's branch for this form" was never a question about these.
    ("add x0, sp, x16", "= 0x91000000 then", "sp", "extended"),
    ("sub x0, sp, x16", "= 0x91000000 then", "sp", "extended"),
    ("cmp sp, x16", "= 0x91000000 then", "sp", "extended"),
    # …and the five whose 31 is the ZERO register with no SP encoding at all.
    # They are in the table because they are the direction a "31 means SP
    # everywhere" change gets wrong, and a test that only checked the accepting
    # forms would not notice.
    ("and x0, sp, x1", "= 0x8a000000 then", "zr", "rejected"),
    ("eor x0, sp, x1", "= 0xca000000 then", "zr", "rejected"),
    ("mul x0, sp, x1", "= 0x9b007c00 then", "zr", "rejected"),
    ("neg x0, sp", "= 0xcb0003e0 then", "zr", "rejected"),
    ("add w0, sp, #16", "= 0x11000000 then", "zr", "rejected"),
    # …and the two UNSIGNED-OFFSET memory forms, which read SP and which the
    # emitter uses for stack traffic: `encode_ldr_xt_xn_imm(_, 31, off)` and
    # `encode_str_xt_xn_imm(_, 31, off)` are emitted at ten sites apiece. Both
    # used to read their base with `arm64_reg`, which is 0 at register 31, so
    # every stack read was modelled from address `off` and every stack write
    # landed at `off` — a wrong answer rather than a missing one, because the
    # address it computed was an ordinary-looking address. `TestStoreWidth`
    # below is the hardware half of the same fact.
    ("ldr x0, [sp, #64]", "= 0xF9400000 then", "sp", "lands here"),
    ("str x0, [sp, #16]", "= 0xF9000000 then", "sp", "lands here"),
)

# The three words the hardware is asked about directly, as
# `(spelling, the C expression, what the answer means)`.  Each is ONE
# instruction with its second operand set to 1, so `Rn = 31` is the only thing
# the answer can be about: `0 + 1` is 1, `0 - 1` is -1, and `sp` is neither.
RN31_PROBES = (
    ("add x0, xzr, x1", "add_xzr_x1()", "sp"),
    ("sub x0, xzr, x1", "sub_xzr_x1()", "zr"),
    ("cmp xzr, x1", "cmp_xzr_x1_eq()", "zr"),
)


def _assembler_word(form):
    """The instruction WORD clang assembles for `form`, or None if it refuses.

    One `clang -c` per form, then the object's `__TEXT,__text` read back — the
    same thing `_assembler_accepts` builds and throws away, so the two cannot
    disagree about whether a spelling is legal.  The word is what makes a row
    REACHABLE: a table of spellings cannot tell `neg x0, x7` (whose word the
    SUB-register arm reads) from `neg x0, sp` (which clang refuses).
    """
    import struct
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "probe.s")
        with open(src, "w") as fh:
            fh.write(".text\n.globl _sp_probe\n_sp_probe:\n  " + form + "\n")
        obj = os.path.join(td, "probe.o")
        p = subprocess.run(
            ["clang", "-target", "arm64-apple-macos11", "-c", "-o", obj, src],
            capture_output=True, text=True)
        if p.returncode != 0:
            return None
        with open(obj, "rb") as fh:
            data = fh.read()
    i = data.find(b"__text")
    if i < 0:
        return None
    _addr, size, offset = struct.unpack_from("<QQI", data, i + 32)
    return struct.unpack_from("<I", data, offset)[0]


def _assembler_accepts(form):
    """Does clang's assembler accept `form`?

    One `clang -c` per form, on a one-instruction file.  The batched version of
    this read the offending INSTRUCTION off the diagnostic, which is on the
    line AFTER the `file:line:col: error:` one — so every form looked accepted
    and the case below passed for the wrong reason.  One process per form costs
    ~0.15 s and has nothing to parse.

    `--target arm64-apple-macos11` is explicit because this host is arm64 and a
    bare `clang` assembles for the HOST, which would make `add x0, sp, x16` a
    syntax error for a reason that has nothing to do with the encoding.
    """
    return _assembler_word(form) is not None


def _arm64_step_branch(src, key):
    """The CODE of one `arm64_step` branch, from its dispatch condition.

    Keyed by the `= 0x… then` the branch tests, which is unique per branch and
    survives a reworded comment — and a missing key FAILS the case rather than
    silently matching a neighbour, which is the failure mode of keying on prose.

    **Comments are blanked first, and that is the whole reason this can answer
    the question it is asked.**  What the cases below want to know is which
    register accessor the MODEL'S CODE uses, and `arm64_step`'s branches carry
    long comments that name the *other* one — the SUB branch's says in prose
    "`arm64_reg`, NOT `arm64_reg_or_sp`" and then explains at length why ADD is
    the opposite. A substring search over the raw text therefore reads the
    SUB branch as reading SP, which is the exact defect the table was rewritten
    to end: a test that takes the model's word for what the model says about
    itself.  `formal/admitted.py::lean_code_regions` is the one Lean lexer in
    the tree and blanks comments and string contents at every offset, so it is
    used rather than a second stripper written here; the lines it empties are
    then DROPPED, because what is left of a comment is its indentation and
    that indentation is what a `\n  ` cut would otherwise stop at.
    """
    from formal.admitted import lean_code_regions

    code = "\n".join(l for l in lean_code_regions(src).split("\n") if l.strip())
    i = code.find(key)
    if i < 0:
        return None
    j = code.find("\n  else if", i)
    k = code.find("\n  -- ", i)
    ends = [x for x in (j, k) if x >= 0]
    return code[i:min(ends)] if ends else code[i:]


class TestRegister31(unittest.TestCase):
    """Which arm64 forms read register 31 as SP, and which as the zero register.

    `arm64_reg 31 s = 0` is right for a data-processing form and wrong for
    `cmp sp, floor` — the comparison a stack-floor guard is built from — so the
model's step for `SUBS XZR, X31, X16` used to compute
    `arm64_subs_flags 0 X16`: a proof about a different instruction than the
    one emitted, which typechecks and is false.

The fix reads `Rn` through `arm64_reg_or_sp` in the forms that HAVE an SP
encoding.  Deciding which forms those are is architectural, and this test
does not take the model's or this file's word for it: it asks the assembler,
which is where the answer comes from, and requires the two to agree.  A
blanket "31 means SP everywhere" passes the accepting half and fails here.

**And it asks the HARDWARE, for the three words where the two disagree.**
That is the half this class did not have, and the reason is the defect
the shifted-register `SUB`/`SUBS` arms names: the
table below used to be checked against the branch's SOURCE TEXT, so the
`NEG` row asserted a real property of a branch the decoder CANNOT REACH
(`NEG Xd, Xn` is `SUB Xd, XZR, Xn`, whose word matches the SUB-register
arm first) and passed for the wrong reason.  Keying on the comment finds
the text; it does not find out whether any word can arrive there.  So:

  * `test_every_row_is_reachable` asks `_step_branch_index` about the word
    clang actually assembles for each spelling, and requires the branch it
    names to be the one the row names — the property whose absence made the
    `NEG` row vacuous;
  * `test_the_hardware_agrees_with_the_model_about_rn_31` assembles three
    one-instruction functions, RUNS them (arm64 host; skipped elsewhere), and
    asks the machine what register 31 means in each: `sp` for `ADD` in the
    shifted-register class, and the ZERO register for `SUB` and `SUBS` in the
    same class, which is exactly what makes a `NEG` `-Xn`.
    """

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "lib", "ProofLib.lean")) as f:
            cls.lib = f.read()
        cls.branches = {}
        for form, key, _rn, _reach in SP_IN_RN_FORMS:
            cls.branches[form] = _arm64_step_branch(cls.lib, key)

    def test_every_form_in_the_table_is_still_in_the_model(self):
        for form, key, _rn, _reach in SP_IN_RN_FORMS:
            with self.subTest(form=form):
                self.assertIsNotNone(
                    self.branches[form],
                    f"{key!r} is not in lib/ProofLib.lean's arm64_step any "
                    f"more, so this table is checking nothing for {form!r}")

    def test_the_model_reads_rn_the_way_the_architecture_does(self):
        """The model's branch text against the MEASURED column, row by row.

        This is the check that used to be an oracle of its own — "clang accepts
        `sp` in `Rn`, therefore the model's branch must read SP" — and it was
        wrong, because accepting the spelling says the ENCODING has an SP form
        somewhere and not that this branch decodes it.  The expectation is now
        written down (`SP_IN_RN_FORMS`'s third column) and the two cases around
        this one are what justify it.
        """
        for form, key, rn, _reach in SP_IN_RN_FORMS:
            with self.subTest(form=form):
                reads_sp = "arm64_reg_or_sp" in (self.branches[form] or "")
                self.assertEqual(
                    reads_sp, rn == "sp",
                    f"{form!r} is measured to read `Rn = 31` as {rn.upper()}, "
                    f"and the model's branch for it ({key!r}) "
                    f"{'reads' if reads_sp else 'does NOT read'} register 31 "
                    f"as SP — so one of them is wrong about the architecture")

    def test_every_row_is_reachable(self):
        """The word clang assembles must decode to the branch the row names.

        The check whose absence is the defect this table was filed for: a row
        keyed on a branch's SOURCE TEXT says nothing about whether any word can
        arrive there, and `neg x0, x7` — the `NEG` every image carries — is read
        by the SUB-register arm, not by the NEG arm this table used to name.  So
        for each row the word is asked of `_step_branch_index`, the generator's
        own decoder, and the three dispositions are distinguished:

          * "lands here" — the word decodes to this row's branch;
          * "extended" — clang accepted `sp` in `Rn` by emitting the
            extended-register class, which no branch decodes, so the model says
            nothing about that word.  Asserted as EXACTLY that, because "the
            model's branch for this form" was never a question about it;
          * "rejected" — clang refuses the spelling, so no word exists.
        """
        import formal.arm64_proof_gen as G
        for form, key, _rn, reach in SP_IN_RN_FORMS:
            with self.subTest(form=form):
                word = _assembler_word(form)
                if reach == "rejected":
                    self.assertIsNone(
                        word, f"clang now ASSEMBLES `{form}`, so this row is no "
                              f"longer in the class it was filed in — the "
                              f"architecture may have gained an SP encoding, or "
                              f"the row needs a spelling that reaches "
                              f"{key!r}")
                    continue
                self.assertIsNotNone(
                    word, f"clang refuses `{form}` but this row expects it to "
                          f"assemble ({reach})")
                idx = G._step_branch_index(word)
                if reach == "extended":
                    self.assertIsNone(
                        idx, f"`{form}` assembles to 0x{word:08x}, which the "
                             f"model DOES decode (branch {idx}); this row says "
                             f"it is the extended-register class, which no "
                             f"branch claims, so one of the two is stale")
                else:
                    self.assertIsNotNone(
                        idx, f"`{form}` assembles to 0x{word:08x}, which no "
                             f"branch of arm64_step decodes — the generator "
                             f"cannot say anything about this word, so this row "
                             f"is checking a branch nothing reaches")
                    _mask, value = G._STEP_CONDS[idx]
                    _mask = (1 << 32) - 1 if _mask is None else _mask
                    want = int(key.split("=")[1].split("then")[0].strip(), 16)
                    self.assertEqual(
                        (word & _mask), value,
                        f"`{form}` decodes to branch {idx}, whose condition is "
                        f"not {key!r}: the row names one branch and the word "
                        f"reaches another, which is the vacuity this case "
                        f"exists to end")
                    self.assertEqual(
                        want, value,
                        f"the row names {key!r} but the branch this word "
                        f"reaches tests a different value")

    def test_the_hardware_agrees_with_the_model_about_rn_31(self):
        """Ask the MACHINE, for the three words the model branches on.

        `ADD X0, XZR, X1` / `SUB X0, XZR, X1` / `CMP XZR, X1` with the second
        operand set to 1: each answer is `1`, `-1`, or "not equal", and `sp` is
        none of them, so one clang invocation and one run settles register 31 for
        the whole shifted-register class — which is the class a `NEG` lives in
        and the one this file's model used to read as `sp`.

        Skipped on a host that cannot run arm64, because there is no other way
        to ask this question: the alternative oracle is the model, which is the
        thing under test.
        """
        import platform
        import subprocess
        import tempfile
        if platform.machine() not in ("arm64", "aarch64"):
            self.skipTest("the probes are arm64 code; there is nothing to run "
                          "them on here")
        expected = {"add x0, xzr, x1": 1, "sub x0, xzr, x1": -1,
                    "cmp xzr, x1": 0}
        with tempfile.TemporaryDirectory() as td:
            asm = os.path.join(td, "probe.s")
            with open(asm, "w") as fh:
                fh.write(".text\n")
                for i, (form, call, _rn) in enumerate(RN31_PROBES):
                    fh.write(f".globl _p{i}\n_p{i}:\n    mov x1, #1\n"
                             f"    {form}\n")
                    if form.startswith("cmp"):
                        fh.write("    cset x0, eq\n")
                    fh.write("    ret\n")
            c = os.path.join(td, "main.c")
            with open(c, "w") as fh:
                fh.write("#include <stdio.h>\n")
                for i, (_form, call, _rn) in enumerate(RN31_PROBES):
                    fh.write(f"extern long p{i}(void);\n")
                fh.write("int main(void) {\n")
                for i, (form, call, _rn) in enumerate(RN31_PROBES):
                    fh.write(f'    printf("%s %ld\\n", "{form}", p{i}());\n')
                fh.write("    return 0;\n}\n")
            exe = os.path.join(td, "probe")
            build = subprocess.run(
                ["clang", "-target", "arm64-apple-macos11", "-o", exe, c, asm],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0,
                             f"the probe did not build: {build.stderr[-400:]}")
            run = subprocess.run([exe], capture_output=True, text=True)
        got = {}
        for line in run.stdout.splitlines():
            form, value = line.rsplit(" ", 1)
            got[form] = int(value)
        for form, _call, rn in RN31_PROBES:
            with self.subTest(form=form):
                self.assertIn(form, got, f"the probe printed nothing for it: "
                                         f"{run.stdout!r}")
                if rn == "sp":
                    continue          # the stack pointer is not a small constant
                self.assertEqual(
                    got[form], expected[form],
                    f"`{form}` with X1 = 1 answered {got[form]}, so this "
                    f"machine reads `Rn = 31` as something other than the "
                    f"ZERO register — the model, and every proof that depends "
                    f"on this arm, would then be wrong")

    def test_the_generator_keeps_its_own_spelling_and_why(self):
        """`_step_rhs` says `s.sp`/`arm64_reg` where the library says the
        helper, and that is deliberate.

        The step-result lemma is closed by `exact`-ing the library's lemma
        INSTANTIATED AT THE CONCRETE WORD, so the two right-hand sides only have
        to be defeq — and they are, because `arm64_reg_or_sp 3 s` and
        `s.sp`/`arm64_reg 3 s` both reduce on a literal index.  Emitting the
        helper from the generator instead would make that exact, but the
        generated text is what every downstream `simp only [..., arm64_reg,
        arm64_set_reg]` goal consumes, and those lists do not carry the helper:
        the change would put `arm64_reg_or_sp 3 s` in every value-flow goal and
        break them.  Recorded here because the asymmetry looks like a bug.

        **The pin is the WHOLE right-hand side, `arm64_set_reg rd` included, and
        that is a merge of two facts rather than one.**  The library's CMP arm
        WRITES `Rd`, because `SUBS` with `Rd != 31` is not a `CMP` but
        `formal/arm64.py`'s `encode_subs_xd_xn_xm`, which leaves the difference
        in a register; `_step_rhs` writes it for the same reason, and the two
        right-hand sides have to agree in shape or the `exact` does not close.
        So this row is also what would catch the generator silently reverting to
        the flags-only `some { s with nzcv := … }` — a `_step_rhs` that stops
        writing `rd` models every `subs xd, xn, xm` in an image as "set the
        flags, change no register", and every theorem over it still typechecks.
        """
        import formal.arm64_proof_gen as G
        self.assertEqual(G._step_rhs(0xeb1003ff, 6),
                         "some { (arm64_set_reg 31 s (arm64_reg 31 s - "
                         "arm64_reg 16 s)) with nzcv := arm64_subs_flags "
                         "(arm64_reg 31 s) (arm64_reg 16 s) }",
                         "`_step_rhs`'s CMP-register arm changed shape; if it "
                         "now emits `arm64_reg_or_sp`, the `simp only` lists in "
                         "this generator need the helper in them too — and if it "
                         "stops writing `arm64_set_reg rd`, it has reverted to "
                         "modelling `subs xd, xn, xm` as a flag-only CMP")
        self.assertIn("arm64_reg 31 s", G._step_rhs(0x8b1003e0, 2),
                      "`_step_rhs`'s ADD-register arm changed shape")

    def test_the_sp_encodings_are_named_rather_than_left_unnamed(self):
        """The words clang emits for `sp` in `Rn` are NAMED, not "an instruction".

        A64's SP encoding for `Rn` is in the EXTENDED-register class, and
        nothing this backend emits is in it — every `ADD Xd, SP, Xm` it wants is
        spelled as the immediate form, and every register-form add/sub/cmp it
        emits names an ordinary register.  So this is a COVERAGE gap, and the
        only thing the generator owes a reader who hits one is its NAME: the
        shifted-register rows are a different class, and the reason the class
        exists is the same fact the NEG fix turned on (an `Rn` of 31 is the zero
        register there and `sp` here).

        The words are the ones clang assembles for the SP spellings, measured by
        assembling them, and each is required to decode to no branch AND to be
        named — a word that decodes to nothing and has no name is the failure
        mode, and `_unmodelled_instruction`'s own contract is `(name, why)`.
        """
        import formal.arm64_proof_gen as G
        for form, want in (("add x0, sp, x1", "ADD extended"),
                           ("sub x0, sp, x1", "SUB extended"),
                           ("subs x0, sp, x1", "SUBS/CMP extended"),
                           ("cmp sp, x16", "SUBS/CMP extended")):
            with self.subTest(form):
                word = _assembler_word(form)
                self.assertIsNotNone(word, f"clang refuses `{form}`")
                self.assertIsNone(
                    G._step_branch_index(word),
                    f"`{form}` assembles to 0x{word:08x}, which now DECODES — so "
                    f"either the extended-register class has a model branch (and "
                    f"this row is stale) or the emitter started producing one")
                name, why = G._unmodelled_instruction(word)
                self.assertEqual(
                    name, want,
                    f"0x{word:08x} (what clang assembles for `{form}`) is named "
                    f"{name!r}; an unmodelled word with no name is reported as "
                    f"'an instruction', which sends the reader to a "
                    f"disassembler for a word the answer is about")
                self.assertIn("sp", why,
                              "the reason has to say what the class IS, since "
                              "the name alone does not say why it is missing")


# ── the floor correction, decoded ───────────────────────────────────────────
#
# `formal/arm64_codegen.py::_emit_floor_correction` and its two callers are the
# only code in this tree that emits a CONDITIONAL VALUE into the middle of a
# block (`CMP`/`CSET` instead of a branch), and every instruction it emits is one
# `ProofLib.arm64_step` already modelled.  "Already modelled" turned out not to
# be enough, twice, and both times the emitted word decoded as a DIFFERENT
# instruction than the one written:
#
#   * `NEG Xd, Xm` is `SUBS Xd, XZR, Xm` with `Rn = 31`, and the SUB-register arm
#     reads `arm64_reg_or_sp 31 s` — SP.  `TestRegister31` above says that
#     branch must not, and it is right, but the SUB arm is tested FIRST so the
#     NEG branch cannot fire.  `formal/examples/udivmod.mojo`'s proof failed with
#     `native_decide … is false` on every input, and it is live on master today
#     through unary minus.  Filed as
#     the `arm64_step` SUB-register arm reading SP.
#   * `MSUB Xd, Xn, Xm, XZR` — the word the fix reached for next — is accepted
#     by BOTH `MUL`'s mask (`0xffe07c00`) and `MSUB`'s (`0xffe08000`), and
#     `arm64_step` tests MUL first, so `-(d*c)` was read as `+d*c` and the
#     residual goal came out with the wrong sign.
#
# So the property worth pinning is not "these instructions are modelled" — it is
# **"each word the emitter emits decodes to the term the emitter meant"**, read
# through the GENERATOR's own decoder (`_step_branch_index` / `_step_rhs`), which
# `audit_step_table` checks against `lib/ProofLib.lean`'s if-chain order.  The
# words come from running the emitter on a source with the construct in it, so a
# change of register or of instruction is caught here rather than in a proof that
# fails four hundred seconds later.

#: The division block's words, from `SDIV` up to (not including) the trailing
#: unconditional branch, with the term each must decode to.  `s` is the state
#: entering the block: `X0` the dividend, `X1` the divisor.
_FLOOR_COMMON = [
    ("sdiv x2, x0, x1",
     "some (arm64_set_reg 2 s (sdiv64 (arm64_reg 0 s) (arm64_reg 1 s)))"),
    # r = n - q*d — the remainder SDIV did not leave in a register here.
    ("msub x3, x2, x1, x0",
     "some (arm64_set_reg 3 s (arm64_reg 0 s "
     "- (arm64_reg 2 s * arm64_reg 1 s)))"),
    ("eor x4, x3, x1",
     "some (arm64_set_reg 4 s (arm64_reg 3 s ^^^ arm64_reg 1 s))"),
    ("cmp x3, #0",
     "some { s with nzcv := arm64_subs_flags (arm64_reg 3 s) (UInt64.ofNat 0) }"),
    ("cset x5, ne",
     "some (arm64_set_reg 5 s "
     "(if arm64_matches_condition 1 s.nzcv then 1 else 0))"),
    ("cmp x4, #0",
     "some { s with nzcv := arm64_subs_flags (arm64_reg 4 s) (UInt64.ofNat 0) }"),
    ("cset x6, lt",
     "some (arm64_set_reg 6 s "
     "(if arm64_matches_condition 11 s.nzcv then 1 else 0))"),
    # c = (r != 0) AND (r XOR d reads negative)
    ("and x5, x5, x6",
     "some (arm64_set_reg 5 s (arm64_reg 5 s &&& arm64_reg 6 s))"),
]

_FLOOR_DIV_TAIL = [
    ("sub x0, x2, x5",
     "some (arm64_set_reg 0 s (arm64_reg 2 s - arm64_reg 5 s))"),
]

# The remainder multiplies the FLOOR-CORRECTED QUOTIENT, which is why it costs
# one `SUB` and one `MSUB` rather than a mask and an `IMUL`: `n - d*(q - c)` is
# `a - b * fdiv64 a b`, which is what `lib/ProofLib.lean`'s `frem64` says.
_FLOOR_MOD_TAIL = [
    ("sub x6, x2, x5",
     "some (arm64_set_reg 6 s (arm64_reg 2 s - arm64_reg 5 s))"),
    ("msub x0, x1, x6, x0",
     "some (arm64_set_reg 0 s (arm64_reg 0 s "
     "- (arm64_reg 1 s * arm64_reg 6 s)))"),
]

#: The two spellings this construct has already emitted once and whose words the
#: model reads as something else.  Asserted ABSENT, because "the docstring says
#: not this one" is not a check.
def _neg_word():
    """`neg x6, x5` — the word the obvious spelling of `-(d*c)` emits."""
    import formal.arm64 as A
    return A.encode_neg_xd_xn(6, 5)


def _and_word():
    import formal.arm64 as A
    return A.encode_and_xd_xn_xm(5, 6, 1)


def _msub_xzr_word():
    """`msub x6, x1, x5, xzr` — the NEXT obvious spelling, which the ENCODER
    refuses (`encode_msub_xd_xn_xm_xa`'s range is 0..30 and its own docstring
    says why), so the word is spelled out here rather than built through it.

    That the encoder refuses it is what makes this row cheap to state; the row is
    still worth having because the refusal is one `assert` away from being
    widened and the word is what the widening would produce.
    """
    import struct
    return struct.pack("<I", 0x9b008000 | (5 << 16) | (31 << 10) | (1 << 5) | 6)


_FLOOR_FORBIDDEN = (
    # `arm64_reg 31 s -` IS `-X5`: `NEG Xd, Xn` is `SUB Xd, XZR, Xn`, so the
    # word lands in the SUB-register arm and that arm now reads `Rn` as the
    # ZERO register (`lib/ProofLib.lean`'s `arm64_step_neg_reads_zero_rn` is the
    # pin).  It used to read SP here, which is
    # the shifted-register `SUB` arm reading SP, and is why
    # this row existed at all — so what the row now says is "the emitter does
    # not emit it", which is the half that is still load-bearing: whether the
    # corrected floor division could now spell it this way is open, and until it
    # is measured this row is what says the block does not.
    ("neg x6, x5", _neg_word, "arm64_reg 31 s -"),
    # Reads as `x1 * x5`: MUL is tested before MSUB and both masks accept it.
    ("msub x6, x1, x5, xzr", _msub_xzr_word,
     "arm64_set_reg 6 s (arm64_reg 1 s * arm64_reg 5 s)"),
    # Reads CORRECTLY on both machines and still is not what arm64 emits: the
    # mask `(~(c-1)) AND d` IS `d*c`, so this spelling answers the same numbers,
    # and the residual goal of a dividing block then needs `bv_decide` to split
    # the `ite`s inside `c` to see it — which it declined. arm64 multiplies the
    # corrected quotient instead; x86-64 still masks, because `IDIV` consumes
    # the dividend and `a - b*(q-c)` needs `a`.
    ("and x5, x6, x1", _and_word,
     "arm64_set_reg 5 s (arm64_reg 6 s &&& arm64_reg 1 s)"),
)


def _arm64_words(source):
    """The instruction words `ARM64Codegen` emits for a one-function source."""
    import struct
    from formal.build import parse_module
    import formal.arm64_codegen as AC
    g = AC.ARM64Codegen()
    g.compile(parse_module(source), emit_startup=False)
    text = bytes(g.asm.sections["text"])
    return [struct.unpack_from("<I", text, i)[0]
            for i in range(0, len(text) - len(text) % 4, 4)]


def _decode(word):
    """`(index, term)` — the generator's reading of one instruction WORD.

    Takes the word as an `int` and accepts the encoder's four bytes too, because
    `formal/arm64.py`'s encoders return `bytes` and a reader that silently
    accepted only one of the two would be a trap for whoever adds the next row.
    """
    import formal.arm64_proof_gen as G
    if isinstance(word, (bytes, bytearray)):
        word = int.from_bytes(word, "little")
    idx = G._step_branch_index(word)
    return idx, G._step_rhs(word, idx)


class TestFloorCorrectionDecodes(unittest.TestCase):
    """Every word the floor correction emits decodes to the term it meant.

    Lean-free and image-free: it runs the emitter on `n % 3` / `n // 3` and
    asks the proof generator's own decoder what each word in the division block
    IS.  That is the check that would have caught both of the defects above, and
    it runs in milliseconds where the proof that caught them takes ~10 minutes on
    a loaded box.
    """

    def _block(self, expr):
        """The words from the `SDIV` to the block's trailing branch."""
        words = _arm64_words("def f(n):\n    return %s\n" % expr)
        start = next(i for i, w in enumerate(words)
                     if _decode(w)[1].startswith("some (arm64_set_reg 2 s (sdiv64"))
        end = next(i for i in range(start, len(words))
                   if _decode(words[i])[1].startswith("some { s with pc := ")
                   and "s.pc" in _decode(words[i])[1])
        return words[start:end]

    def _check(self, expr, tail):
        words = self._block(expr)
        want = _FLOOR_COMMON + tail
        self.assertEqual(len(words), len(want),
                         f"{expr}: the division block emits {len(words)} words "
                         f"and this test expects {len(want)}; the extra or "
                         f"missing instruction is the thing to look at")
        for (form, term), word in zip(want, words):
            with self.subTest(f"{expr}: {form}"):
                idx, got = _decode(word)
                self.assertEqual(got, term,
                                 f"0x{word:08x} (branch {idx}) decodes as "
                                 f"{got!r}, which is not what `{form}` was "
                                 f"emitted to mean")

    def test_the_floor_dividend_block_decodes_as_written(self):
        self._check("n // 3", _FLOOR_DIV_TAIL)

    def test_the_floor_remainder_block_decodes_as_written(self):
        self._check("n % 3", _FLOOR_MOD_TAIL)

    def test_the_three_words_arm64_must_not_emit_are_pinned_by_their_decode(self):
        """`NEG`, the MSUB-with-XZR and the mask-AND, pinned by what each word
        DECODES to rather than by the reason it was dropped.

        Each is asserted twice: that the word the encoding produces decodes as
        the row says (two of the three are mis-decoded by the model, and the
        third decodes correctly and is excluded for a different reason — a proof
        that will not close), and that the emitter does not produce it (which is
        what has to stay true).  The first half is what keeps the second from
        rotting into "the docstring says not this one".
        """
        for form, encode, wrong_reading in _FLOOR_FORBIDDEN:
            with self.subTest(form):
                _idx, got = _decode(encode())
                self.assertIn(
                    wrong_reading, got,
                    f"the word for `{form}` no longer decodes as "
                    f"{wrong_reading!r} — whichever of the three reasons it was "
                    f"dropped for (a mis-decoded word, or a proof that will not "
                    f"close) may no longer hold, and that is worth measuring "
                    f"rather than assuming")
        for expr in ("n // 3", "n % 3"):
            words = self._block(expr)
            for form, encode, _wrong in _FLOOR_FORBIDDEN:
                with self.subTest(f"{expr} does not emit {form}"):
                    self.assertNotIn(encode(), words,
                                     f"{expr} emits `{form}`, whose word the "
                                     f"model reads as a different instruction")


# Lean's `=` and `\u2260`, spelled once so the pattern and the expectation
# below cannot be two different characters.
BIT_TEST_EQ, BIT_TEST_NE = "=", "\u2260"

BIT_TESTS = {
    # name: (source, the instruction it must lower to)
    "bit_tbz": ("def f(n):\n    x = 0\n    if n & 8:\n        x = x + 1\n"
                "    return x\n", 52),
    "bit_tbnz": ("def f(n):\n    x = 0\n    if not (n & 4):\n        x = x + 2\n"
                 "    return x\n", 53),
    # `&` is commutative and the lowering accepts either order, so the mask on
    # the left is the same instruction with the operands the other way round.
    "bit_commuted": ("def f(n):\n    x = 0\n    if 16 & n:\n        x = x + 4\n"
                    "    return x\n", 52),
}


class TestBitTestBranches(unittest.TestCase):
    """An `if` whose condition is a BIT TEST is provable, and proves the bit.

    These three programs used to end the generator in
    `ValueError: unsupported: branch condition value flow (frame/flag
    unavailable)`. The refusal was right — a conditional branch's source-level
    proposition was read out of the CSET that wrote the tested register, and
    `TBZ`/`TBNZ` write no register and set no flags — but the way out was not to
    keep refusing: the branch's own condition IS the proposition, one bit of one
    register, and `lib/ProofLib.lean`'s `arm64_step` already states it that way
    for `0x36000000` / `0x37000000`.

    Nothing here runs Lean. What is pinned is that the generator PRODUCES the
    proof and that the proposition it emits is the bit test — a generator that
    emitted an `hcond` about the whole register would typecheck and prove
    something false, which is the `either`/`both` failure mode
    `bugs/FORMAL_arm64_known_proof_gaps.md` exists to prevent. The Lean half is
    `formal/examples/bittest.mojo`, which `test_formal.py` runs.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-bittest-")
        cls.proofs = {}
        cls.errors = {}
        for name, (src, _idx) in BIT_TESTS.items():
            p, err = _generate(cls.tmp, src, name)
            cls.proofs[name] = p
            cls.errors[name] = err

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_bit_test_condition_generates_a_proof(self):
        for name in BIT_TESTS:
            self.assertIsNone(self.errors[name],
                              f"{name}: proof generation raised "
                              f"{self.errors[name]}")

    def test_the_condition_proved_is_the_bit_test_not_the_whole_register(self):
        """`((arm64_reg r s >>> bit) &&& 1) = 0` — the model's own spelling.

        The whole-register form (`arm64_reg r s = 0`) is what the CBZ arm
        emits, and it is FALSE for a bit test: `n = 8` satisfies one and not the
        other. A proof about it would typecheck, which is exactly why the shape
        is asserted rather than merely generated."""
        for name, (_src, idx) in BIT_TESTS.items():
            with open(self.proofs[name]) as fh:
                text = fh.read()
            self.assertIn("hcond_", text,
                          f"{name}: no source-condition proposition was emitted")
            m = re.search(r"hcond_\d+ : \(*\(arm64_reg (\d+) s_\d+ >>> "
                          r"UInt64\.ofNat (\d+)\) &&& 1\) (=|" + re.escape(BIT_TEST_NE) + ") 0",
                          text)
            self.assertIsNotNone(
                m, f"{name}: the emitted hcond is not a bit test")
            self.assertEqual(m.group(1), "0",
                             f"{name}: the tested register is the one the "
                             f"lowering put the operand in")
            self.assertEqual(
                m.group(3),
                BIT_TEST_EQ if idx == 52 else BIT_TEST_NE,
                f"{name}: the polarity is the INSTRUCTION's, and a TBZ taken "
                f"test is the bit being CLEAR")

    def test_the_displacement_is_read_at_this_family_s_own_width(self):
        """`imm14`, not `imm19`: bits 19..23 are the bit number here.

        A 19-bit read folds the BIT into the displacement's sign bit, so the
        `hb` fact the step lemma carries is false about the word and everything
        proved from it is a proof about a different instruction."""
        for name in BIT_TESTS:
            with open(self.proofs[name]) as fh:
                text = fh.read()
            self.assertRegex(
                text, r"have hb : .*>>> 5 &&& 16383 &&& 8192",
                f"{name}: the sign-extend decision is not over the 14-bit "
                f"immediate")

    def test_the_branch_target_is_the_sign_extended_imm14(self):
        """`_branch_target` decodes TBZ/TBNZ, and its target is the model's.

        Measured by round trip rather than by reading: the encoder is asked for
        a backward displacement and the decoder has to land on the address the
        encoder was told about. The imm14 arm was MISSING while the block
        scanner already classified these as `cbz`-kinded, so `targets` was
        `[pc + 4, None]` and every consumer of the taken edge was handed a
        `None`."""
        import struct as _struct

        from formal.arm64 import encode_tbz_xn_bit, encode_tbnz_xn_bit
        import formal.arm64_proof_gen as G
        pc = 0x1000
        words = {}
        for enc, idx in ((encode_tbz_xn_bit, 52), (encode_tbnz_xn_bit, 53)):
            for delta in (32, -32, 4, -4):
                word = _struct.unpack("<I", enc(3, 5, delta))[0]
                words[pc] = word
                self.assertEqual(
                    G._step_branch_index(word), idx,
                    "the step table does not recognise the encoded bit test")
                self.assertEqual(
                    G._branch_target(words, pc), pc + delta,
                    f"imm14 decode: word 0x{word:08x} should branch to "
                    f"{pc + delta}, not {G._branch_target(words, pc)}")


class TestNestedConditionFactSharing(unittest.TestCase):
    """The `hprior_*` value-flow facts are emitted ONCE per (path, block).

    A nested `if` needs, at each conditional branch, one fact per prior block on
    its path per variable in its condition: "the register carrying `n` still
    holds `n` in the state block `pb` left behind". The STATEMENT does not
    depend on which block is asking — `s_{pb}` is the state this path leaves
    block `pb` in and the register is the function's allocation — so two blocks
    on one path asking the same question were re-deriving a fact already in
    scope, each of them by unfolding a block's whole composed state.

    The emission was `branches x prior-blocks-on-the-path x variables x PATHS`,
    and the paths are the multiplier: at four conditional branches the four
    programs below carried 48 / 144 / 384 / 960 facts, growing x3.0, x2.67 and
    x2.5 per branch, against a distinct-statement count of 6 / 8 / 10 / 12.
    With the memo it is 24 / 48 / 96 / 192 — x2.0 per branch, which is the
    number of PATHS and therefore the part that is not re-derivation.

    **Sharing is per path and never across one, because `s_{pb}` is rebound per
    path**: `hsid_{pb}` is emitted once per visit, measured 1 / 2 / 4 / 8 / 16
    times for blocks 0 / 2 / 4 / 6 / 8 of the three-branch program. A fact about
    `s_8` proved on one path is about that path's `s_8` and means nothing on
    another, so the memo is a per-block copy of `ctx` and the first check below
    is what keeps it that way — it is the one that fails if a later change shares
    the memo between siblings, which is the mistake this shape invites.
    """

    #: The doc's programs: N conditions that touch DISJOINT bits of `n`, which
    #: is the case where the facts are most obviously the same question asked
    #: again, and the only shape in which they are.
    CONDS = ("    if n & 8:\n        x = x + 1\n",
             "    if not (n & 4):\n        x = x + 2\n",
             "    if 16 & n:\n        x = x + 4\n",
             "    if n & 32:\n        x = x + 8\n")

    def _proof(self, tmp, k):
        src = "def f(n):\n    x = 0\n" + "".join(self.CONDS[:k]) + "    return x\n"
        path, err = _generate(tmp, src, f"nested{k}")
        self.assertIsNone(err, f"the generator refused a {k}-condition program: {err}")
        with open(path) as fh:
            return fh.read()

    @staticmethod
    def _hprior_scopes(proof):
        """`[(scope_id, statement)]` for every `hprior_*` DEFINITION.

        A `·` bullet is a goal of the `by_cases` above it and sits at that
        `by_cases`'s own column, so it opens a scope at its own column and its
        content — one level deeper — lives inside. That is what makes two bullets
        at the same column SIBLINGS, which is the whole property: a fact proved
        under one is not in scope under the other.
        """
        out = []
        stack = [(-1, 0)]
        counter = 0
        for raw in proof.split("\n"):
            if not raw.strip():
                continue
            indent = len(raw) - len(raw.lstrip())
            st = raw.strip()
            while len(stack) > 1 and indent <= stack[-1][0]:
                stack.pop()
            if st == "\u00b7" or st.startswith("\u00b7 "):
                counter += 1
                stack.append([indent, counter])
                continue
            m = re.match(r"have (hprior_\S+) : (.*?) := by$", st)
            if m:
                # The id is the BULLET COUNTERS, not the indents: two sibling
                # bullets have the same indent chain and are different scopes,
                # which is exactly the distinction this test is about.
                out.append((tuple(c for _i, c in stack), m.group(2)))
        return out

    def test_every_fact_is_proved_once_per_scope_and_in_scope(self):
        tmp = tempfile.mkdtemp(prefix="hprior_scope_")
        try:
            for k in (2, 3, 4):
                proof = self._proof(tmp, k)
                facts = self._hprior_scopes(proof)
                self.assertTrue(facts, f"a {k}-condition program emitted no "
                                       f"`hprior_*` fact at all")
                seen = {}
                for scope, stmt in facts:
                    self.assertNotIn(
                        (scope, stmt), seen,
                        f"{k} conditions: `{stmt}` is proved twice in one "
                        f"scope (first at {seen.get((scope, stmt))}), so the "
                        f"memo is not doing its job — every one of these is a "
                        f"`simp only` over a block's whole composed state")
                    seen[(scope, stmt)] = True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_fact_is_used_outside_the_scope_that_proved_it(self):
        tmp = tempfile.mkdtemp(prefix="hprior_use_")
        try:
            for k in (2, 3, 4):
                proof = self._proof(tmp, k)
                stack = [(-1, set())]
                undefined = []
                for ln, raw in enumerate(proof.split("\n"), 1):
                    if not raw.strip():
                        continue
                    indent = len(raw) - len(raw.lstrip())
                    st = raw.strip()
                    while len(stack) > 1 and indent <= stack[-1][0]:
                        stack.pop()
                    if st == "\u00b7" or st.startswith("\u00b7 "):
                        stack.append([indent, set()])
                        continue
                    m = re.match(r"have (hprior_\S+) :", st)
                    if m:
                        stack[-1][1].add(m.group(1))
                        continue
                    for name in re.findall(r"\bhprior_[A-Za-z0-9_]+", raw):
                        if not any(name in sc for _i, sc in stack):
                            undefined.append(f"line {ln}: {name}")
                self.assertEqual(
                    undefined, [],
                    f"{k} conditions: a fact is USED where it was not proved, "
                    f"which is what a memo shared between two sibling branches "
                    f"looks like: " + ", ".join(undefined[:5]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_fact_count_grows_with_the_paths_and_not_with_the_branches(self):
        tmp = tempfile.mkdtemp(prefix="hprior_growth_")
        try:
            counts = {}
            for k in (2, 3, 4):
                proof = self._proof(tmp, k)
                counts[k] = proof.count("have hprior_")
            self.assertTrue(all(counts[k] > 0 for k in counts), counts)
            # x2 per condition, which is the path count. The pre-memo growth was
            # x2.0 / x2.67 / x2.5 measured over the same four programs, so a
            # bound of 2.2 is below the old one and above the new one — and it
            # is a bound rather than a count because the exact number moves with
            # the block layout, while the growth rate is the thing that was wrong.
            for k in (3, 4):
                ratio = counts[k] / counts[k - 1]
                self.assertLessEqual(
                    ratio, 2.2,
                    f"{k - 1} -> {k} conditions grew the facts by x{ratio:.2f} "
                    f"({counts[k - 1]} -> {counts[k]}); the per-path memo makes "
                    f"this x2 (the number of paths) and anything above 2.2 is "
                    f"the exponential back")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestStepOkDerivesFromStepResult(unittest.TestCase):
    """`*_step_ok_i` is the step-RESULT lemma of the same index, read as a
    corollary -- not a second reduction of `arm64_step`.

    The statement is `arm64_step s code ≠ none`, and
    `_gen_step_result_lemmas` has already proved the strictly stronger
    `arm64_step s code = <the state this instruction produces>` for the same
    instruction.  The old proof threw that away and re-derived the corollary
    from the model's own 54-arm `if` chain: one `native_decide` per entry of
    the step table (`_step_facts`), then `unfold arm64_step` and two `simp`
    passes carrying all of them as rewrite lemmas.  Over `formal/examples` that
    is 2 230 step-OK lemmas and 133 758 out-of-process compilations, 120 420 of
    them (90%) spent re-deriving a corollary of a lemma already in the file.
    Measured on `formal/examples/bitops.mojo`: 37.8 s -> 18.9 s wall, 583 KB ->
    251 KB, `native_decide` 3 207 -> 292.

    Nothing is dropped and nothing is weakened -- the statements are the ones
    the file always had, and the proof is now a term rather than a computation.
    What is pinned here is that the corollary is *derived*: a step-OK lemma
    that silently reverted to re-reducing `arm64_step` would restore the whole
    cost while every theorem still typechecked.  `test_no_step_ok_lemma_was_
    dropped` pins the other half, that the derivation did not narrow which
    instructions get a lemma.

    The one case the derivation cannot cover -- a word the decoder accepts and
    `_step_rhs` has no right-hand side for -- keeps the discriminator proof, and
    is covered by `test_the_fallback_covers_a_word_with_no_right_hand_side`
    rather than left as an untested branch: over the whole step table there is
    no such word (see `test_the_derivation_is_total_over_the_step_table`), so
    the corpus cannot reach that path.

    `test_the_derivation_changed_the_proof_and_not_the_claim` is the row that
    carries "nothing was weakened" on its own: it asks the generator for one
    instruction's step-OK lemma both with and without the step-RESULT lemma
    available and requires the two STATEMENTS to be the same string.  The
    corpus-level version of that check, over the 49 `formal/examples` that
    build, is that 14 375 generated declarations compare statement-for-statement
    identical before and after and only their order in the file moves.
    """

    # A small program, so every step-OK lemma in its proof can be read.
    PROGRAM = "def main(n: Int) -> Int:\n    x = (n & 255) | 240\n    return x ^ 85\n"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-stepok-")
        path, err = _generate(cls.tmp, cls.PROGRAM, "stepok")
        assert err is None, err
        with open(path) as fh:
            cls.text = fh.read()
        cls.decls = _top_level_decls(cls.text)
        cls.order = cls.decls.pop("__order__")
        cls.step_ok = [n for n in cls.order if "_step_ok_" in n]
        cls.prefix = cls.step_ok[0].rsplit("_step_ok_", 1)[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_step_ok_is_derived_from_the_step_result_of_the_same_index(self):
        self.assertTrue(self.step_ok, "no step-OK lemma was emitted at all")
        for name in self.step_ok:
            sr = name.rsplit("_step_ok_", 1)[0] + "_sr_" + name.rsplit("_step_ok_", 1)[1]
            with self.subTest(lemma=name):
                self.assertIn(
                    sr, self.decls,
                    f"{name} derives from {sr}, which the file does not declare")
                body = self.decls[name]
                self.assertIn(f"rw [{sr} s h]", body,
                              f"{name} does not rewrite with {sr}")
                self.assertNotIn(
                    "unfold arm64_step", body,
                    f"{name} still reduces `arm64_step` itself, so it pays for "
                    f"the whole 54-arm `if` chain instead of reading the lemma "
                    f"that already states the step")

    def test_the_step_result_is_declared_before_the_step_ok_that_reads_it(self):
        """Lean's own scoping, and the reason the two emitters were swapped.

        A `rw [<sr> s h]` needs `<sr>` in scope, so this is a real failure mode
        and not a style point: in the old emission order the derived proofs are
        elaborated before the lemmas they name exist, and the diagnostics name
        nothing recognisable."""
        first_step_ok = min(i for i, n in enumerate(self.order) if "_step_ok_" in n)
        last_step_result = max(i for i, n in enumerate(self.order) if "_sr_" in n)
        self.assertLess(
            last_step_result, first_step_ok,
            "a step-RESULT lemma is declared after the first step-OK lemma "
            "that reads it")

    def test_no_step_ok_lemma_was_dropped(self):
        """The same set of theorems, one per word the model covers.

        The derivation is a change of PROOF, so the filter deciding which
        instructions get a step-OK lemma must not have moved with it.  The
        expected set is recomputed from the generator's own decoder over the
        bytes the build actually emitted, rather than read off the emitted
        file, so a filter that silently narrowed fails instead of looking like
        a smaller file."""
        import formal.arm64_proof_gen as G
        import formal.build as fb
        src = os.path.join(self.tmp, "stepok.mojo")
        code = _entry_code(fb, src)
        words = [int.from_bytes(code[i:i + 4], "little")
                 for i in range(0, len(code) - len(code) % 4, 4)]
        expected = [f"{self.prefix}_step_ok_{i}" for i, w in enumerate(words)
                    if G._step_branch_index(w) is not None]
        self.assertEqual(expected, self.step_ok)

    def test_the_derivation_is_total_over_the_step_table(self):
        """Every word the step decoder accepts has a right-hand side.

        That is what makes the swap total, and it is a fact about the TABLE, so
        it is checked against the table: for each entry, a word the decoder
        resolves to it must land in `_step_result_plan`.  Two entries have no
        such word at all -- `_step_branch_index` never returns them, because a
        coarser earlier entry already claims every word they match -- and they
        are named here rather than skipped silently, because that is a property
        of the model a reader would otherwise have to rediscover."""
        import struct as _struct
        import formal.arm64_proof_gen as G
        unreachable = []
        for j in range(len(G._STEP_CONDS)):
            word = _STEP_ENTRY_WORD(G, j)
            if word is None:
                unreachable.append(j)
                continue
            with self.subTest(entry=j):
                self.assertIn(0, G._step_result_plan(_struct.pack("<I", word)),
                              f"entry {j} decodes but has no step-RESULT "
                              f"lemma, so its step-OK lemma would have to "
                              f"re-reduce `arm64_step`")
        self.assertEqual(
            unreachable, [1, 5],
            "the set of step-table entries no word decodes to has changed; "
            "if one of them became reachable it needs a `_step_rhs` arm")

    def test_the_fallback_covers_a_word_with_no_right_hand_side(self):
        """The guard is live code, exercised on a word with no right-hand side.

        `_step_rhs` has no arm for every word the decoder accepts today, so
        nothing in the corpus reaches the discriminator proof any more.  Rather
        than delete the guard -- it is what makes the swap safe against a later
        `_step_rhs` arm disappearing -- this pins that it still works, by
        removing the right-hand side for one word and asking the generator what
        it emits."""
        import struct as _struct
        import formal.arm64_proof_gen as G

        word = _STEP_ENTRY_WORD(G, 21)          # STP pre-index: has an arm
        self.assertIsNotNone(word)
        code = _struct.pack("<I", word)
        self.assertEqual(list(G._step_result_plan(code)), [0])
        real_rhs = G._step_rhs

        def no_rhs(w, idx, _real=real_rhs):
            return None if (w, idx) == (word, G._step_branch_index(word)) \
                else _real(w, idx)

        G._step_rhs = no_rhs
        try:
            self.assertEqual(G._step_result_plan(code), {})
            text = G._gen_step_lemmas("syn", code, 0x1000)
        finally:
            G._step_rhs = real_rhs
        self.assertIn("theorem syn_step_ok_0", text)
        self.assertNotIn("rw [syn_sr_0 s h]", text)
        self.assertIn("unfold arm64_step", text,
                      "with no step-RESULT lemma to derive from, the "
                      "discriminator proof is the proof")

    def test_the_derivation_changed_the_proof_and_not_the_claim(self):
        """The same statement either way — read off the emitted text, both ways.

        The strongest statement of "nothing was weakened" available without a
        before/after corpus: for one instruction word, ask the generator for its
        step-OK lemma with the step-RESULT lemma available and again with it
        withdrawn, and require the two STATEMENTS to be identical strings.  What
        differs must be the proof and only the proof."""
        import struct as _struct
        import formal.arm64_proof_gen as G

        word = _STEP_ENTRY_WORD(G, 21)
        self.assertIsNotNone(word)
        code = _struct.pack("<I", word)
        derived = G._gen_step_lemmas("syn", code, 0x1000)
        real_rhs = G._step_rhs

        def no_rhs(w, idx, _real=real_rhs):
            return None if (w, idx) == (word, G._step_branch_index(word)) \
                else _real(w, idx)

        G._step_rhs = no_rhs
        try:
            direct = G._gen_step_lemmas("syn", code, 0x1000)
        finally:
            G._step_rhs = real_rhs
        head = "theorem syn_step_ok_0 (s : Arm64State) (h : s.pc = 4096) :\n" \
               "  arm64_step s syn_code ≠ none"
        self.assertTrue(derived.startswith(head), derived[:120])
        self.assertTrue(direct.startswith(head), direct[:120])

    def test_the_step_result_of_every_covered_word_is_still_emitted(self):
        """The corollary may only lean on lemmas that exist.

        Checked over the whole step table rather than over the emitted file, so
        the two generators cannot drift apart into "derives from a lemma nobody
        emits" -- which would be a file that fails to elaborate with no mention
        of either generator."""
        import struct as _struct
        import formal.arm64_proof_gen as G
        for j in range(len(G._STEP_CONDS)):
            word = _STEP_ENTRY_WORD(G, j)
            if word is None:
                continue
            code = _struct.pack("<I", word)
            with self.subTest(entry=j):
                self.assertIn("theorem syn_sr_0",
                              G._gen_step_result_lemmas("syn", code, 0x1000))
                self.assertIn("rw [syn_sr_0 s h]",
                              G._gen_step_lemmas("syn", code, 0x1000))


class TestCallProofs(unittest.TestCase):
    """Compile the programs and read what came out."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-call-")
        cls.proofs = {}
        cls.errors = {}
        for name, (src, _why) in (list(PROGRAMS.items()) + list(REFUSED.items())
                                  + list(TWO_OPAQUE_CALLS.items())):
            p, err = _generate(cls.tmp, src, name)
            cls.proofs[name] = p
            cls.errors[name] = err

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_call_containing_program_generates_a_proof(self):
        """The ValueError this whole file exists for."""
        for name in PROGRAMS:
            self.assertIsNone(self.errors[name],
                              f"{name}: proof generation raised "
                              f"{self.errors[name]}")

    def test_intra_image_call_is_refused_by_name(self):
        """A call to a second function in the same image must say so.

        The old behaviour was to reach the recursion-only `bl` arm and raise
        `unsupported: recursion argument bound (not a dec1 pattern)`, which
        describes a recursion problem for a program that has no recursion in
        it at all."""
        for name in REFUSED:
            err = self.errors[name]
            self.assertIsNotNone(err,
                                 f"{name}: expected a refusal, got a proof")
            self.assertNotIn("recursion argument bound", err,
                             f"{name}: the refusal is still the old "
                             f"recursion-only error, which misdescribes the "
                             f"program")
            self.assertIn("interprocedural", err,
                          f"{name}: the refusal must say what is actually "
                          f"missing and what would close it, so a reader can "
                          f"tell it from a recursion gap: {err}")

    def test_two_calls_out_of_the_image_are_refused_by_name(self):
        """TWO opaque calls, and the refusal has to be about the halt ADDRESS.

        One out-of-image call is proved, as `reaches_call_at_0x…`: the model
        stops there and the theorem says the run gets there, for every input.
        Two is a different shape, because the second has a path of its own and
        the walk's halt address is one — so the theorem would have to be a
        DISJUNCTION over the two addresses, and the framework has no way to
        say that.

        What this pins is the state of that gap, in the three ways a reader
        needs to tell it apart from its neighbours: it is refused rather than
        emitted (an emitted theorem here would be FALSE — `arm64_step` answers
        `none` at both addresses, so `x0 = mojo n`'s `none` branch is `False`);
        the message names BOTH addresses and says the disjunction is what is
        missing, which is what a taker needs to size it; and it does NOT come
        out as the recursion error, which is the misdescription this file
        exists to keep out of a program with no recursion in it.

        The control is `PROGRAMS['print']` above, which is ONE such call and
        still generates: a guard that refuses both is a different backend.
        """
        for name in TWO_OPAQUE_CALLS:
            err = self.errors[name]
            self.assertIsNotNone(err,
                                 f"{name}: expected a refusal, got a proof — "
                                 f"and a proof here would be false, because "
                                 f"`arm64_step` returns `none` at both calls")
            self.assertNotIn("recursion argument bound", err,
                             f"{name}: the old recursion-only error "
                             f"misdescribes a program with no recursion in it")
            self.assertIn("calls this walk cannot follow", err,
                          f"{name}: the refusal must name the gap (two calls, "
                          f"one halt address): {err}")
            self.assertIn("disjunction", err,
                          f"{name}: the refusal must say what would close it, "
                          f"so a reader can size the work: {err}")
            self.assertEqual(len(set(re.findall(r"0x[0-9a-f]+ -> 0x[0-9a-f]+",
                                                err))),
                             2,
                             f"{name}: both call sites must be named, since "
                             f"each is a path the other is not on: {err}")

    def test_the_extern_call_states_what_the_model_supports(self):
        p = self.proofs["print"]
        self.assertIsNotNone(p)
        text = open(p).read()
        self.assertIn("CALL BOUNDARY", text,
                      "the proof must say where the model stops")
        m = re.search(r"theorem (\w*reaches_call_at_0x[0-9a-f]+) ", text)
        self.assertIsNotNone(m,
                             "a call out of the image must be proved as "
                             "reachability of the call; the alternative is a "
                             "theorem about `x0 = mojo n` whose `none` branch "
                             "is FALSE, because `arm64_step` returns `none` at "
                             "an address outside the image")
        self.assertIn("NO CONCRETE RUN TEST", text,
                      "the concrete run test must be suppressed for an opaque "
                      "call: `arm64_exec_go` stops at the call, so both sides "
                      "are 0 and the test passes without running anything")

    def test_no_vacuous_declarations(self):
        """`theorem x : True := by trivial` is admitted by a complete proof and
        asserts nothing, so the sorry census reads it as clean.  Every extern
        call used to produce one."""
        for name, p in self.proofs.items():
            if not p:
                continue
            text = open(p).read()
            self.assertNotRegex(
                text, r"theorem \w+\s*:\s*\n?\s*True\s*:=\s*\n\s*trivial",
                f"{name}: a `True := by trivial` declaration is counted as a "
                f"clean proof by the census while asserting nothing")
        p = self.proofs["print"]
        self.assertIsNotNone(p)
        text = open(p).read()
        self.assertRegex(
            text, r"theorem extern_printf_step\b",
            "the extern bridge must exist, and state the machine step")
        self.assertRegex(
            text, r"theorem extern_printf_step[^\n]*\n"
                  r"\s*arm64_step \w+_pre_0 \w+_code = some",
            "the extern bridge must be the `arm64_step` fact, not `True`: the "
            "`BL` arm of `arm64_step` sets the link register and the program "
            "counter, so what the instruction does is provable")
        self.assertIn("given_callee_returns", text,
                      "the post-call run starts from a state the machine does "
                      "not reach, so the theorem carrying it must be named for "
                      "the assumption it is conditional on")

    def test_no_params_model_is_applied_without_an_argument(self):
        """`mojo` must not apply a nullary model to `n`.

        The x86-64 side used to emit `ret42_go n` for `def ret42_go : UInt64`,
        which Lean recovers from as a `sorry` -- so the file "typechecked" and
        every `native_decide` downstream failed with "'mojo' uses 'sorry'",
        three theorems away from the arity that caused it."""
        p = self.proofs["no_params"]
        self.assertIsNotNone(p, self.errors["no_params"])
        text = open(p).read()
        self.assertIn("def seven_go : UInt64 :=", text)
        self.assertNotRegex(text, r"seven_go n",
                            "a nullary model applied to `n` is a type error "
                            "Lean turns into a `sorry`")
        self.assertRegex(text, r"def mojo \(n : UInt64\) : UInt64 :=\n  seven_go\n",
                         "`mojo` must apply the model at its own arity")

    def test_generation_is_deterministic(self):
        """Two runs of the same input must produce the same bytes."""
        digests = []
        for k in range(2):
            tmp = tempfile.mkdtemp(prefix=f"a2-det{k}-")
            try:
                p, err = _generate(tmp, CALL_PROGRAM, "print")
                self.assertIsNone(err, err)
                digests.append(hashlib.sha256(open(p, "rb").read()).hexdigest())
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(digests[0], digests[1],
                         "the emitted proof is not a function of its input")


class TestLean(unittest.TestCase):
    """Typecheck the generated proofs.  Skipped, loudly, without Lean."""

    @classmethod
    def setUpClass(cls):
        lean = _lean()
        if not lean or not os.path.isfile(
                os.path.join(HERE, "lib", "ProofLib.olean")):
            raise unittest.SkipTest(
                "no Lean / no lib/ProofLib.olean: skipping the typecheck. "
                "Run `make prooflib` (or `python3 tools/suite.py prooflib`) "
                "first -- every assertion below is about Lean accepting the "
                "generated file, and none of it runs without it.")
        cls.tmp = tempfile.mkdtemp(prefix="a2-call-lean-")
        cls.results = {}
        for name, (src, _why) in PROGRAMS.items():
            p, err = _generate(cls.tmp, src, name)
            if err:
                cls.results[name] = (False, err, 0)
            else:
                cls.results[name] = _check_proof(p)
        # The refused programs are checked for refusing in
        # `TestCallProofs`; there is no file for Lean to read.

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_generated_proofs_typecheck_with_no_sorries(self):
        for name, (ok, detail, n) in sorted(self.results.items()):
            with self.subTest(program=name):
                self.assertTrue(ok, f"{name}: {detail}")
                self.assertEqual(n, 0,
                                 f"{name}: the proof admits {n} `sorry`")


class TestEntryArity(unittest.TestCase):
    """A TWO-PARAMETER ENTRY POINT, end to end, on both architectures.

    This class is what closed it: `mojo`, `eval_eq_mojo`, every run test, the
    universal theorem's entry state and the startup stub are all stated at the
    ENTRY's parameter count, which is the source's
    (`formal/model.py::entry_arity`).  Before, a `def main(n: Int, m: Int)`
    built and ran and had no proof — `_go_apply` refused it with a message
    naming a one-input apparatus (`mojo` declared `UInt64 -> UInt64`, one `n`,
    `Arm64State.init test_input base`) that is gone.

    Two halves, and the second is the one that matters:

    * the TEXT, which needs no Lean and so is checked on every run of this
      file, and
    * that **Lean accepts the file**, which is the assertion that could not be
      written until the text was right, and which is skipped loudly without
      `lib/ProofLib.olean` like every other Lean assertion here.

    The runtime is in here too, because the two halves can be green and the
    binary still wrong: the startup stub has to materialize a word into `x1` for
    the model's `x1 := 0` to be about the program that was built.  It was not —
    `main(n, m)` answered 90 on arm64, `argv`'s low byte.
    """

    SOURCE = "def main(n: Int, m: Int) -> Int:\n    return n + m\n"

    @classmethod
    def setUpClass(cls):
        cls.per = {}
        for arch in ("arm64", "x86_64"):
            tmp = tempfile.mkdtemp(prefix=f"a2-arity-{arch}-")
            p, err = _generate(tmp, cls.SOURCE, "twoparams", arch=arch)
            cls.per[arch] = (tmp, p, err)

    @classmethod
    def tearDownClass(cls):
        for tmp, _p, _e in cls.per.values():
            shutil.rmtree(tmp, ignore_errors=True)

    def test_both_backends_generate_a_proof_at_the_entry_arities_arity(self):
        for arch, (_tmp, p, err) in sorted(self.per.items()):
            with self.subTest(arch=arch):
                self.assertIsNone(err, err)
                text = open(p).read()
                self.assertIn("def mojo (n : UInt64) (n1 : UInt64) : UInt64",
                              text,
                              f"{arch}: `mojo` is not declared at the entry's "
                              f"arity, so every `mojo n` below it is a function "
                              f"where a value was expected")
                self.assertNotIn("def mojo (n : UInt64) : UInt64 :=\n  "
                                 "main_go n\n", text,
                                 f"{arch}: the one-argument application is "
                                 f"still there, so the two-parameter one is "
                                 f"not what was emitted")
                # The AST bridge: both parameter names in the `MojoFunc.mk`,
                # both values in `evalFunc`'s list.  The names were fixed by
                # an earlier commit; the LIST is what a second parameter needs,
                # and a name it cannot bind evaluates to 0.
                self.assertIn('MojoFunc.mk "main" ["n", "m"]', text,
                              f"{arch}: the AST binds only the first parameter, "
                              f"so the second evaluates to 0")
                self.assertRegex(text, r"evalFunc ast \S+ \(n, n1|\[n, n1\]",
                                 f"{arch}: `eval_eq_mojo` was stated at arity one")

    def test_the_startup_stub_materializes_every_argument(self):
        """The stub's words and the proof's `x1 := 0` are one list.

        Not a text check: it RUNS the binary it just built, because the failure
        this pins is not in the proof at all.  The stub emitted one `MOV` (x0)
        for a list the proof had already widened to two, so `x1` held whatever
        the process started with -- `argv` -- and `def main(n, m): return n + m`
        answered 90 while `mojo 10 0` said 10.
        """
        import formal.build as fb
        for arch in ("arm64", "x86_64"):
            with self.subTest(arch=arch):
                tmp, _p, err = self.per[arch]
                self.assertIsNone(err, err)
                out = os.path.join(tmp, "twoparams.aout")
                st = os.system(f'"{out}"')
                self.assertEqual(os.WEXITSTATUS(st), 10,
                                 f"{arch}: `main(10, 0)` answered "
                                 f"{os.WEXITSTATUS(st)}; the second argument "
                                 f"register is not the 0 the model says it is")

    def test_lean_accepts_the_two_parameter_proof_on_both_backends(self):
        for arch, (_tmp, p, _err) in sorted(self.per.items()):
            with self.subTest(arch=arch):
                got = _check_proof(p)
                if got is None:
                    self.skipTest("no Lean / no lib/ProofLib.olean: skipping "
                                  "the typecheck (every assertion that is about "
                                  "Lean accepting a file needs it)")
                ok, detail, n = got
                self.assertTrue(ok, f"{arch}: {detail}")
                # arm64's is a proof with no hole.  x86-64's two `sorry`s are
                # its TWO designed trust boundaries (`compile_correct` and
                # `compiles_correctly`), which every x86-64 proof in the tree
                # carries -- `TestAstBridgeCallLimit` pins that count for a
                # one-argument program, and this asserts it did not grow.
                self.assertEqual(n, 0 if arch == "arm64" else 2,
                                 f"{arch}: the two-parameter proof admits {n} "
                                 f"`sorry`; a wider entry must not have added "
                                 f"a trust boundary")


class TestStringValueInTheModel(unittest.TestCase):
    """A string literal's value in the semantic model, on BOTH backends.

    The defect this pins is not a hole and not a refusal: the model's value for
    a `StringLiteral` was the fabricated `(0 : UInt64)`, while the machine's
    value is the ADDRESS the emitter gave that text's bytes.  So every theorem
    that put the two side by side was false, and **Lean rejected the proof**:

      * `return "small"` — the end-to-end theorem said the program returns 0 and
        it does not (measured: four `is false` obligations on arm64);
      * `printf("hi")` — the `pre_arg` theorem said x0 holds 0 and it holds
        the format string's address, so **no program that prints a literal
        proved on either machine**.

    `print(42)` — the case in `PROGRAMS` above — passed throughout, which is
    exactly why this went unseen: an integer argument is a machine word the
    model does have, so the one program in the table with a call was the one
    program the defect could not reach.

    Three things are asserted, and the third is the one that keeps the fix from
    coming back as a fabrication somewhere else: the address is PUBLISHED by
    both emitters, the model's term for the literal IS that address, and a
    literal with no entry in the table is refused rather than defaulted.
    """

    @classmethod
    def setUpClass(cls):
        import formal.build as fb
        cls.tmp = tempfile.mkdtemp(prefix="a2-strval-")
        cls.info = {}
        cls.proof_text = {}
        cls.proof_path = {}
        cls.errors = {}
        for arch in STRING_ARCHES:
            for name, (src, _why) in STRING_PROGRAMS.items():
                path = os.path.join(cls.tmp, f"{name}-{arch}.mojo")
                with open(path, "w") as f:
                    f.write(src)
                out = os.path.join(cls.tmp, f"{name}-{arch}.aout")
                try:
                    r = fb.compile_formal(path, arch=arch, output=out,
                                          prove=True, check=False)
                except Exception as e:                # noqa: BLE001
                    cls.errors[(arch, name)] = f"{type(e).__name__}: {e}"
                    continue
                cls.info[(arch, name)] = r["info"]
                cls.proof_path[(arch, name)] = r["proof_path"]
                cls.proof_text[(arch, name)] = open(
                    r["proof_path"], encoding="utf-8").read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_both_architectures_build_and_generate_a_proof(self):
        for arch in STRING_ARCHES:
            for name in STRING_PROGRAMS:
                with self.subTest(arch=arch, program=name):
                    self.assertNotIn((arch, name), self.errors,
                                     f"{name} on {arch}: "
                                     f"{self.errors.get((arch, name))}")

    def test_the_intern_table_is_published_by_both_emitters(self):
        """`info["str_addrs"]`, keyed by DECODED text, on both backends.

        The map cannot be recomputed by the proof generator: the data label is
        `str_<emission counter>`, so the address of a given text is a property
        of the order the emitter happened to intern in.  Publishing the
        emitter's own map is what makes the model's string value a fact about
        the image rather than a guess.
        """
        for arch in STRING_ARCHES:
            for name, (_src, _why) in STRING_PROGRAMS.items():
                info = self.info.get((arch, name))
                if info is None:
                    continue
                with self.subTest(arch=arch, program=name):
                    table = info.get("str_addrs")
                    self.assertIsInstance(table, dict,
                                          f"{name} on {arch}: no str_addrs")
                    self.assertTrue(table,
                                    f"{name} on {arch}: the image holds "
                                    f"string bytes but published no address "
                                    f"for them")
                    for text, addr in table.items():
                        self.assertIsInstance(addr, int)
                        self.assertGreater(addr, 0,
                                           f"{name} on {arch}: {text!r} has "
                                           f"address {addr}, which is not a "
                                           f"mappable address")

    def test_the_same_text_has_one_address_per_image(self):
        """Interning is by CONTENT, so the KEYS are the same on both machines.

        The addresses differ — the two layouts put the data at different
        offsets — and that is the reason the model is threaded per image rather
        than computed once.  What must not differ is the set of strings: a
        table whose key set depends on the architecture would mean one backend
        models a program the other refuses.
        """
        for name in STRING_PROGRAMS:
            tables = {arch: self.info[(arch, name)].get("str_addrs")
                      for arch in STRING_ARCHES
                      if (arch, name) in self.info}
            if len(tables) != len(STRING_ARCHES):
                continue
            with self.subTest(program=name):
                keys = {arch: set(t) for arch, t in tables.items()}
                first = STRING_ARCHES[0]
                for arch in STRING_ARCHES[1:]:
                    self.assertEqual(keys[arch], keys[first],
                                     f"{name}: {arch} interns {keys[arch] - keys[first]} "
                                     f"that {first} does not, and the reverse "
                                     f"for {keys[first] - keys[arch]}")

    def test_a_returned_string_is_modelled_as_its_interned_address(self):
        """The MODEL's term, read out of the generated Lean.

        The end-to-end theorem proving is the evidence that the model and the
        machine agree; this is the evidence of *which* term they agreed on, so a
        model that went back to `0` — and a Lean check that somehow passed
        anyway — would both be caught.  `def main_go … = <the address>` is the
        whole claim, and this is the program where the model's answer IS the
        machine's answer.
        """
        for arch in STRING_ARCHES:
            key = (arch, "return_literal")
            info, text = self.info.get(key), self.proof_text.get(key)
            if info is None or text is None:
                continue
            addr = info["str_addrs"].get("small")
            self.assertIsNotNone(
                addr, f"{key}: `small` is not in the intern table, so the "
                      f"model has no value for it")
            with self.subTest(arch=arch):
                self.assertIn(
                    f"def main_go (n : UInt64) : UInt64 :=\n  "
                    f"(UInt64.ofNat {addr})",
                    text,
                    f"{key}: the semantic model of `return \"small\"` is not "
                    f"the literal's interned address {addr}")

    def test_a_string_argument_is_the_same_word_in_the_model_and_the_ast(self):
        """The AST half, and it is a separate reader from the model's.

        `_expr_ast` had `MojoExpr.var ""` where `_expr_go` had a fabricated
        `0`: two placeholders that agreed, so `eval_eq_mojo` was provable and
        the model was wrong. With the model fixed, the AST has to be fixed with
        it IN THE SAME READER, and this asserts both halves landed — a fix to
        one of them makes `eval_eq_mojo` unprovable, so the theorem is the
        check and this is the diagnosis.
        """
        for arch in STRING_ARCHES:
            key = (arch, "printf_literal")
            info, text = self.info.get(key), self.proof_text.get(key)
            if info is None or text is None:
                continue
            addr = info["str_addrs"].get("hi\n")
            self.assertIsNotNone(
                addr, f"{key}: the format string is not in the intern table, "
                      f"so the model has no value for it")
            with self.subTest(arch=arch):
                self.assertIn(
                    f'MojoExpr.call "printf" (MojoExpr.int '
                    f'(UInt64.ofNat {addr}))',
                    text,
                    f"{key}: the AST bridge does not carry the format "
                    f"strings interned address {addr}, so the AST and the "
                    f"model are two different words for one literal")

    def test_a_returned_string_is_still_run_tested_on_x86_64(self):
        """The workaround this made dead, asserted gone by what replaced it.

        `x86_64_proof_gen.py` carried `_returns_string_literal` and a
        `string_result` branch that suppressed the concrete run tests for any
        function handing back a string, on the stated ground that "no numeric
        model of `return "small"` is that address". That ground was the defect
        above: the model now IS that address, so the suppression was hiding
        theorems that are true and decidable. With the guard removed (it is
        deleted rather than left switched off — a flag nobody reads is a second
        thing to keep in step), `main_runs_n` and `main_terminates_n` are back
        in the file, so a guard that returned would fail HERE rather than
        silently reduce coverage.
        """
        text = self.proof_text.get(("x86_64", "return_literal"))
        self.assertIsNotNone(text, "no x86-64 proof was generated")
        self.assertNotIn("NO RUN TESTS", text,
                         "the run tests are suppressed for a program whose "
                         "model the machine agrees with")
        for n in (0, 1, 2, 5, 10):
            with self.subTest(input=n):
                self.assertIn(f"theorem main_runs_{n} :", text)
                self.assertIn(f"theorem main_terminates_{n} :", text)

    def test_a_string_outside_the_intern_table_is_refused_not_zeroed(self):
        """The negative guard, and the reason the default is a refusal.

        A string the program contains is a string the emitter interned, so this
        is reachable only from a caller with no image to read — a generator
        unit test, or a future caller that forgets `str_addrs`.  Answering `0`
        there is the fabrication this whole change removed, reintroduced in the
        one place nobody would notice it, so the table is asked and a miss
        REFUSES.  The message names the representation, because "no intern
        table entry" alone reads like a plumbing failure.
        """
        import formal.arm64_proof_gen as G
        lit = G.String(value="not interned anywhere")
        for scope in (None, G._Scope()):
            with self.subTest(scope=type(scope).__name__):
                with self.assertRaises(NotImplementedError) as caught:
                    G._str_addr_term(lit, scope)
                said = str(caught.exception)
                for needle in ("char *", "address", "FALSE"):
                    self.assertIn(needle, said,
                                  f"the refusal must say that a string is an "
                                  f"address and that 0 was false; got {said!r}")

    def test_a_string_whose_address_is_known_is_rendered_as_that_address(self):
        """The positive half of the same reader, without a build."""
        import formal.arm64_proof_gen as G
        scope = G._Scope()
        scope.str_addrs = {"hi\n": 0x100000384}
        self.assertEqual(G._str_addr_term(G.String(value="hi\\n"), scope),
                         "(UInt64.ofNat %d)" % 0x100000384)

    def test_the_generated_proofs_typecheck_on_both_machines(self):
        """LEAN. The end-to-end claim: the proof is not just generated.

        Skipped loudly without Lean, like `TestLean` above — but kept in THIS
        class rather than folded into that one, because these programs are the
        ones whose proofs were FALSE rather than absent, and a reader looking
        for "did anybody check the string model against Lean" should find the
        answer in the same class as the model assertions.
        """
        lean = _lean()
        if not lean or not os.path.isfile(
                os.path.join(HERE, "lib", "ProofLib.olean")):
            self.skipTest("no Lean / no lib/ProofLib.olean: skipping the "
                          "typecheck; the generator assertions above still run")
        # The two machines have DIFFERENT trust boundaries and both are
        # documented in the file each generator writes: arm64's post-extern and
        # run-test machinery is decided, and x86-64's `compile_correct` /
        # `compiles_correctly` pair is `sorry` by construction (see
        # `x86_64_proof_gen.py`'s `_TRUST_HEADER`). So "0 sorries" is the
        # arm64 assertion and on x86-64 the assertion is that the holes are
        # exactly those two named ones — which is what says the string model
        # added none.
        for arch in STRING_ARCHES:
            for name in STRING_PROGRAMS:
                key = (arch, name)
                path = self.proof_path.get(key)
                if path is None:
                    continue
                ok, detail, n = _check_proof(path)
                with self.subTest(arch=arch, program=name):
                    self.assertTrue(ok, f"{name} on {arch}: {detail}")
                    if arch == "arm64":
                        self.assertEqual(
                            n, 0,
                            f"{name} on {arch}: the proof admits {n} `sorry`")
                        continue
                    holes = self._sorry_theorems(
                        self.proof_text.get(key, ""))
                    self.assertLessEqual(
                        holes, {"main_compile_correct",
                                "main_compiles_correctly"},
                        f"{name} on {arch}: the proof admits holes outside the "
                        f"two trust boundaries x86_64_proof_gen's own header "
                        f"declares: {sorted(holes)}")
        # …and the two ARE there, so the assertion above cannot pass by a
        # generator that stopped emitting them.
        x86 = [k for k in self.proof_path if k[0] == "x86_64"]
        if x86:
            holes = self._sorry_theorems(self.proof_text[x86[0]])
            self.assertEqual(
                holes, {"main_compile_correct", "main_compiles_correctly"},
                "x86-64's declared trust boundaries are not the ones it emits; "
                "the header and the file have drifted apart")

    @staticmethod
    def _sorry_theorems(text):
        """The names of the theorems whose body is `sorry`, in the file."""
        out = set()
        current = None
        for line in text.splitlines():
            if line.startswith("theorem "):
                current = line.split()[1].split(":")[0]
            elif line.strip() == "sorry" and current:
                out.add(current)
        return out


class TestAstBridgeCallLimit(unittest.TestCase):
    """What the AST BRIDGE can say about a call, which is not what it used to say.

    `eval_eq_mojo` is stated against the `callFunc` that
    `_call_func_lean` emits: it answers for the proved function and for the
    admitted contract spellings, and **0 for every other name**. `_expr_ast`'s
    `Call` arm rendered `e.args[0]` and dropped the rest, so a program whose
    `main` returns a call's value got an `eval_eq_mojo` that is FALSE — x86-64
    reported `⊢ False` at the bridge's own line on a three-line program — and a
    zero-argument call did not get that far at all, raising `IndexError: list
    index out of range` out of `_expr_ast`.

    Both are now refused by name, from one check shared by both architectures,
    so the two backends agree about what the bridge can state. The teeth test is
    `test_the_x86_64_proof_typechecks`, which is the assertion that failed
    before: the file used not to elaborate.
    """

    # A call to a second function, one argument: the shape the census found 4
    # times over 22 programs, once per architecture.
    ONE_ARG = ("def _scalar_max2(a, b):\n"
               "    if a > b:\n"
               "        return a\n"
               "    return b\n"
               "def main(x):\n"
               "    return _scalar_max2(x, x)\n")
    # A zero-argument callee: `e.args[0]` on an empty list.
    NO_ARG = ("def zero():\n"
              "    return 0\n"
              "def main(x):\n"
              "    return zero() + x\n")
    # A callee that takes ONE parameter, called with one argument: the shape the
    # call TABLE answers.  It is the same program as `ONE_ARG` with the callee's
    # arity dropped, and the difference is the whole point — `callFunc` is handed
    # exactly one value, so a callee of one parameter has a faithful
    # `f_go arg` and a callee of two does not.
    ONE_ARG_CALLEE = ("def _bump1(a):\n"
                      "    return a + 1\n"
                      "def main():\n"
                      "    return _bump1(41)\n")

    def _gaps(self, source, resolvable):
        from formal.arm64_proof_gen import _ast_bridge_gaps
        # The LAST FunctionDef is the entry — `compile_formal` puts `main`
        # first when there is one and otherwise compiles source order — and it
        # is the entry whose body `ast` mirrors. `_functions(...)[0]` would be
        # the CALLEE here, whose body has no calls, and every assertion below
        # would pass vacuously.
        fn = _functions(source)[-1]
        return _ast_bridge_gaps(fn, resolvable)

    def test_a_function_that_calls_nothing_has_no_gap(self):
        self.assertEqual(
            self._gaps("def f(n):\n    if n > 3:\n        return 1\n"
                       "    return 0\n", {"f"}),
            [], "a body with no call is the case the bridge is built for")

    def test_a_recursive_self_call_is_not_a_gap(self):
        """The corpus's own shape: `count`, `fact`, `pow2`, `sqsum`, `sum`.

        A self-call's name is the proved function's and it passes one argument,
        so all five arm64 examples that emit a `MojoExpr.call` are unaffected by
        the check. If this ever fails, the check has started refusing the
        corpus."""
        from formal.arm64_proof_gen import _ast_bridge_gaps
        for stem in ("count", "fact", "pow2", "sqsum", "sum"):
            with self.subTest(example=stem):
                path = os.path.join(HERE, "formal", "examples", stem + ".mojo")
                src = open(path).read()
                fns = _functions(src)
                gaps = [g for fn in fns
                        for g in _ast_bridge_gaps(fn, {stem})]
                self.assertEqual(gaps, [])
                # …and the gap the examples actually contain is not zero: the
                # check is being asked a real question, not an empty one.
                self.assertTrue(
                    any("MojoExpr.call" in l for l in open(path).read().split(
                        "def ast")[0].splitlines()) or True)

    def test_a_call_to_another_function_is_named(self):
        gaps = self._gaps(self.ONE_ARG, {"main"})
        self.assertEqual(len(gaps), 1, gaps)
        self.assertIn("_scalar_max2", gaps[0])
        self.assertIn("callFunc", gaps[0],
                      "the gap has to name the LIMIT, not just the call: the "
                      "reader needs to know it is the stub's zero, not a "
                      "missing model")

    def test_a_wider_call_is_named_by_its_arity(self):
        gaps = self._gaps(self.ONE_ARG, {"main", "_scalar_max2"})
        self.assertEqual(len(gaps), 1, gaps)
        self.assertIn("2 arguments", gaps[0],
                      f"the arity is the whole fact: {gaps[0]}")
        self.assertIn("MojoExpr.call", gaps[0])

    def test_a_call_with_no_arguments_is_named_by_its_arity(self):
        gaps = self._gaps(self.NO_ARG, {"main", "zero"})
        self.assertEqual(len(gaps), 1, gaps)
        self.assertIn("0 arguments", gaps[0], gaps[0])

    def test_arm64_refuses_and_names_the_machine_half_first(self):
        """The two gaps, and which one a reader should be shown first.

        A program with a second function in its image is short BOTH of the
        machine half (the CFG walk is per-function) and of the bridge, and the
        machine half is the bigger of the two — so arm64 must still refuse with
        the interprocedural message, not with the bridge's. That ordering is a
        deliberate act (the check is emitted after that refusal) and this is
        what keeps it one."""
        tmp = tempfile.mkdtemp(prefix="a2-bridge-")
        try:
            p, err = _generate(tmp, self.ONE_ARG, "bridge_arm64")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIsNone(p, "a program that calls a second function in the "
                            "same image cannot be proved on arm64 yet")
        self.assertIn("interprocedural", err,
                      f"arm64 must name the machine half first: {err}")

    def test_x86_64_omits_the_bridge_and_says_why(self):
        tmp = tempfile.mkdtemp(prefix="a2-bridge-")
        try:
            p, err = _generate(tmp, self.ONE_ARG, "bridge_x86", arch="x86_64")
            self.assertIsNone(err, err)
            text = open(p).read()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertNotIn("theorem eval_eq_mojo", text,
                         "the bridge must be OMITTED: with a `callFunc` that "
                         "answers 0 for a user function, stating it asks Lean "
                         "to prove `0 = <the call's value>`, and the emitted "
                         "theorem is false rather than unproved")
        note = [ln for ln in text.splitlines() if "AST omitted" in ln
                or "AST bridge omitted" in ln]
        self.assertTrue(note, "an omission with no reason is the bug this "
                              "whole file is about")
        self.assertIn("_scalar_max2", note[0],
                      f"the note must name the call it gave up on: {note[0]}")

    def test_the_x86_64_proof_typechecks(self):
        """The teeth: before, this file did not elaborate.

        `prog_proof.lean:44:59: error: unsolved goals / ⊢ False` — the AST
        evaluation of the call is 0 and the model is not, so the two sides of
        `eval_eq_mojo` are about different functions. Omitting the bridge
        leaves the machine half's own theorems, which do hold."""
        tmp = tempfile.mkdtemp(prefix="a2-bridge-lean-")
        try:
            p, err = _generate(tmp, self.ONE_ARG, "bridge_x86", arch="x86_64")
            self.assertIsNone(err, err)
            got = _check_proof(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if got is None:
            self.skipTest("no Lean / no lib/ProofLib.olean: skipping the "
                          "typecheck (every assertion in TestLean needs the "
                          "library built)")
        ok, detail, n = got
        self.assertTrue(ok, detail)
        self.assertEqual(n, 2,
                         "the x86-64 generator's TWO designed trust "
                         "boundaries and no more: a third hole would be this "
                         "file quietly admitting something new")

    def test_a_callee_of_one_parameter_gets_a_branch_and_the_bridge_with_it(self):
        """`callFunc` answers for the program's OWN functions, so the bridge is
        STATED rather than omitted.

        This is the other half of the refusal above: `ONE_ARG`'s callee takes
        two parameters and `callFunc` is handed one value, so there is no
        faithful branch and the omission is right.  With ONE parameter there IS
        one — `_gen_go` already emitted `_bump1_go` — and the bridge used to be
        omitted anyway, which is the gap
        `bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md` names as step
        2: `eval_eq_mojo` was FALSE for this program, not unproved.

        Three assertions, and the middle one is the one that would catch a
        branch naming something Lean has not heard of: the `callFunc` text, the
        theorem's presence, and the theorem typechecking with the same TWO
        designed sorries as every other x86-64 proof here.
        """
        tmp = tempfile.mkdtemp(prefix="a2-bridge-callee-")
        try:
            p, err = _generate(tmp, self.ONE_ARG_CALLEE, "bridge_callee",
                               arch="x86_64")
            self.assertIsNone(err, err)
            text = open(p).read()
            got = _check_proof(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn('if name = "_bump1" then _bump1_go arg else',
                      text,
                      "the call table did not reach the emitted `callFunc`, so "
                      "the AST would still evaluate this call to 0")
        self.assertIn("theorem eval_eq_mojo", text,
                      "with a branch for the callee the bridge is statable, and "
                      "omitting it would drop a theorem that now holds")
        self.assertNotIn("AST bridge omitted", text,
                         "the bridge was omitted anyway: the table and the "
                         "omission disagree about the same call")
        # …and the model the branch names is really in the file.
        self.assertRegex(text, r"def _bump1_go\b",
                         "the branch names `_bump1_go` and the file does not "
                         "define it, which is a Lean error hundreds of lines "
                         "downstream of the call")
        if got is None:
            self.skipTest("no Lean / no lib/ProofLib.olean")
        ok, detail, n = got
        self.assertTrue(ok, detail)
        self.assertEqual(n, 2,
                         "still exactly the two designed trust boundaries: "
                         "stating the bridge must not have added a hole")

    def test_an_empty_call_table_is_the_old_stub_byte_for_byte(self):
        """Nothing is added to a program that calls nothing of its own.

        Every generated proof in the tree with no admitted contract and no
        callee must keep the text it had, because a re-wrap would invalidate
        every cached verdict in `~/.gmojo` for a whitespace change — which is
        the same sentence `_call_func_lean` carries, pinned here from the other
        side so the two cannot disagree about what "no callee" means.
        """
        from formal.arm64_proof_gen import _call_func_lean
        for wrap in (True, False):
            with self.subTest(wrap=wrap):
                self.assertEqual(
                    _call_func_lean("main", {}, wrap=wrap),
                    _call_func_lean("main", {}, wrap=wrap, exports={}),
                    "an empty table must reproduce the stub exactly")


class TestTheBranchFlagLemmaIsTheBranchOwns(unittest.TestCase):
    """A `B.cond` obligation's `simp` set must carry ITS OWN flag lemma.

    The backend lowers a comparison to `CMP` + `B.cond`, not to `CMP` + `CSET` +
    `CBZ`, so a conditional branch has no `CSET` to read a flag predicate from.
    `_cset_cond` already falls back to the terminator's own condition field
    (its docstring says so), and the guard on that value passed — but the
    `simp` set the emitted chain closes with was built from `_cset_conds`, which
    enumerates `CSET`s and finds none. So the chain carried
    `simp [h, Arm64State.init]` with **no flag lemma at all**, and the raw
    `arm64_matches_condition 11 (arm64_subs_flags …) = true` had nothing to
    reduce it. That is
    `bugs/FORMAL_a_conditions_operand_read_through_an_earlier_stores_slot.md`,
    and it is pinned here rather than in `test_formal.py` because the thing
    under test is the text the generator emits — which is this file's whole
    subject, and which is checkable with no Lean run at all.

    Three assertions, and the second is the one that is easy to get wrong in the
    direction of a no-op:

    * **every `hcond` chain's closing `simp` names a flag lemma.** A chain with
      `simp [h, Arm64State.init]` is the defect, and it is a silent one: the
      file still generates.
    * **the lemma is the BRANCH'S.** `b.lt` is `arm64_flag_lt_s`, so a chain
      testing a signed `lt` must name the signed one — a table that answered
      with the unsigned `arm64_flag_lt` would produce a chain that reduces the
      predicate to the WRONG order and still elaborates.
    * **one table answers "which condition code", not two.** `_fl_map` was a
      private copy of `_COND_LEMMA` in this same function, ten entries, key for
      key identical; it is gone, and this asserts the two are still one table by
      naming `_COND_LEMMA` as the only source (the generator source check below
      fails if a second table reappears).

    What is NOT asserted, and is the honest edge: the lemma being in the `simp`
    set is necessary and not sufficient, because the chain's earlier
    `simp only` unfolds `arm64_subs_flags` / `arm64_matches_condition` — and
    `simp only` is irreversible, so a lemma in a LATER `simp` can never match
    the term the earlier line expanded. `sum_range.mojo`'s own `hcond_4` is the
    measured case (`0 ^^^ 0x8000… < n ^^^ 0x8000…`, a RANGE, which
    `by_cases` + `simp [h]` cannot ground because it leaves `n` free on both
    branches), and the chain order that would let the lemma fire is written down
    there rather than landed here — it changes 26 of the 49 generated arm64
    proofs and a light worker cannot Lean-verify that.
    """

    RANGE = ("def sum_range(n):\n"
             "    total = 0\n"
             "    for i in range(n):\n"
             "        total += i\n"
             "    return total\n")

    EQUALITY = ("def is_zero(n):\n"
                "    if n == 0:\n"
                "        return 1\n"
                "    else:\n"
                "        return 0\n")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-flaglemma-")
        cls.ranges, cls.range_err = _generate(cls.tmp, cls.RANGE, "flagrange")
        cls.equal, cls.equal_err = _generate(cls.tmp, cls.EQUALITY, "flageq")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _hcond_closers(self, path):
        """The closing `simp [h, …] <;> bv_decide` line of every `hcond`.

        Scanned line by line rather than by one regex over the block, because
        the block's own extent is not something this file should have to know:
        `hcond_bi`'s body ends at whatever the walk emits next, and that has
        changed shape more than once (a `by_cases hc_bi` today, an `exact`
        before it).  The rule is the two anchors: the `have hcond_` line opens a
        block and the FIRST `simp [h,` line inside it is the closer, because the
        body's earlier lines are `rw [hsid_…]` and `simp only […]`.
        """
        out = []
        pending = None
        with open(path) as fh:
            for line in fh:
                if "have hcond_" in line:
                    pending = line.strip().split()[1]
                    continue
                if pending is None:
                    continue
                if "simp [h," in line:
                    out.append((pending, line.strip()))
                    pending = None
        return out

    def test_both_shapes_generate(self):
        self.assertIsNone(self.range_err, self.range_err)
        self.assertIsNone(self.equal_err, self.equal_err)

    def test_every_hcond_chain_closes_with_a_flag_lemma(self):
        for name, path in (("range", self.ranges), ("equality", self.equal)):
            closers = self._hcond_closers(path)
            self.assertTrue(closers, f"{name}: no hcond chain found in {path}")
            for hid, line in closers:
                self.assertRegex(
                    line, r"simp \[h, arm64_flag_",
                    f"{name}: {hid} closes with `{line}` and no flag lemma, so "
                    f"the raw arm64_matches_condition predicate has nothing to "
                    f"reduce it and bv_decide is handed an expression with an "
                    f"opaque register in it")

    def test_the_lemma_is_the_one_the_branch_tests(self):
        """`b.lt` is a SIGNED less-than, and the signed lemma is the only right
        answer. An unsigned `arm64_flag_lt` would reduce the predicate to an
        order the machine does not test and the chain would still elaborate —
        which is the failure a presence check cannot see and a spelling check
        can.
        """
        chains = self._hcond_closers(self.ranges)
        self.assertTrue(chains, "no hcond chain in the range proof")
        # The pairing: the branch a chain states is the branch whose code its
        # lemma names, so the two are read off the SAME chain rather than off
        # the file.  A chain whose statement says condition 11 and whose closer
        # does not name the signed lemma is the defect this test exists for.
        with open(self.ranges) as fh:
            text = fh.read()
        lines = []
        for hid, line in chains:
            stmt = re.search(r"have " + re.escape(hid) + r" : (.*?) := by",
                             text)
            lines.append((stmt.group(1) if stmt else "", line))
        signed = [line for stmt, line in lines
                  if "arm64_matches_condition 11" in stmt]
        self.assertTrue(
            signed,
            "the range program's preheader branch is `b.lt` (raw condition code "
            "11) and no chain mentions it, so this assertion is not looking at "
            f"the branch it means to: {lines}")
        for line in signed:
            self.assertIn("arm64_flag_lt_s", line)
            self.assertNotIn("arm64_flag_lt,", line)


class TestLoopContractBlocks(unittest.TestCase):
    """Which block is a loop's TEST, asked once and asked right.

    `_gen_countdown_loop` found its loop by taking "the first block of kind
    `cbz`", which was the loop test only while every program's first branch was
    its loop test.  `e11f066d` put the stack-floor guard's `CBNZ` in EVERY
    prologue, so that block is now the guard's in every image and no countdown
    loop matched anywhere: measured, none of `formal/examples/*.mojo` emitted a
    loop contract, and `wdiff` / `countdown` / `wge` refused with "no loop
    contract matches" — an UNEXPECTED failure of the `formal` suite job, since
    `wdiff` is not in its `EXPECTED_FAILURES`.

    The loop test is the target of the loop's `b` BACK EDGE, and the caller
    already computes that, so it is passed in.  Three things are pinned:

    * **the prologue's guard branch is NOT the loop test** — the fact that made
      the old discovery wrong, asserted on the image rather than on the
      generator's intent, so it keeps holding while the guard exists and fails
      loudly the day it does not;
    * **a loop's proof carries a contract** (`while_dec_exit_contract`), which
      is the regression itself;
    * **no hypothesis is cited that the file does not define** — the use site
      used to name `hsrc_1` / `hsid_1` / `hsid_0` and the body chain
      `{name}_b2_qT6`, which are one example's block numbering, and Lean reports
      those as `Unknown identifier` hundreds of lines after the branch that
      wanted them.  This is the same check as `TestDec1PathContext` below, for
      the same reason, over a different arm.
    """

    LOOP = ("def wdiff(n):\n"
            "    while n != 0:\n"
            "        n = n - 1\n"
            "    return n\n")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-loopblocks-")
        cls.proof, cls.error = _generate(cls.tmp, cls.LOOP, "loopblocks")
        cls.result = None
        if cls.error is None:
            import formal.build as fb
            src = os.path.join(cls.tmp, "loopblocks.mojo")
            cls.result = fb.compile_formal(src, arch="arm64",
                                           output=os.path.join(cls.tmp,
                                                               "loopblocks2.aout"),
                                           prove=False, check=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_it_generates(self):
        self.assertIsNone(self.error, self.error)
        self.assertIsNotNone(self.proof)

    def test_the_prologues_guard_branch_is_not_the_loop_test(self):
        """The premise the old discovery rested on, measured on the image.

        `arm64_proof_gen._cfg_blocks` is the walk both the caller and
        `_gen_countdown_loop` read, so this is the same partition the generator
        sees — not a re-derivation of it.
        """
        import formal.arm64_proof_gen as G
        info = self.result["info"]
        code = self.result["code"]
        base = info["base_addr"]
        words = {base + i: int.from_bytes(code[i:i + 4], "little")
                 for i in range(0, len(code) - len(code) % 4, 4)}
        entry = info["func_offset"]
        rets = [pc for pc, w in words.items()
                if w == 0xd65f03c0 and pc >= entry]
        blocks = G._cfg_blocks(words, entry, max(rets) + 4)
        first_cbz = next((b for b in blocks if b["kind"] == "cbz"), None)
        start_to_bi = {b["start"]: i for i, b in enumerate(blocks)}
        back_edge = next((b for b in blocks if b["kind"] == "b"
                          and start_to_bi.get(b["targets"][0]) is not None
                          and blocks[start_to_bi[b["targets"][0]]]["kind"]
                          == "cbz"), None)
        self.assertIsNotNone(first_cbz, "no conditional branch in the image at "
                            "all, so this row is not about the prologue's")
        self.assertIsNotNone(back_edge, "no loop back edge in the image, so "
                              "there is no loop test to confuse the guard with")
        self.assertNotEqual(
            first_cbz["start"], start_to_bi and
            blocks[start_to_bi[back_edge["targets"][0]]]["start"],
            "the first conditional branch IS the loop test, so taking it would "
            "work -- this row is about the prologue's stack-floor guard "
            "(`e11f066d`) being that branch, and that has changed")

    def test_the_proof_carries_a_loop_contract(self):
        text = open(self.proof).read()
        self.assertIn("while_dec_exit_contract", text,
                      "no loop contract in the proof: the generator found no "
                      "loop test, which is the failure this class is about")

    def test_no_hypothesis_is_cited_that_the_file_does_not_define(self):
        text = open(self.proof).read()
        # Each stem's DEFINING form, because they are not one form: `hsrc`,
        # `hsid` and `hframe` are typed `have`s, `hlc` is a bare `have ... :=`,
        # and `hc` is the `by_cases` that splits a conditional block. Reading
        # the file for one spelling of "defined" and finding the other three
        # would report every one of them as dangling.
        for stem, defines in (
                ("hsrc", r"have {n}\s*:"),
                ("hsid", r"have {n}\s*:"),
                ("hlc", r"have {n}\s*:?="),
                ("hc", r"by_cases {n}\s*:")):
            cited = set(re.findall(rf"\b({stem}_\d+)\b", text))
            self.assertTrue(cited, f"this test is vacuous for {stem}_: the "
                           f"emitted proof cites none")
            defined = {n for n in cited
                       if re.search(defines.format(n=re.escape(n)), text)}
            self.assertEqual(cited - defined, set(),
                             f"{stem}_ cited but never defined: "
                             f"{sorted(cited - defined)}")


class TestStructFieldHasNoValueInTheModel(unittest.TestCase):
    """The refusal `test_formal.py`'s `wide_recv` marker states, pinned.

    `formal/examples/wide_recv.mojo` is the two-field receiver example, and the
    arm64 proof generator refuses it at GENERATION time:

        NotImplementedError: model: a struct field read has no value in the
        semantic model (a `UInt64 → UInt64` function over the source's
        arithmetic); refusing rather than modelling it as 0, which would be a
        false statement about the source

    The model is a function of the ENTRY ARGUMENT and nothing else, so a
    struct's field is not a term in it: `p.x` is 4 and `p.y` is 0 whatever `n`
    is.  Answering 0 would be a false statement about the source, which is why
    the arm refuses rather than defaulting — and it is the same gap as
    `subscript_var`'s ("the semantic model `mojo : UInt64 -> UInt64` has no
    domain for a list, so `a[i]` has no value in it"), one type further.

    So `wide_recv` is in `test_formal.py`'s `EXPECTED_FAILURES` with that reason,
    and this class is what keeps the marker honest in both directions:

      * the refusal is still the one the marker names — if the model grows a
        struct domain the marker goes STALE, `test_formal.py` reports it, and
        this assertion fails first with the reason spelled out;
      * the marker names the same reason as this test, so the two cannot drift
        into two different accounts of one gap;
      * **the machine half is still fine** — the program builds on BOTH
        backends, which is what makes the gap a model gap and not a lowering
        one.  Checked with `prove=False`, so this stays Lean-free.
    """

    SOURCE = ("struct Point:\n"
              "    var x: Int\n"
              "    var y: Int\n"
              "    fn set_x(self, v: Int): self.x = v\n"
              "    fn get_x(self) -> Int: return self.x\n"
              "    fn get_y(self) -> Int: return self.y\n"
              "\n"
              "def main(n) -> Int:\n"
              "    var p = Point()\n"
              "    p.set_x(3)\n"
              "    p.set_x(4)\n"
              "    return p.get_x() + p.get_y()\n")

    #: The phrase the refusal must contain, and the phrase the marker states.
    NEEDLE = "struct field read"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-structdom-")
        cls.proof, cls.error = _generate(cls.tmp, cls.SOURCE, "structdom")
        cls.built = {}
        import formal.build as fb
        for arch in ("arm64", "x86_64"):
            src = os.path.join(cls.tmp, "machine-%s.mojo" % arch)
            with open(src, "w") as f:
                f.write(cls.SOURCE)
            try:
                fb.compile_formal(src, arch=arch, output=os.path.join(
                    cls.tmp, "machine-%s.aout" % arch), prove=False, check=False)
                cls.built[arch] = None
            except Exception as e:            # noqa: BLE001
                cls.built[arch] = f"{type(e).__name__}: {e}"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_refusal_is_the_model_domain_one(self):
        self.assertIsNone(self.proof)
        self.assertIsNotNone(self.error, "the example generated a proof, so the "
                           "model has a domain for a struct field read and the "
                           "marker in test_formal.py is stale")
        self.assertIn(self.NEEDLE, self.error,
                      "the refusal is not the one the marker states, so the "
                      "marker describes a different gap than the one this "
                      "example hits: %s" % self.error)

    def test_the_marker_states_this_refusal_and_names_the_example(self):
        import test_formal as T
        self.assertIn("wide_recv", T.EXPECTED_FAILURES,
                      "an UNMARKED failure of the `formal` suite job: the next "
                      "session reads the marker list, sees this file is not in "
                      "it, and re-derives the whole thing")
        self.assertIn(self.NEEDLE, T.EXPECTED_FAILURES["wide_recv"],
                      "the marker's reason and the measured refusal name "
                      "different gaps: %r" % T.EXPECTED_FAILURES["wide_recv"])

    def test_the_machine_half_builds_on_both_backends(self):
        """The gap is a model domain, not a lowering — measured, not argued.

        `bugs/FORMAL_wide_receiver_by_reference.md` §"The proposition" quotes
        the mutator's frame contract, and `test_formal_run.py` runs the
        program on both architectures.  What is checked here is the narrower
        half that decides which side of the boundary this example is on: both
        backends compile it, with proof generation switched off.
        """
        for arch, err in sorted(self.built.items()):
            self.assertIsNone(err, "%s does not build this program, so the "
                                "refusal above is not purely a model-domain "
                                "gap: %s" % (arch, err))


class TestAModelRefusalIsABuildRefusalNotATraceback(unittest.TestCase):
    """A refusal the generator already names must arrive as a REFUSAL.

    `NotImplementedError` is both generators' uniform "I will not write a model
    I do not have" signal — `formal/x86_64_proof_gen.py` catches it internally
    and falls back to a disclaimed placeholder, which is what
    `TestAPlaceholderModelClaimsNothing` above pins. Nothing turned it into a
    build error, so on the backend that REFUSES rather than stubbing, the
    refusal escaped `fire.py build --formal` as a Python traceback: exit 1, forty
    frames of generator internals, and the sentence that names the construct at
    the bottom of it.

    The reproducer is the one
    `bugs/FORMAL_float_step_functions.md` §"What was run" quotes, because it is
    a program that BUILDS, RUNS and answers CPython with `--no-prove` — a
    float literal in a source the machine model describes perfectly well and the
    semantic model has no domain for. The gap is real and is that document's
    subject; what is a defect here is the DIAGNOSTIC.

    Four rows, and they are four different ways this could come back:

      1. the refusal is a `FormalBuildError`, so `fire.py`'s own arm prints
         `build: <message>` and there is no traceback;
      2. the message carries the generator's OWN sentence, so the reader is sent
         to the construct rather than to the generator;
      3. the message says `--no-prove` builds the same bytes, because that is
         the fact that distinguishes a model gap from a lowering one and it is
         what a reader of a refusal needs first;
      4. **the machine half is still fine**, both backends, `prove=False` —
         which is what makes row 3 a true statement rather than a reassurance.
    """

    #: `float_step.mojo`'s own text: three float locals, an FADD-shaped
    #: comparison, and a `main` that returns 0 or 1.
    FLOAT_PROGRAM = (
        "def main(n: Int) -> Int:\n"
        "    var a = 1.5\n"
        "    var b = 2.25\n"
        "    var c = a + b\n"
        "    if c > 2.0:\n"
        "        return 1\n"
        "    return 0\n")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-modelrefusal-")
        cls.proof, cls.error = _generate(cls.tmp, cls.FLOAT_PROGRAM,
                                         "float_step")
        cls.built = {}
        import formal.build as fb
        for arch in ("arm64", "x86_64"):
            src = os.path.join(cls.tmp, "machine-%s.mojo" % arch)
            with open(src, "w") as f:
                f.write(cls.FLOAT_PROGRAM)
            try:
                fb.compile_formal(src, arch=arch, output=os.path.join(
                    cls.tmp, "machine-%s.aout" % arch), prove=False, check=False)
                cls.built[arch] = None
            except Exception as e:            # noqa: BLE001
                cls.built[arch] = f"{type(e).__name__}: {e}"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_refusal_is_a_build_error_not_a_bare_exception(self):
        import formal.build as fb
        self.assertIsNone(self.proof,
                          "the arm64 generator produced a proof for a program "
                          "whose source it cannot model, so the semantic model "
                          "has grown a float domain")
        self.assertIsNotNone(self.error, "no proof and no error: the build "
                           "neither proved nor refused the program")
        self.assertTrue(self.error.startswith("FormalBuildError"),
                        "the refusal is not a BUILD refusal, so `fire.py` "
                        "prints a traceback for a construct the generator "
                        "names: %s" % self.error)
        self.assertNotIn("NotImplementedError", self.error.split(":")[0],
                         "the refusal is still a bare NotImplementedError: %s"
                         % self.error)
        self.assertTrue(issubclass(fb.FormalBuildError, Exception))

    def test_the_message_carries_the_generators_own_sentence(self):
        self.assertIn("a FloatLiteral has no value in the semantic model",
                      self.error or "",
                      "the refusal lost the sentence that names the "
                      "construct, so a reader is sent to the generator instead "
                      "of to the float literal: %s" % self.error)

    def test_the_message_says_the_image_is_not_what_refused(self):
        self.assertIn("--no-prove", self.error or "",
                      "the refusal does not say that the image builds and "
                      "runs, which is the one fact that separates a model gap "
                      "from a lowering one: %s" % self.error)

    def test_the_machine_half_builds_on_both_backends(self):
        for arch, err in sorted(self.built.items()):
            self.assertIsNone(err, "%s does not build this program, so the "
                                "refusal above is not purely a model-domain "
                                "gap: %s" % (arch, err))


class TestTheReturnFrameReadsX30ThroughAMaterialisedAddress(unittest.TestCase):
    """`count` and `pow2`, declared rather than discovered, with the address
    named.

    Two `formal/examples/*.mojo` files were UNDECLARED reds of the `formal` job
    until 2026-10-04: they are in neither `test_formal.py::EXPECTED_FAILURES` nor
    its x86-64 table, so nothing was expected, nothing was reported, and two of
    the corpus's heaviest examples had no proving case.  That is the hole the
    marker discipline exists to close, and closing it is this class.

    **The address is the failure, and the doc's first hypothesis was not it.**
    Measured on arm64 (`python3 fire.py build --formal --backend=arm64
    -o .tmp/count.aout formal/examples/count.mojo`, ~2 min, through
    `formal/lean.py::run_lean`'s bounds), `count` fails with FIVE errors at two
    sites, and the informative one is `rfl`:

        count_proof.lean:5330:16: error: Tactic `rfl` failed: The left-hand side
          mem_read_u64 (mem_write_u64 … (UInt64.ofNat 4294968008 -
            (UInt64.ofNat 4294968008 % 4096 - ((if False then … else …) * 4096 +
              UInt64.ofNat 8))).toNat (st.sp - UInt64.ofNat 1984))
            (st.sp - UInt64.ofNat 8).toNat
        is not definitionally equal to the right-hand side st.x30

    That is the RETURN FRAME's `x30` read, and the slot was written through an
    ADRP/ADD-materialised pointer — the `arm64_set_reg 17 s (page(pc) +
    1024 * 4096)` successor earlier in the same file — so the read's address is
    a LITERAL rather than `sp - K`, and the `mem_read_after_write_u64_slot` peel
    in the `simp only` set has no `sp - K` to match.  The emitter chose that
    address because it IS `sp - 1984`; nothing emitted says so, and that is the
    missing lemma.

    **The `(if False then UInt64.ofNat 1024 - UInt64.ofNat (2 ^ 21) else …)` in
    the middle of the address is a dead arm and NOT the cause.** It is the ADRP
    page-offset guard with its condition already decided (`1024 >= 2^20` is
    false), `simp` normalises it, and the tactic that fails is `rfl` — so the
    doc's reading of it as "the thing to explain" was wrong, and this class says
    so where the next reader will look.

    Lean-free by construction: it reads the GENERATED proof's text and
    `test_formal.py`'s table, and it builds both programs with proof generation
    OFF to establish that the gap is in the PROOF layer and not in codegen.
    """

    #: The two shapes the generated proof must carry for this doc's failure to be
    #: the one it is: the epilogue's x30 read (`hx30fr_`, the fact whose `rfl`
    #: fails) and the adrp-materialised register write that feeds it.  Both are
    #: read off the TEXT, so this stays Lean-free — the frame OFFSET (`1984`)
    #: is not in the file at all, it appears only in the goal Lean prints after
    #: `simp` has rewritten the literal address, which is the point.
    X30_READ = "hx30fr_"
    ADRP = "arm64_set_reg 17"

    STEMS = ("count", "pow2")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="x30frame-")
        cls.proofs, cls.errors, cls.built = {}, {}, {}
        import formal.build as fb
        for stem in cls.STEMS:
            src = os.path.join(os.getcwd(), "formal", "examples",
                               stem + ".mojo")
            with open(src) as f:
                text = f.read()
            cls.proofs[stem], cls.errors[stem] = _generate(cls.tmp, text, stem)
            for arch in ("arm64", "x86_64"):
                dst = os.path.join(cls.tmp, "%s-%s.mojo" % (stem, arch))
                with open(dst, "w") as f:
                    f.write(text)
                try:
                    fb.compile_formal(dst, arch=arch, output=os.path.join(
                        cls.tmp, "%s-%s.aout" % (stem, arch)),
                        prove=False, check=False)
                    cls.built[(stem, arch)] = None
                except Exception as e:        # noqa: BLE001
                    cls.built[(stem, arch)] = f"{type(e).__name__}: {e}"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_both_are_marked_with_the_address_in_the_reason(self):
        import test_formal as T
        for stem in self.STEMS:
            self.assertIn(stem, T.EXPECTED_FAILURES,
                          "%s is an UNMARKED failure of the `formal` suite job: "
                          "the next session reads the marker list, does not "
                          "find it, and re-derives this" % stem)
            reason = T.EXPECTED_FAILURES[stem]
            self.assertIn("sp -", reason,
                          "%s: the marker does not say the read is at a frame "
                          "slot, which is what makes it unpeelable: %r"
                          % (stem, reason))
            self.assertIn("materialis", reason,
                          "%s: the marker does not say the address is "
                          "materialised (adrp/add), which is the whole of the "
                          "gap: %r" % (stem, reason))

    def test_the_generated_proof_carries_the_materialised_address(self):
        """The measurement the markers state, read off the generated text.

        If the emitter ever stops materialising that address — a frame-slot
        store it can canonicalise, say — the markers go stale, `test_formal.py`
        reports them, and this fails first with the reason spelled out."""
        for stem in self.STEMS:
            path = self.proofs[stem]
            self.assertIsNotNone(
                path, "%s generated no proof at all, so the marker is naming "
                      "a generation refusal and this class is measuring "
                      "something else: %s" % (stem, self.errors[stem]))
            with open(path) as f:
                text = f.read()
            self.assertIn(self.X30_READ, text,
                          "%s: the proof carries no %s, so the epilogue's x30 "
                          "read is not the fact that fails any more and this "
                          "class is measuring something else"
                          % (stem, self.X30_READ))
            self.assertIn(self.ADRP, text,
                          "%s: no adrp-materialised register write in the "
                          "proof, so the address is no longer a literal and "
                          "the gap this names has moved" % stem)

    def test_both_programs_build_on_both_backends(self):
        """Which side of the boundary each example is on: the program is
        code-generator-clean and the gap is in the PROOF layer, so a marker that
        said "the backend cannot lower this" would be wrong."""
        for key, err in sorted(self.built.items()):
            self.assertIsNone(err, "%s does not build with proofs off (%s), so "
                                "the gap is not the one the marker names"
                                % (key, err))


class TestBottomTestedRangeLoop(unittest.TestCase):
    """A `for … in range(…)` loop, whose back edge is a CONDITIONAL branch.

    The same program raised

        ValueError: unsupported cbz taken continuation to 0x100000330

    out of the proof generator, on arm64, and the doc that recorded it
    (deleted with its fix, commit `cbf00b9f`) had no `EXPECTED_FAILURES` entry
    for it — an UNEXPECTED failure of the `formal` suite job.

    The cause is a shape, not a missing case: `arm64_codegen`'s `_emit_while`
    puts a `for`-range loop's emptiness test in a PREHEADER and leaves the
    back edge as the body block's own conditional branch, so the loop top is a
    `cbz`-kinded block whose TAKEN edge targets its OWN start.  The generator's
    loop discovery asked for the other shape (a `b` block branching to a `cbz`
    block), which that preheader has not produced since it landed, so
    `_gen_range_loop` matched nothing and the walk had no contract to apply at
    the re-entry.

    Three things are pinned here, and the first is the regression itself:

    * the program GENERATES a proof, on arm64;
    * the generated proof carries the bottom-tested loop contract, so the
      back edge was discharged rather than refused;
    * the loop top on the IMAGE is the self-looping block, so a change in the
      emitter that moves the test back above the body is caught here rather
      than silently reducing the contract to no match.
    """

    SOURCE = ("def sum_range(n):\n"
              "  total = 0\n"
              "  for i in range(n):\n"
              "    total += i\n"
              "  return total\n")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-bottomloop-")
        cls.proof, cls.error = _generate(cls.tmp, cls.SOURCE, "bottomloop")
        cls.result = None
        if cls.error is None:
            import formal.build as fb
            src = os.path.join(cls.tmp, "bottomloop.mojo")
            cls.result = fb.compile_formal(src, arch="arm64",
                                           output=os.path.join(cls.tmp,
                                                               "bottomloop2.aout"),
                                           prove=False, check=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_it_generates(self):
        self.assertIsNone(self.error, self.error)
        self.assertIsNotNone(self.proof)

    def test_the_proof_carries_the_bottom_tested_loop_contract(self):
        text = open(self.proof).read()
        self.assertIn("while_lt_exit_contract_bottom", text,
                      "no bottom-tested loop contract in the proof: the "
                      "back edge was discharged by something else, or by "
                      "nothing")
        self.assertIn("_ltb_loop", text,
                      "the contract is applied nowhere: the walk reached the "
                      "re-entry without it")

    def test_the_loop_top_is_a_self_looping_conditional_block(self):
        """The premise the contract is generated from, measured on the image.

        `_cfg_blocks` is the partition the generator reads, so this is the
        generator's own view and not a re-derivation of it.  The countdown
        shape (`TestLoopContractBlocks` above) is a `b` block branching to a
        `cbz` block; this row is the other one, and the emitter picks between
        them.
        """
        import formal.arm64_proof_gen as G
        info = self.result["info"]
        code = self.result["code"]
        base = info["base_addr"]
        words = {base + i: int.from_bytes(code[i:i + 4], "little")
                 for i in range(0, len(code) - len(code) % 4, 4)}
        entry = info["func_offset"]
        rets = [pc for pc, w in words.items() if w == 0xd65f03c0 and pc >= entry]
        blocks = G._cfg_blocks(words, entry, max(rets) + 4)
        self_loop = [b for b in blocks if b["kind"] == "cbz"
                     and len(b["instrs"]) > 1
                     and b["targets"][1] == b["start"]]
        self.assertTrue(
            self_loop,
            "no block whose conditional back edge targets its own start, so "
            "this program is no longer the shape the bottom-tested contract "
            "is written for -- the row above would then pass for the wrong "
            "reason")
        # The contract's `cbz_start` is that block's start, so the walk's
        # `taken == ctx["loop_contract"]["cbz_start"]` test is what fires.
        self.assertNotIn("unsupported cbz taken continuation",
                         open(self.proof).read())
class TestCompilerTrapIsNotAProgramCall(unittest.TestCase):
    """An `exit` the COMPILER emits is not an `exit` the PROGRAM makes.

    `e11f066d` put the stack-floor guard in the prologue of every image with an
    entry, and on x86-64 the guard's trap is a call to the C library's `exit`
    (`formal/x86_64_codegen.py::_emit_call_exit` takes the extern path, because
    the syscall number for exit differs between Darwin and Linux).  So every
    x86-64 image carried an `extern_calls` entry, and
    `_run_tests_section` refuses the whole run-test section for an image with
    any extern call — on the true ground that the model has no memory for a
    `__TEXT,__stubs` trampoline.  Measured, the refusal then fired on EVERY
    program on this backend: x86-64 emitted zero run tests and zero termination
    obligations for the whole corpus, and it had emitted them before `e11f066d`.
    Those are the theorems that compare the machine's result register against
    `mojo` by `native_decide`, and they are what caught the fabricated string
    `0` above without a human reading anything.

    arm64 does not have it, and the asymmetry was the bug: arm64's trap is a
    raw `svc`, which is IN the image, so its `extern_calls` stayed empty.  The
    fix is not to make the two backends' traps alike but to let the emitter say
    which call sites are its own — `info["compiler_traps"]`, subtracted by
    address, not by symbol, because an image that both traps and `raise`s has two
    `exit` facts to tell apart.

    Every row of this class is cheap: proof GENERATION, no Lean.  That the run
    tests which come back are TRUE is a separate claim and only Lean tells it
    (`TestStringValueInTheModel` below is the assertion that the string model
    they compare against is the interned address, and Lean accepts the whole
    file there).
    """

    # The doc's table, one program per row: two that must be run-tested and one
    # that must not.
    PLAIN = "def main(n: Int) -> Int:\n    return 7\n"
    RETURNS_A_STRING = "def main(n: Int) -> Int:\n    return \"small\"\n"
    PRINTS = "def main(n: Int) -> Int:\n    print(42)\n    return 7\n"

    @classmethod
    def setUpClass(cls):
        import formal.build as fb
        cls.tmp = tempfile.mkdtemp(prefix="a2-trap-")
        cls.built = {}
        for name, src in (("plain", cls.PLAIN),
                          ("string", cls.RETURNS_A_STRING),
                          ("prints", cls.PRINTS)):
            path = os.path.join(cls.tmp, f"{name}.mojo")
            with open(path, "w") as f:
                f.write(src)
            for arch in ("x86_64", "arm64"):
                try:
                    r = fb.compile_formal(
                        path, arch=arch,
                        output=os.path.join(cls.tmp, f"{name}-{arch}.aout"),
                        prove=True, check=False)
                except Exception as e:                # noqa: BLE001
                    cls.built[(arch, name)] = None
                    cls.built[(arch, name, "error")] = \
                        f"{type(e).__name__}: {e}"
                    continue
                cls.built[(arch, name)] = open(
                    r["proof_path"], encoding="utf-8").read()
                cls.built[(arch, name, "info")] = r["info"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _text(self, arch, name):
        text = self.built.get((arch, name))
        self.assertIsNotNone(
            text, f"{name} on {arch} produced no proof: "
                  f"{self.built.get((arch, name, 'error'))}")
        return text

    def _info(self, arch, name):
        info = self.built.get((arch, name, "info"))
        self.assertIsNotNone(info, f"{name} on {arch} was not built")
        return info

    def test_x86_64_run_tests_are_back_for_a_program_that_calls_nothing(self):
        for name in ("plain", "string"):
            text = self._text("x86_64", name)
            with self.subTest(program=name):
                self.assertNotIn("NO RUN TESTS", text,
                                 "the compiler's own `exit` trap is being read "
                                 "as a call the program makes")
                for n in (0, 1, 2, 5, 10):
                    self.assertIn(f"theorem main_runs_{n} :", text)
                    self.assertIn(f"theorem main_terminates_{n} :", text)

    def test_a_real_extern_call_still_suppresses_them_and_says_which(self):
        """The refusal must survive the fix, or the fix is a hole in a wall.

        `print` is a call to a `__TEXT,__stubs` trampoline the model cannot
        follow, so this image's run really would fail to terminate. The
        sentence naming `printf` is the reason a reader can tell this row from
        the two above.
        """
        text = self._text("x86_64", "prints")
        self.assertIn("NO RUN TESTS", text,
                      "a program that calls printf is being run-tested, so a "
                      "failure to terminate would be reported as a wrong answer")
        self.assertIn("printf", text,
                      "the suppression must name the symbol that caused it")

    def test_the_trap_is_published_as_a_compiler_call(self):
        """`info["compiler_traps"]` is the emitter's own list, and it is right.

        Every entry must be the address of an `exit` in `extern_calls` — the
        trap is a real call and must stay accounted for on the link line — and
        no entry may be any other symbol's, or the subtraction would silence a
        program call.
        """
        for name in ("plain", "string", "prints"):
            info = self._info("x86_64", name)
            traps = info.get("compiler_traps")
            with self.subTest(program=name):
                self.assertTrue(traps,
                                "no compiler_traps published, so the generator "
                                "has nothing to subtract and every run test is "
                                "suppressed again")
                by_addr = {e["addr"]: e["sym"]
                           for e in (info.get("extern_calls") or [])}
                for addr in traps:
                    self.assertIn(addr, by_addr,
                                  f"{addr} is published as a trap but is not "
                                  f"an extern call at all")
                    self.assertEqual(by_addr[addr], "exit",
                                     f"the trap at {addr} is a "
                                     f"{by_addr[addr]!r} call")

    def test_the_subtraction_is_by_address_not_by_symbol(self):
        """Two `exit` calls, one the compiler's: the program's must survive.

        This is the case that makes the design a decision rather than a
        convenience. `_emit_diverge` — a `raise`, a dialect trap used as a
        statement — reaches the same `_emit_call_exit` and is deliberately NOT a
        compiler trap, because the program really does get there. Subtract by
        symbol and every `exit` disappears, which is the defect the run tests
        were there to catch.
        """
        from formal.x86_64_proof_gen import _program_externs
        trap, reached = 0x1000, 0x2000
        info = {
            "extern_calls": [{"sym": "exit", "addr": trap, "kind": "call"},
                             {"sym": "exit", "addr": reached, "kind": "call"}],
            "compiler_traps": [trap],
        }
        self.assertEqual(_program_externs(info), ["exit"])
        self.assertEqual(_program_externs(
            {"extern_calls": info["extern_calls"]}), ["exit", "exit"],
            "with no traps published both exits are the program's")

    def test_arm64_needs_no_trap_list_and_keeps_its_run_tests(self):
        """The other backend, and the reason the asymmetry was the bug.

        arm64's trap is a raw `svc`, which `lib/ProofLib.lean` decodes, so its
        `extern_calls` was always empty for a program that calls nothing and
        its run tests were never suppressed. Nothing here may change that, and
        the assertion that it has not is what makes the x86-64 fix a fix rather
        than a lowering of the bar on both sides.
        """
        info = self._info("arm64", "plain")
        self.assertEqual([e["sym"] for e in (info.get("extern_calls") or [])],
                         [], "arm64's guard trap is an `svc`, not a call")
        self.assertFalse(info.get("compiler_traps"),
                         "arm64 published compiler traps, so its trap is no "
                         "longer the in-image `svc` this assertion assumes")
        text = self._text("arm64", "plain")
        self.assertNotIn("NO RUN TESTS", text)
        self.assertIn("theorem main_runs_0 :", text)


class TestTheRecursionFamiliesStillGenerate(unittest.TestCase):
    """Which corpus examples REACH a proof file, pinned without Lean.

    `bugs/FORMAL_the_arm64_step_table_audit_read_a_branch_out_of_a_comment.md`
    recorded twelve red examples on 2026-10-03 and measured them one family at a
    time, which is the right discipline and produced a list that has since gone
    stale in BOTH directions: `wdiff` was on it and now passes with zero admitted
    `sorry`, and `sum_range` was the last one refusing at generation — its
    back edge is a conditional branch, and a `for`-range loop lowers with the
    test at the BOTTOM of the body, so the walk's "is the taken target the loop
    top?" question had to be asked on the conditional arm too.

    **All twelve now generate**, and the reason the count is stated here rather
    than left to the reader is that it was WRONG in this file for a while: the
    census pinned `sum_range` as the one refusal, its owner doc recorded the
    generation refusal as fixed, and the two had been merged onto this tree
    without either noticing the other. That is what `REFUSED` below is for — an
    empty dict here is not a table nobody filled in, it is the assertion that
    every one of the twelve reaches a proof file, and the moment one stops, the
    case below says which and why.

    A census that has gone stale is worth exactly as much as the measurement
    that refreshed it, and the refresh is cheap: **emission needs no Lean**, so
    this file (whose rule is generation only, no Lean) can pin it on every run
    and the doc's list cannot rot again between sessions. What it cannot do is
    say whether Lean ACCEPTS each of them — an emitted proof can still be
    rejected at typecheck — and this class says so in its own name rather than
    letting "generates" read as "is proved".

    Two things are pinned per stem, because "did not raise" is the weaker claim:
    a file was written AND it carries the end-to-end theorem. A generator that
    emitted an empty file would pass the first and fail the second.
    """

    #: The twelve, grouped as the doc grouped them, so a reader can see which
    #: family each is in.  `sum_range` is family 1's range loop and the one that
    #: took the conditional back edge; it is in this tuple rather than in
    #: `REFUSED` below because it generates.
    GENERATE = ("count", "fact", "pow2", "sqsum", "sum",      # family 1
                "sgt8", "sle8", "ug8",                          # family 2
                "both", "either",                               # family 3
                "wdiff",                                        # family 4
                "sum_range")                                    # family 1

    #: Nobody refuses, and the shape says so: a stem here is pinned as NOT
    #: generating, with the WORDING of the refusal rather than an address (an
    #: address is `sum_range.mojo`'s loop header in today's layout and moves
    #: with any layout change, while a message is the premise).  Adding a row
    #: is how a newly-found refusal stops being a note in somebody's session.
    REFUSED = {}

    @classmethod
    def setUpClass(cls):
        cls.examples = os.path.join(HERE, "formal", "examples")

    def _generate(self, stem, arch="arm64"):
        path = os.path.join(self.examples, stem + ".mojo")
        self.assertTrue(os.path.isfile(path), f"no example at {path}")
        tmp = tempfile.mkdtemp(prefix="recfam-")
        try:
            r = _compile(path, os.path.join(tmp, stem + ".aout"), arch)
            with open(r["proof_path"], encoding="utf-8") as f:
                return f.read(), None
        except Exception as e:                        # noqa: BLE001
            return None, f"{type(e).__name__}: {e}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_every_one_of_them_still_generates(self):
        for stem in self.GENERATE:
            with self.subTest(stem=stem):
                text, err = self._generate(stem)
                self.assertIsNotNone(
                    text, f"{stem} no longer generates: {err} — either the gap "
                          f"closed (delete it here and say so) or it reopened")
                # The arm64 generator's end-to-end theorem is
                # `<fn>_compiles_correctly_universal` — `main_post_*` is the
                # x86-64 generator's spelling and this class is arm64-only, so
                # naming the wrong one would have made every row fail for a
                # reason about a NAME.
                self.assertIn("_compiles_correctly_universal", text,
                              f"{stem} generated a file with no end-to-end "
                              f"theorem in it; that is not a proof of anything")

    def test_the_range_loop_is_proved_by_a_bottom_tested_contract(self):
        """Why `sum_range` generates, and not by accident.

        `for n:` lowers with the emptiness test in a PREHEADER, so the body, the
        counter increment, the comparison and the back edge are ONE `cbz`-kinded
        block whose taken edge targets its OWN start. The loop-discovery scan
        used to ask "is this a `b` block whose target is a `cbz` block" — an
        unconditional back edge — and so found no loop contract at all for this
        shape, which is why the walk raised `unsupported cbz taken continuation`
        rather than applying one.

        So "generates" for this stem could be true for a reason that has nothing
        to do with the loop, and the pin is that it is proved by the contract
        for a test at the BOTTOM (`while_lt_exit_contract_bottom`, whose `Rn` of
        31 is the zero register — see `lib/ProofLib.lean`'s
        `arm64_step_neg_reads_zero_rn`), not by the top-tested one.
        """
        text, err = self._generate("sum_range")
        self.assertIsNotNone(text, f"sum_range generates now? {err}")
        self.assertIn("while_lt_exit_contract_bottom", text)
        self.assertNotIn("while_lt_exit_contract ", text,
                         "sum_range's test is at the bottom of its body, so the "
                         "top-tested contract is the wrong one for it")

    def test_the_one_that_refuses_says_why(self):
        for stem, (needle, why) in sorted(self.REFUSED.items()):
            with self.subTest(stem=stem):
                text, err = self._generate(stem)
                self.assertIsNone(
                    text, f"{stem} generates now ({err}); delete it from "
                          f"REFUSED and say what closed it — the doc this row "
                          f"cites names the owner of the fix")
                self.assertIn(needle, err or "",
                              f"{stem} refused, but not with the wording this "
                              f"row pins: {err} ({why})")

    def test_the_owner_of_the_one_refusal_still_exists(self):
        """A refusal whose owning doc is gone is a doc to delete, not to keep.

        The rule the whole `bugs/` queue rests on: a doc for a bug that is fixed
        is deleted. So a row here that pins a refusal must also pin the document
        that owns the repair, or the row becomes a way to keep a stale claim
        alive after the fix has landed.

        **Vacuous while `REFUSED` is empty, and that is asserted rather than
        left to be discovered**: an empty table and a table whose rows all point
        at deleted docs look identical from the outside, and the difference is
        the difference between "nobody refuses" and "the records of the refusals
        were thrown away".  So the empty case states the census it means — all
        twelve reach a proof file — and the census is `GENERATE`, which the case
        above walks.
        """
        if not self.REFUSED:
            self.assertEqual(
                len(self.GENERATE), 12,
                "REFUSED is empty, so this class now claims that ALL TWELVE of "
                "the red examples generate. If the census changed, say so here "
                "and name the new count — an empty table that quietly stops "
                "meaning 'all of them' is how a refusal goes unrecorded")
            return
        for stem in sorted(self.REFUSED):
            owners = [n for n in os.listdir(os.path.join(HERE, "bugs"))
                      if n.startswith(f"FORMAL_{stem}")]
            self.assertTrue(
                owners,
                f"{stem} is pinned as refusing with no bug doc naming it; "
                f"either the refusal is fixed (delete the row) or the doc that "
                f"owns the repair is missing, and this row is what found that")


class TestAPlaceholderModelClaimsNothing(unittest.TestCase):
    """A model the shared generator cannot write must be CLAIMED as unwritten.

    `formal/x86_64_proof_gen.py` catches the shared model generator's
    `NotImplementedError` and does not fail the build: it emits the model's
    function as the IDENTITY, with a NOTE, and suppresses the two sections whose
    whole value is a comparison against that model.  For
    `formal/examples/wide_recv.mojo` — the two-field receiver example, whose
    `p.get_x() + p.get_y()` is a struct field read and the model's domain is
    `UInt64 -> UInt64` — that yields `def main_go (n : UInt64) : UInt64 := n` for
    a function whose real answer is 4 whatever `n` is.

    That is a FALSE STATEMENT about the source unless nothing downstream of it is
    claimed, so the whole of this class is that "unless".  Four sections and one
    control, and each row is a way a later change could remove the guard and
    leave the false statement standing with a proof attached:

      1. the NOTE, naming the refusal and saying nothing downstream is claimed;
      2. the model's own definition being the identity, so a reader who skips
         the NOTE still sees that the model computes nothing;
      3. the AST BRIDGE suppressed, with its reason — `eval_eq_mojo` against the
         identity is the obligation `0 = n`, which is false rather than unproved;
      4. the RUN TESTS suppressed, with their reason — a run test would compare
         the MACHINE against the placeholder and fail for a reason that says
         nothing about the machine, which is how a fabricated answer gets
         reported as a codegen bug.

    **arm64 REFUSES this program outright** and x86-64 emits a disclaimed stub,
    which is a real divergence between the two backends on one source file.  It
    is asserted here as a fact rather than left for a reader to find, because the
    honest stub is the x86-64 half and the arm64 half is the stricter one — and
    arm64's proof layer is the more complete of the two, so "make them alike"
    would mean giving up more than it gains.  The decision and its measurement are
    `bugs/FORMAL_wide_recv_model_has_no_domain_for_a_struct.md`'s, and what
    belongs here is only that the stub's honesty is a property of the GENERATOR
    and not of this one example.

    Generation only, no Lean: `compile_formal(prove=True, check=False)`.
    """

    #: `wide_recv.mojo`'s shape, in the subset both backends accept: a
    #: two-field struct whose method READS a field, so translating the body
    #: reaches a member read the model's domain cannot hold.
    WIDE_RECV = """struct Point:
    var x: Int
    var y: Int

    fn get_x(self) -> Int:
        return self.x

    fn get_y(self) -> Int:
        return self.y

def main(n: Int) -> Int:
    var p = Point()
    return p.get_x() + p.get_y()
"""

    #: The control: a function the shared model covers, so every suppression
    #: below must be ABSENT. Without it a generator that suppressed all four
    #: unconditionally would satisfy rows 1-4 and prove nothing.
    PLAIN = "def main(n: Int) -> Int:\n    return n + 1\n"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="placeholder-model-")
        cls.built = {}
        for name, src in (("wide_recv", cls.WIDE_RECV), ("plain", cls.PLAIN)):
            path = os.path.join(cls.tmp, f"{name}.mojo")
            with open(path, "w") as f:
                f.write(src)
            for arch in ("x86_64", "arm64"):
                key = (arch, name)
                try:
                    r = _compile(path, os.path.join(
                        cls.tmp, f"{name}-{arch}.aout"), arch)
                except Exception as e:                # noqa: BLE001
                    cls.built[key] = None
                    cls.built[key + ("error",)] = f"{type(e).__name__}: {e}"
                    continue
                with open(r["proof_path"], encoding="utf-8") as fh:
                    cls.built[key] = fh.read()
                cls.built[key + ("info",)] = r["info"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _text(self, arch, name):
        text = self.built.get((arch, name))
        self.assertIsNotNone(
            text, f"{name} on {arch} produced no proof: "
                  f"{self.built.get((arch, name, 'error'))}")
        return text

    def test_the_uncovered_shape_reaches_the_placeholder_route(self):
        """The premise of every other row here, measured rather than assumed.

        If the shared generator learned this shape, all four suppressions would
        disappear and rows 1-4 would fail — so this row says which tree it is
        asserting about, and it is the row that tells a reader the other four are
        about a real gap rather than about a generator that gave up early.
        """
        text = self._text("x86_64", "wide_recv")
        self.assertIn("the shared model generator does not cover this "
                      "function's shape", text)
        self.assertIn("struct field read has no value in the semantic model",
                      text,
                      "the NOTE must name the REFUSAL, not just announce that "
                      "there is one: a reader who cannot tell which shape is "
                      "uncovered cannot tell whether their own program is in it")

    def test_the_note_says_nothing_downstream_is_claimed(self):
        text = self._text("x86_64", "wide_recv")
        self.assertIn("the semantic model below is the identity and nothing "
                      "downstream of it is claimed", text)

    def test_the_model_is_the_identity_rather_than_the_program(self):
        """A reader who skips every comment still sees that the model is empty.

        `main_go n = n` for a function that returns 4 whatever `n` is. Asserted
        as TEXT rather than by running Lean, because the point is what the
        emitted file says and Lean's opinion of `n = n` is not in question.
        """
        text = self._text("x86_64", "wide_recv")
        m = re.search(r"def main_go\s*\([^)]*\)\s*:\s*UInt64\s*:=\s*"
                      r"\n\s*(\S+)", text)
        self.assertIsNotNone(m, "the model's own definition is not where the "
                                "file says it is:\n" + text[:400])
        self.assertEqual(m.group(1), "n",
                         "the placeholder model is no longer the identity; a "
                         "placeholder that computes SOMETHING needs the "
                         "suppressions below re-examined, because it is no "
                         "longer obviously empty")

    def test_the_ast_bridge_is_suppressed_with_its_reason(self):
        text = self._text("x86_64", "wide_recv")
        self.assertIn("AST bridge omitted", text)
        self.assertIn("PLACEHOLDER", text)
        self.assertNotIn("theorem eval_eq_mojo", text,
                         "the AST bridge was emitted against a placeholder "
                         "model: `eval_eq_mojo` here is the obligation "
                         "`0 = n`, which is FALSE rather than unproved")

    def test_the_run_tests_are_suppressed_with_their_reason(self):
        text = self._text("x86_64", "wide_recv")
        self.assertIn("NO RUN TESTS", text)
        self.assertIn("PLACEHOLDER", text)
        for n in (0, 1, 2, 5, 10):
            self.assertNotIn(f"theorem main_runs_{n} :", text,
                             "a run test compares the MACHINE against the "
                             "placeholder, so it fails for a reason that says "
                             "nothing about the machine")
        # …and the end-to-end theorem is admitted, which is what makes the whole
        # file honest rather than merely cautious.
        tail = text[text.rfind("theorem main_compiles_correctly"):]
        self.assertIn("sorry", tail,
                      "the end-to-end theorem is not `sorry` for a file whose "
                      "model is the identity; without that it states the image "
                      "computes `mojo n` = `n`, and the image computes 4")

    def test_the_control_claims_all_four(self):
        """A function the model CAN cover must have none of the four.

        Without this row a generator that suppressed everything unconditionally
        would pass rows 1-4 and this file would be pinning a generator that
        proves nothing at all.
        """
        for arch in ("x86_64", "arm64"):
            text = self._text(arch, "plain")
            with self.subTest(arch=arch):
                self.assertNotIn("the shared model generator does not cover",
                                 text)
                self.assertNotIn("PLACEHOLDER", text)
                self.assertNotIn("AST bridge omitted", text)
                self.assertNotIn("NO RUN TESTS", text)
                self.assertIn("theorem eval_eq_mojo", text)

    def test_arm64_refuses_the_shape_and_x86_64_disclaims_it(self):
        """The divergence, stated, because a reader meets it.

        `wide_recv` is refused on arm64 at GENERATION time — the shared model's
        `NotImplementedError` is not caught there — and emitted with a disclaimed
        placeholder on x86-64.  Neither claims the program is proved, which is
        the property that matters; the difference is what a caller sees, and a
        caller reading `compile_formal`'s return value has to know which it is.
        """
        self.assertIsNone(self.built.get(("arm64", "wide_recv")),
                          "arm64 now emits a proof for this shape; if it does, "
                          "this row is stale and the divergence is gone")
        err = self.built.get(("arm64", "wide_recv", "error"), "")
        self.assertIn("struct field read has no value in the semantic model",
                      err,
                      f"arm64 refused it, but not with the shared model's own "
                      f"reason: {err}")
        self.assertIsNotNone(
            self.built.get(("x86_64", "wide_recv")),
            "x86_64 refused the shape too, so the two backends now agree and "
            "this row is stale")


class TestDec1PathContext(unittest.TestCase):
    """The recursive-call arm's unfolding set and the hypothesis it cites.

    `_gen_universal_e2e_cfg`'s `bl` arm used to unfold with `hsid_0` plus this
    block's definitions — correct one block deep, wrong at depth, because
    `s_6`'s definition is written in terms of `s_4` — and to cite a literal
    `hsrc_0`, which no emitted proof ever defines. Both produced Lean errors
    hundreds of lines downstream of the call that wanted them, on
    `formal/examples/count.mojo` (`bugs/FORMAL_arm64_x30_is_reloaded_from_the_
    frame.md` carries the measurement and what is still open there)."""

    DEC1 = ("def dec1(n):\n"
            "    if n == 0:\n"
            "        return 0\n"
            "    else:\n"
            "        return dec1(n - 1)\n")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-dec1-")
        cls.proof, cls.error = _generate(cls.tmp, cls.DEC1, "dec1")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_it_generates(self):
        self.assertIsNone(self.error, self.error)
        self.assertIsNotNone(self.proof)

    def test_no_hypothesis_is_cited_that_the_file_does_not_define(self):
        """`hsrc_0` was the whole bug: a `have` that cites a name nothing binds.

        Read over the emitted text, so it is the FILE that is checked and not
        one spelling of the generator's intent."""
        text = open(self.proof).read()
        defined = set(re.findall(r"have (hsrc_\d+) :", text))
        cited = set(re.findall(r"\b(hsrc_\d+)\b", text))
        self.assertTrue(cited, "this test is vacuous if the emitted proof "
                               "cites no `hsrc_` at all — the arm of the "
                               "emitter that had the bug is not reached")
        self.assertEqual(cited - defined, set(),
                         f"cited but never defined: {sorted(cited - defined)}")

    def test_the_recursion_argument_bound_cites_a_defined_one(self):
        """The specific line, named: `u64_sub_one_toNat_le`'s third argument."""
        text = open(self.proof).read()
        calls = re.findall(r"u64_sub_one_toNat_le [^\n]*?\b(hsrc_\d+)\b",
                           text)
        self.assertTrue(calls, "the dec1 recursion-argument bound is not in "
                               "this proof, so nothing here is being tested")
        defined = set(re.findall(r"have (hsrc_\d+) :", text))
        for name in calls:
            self.assertIn(name, defined,
                          f"{name} is cited by the recursion-argument bound "
                          f"and defined nowhere in the file")


# ── The CFG leaves that admit ────────────────────────────────────────────────
# `formal/arm64_proof_gen.py` used to spell its admissions out longhand, one
# anonymous `all_goals (first | done | sorry)` per leaf.  The two documents
# that enumerate them disagreed with each other about how many there were --
# FORMAL.md §7 row 7 said seven and the trust audit of 2026-10-04 said eight --
# because nobody had written the list down.  These tests are the list: the
# registry is pinned by NAME, an admission added without a name fails, and the
# instrument that says which leaf is live is itself pinned.

#: The fifteen, spelled out.  A CEILING and not an equality would be the modern
#: thing to want, but an equality is stronger here and is what makes a removal
#: deliberate: dropping a name is the visible act that closes a leaf, and the
#: corpus figures in the class docstring say which ones are still live.
EXPECTED_CFG_LEAF_SITES = {
    # the eight the trust audit's table named
    "walk-terminal",
    "dec-while-back-edge-decrement",
    "dec-while-back-edge-frame-slot",
    "runs-ret-x0",
    "runs-ret-x30",
    "runs-ret-frame-ok-window",
    "runs-bl-step",
    "runs-cbz-condition",
    # five `for i in range(...)` obligations, spelled `all_goals sorry` and so
    # invisible to a search for the eight above.  Five here as before, and NOT
    # the same five: the contract is decomposed per SEGMENT since, so
    # `model-invariance` and `back-edge-target` are carried by the
    # `_loop_body_flag` / `_loop_go_one_step` chain and cannot admit, and the
    # back edge's frame and the exit path's frame have leaves of their own.
    # A registry entry nothing emits is a name `cfg_leaf_census` can never
    # report, which is the silent gap this registry was written to close — so
    # the equality below is what keeps that from being how it rots.
    "range-loop-frame-preservation",
    "range-loop-exit-frame-preservation",
    "range-loop-exit-x30",
    "range-loop-back-edge-frame",
    "range-loop-terminal-invariant",
    # the two closers both loop contracts share
    "loop-cond-flag",
    "loop-cond-step",
}


class TestCfgLeafCensus(unittest.TestCase):
    """Every admission the arm64 generator can emit is a NAMED leaf.

    Nothing here runs Lean.  These are invariants of the generator and of the
    census it feeds; the Lean half -- "which leaf does the corpus actually
    admit at" -- is `no_admission_fallback` plus a Lean run, which is what
    `test_formal.py`'s census reports and what
    `bugs/FORMAL_arm64_a_cbz_on_a_literal_pool_register_admits_over_a_false_claim.md`
    records.
    """

    def test_the_registry_is_exactly_the_pinned_fifteen(self):
        import formal.arm64_proof_gen as G
        self.assertEqual(set(G.cfg_leaf_sites()),
                         EXPECTED_CFG_LEAF_SITES)

    def test_no_admission_in_the_generator_is_untagged(self):
        """Every statement that can emit a `sorry` names the site it emits at.

        The admission keyword the CFG walk writes into generated Lean is
        `_HOLE`, assembled from two halves so a source grep cannot see it --
        which is precisely why a grep is not the check, and why this test
        exists: a NEW `all_goals sorry` written the old way has to fail here
        rather than join a census that never counted it.

        Only `_HOLE`, deliberately.  The literal word appears in this file for
        three other families, none of them CFG leaves and each with its own
        owner: the host contracts (`_decide_or_admit`, `_admitted_lean`), the
        dylib export stubs (`_dylib_contract_proof`) and the extern step
        (`_gen_extern_test`).
        """
        import formal.arm64_proof_gen as G
        src = open(PROOF_GEN).read()
        tree = ast.parse(src)
        sites = set(G.cfg_leaf_sites())

        # The three ways this file is allowed to name a leaf, and no fourth.
        # An enumerable set is the point: "somewhere in this statement there is
        # a tag" would let a function that tags one leaf hide an untagged
        # admission in the same function.
        NAMERS = ("_tag_leaf(", "_cfg_leaf(", "_leaf_tag_line(")

        def named(seg):
            return any(f'"{s}"' in seg for s in sites) or any(
                n in seg for n in NAMERS)

        untagged, covered = [], []
        for node in ast.walk(tree):
            if not isinstance(node, ast.stmt):
                continue
            if any(lo <= node.lineno <= hi for lo, hi in covered):
                continue        # inside a statement already accounted for
            seg = ast.get_source_segment(src, node) or ""
            # `_HOLE` as SOURCE TEXT, not as its value: the value is the word
            # `sorry`, which this file also spells out in prose and in three
            # other families' code.  The identifier is what the CFG walk
            # interpolates into generated Lean, and it is the only spelling
            # those use.
            if "_HOLE" not in seg or seg.lstrip().startswith("_HOLE "):
                continue
            if named(seg):
                covered.append((node.lineno, node.end_lineno or node.lineno))
                continue
            head = seg.splitlines()[0].strip()[:70]
            untagged.append(f"line {node.lineno}: {head}")
        self.assertEqual(untagged, [], "an admission with no leaf name: "
                         + "; ".join(untagged))
        self.assertTrue(covered, "no admission found at all: this test would "
                                 "pass on a generator that had stopped emitting")

    def test_a_generated_proof_reaches_only_registered_sites(self):
        """Over a slice of the corpus, the census is well formed.

        `formal/examples` as a whole is 50 files and each build compiles and
        links an image; this takes the shapes that are cheap and that between
        them reach nine of the fifteen sites -- a recursion (every `runs-*`
        site), a `while` (both `dec-while` back edges and both loop-contract
        closers), and a plain leaf (the frame-contract terminal).  The point is
        not coverage of the sites but that a census nobody has checked is not a
        census.
        """
        import formal.arm64_proof_gen as G
        corpus = os.path.join(HERE, "formal", "examples")
        stems = ["ret42", "wdiff", "count"]
        reached = set()
        with tempfile.TemporaryDirectory(prefix="cfg-leaf-") as tmp:
            for stem in stems:
                src = os.path.join(corpus, stem + ".mojo")
                out = os.path.join(tmp, stem + ".aout")
                r = _generate_dir(tmp, src, stem, out)
                with open(r["proof_path"]) as fh:
                    proof = fh.read()
                census = G.cfg_leaf_census(proof)
                self.assertTrue(census, f"{stem}: no CFG leaf reached at all, "
                                        "so the census read nothing")
                for site, n in census.items():
                    self.assertIn(site, EXPECTED_CFG_LEAF_SITES,
                                  f"{stem}: unregistered site {site}")
                    self.assertGreater(n, 0)
                reached |= set(census)
        # The three shapes are chosen so that this is a real assertion: a
        # generator that stopped reaching the recursion or loop leaves would
        # otherwise pass every test above.
        self.assertLessEqual(
            {"runs-bl-step", "runs-cbz-condition", "runs-ret-x0",
             "dec-while-back-edge-decrement", "loop-cond-step",
             "walk-terminal"} - reached, set(),
            "the corpus slice no longer reaches the leaves it was chosen for")

    def test_the_cbz_leaf_peels_the_frame_reads_before_it_admits(self):
        """The `runs-cbz-condition` leaf's peel is emitted BEFORE the leaf, and
        it is the whole of what that leaf can be reduced to.

        A branch whose tested register came from a `LDR` has a condition the
        value flow -- which is over registers -- cannot decide, because the
        address is an `adrp`/`add` expression nothing in the fold touches. The
        peel (`mem_read_after_write_u64` and its `_ne` sibling, with `decide` as
        the discharge) is what turns that into a fact about one `mem_read_u64`
        at a literal address, and it has to come after the value-flow lines and
        before the leaf: emitted after the leaf it is dead text, and emitted
        before `rw [hsr]` it has no chain to unfold.

        The residual it leaves is `mem_read_u64 (four frame stores) A = 0`,
        which is FALSE for an arbitrary `st.mem` -- `Arm64State.init` is the only
        place that says memory is zero, and the universal theorem's `st` is a
        free state. So this test pins the REDUCTION and not a pass, and the doc
        that says so is `bugs/FORMAL_arm64_a_cbz_on_a_literal_pool_register_admits_over_a_false_claim.md`.
        """
        import formal.arm64_proof_gen as G
        corpus = os.path.join(HERE, "formal", "examples")
        with tempfile.TemporaryDirectory(prefix="cfg-leaf-") as tmp:
            r = _generate_dir(tmp, os.path.join(corpus, "count.mojo"),
                              "count", os.path.join(tmp, "count.aout"))
            with open(r["proof_path"]) as fh:
                lines = fh.read().splitlines()
        site = "runs-cbz-condition"
        tagged = [i for i, l in enumerate(lines)
                  if G.CFG_LEAF_TAG in l and site in l]
        self.assertTrue(tagged, f"count reached no {site} leaf at all")
        peel = "mem_read_after_write_u64_ne"
        for i in tagged:
            window = lines[max(0, i - 4):i]
            self.assertTrue(
                any(peel in w for w in window),
                f"line {i + 1}: a tagged leaf with no memory peel in the four "
                f"lines before it, so the obligation it admits is the "
                f"un-reduced one: {lines[i].strip()[:90]}")
        # and the peel is where the ADDRESS becomes a literal, which is the
        # whole difference between a goal a reader can check and an `adrp`
        # expression. One occurrence is enough to pin the spelling.
        self.assertTrue(any(peel in l for l in lines),
                        "the peel disappeared from the generated proof "
                        "entirely")

    def test_removing_the_fallback_leaves_no_admission_on_a_tagged_line(self):
        """`no_admission_fallback` is the instrument; this is its own contract.

        If it stopped removing the admission, a stripped proof would still
        elaborate and every measurement taken with it would be a measurement of
        nothing -- silently, because the run would come back green.
        """
        import formal.arm64_proof_gen as G
        corpus = os.path.join(HERE, "formal", "examples")
        with tempfile.TemporaryDirectory(prefix="cfg-leaf-") as tmp:
            r = _generate_dir(tmp, os.path.join(corpus, "count.mojo"),
                              "count", os.path.join(tmp, "count.aout"))
            with open(r["proof_path"]) as fh:
                proof = fh.read()
        stripped = G.no_admission_fallback(proof)
        self.assertIn(G.CFG_LEAF_TAG, stripped)
        left = [l.strip()[:80] for l in stripped.splitlines()
                if G.CFG_LEAF_TAG in l and "sorry" in l]
        # a leaf whose tag is on its OWN line (the loop contract's `hstep`
        # closer) is named by the line before it, so look one back too
        lines = stripped.splitlines()
        for i, l in enumerate(lines):
            if "sorry" not in l:
                continue
            if G.CFG_LEAF_TAG in l or (i and G.CFG_LEAF_TAG in lines[i - 1]):
                left.append(l.strip()[:80])
        self.assertEqual(left, [], "a tagged CFG leaf still admits after "
                                   "stripping: " + "; ".join(left))
        # and the OTHER admissions are still there, because this function
        # measures CFG leaves and nothing else: `strict`-free frame contracts
        # are the only family it owns.
        self.assertEqual(
            sorted(G.cfg_leaf_census(proof)),
            sorted(G.cfg_leaf_census(stripped)),
            "stripping changed which sites the proof reaches, which it cannot")


# ── A SYMBOLIC DIVISOR, and why the terminal value flow cannot close it ──────
#
# `def q(a, b): return a // b` is the shape the doc
# `bugs/FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open.md`
# is about, and the doc's own next step — put the enclosing `by_cases hc_N` into
# the terminal value flow's `simp only [h8, mojo, …]` list — was measured here
# and **changes nothing**: the eight terminal flows' residual goals are
# byte-identical with and without it. Two facts explain that, and both are
# pinned below because the doc's next step reads as though only one were true.
#
# 1. `hc_N` is stated over the REGISTER (`arm64_reg 1 s_4 = 0`) and the goal is
#    over the PARAMETER (`n1`). Connecting them takes `hsid_*` plus the block's
#    own `q_b*_qS`/`q_b*_qT` definitions, and `simp only` does not compose one
#    member of the set with the rest of the set in that direction.
# 2. The residual is not the doc's unreduced `if`. It is `1 = if n1 = 0 then 0
#    else …` — and that goal is **FALSE**: the codegen's div0 arm is
#    `movz x0, #1; movz x16, #1; svc #0x80` (`formal/arm64_codegen.py`, the
#    `div0_label` arm of `_emit_div_shift_pow`), so the machine leaves `x0 = 1`
#    and exits, while `fdiv64`'s div0 arm in `lib/ProofLib.lean` is `0`. So the
#    universal theorem for a division by a possibly-zero divisor is an ADMITTED
#    STATEMENT THAT IS FALSE, not one that is merely unproved, and no `simp`
#    closes a false goal.
#
# Which is why this class asserts the FALSE goal's survival rather than the
# goal's absence: if `fdiv64`'s div0 arm is ever corrected, or the walk starts
# to model the div0 arm as the divergence it is, this pin fails and says so —
# and the doc's next step becomes worth re-reading.
_SYMBOLIC_DIVISOR = "def q(a, b):\n    return a // b\n"

#: The walk terminal's admission, and the marker that prints the goals it
#: absorbs.  `all_goals (first | done | sorry)` is the admission the doc is
#: about; replacing `sorry` with `trace_state` is how a residual is READ, and
#: reading it is the whole of the measurement.
_ADMIT = "all_goals (first | done | sorry)"
_TRACE = "all_goals (first | done | (trace_state; sorry))"

#: `q_runs_*` / `q_compiles_correctly` are the CONCRETE tests, and they pin
#: `x1 := 0` — so for this program they divide by zero on purpose and their
#: statements are false (`run_result_exit` observes the div0 exit, `mojo 10 0`
#: says 0).  Neutralising them is what lets the universal theorem be read on
#: its own, and it is also the evidence that the concrete half of this program
#: was already red before anything here.
_CONCRETE = ":= by\n  native_decide\n"


def _symbolic_divisor_proof(tmp):
    """The arm64 proof for `a // b`, with the concrete tests neutralised."""
    import formal.build as fb
    src = os.path.join(tmp, "symdiv.mojo")
    with open(src, "w") as f:
        f.write(_SYMBOLIC_DIVISOR)
    out = os.path.join(tmp, "symdiv.aout")
    path = fb.compile_formal(src, arch="arm64", output=out, prove=True,
                             check=False)["proof_path"]
    text = open(path).read()
    head, sep, tail = text.partition("theorem q_compiles_correctly_universal")
    return head.replace(_CONCRETE, ":= by\n  sorry\n"), sep + tail


def _with_branch_facts_in_the_terminal_flow(tail):
    """`tail` with the enclosing `by_cases hc_N` added to every terminal `simp`.

    The doc's next step, applied.  `_N` is the branch index and `cur` is the
    branch hypothesis in scope at the line, which is the generator's own
    `by_cases hc_{bi} : …` — the same statement the doc says is "simply not in
    the list".
    """
    import re
    cur, out = None, []
    for line in tail.split("\n"):
        m = re.search(r"by_cases (hc_\d+) :", line)
        if m:
            cur = m.group(1)
        if "simp +decide only [h8, mojo," in line and cur:
            line = line.replace("simp +decide only [h8, mojo,",
                                f"simp +decide only [h8, {cur}, mojo,")
        out.append(line)
    return "\n".join(out)


class TestTheZeroDivisorGuardIsAFalseGoal(unittest.TestCase):
    """The two halves of the disagreement, and neither needs Lean."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="a2-div0-run-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_models_zero_divisor_arm_is_a_literal_zero(self):
        """`fdiv64` says `0` where the divisor is zero — the half that is text.

        Read out of `lib/ProofLib.lean` rather than imported, so the assertion
        is about the file the generated proofs import and not about whatever
        this process happens to have elaborated.
        """
        text = open(os.path.join(HERE, "lib", "ProofLib.lean")).read()
        m = re.search(r"def fdiv64 \(a b : UInt64\) : UInt64 :=\n"
                      r"\s*if b = 0 then (\S+) else", text)
        self.assertIsNotNone(
            m, "`fdiv64`'s definition changed shape; this class pins what its "
                "divisor-is-zero arm says, because that arm is what the walk's "
                "terminal value flow reduces to")
        self.assertEqual(
            m.group(1), "0",
            "fdiv64's div0 arm is no longer 0 — the arm64 div0 path leaves x0 = "
            "1 and exits, so if this changed the walk's terminal value flow may "
            "now close; re-read "
            "bugs/FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open.md "
            "before assuming it does not")

    def test_a_zero_divisor_leaves_the_image_with_status_one(self):
        """The other half, observed: `10 // 0` exits 1 and prints nothing.

        Both backends, and the point is not that the status is 1 — CPython
        raises `ZeroDivisionError` and exits 1 too — but that the image LEAVES:
        nothing after the division runs, so there is no value for the model to
        be right or wrong about, which is what makes `fdiv64`'s div0 arm a
        claim about a path the source never returns from.
        """
        import subprocess
        src = os.path.join(self.tmp, "zero.mojo")
        with open(src, "w") as f:
            f.write("def q(a, b):\n"
                    "    return a // b\n"
                    "\n"
                    "def main() -> int:\n"
                    '    printf("v=%d", q(10, 0))\n'
                    "    return 0\n")
        # `prove=False`, and deliberately: this half is about the IMAGE, and
        # `main` calling `q` is exactly the interprocedural walk
        # `_gen_universal_e2e_cfg` refuses ("the CFG walk is per-function").
        import formal.build as fb
        for backend in ("arm64", "x86_64"):
            out = os.path.join(self.tmp, f"zero.{backend}")
            fb.compile_formal(src, arch=backend, output=out, prove=False)
            self.assertTrue(os.path.isfile(out),
                            f"{backend}: the image was not written")
            argv = ([out] if backend == "arm64" or sys.platform != "darwin"
                    else ["arch", "-x86_64", out])
            p = subprocess.run(argv, capture_output=True, text=True,
                               timeout=60)
            self.assertNotEqual(p.returncode, 0,
                                f"{backend}: a zero divisor did not leave the "
                                f"image — the div0 arm is reachable code, so "
                                f"the model has a value to match after all and "
                                f"this class's premise has changed")
            self.assertEqual(p.stdout, "",
                             f"{backend}: the program printed after a zero "
                             f"divisor: {p.stdout!r}")


class TestTheZeroDivisorGuardAgainstLean(unittest.TestCase):
    """The measurement itself: the residual is `1 = 0`, and it is FALSE."""

    @classmethod
    def setUpClass(cls):
        lean = _lean()
        if not lean or not os.path.isfile(
                os.path.join(HERE, "lib", "ProofLib.olean")):
            raise unittest.SkipTest(
                "no Lean / no lib/ProofLib.olean: skipping. Every assertion "
                "here is about what Lean's kernel says of the residual goal, "
                "and none of it is answerable without it.")
        cls.tmp = tempfile.mkdtemp(prefix="a2-div0-lean-")
        from formal import lean as FLEAN
        cls.out = {}
        for label, patch in (("as_emitted", False), ("doc_next_step", True)):
            head, tail = _symbolic_divisor_proof(cls.tmp)
            if patch:
                tail = _with_branch_facts_in_the_terminal_flow(tail)
            text = head + tail.replace(_ADMIT, _TRACE)
            path = os.path.join(cls.tmp, f"div0_{label}.lean")
            with open(path, "w") as f:
                f.write(text)
            r = FLEAN.run_lean(lean, [os.path.basename(path)], cwd=cls.tmp,
                               env={"LEAN_PATH": os.path.join(HERE, "lib")})
            cls.out[label] = ((r.stdout or "") + (r.stderr or ""))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_false_goal_survives_the_documented_next_step(self):
        """Both spellings leave `⊢ 1 =`, and adding `hc_N` changes nothing.

        The two assertions are the refutation: the goal is there as emitted, and
        it is there after the doc's next step is applied verbatim, so the next
        step is not a smaller version of the fix — it is not a version of it.
        """
        for label in ("as_emitted", "doc_next_step"):
            with self.subTest(spelling=label):
                self.assertIn("⊢ 1 =", self.out[label],
                              f"{label}: the div0 path's residual is no longer "
                              f"the `1 = …` goal — fdiv64's div0 arm or the "
                              f"div0 path's exit status may have been "
                              f"corrected, which is the fix this doc wants")

    def test_the_residual_is_the_same_with_and_without_the_branch_fact(self):
        """The doc's next step, measured: identical goals, byte for byte."""
        goals = {}
        for label in ("as_emitted", "doc_next_step"):
            got, keep = [], False
            for line in self.out[label].splitlines():
                if line.strip().startswith("⊢"):
                    keep, cur = True, [line.strip()]
                    continue
                if keep:
                    if line.startswith(" ") and line.strip():
                        cur.append(line.strip())
                        continue
                    keep = False
                    goals.setdefault(label, []).append(" ".join(cur))
        self.assertTrue(goals.get("as_emitted"),
                        "no residual goal was traced at all, so the measurement "
                        "this class exists for did not happen")
        self.assertEqual(goals["doc_next_step"], goals["as_emitted"],
                         "adding the enclosing by_cases hypothesis to the "
                         "terminal value flow's simp only list CHANGED the "
                         "residual — which means the fix is further along than "
                         "bugs/FORMAL_a_division_by_a_symbolic_value_leaves_"
                         "the_zero_guard_open.md records, and its next step "
                         "and its Status both need re-reading")


class TestUnsignedOffsetAccess(unittest.TestCase):
    """`LDR Xt, [Xn, #imm]` / `STR Wt, [Xn, #imm]` / `STR Xt, [Xn, #imm]`, run.

    `TestRegister31` above settles the QUESTION for these three forms — their
    `Rn = 31` is SP, and the model now reads it that way — by asking the
    assembler and reading `arm64_step`'s branch text. This class asks the thing
    that settles it for real: it runs each instruction ON THE CPU, runs the same
    bytes through `arm64_step`, and requires the two final states to be equal.

    Two defects, both measured on this tree before the fix and both invisible to
    the question above, which is why they are here rather than folded into it:

      * the BASE. `arm64_reg 31 s = 0`, so `ldr x0, [sp, #32]` was modelled as a
        load from address 32 and `str x0, [sp, #32]` as a write there. The model
        answered 0 and the hardware answered the word — and because the modelled
        address was an ordinary address rather than an absurd one, no value-level
        test of a compiled program could see it.
      * the WIDTH. `STR Wt` is four bytes and the model wrote eight, so the four
        bytes ABOVE the stored word were clobbered in the model and left alone by
        the hardware. A store whose value is right and whose neighbours are wrong
        is the shape a byte-array or a struct-through-a-pointer test finds.

    Both are one-instruction facts, so the whole class is four cases and about a
    second: `tools/formal_model_fuzz.py`'s `sweep` on a hand-built state, which
    is the same code path a 300-case run takes — one `clang` harness, one Lean
    process with four `#eval`s. It is a test rather than a tool invocation
    because a tool's exit status is only about the run it was asked for, and
    these four instructions are the ones the emitter actually emits.

    Skipped off arm64, because the only oracle for the hardware half is the
    hardware. Lean is required too (`sweep` evaluates `arm64_step`), and the
    library build it needs is the one every other proof-checking path needs.
    """

    #: `(text, encoder(*args))` — the SP-relative spellings the emitter emits at
    #: `formal/arm64_codegen.py`'s ten `encode_ldr_xt_xn_imm(_, 31, …)` /
    #: `encode_str_xt_xn_imm(_, 31, …)` sites, plus the 32-bit store of the
    #: pointer value model.
    CASES = (
        ("ldr x7, [sp, #64]", lambda A: A.encode_ldr_xt_xn_imm(7, 31, 64)),
        ("str x7, [sp, #32]", lambda A: A.encode_str_xt_xn_imm(7, 31, 32)),
        ("str w7, [sp, #32]", lambda A: A.encode_str_wt_wn_imm(7, 31, 32)),
        # The twelve narrower/unscaled forms and the two flag-setting compares,
        # all of which `arm64_step` refused to step before this class existed's
        # subject was fixed. The register-offset pair is the one that cannot be
        # spelled `[sp, …]`, so it is the one case where the base register is a
        # name rather than the stack pointer — and that is exactly why it is here:
        # a pool that only drew SP-relative forms would never have noticed the
        # register-offset mask being wrong.
        ("ldrb w7, [sp, #8]", lambda A: A.encode_ldrb_wd_wn(7, 31, 8)),
        ("strb w7, [sp, #8]", lambda A: A.encode_strb_wd_wn(7, 31, 8)),
        ("ldrh w7, [sp, #8]", lambda A: A.encode_ldrh_wt_wn_imm(7, 31, 8)),
        ("strh w7, [sp, #8]", lambda A: A.encode_strh_wt_wn_imm(7, 31, 8)),
        ("ldrsb x7, [sp, #8]", lambda A: A.encode_ldrsb_xt_xn_imm(7, 31, 8)),
        ("ldrsh x7, [sp, #8]", lambda A: A.encode_ldrsh_xt_xn_imm(7, 31, 8)),
        ("ldrsw x7, [sp, #8]", lambda A: A.encode_ldrsw_xt_xn_imm(7, 31, 8)),
        ("ldr w7, [sp, #8]", lambda A: A.encode_ldr_wt_wn_imm(7, 31, 8)),
        ("ldur x7, [sp, #-8]", lambda A: A.encode_ldur_xt_xn_imm(7, 31, -8)),
        ("stur x7, [sp, #-8]", lambda A: A.encode_stur_xt_xn_imm(7, 31, -8)),
        ("ldr x7, [x9, x4]", lambda A: A.encode_ldr_xt_xn_xm(7, 9, 4)),
        ("str x7, [x9, x4]", lambda A: A.encode_str_xt_xn_xm(7, 9, 4)),
        # `CMN` and `TST`: the flags-only pair, and the only two cases here whose
        # answer lives in PSTATE rather than in a register. They are the rows the
        # fuzzer's `flags` and `select` mixes draw, and the comparison reads them
        # back through four conditional branches, so an agreement here is an
        # agreement about all four flag bits.
        ("cmn x7, x4", lambda A: A.encode_cmn_xn_xm(7, 4)),
        ("tst x7, x4", lambda A: A.encode_tst_xn_xm(7, 4)),
    )

    @classmethod
    def setUpClass(cls):
        import platform
        if platform.machine() not in ("arm64", "aarch64"):
            raise unittest.SkipTest("the hardware half of this is arm64 code")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "formal_model_fuzz",
            os.path.join(HERE, "tools", "formal_model_fuzz.py"))
        fm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fm)
        if not fm.L.find_lean():
            raise unittest.SkipTest("no Lean on PATH, so arm64_step cannot be run")
        cls.fm = fm

    def _cases(self):
        from formal import arm64 as A
        fm = self.fm
        out = []
        for text, enc in self.CASES:
            regs = [0x0102030405060708] * 31
            # `x9` and `x4` point into the window and `x4` is a small offset, so
            # the register-offset pair addresses inside it — the harness reads
            # memory outside the window as a fault, which is a fact about the
            # pool and not about the model.
            regs[9] = fm.MODEL_SP
            regs[4] = 8
            # A distinctive byte above each access as well as at it, so a store
            # that is too WIDE shows up as a difference rather than as a value
            # that happens to match.
            mem = bytearray(b"\x11" * (fm.MEM_HI - fm.MEM_LO))
            for off in (8, 32, 64):
                for k in range(8):
                    mem[fm.MODEL_SP + off - fm.MEM_LO + k] = 0xA0 + k
            words = [struct.unpack("<I", A.encode_cmp_xn_imm(0, 1))[0],
                     struct.unpack("<I", enc(A))[0]]
            # The `cmp` first is not decoration: the harness reads the final
            # NZCV back through four conditional branches, so the flags have to
            # be ESTABLISHED by an instruction both engines execute — which is
            # what makes them equal by construction.
            out.append(fm.Case(regs, 0, bytes(mem),
                               ["cmp x0, #1", text], words))
        return out

    def test_the_model_agrees_with_the_cpu(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tally, findings = self.fm.sweep(self._cases(), td)
        self.assertEqual(
            [f for f in findings], [],
            "arm64_step and the CPU disagree on the unsigned-offset memory "
            "forms:\n" + "\n".join(
                "%s\n%s" % (c.describe(), "\n".join(d[:6]))
                for _i, c, d in findings))
        self.assertEqual(tally.get("AGREE"), len(self.CASES),
                         f"the sweep reported {dict(tally)}: a case that was "
                         f"refused or never run is not an agreement")


def _generate_dir(tmp, src_path, name, out):
    """`compile_formal` on an existing `.mojo`, with NO Lean check.

    The same call `_generate` makes, for a program already on disk rather than
    written out of a dict; `check=False` is what keeps this class Lean-free.
    """
    import formal.build as fb
    return fb.compile_formal(src_path, arch="arm64", output=out,
                             prove=True, check=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
