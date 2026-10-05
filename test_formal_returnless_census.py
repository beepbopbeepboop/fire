#!/usr/bin/env python3
"""The return-less census is a MEASUREMENT, so the measurement is pinned — one
case per rule that decides a row, including the rules that REMOVE one.

    python3 test_formal_returnless_census.py [-v]

`tools/formal_returnless_census.py` answers the question
`bugs/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`
§4 step 0 asks for: how many call sites in this repository and the stdlib
CONSUME the value of a function that returns nothing. Its number is quoted in
that doc and decides whether a `None` refusal is affordable, so the rules that
decide a row are the instrument.

**What has to be pinned, and the two that are easy to get wrong in the
inventing direction:**

  * a call as the value of an `ExprStmt` — `print(g(1, 2))` — DISCARDS its
    result. The AST evaluator's `MojoStmt.exprstmt` arm does not evaluate the
    expression at all, which is why `fn main(): print(42)` proved with no
    holes, and a census that counted those rows would report the shape
    `bugs/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`'s
    own reproducer as a divergence when the answer is never observed;
  * a GENERATOR's "return value" is the generator object, and a STRUCT's is a
    frame. Counting either put 456 rows in `formal/hostmods/argparse.mojo` on
    the instrument's first run — that file constructs a hundred action objects —
    and a census that reports its own blindness as a fact about the corpus is
    the one thing a census must not do.

**And the one that is easy to get wrong in the MISSING direction**, which is
§0's own bug: a name with two definitions that disagree about whether they
return is UNDECIDED, so its call sites are not candidates. `add`, `chain`,
``gcd`, `count` and `__enter__` are undecided in the real corpus, and a
by-name table would have called all of them return-less.

Every case goes through the tool's own `collect`, so what is asserted is what the
census prints rather than a re-derivation of it.
No Lean, no build: the instrument is a parse and a walk.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_returnless_census as C   # noqa: E402


def census(source, name="case.mojo"):
    """`(decided, candidates)` for one source, through the tool's own readers.

    `decided` is `formal_returnless_census.decided_names`' table — the same one
    the report prints its "decided / undecided" line from — and `candidates` is
    the `(same_file, path, line, name, position)` rows.

    **The tool's `decided_names` and `candidate_rows`, not a second copy of
    either.** This helper used to carry its own comprehension of the same rule,
    and it was the reason the rule's own defect survived: both copies spelled
    `defs[0][2] and defs[0][3]`, and every case in this file that reached the
    DECLARED half spelled a function that returns AND declares — so the two
    copies agreed on all of them and neither was ever asked about a function
    that returns a value without declaring one, which is the shape the whole
    corpus is made of (`formal/hostmods/argparse.mojo`'s `_fld` and its 456
    call sites). Asking the tool is also the only way a test here can fail when
    the tool's rule changes.
    """
    tmp = tempfile.mkdtemp(prefix="rlc-")
    try:
        path = os.path.join(tmp, name)
        with open(path, "w") as f:
            f.write(source)
        index, calls, _defs, _rl, _structs = C.collect([path])
        _decided, _kinds, rows = C.candidate_rows(index, calls)
        return (C.decided_names(index),
                [(r[0], r[1], r[2], r[3], r[5]) for r in rows])
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


class TestWhatCounts(unittest.TestCase):
    def test_a_returned_call_of_a_return_less_function_is_a_candidate(self):
        decided, rows = census(
            "def quiet(a):\n"
            "    w = 1\n"
            "def main(n):\n"
            "    return quiet(n)\n")
        self.assertFalse(decided["quiet"],
                         "`quiet` has no value-returning `return` and declares "
                         "no type, so it returns nothing")
        self.assertEqual([r[3] for r in rows], ["quiet"],
                         f"the returned value is not a candidate: {rows}")
        self.assertEqual(rows[0][4], "returned",
                         f"the row does not say where the value goes: {rows}")

    def test_a_discarded_call_is_not_a_candidate(self):
        """A bare `quiet(n)` on its own line observes nothing: the value is
        thrown away.

        **This is the case `print(quiet(n))` is NOT**, and the difference is the
        whole reason the instrument counts POSITIONS: `print` is itself a call,
        so `quiet(n)`'s parent is the `print` CallExpr and its value IS consumed
        — it is the word the program prints where CPython prints `None`, which
        is this document's own reproducer. A census that treated "an expression
        statement" as "a discarded value" at any depth would have thrown the
        reproducer away, which is the failure this row exists to prevent."""
        decided, rows = census(
            "def quiet(a):\n"
            "    w = 1\n"
            "def main(n):\n"
            "    quiet(n)\n"
            "    return 0\n")
        self.assertFalse(decided["quiet"])
        self.assertEqual(rows, [],
                         f"an expression statement discards its value: {rows}")

    def test_a_printed_call_is_a_candidate_because_print_consumes_it(self):
        decided, rows = census(
            "def quiet(a):\n"
            "    w = 1\n"
            "def main(n):\n"
            "    print(quiet(n))\n"
            "    return 0\n")
        self.assertEqual([(r[3], r[4]) for r in rows],
                         [("quiet", "argument of a call")],
                         f"the doc's own reproducer is a candidate, and the row "
                         f"says why: {rows}")

    def test_a_generator_is_not_a_function_that_returns_nothing(self):
        decided, rows = census(
            "def gen(n):\n"
            "    yield n\n"
            "def main(k):\n"
            "    return list(gen(k))\n")
        self.assertTrue(decided["gen"],
                        "a generator's value is the generator object, so "
                        "`yield n` with no `return` is NOT a return-less "
                        "function — and every `for x in gen(y)` would be a "
                        "false row")
        self.assertEqual(rows, [])

    def test_a_struct_construction_is_not_a_call(self):
        decided, rows = census(
            "struct Point:\n"
            "    var x: Int\n"
            "def main(n):\n"
            "    p = Point(n)\n"
            "    return p.x\n")
        self.assertEqual(rows, [],
                         f"`Point(n)` binds a frame and has a whole value model "
                         f"of its own: {rows}")

    def test_a_declared_return_type_keeps_it_out(self):
        decided, rows = census(
            "def quiet(a) -> Int:\n"
            "    w = 1\n"
            "    return 0\n"
            "def main(n):\n"
            "    return quiet(n)\n")
        self.assertTrue(decided["quiet"],
                        "a declared return type means this path has said what "
                        "the function means, so it is out of the census whatever "
                        "the body does")
        self.assertEqual(rows, [])

    def test_a_return_with_no_declared_type_is_not_a_candidate(self):
        """The half the census got WRONG, and the corpus's commonest shape.

        `def fld(rec, k): … return p` — a function that RETURNS a value and
        DECLARES nothing — is not "a function that returns nothing", and filing
        its call sites as candidates is what put **456 rows in
        `formal/hostmods/argparse.mojo`** into the report §0a of
        `bugs/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`
        quotes: `_fld`, `_cp`, `_alpha_index` and `_name_ptr` are all of this
        shape and that file is a host module the gate compiles. The rule is a
        DISJUNCTION — a candidate is a site whose callee has neither a
        value-returning `return` nor a declared return type — and reading it as a
        conjunction needs both halves false at once, which for an undeclared
        function is never so.
        """
        decided, rows = census(
            "def fld(rec, k):\n"
            "    p = rec\n"
            "    while k > 0:\n"
            "        p = p + 1\n"
            "        k = k - 1\n"
            "    return p\n"
            "def main(n):\n"
            "    x = fld(n, 3)\n"
            "    return x\n")
        self.assertTrue(decided["fld"],
                        "`fld` returns a value, so consuming it is not a "
                        "candidate: the doc's rule is 'no value-returning "
                        "`return` AND no declared return type'")
        self.assertEqual(rows, [], f"a returning call is a candidate: {rows}")

    def test_a_declared_type_with_no_return_is_not_a_candidate_either(self):
        """The other half alone, which is what `_declares_a_return` is FOR.

        `def quiet(n) -> Int: w = 1` states what it means even where the value
        is not CPython's, so it is out of the census for the DECLARATION and not
        for the `return`. The case above spells a function that both returns and
        declares, so this half was never asked about on its own — which is how a
        conjunction survived every case in this file, in the tool AND in the
        helper above.
        """
        decided, rows = census(
            "def quiet(n) -> Int:\n"
            "    w = 1\n"
            "def main(n):\n"
            "    return quiet(n)\n")
        self.assertTrue(decided["quiet"],
                        "a declared return type alone keeps it out — that is "
                        "what the second half of the rule is for")
        self.assertEqual(rows, [])

    def test_an_assigned_call_is_a_candidate_and_says_it_is_the_weakest(self):
        decided, rows = census(
            "def quiet(a):\n"
            "    w = 1\n"
            "def main(n):\n"
            "    x = quiet(n)\n"
            "    return 0\n")
        self.assertEqual([r[4] for r in rows], ["assigned"])
        # The census's own vocabulary: a position the report does not have a
        # note for would be a row a reader cannot interpret, and "assigned" is
        # the one that most needs the note (nothing here does a liveness pass).
        self.assertIn("assigned", C.POSITION_NOTES,
                      "the weakest position is the one whose note says why it "
                      "is weak")

    def test_a_call_through_a_receiver_is_seen(self):
        """The shape §0's census could not see, and a method value IS consumed.

        `self._flatten(…)` reads a field and does not return; a receiver call is
        a call, and a census that only matched bare names would report zero."""
        decided, rows = census(
            "struct S:\n"
            "    var v: Int\n"
            "\n"
            "    def _setup(self):\n"
            "        w = 1\n"
            "\n"
            "    def run(self) -> Int:\n"
            "        return self._setup()\n")
        self.assertFalse(decided["_setup"])
        self.assertEqual([r[3] for r in rows], ["_setup"],
                         f"a receiver call is not in the census: {rows}")


class TestTheIndexIsNotNameKeyed(unittest.TestCase):
    def test_definitions_that_disagree_leave_the_name_undecided(self):
        """The defect §0's census had, as a case.

        `coord.mojo` declares `value` three times and `info.mojo` declares
        `normalize_target_arch` twice; at least one definition of each RETURNS,
        and a `{name: has-no-return}` set cannot tell which. So the name is
        absent from the decided table and its call sites are not candidates."""
        decided, rows = census(
            "def thing(n):\n"
            "    return n\n"
            "\n"
            "def thing(n):\n"
            "    w = 1\n"
            "\n"
            "def main(k):\n"
            "    return thing(k)\n")
        self.assertNotIn("thing", decided,
                         "a name whose definitions disagree must be absent "
                         "from the decided table — `formal/build.py`'s own rule "
                         "for a name that disagrees about returning a frame")
        self.assertEqual(rows, [],
                         f"an undecided name is not a candidate: {rows}")

    def test_definitions_that_agree_are_decided(self):
        """The control: two definitions that AGREE are one answer, and the
        instrument must still report them (it prints both sites)."""
        decided, rows = census(
            "def thing(n):\n"
            "    w = 1\n"
            "\n"
            "def thing(n):\n"
            "    v = 2\n"
            "\n"
            "def main(k):\n"
            "    return thing(k)\n")
        self.assertFalse(decided["thing"])
        self.assertEqual([r[3] for r in rows], ["thing"])

    def test_a_same_name_in_another_file_is_reported_as_other_file(self):
        tmp = tempfile.mkdtemp(prefix="rlc2-")
        try:
            a = os.path.join(tmp, "a.mojo")
            b = os.path.join(tmp, "b.mojo")
            with open(a, "w") as f:
                f.write("def helper(n):\n    w = 1\n")
            with open(b, "w") as f:
                f.write("def main(k):\n    return helper(k)\n")
            index, calls, _d, _r, _s = C.collect([a, b])
            decided = {n: defs[0][2] and defs[0][3]
                       for n, defs in index.items()
                       if len(defs) == 1 or all(x[2] == defs[0][2]
                                                and x[3] == defs[0][3]
                                                for x in defs)}
            self.assertFalse(decided["helper"])
            self.assertEqual(len(calls), 1)
            path, line, callee, recv, position = calls[0]
            self.assertEqual((callee, position), ("helper", "returned"))
            self.assertTrue(os.path.relpath(b, C.ROOT).endswith("b.mojo"))
            self.assertFalse(os.path.relpath(a, C.ROOT) == path,
                             "the call and the definition are in different "
                             "files, which is the instrument's stated upper "
                             "bound — a parse-and-walk does not resolve imports")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)