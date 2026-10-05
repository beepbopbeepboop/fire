#!/usr/bin/env python3
"""`tools/formal_host_import_shapes.py` is a measurement, so its READERS are
pinned — one case each, and each case a filter that is what separates.

    python3 test_formal_host_import_shapes.py [-v]

`tools/formal_sweep_causes.py --host` ranks the host-import rows by files
blocked and adds a `uses:` column. That column cannot answer the question the
queue actually asks, for two reasons this tool exists to close, and both are
pinned here:

  * for a module with no `.py` source in this interpreter's stdlib it can only
    print a LOWER BOUND (`itertools`, `builtins`, `resource`, `pwd`), and the
    count it cannot get is answerable from the other end — the swept file's own
    AST says what it spells;
  * "the file names it" is not "a `.mojo` module can answer it". A value on this
    path is one 64-bit word, so the SHAPE of each use decides whether a module
    could answer it at all, and the tool's column is that shape.

WHAT IS PINNED, AND WHY IT IS THE READERS AND NOT THE NUMBERS
---------------------------------------------------------------
A number here moves with the tree: the whole point of the `live` column is that
it re-reads the files NOW, so a wave's effect shows up without a re-sweep and a
snapshot of it would be red within a week and mean nothing when it went green.
So the readers are pinned on synthetic sources where each case is a filter that
is what separates two shapes, and the only things pinned against the real corpus
are properties that must hold for the instrument to be an instrument at all
(§`TestAgainstTheRealCorpus`) plus three `live=0` ratchets whose going red is
the signal anyone wants.

The instrument is a parse and a walk. No build, no Lean, no sweep.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_host_import_shapes as S     # noqa: E402

# Every shape the tool can print. A shape that is not in this set is a bug in
# the tool or in this table, and the corpus test below fails on either — the
# point being that a new shape cannot appear in a report without somebody
# having decided what it MEANS, since the whole reading of the table is which
# shapes stand between a row and a module.
SHAPES = {"WORD", "FIELD", "SUBSCRIPT", "CONCAT", "FSTRING", "BARE",
          "DECORATOR", "STAR", "DEAD"}


def write(directory, name, source):
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(source)
    return path


class TestTheShapes(unittest.TestCase):
    """One source per shape, each one a case a parent lookup would get wrong."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hostmods_shapes_")

    def shapes(self, source, module="zlib"):
        path = write(self.dir, "probe.py", source)
        return S.uses_in(path, module)

    def test_a_call_is_a_word(self):
        got = self.shapes("import zlib\n\nzlib.crc32(1)\n")
        self.assertEqual(got, {"zlib.crc32": {"WORD"}})

    def test_a_field_through_a_call_is_both(self):
        """`f(x).attr` is a WORD AND a FIELD, and reporting only one of the two
        says the wrong thing: the call is the shape a module could publish and
        the field is what stands in its way, so a row reported as `WORD` alone
        reads as work."""
        got = self.shapes("import zlib\n\nzlib.crc32(1).name\n")
        self.assertEqual(got, {"zlib.crc32": {"WORD", "FIELD"}})

    def test_a_bare_name_is_not_a_word(self):
        """`os.sep` and `os.getenv("HOME")` look alike to a reader who looks
        one parent out, and they are different problems: one is refused as a
        read of a module-level name, the other lowers. So a name nothing CALLS
        is `BARE`, and it is `BARE` whether it is an operand, an argument or a
        statement of its own."""
        for src, why in (
                ("import zlib\n\nx = zlib.ZLIB_VERSION == 1\n",
                 "as an operand"),
                ("import zlib\n\nzlib.crc32(zlib.ZLIB_VERSION)\n",
                 "as an argument"),
                ("import zlib\n\nzlib.ZLIB_VERSION\n",
                 "as a statement of its own")):
            with self.subTest(why):
                got = self.shapes(src)
                self.assertEqual(got["zlib.ZLIB_VERSION"], {"BARE"})

    def test_a_subscript_and_a_concatenation_are_theirs_own(self):
        """Both need something a word is not — a container and a buffer — and
        both are refusals of their own rather than the field refusal, so
        collapsing them into one shape would hide which refusal a reader is
        looking at."""
        self.assertEqual(
            self.shapes("import zlib\n\nzlib.crc32(1)[0]\n")["zlib.crc32"],
            {"WORD", "SUBSCRIPT"})
        self.assertEqual(
            self.shapes("import zlib\n\nzlib.crc32(1) + 'x'\n")["zlib.crc32"],
            {"WORD", "CONCAT"})
        self.assertEqual(
            self.shapes("import zlib\n\nf'{zlib.crc32(1)}'\n")["zlib.crc32"],
            {"WORD", "FSTRING"})

    def test_a_dead_import_is_dead_and_not_zero(self):
        """A dead import blocks a file for the same reason an absent module
        does, and it is invisible in every count that only asks "does the file
        mention the module". `tools/apply_extraction.py`'s `import copy` was
        one, and deleting it closed the `copy` row's only `alone` file."""
        self.assertEqual(self.shapes("import zlib\n\ndef f() -> int:\n"
                                     "    return 1\n"),
                         {"zlib": {"DEAD"}})

    def test_a_comment_and_a_string_are_prose_not_uses(self):
        got = self.shapes("# zlib.crc32(1)\n"
                          "TEXT = 'import zlib; zlib.crc32(1)'\n"
                          "import zlib\n\ndef f() -> int:\n    return 1\n")
        self.assertEqual(got, {"zlib": {"DEAD"}})


class TestTheThreeBindings(unittest.TestCase):
    """CPython has three ways to bind a module's name and reading only one of
    them is how a row looks busy when it is not."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hostmods_bind_")

    def shapes(self, source, module="zlib"):
        return S.uses_in(write(self.dir, "probe.py", source), module)

    def test_a_from_import_is_read_through_the_BOUND_NAME(self):
        """`from zlib import crc32` never spells `zlib` at all, so a reader that
        only looks for `zlib.something` reports the name as unused."""
        got = self.shapes("from zlib import crc32\n\ncrc32(1)\n")
        self.assertEqual(got, {"zlib.crc32": {"WORD"}})

    def test_a_from_import_bound_and_never_read_is_dead(self):
        self.assertEqual(self.shapes("from zlib import crc32\n\n"
                                     "def f() -> int:\n    return 1\n"),
                         {"zlib.crc32": {"DEAD"}})

    def test_an_alias_is_followed(self):
        got = self.shapes("import zlib as _z\n\n_z.crc32(1)\n")
        self.assertEqual(got, {"zlib.crc32": {"WORD"}})

    def test_a_star_import_is_reported_and_NOT_resolved(self):
        """Any name in the file could have come from `M`, so guessing which is
        worse than saying so — and saying so is the shape a reader can act on."""
        got = self.shapes("from zlib import *\n\ncrc32(1)\n")
        self.assertEqual(got, {"zlib.*": {"STAR"}})

    def test_a_decorator_is_its_own_shape(self):
        """A decorator on a function OR a class is DROPPED, silently, by both
        backends, so a name used here would make the program build and enforce
        nothing. It is recorded next to the other shapes rather than instead of
        them: `version.py`'s `@functools.lru_cache(maxsize=1)` is both a
        decorator and a call."""
        got = self.shapes("import zlib\n\n@zlib.cache(maxsize=1)\n"
                          "def f() -> int:\n    return 1\n")
        self.assertEqual(got["zlib.cache"], {"WORD", "DECORATOR"})
        cls = self.shapes("import zlib\n\n@zlib.marker\n"
                          "class C:\n    pass\n")
        self.assertEqual(cls["zlib.marker"], {"BARE", "DECORATOR"})


class TestTheLogReader(unittest.TestCase):
    """The terminal module is the LAST one in the chain, and a line whose
    terminal module cannot be found is DROPPED AND COUNTED rather than guessed
    at: a row keyed on the wrong module is worse than a missing row, because it
    names a module the file does not import."""

    LINE = ("NOT-ANSWERABLE/HOST-IMPORT: {path}  (build: {path} imports "
            "'{first}', which cannot be built either: dep.py imports '{second}',"
            " which is a host module (CPython standard library), which has no "
            "Mojo source for this backend to compile)\n")

    def read(self, lines):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.writelines(lines)
            path = f.name
        try:
            return S.parse_log(path)
        finally:
            os.unlink(path)

    def test_a_chain_is_peeled_to_its_INNERMOST_host_module(self):
        rows, missed = self.read([
            self.LINE.format(path="tools/suite.py", first="cas", second="zlib")])
        self.assertEqual(rows, [("tools/suite.py", "zlib")])
        self.assertEqual(missed, 0)

    def test_the_no_tier_wording_is_matched_too(self):
        """`tokenize` is in NEITHER tier, so its refusal is the OTHER sentence,
        and a pattern matching only "is a host module" loses the whole
        unclassified class of row."""
        rows, missed = self.read([
            "NOT-ANSWERABLE/HOST-IMPORT: test_ast_formal.py  (  test_ast_"
            "formal.py imports 'tokenize', which is a CPython standard-library "
            "module, which has no Mojo source in this tree and no tier in "
            "`formal/imports.py` saying whether implementing it would need an "
            "object this target does not have)\n"])
        self.assertEqual(rows, [("test_ast_formal.py", "tokenize")])
        self.assertEqual(missed, 0)

    def test_a_line_with_no_terminal_module_is_counted_not_guessed(self):
        rows, missed = self.read([
            "NOT-ANSWERABLE/HOST-IMPORT: x.py  (build: x.py imports 'cas', "
            "which cannot be built either)\n",
            "CODEGEN: y.py  (build: y.py: f: refused)\n"])
        self.assertEqual(rows, [])
        self.assertEqual(missed, 1)


class TestAgainstTheRealCorpus(unittest.TestCase):
    """Properties that must hold for the instrument to be an instrument, on the
    real sweep log — no snapshot of any number, because every number here moves
    with the tree and that is the instrument working."""

    # Walked ONCE for the class rather than per test: `rows_for` parses 220
    # files and six tests re-deriving the same table is a test file that takes
    # 34 s to say nothing six times over. One walk, and a test that changes the
    # log would have to say so in this cache rather than by accident.
    _walked = None

    def setUp(self):
        if TestAgainstTheRealCorpus._walked is None:
            sweep = S.default_sweep()
            if not sweep or not os.path.isfile(sweep):
                self.skipTest("no sweep log in this checkout")
            TestAgainstTheRealCorpus._walked = (sweep,) + S.rows_for(sweep)
        self.sweep, self.rows, self.missed, self.total = \
            TestAgainstTheRealCorpus._walked

    def test_every_host_import_line_is_attributed_to_a_row(self):
        """The tool accounts for every line the log printed, or its table is a
        ranking of a subset with nothing saying which subset."""
        counted = sum(r["files"] for r in self.rows)
        self.assertEqual(counted, self.total,
                         f"{self.total - counted} host-import line(s) in "
                         f"{os.path.basename(self.sweep)} are in no row")

    def test_no_line_is_dropped_for_lack_of_a_terminal_module(self):
        self.assertEqual(self.missed, 0,
                         "a line whose terminal module could not be read is "
                         "dropped from the table, and the count is printed but "
                         "nothing fails on it")

    def test_every_shape_is_one_this_file_documents(self):
        """A shape that is not in `SHAPES` has no meaning attached, and the
        whole reading of the table is which shapes stand between a row and a
        module — so an unlabelled one is a silent gap in the vocabulary."""
        for r in self.rows:
            unknown = set(r["needs"]) - SHAPES
            self.assertFalse(unknown,
                             f"{r['name']} reports shape(s) {sorted(unknown)} "
                             f"that this test and the tool's docstring do not "
                             f"define")

    def test_a_row_whose_names_are_all_dead_reads_as_dead(self):
        """`live` counts the files that still spell the module, so a row can
        read `live=0` and mean it. Two rows in the current corpus read that way
        for a reason a module cannot fix, and they are the shape this test is
        for: `importlib.util` and `builtins` are blocked because the files want
        the MODULE'S NAMESPACE (`spec_from_file_location`, `dir(builtins)`),
        which is not a name out of the module at all."""
        for name in ("importlib.util", "builtins"):
            row = next((r for r in self.rows if r["name"] == name), None)
            if row is None:
                continue
            self.assertTrue(row["live"] > 0,
                            f"{name} has left the corpus; delete this case")
            shapes = {s for v in row["names"].values() for s in v}
            self.assertEqual(shapes, {"DEAD"},
                             f"{name} is blocked on something that is not a "
                             f"dead import any more: {row['names']}")

    # ── the three ratchets, whose going RED is the point ────────────────────
    #
    # Each is a row whose files the sweep blocked and this tree no longer
    # imports, so `live` is 0 and a module written for it would be written for
    # nothing. If one of these goes red, the dependency CAME BACK: either
    # deliberately, in which case the reason belongs in the case, or by accident,
    # which is the failure this pins.

    def test_ratchet_itertools_is_not_imported_again(self):
        """`itertools` was 14 sweep files and 19 files of closure for TWO import
        statements, both replaced on 2026-10-05 by index loops that yield the
        same sequence (`test_formal_dylib.py`, `test_module_cache.py`). The
        module cannot answer the row either way — a generator of tuples is not
        one 64-bit word — so a re-import would put 14 files back on the wall
        for nothing."""
        self.assert_row_is_dead("itertools",
                                "two index loops replaced the import")

    def test_ratchet_datetime_is_not_imported_again(self):
        """Two report timestamps moved to `time.time()` on 2026-10-05, which is
        a module this tree HAS; `datetime` is a six-field record and could
        never have answered `.isoformat()`."""
        self.assert_row_is_dead("datetime",
                                "the report timestamps moved to `time.time()`")

    def test_ratchet_copy_is_not_imported_for_nothing(self):
        """`tools/apply_extraction.py` imported `copy` and read nothing through
        it, and that dead import was the row's only `alone` file. The OTHER nine
        files in the row are `copy.copy`/`copy.deepcopy` on values, which is a
        type clone, so this ratchets the DEAD half rather than the row."""
        row = next((r for r in self.rows if r["name"] == "copy"), None)
        if row is None:
            self.skipTest("the copy row has left the corpus entirely")
        dead = [k for k, v in row["names"].items() if v == ["DEAD"]]
        self.assertFalse(
            dead,
            f"the copy row has a dead import again ({dead}); `copy.copy` is a "
            f"type clone and `copy.deepcopy` is its other half, so a file that "
            f"imports it and reads nothing through it is a row about nothing "
            f"— which is how `tools/apply_extraction.py` closed its half")

    def assert_row_is_dead(self, name, why):
        row = next((r for r in self.rows if r["name"] == name), None)
        if row is None:
            self.skipTest(f"{name} has left the corpus entirely")
        self.assertEqual(
            (row["files"], row["live"]), (row["files"], 0),
            f"{name}: {row['live']} of the {row['files']} files the sweep "
            f"blocked it in still spell it, but {why}. Either the "
            f"substitution was undone — put it back and say why — or the row "
            f"needs a module after all, which is a bigger claim than this "
            f"ratchet can make on its own")


if __name__ == "__main__":
    unittest.main()