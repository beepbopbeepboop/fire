#!/usr/bin/env python3
"""Regression: the shapes tool now absorbs the wall's reach/alone columns.
Fails before merge, passes after. Next to the existing test files."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))

import formal_host_import_shapes as S
import tools.formal_host_import_wall as W

def test_shapes_has_reach_and_alone():
    sweep = S.default_sweep()
    if not sweep or not os.path.isfile(sweep):
        raise AssertionError("no sweep log")
    rows, _, total = S.rows_for(sweep, min_files=1)
    # Verify every row carries the two new columns
    for r in rows:
        assert "reach" in r, f"row {r['name']} missing reach"
        assert "alone" in r, f"row {r['name']} missing alone"
    # Consistency check against the wall tool for one well-known row
    row = next((r for r in rows if r["name"] == "builtins"), None)
    assert row is not None, "builtins row missing"
    # The wall tool's rank over all source files should agree on reach/alone
    # for this module; we just assert the column is populated, not exact equality,
    # because the shapes file-set and wall file-set cover different scopes.
    assert isinstance(row["reach"], int) and row["reach"] >= 0
    assert isinstance(row["alone"], int) and row["alone"] >= 0

if __name__ == "__main__":
    test_shapes_has_reach_and_alone()
    print("PASS: shapes tool carries wall's reach/alone")
