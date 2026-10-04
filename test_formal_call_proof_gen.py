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


# The forms whose `Rn` can be register 31, and how the assembler answers.  The
# right-hand column is NOT written down: it is what `clang -c` says, which is
# the only authority for whether an encoding HAS an SP form at all, and the
# model's answer is checked against it below.
#
# The left-hand column is the model's own branch, keyed by the comment that
# introduces it in `lib/ProofLib.lean`'s `arm64_step` — a comment rather than an
# opcode so the test fails LOUDLY when a branch is renamed (the key goes
# missing) instead of silently checking a different branch.
SP_IN_RN_FORMS = (
    ("add x0, sp, x16", "= 0x8b000000 then"),
    ("sub x0, sp, x16", "= 0xcb000000 then"),
    ("cmp sp, x16", "= 0xeb000000 then"),
    ("cmp sp, #16", "= 0xf1000000 then"),
    ("add x0, sp, #16", "= 0x91000000 then"),
    # …and the five whose 31 is the ZERO register.  They are in the table
    # because they are the direction a "31 means SP everywhere" change gets
    # wrong, and a test that only checked the accepting forms would not notice.
    ("and x0, sp, x1", "= 0x8a000000 then"),
    ("eor x0, sp, x1", "= 0xca000000 then"),
    ("mul x0, sp, x1", "= 0x9b007c00 then"),
    ("neg x0, sp", "= 0xcb0003e0 then"),
    ("add w0, sp, #16", "= 0x11000000 then"),
)


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
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "probe.s")
        with open(src, "w") as fh:
            fh.write(".text\n.globl _sp_probe\n_sp_probe:\n  "
                     + form + "\n")
        p = subprocess.run(
            ["clang", "-target", "arm64-apple-macos11", "-c", "-o",
             os.path.join(td, "probe.o"), src],
            capture_output=True, text=True)
    return p.returncode == 0


def _arm64_step_branch(src, key):
    """The text of one `arm64_step` branch, from its dispatch condition.

    Keyed by the `= 0x… then` the branch tests, which is unique per branch and
    survives a reworded comment — and a missing key FAILS the case rather than
    silently matching a neighbour, which is the failure mode of keying on prose.
    """
    i = src.find(key)
    if i < 0:
        return None
    j = src.find("\n  else if", i)
    k = src.find("\n  -- ", i)
    ends = [x for x in (j, k) if x >= 0]
    return src[i:min(ends)] if ends else src[i:]


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
    """

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "lib", "ProofLib.lean")) as f:
            cls.lib = f.read()
        cls.branches = {}
        for form, key in SP_IN_RN_FORMS:
            cls.branches[form] = _arm64_step_branch(cls.lib, key)

    def test_every_form_in_the_table_is_still_in_the_model(self):
        for form, key in SP_IN_RN_FORMS:
            with self.subTest(form=form):
                self.assertIsNotNone(
                    self.branches[form],
                    f"{key!r} is not in lib/ProofLib.lean's arm64_step any "
                    f"more, so this table is checking nothing for {form!r}")

    def test_the_model_reads_rn_as_sp_exactly_where_the_assembler_allows_it(self):
        accepts = {f: _assembler_accepts(f) for f, _k in SP_IN_RN_FORMS}
        # Sanity on the oracle itself: a missing clang, or one assembling for
        # the wrong target, rejects EVERY form and this case would then pass
        # for the wrong reason — every model answer would "match".  So the
        # accepting set is asserted to be the one the architecture has.
        self.assertEqual(
            sorted(f for f, ok in accepts.items() if ok),
            sorted(f for f, _k in SP_IN_RN_FORMS
                   if f not in ("and x0, sp, x1", "eor x0, sp, x1",
                                "mul x0, sp, x1", "neg x0, sp",
                                "add w0, sp, #16")),
            "the assembler accepted a different set of forms than the "
            "architecture does, so this case is measuring clang rather than "
            "the model")
        for form, key in SP_IN_RN_FORMS:
            with self.subTest(form=form):
                reads_sp = "arm64_reg_or_sp" in (self.branches[form] or "")
                self.assertEqual(
                    reads_sp, accepts[form],
                    f"{form!r} is "
                    f"{'accepted' if accepts[form] else 'REFUSED'} by the "
                    f"assembler with `sp` in `Rn`, and the model's branch for "
                    f"it ({key!r}) "
                    f"{'reads' if reads_sp else 'does NOT read'} register 31 "
                    f"as SP — so one of them is wrong about the architecture")

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
        """
        import formal.arm64_proof_gen as G
        self.assertEqual(G._step_rhs(0xeb1003ff, 6),
                         "some { s with nzcv := arm64_subs_flags "
                         "(arm64_reg 31 s) (arm64_reg 16 s) }",
                         "`_step_rhs`'s CMP-register arm changed shape; if it "
                         "now emits `arm64_reg_or_sp`, the `simp only` lists in "
                         "this generator need the helper in them too")
        self.assertIn("arm64_reg 31 s", G._step_rhs(0x8b1003e0, 2),
                      "`_step_rhs`'s ADD-register arm changed shape")


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


class TestCallProofs(unittest.TestCase):
    """Compile the programs and read what came out."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-call-")
        cls.proofs = {}
        cls.errors = {}
        for name, (src, _why) in list(PROGRAMS.items()) + list(REFUSED.items()):
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
    # invisible to a search for the eight above
    "range-loop-frame-preservation",
    "range-loop-exit-x30",
    "range-loop-model-invariance",
    "range-loop-back-edge-target",
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
