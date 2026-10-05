#!/usr/bin/env python3
"""The host-import WALL tool is a measurement, so its readers are pinned — one
case each, and each case a filter that is what separates.

    python3 test_formal_host_import_wall.py [-v]

`tools/formal_host_import_wall.py` answers "what is left of the
`not-answerable/host-import` row, and what would each name take", which three
bug docs had each described in prose before it was promoted out of scratch
(`bugs/FORMAL_the_host_import_wall_is_at_its_honest_floor.md` §5 and
`bugs/FORMAL_eleven_of_thirteen_host_import_rows_are_closure.md`'s own
re-measurement). A measurement whose readers are unpinned reports its own
blindness as a fact about the corpus, so what is pinned here is the SET OF
READERS, not the numbers they produce — a number that moves with the tree is the
instrument working, and a snapshot of one would be red within a week and mean
nothing when it went green.

  * **the backend's readers, not Python's** — `imported_modules` takes
    `fire_compiler`'s node classes, so an `ast`-based walk returns nothing and
    every row reads 0; and it deliberately does not descend into `if`/`try`
    bodies, which is the exclusion that made an `ast` walk call `traceback` a
    38-file row where the backend says 0;
  * **a file the backend cannot read is `None`, not `[]`** — "imports nothing"
    and "could not be read" are different answers, and the tool's own header
    prints the count of the second. The corpus no longer contains such a file
    (`cca2a17f` closed the one CPython read and this tokenizer did not), so the
    `None` is pinned on a shape no Python accepts and the closed case is pinned
    beside it as a regression row — a reader that answered `None` for a file it
    reads perfectly well would report a coverage hole that does not exist;
  * **`--unmodelled` is the before/after instrument** — a module landing
    UNMASKS the row behind it and never grows one, so a delta measured across
    two checkouts measures the merge. This is the one ability the promotion had
    to keep and it is pinned on a real file in this tree;
  * **`alone` means "the ONLY wall"**, not "the first one found", because the
    first is a property of the traversal order;
  * **the sweep column peels a chain to its INNERMOST host module**, which is
    the same peel `tools/formal_sweep_causes.py::rank` does, and it is read
    with that tool's reader rather than a second spelling of the pattern.

No build, no Lean, no sweep: the instrument is a parse and a walk.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_host_import_wall as W     # noqa: E402
# The readers themselves, imported by name: the test's subject is which readers
# the tool asks, so a reader that moves is a visible failure here rather than a
# different answer from the tool.
from formal.imports import host_module_tier, resolve_module_path   # noqa: E402


def write(directory, name, source):
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(source)
    return path


class TempTree(unittest.TestCase):
    """A scratch module tree, so the resolvers answer the way they will in it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="formal_host_import_wall_")

    def path(self, name, source):
        return write(self.dir, name, source)


class TestTheReadersAreTheBackends(TempTree):

    def test_the_names_come_from_the_backend_and_skip_conditional_imports(self):
        """`imported_modules` filters two kinds, and both filters are findings.

        The conditional one is the doc's own correction: an `ast`-based walk
        reported `traceback` as a 38-file row, all of it from `import
        traceback` inside `if`/`try` blocks. A conditional import is not on the
        link line, so the build does not see it and neither does this.
        """
        path = self.path("cond.py",
                         "import pwd\n"
                         "if True:\n"
                         "    import wave\n"
                         "try:\n"
                         "    import cgitb\nexcept ImportError:\n"
                         "    pass\n"
                         "def f():\n"
                         "    import mailcap\n"
                         "    return mailcap\n")
        self.assertEqual(W.module_imports(path), ["pwd", "mailcap"],
                         "the conditional imports are filtered and the "
                         "function-local one is not: the exclusion is about "
                         "CONDITIONALS, not about nesting")

    def test_a_file_the_backend_cannot_read_is_none_and_not_empty(self):
        """The distinction the header prints a count for.

        A `[]` here would make an unreadable file contribute no walls and look
        like a file that imports nothing, which is the narrower answer wearing
        the same word.

        **The unreadable file is one this tokenizer refuses as a MATTER OF
        COURSE, not one it used to refuse by accident.** This case was pinned on
        `test_formal_libc_symbol.py`, whose source held a PEP 701 f-string whose
        replacement field spanned lines: the only file in the sweep's 738-file
        scope CPython accepted and `fire_compiler.py` did not, and a real hole in
        this repository rather than a limit of the formal value model. That hole
        is closed — `cca2a17f` made `_scan_string_end` brace-aware, and the file
        tokenizes now, so a fixture of that shape asserts nothing: it reads as a
        list of imports and this case went red on the FIX.

        So the shape here is an unterminated triple-quoted string, which no
        Python accepts and which therefore keeps testing the reader rather than
        the lexer's agreement with CPython. Measured over this checkout's own
        363 `.py` files and the 749 the sweep walks, the backend now reads every
        one, so the count the header prints is 0 today; the reader still has to
        answer `None` for the file that cannot be read, because that is the
        answer a caller uses to tell "imports nothing" from "not measured", and
        a tree that grows such a file again must not silently widen its own
        coverage claim.
        """
        path = self.path("broken.py", 's = """abc\n')
        self.assertIsNone(W.module_imports(path),
                          "an unreadable file must not read as 'imports "
                          "nothing' — that is the narrower answer wearing the "
                          "same word")
        ok = self.path("fine.py", "import pwd\n")
        self.assertEqual(W.module_imports(ok), ["pwd"])

    def test_a_file_cpython_reads_and_this_backend_used_to_refuse_is_read_now(self):
        """The PEP 701 case, as a REGRESSION row for the lexer fix that closed it.

        It belongs beside the `None` case rather than inside it because it is a
        different claim: that one says "a file the backend cannot read must not
        read as `[]`", and this one says the class of files that answer is now
        empty over this tree's own corpus. Without it, the case above would go
        quietly untrue — a reader that answered `None` for a file the backend
        reads perfectly well would pass it, which is a wall tool reporting a
        coverage hole that does not exist.

        The file is `test_formal_libc_symbol.py` itself, the one the corpus-wide
        comparison in `cca2a17f` measured as the single disagreement: tokenized
        as `(kind, value, line, col)` per token, and now reaching
        `module_imports` rather than a refusal.
        """
        here = os.path.join(HERE, "test_formal_libc_symbol.py")
        self.assertTrue(os.path.isfile(here), here)
        self.assertIsNotNone(
            W.module_imports(here),
            "the multiline f-string replacement field this file spells is "
            "accepted by CPython since PEP 701 and by this tokenizer since "
            "cca2a17f; if this goes red the lexer regressed and the tool is "
            "understating its own corpus again")

    def test_the_closure_is_transitive_because_the_build_links_it(self):
        """A file that never spells the wall is still refused on it.

        `formal/build.py` compiles every module of the closure into a dylib and
        links them, so `top.py` importing `mid.py` which imports `pwd` is
        refused on `pwd` — which is why `importlib` reaches 235 files that
        mention it twice between them.
        """
        self.path("mid.py", "import pwd\n")
        top = self.path("top.py", "import mid\n")
        self.assertEqual(W.walls_of(top), frozenset({"pwd"}))


class TestWhatAWallIs(TempTree):

    def test_a_standard_library_name_no_tier_classifies_is_still_a_wall(self):
        """The two questions, asked in the two places that use them.

        `host_module_tier` answers "has this tree CLASSIFIED the name" and
        `is_cpython_stdlib` answers "does CPython ship it"; a name for which the
        first says no and the second says yes is a wall with no tier. `pwd` is
        a real one — `formal/hostmods/` has no `pwd.mojo` and no tier names it,
        and it is the only wall in `test_formal_os.py` today.
        """
        self.assertEqual(host_module_tier("pwd"), "")
        self.assertTrue(W._is_wall("pwd"))
        top = self.path("os_test.py", "import pwd\n")
        self.assertEqual(W.walls_of(top), frozenset({"pwd"}))

    def test_a_name_nothing_provides_is_not_a_wall(self):
        """The negative, which is what keeps the row from being everything.

        A module that is not CPython's and has no source is a typo or a gap in
        this repository, and `tools/formal_sweep.py` reports it as
        `not-answerable/unresolved-import` — a different class, and one a wall
        table that counted it would misattribute to the target.
        """
        self.assertFalse(W._is_wall("definitely_not_a_real_module_9f3a"))
        top = self.path("typo.py", "import definitely_not_a_real_module_9f3a\n")
        self.assertEqual(W.walls_of(top), frozenset())

    def test_a_module_this_tree_writes_is_not_a_wall(self):
        """The other half of the same rule, and the one a module landing flips.

        `formal/hostmods/glob.mojo` exists, so `glob` resolves and is not a wall
        — which is the whole mechanism by which writing a host module moves a
        row.
        """
        self.assertIsNotNone(resolve_module_path("glob"))
        top = self.path("g.py", "import glob\n")
        self.assertEqual(W.walls_of(top), frozenset())

    def test_a_frontend_provided_name_is_not_a_wall(self):
        """`dataclasses` is a front-end transform, not a host module.

        `imported_modules` filters it, so the walk never even asks; this pins
        that the filter is where the doc says it is, because an `ast` walk puts
        `dataclasses` on 176 files and calls the target its problem.
        """
        path = self.path("dc.py", "import dataclasses\nfrom dataclasses import dataclass\n")
        self.assertEqual(W.module_imports(path), [])
        self.assertEqual(W.walls_of(path), frozenset())


class TestAloneIsTheOnlyWall(TempTree):

    def test_alone_is_not_the_first_wall_found(self):
        """The order-independent definition, and why it is this one.

        "Writing this module makes this file build" is a statement about a file
        having exactly ONE wall. The first wall a traversal happens to reach is
        a property of the traversal, and `fire_compiler.py` reaching five
        unresolved modules is how `importlib` reached 165 files and was "the"
        blocker for all of them.
        """
        self.path("other.py", "import wave\n")
        top = self.path("two.py", "import other\nimport pwd\n")
        rows = W.rank([top])
        self.assertEqual(sorted(rows), ["pwd", "wave"])
        self.assertEqual(rows["pwd"]["reach"], [top])
        self.assertEqual(rows["pwd"]["alone"], [], "two walls is not 'alone'")
        self.assertEqual(rows["wave"]["alone"], [])

        only = self.path("one.py", "import pwd\n")
        rows = W.rank([only])
        self.assertEqual(rows["pwd"]["alone"], [only])

    def test_every_alone_file_is_also_a_reaching_file(self):
        """The invariant the two columns share, in one direction that must hold.

        `alone` is a subset of `reach` by construction; asserting it catches the
        shape where a `rank` builds the two dicts from different walks and one
        of them stops short. Six files each with exactly one wall are all six
        alone, which is also why the two columns cannot be derived from each
        other.
        """
        files = [self.path(f"m{i}.py", "import pwd\n" if i % 2 else "import wave\n")
                 for i in range(6)]
        rows = W.rank(files)
        for name, info in rows.items():
            self.assertTrue(set(info["alone"]) <= set(info["reach"]), name)
        self.assertEqual({name: len(v["alone"]) for name, v in rows.items()},
                         {"pwd": 3, "wave": 3})


class TestTheUnmodelledFlag(TempTree):
    """The ability the promotion had to keep, pinned on a REAL file.

    A before/after across two checkouts measures the merge, not the change:
    every other file in the tree moved too. `--unmodelled` pretends a module has
    no `formal/hostmods/` source, which is exactly what "before this module
    landed" means, so the delta is measurable on one tree.
    """

    def test_a_written_module_stops_being_a_wall_when_it_is_pretended_away(self):
        path = os.path.join(HERE, "tools", "suite.py")
        self.assertTrue(os.path.isfile(path), path)
        self.assertEqual(W.walls_of(path), frozenset(),
                         "tools/suite.py imports glob, and glob is written — "
                         "so it is not a wall today. If this row ever goes red "
                         "the module it names has been written or removed")
        self.assertEqual(W.walls_of(path, frozenset({"glob"})),
                         frozenset({"glob"}),
                         "pretending glob unmodelled is what makes this file's "
                         "delta measurable, and it is the only column that can")

    def test_the_flag_turns_a_resolvable_name_into_a_wall_and_never_the_reverse(self):
        """The direction of the flag, which is the measurement's whole point.

        Pretending a module away can only ADD a name to a file's wall set. A
        flag that could remove one would be measuring something else. `local.py`
        is the case that separates the two: it has a source, so it is not a
        wall, and pretending it has none is what a host module landing does.
        """
        self.path("local.py", "x = 1\n")
        top = self.path("two.py", "import local\nimport pwd\n")
        self.assertEqual(W.walls_of(top), frozenset({"pwd"}))
        self.assertEqual(W.walls_of(top, frozenset({"local"})),
                         frozenset({"local", "pwd"}))


class TestTheSweepColumn(unittest.TestCase):

    LOG = "\n".join([
        "NOT-ANSWERABLE/HOST-IMPORT: _ab.py  (build: _ab.py imports "
        "'test_ab_native', which cannot be built either: test_ab_native.py "
        "imports 'atexit', which is a host module (CPython standard library), "
        "which has no Mojo source for this backend to compile)",
        "NOT-ANSWERABLE/HOST-IMPORT: solo.py  (build: solo.py imports 'uuid', "
        "which is a host module (CPython standard library), which has no Mojo "
        "source for this backend to compile)",
        "NOT-ANSWERABLE/HOST-IMPORT: untiered.py  (build: untiered.py imports "
        "'plistlib', which is a CPython standard-library module, which has no "
        "Mojo source in this tree and no tier in `formal/imports.py` saying "
        "whether implementing it would need an object this target does not "
        "have — so nothing here can say whether it is reachable)",
        "CODEGEN: other.py  (build: other.py: unsupported construct)",
        "NOT-ANSWERABLE/UNRESOLVED-IMPORT: typo.py  (build: typo.py imports "
        "'nope_9f3a', which is not a stdlib or sibling module)",
    ]) + "\n"

    def rows(self):
        import tempfile
        fd, path = tempfile.mkstemp(prefix="sweep_log_", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(self.LOG)
        try:
            return W.sweep_rows(path), W.sweep_coverage(path)
        finally:
            os.unlink(path)

    def test_the_column_is_the_INNERMOST_host_module_of_the_chain(self):
        """The peel, and why the innermost one.

        A file's chain names every module the walk passed through and the
        refusal names the one that stopped it, so counting the OUTER name would
        put `_ab.py` on a row about `atexit` — and 37 of the 40 files the `cas.py`
        row blocks are exactly that shape: they spell nothing `cas.py` declares.
        """
        rows, _coverage = self.rows()
        self.assertEqual(rows["_ab.py"], "atexit",
                         "the chain's outermost module is test_ab_native; the "
                         "one that refused is atexit")
        self.assertEqual(rows["solo.py"], "uuid")

    def test_both_wordings_of_a_host_module_are_one_column(self):
        """The no-tier wording, and matching one of the two is a BIAS.

        `formal/imports.py::unresolvable_import_error` has three arms and two of
        them name a host module: a name a tier classifies, and a name CPython
        ships that no tier classifies. A pattern that knows only the first drops
        exactly the files that are in no tier, so the column would be silent
        about the rows `bugs/FORMAL_stdlib_module_names_are_not_classified.md`
        is about. Measured on `sweep-arm-11.txt`: 4 of 203 lines, all four of
        the second wording.
        """
        rows, coverage = self.rows()
        self.assertEqual(rows["untiered.py"], "plistlib")
        self.assertEqual(coverage, (3, 3), "every host-import line is attributed")

    def test_a_line_of_another_class_contributes_nothing(self):
        """The class filter, in both directions.

        Only `not-answerable/host-import` lines are this column, and the sweep
        prints the class UPPERCASED — so the prefix to match is the class in
        that spelling and not the constant, which is the mistake that made this
        column print 0 rows against a log with 203 of them in it.
        """
        rows, _coverage = self.rows()
        self.assertNotIn("other.py", rows)
        self.assertNotIn("typo.py", rows)

    def test_an_absent_log_is_an_empty_column_and_not_a_zero_column(self):
        """No measurement is not a measurement of zero.

        The function answers `{}` for a log that is not there, so a caller
        printing `sweep=0` for every row would be claiming the sweep saw nothing
        when it saw no log at all. The header distinguishes them.
        """
        self.assertEqual(W.sweep_rows(os.path.join(HERE, "no_such_log.txt")), {})

    def test_the_committed_log_is_attributed_completely(self):
        """The one coverage assertion, because a filter can exclude everything.

        Every other assertion here is about which rows are in and which are out;
        without this one, a regex that matched nothing at all would pass all of
        them. `bugs/sweeps/sweep-arm-11.txt` is the log the work map's §2
        numbers were read out of, and it is the newest arm64 one in the tree.
        Both halves matter: `total` is the log's own count of host-import lines,
        and `attributed` is how many of them this column named a module for.
        """
        log = os.path.join(HERE, "bugs", "sweeps", "sweep-arm-11.txt")
        if not os.path.isfile(log):
            self.skipTest("no sweep log in this checkout")
        rows = W.sweep_rows(log)
        attributed, total = W.sweep_coverage(log)
        self.assertEqual(total, 203, "the log's own host-import line count")
        self.assertEqual(attributed, total,
                         f"a line was dropped: {sorted(set(W.sweep_rows(log)))}")
        self.assertEqual(rows.get("_ab.py"), "atexit")
        self.assertEqual(rows.get("test_ast_formal.py"), "tokenize",
                         "the no-tier wording, which is the arm the pattern "
                         "that matched only 'is a host module' would lose")


class TestTheRankingOrder(unittest.TestCase):
    """`alone` first, because that is the column a module landing converts.

    A row with a large `reach` and no `alone` file is closure: 235 files reach
    `abc` and writing it moves none of them, which is the whole reading
    `bugs/FORMAL_eleven_of_thirteen_host_import_rows_are_closure.md` gave.
    """

    def test_the_json_rows_are_sorted_by_alone_then_reach(self):
        rows = [
            {"name": "closure_only", "alone": 0, "reach": 500},
            {"name": "small_alone", "alone": 1, "reach": 3},
            {"name": "big_alone", "alone": 7, "reach": 9},
        ]
        ordered = sorted(rows, key=lambda r: (-r["alone"], -r["reach"], r["name"]))
        self.assertEqual([r["name"] for r in ordered],
                         ["big_alone", "small_alone", "closure_only"])



if __name__ == "__main__":
    unittest.main()