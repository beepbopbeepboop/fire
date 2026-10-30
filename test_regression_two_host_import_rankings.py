#!/usr/bin/env python3
"""Regression: the shapes tool's `reach` / `alone` columns are the WALL tool's.

`tools/formal_host_import_shapes.py` absorbed `tools/formal_host_import_wall.py`'s
two columns. They must be the same numbers the wall prints for the same module,
computed over the wall's own corpus — not over the sweep's blocked files for that
module, which is a different question under the same name (measured before this
was pinned: `copy` 7 vs 297, `builtins` 3 vs 35).

    python3 test_regression_two_host_import_rankings.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import formal_host_import_shapes as S
import tools.formal_host_import_wall as W


def test_reach_and_alone_are_the_wall_tools():
    sweep = S.default_sweep()
    if not sweep or not os.path.isfile(sweep):
        raise AssertionError("no sweep log")
    rows, _, _ = S.rows_for(sweep, min_files=1)
    assert rows, "no host-import rows"
    wall = W.default_rank()
    for r in rows:
        info = wall.get(r["name"], {"reach": [], "alone": []})
        assert r["reach"] == len(info["reach"]), (
            f"{r['name']}: shapes reach {r['reach']} != wall {len(info['reach'])}")
        assert r["alone"] == len(info["alone"]), (
            f"{r['name']}: shapes alone {r['alone']} != wall {len(info['alone'])}")


def test_reach_is_over_the_corpus_not_the_sweep_files():
    # The property that was broken: a closure reaches files the sweep never
    # blocked on, so for some row `reach` must exceed `files`.
    sweep = S.default_sweep()
    rows, _, _ = S.rows_for(sweep, min_files=1)
    assert any(r["reach"] > r["files"] for r in rows), (
        "every row's reach is bounded by its sweep files: the columns were "
        "computed over the subset again")


if __name__ == "__main__":
    test_reach_and_alone_are_the_wall_tools()
    test_reach_is_over_the_corpus_not_the_sweep_files()
    print("PASS: shapes reach/alone are the wall tool's, over its corpus")
