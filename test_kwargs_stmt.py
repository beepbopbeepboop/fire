#!/usr/bin/env python3
"""Minimal test case for kwargs in statement-level function calls."""

def my_func(a, b=10):
    return a + b

def test():
    x = 5
    # This should pass x and 20 as arguments, but _gen_stmt_ExprStmt might not handle kwargs
    my_func(x, b=20)  # ExprStmt containing CallExpr with kwargs
    print("done")

test()
