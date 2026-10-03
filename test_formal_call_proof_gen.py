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


if __name__ == "__main__":
    unittest.main(verbosity=2)
