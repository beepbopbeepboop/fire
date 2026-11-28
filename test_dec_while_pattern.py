#!/usr/bin/env python3
"""Regression for `formal.arm64_proof_gen._dec_while_pattern`.

The recognizer gates a TOTAL closed-form model (`_gen_go`: a signed-positive
seed counts down to 0) and a `rfl` AST bridge stated about exactly
`while cond [p := p - 1]` (`_gen_dec_while_block`).  So recognition is only
sound for the single net decrement by one: any wider match makes the emitted
theorem about a different program.

This pins both halves:
  * the equivalent spellings that MUST match — the canonical `p = p - 1`, the
    augmented `p -= 1` (which `_stmts_ast` desugars to the identical node), and
    the `!= 0` / `>= 1` conditions; and
  * the variants that MUST be refused — a decrement by 2 (never reaches 0),
    an extra/conditional statement around the decrement, a non-decrement, and
    a reversed condition (the AST and the signed model differ).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fire_compiler as F
import formal.arm64_proof_gen as G


def _fn(src):
    return F.Parser(F.py_tokenize(src)).parse_module()[0]


ACCEPT = {
    # canonical
    "canon": "def f(p):\n    while p > 0:\n        p = p - 1\n    return p\n",
    # augmented assignment: same AST node after `_stmts_ast`'s desugar
    "augassign": "def f(p):\n    while p > 0:\n        p -= 1\n    return p\n",
    # equivalent "counter nonzero" conditions
    "ne": "def f(p):\n    while p != 0:\n        p = p - 1\n    return p\n",
    "ge": "def f(p):\n    while p >= 1:\n        p = p - 1\n    return p\n",
}

REFUSE = {
    # decrement by 2: the loop does not reach 0, so `_go` (0 for a
    # signed-positive seed) is a false model
    "dec2": "def f(p):\n    while p > 0:\n        p = p - 2\n    return p\n",
    "augdec2": "def f(p):\n    while p > 0:\n        p -= 2\n    return p\n",
    # extra statement: the post-body environment differs from `envOf (m - 1)`
    "extra": ("def f(p):\n    while p > 0:\n        q = 1\n"
              "        p = p - 1\n    return p\n"),
    # conditional around the decrement
    "cond": ("def f(p):\n    while p > 0:\n        if p > 5:\n            q = 1\n"
             "        p = p - 1\n    return p\n"),
    # wrong direction
    "add": "def f(p):\n    while p > 0:\n        p = p + 1\n    return p\n",
    "augadd": "def f(p):\n    while p > 0:\n        p += 1\n    return p\n",
    # reversed operand order: `ast` is `binop "<" (int 0) (var p)`, which the
    # `rfl` bridge is not stated about, and the signed model differs
    "rev": "def f(p):\n    while 0 < p:\n        p = p - 1\n    return p\n",
    # must return the counter
    "retp1": "def f(p):\n    while p > 0:\n        p = p - 1\n    return p + 1\n",
}


def test_accepts_canonical_spellings():
    for name, src in ACCEPT.items():
        got = G._dec_while_pattern(_fn(src))
        assert got == "p", f"{name}: expected 'p', got {got!r}"
    print(f"PASS: accepted {len(ACCEPT)} canonical spellings")


def test_refuses_unsound_variants():
    for name, src in REFUSE.items():
        got = G._dec_while_pattern(_fn(src))
        assert got is None, (
            f"{name}: _dec_while_pattern matched {got!r}, but the closed-form "
            f"model / AST bridge is not valid for this shape")
    print(f"PASS: refused {len(REFUSE)} unsound variants")


if __name__ == "__main__":
    test_accepts_canonical_spellings()
    test_refuses_unsound_variants()
