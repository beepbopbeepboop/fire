#!/usr/bin/env python3
"""`eval_eq_mojo`: the AST-evaluation bridge for a comparison-only body.

The arm64 proof of a straight-line, always-returning, loop-free function rests
on ONE theorem:

    theorem eval_eq_mojo (n : UInt64) :
      evalFunc ast (fun name arg => if name = "f" then mojo arg else 0) [n]
        = mojo n

`evalFunc`'s third argument is the model's ARGUMENT LIST: `MojoFunc.mk` carries
the source's parameter NAMES and `evalFunc` the model's argument values, and
the i-th name binds the i-th value (`MojoEnv`, whose two lemmas say so).  It
was one `UInt64` while the bridge bound one name; the list is what makes a
two-parameter model's AST faithful, and `_go_apply` applies one at its own
arity (`formal/model.py::entry_arity` is the reader both generators use).

The bridge is proved by splitting on the function's own conditions (`by_cases h0 : <cond>`)
and then letting `simp` close the goal.  That only works if the `by_cases`
hypothesis IS the `if` test in the goal, and for a **signed** comparison there
are two renderings of it:

  * the generator's `_cmp_go` spells the condition as the sign-flipped
    two's-complement word order, `(l ^^^ 0x8000…) < (r ^^^ 0x8000…)`;
  * `evalExpr` in `lib/ProofLib.lean` spells the same comparison as
    `sKey l < sKey r`, because `sKey` is that sign flip by name.

`by_cases` produces the first and the goal contains the second, so unless
`sKey` is in the simp set the two never meet definitionally: the `if` inside
the AST evaluation cannot be discharged by the hypothesis that decided it, and
the bridge is unprovable.  Ten of the forty-five `formal/examples/` were in
exactly that state (`absval`, `bigconst`, `condassign`, `condassign2`,
`deepif`, `elif3`, `ifonly`, `ifonly2`, `ifparam`, `twoifs` — every one of them
an `if` on a comparison and nothing else).  The x86-64 generator has carried
`sKey` in this simp set for the same reason.

The Lean half is skipped, loudly, when Lean or the built `lib/ProofLib.olean`
is absent; the text half runs either way, because a generator that emits a
bridge with no `sKey` in its simp set is wrong whether or not Lean is here to
say so.

    python3 test_formal_eval_eq_mojo_bridge.py [-v]
"""
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PROOF_GEN = os.path.join(HERE, "formal", "arm64_proof_gen.py")
PROOFLIB = os.path.join(HERE, "lib", "ProofLib.lean")

# One program per shape the ten failures had in common, kept small and
# self-contained (they do NOT read formal/examples/, which is a separate
# parser invariant with its own test).  Each is a function whose whole body is
# an `if` on a comparison, so the bridge is the only thing that can fail.
PROGRAMS = {
    # ifonly: one comparison, one `return` in each arm.
    "ifonly": "def ifonly(n):\n"
              "    if n > 0:\n"
              "        return 1\n"
              "    return 0\n",
    # condassign: the `if` assigns a local and the value is returned after it,
    # so the goal reads the variable back out of the environment.
    "condassign": "def condassign(n):\n"
                  "    x = 0\n"
                  "    if n > 0:\n"
                  "        x = 1\n"
                  "    return x\n",
    # elif3: three comparisons in one body, and the second one is only reached
    # on the fallthrough of the first.
    "elif3": "def elif3(n):\n"
             "    if n > 10:\n"
             "        return 3\n"
             "    elif n > 5:\n"
             "        return 2\n"
             "    elif n > 0:\n"
             "        return 1\n"
             "    else:\n"
             "        return 0\n",
}


def _read(path):
    with open(path) as f:
        return f.read()


def _lean():
    from formal.lean import find_lean
    return find_lean(HERE)


def _generate(tmp, source, name, arch="arm64"):
    """Compile `source`, return `(proof_path, error)`; error is None on success.

    Through `formal.build.compile_formal` rather than `fire.py`, so a generator
    exception arrives as an exception instead of as text on stderr."""
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


def _bridge_tactic(text):
    """The tactic proving `eval_eq_mojo`, or None when there is no bridge.

    A typed function omits the whole section (the untyped `evalExpr` model does
    not match a fixed-width source model), so its absence is not a failure; all
    three programs here are untyped, so it is present for each."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("theorem eval_eq_mojo ("):
            out = []
            for follow in lines[i + 1:]:
                if not follow.strip():
                    break
                out.append(follow)
            return "\n".join(out)
    return None


class TestBridgeSimpset(unittest.TestCase):
    """`sKey` has to be reachable from the bridge's simp set."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="bridge-simp-")
        cls.proofs, cls.errors = {}, {}
        for name, src in PROGRAMS.items():
            p, err = _generate(cls.tmp, src, name)
            cls.proofs[name], cls.errors[name] = p, err

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_program_generates_a_bridge(self):
        for name in PROGRAMS:
            with self.subTest(program=name):
                self.assertIsNone(self.errors[name],
                                  f"{name}: proof generation raised "
                                  f"{self.errors[name]}")

    def test_skey_is_in_the_bridge_simpset(self):
        for name, p in sorted(self.proofs.items()):
            if not p:
                continue
            with self.subTest(program=name):
                tac = _bridge_tactic(_read(p))
                self.assertIsNotNone(
                    tac, f"{name}: no `eval_eq_mojo` bridge was emitted")
                # The condition is split by `by_cases` and the goal is closed
                # by `simp`, so `sKey` must be in the SET (`simp_all [..]`) and
                # not merely somewhere in the tactic text.
                self.assertRegex(
                    tac, r"simp\w* \+decide \[[^\]]*\bsKey\b",
                    f"{name}: the bridge's simp set does not unfold `sKey`, so "
                    f"the `by_cases` hypothesis (the sign-flipped word order "
                    f"`_cmp_go` writes) and the goal's `if` (the `sKey l < sKey "
                    f"r` `evalExpr` writes) are two different terms and the "
                    f"bridge cannot close")

    def test_skey_is_what_evalexpr_compares_with(self):
        """The reason the simp entry exists, pinned on the library side.

        If `evalExpr` ever stops rendering a signed comparison through `sKey`,
        the simp entry above becomes a no-op and the ten examples go red
        again -- for a reason nothing here would report.  So assert the two
        facts the fix rests on, in the two files that carry them."""
        gen = _read(PROOF_GEN)
        self.assertIn("sKey", gen,
                      "the arm64 generator no longer mentions `sKey` at all")
        lib = _read(PROOFLIB)
        self.assertRegex(
            lib, r'def sKey \(x : UInt64\) : UInt64 :=',
            "`lib/ProofLib.lean` has no `sKey` definition; the bridge's simp "
            "entry would name an unknown constant and the file would not "
            "typecheck")
        n_signed = len(re.findall(
            r"=> if sKey \(evalExpr callFunc [lr] env\) [<>=≤≥]+ sKey", lib))
        self.assertGreater(
            n_signed, 0,
            "`evalExpr` no longer renders a comparison as `sKey l < sKey r`; "
            "the bridge's `sKey` entry has to be re-derived from whatever "
            "replaced it, not left as a token")


class TestBridgeTypechecks(unittest.TestCase):
    """The bridge must actually close, with no hole left behind."""

    @classmethod
    def setUpClass(cls):
        lean = _lean()
        if not lean or not os.path.isfile(
                os.path.join(HERE, "lib", "ProofLib.olean")):
            raise unittest.SkipTest(
                "no Lean / no lib/ProofLib.olean: skipping the typecheck. "
                "Run `make prooflib` (or `python3 tools/suite.py prooflib`) "
                "first -- every assertion below is about Lean accepting the "
                "generated bridge, and none of it runs without it.")
        from formal.lean import check_proof_cached
        cls.tmp = tempfile.mkdtemp(prefix="bridge-lean-")
        cls.results = {}
        for name, src in PROGRAMS.items():
            p, err = _generate(cls.tmp, src, name)
            if err:
                cls.results[name] = (False, err, 0)
            else:
                ok, detail, _cached, n = check_proof_cached(
                    p, repo_root=HERE)
                cls.results[name] = (ok, detail, n)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_bridge_typechecks_with_no_sorries(self):
        for name, (ok, detail, n) in sorted(self.results.items()):
            with self.subTest(program=name):
                self.assertTrue(ok, f"{name}: {detail}")
                self.assertEqual(n, 0, f"{name}: the proof admits {n} `sorry`")

class TestTheBridgeBindsEveryParameter(unittest.TestCase):
    """`MojoFunc.mk` carries the source's parameter NAMES, and all of them.

    `MojoFunc.mk` took ONE name and `evalFunc`'s environment answered 0 for
    every other name, so a two-parameter function's AST was a function whose
    second parameter was silently 0 — the bridge could not say what a
    two-parameter model was even if the rest of the apparatus could apply one.
    Both halves now carry a list, and this pins the emitted VALUE rather than
    the mechanism: the generated `ast` names every parameter of the source.

    It also pins what is still refused, because the two are the same fact seen
    from both sides: `_go_apply` refuses a model whose arity disagrees with the
    theorem it is the model of. A test that only checked the list would let
    someone widen one half and leave the other reading `binders[0]`.
    """

    def test_the_ast_value_names_every_parameter(self):
        """`_param_list_lean` — the ONE reader both generators use."""
        import formal.arm64_proof_gen as AP

        class _P:
            def __init__(self, *names):
                self.params = [(n, None) for n in names]

        self.assertEqual(AP._param_list_lean(_P("n")), '["n"]')
        self.assertEqual(AP._param_list_lean(_P("n", "m")), '["n", "m"]')
        self.assertEqual(AP._param_list_lean(_P("a", "b", "c")),
                         '["a", "b", "c"]')
        self.assertEqual(AP._param_list_lean(_P()), "[]")

    def test_the_generated_ast_carries_a_name_list_and_the_sites_pass_one(self):
        """The emitted TEXT of a one-parameter proof, which is what a reader of
        a generated file sees.

        `MojoFunc.mk "ifonly" "n"` became `MojoFunc.mk "ifonly" ["n"]`, and every
        `evalFunc`/`evalFuncF` site now passes the argument LIST. Both are
        invisible in a `PASS` — a proof that mentions an unknown constructor or
        passes a `UInt64` where a `List` is expected does not elaborate, which
        is a build failure the census reports as one, so this is a cheap text
        check for the class of change that a `native_decide` cannot catch.
        """
        tmp = tempfile.mkdtemp(prefix="bridge-params-")
        try:
            src = "def oneparam(n):\n    if n > 0:\n        return 1\n    return 0\n"
            p, err = _generate(tmp, src, "oneparam")
            self.assertIsNone(err, err)
            text = _read(p)
            ast = [ln for ln in text.split("\n") if ln.startswith("def ast :")]
            self.assertEqual(len(ast), 1,
                             f"expected exactly one `def ast`, got {ast}")
            self.assertIn('MojoFunc.mk "oneparam" ["n"]', ast[0],
                          "the AST does not carry the parameter NAME as a list")
            # The two statement shapes that carry the argument, spelled out
            # rather than pattern-matched across lines: the universal theorem's
            # `n` and one of the numbered `eval_eq_mojo_<v>` tests. The callFunc
            # between `evalFunc ast` and the argument wraps over three lines,
            # so a line-oriented check would be checking the wrong line.
            for want in ("[n] = mojo n",
                         "[(UInt64.ofNat 0)] = mojo (UInt64.ofNat 0)"):
                self.assertIn(want, text,
                              f"no `{want}` in the proof: an `evalFunc` site "
                              f"still passes a bare argument where the bridge "
                              f"now takes the model's argument LIST")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_two_parameter_model_is_applied_at_its_arity(self):
        """`_go_apply` at the model's arity, and a MISMATCH refused by name.

        It used to read `binders[0]` and apply ONE argument, which for
        `def f(a, b): return a + b` produced `def mojo (n : UInt64) := f_go n` —
        an argument-count error Lean does not recover from. The apparatus that
        made the correct application impossible (`mojo` declared
        `UInt64 -> UInt64`, one `n` in every theorem, `test_input` a single
        integer) is at the entry's arity now, so the correct application is the
        ordinary one.

        What is left to refuse is the case this is actually good at: a model
        whose arity disagrees with the theorem it is the model of, which is a
        GENERATOR bug rather than a program shape.
        """
        import formal.arm64_proof_gen as AP
        defs = ("def twoparam_go (a : UInt64) (b : UInt64) : UInt64 :=\n"
                "  a + b\n")
        self.assertEqual(AP._go_apply(defs, "twoparam", ["n", "n1"]),
                         "twoparam_go n n1")
        with self.assertRaises(NotImplementedError) as cm:
            AP._go_apply(defs, "twoparam")        # one argument, two binders
        msg = str(cm.exception)
        for needle in ("twoparam_go", "2 argument(s)", "1", "n"):
            self.assertIn(needle, msg,
                          f"the refusal must name BOTH counts, because a model "
                          f"and the theorem it is the model of disagreeing "
                          f"about the arity is what it exists to report; got "
                          f"{msg!r}")

    def test_prooflib_binds_by_position_and_leaves_an_unbound_name_at_zero(self):
        """The two library lemmas, named — the bridge's contract in one line each.

        They are `simp` on `MojoEnv`, so this asserts they EXIST rather than
        proving them: a rename would break the generated proofs' simp sets and
        this would name the new name instead of the old one.
        """
        lib = _read(PROOFLIB)
        self.assertRegex(lib, r"theorem mojoEnv_binds_by_position",
                         "lib/ProofLib.lean no longer states that the i-th name "
                         "binds the i-th value")
        self.assertRegex(lib, r"theorem mojoEnv_unbound_name_is_zero",
                         "lib/ProofLib.lean no longer states that a name no "
                         "argument answers for is 0")
        self.assertRegex(
            lib, r"\| mk \(name : String\) \(params : List String\)",
            "`MojoFunc.mk` does not carry a parameter-NAME list, so the AST "
            "cannot say what a two-parameter function takes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
