#!/usr/bin/env python3
"""Pinning regression for bug:TEST_budget_census_disagrees_on_formal_link_accounting.
Before the fix (census 2 vs walk 4) this failed; after (census 4 vs 4) it passes.
Written 2026-10-27."""
import ast, os
HERE = os.path.dirname(os.path.abspath(__file__))

def test_formal_link_accounting_census_matches_walk():
    path = os.path.join(HERE, 'test_formal_link_accounting.py')
    tree = ast.parse(open(path).read(), filename=path)
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == 'timeout' and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, int):
                    n += 1
    # Census row after fix: 4 (three compile-time 600s + one run 120s)
    assert n == 4, f'walk found {n} timeout literals, expected 4 (census 4)'
