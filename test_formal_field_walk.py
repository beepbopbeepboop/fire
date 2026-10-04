#!/usr/bin/env python3
"""The STATEMENT walk `struct_receiver_stores` uses, pinned against the full walk.

    python3 test_formal_field_walk.py [-v]

`formal/model.py`'s `iter_statement_nodes` reaches a method body's assignments
by descending only into list fields of statements and of the container types in
`_STATEMENT_CONTAINERS`, where `iter_nodes` descends into every node. That is
~6x fewer nodes on this repository's own largest sources, and it is worth
nothing if it finds a different set of assignments — a missed assignment is a
field this struct does not have, so two real fields end up sharing one slot and
every read of the second returns the first's word.

`tools/formal_field_walk_differential.py` is the measurement that decides it,
over the 712 `.py`/`.mojo` files of this repository and the stdlib, and this file
is what keeps the measurement honest in three ways the tool alone cannot:

  * **the tool can still SEE a difference.** Every case here that expects a
    difference builds a node the walk must miss, so an instrument that had been
    broken into always-agree would fail rather than pass quietly;
  * **the shapes that made the first version wrong are named.** A nested class
    inside a method, an `except` arm and a `match` arm each hid a store from a
    walk without `_STATEMENT_CONTAINERS`, and `fire_compiler.py`'s own
    `TestSuite`, `std/iter`'s `_ChainedIterator` and `std/benchmark`'s `Format`
    are the three structs that caught it. They are here as small sources, so the
    regression is caught by the everyday suite and not only by a 9-second corpus
    walk somebody has to remember to run;
  * **the container tuple is checked against the parser.** A new node type that
    holds statements in a list is the one thing that has to be added to
    `_STATEMENT_CONTAINERS`, so the tool reports every such type and says whether
    the tuple names it; `test_the_container_tuple_covers_what_the_corpus_finds`
    asserts the naming logic itself.

No Lean, no build, no sweep: a parse and two walks.
"""
import argparse
import dataclasses
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import fire_compiler as F                                # noqa: E402
import formal.model as M                                 # noqa: E402
import formal_field_walk_differential as D               # noqa: E402


def stores_of(source, full: bool):
    """`(struct, stores)` for every struct in `source`, under one walk or the
    other. Goes through the tool's own two functions rather than re-deriving
    them, so what is asserted is what the differential compares.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "case.mojo")
        with open(path, "w") as f:
            f.write(source)
        stmts = D.parsed(path)
    want = D.stores_full if full else D.stores_statements
    return [(getattr(st, "name", "?"), sorted(want(st, M.struct_receivers(st))))
            for st in M.iter_nodes(stmts)
            if isinstance(st, F.StructDef) and M.struct_methods(st)]


# ── the two walks agree, on every shape that has a store in it ──────────────
#
# Each of these is a place an assignment can hide, and the list is not
# decorative: `NESTED_CLASS` and the two compound-statement arms are the three
# shapes the FIRST version of the walk got wrong, found by the corpus
# differential on structs in this repository and the stdlib.
NESTED_CLASS = """\
struct Outer:
    var kept: Int

    def build(self, fns):
        class _Suite:
            def __init__(self, fns): self._fns = fns

            def run(self):
                passed = 0
                for name, fn in self._fns:
                    try:
                        fn()
                        passed = passed + 1
                    except Exception as e:
                        pass
                return passed

        return _Suite(fns)
"""

EXCEPT_ARM = """\
struct Guarded:
    var value: Int

    def step(self, n):
        try:
            return self.value + n
        except Exception as e:
            self.value = 0
            raise e
        finally:
            self.value = self.value + 1
"""

MATCH_ARM = """\
struct Shape:
    var value: Int

    def pick(self, k):
        match k:
            case 1:
                self.value = 11
            case 2:
                self.value = 22
            case _:
                self.value = 33
        return self.value
"""

EVERY_ASSIGNMENT_SHAPE = """\
struct Wide:
    var a: Int
    var b: Int
    var c: Int
    var d: Int

    def __init__(self):
        self.a = 1

    def bump(self, n):
        self.b = self.b + n
        self.c += n
        self.d, self.a = n, self.a
        if n > 0:
            self.b = 0
        else:
            self.b = 1
        while n > 0:
            n = n - 1
        for i in [1, 2]:
            self.c = self.c + i
        with open("x") as fh:
            self.d = 1
        del self.d
"""

AGREE_CASES = [
    ("a nested class inside a method", NESTED_CLASS),
    ("an except arm and a finally arm", EXCEPT_ARM),
    ("a match arm", MATCH_ARM),
    ("every assignment statement shape", EVERY_ASSIGNMENT_SHAPE),
]


class TestTheStatementWalkAgrees(unittest.TestCase):
    def test_both_walks_find_the_same_stores(self):
        for name, source in AGREE_CASES:
            with self.subTest(case=name):
                self.assertEqual(stores_of(source, full=False),
                                 stores_of(source, full=True))
                self.assertTrue(stores_of(source, full=False),
                                "the case stores nothing, so it asserts nothing")

    def test_a_store_the_walk_could_miss_is_reported_as_a_difference(self):
        """The instrument must be able to FAIL, and this is how that is pinned.

        A differential whose answer is always "no differences" is
        indistinguishable from a walk that is always right, and the two are not
        the same claim. So: a struct whose method body holds an assignment behind
        a SCALAR field, which is precisely the shape `iter_statement_nodes`
        documents as outside its contract. `iter_nodes` finds the store and the
        statement walk does not, and the differential has to say so — asserted
        through the tool's own two functions and its own `scan`, so what is
        pinned is the instrument rather than a re-derivation of it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hidden.mojo")
            with open(path, "w") as f:
                f.write("struct S:\n    var x: Int\n\n"
                        "    def set(self, v):\n        self.x = v\n")
            # The control first: the file as written has nothing hidden, so the
            # two walks agree on it and the differential is silent.
            rows, scalars, containers = [], set(), set()
            D.scan(path, rows, scalars, containers)
            self.assertEqual(rows, [], "the control case reported a difference")
            self.assertEqual(scalars, set(),
                             "the control case hid a statement behind a scalar")

            # …and the same file with the store moved behind one.
            hidden = _struct_with_a_statement_behind_a_scalar_field()
            self.assertNotEqual(D.stores_statements(hidden, {"self"}),
                                D.stores_full(hidden, {"self"}),
                                "the two walks agree on a store the statement "
                                "walk cannot see, so the differential cannot "
                                "fail")
            self.assertEqual(sorted(D.stores_full(hidden, {"self"})), ["x"])
            self.assertEqual(sorted(D.stores_statements(hidden, {"self"})), [])
            scalars = set()
            D.statements_behind_scalars(hidden, scalars, set())
        self.assertEqual(scalars, {"HiddenStmt.only"},
                         "the scalar census did not see the hidden statement")

    def test_the_container_tuple_covers_what_the_corpus_finds(self):
        """`_STATEMENT_CONTAINERS` names every type the census reports.

        The census is over the corpus, so this is not re-running it — it is
        checking the NAMING: a type the census finds that the tuple does not
        name would be a walk that loses an assignment, and the tool says so, so
        the condition the tool enforces is pinned here rather than only in a
        9-second walk somebody has to remember to run.
        """
        named = {t.__name__ for t in M._STATEMENT_CONTAINERS}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "arms.mojo")
            with open(path, "w") as f:
                f.write(EXCEPT_ARM + MATCH_ARM)
            scalars, containers = set(), set()
            D.statements_behind_scalars(D.parsed(path), scalars, containers)
        self.assertEqual(scalars, set(),
                         "a statement behind a scalar field, which the walk's "
                         "contract forbids")
        found = {name.split(".")[0] for name in containers}
        self.assertTrue(found, "the census found no container at all, so this "
                               "case is asserting nothing")
        self.assertEqual(found - named, set(),
                         "a container type the walk does not descend into")


def _hidden_stmt_holder(statement):
    """A node carrying one statement behind a SCALAR field.

    Built here rather than parsed because no spelling produces one — which is
    the whole point: the shape is not representable in source today, so the only
    way to prove the census can see it is to hand the census one. Named after the
    convention `_is_statement_node` reads (`…Stmt`), so it is a "statement" to the
    walk's own test and a non-container to the descent.

    `dataclasses.make_dataclass` rather than the decorator, and that is not a
    style choice: `test_dataclasses_formal.py`'s corpus discovery treats any file
    containing the decorator's own spelling as a real user of the transform and
    builds it through the formal path, so writing it here — even inside this
    sentence — would add a case to that suite that is a test helper rather than a
    dataclass. It would pass, and it would be a case about nothing.
    """
    return dataclasses.make_dataclass(
        "HiddenStmt",
        [("only", object, dataclasses.field(default=None)),
         ("line", int, dataclasses.field(default=0)),
         ("col", int, dataclasses.field(default=0))])(only=statement)


def _struct_with_a_statement_behind_a_scalar_field():
    """`struct S` whose only method body is one hidden statement.

    The shape that makes the differential meaningful: `iter_nodes` descends into
    `HiddenStmt.only` and finds `self.x = 1`, and `iter_statement_nodes` stops at
    `HiddenStmt` because it is not a statement and not in
    `_STATEMENT_CONTAINERS`. Their store sets therefore differ, which is what the
    corpus run reports for a real source.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "s.mojo")
        with open(path, "w") as f:
            f.write("struct S:\n    var x: Int\n\n"
                    "    def set(self, v):\n        self.x = v\n")
        stmts = D.parsed(path)
    store = F.AssignStmt(target=F.MemberExpr(obj=F.IdentExpr(name="self"),
                                             member="x"),
                         value=F.IntLiteral(value=1))
    st = next(s for s in M.iter_nodes(stmts) if isinstance(s, F.StructDef))
    method = M.struct_methods(st)[0]
    method.body = [_hidden_stmt_holder(store)]
    return st


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if args.verbose:
        unittest.main(argv=[__file__, "-v"])
        return 0
    result = unittest.main(argv=[__file__], exit=False).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())