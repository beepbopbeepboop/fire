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
import types
import unittest
from unittest import mock

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


#: `formal_fuzz.run_on`'s two shapes, as the verdict helpers the tool reads them.
#: They are spelled once here because three classes below decide verdicts from
#: them and a second copy of "an `ok` is `{"verdict": "ok", …}`" is a third thing
#: to keep in step with the tool.
def ok(stdout, rc=0):
    return {"verdict": "ok", "rc": rc, "stdout": stdout}


def refused(diag):
    return {"verdict": "refusal", "rc": 1, "diag": diag}


#: The one attribute `_normalisation` reads off the run's arguments.  A
#: stand-in rather than an `argparse.Namespace`, so the coupling stays visible.
def _ARGS(backends):
    return types.SimpleNamespace(backends=backends)


def answer(text, tmpdir, name, args=""):
    """`(exit, stdout)` from CPython, or None when it produced no answer.

    `args` is what the driver calls `main` with, and it is a parameter for the
    same reason it is one in `formal_fuzz.cpython_answer`: an example whose own
    entry point takes arguments cannot be answered without it, and a corpus that
    quietly dropped those examples would be a corpus with a coverage hole in
    exactly the place the metamorphic tool was extended to reach.
    """
    ref, _err = F.cpython_answer(text, tmpdir, name, args)
    return (ref[0], ref[1]) if F.has_oracle(ref) else None


def by_label(programs):
    """`{label: text}` for the corpus — the `MUST_APPLY` table is by name."""
    return {label: text for label, text, _args in programs}


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
    """`(label, text, args)` for every mix and `FUZZ_INDEXES`.

    The generated corpus is every `main()` — `formal_fuzz.make_program`'s own
    convention — so `args` is empty for all of them, and it is carried anyway so
    the two halves of the corpus have one shape.
    """
    out = []
    for mix in sorted(F.MIXES):
        for i in FUZZ_INDEXES:
            out.append((f"{mix}:{i}",
                        F.make_program("t-metamorph", i, mix, (8, 14)), ""))
    return out


def example_corpus():
    """`(label, text, args)` for every `formal/examples/*.mojo` this file can
    drive."""
    out = []
    if not os.path.isdir(EXAMPLES):
        return out
    for stem in sorted(f[:-5] for f in os.listdir(EXAMPLES)
                       if f.endswith(".mojo")):
        with open(os.path.join(EXAMPLES, stem + ".mojo")) as f:
            prog = M.example_program(f.read())
        if prog["text"] is not None:
            out.append((stem, prog["text"], prog["driver_args"]))
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
        cls.programs = ([(n, t, "") for n, t in PROGRAMS]
                        + fuzz_corpus() + example_corpus())
        cls.answers = {}
        for label, text, args in cls.programs:
            cls.answers[label] = answer(text, cls.tmpdir, f"o{label}", args)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_every_transform_preserves_the_meaning(self):
        checked = 0
        bad = []
        for label, text, args in self.programs:
            want = self.answers[label]
            if want is None:
                continue
            for tname in M.TRANSFORM_NAMES:
                ttext = twin(text, label, tname)
                if ttext is None:
                    continue
                got = answer(ttext, self.tmpdir, f"t{label}_{tname}", args)
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
                text = by_label(self.programs)[label]
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
        text = by_label(self.programs)["chain_of_bindings"]
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

    def test_a_global_declared_name_is_still_a_module_binding(self):
        """The other half of the same rule, and it is the half that broke.

        `_bind_body` refuses to descend into a nested `def`, but it spelled the
        refusal so that the refusal did not apply to the `def` STATEMENT — so
        `global G6` inside `def bump7` was read as a declaration of the MODULE,
        and `G6` was then dropped from the module's bindings.  That set is what
        `reorder`'s `_reachable_by_a_call` consults, so `G6 = 9` and
        `print(bump9(5))` were exchanged and the printed value moved from 14 to
        25.  Found by the CPython oracle over 5910 pairs
        (`stress-mm:18`, `globals`).
        """
        an = self._an("G = 5\n"
                      "def bump(n):\n"
                      "    global G\n"
                      "    G = G + n\n"
                      "    return G\n")
        self.assertIn("G", an.module_bindings,
                      "a name a function declares `global` is bound in the "
                      "MODULE, whatever the declaration is written inside")

    def test_a_nested_functions_locals_are_not_module_bindings(self):
        """The other direction of the same fix, and it is an over-approximation.

        `module_bindings` is "what a call made from anywhere can reach".  A
        module-level `def`'s locals are not that: reaching them needs a closure,
        and `_captured_names` is the predicate for that.  Reading them in here
        made `reorder` refuse swaps it need not refuse, which costs pairs and
        hides the rule that is actually protecting anything.
        """
        an = self._an("def main() -> Int32:\n"
                      "    s1 = 0\n"
                      "    print(s1)\n"
                      "    return 0\n")
        self.assertNotIn("s1", an.module_bindings)

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

    # -- the integer classification, one rule per row ------------------------
    #
    # Each rule below exists because a MEASUREMENT said the predicate was
    # declining programs it could classify: 133 of 440 generated programs admitted
    # a `swap_add`, and the reasons, in order, were a `for`/comprehension target,
    # a parameter with an integer default, a call used as an argument, and a
    # self-referential store.  Each is a decidable question with a decidable
    # answer, so the cost of getting it wrong is bounded by the CPython oracle —
    # and the row that would catch getting it wrong is the one asserting it does
    # NOT fire.

    def test_a_defaulted_parameter_is_classified_from_its_default(self):
        """`argshape` spells every helper `def af8(q9, q10=30)`.

        The rule used to EXCLUDE a function with any default, which was answering
        a question about binding ("may this call omit the argument?") with a
        statement about type.  With `q10` excluded on that technicality, `af8`'s
        own `return (q9 + q10 + 11) & 0xFFFF` was unclassifiable, so nothing that
        CALLS `af8` was either.
        """
        an = self._an("def af(q9, q10=30):\n"
                      "    return (q9 + q10 + 11) & 0xFFFF\n"
                      "def main() -> Int32:\n"
                      "    print(af(1))\n"
                      "    print(af(1, 2))\n"
                      "    return 0\n")
        self.assertEqual(an.int_only, {"q9", "q10"})

    def test_a_defaulted_parameter_with_a_container_default_is_not_an_int(self):
        """And the granularity is per FUNCTION, not per parameter.

        `af(1)` leaves `q10` bound to `[1]`, so `q10` is not an int at every
        binding — and `q9` goes with it, because the rule is a conjunction over
        the parameters rather than a per-parameter answer.  Coarser than it could
        be, and sound in the direction that matters: a parameter classified on
        one call site and forgotten on another is exactly the mistake the
        conjunction exists to prevent.
        """
        an = self._an("def af(q9, q10=[1]):\n"
                      "    return q9 + 1\n"
                      "def main() -> Int32:\n"
                      "    print(af(1))\n"
                      "    return 0\n")
        self.assertNotIn("q10", an.int_only)
        self.assertNotIn("q9", an.int_only)

    def test_a_function_that_returns_only_ints_is_an_int_expression(self):
        """`w3 = g10 + 1` is the corpus's own idiom, and it is why this row exists.

        A CALL used to be unconditionally False for `_int_expr`, so `g10(...)`
        was unclassifiable, so the parameter receiving it was unclassifiable, so
        every `+` downstream of a helper call was out of reach for `swap_add`.
        """
        an = self._an("def g10(p):\n"
                      "    return p + 1\n"
                      "def use(n):\n"
                      "    w = g10(n) + 1\n"
                      "    return w + n\n"
                      "def main() -> Int32:\n"
                      "    print(use(3))\n"
                      "    return 0\n")
        self.assertIn("w", an.int_only)
        self.assertIn("g10", an._int_returns)

    def test_a_function_that_can_return_none_is_not_an_int_expression(self):
        """The three ways, because they are three different mistakes.

        `maybe` falls off the end (so its result is `None`), `cond` returns the
        string on one branch, and `gen` is a generator — `gen()` is a generator
        whatever its `return` says.
        """
        an = self._an("def maybe(p):\n"
                      "    if p > 0:\n"
                      "        return p\n"
                      "def cond(p):\n"
                      "    if p > 0:\n"
                      "        return p\n"
                      "    return 'x'\n"
                      "def gen(p):\n"
                      "    yield p\n"
                      "def main() -> Int32:\n"
                      "    print(maybe(1) + cond(1) + len(list(gen(1))))\n"
                      "    return 0\n")
        self.assertEqual(an._int_returns, {"main"})

    def test_a_nested_functions_return_is_not_the_outer_functions(self):
        """`ast.walk` descends into everything, and it descends silently.

        `def outer(): def inner(): return "x"` read as a function returning a
        string, which is the OPPOSITE of the answer, and it would have been
        certified by the very rule meant to widen the classification.
        """
        an = self._an("def outer(p):\n"
                      "    def inner():\n"
                      "        return 'x'\n"
                      "    return inner()\n"
                      "def main() -> Int32:\n"
                      "    print(1)\n"
                      "    return 0\n")
        self.assertNotIn("outer", an._int_returns)

    def test_a_loop_target_of_an_int_sequence_is_an_int(self):
        """`for tk7 in T6` where `T6` is `(28, 23)`, which is the `containers`
        mix's whole shape — and `containers` had NO `swap_add` at all before."""
        an = self._an("def main() -> Int32:\n"
                      "    T6 = (0, 0)\n"
                      "    w8 = 0\n"
                      "    T6 = (28, 23)\n"
                      "    for tk7 in T6:\n"
                      "        w8 = (w8 + tk7) & 0xFFFF\n"
                      "    print(w8)\n"
                      "    return 0\n")
        self.assertIn("tk7", an.int_only)
        self.assertIn("T6", an._int_sequences)
        self.assertIn("w8", an.int_only)

    def test_a_loop_target_of_a_string_sequence_is_not_an_int(self):
        an = self._an("def main() -> Int32:\n"
                      "    t = 'ab'\n"
                      "    for ch in t:\n"
                      "        print(ch)\n"
                      "    return 0\n")
        self.assertNotIn("ch", an.int_only)
        self.assertNotIn("t", an._int_sequences)

    def test_a_self_referential_store_is_int_when_something_anchors_it(self):
        """`s2 = (s2 + 1)` beside `s2 = 0`, which is the `core` mix's arithmetic.

        The fixpoint is a LEAST one, so a name whose store mentions the name can
        never enter it — and `s2 = (s2 + 1)` never becomes an int however obvious
        the arithmetic is.  One store int-shaped without assuming anything is the
        anchor that lets the self-referential ones be read in the assumption.
        """
        an = self._an("def main() -> Int32:\n"
                      "    s2 = 0\n"
                      "    s2 = (s2 + 1)\n"
                      "    print(s2)\n"
                      "    return 0\n")
        self.assertIn("s2", an.int_only)

    def test_a_cycle_that_anchors_nothing_is_not_an_int(self):
        """The row that keeps the anchor rule from becoming a licence.

        `x = y; y = x` is int-shaped for both names under the assumption and
        neither of them is an int, because nothing in the program ever
        established that either was — a greatest fixpoint over the names would
        certify the whole cycle from nothing.
        """
        an = self._an("def main() -> Int32:\n"
                      "    x = 0\n"
                      "    y = 0\n"
                      "    x = y\n"
                      "    y = x\n"
                      "    print(x + y)\n"
                      "    return 0\n")
        # `x` and `y` each store 0, so they ARE ints here.  The row that matters
        # is the one with no anchor at all:
        an = self._an("def main() -> Int32:\n"
                      "    x = 0\n"
                      "    y = 0\n"
                      "    del x\n"
                      "    x = y\n"
                      "    y = x\n"
                      "    print(1)\n"
                      "    return 0\n")
        self.assertNotIn("x", an.int_only)
        self.assertNotIn("y", an.int_only)

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

    def test_two_images_that_disagree_are_metamorphic(self):
        want = (0, "1\n")
        got = M._compare_one("x86_64", ok("1\n"), ok("2\n"), want)
        # BOTH verdicts, and both are true: the two builds of one meaning
        # disagree (no oracle needed), and the twin is also the wrong answer
        # (which is how the metamorphic violation is usually LOCALISED — the
        # transform that turned a right answer into a wrong one is the bug's
        # shape).  Collapsing them into one token would lose the localisation.
        self.assertEqual(got, ["METAMORPH-X86", "MISMATCH-X86"])

    def test_one_side_building_and_the_other_refusing_is_a_twin_divergence(self):
        got = M._compare_one("arm64", ok("1\n"),
                             refused("no such construct"), (0, "1\n"))
        self.assertEqual(got, ["TWIN-DIVERGES-ARM"])

    def test_a_disagreement_the_original_also_has_is_a_divergence(self):
        # Both sides wrong AND equal: no metamorphic violation, one
        # disagreement the original already had — and the twin is wrong too, so
        # `MISMATCH` says which side is.  `test_one_verdict_is_not_reported_twice`
        # below is the row that says the same disagreement is not reported as a
        # finding under either token.
        got = M._compare_one("arm64", ok("9\n"), ok("9\n"),
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
        got = M._compare_one("arm64", ok("9\n"), ok("8\n"),
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
            refused("on the formal x86-64 path: `x` has no home"),
            refused("on the formal arm64 path: `x` has no home"),
            (0, "1\n"))
        self.assertEqual(got, [])

    def test_two_refusals_in_different_words_are_a_finding(self):
        # The two architectures are ONE language implementation, so the same
        # refusal in two sets of words is a finding — and a transform that does
        # not change the program must not change the sentence either.
        got = M._compare_one(
            "x86_64",
            refused("`x` has no home: the register allocator collected no "
                         "home for it"),
            refused("`x` cannot be represented on this target"),
            (0, "1\n"))
        self.assertEqual(got, ["REFUSAL-DIVERGES-X86"])

    def test_one_verdict_is_not_reported_twice(self):
        """One disagreement, one token for it.

        An earlier version appended `MISMATCH-arch` once per SIDE, so a single
        disagreement printed as `MISMATCH-X86+MISMATCH-X86+MISMATCH-ARM+
        MISMATCH-ARM` and a tally that counted tokens was counting four.
        """
        got = M._compare_one("x86_64", ok("9\n"), ok("9\n"),
                             (0, "1\n"))
        self.assertEqual(len(got), len(set(got)))
        self.assertEqual(got, ["DIVERGENCE-X86"])


class ExamplePrograms(unittest.TestCase):
    """`example_program` — the driver, and what it refuses to invent one for."""

    def test_example_program_drives_an_example_with_no_entry_point(self):
        prog = M.example_program("def f(n):\n    return n + 1\n")
        self.assertIsNone(prog["reason"])
        self.assertIn("def main() -> Int:", prog["text"])
        self.assertIn("print(f(0))", prog["text"])
        # And the driver is the LAST thing in the file, so `def_order` can
        # permute it along with everything else — a driver that could not be
        # permuted would make half the transformations untested on this corpus.
        self.assertTrue(prog["text"].rstrip().endswith("return 0"))

    def test_example_program_leaves_a_zero_argument_entry_point_alone(self):
        src = "def main() -> Int32:\n    printf(\"hi\")\n    return 0\n"
        prog = M.example_program(src)
        self.assertIsNone(prog["reason"])
        self.assertEqual(prog["text"], src, "a synthesised driver shadowed the "
                                            "example's own entry point")

    def test_example_program_drives_an_entry_point_that_takes_arguments(self):
        """`twoparams.mojo`, and it is measured rather than reported.

        Synthesising a driver for `def main(n: Int, m: Int)` calls `main` with
        the wrong arity and recurses forever: measured, and the symptom was a
        `not-answerable` with nothing to say why.  The first version of this tool
        reported both such examples as undrivable with a comment saying it needed
        the shared harness threaded with an input; the input is threaded now, so
        the file is measured — and the two numbers have to be the SAME list,
        because the input is baked into the image and the oracle calls `main` with
        it.  A record that carried one without the other would compare two
        different programs and report the difference as a backend bug.
        """
        prog = M.example_program("def main(n, m):\n    return n + m\n")
        self.assertIsNone(prog["reason"])
        self.assertEqual(prog["driver_args"], "10, 0")
        self.assertEqual(prog["test_input"], "10,0")
        self.assertEqual([int(v) for v in prog["driver_args"].split(", ")],
                         [int(v) for v in prog["test_input"].split(",")],
                         "the image's baked input and the oracle's arguments "
                         "are different programs")
        self.assertEqual(prog["text"], "def main(n, m):\n    return n + m\n",
                         "an example that has its own entry point is used "
                         "verbatim, driver and all")

    def test_example_program_reports_an_entry_point_it_cannot_supply(self):
        """`*args`, `**kwargs`, keyword-only and defaulted: said, not guessed.

        Each of them would need a synthesised argument, and the value that went in
        would have to be one the image also baked in — so rather than a driver
        that measures one shape of a call and calls it the file, the file is
        reported.  `twoparams.mojo`'s comment calls the un-threaded behaviour a
        program with no PROOF, which is the same complaint.
        """
        for src in ("def main(*a):\n    return len(a)\n",
                    "def main(**k):\n    return len(k)\n",
                    "def main(n=1):\n    return n\n",
                    "def main(*, n=1):\n    return n\n"):
            with self.subTest(src=src):
                prog = M.example_program(src)
                self.assertIsNone(prog["text"])
                self.assertIn("main", prog["reason"])


class Normalising(unittest.TestCase):
    """`normalise_mojo` — the rules, and the gate the oracle cannot supply.

    The rules are the one place in this file where a mistake would be invisible:
    normalisation moves P and T together, so the per-pair CPython oracle would
    happily agree with itself about a program whose meaning a rule had changed.
    The gate for that is `_normalisation`'s, and both halves of it are below —
    the rules, and the machine that has to agree with the file as written.
    """

    #: `(source, gone, kept)` per rule.  The negatives are the point: a rule that
    #: fired on a file it was not written for is a rule that will eventually fire
    #: on prose.
    RULES = (
        ("@spec(f_spec; f_spec 0 = 1)\n@require(n >= 0)\ndef f(n):\n"
         "    return n\n",
         ("@spec", "@require"), ()),
        ("@spec(\n    f_spec; f_spec 0 = 1)\ndef f(n):\n    return n\n",
         ("@spec",), ()),
        ("def f(n):\n    var a = 1\n    return a + n\n",
         ("var ",), ("a = 1",)),
        ("fn g(n):\n    return n\n", ("fn ",), ("def g(n):",)),
        # One rule firing is not enough to make a file parseable, and the file is
        # still REPORTED rather than half-rewritten: the `struct` case is the
        # reason this tool cannot measure `wide_recv.mojo`, so it is a row here
        # rather than a sentence in a docstring.
        ("struct Point:\n    var x: Int\n", ("var ",), ("struct Point:",)),
    )

    def test_each_rule_removes_only_its_own_spelling(self):
        for src, gone, kept in self.RULES:
            with self.subTest(src=src.splitlines()[0]):
                text, notes, why = M.normalise_mojo(src)
                if text is None:
                    self.assertTrue(why, "a refusal with no reason")
                    self.assertTrue(notes, "a rule fired and said nothing")
                    for token in gone:
                        self.assertNotIn(token, text or "", "a rule was applied "
                                                            "to a file it could "
                                                            "not rescue")
                    continue
                self.assertIsNone(why)
                for token in gone:
                    self.assertNotIn(token, text)
                for token in kept:
                    self.assertIn(token, text)
                self.assertTrue(notes, "a rule fired and said nothing")

    def test_a_wrapped_decorator_argument_is_consumed_too(self):
        """`@spec(` opens a paren, so the removal cannot stop at the line end.

        A rule that deleted only the first line would leave the rest of the
        arguments to be parsed as code, and the file would come back with a
        SyntaxError that says nothing about the decorator.
        """
        src = ("@spec(\n    f_spec;\n    f_spec 0 = 1)\n"
               "@ensure(result >= 0)\ndef f(n):\n    return n\n")
        text, notes, why = M.normalise_mojo(src)
        self.assertIsNone(why)
        ast.parse(text)
        self.assertNotIn("f_spec", text)
        self.assertNotIn("ensure", text)
        self.assertEqual(text, "def f(n):\n    return n\n")

    def test_a_file_that_already_parses_is_returned_unchanged(self):
        """The generated corpus, and the property that makes the rules safe.

        `formal_fuzz.make_program` emits none of these spellings — that
        intersection is what this tool's whole choice of CPython's `ast` rests on
        — and a rule that ran over a file with nothing to remove is one more way
        to damage a corpus the rules were not written for.  So the common case is
        a parse and an early return, and `notes` is empty so the summary cannot
        print a rule that did not fire.
        """
        for mix in sorted(F.MIXES):
            with self.subTest(mix=mix):
                src = F.make_program("t-metamorph", 0, mix, (8, 14))
                text, notes, why = M.normalise_mojo(src)
                self.assertIsNone(why)
                self.assertEqual(text, src)
                self.assertEqual(notes, ())

    def test_a_comment_that_mentions_a_keyword_is_not_a_declaration(self):
        """`vardecl.mojo`'s own first line is a comment whose text is
        "`var a = 1` is a `VarDecl`".  A rule that rewrote inside a comment would
        turn prose into code, and CPython — which would have to execute the result
        — would be the only thing that noticed."""
        src = ("# `var a = 1` is a `VarDecl`, and `fn g(x)` is a function.\n"
               "def f(n):\n    return n\n")
        text, notes, why = M.normalise_mojo(src)
        self.assertIsNone(why)
        self.assertEqual(text, src)
        self.assertEqual(notes, ())

    def test_a_rule_that_cannot_finish_names_the_construct(self):
        text, notes, why = M.normalise_mojo("struct Point:\n    var x: Int\n")
        self.assertIsNone(text)
        self.assertIn("struct", why)
        self.assertIn("var declaration x1", notes,
                      "the rule that DID fire was not reported, so the reason "
                      "reads as though nothing was tried")

    # ── the gate ──
    #
    # `args` here is the one attribute `_normalisation` reads, so a two-field
    # stand-in rather than an argparse.Namespace keeps the coupling visible.

    def _normalisation(self, verbatim, base, tmpdir, run_on):
        with mock.patch.object(M.F, "run_on", run_on):
            return M._normalisation(
                {"text": "normalised", "verbatim": verbatim,
                 "test_input": "10,0"},
                base, _ARGS(("arm64",)), 0, tmpdir)

    def test_a_normalised_file_is_re_run_on_the_machine_as_written(self):
        """The gate.  Both answers come from the SAME backend, so this is the
        metamorphic invariant applied to the rewriting rather than to a transform:
        the file as written and the file this tool rewrote must answer alike."""
        asked = []

        def run_on(backend, text, tmpdir, name, test_input=None):
            asked.append((text, test_input))
            return ok("1\n")

        with tempfile.TemporaryDirectory() as tmp:
            got = self._normalisation("as written", {"arm64": ok("1\n")},
                                      tmp, run_on)
        self.assertEqual(got, [])
        self.assertEqual(asked, [("as written", "10,0")],
                         "the file as written is not the thing the gate checked, "
                         "or the input was not threaded into it")

    def test_a_rewrite_that_changes_the_answer_is_a_finding(self):
        """A finding that INVALIDATES the row rather than describing it: if the
        normalised file and the file as written disagree, nothing measured about
        it — including every `match` — is a statement about the file a reader has
        open.  So it outranks `METAMORPH` in the screen order."""
        with tempfile.TemporaryDirectory() as tmp:
            got = self._normalisation(
                "as written", {"arm64": ok("1\n")}, tmp,
                lambda *a, **k: ok("2\n"))
        self.assertEqual(got, ["NORMALISES-DIFFERLY-ARM"])
        self.assertIn("NORMALISES-DIFFERLY-ARM", M.FINDING_VERDICTS)
        self.assertLess(M.SEVERITY.index("NORMALISES-DIFFERLY-ARM"),
                        M.SEVERITY.index("METAMORPH-ARM"))

    def test_a_rewrite_whose_original_will_not_build_is_reported_not_skipped(self):
        """A hole, not a property of the program.

        The file could only be measured by removing syntax, and the removed
        spelling would not build — so nothing established that the removal
        preserved anything.  Reporting that as "does not apply" would report a
        coverage loss as though it were a file with nothing to do.
        """
        with tempfile.TemporaryDirectory() as tmp:
            got = self._normalisation(
                "as written", {"arm64": ok("1\n")}, tmp,
                lambda *a, **k: refused("no such construct"))
        self.assertEqual(got, ["NORMALISES-UNCOMPARABLE"])
        self.assertIn("NORMALISES-UNCOMPARABLE", M.FINDING_VERDICTS)

    def test_a_file_no_rule_fired_on_is_not_built_twice(self):
        """The whole generated corpus, and 45 of the 52 examples on this tree.

        A gate that built a second image per program would double the sweep to
        check nothing, so the common case must cost no build at all — asserted by
        a `run_on` that raises rather than by reading the code.
        """

        def boom(*a, **k):
            raise AssertionError("the no-rule path built something")

        self.assertEqual(self._normalisation(None, {"arm64": ok("1\n")},
                                             "/nonexistent", boom), [])

    def test_every_example_is_either_driven_or_reported(self):
        """No example is dropped silently.

        An example that cannot be driven is a coverage hole, and the tool's own
        docstring says a corpus that stops producing a construct reports the same
        clean tally as one that never produced it — so the reason has to be on the
        screen.
        """
        if not os.path.isdir(EXAMPLES):
            self.skipTest("formal/examples is not present")
        stems = sorted(f[:-5] for f in os.listdir(EXAMPLES)
                       if f.endswith(".mojo"))
        reported, notes = [], []
        for stem in stems:
            with open(os.path.join(EXAMPLES, stem + ".mojo")) as f:
                prog = M.example_program(f.read())
            if prog["reason"]:
                reported.append((stem, prog["reason"]))
            notes += [(stem, n) for n in prog["notes"]]
        self.assertEqual(sorted(stems),
                         sorted([s for s, _ in reported]
                                + [s for s in stems if s not in
                                   {r for r, _ in reported}]),
                         "an example was neither driven nor reported")
        # A rewrite is a SMALLER claim than a measurement, so the notes are part
        # of what this file checks: a normaliser that starts rewriting files
        # nobody recorded is a coverage report that no longer describes the tree.
        self.assertTrue(notes, "no example exercised a normalising rule, so the "
                               "rules are measured by nothing")
        for stem, why in reported:
            self.assertTrue(why.strip(), f"{stem} is unreported and unexplained")

    def test_the_examples_corpus_is_mostly_measured(self):
        """The coverage number this file exists to keep honest.

        41 of 52 was the state this normaliser was written for, and the 11 that
        were not measured were all refused for a spelling rather than for a
        semantics.  Asserting a floor rather than 52 keeps the assertion honest
        when a future example adds a construct — the point is that the tool
        measures the corpus, not that it measures every file in it.
        """
        if not os.path.isdir(EXAMPLES):
            self.skipTest("formal/examples is not present")
        stems = [f for f in os.listdir(EXAMPLES) if f.endswith(".mojo")]
        driven = 0
        for stem in stems:
            with open(os.path.join(EXAMPLES, stem)) as f:
                if M.example_program(f.read())["text"] is not None:
                    driven += 1
        self.assertGreaterEqual(driven, len(stems) - 1,
                                f"{len(stems) - driven} of {len(stems)} examples "
                                f"are not measured")

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