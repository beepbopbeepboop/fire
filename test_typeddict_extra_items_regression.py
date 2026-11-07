#!/usr/bin/env python3
"""Regression: PEP 728 TypedDict typed extra items (PYTHON3.15_typeddict_extra_items).

The parser used to consume and discard class keyword arguments in the base
list (e.g. extra_items=bool, closed=True), so the AST and interpreter never
saw them. PEP 728's extra_items/closed must reach class creation.
"""
from __future__ import annotations

import os
import subprocess
import sys

import fire_compiler as N


def _parse_one(source):
    return N.Parser(N.py_tokenize(source)).parse_module()[0]


def test_parser_preserves_class_keywords():
    node = _parse_one(
        "class Movie(TypedDict, extra_items=bool, closed=True):\n"
        "    name: str\n"
    )
    assert isinstance(node, N.StructDef), node
    assert node.bases == ["TypedDict"], node.bases
    kws = {k: v for k, v in node.keywords}
    assert set(kws) == {"extra_items", "closed"}, node.keywords
    assert isinstance(kws["extra_items"], N.IdentExpr)
    assert kws["extra_items"].name == "bool"
    assert isinstance(kws["closed"], (N.BoolLiteral, N.IdentExpr)), kws["closed"]
    print("ok: parser preserves class keywords")


def test_interpreter_typed_dict_extra_items():
    src = (
        "from typing import TypedDict\n"
        "\n"
        "class Movie(TypedDict, extra_items=bool):\n"
        "    name: str\n"
        "\n"
        "print(repr(getattr(Movie, '__extra_items__', 'MISSING')))\n"
    )
    path = os.path.join(os.path.dirname(__file__), ".tmp", "td_extra_items.mojo")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(src)
    r = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), "fire.py"),
         "run", path],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(__file__) or ".")
    out = (r.stdout + r.stderr).strip()
    assert r.returncode == 0, f"fire.py run failed ({r.returncode}):\n{out}"
    assert "<class 'bool'>" in r.stdout, f"expected __extra_items__ bool, got:\n{out}"
    assert "MISSING" not in r.stdout, f"extra_items was lost:\n{out}"
    print("ok: interpreter preserves TypedDict extra_items")


def main():
    test_parser_preserves_class_keywords()
    test_interpreter_typed_dict_extra_items()
    print("PASS: TypedDict extra_items regression")


if __name__ == "__main__":
    main()
