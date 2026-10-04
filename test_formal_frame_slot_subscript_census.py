#!/usr/bin/env python3
"""The frame-slot subscript census is a MEASUREMENT, so its filters are pinned —
one case each, and each case that filter is what separates.

    python3 test_formal_frame_slot_subscript_census.py [-v]

`tools/formal_frame_slot_subscript_census.py` answers the question
`formal/model.py`'s `frame_slot_element_refusal` needs answered before its set
may be widened: how many corpus subscripts take a FRAME-valued struct FIELD as
their base, and which. It is the instrument behind that refusal's corpus row,
and an instrument whose filters are unpinned reports its own blindness as a fact
about the corpus — which is what `tools/formal_frame_field_census.py`'s own
docstring says happened to its first cut (52 sites reported, 28 of them words).

So each case here is a filter REMOVED:

  * the owner pairing — a method's `self.<field>` is that struct's field, and
    the pairing is structural (a method is a member of its StructDef), because a
    parsed tree has no lifted name to reconstruct it from;
  * `formal_frame_field_census.frame_bound_structs` — a local holding a
    multi-field struct's frame address, from a parameter's ANNOTATION or from a
    construction assigned to it;
  * the ONE-FIELD exclusion — a one-field struct's receiver is its field, so
    `q.<f>[i]` there is a word, and a word base is `int`, which the OTHER scalar
    gate refuses by a different sentence;
  * the CHAIN exclusion — `a.b.c[i]`'s outer field is the type of the WORD, not
    of whatever the word points at, so it is counted under neither kind;
  * and the container row, which is the one that must NOT be `frame`: a field
    declared `List[Int]` is a blob, and a refusal that reached it would refuse
    every `h.xs[i]` in the corpus.

No Lean, no build, no sweep: the instrument is a parse and a walk.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_frame_slot_subscript_census as C   # noqa: E402


def sites(source, name="case.mojo"):
    """`(spelled base, annotation, kind)` for every site one source yields.

    Goes through the tool's own `scan`, so what is asserted is what the census
    prints rather than a re-derivation of it.
    """
    tmp = tempfile.mkdtemp(prefix="frame_slot_subscript_census_")
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        f.write(source)
    rows = []
    C.scan(path, rows)
    return [(spelled, ann, kind) for _p, _fn, _line, spelled, ann, kind, _how
            in rows]


class TestFrameSlotSubscriptCensus(unittest.TestCase):

    def test_a_self_field_declared_a_framed_struct_is_a_frame(self):
        """The owner pairing, and the case the whole census is about.

        `Wrap.d`'s declared type is `Deep`, a two-field struct of THIS file, so
        the base is a frame address — and `model.frame_slot_element_refusal`
        exists to refuse exactly this.
        """
        self.assertEqual(
            sites("struct Deep:\n"
                  "    var x: Int\n"
                  "    var y: Int\n"
                  "\n"
                  "struct Wrap:\n"
                  "    var d: Deep\n"
                  "    var t: Int\n"
                  "\n"
                  "    def first(out self) -> Int:\n"
                  "        return self.d[0]\n"),
            [("self.d", "Deep", C.M.FRAME_KIND)])

    def test_a_frame_bound_local_is_a_frame(self):
        """`frame_bound_structs`, imported from the sibling census.

        `q` is a PARAMETER annotated with a multi-field struct of this file, so
        it holds that struct's frame address and `q.d` is a frame slot. Without
        this reader the row would read `unresolved` and the census would report
        a corpus the model does not have.
        """
        self.assertEqual(
            sites("struct Deep:\n"
                  "    var x: Int\n"
                  "    var y: Int\n"
                  "\n"
                  "struct Wrap:\n"
                  "    var d: Deep\n"
                  "    var t: Int\n"
                  "\n"
                  "def read(q: Wrap) -> Int:\n"
                  "    return q.d[0]\n"),
            [("q.d", "Deep", C.M.FRAME_KIND)])

    def test_a_one_field_receivers_field_is_not_a_frame(self):
        """The ONE-FIELD exclusion, which is what keeps a `self.<f>` word a word.

        A one-field struct's receiver IS its field (`model.one_word_receiver_kind`),
        so `self.only` holds the `Int` the declaration names and the base is a
        scalar — `int`, not `frame`. That is also the row
        `model.NON_CONTAINER_SLOT_KINDS` refuses by name, so the census has to be
        able to tell the two apart: both are scalar bases, one is refused and one
        is not, and a census that merged them could not say which.
        """
        self.assertEqual(
            sites("struct Single:\n"
                  "    var only: Int\n"
                  "\n"
                  "    def first(out self) -> Int:\n"
                  "        return self.only[0]\n"),
            [("self.only", "Int", C.M.INT_KIND)])

    def test_a_chain_is_counted_under_neither_kind(self):
        """The CHAIN exclusion, and the conservative direction it takes.

        `a.b.c`'s declared type is the type of the WORD `a.b`, not of whatever
        that word points at, so the census says so in words rather than resolving
        it and risking an invented frame. Every chain row carries this `how`,
        which is why it is the largest row in the table and not a frame bucket.
        """
        rows = sites("struct Deep:\n"
                     "    var x: Int\n"
                     "    var y: Int\n"
                     "\n"
                     "struct Mid:\n"
                     "    var d: Deep\n"
                     "\n"
                     "def read(m: Mid) -> Int:\n"
                     "    return m.d.x[0]\n")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0][2].startswith("a chain"))

    def test_a_container_field_is_a_list_and_never_a_frame(self):
        """The row the widening must NOT touch.

        `var xs: List[Int]` is a blob on this path, so `self.xs[i]` is the
        container reading and the right answer — which is why
        `model.FRAME_SLOT_ELEMENT_KINDS` is one kind and `self.xs` never reaches
        `frame_slot_element_refusal`.
        """
        self.assertEqual(
            sites("struct Bag:\n"
                  "    var xs: List[Int]\n"
                  "    var n: Int\n"
                  "\n"
                  "    def first(out self) -> Int:\n"
                  "        return self.xs[0]\n"),
            [("self.xs", "List[Int]", "list")])


if __name__ == "__main__":
    unittest.main(verbosity=2)