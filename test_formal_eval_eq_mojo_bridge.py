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


# `~` is BITWISE and `not` is LOGICAL, and one spelling for both was a MODEL
# bug rather than a codegen one: the generator rendered `~x` as
# `if x = 0 then 1 else 0`, which is `not`, so every program using `~` had a
# source model that is a model of a different program.  Nothing caught it
# because both sides of the bridge made the SAME mistake -- `evalExpr` evaluated
# `unop "not"` the same way -- so `eval_eq_mojo` agreed, about a program nobody
# ran.  The bug that measured this was filed as
# FORMAL_the_semantic_model_renders_a_bitwise_not_as_a_logical_one and is FIXED,
# so its doc is deleted per CLAUDE.md and the commit that landed this is the
# record.  The fix carries four sites (three in the generator, one in
# `lib/ProofLib.lean`) and has to carry all four, because a fix that lifted only
# the `_go` halves would make `eval_eq_mojo` FALSE for every program using `~`.
#
# The machine half turned out to need a fifth change, which that bug's "what is
# NOT the cause" asserted was not needed ("`~` lowers to ORN/NOT, and both are
# in the step tables"): `arm64_step`'s ORN arm matched `0x0A200000`, which is ORN
# (IMMEDIATE), while the codegen emits ORN (SHIFTED REGISTER) at `0xAA200000`
# as `MVN`'s alias -- so the word `~x` lowers to fell through every arm, and
# proof generation for ANY program containing `~` was refused with "CFG
# decomposition unsupported for this function shape".  The arm's body had the
# two source operands the wrong way round as well (`NOT Rn OR Rm` rather than
# `Rn OR NOT Rm`), which no emitted word had ever reached.  Both are pinned
# below, from the encoder's own bytes.
BITNOT_PROGRAM = "def main(n):\n    return ~n\n"
# The doc's own reproducer, one function and no call: the `& ~31` align idiom
# this repository uses in three places, which is where the wrong model was
# found.
BITNOT_ALIGN_PROGRAM = "def main(n):\n    return (n + 48) & ~31\n"


def _typed_model(source, root_name):
    """The `_go` text a TYPED function produces (fixed-width `vtypes`).

    `generate_arm64_proof` is what asks the typed question, through
    `types.uses_typed_model`; this asks the same two tables directly so the
    typed half can be read without compiling anything.
    """
    import formal.arm64_proof_gen as G
    from formal.build import parse_module
    from formal.types import (DEFAULT_INT_TYPE, function_var_types,
                              parse_type_name, resolve)
    from types import SimpleNamespace
    import fire_compiler as F

    fns = [f for f in parse_module(source) if isinstance(f, F.FunctionDef)]
    call_types = {g.name: resolve(parse_type_name(g.return_type) or DEFAULT_INT_TYPE)
                  for g in fns}
    root = next((f for f in fns if f.name == root_name), fns[-1])
    tc = {"typed": True, "vtypes": function_var_types(root, call_types),
          "call_types": call_types}
    prog = SimpleNamespace(functions=fns, externs=[])
    return "\n\n".join(G._go_defs_for(prog, root, tc))


def _models(source, root_name):
    """The UNtyped `_go` text, which is the other of the two model paths."""
    from test_formal_call_proof_gen import _models as untyped
    return untyped(source, root_name)


class TestBitwiseNotIsNotLogicalNot(unittest.TestCase):
    """The SOURCE half: the model of `~x`, and the AST that has to agree with it.

    Each row is one of the four sites, and they are four separate readers of one
    decision -- so the test is four rows rather than one, because a fix that
    lifted three of them leaves a model that is wrong in a way no single
    assertion can name.
    """

    def test_the_untyped_model_complements_every_bit(self):
        got = _models(BITNOT_PROGRAM, "main")
        self.assertIn("n ^^^ 0xFFFFFFFFFFFFFFFF", got,
                      f"the model of `~n` is not a bitwise complement:\n{got}")
        self.assertNotIn("if n = 0 then", got,
                         f"the model of `~n` is a LOGICAL not:\n{got}")

    def test_a_typed_complement_is_taken_at_the_declared_width(self):
        """32-bit `~x` is `t32s (x ^^^ 0xffffffff)`, not a 64-bit complement.

        The width matters and it is not a detail: a 32-bit `~x` that were
        modelled at 64 bits would agree with the machine only after the mask
        commuted with the truncator, which is one coincidence rather than one
        rule, and the machine's own lowering is "complement 64 bits, then
        `_emit_trunc` to the operand's declared type".
        """
        got = _typed_model("def f(n: Int32):\n    return ~n\n", "f")
        self.assertIn("t32s ((t32s n) ^^^ 0xffffffff)", got,
                      f"a 32-bit `~n` is not complemented at its own width:\n{got}")
        got16 = _typed_model("def f(n: UInt16):\n    return ~n\n", "f")
        self.assertIn("t16u ((t16u n) ^^^ 0xffff)", got16,
                      f"a 16-bit `~n` is not complemented at its own width:\n{got16}")

    def test_the_ast_names_bnot_and_leaves_not_logical(self):
        """`~` and `not` get different OPERATOR NAMES, so `evalExpr` can differ.

        Overloading one spelling for both is what made the bridge agree with a
        wrong model: both sides computed `not` for a program whose machine
        answer is MVN/NOT.
        """
        import formal.arm64_proof_gen as G
        from formal.build import parse_module
        import fire_compiler as F

        fns = [f for f in parse_module("def f(n):\n    return ~n\ndef g(n):\n"
                                       "    return not n\n")
               if isinstance(f, F.FunctionDef)]
        self.assertEqual(G._expr_ast(fns[0].body[0].value),
                         '(MojoExpr.unop "bnot" (MojoExpr.var "n"))')
        # The logical one keeps its name, because every condition in the corpus
        # spells it and `evalExpr`'s `"not"` arm is `if x = 0 then 1 else 0`.
        self.assertEqual(G._expr_ast(fns[1].body[0].value),
                         '(MojoExpr.unop "not" (MojoExpr.var "n"))')

    def test_eval_expr_renders_bnot_as_a_complement(self):
        """The LIBRARY half, in both places that have to know about it.

        `evalExpr`'s evaluation and the `evalExpr_unop` lemma are two
        statements of the same function, and the lemma is what
        `evalFunc_eq_mojo_all` is built from -- so a `bnot` arm added to one and
        not the other makes the library not typecheck, which is the cheap
        failure, rather than prove something false, which is not.
        """
        lib = _read(PROOFLIB)
        self.assertRegex(
            lib,
            r'\| MojoExpr\.unop "bnot" operand => evalExpr callFunc operand env \^\^\^ '
            r'\(0xFFFFFFFFFFFFFFFF : UInt64\)',
            "`evalExpr` does not evaluate `unop \"bnot\"` as a bitwise "
            "complement; it falls through to the identity arm and the model's "
            "`~n` is `n`")
        self.assertRegex(
            lib, r'\| "bnot" => evalExpr callFunc operand env \^\^\^ '
                r'\(0xFFFFFFFFFFFFFFFF : UInt64\)',
            "`evalExpr_unop` does not state `bnot` either, so the congruence "
            "and `evalFunc_eq_mojo_all` chain describes a different function "
            "than `evalExpr` defines")

    def test_the_orn_the_codegen_emits_is_the_orn_the_model_matches(self):
        """The machine half, from the encoder's own bytes.

        Asked of the words `formal/arm64.py` actually produces rather than of a
        literal, because the two disagreed once already: the model matched
        `0x0A200000` (ORN immediate) and the codegen emits `0xAA200000` (ORN
        shifted register), so an `~x` was an unmodelled word and
        `_step_branch_index` answered `None` for it. The second half of the
        assertion is the OPERAND ORDER, which is what makes the modelled
        complement `~Rm` and not all ones.
        """
        import struct
        import formal.arm64_proof_gen as G
        from formal.arm64 import encode_orn_xd_xn_xm, encode_mvn_xd_xn

        word = struct.unpack("<I", encode_mvn_xd_xn(0, 5))[0]
        self.assertEqual(word, 0xAA2503E0,
                         f"`encode_mvn_xd_xn(0, 5)` is {word:#010x}, not the "
                         f"0xAA2503E0 the assembler gives for `mvn x0, x5` "
                         f"(measured: clang assembles `mvn x0, x1` to "
                         f"0xAA2103E0, which is this encoding with Rm = 1). If "
                         f"the encoder moved, the row below is asserting about "
                         f"a word no image contains")
        idx = G._step_branch_index(word)
        self.assertEqual(
            idx, 33,
            f"`arm64_step` has no branch for the word `~x` lowers to "
            f"({word:#010x}): _step_branch_index says {idx}. That is the "
            f"unmodelled-word case -- proof generation refuses the whole "
            f"program -- and it is not a missing ARM feature, it is the "
            f"immediate/shifted-register encoding being confused")
        rhs = G._step_rhs(word, idx)
        # `Rn` is bits [9:5] = 31 (the zero register, which `arm64_reg` reads as
        # 0) and `Rm` is bits [20:16] = 5: OR NOT inverts the SECOND source, so
        # the complement belongs on register 5 and register 31 must not be the
        # one being complemented.
        self.assertIn("arm64_reg 31 s ||| ((arm64_reg 5 s) ^^^ 0xffffffffffffffff)",
                      rhs,
                      f"the modelled ORN puts the complement on the wrong "
                      f"source operand: {rhs}")
        # …and the ORN (immediate) encoding, which the model used to match, is
        # still not an ORN shifted register -- which is what makes a future
        # re-introduction visible rather than silent.
        self.assertIsNone(
            G._step_branch_index(0x0A200000 | 0x000003E0),
            "`0x0A200000` is being matched as a shifted-register ORN again")
        self.assertIsNotNone(
            G._step_branch_index(struct.unpack(
                "<I", encode_orn_xd_xn_xm(0, 7, 9))[0]),
            "`encode_orn_xd_xn_xm` emits a word the step table does not match, "
            "so a general ORN is unmodelled even though `MVN` is not")


TERNARY_PROGRAM = "def main(n):\n    return 1 if n > 3 else 0\n"


class TestAConditionalExpressionIsAValue(unittest.TestCase):
    """`a if c else b`: the model's two renderings, the AST's refusal, and the
    machine half's own word for what it cannot step.

    A conditional expression is the construct this file's sibling
    `bugs/FORMAL_a_conditional_expression_has_no_value_in_the_semantic_model.md`
    is about, and it is here rather than in that file because the subject is the
    same one this file is about: two renderings of a source construct that have
    to agree, and what happens when one of them cannot exist.

    Four things are pinned, and the last is the one that keeps the other three
    honest:

      * the UNTYPED model selects between the two words, at the condition's own
        signedness -- the comparison goes through `_cmp_go`, so `n > 3` on a
        signed `n` is the sign-flipped word order and not the unsigned one;
      * a NON-comparison condition is a test against zero, because Python's
        conditional expression tests truthiness (`_emit_truthy_word`'s rule on
        both backends) and not equality with zero;
      * the TYPED model carries the SELECTED word at the arms' common type, which
        is the one thing the typed path adds and the reason it cannot be the
        untyped term;
      * the arm64 refusal names the instruction it cannot step. The model is
        right and the machine half is not, and a reader who is sent to "this
        function shape" has nothing to look at.
    """

    def test_the_untyped_model_selects_between_the_two_words(self):
        got = _models(TERNARY_PROGRAM, "main")
        self.assertIn("then (UInt64.ofNat 1) else (UInt64.ofNat 0)", got,
                      f"`1 if n > 3 else 0` does not model as a selection "
                      f"between 1 and 0:\n{got}")
        # The SIGN-FLIPPED comparison is the point: an unsigned `n > 3` would
        # be a model of a different program for every negative `n`, and this is
        # the same term `_cmp_go` hands the `if` this expression is nested in.
        self.assertIn("(n ^^^ (0x8000000000000000 : UInt64)) > "
                      "((UInt64.ofNat 3) ^^^ (0x8000000000000000 : UInt64))",
                      got,
                      f"the condition is not rendered at its own signedness:\n"
                      f"{got}")

    def test_a_truthy_condition_is_a_test_against_zero(self):
        got = _models("def main(n):\n    return 1 if n else 0\n", "main")
        self.assertIn("if (n ≠ 0) then (UInt64.ofNat 1) else (UInt64.ofNat 0)",
                      got,
                      f"`1 if n else 0` tests equality with zero instead of "
                      f"truthiness, so it is wrong for every `n` that is neither "
                      f"0 nor 1:\n{got}")

    def test_a_nested_conditional_nests(self):
        got = _models("def main(n):\n"
                      "    return 2 if n > 9 else (5 if n > 3 else 7)\n",
                      "main")
        self.assertEqual(got.count("if (") , 2,
                         f"a nested conditional expression is not two nested "
                         f"selections:\n{got}")
        self.assertIn("else (if ", got,
                      f"the inner selection is not the else arm:\n{got}")

    def test_the_typed_model_carries_the_selection_at_the_arms_common_type(self):
        """`Int8` and `Int32` select into a word kept at the common type.

        This is the typed model's own addition: the machine carries the value of
        a conditional expression at the operands' type, so a selection of two
        narrow words into a wide one has to be re-widened by the same
        `_t_wrap` every arithmetic operator in `_expr_go_t` uses. Without it the
        model computes a number the register does not hold.
        """
        got = _typed_model("def f(a: Int8, b: Int32) -> Int32:\n"
                           "    return a if a > b else b\n", "f")
        self.assertIn("(t32s (if ", got,
                      f"the selected word is not carried at the arms' common "
                      f"type:\n{got}")

    def test_the_ast_refuses_rather_than_fabricating_a_zero(self):
        """`MojoExpr` has no conditional constructor, and the AST must SAY so.

        The fall-through this replaces returned `MojoExpr.int 0`, which is not a
        gap in the proof but a bridge that agrees with the model about a
        DIFFERENT program: the emitted file carried
        `def ast := … [MojoStmt.return (MojoExpr.int 0)]` under a comment
        reading "mirrors source code" for a source that says `1 if n > 3 else
        0`. Raising is what lets the caller DROP the bridge, which is the right
        answer here — the model's half of the two layers is real, so refusing
        the whole proof would be refusing it for the AST's missing constructor.
        """
        import formal.arm64_proof_gen as G
        from formal.build import parse_module
        import fire_compiler as F

        fns = [f for f in parse_module(TERNARY_PROGRAM)
               if isinstance(f, F.FunctionDef)]
        with self.assertRaises(NotImplementedError) as caught:
            G._expr_ast(fns[0].body[0].value)
        self.assertIn("conditional form", str(caught.exception),
                      "the refusal does not name the limit it is refusing for")

    def test_the_bridge_is_omitted_with_the_reason_named(self):
        """x86-64 can carry the program, so the bridge is dropped, not refused.

        This is the end-to-end statement of the previous row: the file has a
        REAL model, no `ast` value at all, and a note naming the gap. The
        assertion that matters is the middle one — `def ast` must be absent,
        because the alternative is a fabricated mirror of the source sitting in
        the file under a comment that says it mirrors the source.
        """
        tmp = tempfile.mkdtemp(prefix="ternary-")
        try:
            for arch in ("x86_64",):
                path, err = _generate(tmp, TERNARY_PROGRAM, "tern_" + arch,
                                      arch=arch)
                self.assertIsNone(err, f"{arch}: {err}")
                text = _read(path)
                self.assertIn("AST bridge omitted", text,
                              f"{arch}: the file does not say the bridge is "
                              f"omitted:\n{text[:400]}")
                self.assertIn("conditional form", text,
                              f"{arch}: the note does not name the gap")
                self.assertNotIn("def ast :", text,
                                 f"{arch}: an `ast` value was emitted anyway, so "
                                 f"the bridge is not really omitted")
                self.assertIn("then (UInt64.ofNat 1) else (UInt64.ofNat 0)",
                              text,
                              f"{arch}: the model is not the selection, so the "
                              f"generator fell back to a placeholder")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_arm64_refusal_names_the_select_it_cannot_step(self):
        """The machine half's own word for its gap, not "this function shape".

        `a if c else b` with pure operands is one `CSEL` on arm64, `arm64_step`
        has no branch for it, `_STEP_CONDS` deliberately has no row for it, and
        a block's runs certificate cannot be built — so the program gets no
        proof. That is unchanged; what changed is that the message names the
        instruction and the bug doc, which is the difference between a reader
        knowing where the wall is and re-deriving it.
        """
        import struct
        import formal.arm64_proof_gen as G
        from formal.arm64 import encode_csel_xd_xm_cond

        word = struct.unpack("<I", encode_csel_xd_xm_cond(0, 1, 2, "ne"))[0]
        self.assertEqual((word >> 21) & 0x7ff, 0x4d4,
                         f"`encode_csel_xd_xm_cond(0, 1, 2, \"ne\")` is "
                         f"{word:#010x}, whose bits 31..21 are "
                         f"{bin((word >> 21) & 0x7ff)} and not the CSEL field "
                         f"the refusal's diagnosis reads — so the refusal names "
                         f"an instruction the image does not contain")
        self.assertIsNone(G._step_branch_index(word),
                          "`arm64_step` grew a CSEL branch: the refusal message "
                          "is no longer the reason this program has no proof, "
                          "and `bugs/FORMAL_arm64_csel_is_not_modelled_so_the_"
                          "step_table_cannot_claim_it.md` should be re-read "
                          "before this row is deleted")

        tmp = tempfile.mkdtemp(prefix="ternary-arm64-")
        try:
            path, err = _generate(tmp, TERNARY_PROGRAM, "tern_arm64",
                                  arch="arm64")
            self.assertIsNone(path, "arm64 now generates a proof for this "
                                    "program, so the rows above are no longer "
                                    "the whole story — re-measure them")
            self.assertIn("CSEL", err,
                          f"the refusal does not name the instruction:\n{err}")
            self.assertIn("FORMAL_arm64_csel_is_not_modelled", err,
                          f"the refusal does not point at the measurement:\n"
                          f"{err}")
            self.assertIn("_ternary_go", err,
                          f"the refusal does not say the model states it:\n{err}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_spill_is_not_attributed_to_the_conditional_expression(self):
        """The other unmodelled word is a spill, and it says so.

        `STUR`/`LDUR` is the 9-bit-displacement form a frame access at a
        NEGATIVE offset needs, and the step table has arms for the scaled
        `STR`/`LDR` and not for these — so a function with enough spilled
        locals to reach below the entry `sp` gets no arm64 proof either, and has
        nothing to do with a conditional expression. This row is why the refusal
        names the instruction off its encoding instead of assuming the one
        construct this file is about: a message that blamed the ternary for a
        spill would send a reader to fix the wrong thing.

        Measured: twelve spilled locals is enough, and the words are
        `stur x0, [x29, #-0x58]` (`0xf81a83a0`) and `ldur` of the same shape.
        """
        locals_12 = "\n".join(f"    v{i} = {i} + n" for i in range(12))
        spill = ("def main(n):\n" + locals_12 + "\n    return "
                 + " + ".join(f"v{i}" for i in range(12)) + "\n")
        import formal.arm64_proof_gen as G
        import struct
        from formal.arm64 import encode_stur_xt_xn_imm, encode_ldur_xt_xn_imm
        for enc, want in ((encode_stur_xt_xn_imm, "STUR"),
                          (encode_ldur_xt_xn_imm, "LDUR")):
            word = struct.unpack("<I", enc(0, 29, -0x58))[0]
            self.assertEqual(G._unmodelled_instruction(word)[0], want,
                             f"{want} is not what the refusal names for "
                             f"{word:#010x}")

        tmp = tempfile.mkdtemp(prefix="spill-arm64-")
        try:
            path, err = _generate(tmp, spill, "spill_arm64", arch="arm64")
            self.assertIsNone(path, "a spilling function now generates an arm64 "
                                    "proof, so `bugs/FORMAL_arm64_instruction_"
                                    "coverage.md`'s LDUR/STUR row is stale and "
                                    "this row should be re-measured")
            self.assertNotIn("_ternary_go", err,
                             f"a spill is being blamed on the conditional "
                             f"expression:\n{err}")
            self.assertIn("STUR", err,
                          f"the refusal does not name the spill:\n{err}")
            self.assertIn("NEGATIVE offset", err,
                          f"the refusal does not say why the emitter reached "
                          f"for the unscaled form:\n{err}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestTheConditionalExpressionModelTypechecks(unittest.TestCase):
    """The teeth for the row above: the file with a REAL ternary model checks.

    The text rows can all pass against a model nothing can be proved about —
    that is the failure this repository's own `test_formal_run.py` docstring
    records ("images dyld refused to load … every one of those produced a
    *correct proof* about code that could not run"). So this asks Lean.

    x86-64 only, and the reason is the arm64 wall rather than a preference:
    `a if c else b` is one `CSEL` there and `arm64_step` has no branch for it,
    so arm64 refuses the program (`bugs/FORMAL_arm64_csel_is_not_modelled_so_
    the_step_table_cannot_claim_it.md`). What this pins on x86-64 is the half
    that IS landable now — that the model a conditional expression produces is
    a term the generated file accepts, that the bridge really is absent rather
    than present and unproved, and that the two designed trust boundaries are the
    only holes.

    Skipped, loudly, without Lean or `lib/ProofLib.olean`.
    """

    @classmethod
    def setUpClass(cls):
        lean = _lean()
        if not lean or not os.path.isfile(
                os.path.join(HERE, "lib", "ProofLib.olean")):
            raise unittest.SkipTest(
                "no Lean / no lib/ProofLib.olean: skipping the ternary "
                "typecheck. Run `python3 tools/suite.py prooflib` first.")
        from formal.lean import check_proof_cached
        cls.tmp = tempfile.mkdtemp(prefix="ternary-lean-")
        path, err = _generate(cls.tmp, TERNARY_PROGRAM, "tern_x86_64",
                              arch="x86_64")
        cls.error = err
        if err:
            cls.ok, cls.detail, cls.n = False, err, 0
            return
        ok, detail, _cached, n = check_proof_cached(path, repo_root=HERE)
        cls.ok, cls.detail, cls.n = ok, detail, n

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_file_with_a_conditional_expression_model_typechecks(self):
        self.assertTrue(self.ok, f"x86-64: {self.detail}")

    def test_the_only_holes_are_the_two_designed_trust_boundaries(self):
        self.assertEqual(self.n, 2,
                         f"the generated file admits {self.n} `sorry`; the "
                         f"x86-64 generator's two designed boundaries (the "
                         f"AST/model conformance theorem and the end-to-end "
                         f"one) are the only two this project admits, so a "
                         f"third is a hole nobody designed")


class TestBitwiseNotTheRunTestTypechecks(unittest.TestCase):
    """The teeth: `~n`'s run test `machine(n) = mojo n`, on BOTH backends.

    A `native_decide` run test is an evaluation of the model over the real
    instruction bytes, so it is the one assertion that cannot be satisfied by
    two wrong renderings of the same source. Before the fix it could not even be
    reached on arm64 (proof generation refused the program), and on the x86-64
    generator the same program's run test is what reported `is false` (the bug doc
    is deleted with its fix; the commit that landed this is the record).

    Skipped, loudly, when Lean or `lib/ProofLib.olean` is absent -- and that is
    a real gap in this file's coverage, because the fix it checks cannot be
    verified any other way: the text rows above would all pass against a model
    that no program could be proved about.
    """

    PROGRAMS = {"bnot": BITNOT_PROGRAM, "bnot_align": BITNOT_ALIGN_PROGRAM}

    @classmethod
    def setUpClass(cls):
        lean = _lean()
        if not lean or not os.path.isfile(
                os.path.join(HERE, "lib", "ProofLib.olean")):
            raise unittest.SkipTest(
                "no Lean / no lib/ProofLib.olean: skipping the run-test "
                "typecheck. Run `make prooflib` (or `python3 tools/suite.py "
                "prooflib`) first -- every assertion below is about Lean "
                "accepting the generated run test, and none of it runs without "
                "it.")
        from formal.lean import check_proof_cached
        cls.tmp = tempfile.mkdtemp(prefix="bnot-lean-")
        cls.results = {}
        for name, src in cls.PROGRAMS.items():
            for arch in ("arm64", "x86_64"):
                p, err = _generate(cls.tmp, src, f"{name}_{arch}", arch=arch)
                if err:
                    cls.results[(name, arch)] = (False, err, 0)
                    continue
                ok, detail, _cached, n = check_proof_cached(p, repo_root=HERE)
                cls.results[(name, arch)] = (ok, detail, n)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_program_generates_and_its_run_test_typechecks(self):
        for (name, arch), (ok, detail, n) in sorted(self.results.items()):
            with self.subTest(program=name, arch=arch):
                self.assertTrue(
                    ok,
                    f"{name} on {arch}: {detail}\n\nThe run test is the only "
                    f"assertion here that cannot be satisfied by the model and "
                    f"the AST agreeing about the wrong program: a `native_decide` "
                    f"over `arm64_step`/`x86_step` and the emitted bytes. If it "
                    f"says `is false`, one of the two is not what the machine "
                    f"does.")
                self.assertLessEqual(n, 2,
                                     f"{name} on {arch}: the proof admits {n} "
                                     f"`sorry`; the x86-64 generator's two "
                                     f"designed trust boundaries are the only "
                                     f"two this project admits, and the arm64 "
                                     f"file admits none")


if __name__ == "__main__":
    unittest.main(verbosity=2)
