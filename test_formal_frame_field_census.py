#!/usr/bin/env python3
"""The frame-field census tool is a MEASUREMENT, so the measurement is pinned —
case by case, and each filter that decides a row has a case that removes it.

    python3 test_formal_frame_field_census.py [-v]

`tools/formal_frame_field_census.py` answers the question the field-store
refusal cannot answer about itself: how many sites in this repository and the
stdlib store a frame ADDRESS into a field (`self.f = r`), and of what shape. It
exists because that refusal's evidence — the holder set `formal/build.py`'s
`_refuse_holder_use` consults — is DERIVED, so it exists only for a file that
survives every earlier check, and a census over the corpus is the only way to
count the shape at all.

**Why the answers have to be pinned, and the specific failure this file is
for.** The tool's first cut asked "does this name have a METHOD CALLED ON IT",
which is the natural syntactic proxy for "is this name used as a value" and is
wrong in the direction that invents sites: this repository calls `.strip()` on
strings and `.keys()` on dicts all day, and the first cut reported **52 sites in
19 files of which 28 were a word**. A census that cannot tell "this name holds a
frame" from "this name is used" reports its own blindness as a fact about the
corpus, which is the one thing a census must not do — and the tool's own
docstring names both filters because that is the mistake this shape invites.

So there are two filters and each has a case here that turns it OFF:

  * a parameter annotated with a multi-field struct of the SAME file, or a name
    assigned from a CONSTRUCTION of one — those hold a frame's address;
  * a ONE-FIELD struct does not, because a one-field struct has no frame at
    all (`model.one_word_field_struct` is the reader that says so), and neither
    does a name this file cannot type.

**The two corpus rows are read off the real tree, not written for the test**,
and they are the two shapes the count depends on: a delegating `__init__` — 13
of the 14 sites — and the one site that is neither a parameter nor a declared
local. They are asserted as SHAPES and not as a count over the corpus, because a
count goes stale the moment an unrelated header grows a function and a stale
count is the failure this file is arguing against.

No Lean, no build, no sweep: the instrument is a parse and a walk, so this is
too.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_frame_field_census as C   # noqa: E402


def sites(source, name="case.mojo"):
    """`(function, member, value, kind)` for every site one source yields.

    Goes through the tool's own `scan`, so what is asserted is what the census
    prints rather than a re-derivation of it — which is how an instrument and
    its test come to disagree about what they measured.
    """
    tmp = tempfile.mkdtemp(prefix="frame_field_census_")
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        f.write(source)
    rows = []
    C.scan(path, rows)
    return [(fn, member, value, kind) for _p, fn, _line, member, value, kind
            in rows]


# The structs the filters have to tell apart: `Pair` is TWO fields, so a value
# of it is a frame; `Single` is ONE, so a value of it is a word and a parameter
# annotated with it is not a frame holder. No delegating `__init__` here — the
# corpus' 13-of-14 shape is its own source below, so a filter case can assert
# "this file has NO sites" without carrying one.
STRUCTS = """\
struct Pair:
    var a: Int
    var b: Int

struct Single:
    var only: Int

struct Holder:
    var kept: Pair
    var n: Int

    def keep_single(out self, s: Single):
        self.n = s.only

    def keep_text(out self, s):
        self.n = len(s)
"""

# The DELEGATING CONSTRUCTOR on its own, because it is the site every positive
# assertion is about and a filter case must be able to say "nothing here".
DELEGATING = """\
struct Pair:
    var a: Int
    var b: Int

struct Holder:
    var kept: Pair
    var n: Int

    def __init__(out self, r: Pair):
        self.kept = r
        self.n = 1

    def total(self) -> Int:
        return self.kept.a + self.n
"""


class TestFrameFieldCensus(unittest.TestCase):
    maxDiff = None

    # ── the shape the count is made of ───────────────────────────────────
    def test_a_delegating_constructor_is_a_site_and_is_a_parameter(self):
        """`self.kept = r` where `r` arrived as this method's own parameter.

        This is the DELEGATING CONSTRUCTOR, and it is 13 of the 14 corpus sites
        (`self._list = _list` in `collections/list.mojo`, `self.src = src` in
        `collections/span.mojo`, `self._layout = _layout` in `memory/alloc.mojo`
        and so on). The classification is the useful half: a site whose value is
        a parameter of the SAME method is the shape the delegating-store rule
        (`model.init_stores_a_parameter_struct`) accepts, because both the owner
        and the stored frame belong to the caller's lifetime.
        """
        self.assertEqual(sites(DELEGATING),
                         [("__init__", "kept", "r", "parameter")])

    # ── filter 1: only a MULTI-FIELD struct's frame address counts ────────
    def test_a_one_field_structs_parameter_is_not_a_frame_holder(self):
        """`self.n = s.only` reads a one-field struct; it is not a site.

        A one-field struct has no frame at all, so its value is a word and the
        store is a word store. Keeping this row would put a case in the census
        that no call site can ever be unsound about, and the count is already an
        upper bound for a different reason (`FILES BLOCKED`'s own warning).
        """
        self.assertEqual(sites(STRUCTS), [])

    def test_a_one_field_struct_constructed_here_is_not_a_frame_holder(self):
        """The same filter on the CONSTRUCTION arm: `var w = Single()`.

        Both filters are named in the tool's docstring because they are the two
        ways to be wrong in the direction that invents sites, and this is the
        construction half of the one-field half.
        """
        self.assertEqual(sites(STRUCTS + """
def take_it(h: Holder) -> Int:
    var w = Single()
    h.n = w.only
    return h.n
"""), [])

    # ── filter 2: a name this file cannot type is not a frame holder ─────
    def test_a_name_with_a_method_called_on_it_is_not_a_frame_holder(self):
        """`self.n = len(s)`: `s` is used as a value and holds no frame.

        This is the first cut's filter, and the one that reported 52 sites in 19
        files. `s` is unannotated, so the tool cannot type it, and the two
        filters together say a name it cannot type is not a site rather than
        guessing. The row below is the same statement with the method call on
        the right-hand side, which is the shape that actually occurs all over
        this repository's source.
        """
        self.assertEqual(sites(STRUCTS + """
def strip_it(h: Holder, text):
    h.n = text.strip()
    return h.n
"""), [])

    # ── a site whose value is neither a parameter nor a declared local ───
    def test_a_name_bound_by_assignment_is_a_site_and_is_neither_kind(self):
        """`h.kept = q` where `q` came from `q = Pair()`: a site, kind `other`.

        The construction arm of `frame_bound_names` fires on an `AssignStmt` as
        well as a `VarDecl`, while `local_names` reads only declarations — so a
        name bound that way IS a frame holder and is NOT a declared local, and
        the tool says `other` rather than guessing. That is the honest answer
        and it is the one real corpus site of this kind
        (`myinterpreter.py`'s `_invoke`: `interpreter.scope = func_scope`).
        """
        self.assertEqual(sites("""\
struct Pair:
    var a: Int
    var b: Int

struct Holder:
    var kept: Pair
    var n: Int

def store(h: Holder) -> Int:
    q = Pair()
    h.kept = q
    return h.n
"""), [("store", "kept", "q", "other")])

    # ── the two corpus rows, read off the REAL tree ─────────────────────
    def _corpus_sites(self, relpath, member):
        path = relpath if os.path.isabs(relpath) else os.path.join(
            HERE, relpath)
        rows = []
        C.scan(path, rows)
        return [(fn, m, value, kind) for _p, fn, _line, m, value, kind in rows
                if m == member]

    def test_this_repositorys_one_non_parameter_site_is_still_reported(self):
        """`myinterpreter.py`'s `_invoke` writes `interpreter.scope =
        func_scope`, and `func_scope` is neither a parameter of that method nor
        a declared local — the `other` row, and the one that says the count is
        read off declarations and not off the holder set the refusal uses.
        """
        got = self._corpus_sites("myinterpreter.py", "scope")
        self.assertEqual(got, [("_invoke", "scope", "func_scope", "other")])

    def test_the_stdlibs_delegating_constructor_is_still_a_parameter_site(self):
        """`collections/span.mojo`'s `__init__` stores its own `src` parameter.

        Read off the real stdlib rather than written here, because the claim the
        census's number rests on is about THAT file: a delegating constructor in
        the standard library, not a shape invented for a test. Skipped when the
        stdlib is not on this machine — the census itself skips it, and a test
        that failed for a missing directory would be a failure about the
        checkout rather than about the instrument.
        """
        try:
            from module_loader import STDLIB_PATH
        except Exception:                       # pragma: no cover
            self.skipTest("module_loader cannot name the stdlib")
        std = os.path.join(STDLIB_PATH, "std")
        if not os.path.isdir(std):              # pragma: no cover
            self.skipTest(f"no stdlib at {std}")
        rows = []
        C.scan(os.path.join(std, "collections", "span.mojo"), rows)
        got = [(fn, m, value, kind) for _p, fn, _line, m, value, kind in rows
               if m == "src"]
        self.assertEqual(got, [("__init__", "src", "src", "parameter")])


if __name__ == "__main__":
    unittest.main()