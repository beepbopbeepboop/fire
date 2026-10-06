#!/usr/bin/env python3
"""The declared-parameter census tool is a MEASUREMENT, so the measurement is
pinned — case by case, on sources with known answers.

    python3 test_formal_declared_param_census.py [-v]

`tools/formal_declared_param_census.py` is the instrument behind row B of
`“FORMAL_receiver_stored_in_a_field: a frame address in a struct field”` and behind
`bugs/FORMAL_declared_parameter_against_its_call_sites.md`: it reads one `.mojo`
file, finds the parameters whose declared type is a struct of that file, and
reports the ones where EVERY call site in that file hands over something else —
which is exactly the shape `model.frame_declared_parameter_refusal` refuses.

**Why its answers have to be pinned, and the specific failure this file exists
for.** A census that cannot tell "the call site contradicts the declaration"
from "this instrument cannot read the call site" reports its own blindness as a
program bug, and the first version of this tool did: it decided **nothing**, so
its DECIDED section was structurally empty and every row sat in a MAYBE bucket
whose text was really a confession. Reading a `List[T]`'s element type, a field's
declared type, a class `comptime` alias's initialiser, a callee's declared return
type, a method's receiver and a function's own scope turns most of that into
verdicts — and every one of those six readers is a way to be wrong in the
direction that invents bugs, so each is a case here.

Two rows are pinned from the REAL corpus rather than from a source written for
the test, because they are the two the fix found and the reason to believe it:

    std/simd.mojo        _modf_scalar(x: Scalar) calls _floor(x), declared `x: SIMD`
    std/utils/index.mojo IndexList.__eq__ passes self.data, a StaticTuple, to
                         _int_tuple_compare, declared `a: IndexList` — and that
                         function's OWN docstring says `var a: StaticTuple`

Both are DECIDED, and both are stdlib declaration bugs rather than backend gaps,
which is the answer `“FORMAL_receiver_stored_in_a_field: a frame address in a struct field”` §3 asks for. They
are asserted as "decided, with this shape", not as a count over the corpus: a
count goes stale the moment an unrelated header grows a function, and a stale
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

import formal_declared_param_census as C   # noqa: E402


def verdicts(source):
    """`(callee, parameter, struct, n sites, [why, …])` for one source's rows.

    Goes through the tool's own `scan` and `candidates`, so what is asserted is
    what the census prints — not a re-derivation of it, which is how an
    instrument and its test come to disagree about what they measured.
    """
    tmp = tempfile.mkdtemp(prefix='declared_param_census_')
    path = os.path.join(tmp, 'case.mojo')
    with open(path, 'w') as f:
        f.write(source)
    rows, parsed = [], {}
    C.scan(path, rows, parsed)
    out, _groups = C.candidates(parsed, rows)
    return {(callee, pname, struct): (n, whys)
            for _p, callee, pname, struct, n, whys in out}


# A struct with two fields, so `frame` counts are distinguishable, and a second
# one with the same field count, so the "same layout" bucket has something to
# bite on.
BOX = """\
struct Box:
    var a: Int
    var b: Int

struct Other:
    var c: Int
    var d: Int

def take(x: Box) -> Int:
    return x.a
"""


class TestDeclaredParamCensus(unittest.TestCase):
    maxDiff = None

    # ── the reader's decidable shapes ─────────────────────────────────────
    def test_a_declared_element_type_decides_a_subscript(self):
        """`List[Box]` states what `xs[0]` is, so the row is decidable.

        Before this reader existed this was the instrument's largest MAYBE
        family, and `benchmark.mojo`'s `report.runs[i]` handed to a parameter
        declared `Batch` is the shape: the element type is the whole question,
        and nothing here derived it, so the row could not be read either way.
        """
        self.assertEqual(verdicts(BOX + """
def take_all(xs: List[Box]) -> Int:
    return take(xs[0])
"""), {})

    def test_a_subscript_of_a_list_of_something_else_is_a_DECIDED_disagreement(self):
        self.assertEqual(verdicts(BOX + """
def take_wrong(xs: List[Other]) -> Int:
    return take(xs[0])
"""), {("take", "x", "Box"): (1, ["DISAGREES a value of Other"])})

    def test_a_field_declared_type_decides_a_field_read(self):
        self.assertEqual(verdicts(BOX + """
struct Holder:
    var kept: Box
    var other: Other

def read_it(h: Holder) -> Int:
    return take(h.kept)
"""), {})

    def test_a_field_read_of_another_type_is_DECIDED(self):
        self.assertEqual(verdicts(BOX + """
struct Holder:
    var kept: Box
    var other: Other

def read_it(h: Holder) -> Int:
    return take(h.other)
"""), {("take", "x", "Box"): (1, ["DISAGREES a value of Other"])})

    def test_a_class_comptime_alias_is_a_value_of_its_class(self):
        """`ControlOffset.ready_flag` is `Self(0)` by its own initialiser.

        `sys/_amdgpu.mojo` spells four calls this way and every one of them was a
        MAYBE for this instrument — a field access on the NAME of a struct, which
        no parameter or binding ever binds.
        """
        self.assertEqual(verdicts("""\
struct Flag:
    var value: Int
    comptime ready = Self(0)

def read_flag(f: Flag) -> Int:
    return f.value
"""), {})

    def test_a_callees_declared_return_type_decides_a_call(self):
        self.assertEqual(verdicts(BOX + """
def make() -> Box:
    return Box()

def use_it() -> Int:
    return take(make())
"""), {})

    def test_a_call_returning_another_type_is_DECIDED(self):
        self.assertEqual(verdicts(BOX + """
def make_other() -> Other:
    return Other()

def use_it() -> Int:
    return take(make_other())
"""), {("take", "x", "Box"): (1, ["DISAGREES a value of Other"])})

    # ── the reader's UNdecidable shapes, which must stay undecided ───────
    def test_an_unannotated_name_stays_a_maybe(self):
        # A source of its own, because a row is dropped when ANY site agrees.
        self.assertEqual(verdicts("""\
struct Box:
    var a: Int
    var b: Int

def take(x: Box) -> Int:
    return x.a

def use_it(raw) -> Int:
    return take(raw)
"""), {("take", "x", "Box"): (1, ["MAYBE a name whose type this file does "
                                  "not state"])})

    def test_a_subscript_of_a_container_with_no_element_type_stays_a_maybe(self):
        self.assertEqual(verdicts(BOX + """
def take_all(xs: List) -> Int:
    return take(xs[0])
"""), {("take", "x", "Box"): (1, ["MAYBE a subscript"])})

    def test_a_call_to_a_callee_this_file_does_not_define_is_unread(self):
        self.assertEqual(verdicts(BOX + """
def use_it() -> Int:
    return take(from_elsewhere())
"""), {("take", "x", "Box"): (1, ["UNREAD a call to from_elsewhere()"])})

    # ── the three readers that were WRONG before, each in one case ───────
    def test_a_method_receiver_is_a_value_of_its_own_struct(self):
        """`self` is a value of ITS OWN struct inside a method, and no other.

        This is the false positive the first version of this tool could not see:
        it marked `self` as a value of every struct in the file because ONE
        method in `python_object.mojo` writes `self = Self(None)`, so eleven rows
        across six files were reported that are not contradictions at all.

        Both halves are here, and they are two sources rather than one because a
        row is dropped when ANY site agrees: "the receiver is a value of its
        class" and "the receiver is a value of anything" are the same rule
        pointed both ways, and only the first one is true.
        """
        self.assertEqual(verdicts("""\
struct Box:
    var a: Int
    var b: Int
    def rewrap(self) -> Int:
        return take(self) + self.a

def take(x: Box) -> Int:
    return x.a
"""), {})
        self.assertEqual(verdicts("""\
struct Box:
    var a: Int
    var b: Int

def take(x: Box) -> Int:
    return x.a

struct Sized:
    var n: Int
    def total(self) -> Int:
        return take(self) + self.n
"""), {("take", "x", "Box"): (1, ["DISAGREES a value of Sized"])})

    def test_a_name_is_typed_by_ITS_OWN_function_not_by_the_file(self):
        """`simd.mojo` has `_convert_float8_to_f32`'s `val: SIMD` and a nested
        `def wrapper_fn(…)(val: Scalar[…])`. One file-wide table binds `val` to
        whichever came first and then calls a SIMD argument a Scalar.

        And the converse: a name the enclosing function binds but cannot type is
        answered HERE, not by the file's table — `pointer.mojo`'s `var base =
        offset.cast[.int]().fma(…)` is a `SIMD` by its own statement, and a
        `Some` construction bound to `base` elsewhere in the file.
        """
        self.assertEqual(verdicts(BOX + """
def outer(val: Box) -> Int:
    var base = val
    return take(base) + base.a

def elsewhere() -> Int:
    var base = Other()
    return base.c
"""), {})

    def test_a_method_called_without_its_receiver_does_not_shift_the_arguments(self):
        """`gather[alignment=…](base, mask, default)` inside the class passes the
        receiver IMPLICITLY (`@__allow_legacy_custom_self_type`, and
        `formal/build.py`'s `_receiverless_methods` is the build's half). Reading
        `args[0]` as the receiver reported the method's own first real argument
        as a `Pointer`.
        """
        self.assertEqual(verdicts(BOX + """
struct Bag:
    var kept: Box
    def take_first(self) -> Int:
        return take(self.kept)
    def take_it(b) -> Int:
        return take(b)
"""), {})

    # ── the two rows the reader found, read off the REAL corpus ──────────
    def _corpus_row(self, relpath, callee, pname, struct_name):
        from module_loader import STDLIB_PATH
        path = os.path.join(STDLIB_PATH, "std", relpath)
        rows, parsed = [], {}
        C.scan(path, rows, parsed)
        out, _groups = C.candidates(parsed, rows)
        for _p, c, p, s, n, whys in out:
            if (c, p, s) == (callee, pname, struct_name):
                return n, whys
        self.fail(f"{relpath}: no row for {callee}({pname}: {struct_name}); "
                  f"rows are {[(c, p, s) for _p, c, p, s, _n, _w in out]}")

    def test_simd_modf_scalar_hands_a_Scalar_to_a_SIMD_parameter(self):
        """A REAL disagreement, in the stdlib: `_modf_scalar(x: Scalar)` calls
        `_floor(x)`, which declares `x: SIMD`. Whether upstream Mojo accepts the
        widening is a question about its type system; that this instrument can
        now STATE the disagreement is the point, and it is why the row is a
        DECIDED one rather than a MAYBE.
        """
        n, whys = self._corpus_row("simd.mojo", "_floor", "x", "SIMD")
        self.assertEqual(n, 1)
        self.assertEqual(whys, ["DISAGREES a value of Scalar"])

    def test_index_int_tuple_compare_declares_an_IndexList_and_is_handed_a_StaticTuple(self):
        """A REAL disagreement, and one the source itself contradicts:
        `_int_tuple_compare`'s first parameter is declared `a: IndexList` while
        its own docstring's example is `var a: StaticTuple[Int, size]`, and all
        five of its call sites hand it `IndexList.data`, a
        `StaticTuple[Self._int_type, Self.size]`.
        """
        n, whys = self._corpus_row("utils/index.mojo", "_int_tuple_compare",
                                   "a", "IndexList")
        self.assertEqual(n, 5)
        self.assertEqual(whys, ["DISAGREES a value of StaticTuple"] * 5)


if __name__ == '__main__':
    unittest.main()