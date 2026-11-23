#!/usr/bin/env python3
"""Regression: the per-step `hval` simp sets must carry the `hmem` fact.

Bug: FORMAL_x86_endtoend_memory_ceiling.

For EVERY step whose FORM writes only registers, `emit_terminates` proves
`hmem{k+1} : s{k+1}.mem = s{k}.mem` and emits it, and then proves the step's
`hval{k+1}` — the one the decided-branch side condition feeds — over the
successor's memory reads.  The `hval` simp set, however, named only the
successor's equation (`hs{k+1}`), the previous value fact (`hval{k}`) and the
accessor defs, so a goal like

    mem_read_bytes s{k+1}.mem <cell> 8 = <literal>

had no rewrite that could take it through the unchanged memory to the read the
previous fact already states.  `simp` therefore re-normalised the nested
`mem_write_bytes` `ite` chain at every level — the exact term the
single-`simp` strategy died on — and the proof files for `wide_expr`,
`wide_recv` and `list_literal_index` peaked at 6–7 GB, over the `-M 6144` the
runner gives a generated proof, and never elaborated.

The fix: thread the `hmem{k+1}` fact the step just emitted into the `hval`
simp set, so a memory projection collapses to the previous state's read in one
step instead of re-normalising the chain.

This test does NOT build a proof or run Lean.  It generates the text for one of
the three memory-ceiling files and checks that each `hval{k}` that has an
`hmem{k}` predecessor names it in its `simp` set.  It fails before the fix (no
`hmem` in the simp sets) and passes after.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal.x86_64_endtoend_test as E


#: The three files the bug names; each is checked because each has a different
#: path shape (a plain chain, a call that returns, and a list index).
MEMORY_CEILING_EXAMPLES = (
    "early_ret.mojo",
    "wide_expr.mojo",
    "list_literal_index.mojo",
)


def _hmem_indices(lines):
    """Every `k` for which the text proves `have hmem{k} : …`."""
    return {int(m.group(1))
            for m in (re.match(r"\s*have hmem(\d+) :", line) for line in lines)
            if m}


def _hval_simp_sets(lines):
    """`[(k, the simp line proving hval{k})]` for every `have hval{k}`.

    The statement of a `have hval{k}` can span many lines (the conjunction of
    every tracked field), so `:= by` and the proof's `simp [...]` are found by
    scanning forward until the first `simp [` line, which is the fact's own
    simp set (the peel's later `<;> simp [hval{k-1}]` is a second line and is
    not the one this test is about).
    """
    out = []
    for i, line in enumerate(lines):
        m = re.match(r"\s*have hval(\d+) :", line)
        if not m:
            continue
        k = int(m.group(1))
        for j in range(i + 1, len(lines)):
            if "simp [" in lines[j]:
                out.append((k, lines[j]))
                break
            # A malformed fact with no proof: stop rather than pick a later one.
            if re.match(r"\s*(have|obtain|exact|apply) ", lines[j]):
                break
    return out


class TestHvalSimpSetsCarryHmem(unittest.TestCase):
    def _check(self, filename):
        path = os.path.join(E.HERE, "examples", filename)
        text = E.emit_terminates(path)
        lines = text.split("\n")
        hmem = _hmem_indices(lines)
        sets = _hval_simp_sets(lines)
        self.assertTrue(sets, "%s: emit_terminates produced no `hval` facts" % filename)
        checked = 0
        for k, simp_line in sets:
            if k == 0:
                continue                    # `hval0` is the initial state; no `hmem`
            if k not in hmem:
                continue                    # a store step: the peel covers it
            self.assertIn("hmem%d" % k, simp_line,
                          "%s: `hval%d`'s simp set does not carry `hmem%d`; the "
                          "memory read has no route to the previous fact, so "
                          "`simp` re-normalises the `mem_write_bytes` chain — "
                          "the FORMAL_x86_endtoend_memory_ceiling regression.\n"
                          "  simp line: %s" % (filename, k, k, simp_line.strip()))
            checked += 1
        self.assertTrue(
            checked,
            "%s: no `hval{k}` with an `hmem{k}` predecessor was found, so this "
            "test checked nothing.  Pick an example with a register-only step "
            "that emits both facts." % filename)

    def test_early_ret(self):
        self._check("early_ret.mojo")

    def test_wide_expr(self):
        self._check("wide_expr.mojo")

    def test_list_literal_index(self):
        self._check("list_literal_index.mojo")


if __name__ == "__main__":
    unittest.main()
