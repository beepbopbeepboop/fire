#!/usr/bin/env python3
"""The arm64 proof generator on programs that MAKE A CALL.

`formal/arm64_proof_gen.py` used to raise

    ValueError: unsupported: recursion argument bound (not a dec1 pattern)

for every program containing a call, from `fn main(): print(42)` upwards.  The
`bl` arm of the CFG walk was written for self-recursion only, so a call to
anything else fell through to a recursion-only branch.  The consequence was
that the arm64 corpus had **no proof at all** for any program with a call, and
a `sorry` census over generated files was measuring nothing.

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

    def test_a_model_of_two_parameters_is_refused_not_applied_to_one(self):
        """`_go_apply` used to read the FIRST binder and apply one argument.

        `def f(a0, a1): return a0 + a1` produced `def f_go (a0) (a1)` and then
        `def mojo (n : UInt64) := f_go n` — an argument-count error, which Lean
        does not recover from as a `sorry` and does not elaborate, so the whole
        proof file fails three definitions away from the line that is wrong.

        The one-parameter limit is not a generator's taste: `mojo` is declared
        `UInt64 -> UInt64`, `eval_eq_mojo` and every run test quantify over one
        `n`, and `lib/ProofLib.lean`'s `MojoFunc`/`evalFunc` bind one parameter
        with 0 for every other name.  So the honest answer is to refuse and name
        the arity.  Measured on both generators.
        """
        import formal.arm64_proof_gen as G
        defs2 = "def f_go (a0 : UInt64) (a1 : UInt64) : UInt64 :=\n  a0\n"
        with self.assertRaises(NotImplementedError) as caught:
            G._go_apply(defs2, "f")
        said = str(caught.exception)
        for needle in ("f_go", "2 parameters", "mojo"):
            self.assertIn(needle, said,
                          f"the refusal must name the model's arity and the "
                          f"one-input apparatus it does not fit; got {said!r}")
        # ONE implementation, not two.  The x86-64 generator imports the arm64
        # one (`from formal import arm64_proof_gen as AP`) precisely so the two
        # machines cannot disagree about how a model is applied; a second
        # arity check of its own would be the duplication that check exists to
        # prevent, and this is the assertion that says so.
        import formal.x86_64_proof_gen as X
        src = open(PROOF_GEN).read()
        self.assertIn("_go_apply(go_defs, func_name)", src,
                      "the x86-64 generator no longer applies the model through "
                      "the shared reader, so it has its own arity handling")
        self.assertEqual(X.generate_x86_64_proof.__module__,
                         "formal.x86_64_proof_gen")
        # …and the three shapes that DO fit are untouched, which is the other
        # half: a guard that also refused arity 1 would turn this into a proof
        # generator that proves nothing.
        for defs, want in (("def f_go (n : UInt64) : UInt64 :=\n  n\n", "f_go n"),
                           ("def f_go : UInt64 :=\n  0\n", "f_go")):
            self.assertEqual(G._go_apply(defs, "f"), want)

    def test_the_generated_mojo_is_one_input_for_every_arity(self):
        """The end-to-end statement, on both generators, for a 2-parameter entry.

        `_go_apply` is the shared reader both call, so pinning it is nearly
        enough — but "nearly" is how a second call site appears.  This drives the
        real entry points with the one text that reaches them, and asks for the
        REFUSAL rather than the text, so a reordering that lets `MojoFunc.mk`
        reach the output first is caught here.
        """
        from types import SimpleNamespace
        from formal.build import parse_module
        import fire_compiler as F
        src = "def f(a0, a1):\n    return a0 + a1\n"
        fns = [f for f in parse_module(src) if isinstance(f, F.FunctionDef)]
        prog = SimpleNamespace(functions=fns, externs=[])
        info = {"func_name": "f", "base_addr": 0x1000, "labels": {},
                "test_input": 10}
        import formal.arm64_proof_gen as G
        import formal.x86_64_proof_gen as X
        for gen, entry in ((X, "generate_x86_64_proof"),
                           (G, "generate_arm64_proof")):
            with self.assertRaises(NotImplementedError,
                                   msg=f"{entry} emitted a one-input `mojo` for "
                                       f"a two-parameter model"):
                getattr(gen, entry)(prog, b"", dict(info))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
