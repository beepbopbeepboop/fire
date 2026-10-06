#!/usr/bin/env python3
"""The arm64 proof generator on a SHORT-CIRCUIT `and`/`or` used as a condition.

`if a or b:` and `if a and b:` do not lower to one conditional branch.
`_emit_truthy_word` recurses into both operands and branches between them
(`formal/arm64_codegen.py`), so there are two: the chain's OWN branch,
whose taken edge skips the right operand, and the `if`'s own branch, in
the merge block that both paths reach.  That block's register holds the
LEFT operand's cset on the short-circuit path and the RIGHT one's on the
fallthrough, so no single

    arm64_reg r <block> = 0 ↔ ¬(<source condition>)

describes it, and `bugs/FORMAL_arm64_known_proof_gaps.md` recorded the
per-path statement as not expressible.  Three things were wrong about
it, and each is a separate defect this file pins:

  * the source condition was paired with the i-th CONDITIONAL block, and
    a short-circuit condition puts the chain's own branch first — so
    `if a or b:` was read as `if a:` and `bv_decide` returned the
    counterexample.  The pairing is now with the block whose terminator
    the codegen RECORDED as the `if`/`while` test
    (`info["cond_branches"]`);
  * the `*_entry_cond` seed claimed `arm64_reg r <merge block> = 0 ↔ ¬(…)`
    for a merge block that contains no cset at all, so no register
    carried that condition — and nothing referenced the theorem, so its
    entire effect was `bv_decide`'s counterexample;
  * a CBNZ's step-RESULT lemma was proved by `by_cases … ≠ 0` while the
    MODEL's `if` is normalised to `= 0` as soon as `arm64_reg` unfolds,
    so the branch's own `*_sr_N` lemma did not typecheck — and that
    affects every program with a CBNZ, not only these two.

The Lean check is skipped, loudly, when Lean is unavailable; everything
else runs either way, because a generator that cannot even produce text
is worth catching without a 27MB library build.

    python3 test_formal_short_circuit_cond.py [-v]
"""
import ast
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PROOF_GEN = os.path.join(HERE, "formal", "arm64_proof_gen.py")

# `or` and `and`, plus the two examples in `formal/examples/` the gap was
# recorded against, because a hand-written program that happens to elaborate
# is not the same evidence as the one the bug doc names.
PROGRAMS = {
    "short_or": ("def f(n):\n"
                 "    if n > 10 or n == 0:\n"
                 "        return 1\n"
                 "    else:\n"
                 "        return 0\n",
                 "`or`: the chain's branch is a CBNZ, taken when the LEFT is "
                 "truthy"),
    "short_and": ("def f(n):\n"
                  "    if n > 0 and n < 10:\n"
                  "        return 1\n"
                  "    else:\n"
                  "        return 0\n",
                  "`and`: the chain's branch is a CBZ, taken when the LEFT is "
                  "falsey"),
}

# A chain NESTED inside a chain is a separate, recorded gap: see
# bugs/FORMAL_nested_short_circuit_chain_in_a_condition.md.  `((a or b) or c)`
# gives the outer merge FOUR entry paths, each with a different cset having
# written the register, so the two-path statement this file is about does not
# reach it.  It is listed here so the boundary is a test rather than a comment.
#
# **Its MODEL half is proved (2026-10-05) and its MACHINE half is not.**  The
# `eval_eq_mojo` statement — the AST evaluator against the semantic model — used
# to be left open for this shape on BOTH architectures, because `lib/ProofLib`
# spells a nested `or` as a curried `¬a → ¬b → c` and the emitted split was on
# the whole disjunction; `eval_split_conds` now also splits on the chain's
# leaves, and `TestLeanModelBridge` below typechecks that theorem in isolation.
# What still fails is the machine half: sixteen `counterexample`s on the `hcond`
# statements in the universal theorem, and the kernel's memory ceiling on the
# same file (which is why that theorem is checked apart from this one and not as
# part of it).  So this entry is still a gap, for a narrower reason than it was.
KNOWN_GAP = {
    "nested_or": ("def f(n):\n"
                  "    if n > 10 or n == 0 or n < -4:\n"
                  "        return 1\n"
                  "    else:\n"
                  "        return 0\n",
                  "bugs/FORMAL_nested_short_circuit_chain_in_a_condition.md: "
                  "the MACHINE half. The merge statement's right-hand side is a "
                  "nested chain's VALUE, and `simp [h]` cannot split the `Or`, so "
                  "the operand that did not write the register is unconstrained "
                  "and `bv_decide` reports a counterexample. Measured 2026-10-03 "
                  "on the emitted proofs: the `rw`/`simp only`/"
                  "mem_read_two_writes_adj_uint` lines are character-for-character "
                  "the passing two-operand case's, and the RIGHT-nested spelling "
                  "(`n > 10 or (n == 0 or n < -4)`) fails the same way, so it is "
                  "the `Or` and not which side the sub-chain is on. Re-measured "
                  "2026-10-05: 16 counterexamples plus the kernel's memory "
                  "ceiling, and the model half is now proved on both "
                  "architectures"),
}

EXAMPLE_STEMS = ("either", "both")


def _model_only(proof_path):
    """The generated file truncated to just `eval_eq_mojo`, or None.

    `eval_eq_mojo` is the AST-evaluator-against-the-semantic-model statement,
    and it is INDEPENDENT of the universal theorem that follows it: nothing in
    the model bridge names anything the machine half defines.  So the honest way
    to check it for a program whose machine half does not typecheck (which
    `nested_or` does not, and `either`/`both` do not either — Lean's kernel
    refuses them, see `bugs/FORMAL_a_generated_proof_over_leans_memory_ceiling_is_
    rejected.md`) is to cut the file at the next top-level declaration after the
    theorem and check that.

    Which is a real check and not a weakened one: a truncation that cut a
    `theorem` in half is a SYNTAX error and Lean says so rather than passing,
    and the same `formal/lean.py::run_lean` bounds, the same `lib/` and the same
    kernel apply to what is left.
    """
    lines = open(proof_path).read().split("\n")
    try:
        start = next(i for i, l in enumerate(lines)
                     if l.startswith("theorem eval_eq_mojo "))
    except StopIteration:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith(("/--", "theorem ", "def ", "abbrev ")):
            end = i
            break
    return "\n".join(lines[:end]) + "\n"


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
    """Compile `source` and return `(proof_path, error)`."""
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


def _cond_nodes_of(stem):
    """`(node, op)` for each condition of `formal/examples/<stem>.mojo`."""
    from formal.build import parse_module
    import fire_compiler as F
    import formal.arm64_proof_gen as G
    src = os.path.join(HERE, "formal", "examples", stem + ".mojo")
    fns = [f for f in parse_module(open(src).read())
           if isinstance(f, F.FunctionDef) and f.params]
    fn = fns[-1]
    p = fn.params[0][0]
    return [(n, getattr(n, "op", None), e)
            for n, e in G._cond_nodes(fn, p, {}, {}, None)]


class TestGeneratorSource(unittest.TestCase):
    """Invariants on the generator itself, which need no compilation."""

    def test_no_duplicate_top_level_definitions(self):
        src = open(PROOF_GEN).read()
        names = [n.name for n in ast.parse(src).body
                 if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        dupes = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(dupes, [],
                         f"formal/arm64_proof_gen.py defines {dupes} twice; "
                         f"Python binds the last, so an edit to the other copy "
                         f"is silently inert")

    def test_cond_nodes_agrees_with_collect_conds(self):
        """`_cond_nodes` is the walk `_collect_conds` renders.

        The two are paired with CFG blocks BY POSITION, so a disagreement
        between them is not a weaker proof but a proof about the wrong
        condition, which is exactly what the short-circuit bug was.

        **Both sides walk in the SAME environment, and the walk used to be
        handed an EMPTY one** — `_cond_nodes(fn, p, {}, {}, None)` — while the
        renderer was handed `{p: p}`.  `_cond_nodes`' third argument is `env`
        and `None` is what means "bind `param` to itself", so `{}` means "bind
        nothing", and rendering a condition that reads `n` in it raises
        `model: 'n' is read here and this generator binds it to nothing`.  So
        this test could not pass on ANY tree: it was an ERROR, not a failure,
        for as long as it existed, and it is the test that guards the pairing
        the whole file is about.  The two environments are now the same object.
        """
        import formal.arm64_proof_gen as G
        from formal.build import parse_module
        import fire_compiler as F
        for stem in EXAMPLE_STEMS + ("twoifs", "deepif", "elif3", "countdown",
                                     "sum_range", "wdiff"):
            src = open(os.path.join(HERE, "formal", "examples",
                                    stem + ".mojo")).read()
            for fn in [f for f in parse_module(src)
                       if isinstance(f, F.FunctionDef) and f.params]:
                p = fn.params[0][0]
                env = {p: p}
                rendered = G._collect_conds(fn, p, env, {}, {})
                walked = [G._norm_uint(G._cmp_go(node, p, node_env, {}, {},
                                                 None))
                          for node, node_env in G._cond_nodes(fn, p, env, {},
                                                             {}, None)]
                self.assertEqual(rendered, walked,
                                 f"{stem}.{fn.name}: the condition walk and "
                                 f"its renderer disagree, so a condition is "
                                 f"paired with the wrong CFG block")

    def test_condition_pairing_filters_on_the_recorded_branch(self):
        """The pairing must be a FILTER, not the i-th conditional block.

        A short-circuit condition emits a conditional branch of its own, so
        pairing by position attributes the whole condition to that one — and
        its register holds the chain's LEFT operand."""
        src = open(PROOF_GEN).read()
        self.assertIn("_cond_blocks", src,
                      "the condition/block pairing no longer distinguishes "
                      "the `if`'s own branch; a short-circuit condition is "
                      "attributed to the chain's own branch again")
        i = src.index("_cond_blocks = [b for b in blocks")
        window = src[i:i + 400]
        self.assertIn("cond_branches", window,
                      "the pairing must use `info['cond_branches']`, the "
                      "terminators the codegen recorded as `if`/`while` tests")

    def test_entry_cond_seed_requires_a_cset_in_the_selected_block(self):
        """The seed claims a fact about a REGISTER.

        It is true only when a cset in the block it names wrote that
        register with the source condition.  A merge block after a
        short-circuit chain has no cset at all, and the theorem is
        referenced by nothing — so emitting it there fails the build with
        `bv_decide`'s counterexample and no other effect."""
        src = open(PROOF_GEN).read()
        i = src.index("_emittable = ")
        window = src[i:i + 600]
        self.assertIn("_cset_registers", window,
                      "the `*_entry_cond` seed is emitted without checking "
                      "that the selected block wrote the register it "
                      "describes")

    def test_cbnz_step_result_splits_on_equality_to_zero(self):
        """A CBNZ's result lemma must split on `= 0`, not on `≠ 0`.

        `_step_rhs` states the CBNZ as `if arm64_reg r s ≠ 0 then …`, but
        the MODEL does not keep that sense: unfolding `arm64_reg` turns it
        into `= 0`, so a `by_cases … ≠ 0` has already fixed the case the
        other way and cannot retire the goal.  This affects every program
        with a CBNZ."""
        import formal.arm64_proof_gen as G
        # `CBNZ X0, #0` — register 0 so the emitted split names `s.x0`.
        text = G._gen_step_result_lemmas("t", (0xB5000000).to_bytes(4, "little"),
                                         0)
        self.assertIn("by_cases hp : s.x0 = 0", text,
                      "the CBNZ step-result lemma does not split on "
                      "`= 0`; the model's `if` is normalised to that sense "
                      "and the lemma cannot close")

    def test_a_nested_chain_splits_on_its_leaves(self):
        """`eval_eq_mojo`'s split list must reach INSIDE a chain.

        `lib/ProofLib`'s `evalExpr` spells a binary `or` as `¬x → y`, so
        `((a or b) or c)` nests that to `¬a → ¬b → c` — which is not the
        disjunction the emitted hypothesis carries.  One `by_cases` on the
        whole condition leaves `case pos` with `h0 : (A ∨ B) ∨ C ⊢ ¬(¬A →
        ¬B → C)`, which is TRUE and is not retirable without knowing whether
        `B` holds.  Measured on the program this file's `KNOWN_GAP` names:
        arm64 and x86-64 both left that goal open before `eval_split_conds`.
        """
        import formal.arm64_proof_gen as G
        from formal.build import parse_module
        import fire_compiler as F
        src = KNOWN_GAP["nested_or"][0]
        fn = [f for f in parse_module(src)
              if isinstance(f, F.FunctionDef) and f.params][-1]
        p = fn.params[0][0]
        split = G.eval_split_conds(fn, p, G._entry_env(fn, 1))
        self.assertEqual(len(split), 3,
                         f"a three-operand nested chain must split on the "
                         f"whole condition and on each of its two leaves, got "
                         f"{len(split)}")
        for leaf in ("(n = 0)", "(if ((n ^^^ (0x8000000000000000 : UInt64)) "
                     "> (10 ^^^ (0x8000000000000000 : UInt64))) then"):
            self.assertTrue(
                any(leaf in t for t in split),
                f"the split list has no proposition naming {leaf!r}, so the "
                f"case that needs it has nothing to close it with")

    def test_a_flat_chain_still_splits_on_nothing_extra(self):
        """The GUARD for the row above, and the reason it costs nothing.

        A chain that is NOT nested has no `and`/`or` descendant, so the extra
        propositions do not exist and the emitted text is character-for-character
        what it was — which is the standard a proof-generator change has to meet
        (`CLAUDE.md`: byte-identical generated output on a large succeeding
        case).  Measured: ten `formal/examples/` stems x two architectures, 40
        generated proofs, all 40 byte-identical before and after.
        """
        import formal.arm64_proof_gen as G
        from formal.build import parse_module
        import fire_compiler as F
        for stem in EXAMPLE_STEMS:
            src = open(os.path.join(HERE, "formal", "examples",
                                    stem + ".mojo")).read()
            for fn in [f for f in parse_module(src)
                       if isinstance(f, F.FunctionDef) and f.params]:
                p = fn.params[0][0]
                self.assertEqual(
                    G.eval_split_conds(fn, p, G._entry_env(fn, 1)),
                    G._collect_conds(fn, p, G._entry_env(fn, 1)),
                    f"{stem}.{fn.name}: a flat chain gained a proposition, so "
                    f"its emitted proof grew goals it did not need")


class TestShortCircuitProofs(unittest.TestCase):
    """Compile the programs and read what came out."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="a2-sc-")
        cls.proofs = {}
        cls.errors = {}
        for name, (src, _why) in PROGRAMS.items():
            p, err = _generate(cls.tmp, src, name)
            cls.proofs[name] = p
            cls.errors[name] = err
        for stem in EXAMPLE_STEMS:
            src = os.path.join(HERE, "formal", "examples", stem + ".mojo")
            out = os.path.join(cls.tmp, stem + ".aout")
            try:
                import formal.build as fb
                cls.proofs[stem] = fb.compile_formal(
                    src, arch="arm64", output=out, prove=True,
                    check=False)["proof_path"]
                cls.errors[stem] = None
            except Exception as e:        # noqa: BLE001
                cls.proofs[stem] = None
                cls.errors[stem] = f"{type(e).__name__}: {e}"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_program_generates_a_proof(self):
        for name in PROGRAMS:
            self.assertIsNone(self.errors[name],
                              f"{name}: proof generation raised "
                              f"{self.errors[name]}")

    def test_the_merge_block_states_one_operand_not_the_whole_condition(self):
        """The `hcond` at the merge block is about ONE operand.

        `arm64_reg r <merge> = 0` is `¬(left)` on the short-circuit path
        and `¬(right)` on the fallthrough, so a statement naming the whole
        condition is false for one of them — and `bv_decide` finds the
        counterexample."""
        for name, p in sorted(self.proofs.items()):
            if not p:
                continue
            text = open(p).read()
            m = re.search(r"have hcond_\d+ : \(arm64_reg \d+ s_\d+ = 0\) "
                          r"↔ ¬\((.*?)\) := by", text, re.S)
            self.assertIsNotNone(
                m, f"{name}: the merge block's `hcond` is missing, so the "
                   f"register's value is never related to any condition")
            whole = re.search(r"\(if .*?≠ 0\) (?:∨|∧) \(if .*?≠ 0\)",
                              m.group(1), re.S)
            self.assertIsNone(
                whole, f"{name}: the merge block's `hcond` names the WHOLE "
                       f"condition `{m.group(1)[:90]}`, which its register "
                       f"does not hold on both entry paths")

    def test_the_chain_branch_hands_one_fact_down(self):
        """`hscL`, not an `hsrc`.

        The generator's taken/fall sense is the `if`'s — the taken edge
        means the condition is FALSE — and a short-circuit branch's taken
        edge means the LEFT is truthy (`or`) or falsey (`and`).  So it
        cannot carry an `hsrc`; it carries a fact about the left operand
        and lets the merge block combine it."""
        for name, p in sorted(self.proofs.items()):
            if not p:
                continue
            text = open(p).read()
            self.assertIn("have hscL_", text,
                          f"{name}: the chain's own branch does not hand a "
                          f"fact about its left operand down")
            # `or` rebuilds the whole condition with `Or.inl`/`Or.inr` (it has
            # no projection); `and` with the conjunction's projections.
            src = PROGRAMS.get(name, ("", ""))[0] or open(
                os.path.join(HERE, "formal", "examples",
                             name + ".mojo")).read()
            marker = "Or.inl hscL_" if " or " in src else "h.1 hscL_"
            self.assertIn(marker, text,
                          f"{name}: the whole condition is never rebuilt from "
                          f"the left operand's fact ({marker} is how each "
                          f"operator does it)")

    def test_no_entry_cond_seed_for_a_merge_block(self):
        for name, p in sorted(self.proofs.items()):
            if not p:
                continue
            text = open(p).read()
            self.assertNotIn("_entry_cond", text,
                             f"{name}: the `*_entry_cond` seed is back. It is "
                             f"referenced by nothing and, for a merge block, "
                             f"false")

    def test_the_terminal_leaves_see_a_source_condition_fact(self):
        """The value-flow leaves must be able to use one.

        They close with `all_goals (first | done | sorry)`, so a path that
        reaches them with nothing about the condition falls through to a
        `sorry` — which asserts the short circuit's semantics.  `TestLean`
        below counts the admitted holes; this says WHERE they would come from.
        """
        for name, p in sorted(self.proofs.items()):
            if not p:
                continue
            text = open(p).read()
            self.assertRegex(
                text, r"-- terminal value flow.*\n.*\n?.*(hsrc_\d+|hscL_\d+)",
                f"{name}: a terminal value-flow leaf does not reference a "
                f"source-condition fact, so it has nothing to discharge the "
                f"answer with and falls through to `sorry`")

    def test_a_nested_chain_does_not_silently_prove(self):
        """The recorded gap must stay a FAILURE, not become a proof.

        A chain nested in a chain reaches the outer merge four ways, each with
        a different cset having written the register, which the two-path
        statement does not cover.  What must not happen is a `sorry`-backed
        theorem passing as a proof — that is the failure mode the recorded gap
        is recorded for."""
        import formal.arm64_proof_gen as G
        for name, (src, _why) in KNOWN_GAP.items():
            text = None
            tmp = tempfile.mkdtemp(prefix="a2-sc-nest-")
            try:
                p, err = _generate(tmp, src, name)
                if err:
                    self.assertIn("unsupported", err,
                                  f"{name}: the nested chain must fail "
                                  f"loudly, not with {err}")
                    continue
                text = open(p).read()
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            if text is None:
                continue
            self.assertNotIn(
                "hscL_0 :", text.split("Or.inl")[0] if "Or.inl" in text else text,
                f"{name}: the outer chain's left operand is itself a chain, so "
                f"its own branch is what has to be identified — see the bug "
                f"doc")
            self.assertIsNotNone(G._sc_merge_hsrc,
                                 "the per-path statement helper is gone")


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
        cls.tmp = tempfile.mkdtemp(prefix="a2-sc-lean-")
        cls.results = {}
        for name, (src, _why) in PROGRAMS.items():
            p, err = _generate(cls.tmp, src, name)
            cls.results[name] = (False, err, 0) if err else _check_proof(p)
        for stem in EXAMPLE_STEMS:
            src = os.path.join(HERE, "formal", "examples", stem + ".mojo")
            out = os.path.join(cls.tmp, stem + ".aout")
            import formal.build as fb
            p = fb.compile_formal(src, arch="arm64", output=out, prove=True,
                                  check=False)["proof_path"]
            cls.results[stem] = _check_proof(p)

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


class TestLeanModelBridge(unittest.TestCase):
    """`eval_eq_mojo` ALONE, on both architectures, for a NESTED chain.

    Separate from `TestLean` for the reason `_model_only` gives: the machine
    half of every short-circuit proof is currently over Lean's memory ceiling
    (`bugs/FORMAL_a_generated_proof_over_leans_memory_ceiling_is_rejected.md`,
    measured 2026-10-05 at 13.6 GB peak for `either`), so a `TestLean` row for
    the nested chain would be reporting the ceiling and not the construct.  The
    model bridge does not depend on any of it, so it is checked on its own and
    the failure it would report is about the AST bridge.

    This is the test the 2026-10-05 fix is measured by: before
    `eval_split_conds`, both architectures left `eval_eq_mojo` open with
    `h0 : (A ∨ B) ∨ C ⊢ ¬(¬A → ¬B → C)` on the table; after it, `rc 0`.
    """

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
        cls.tmp = tempfile.mkdtemp(prefix="a2-sc-model-")
        cls.results = {}
        for arch in ("arm64", "x86_64"):
            src, _why = KNOWN_GAP["nested_or"]
            p, err = _generate(cls.tmp, src, "nested_or_" + arch,
                               arch=arch)
            if err:
                cls.results[arch] = (False, err, 0)
                continue
            cut = os.path.join(cls.tmp, "model_" + arch + ".lean")
            with open(cut, "w") as f:
                f.write(_model_only(p))
            cls.results[arch] = _check_proof(cut)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_nested_chains_model_bridge_typechecks_on_both_architectures(self):
        for arch, (ok, detail, n) in sorted(self.results.items()):
            with self.subTest(arch=arch):
                self.assertTrue(
                    ok, f"{arch}: the AST bridge for a chain nested in a chain "
                        f"does not typecheck: {detail}")
                self.assertEqual(n, 0,
                                 f"{arch}: the model bridge admits {n} "
                                 f"`sorry`")


if __name__ == "__main__":
    unittest.main(verbosity=2)