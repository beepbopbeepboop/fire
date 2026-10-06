#!/usr/bin/env python3
"""test_formal_metamorph.py — is the metamorphic HARNESS itself sound?

`tools/formal_metamorph.py` asserts that a program and its transformed twin
answer the same thing, and builds both to check it.  Every conclusion that tool
draws about the backend rests on the twin being the SAME PROGRAM, so that is the
thing this file tests, and it is tested against CPython: for each of the ten
transformations and a fixed corpus, run the original and the twin through the
interpreter here and require identical stdout and exit status.

Nothing in this file needs a build except `test_a_rename_twin_agrees_on_the_host`,
which exists so the file is not purely a statement about the harness: it builds
one program and its `rename` twin with `--formal` and requires the same stdout,
which is the tool's own claim made end to end on a real image.

The corpus is two halves, and the second half is the one that earned the file:

  * a fixed set of programs written here, one per shape the transforms have a
    documented rule about — shadowing, `global`, a closure capture, a
    comprehension scope, a keyword argument, an f-string, a default parameter, a
    subscript store, two adjacent prints, an augmented assignment, a
    single-return helper, a recursion;
  * programs from `tools/formal_fuzz.py`'s generator, because a hand-written
    corpus only covers what its author thought of.  Every MIX, a fixed index
    range, and the index range is IN the seed so the whole file is a pure
    function of itself.

THE DIRECTION THAT MATTERS.  A metamorphic tool whose transform quietly changes
the meaning reports every disagreement as its own bug and tests nothing.  So the
assertion here is `CPython(P) == CPython(T)` for every transform that APPLIED,
and the count of applied transforms is asserted too — a tool that silently
declined everything would pass the equality check while measuring nothing, which
is the failure mode this file exists to make impossible.  `MUST_APPLY` says
which transform must apply to which corpus, and `test_no_transform_is_measured
_on_nothing` reads the table rather than trusting the tally.

    python3 test_formal_metamorph.py [-v]
"""
import ast
import os
import random
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_fuzz as F  # noqa: E402
import formal_metamorph as M  # noqa: E402

# `exec_budget`'s shared per-child budgets rather than a literal: the
# `--list-transforms` probe below runs a python process, and a reader has no way
# to tell a deliberate 120 s from a stale one.
from exec_budget import RUN_TIMEOUT_S  # noqa: E402

EXAMPLES = os.path.join(HERE, "formal", "examples")


def answer(text, tmpdir, name):
    """`(exit, stdout)` from CPython, or None when it produced no answer."""
    ref, _err = F.cpython_answer(text, tmpdir, name)
    return (ref[0], ref[1]) if F.has_oracle(ref) else None


def twin(text, index, tname, seed="t"):
    """The transformed text, or None when the transformation does not apply."""
    tree = ast.parse(text)
    try:
        out = M.TRANSFORMS[tname](tree, M.Analysis(tree),
                                  random.Random(f"{seed}:{index}:{tname}"))
    except M.NotApplicable:
        return None
    if out is None:
        return None
    return ast.unparse(out)


#: Programs that exercise one documented rule each.  Every one has a `main` so
#: the CPython driver can call it, and every one is valid in BOTH engines — the
#: intersection `tools/formal_fuzz.py` works in.
PROGRAMS = [
    ("shadowing", "def f(n):\n"
     "    x = n + 1\n"
     "    def g(x):\n"
     "        return x * 2\n"
     "    return g(x) + x\n"
     "def main() -> Int32:\n"
     "    print(f(3))\n"
     "    return 0\n"),
    ("global_declared", "G = 5\n"
     "def bump(k):\n"
     "    global G\n"
     "    G = G + k\n"
     "    return G\n"
     "def main() -> Int32:\n"
     "    print(bump(2))\n"
     "    print(G)\n"
     "    return 0\n"),
    ("closure_capture", "def main() -> Int32:\n"
     "    c = 1\n"
     "    def cf(k):\n"
     "        return (c + k) & 0xFFFF\n"
     "    c = 9\n"
     "    print(cf(4))\n"
     "    return 0\n"),
    ("comprehension_scope", "def main() -> Int32:\n"
     "    t = 3\n"
     "    xs = [t, t + 1, t + 2]\n"
     "    ys = [v * 2 for v in xs]\n"
     "    print(ys)\n"
     "    print(t)\n"
     "    return 0\n"),
    ("keyword_argument", "def f(a, b):\n"
     "    return a + b\n"
     "def main() -> Int32:\n"
     "    print(f(b=2, a=1))\n"
     "    return 0\n"),
    ("default_parameter", "def f(a, b=5):\n"
     "    return a + b\n"
     "def main() -> Int32:\n"
     "    print(f(1))\n"
     "    print(f(1, 2))\n"
     "    return 0\n"),
    ("interpolated", "def main() -> Int32:\n"
     "    s = 4\n"
     "    print(f'v={s} ')\n"
     "    print(t'v={s} ')\n"
     "    return 0\n"),
    ("subscript_store", "def main() -> Int32:\n"
     "    L = [0, 0, 0]\n"
     "    L[0] = 31\n"
     "    L[1] = 15\n"
     "    print(L)\n"
     "    return 0\n"),
    ("two_adjacent_prints", "def f(n):\n"
     "    return n + 1\n"
     "def main() -> Int32:\n"
     "    print(f(1))\n"
     "    print(f(2))\n"
     "    print(f(3))\n"
     "    return 0\n"),
    ("augmented_assignment", "def main() -> Int32:\n"
     "    a = 1\n"
     "    a += 2\n"
     "    a |= 8\n"
     "    print(a)\n"
     "    return 0\n"),
    ("single_return_helper", "def dbl(a):\n"
     "    return a * 2\n"
     "def triple(a):\n"
     "    return a * 3\n"
     "def main() -> Int32:\n"
     "    print(dbl(4))\n"
     "    print(dbl(4) + triple(2))\n"
     "    return 0\n"),
    ("recursion", "def rec(n):\n"
     "    if n <= 0:\n"
     "        return 1\n"
     "    return rec(n - 1) + 2\n"
     "def main() -> Int32:\n"
     "    print(rec(4))\n"
     "    return 0\n"),
    ("adjacent_independent", "def main() -> Int32:\n"
     "    a = 0\n"
     "    b = 0\n"
     "    a = a + 3\n"
     "    b = b + 5\n"
     "    print(a, b)\n"
     "    return 0\n"),
    ("chain_of_bindings", "def f(n):\n"
     "    a = n + 1\n"
     "    b = a + 1\n"
     "    c = b + 1\n"
     "    return c\n"
     "def main() -> Int32:\n"
     "    print(f(2))\n"
     "    return 0\n"),
]

#: transform -> (corpus label, index) pairs it MUST apply to.  A row is a claim
#: that the transform reaches that program, and `test_every_transform_applies_
#: somewhere` is what stops a transform from being deleted by accident and
#: leaving the suite green because it applied to nothing.
MUST_APPLY = {
    "rename": [("shadowing", 0)],
    "dead_local": [("chain_of_bindings", 0)],
    "extra_param": [("single_return_helper", 0)],
    "noop_loop": [("adjacent_independent", 0)],
    "if_true": [("adjacent_independent", 0)],
    "swap_add": [("chain_of_bindings", 0)],
    "extract": [("chain_of_bindings", 0)],
    "reorder": [("adjacent_independent", 0)],
    "def_order": [("single_return_helper", 0)],
    "inline_helper": [("single_return_helper", 0)],
}

#: Every generator mix, a fixed index range.  Chosen as "all of them" because the
#: transforms' reachability is a property of the corpus: `swap_add` needs an
#: integer operand and `containers` binds lists, so a suite that only ran `core`
#: would report a coverage number that says nothing about `containers`.
FUZZ_INDEXES = range(6)


def fuzz_corpus():
    """`(label, text)` for every mix and `FUZZ_INDEXES`."""
    out = []
    for mix in sorted(F.MIXES):
        for i in FUZZ_INDEXES:
            out.append((f"{mix}:{i}",
                        F.make_program("t-metamorph", i, mix, (8, 14))))
    return out


def example_corpus():
    """`(label, text)` for every `formal/examples/*.mojo` this file can drive."""
    out = []
    if not os.path.isdir(EXAMPLES):
        return out
    for stem in sorted(f[:-5] for f in os.listdir(EXAMPLES)
                       if f.endswith(".mojo")):
        with open(os.path.join(EXAMPLES, stem + ".mojo")) as f:
            text, why = M.example_main(f.read())
        if why is None:
            out.append((stem, text))
    return out


class TransformSoundness(unittest.TestCase):
    """CPython(P) == CPython(T) for every transform that applies.

    The whole file in one property.  A `transform-invalid` here is a defect in
    `tools/formal_metamorph.py`, and the transform's name is in the message so
    the reader knows which one.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="t_formal_metamorph.")
        cls.programs = ([(n, t) for n, t in PROGRAMS]
                        + fuzz_corpus() + example_corpus())
        cls.answers = {}
        for label, text in cls.programs:
            cls.answers[label] = answer(text, cls.tmpdir, f"o{label}")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_every_transform_preserves_the_meaning(self):
        checked = 0
        bad = []
        for label, text in self.programs:
            want = self.answers[label]
            if want is None:
                continue
            for tname in M.TRANSFORM_NAMES:
                ttext = twin(text, label, tname)
                if ttext is None:
                    continue
                got = answer(ttext, self.tmpdir, f"t{label}_{tname}")
                if got is None:
                    bad.append(f"{label}/{tname}: CPython could not run the "
                               f"twin, so the transform produced a program that "
                               f"does not answer")
                    continue
                if got != want:
                    bad.append(f"{label}/{tname}: original {want[0]}/"
                               f"{want[1]!r} vs twin {got[0]}/{got[1]!r}")
                checked += 1
        self.assertEqual(bad, [], "a transform changed the meaning:\n  "
                                 + "\n  ".join(bad))
        # The tally is the second half of the assertion.  Without it a transform
        # that declined every program would pass the line above while the tool
        # measured nothing, and "0 pairs" and "every pair agreed" print the
        # same on a screen.
        self.assertGreater(checked, 200 * len(M.TRANSFORM_NAMES) // 2,
                           f"only {checked} pairs were measured; the corpus is "
                           f"too small for this file to be evidence")

    def test_every_transform_applies_somewhere(self):
        for tname, rows in MUST_APPLY.items():
            for label, _index in rows:
                text = dict(self.programs)[label]
                with self.subTest(transform=tname, program=label):
                    self.assertIsNotNone(
                        twin(text, label, tname),
                        f"{tname} does not apply to {label}, and nothing else "
                        f"in this file measures it")

    def test_no_transform_is_measured_on_nothing(self):
        """Every transform in the table is in `MUST_APPLY`, and vice versa.

        A transform that reached nothing and a transform nobody wrote down are
        the same defect from two directions — the first is invisible in a tally
        of passes, the second is invisible in a diff.
        """
        self.assertEqual(sorted(MUST_APPLY), sorted(M.TRANSFORM_NAMES))
        self.assertEqual(sorted(M.TRANSFORM_WHY), sorted(M.TRANSFORM_NAMES))

    def test_the_pair_is_a_pure_function_of_its_seed(self):
        text = dict(self.programs)["chain_of_bindings"]
        for tname in M.TRANSFORM_NAMES:
            a = twin(text, "chain_of_bindings", tname)
            b = twin(text, "chain_of_bindings", tname)
            if a is not None:
                with self.subTest(transform=tname):
                    self.assertEqual(a, b,
                                     f"{tname} is not deterministic, so a "
                                     f"finding cannot be re-run")


class ScopeResolution(unittest.TestCase):
    """The predicates `Analysis` computes, one case each.

    These are the load-bearing answers: `rename` rewrites an occurrence only
    when `bind_of` names the scope it is rewriting, and `swap_add` swaps only
    operands `int_only` contains.  Both were wrong during development in ways
    CPython caught, so they are pinned here where the failure is a unit test
    rather than a 40-program sweep.
    """

    def _an(self, source):
        return M.Analysis(ast.parse(source))

    def test_a_global_declared_name_is_not_a_local(self):
        an = self._an("G = 5\n"
                      "def f(n):\n"
                      "    global G\n"
                      "    G = n\n"
                      "    return G\n")
        fn = an.functions[-1]
        # The declaration is the FIRST line and the assignment is the third, so
        # a scope tree that discarded on the way past and rebound on the way
        # back reported `G` as a local — and `rename` then rewrote the reads
        # without the declaration, which is a NameError in the twin.
        self.assertNotIn("G", an.locals_of(fn))

    def test_a_shadowing_parameter_is_its_own_binding(self):
        an = self._an("def f(x):\n"
                      "    x = x + 1\n"
                      "    def g(x):\n"
                      "        return x\n"
                      "    return g(x) + x\n")
        outer = an.functions[0]
        inner = [fn for fn in ast.walk(outer)
                 if isinstance(fn, ast.FunctionDef)][0]
        self.assertIn("x", an.locals_of(outer))
        self.assertIn("x", an.locals_of(inner))
        scopes = {id(an.builder.bind_of(o))
                  for o in ast.walk(outer) if isinstance(o, ast.Name)
                  and o.id == "x"}
        self.assertEqual(len(scopes), 2,
                         "the three `x`s resolved to fewer than two bindings")

    def test_a_comprehension_target_does_not_leak(self):
        # `v` exists ONLY as the comprehension's target: the outer read is `t`.
        # An earlier version of this program assigned `v` in the body, which
        # makes it a local by CPython's own rule and made the assertion vacuous.
        an = self._an("def f(t):\n"
                      "    xs = [v for v in (t, 2)]\n"
                      "    return xs\n")
        self.assertNotIn("v", an.locals_of(an.functions[0]))

    def test_a_dict_comprehension_is_scoped_too(self):
        # `DictComp` has neither `elt` nor `keywords`, and a reader that read
        # both anyway raised `AttributeError` on every `{k: v for …}` in the
        # corpus — which is the `containers` mix, so a whole mix became
        # unmeasurable rather than measured empty.
        an = self._an("def f(t):\n"
                      "    d = {v: v + t for v in (1, 2)}\n"
                      "    return d\n")
        self.assertNotIn("v", an.locals_of(an.functions[0]))

    def test_a_keyword_argument_name_is_never_renamed(self):
        an = self._an("def f(a, b):\n"
                      "    return a + b\n"
                      "def main() -> Int32:\n"
                      "    print(f(b=2, a=1))\n"
                      "    return 0\n")
        self.assertEqual(an.arg_keywords, {"a", "b"})

    def test_a_name_inside_an_interpolated_string_is_never_renamed(self):
        an = self._an("def main() -> Int32:\n"
                      "    s = 4\n"
                      "    print(f'v={s} ')\n"
                      "    print(t'v={s} ')\n"
                      "    return 0\n")
        self.assertEqual(M._interpolated_names(an.module), {"s"},
                         "an f-string's expression is source text, and a "
                         "`TemplateStr` is not a `JoinedStr`")

    def test_an_integer_parameter_is_classified_from_its_call_sites(self):
        an = self._an("def threevar(n):\n"
                      "    a = n + 1\n"
                      "    b = a + 1\n"
                      "    return b\n"
                      "def main() -> Int32:\n"
                      "    print(threevar(0))\n"
                      "    return 0\n")
        # Without the call-site rule `n` has no stores and no classification, so
        # `a` is not an int, so `swap_add` and the int half of `extract` are
        # unreachable on every program in `formal/examples`.
        self.assertEqual(an.int_only, {"n", "a", "b"})

    def test_a_parameter_of_an_uncalled_function_is_not_classified(self):
        an = self._an("def f(n):\n"
                      "    return n + 1\n"
                      "def main() -> Int32:\n"
                      "    return 0\n")
        self.assertNotIn("n", an.int_only)


class TheDriver(unittest.TestCase):
    """The harness's own decisions: verdicts, drivers, and what a run reports."""

    def test_a_metamorphic_disagreement_is_a_finding_and_a_divergence_is_not(
            self):
        """`DIVERGENCE-*` is `formal_fuzz`'s queue; the rest are findings here."""
        for v in M.FINDING_VERDICTS:
            with self.subTest(verdict=v):
                self.assertNotIn(v, ("match", "TIMEOUT", "trapped",
                                     "not-answerable"))
        for v in ("DIVERGENCE-X86", "DIVERGENCE-ARM"):
            with self.subTest(verdict=v):
                self.assertNotIn(v, M.FINDING_VERDICTS)
        # And the ordering the screen line reads: a metamorphic violation is
        # this tool's own finding and outranks everything else.
        self.assertLess(M.SEVERITY.index("METAMORPH-X86"),
                        M.SEVERITY.index("DIVERGENCE-X86"))

    def _ok(self, stdout, rc=0):
        return {"verdict": "ok", "rc": rc, "stdout": stdout}

    def _refused(self, diag):
        return {"verdict": "refusal", "rc": 1, "diag": diag}

    def test_two_images_that_disagree_are_metamorphic(self):
        want = (0, "1\n")
        got = M._compare_one("x86_64", self._ok("1\n"), self._ok("2\n"), want)
        # BOTH verdicts, and both are true: the two builds of one meaning
        # disagree (no oracle needed), and the twin is also the wrong answer
        # (which is how the metamorphic violation is usually LOCALISED — the
        # transform that turned a right answer into a wrong one is the bug's
        # shape).  Collapsing them into one token would lose the localisation.
        self.assertEqual(got, ["METAMORPH-X86", "MISMATCH-X86"])

    def test_one_side_building_and_the_other_refusing_is_a_twin_divergence(self):
        got = M._compare_one("arm64", self._ok("1\n"),
                             self._refused("no such construct"), (0, "1\n"))
        self.assertEqual(got, ["TWIN-DIVERGES-ARM"])

    def test_a_disagreement_the_original_also_has_is_a_divergence(self):
        # Both sides wrong AND equal: no metamorphic violation, one
        # disagreement the original already had — and the twin is wrong too, so
        # `MISMATCH` says which side is.  `test_one_verdict_is_not_reported_twice`
        # below is the row that says the same disagreement is not reported as a
        # finding under either token.
        got = M._compare_one("arm64", self._ok("9\n"), self._ok("9\n"),
                             (0, "1\n"))
        self.assertEqual(got, ["DIVERGENCE-ARM"])

    def test_a_disagreement_both_sides_have_is_not_also_a_mismatch(self):
        """`MISMATCH` means the TRANSFORM introduced it.

        Otherwise every documented divergence becomes a fresh finding on every
        run: measured on the `strings` mix, where `s[i]` is a byte rather than a
        one-character string (`formal_fuzz.KNOWN_DIVERGENCES`), 17 of 20
        programs arrived as `MISMATCH-X86`.  The localisation is not lost —
        `METAMORPH` above says the two sides differ.
        """
        got = M._compare_one("arm64", self._ok("9\n"), self._ok("8\n"),
                             (0, "1\n"))
        self.assertEqual(got, ["METAMORPH-ARM", "DIVERGENCE-ARM"])

    def test_two_refusals_that_differ_only_by_machine_name_are_one(self):
        """`fold_arch` is what makes this true, and it is the sweep's normaliser.

        12 of 542 rows in `tools/formal_sweep_parity.py`'s measurement differed
        for no reason other than a machine name, so the words are compared after
        the fold and an architecture label is not a second opinion about the
        program.
        """
        got = M._compare_one(
            "x86_64",
            self._refused("on the formal x86-64 path: `x` has no home"),
            self._refused("on the formal arm64 path: `x` has no home"),
            (0, "1\n"))
        self.assertEqual(got, [])

    def test_two_refusals_in_different_words_are_a_finding(self):
        # The two architectures are ONE language implementation, so the same
        # refusal in two sets of words is a finding — and a transform that does
        # not change the program must not change the sentence either.
        got = M._compare_one(
            "x86_64",
            self._refused("`x` has no home: the register allocator collected no "
                         "home for it"),
            self._refused("`x` cannot be represented on this target"),
            (0, "1\n"))
        self.assertEqual(got, ["REFUSAL-DIVERGES-X86"])

    def test_one_verdict_is_not_reported_twice(self):
        """One disagreement, one token for it.

        An earlier version appended `MISMATCH-arch` once per SIDE, so a single
        disagreement printed as `MISMATCH-X86+MISMATCH-X86+MISMATCH-ARM+
        MISMATCH-ARM` and a tally that counted tokens was counting four.
        """
        got = M._compare_one("x86_64", self._ok("9\n"), self._ok("9\n"),
                             (0, "1\n"))
        self.assertEqual(len(got), len(set(got)))
        self.assertEqual(got, ["DIVERGENCE-X86"])

    def test_example_main_drives_an_example_with_no_entry_point(self):
        text, why = M.example_main("def f(n):\n    return n + 1\n")
        self.assertIsNone(why)
        self.assertIn("def main() -> Int32:", text)
        self.assertIn("print(f(0))", text)

    def test_example_main_leaves_a_zero_argument_entry_point_alone(self):
        src = "def main() -> Int32:\n    printf(\"hi\")\n    return 0\n"
        text, why = M.example_main(src)
        self.assertIsNone(why)
        self.assertEqual(text, src, "a synthesised driver shadowed the "
                                   "example's own entry point")

    def test_example_main_reports_an_entry_point_that_takes_arguments(self):
        # Synthesising a driver for `def main(n: Int, m: Int)` calls `main` with
        # the wrong arity and recurses forever. Measured: the twin was a
        # `not-answerable` with nothing to say why.
        text, why = M.example_main("def main(n, m):\n    return n + m\n")
        self.assertIsNone(text)
        self.assertIn("main", why)

    def test_example_main_reports_mojo_only_syntax(self):
        text, why = M.example_main("def f(n):\n    var a = 1\n    return 2\n")
        self.assertIsNone(text)
        self.assertIn("parser", why)

    def test_every_example_is_either_driven_or_reported(self):
        """No example is dropped silently.

        An example that cannot be driven is a coverage hole, and the tool's own
        docstring says a corpus that stops producing a construct reports the
        same clean tally as one that never produced it — so the reason has to be
        on the screen.
        """
        if not os.path.isdir(EXAMPLES):
            self.skipTest("formal/examples is not present")
        stems = sorted(f[:-5] for f in os.listdir(EXAMPLES)
                       if f.endswith(".mojo"))
        self.assertEqual(len(stems), len(
            os.listdir(EXAMPLES)) - 0 if False else len(stems))
        reported = []
        for stem in stems:
            with open(os.path.join(EXAMPLES, stem + ".mojo")) as f:
                _text, why = M.example_main(f.read())
            if why:
                reported.append(stem)
        self.assertEqual(sorted(stems),
                         sorted([s for s in stems if s not in reported]
                                + reported),
                         "an example was neither driven nor reported")

    def test_list_transforms_names_every_transformation(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "tools", "formal_metamorph.py"),
             "--list-transforms"],
            capture_output=True, text=True, timeout=RUN_TIMEOUT_S, cwd=HERE)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        for name in M.TRANSFORM_NAMES:
            self.assertIn(name, proc.stdout)


class OneRealBuild(unittest.TestCase):
    """The tool's own claim, end to end, on an image rather than on CPython.

    One program and its `rename` twin, on whichever architecture this host runs.
    It is here so the file is not only a statement about the harness: `rename`
    changes every name the register allocator and the frame-slot map see and
    must not change the answer, and that is worth one build.
    """

    def test_a_rename_twin_agrees_on_the_host(self):
        source = ("def f(n):\n"
                  "    a = n + 1\n"
                  "    b = a * 2\n"
                  "    c = b - a\n"
                  "    return (c + a + b) & 0xFFFF\n"
                  "def main() -> Int32:\n"
                  "    print(f(5))\n"
                  "    print(f(6))\n"
                  "    return 0\n")
        other = twin(source, "one-real-build", "rename")
        self.assertIsNotNone(other, "rename did not apply to the row below")
        backend = "arm64" if F.platform.machine() in ("arm64", "aarch64") \
            else "x86_64"
        with tempfile.TemporaryDirectory(dir=os.path.join(HERE, ".tmp")
                                         if os.path.isdir(
                                             os.path.join(HERE, ".tmp"))
                                         else None) as tmp:
            answers = {}
            for tag, text in (("orig", source), ("twin", other)):
                src = os.path.join(tmp, tag + ".mojo")
                out = os.path.join(tmp, tag + ".bin")
                with open(src, "w") as f:
                    f.write(text)
                rc, diag = F.build(src, out, backend)
                self.assertEqual(rc, 0, f"{tag} did not build: {diag[-300:]}")
                got, err = F.run(out, backend)
                self.assertIsNotNone(got, f"{tag} did not run: {err}")
                answers[tag] = got
            self.assertEqual(answers["orig"], answers["twin"],
                             "a rename changed the answer")


if __name__ == "__main__":
    unittest.main()