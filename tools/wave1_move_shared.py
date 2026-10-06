#!/usr/bin/env python3
"""Wave-1 restructure: move pure-shared gimple leaves into mojo/middle/.

  gimple_solvers.py    -> mojo/middle/solvers.py
  gimple_ctypes.py     -> mojo/middle/types.py
  gimple_exprtypes.py  -> mojo/middle/exprtypes.py

Leaves a compatibility shim at each old path so every existing
`import gimple_X` / `from gimple_X import Y` keeps working.
Rewrites gimple_* imports inside the moved files to the new dotted paths.
Idempotent: skips if destination already exists.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MOVES = [
    ("gimple_solvers", "mojo/middle/solvers.py", "mojo.middle.solvers"),
    ("gimple_ctypes", "mojo/middle/types.py", "mojo.middle.types"),
    ("gimple_exprtypes", "mojo/middle/exprtypes.py", "mojo.middle.exprtypes"),
]

OLD_TO_NEW = {old: dotted for old, _, dotted in MOVES}


def rewrite_imports(tree: ast.Module) -> ast.Module:
    class Rewriter(ast.NodeTransformer):
        def visit_Import(self, node: ast.Import) -> ast.Import:
            new_names = []
            for a in node.names:
                root = a.name.split(".")[0]
                if root in OLD_TO_NEW:
                    # import gimple_ctypes -> import mojo.middle.types as gimple_ctypes
                    new_names.append(
                        ast.alias(name=OLD_TO_NEW[root], asname=a.asname or root)
                    )
                else:
                    new_names.append(a)
            node.names = new_names
            return node

        def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
            if node.module and node.level == 0:
                root = node.module.split(".")[0]
                if root in OLD_TO_NEW:
                    node.module = OLD_TO_NEW[root]
            return node

    return Rewriter().visit(tree)


def make_shim(old: str, dotted: str) -> str:
    # Star import skips underscore names; dir() loop re-exports them so
    # `from gimple_ctypes import _mojo_type` keeps working.
    return (
        f'"""Compatibility shim - implementation moved to `{dotted}`.\n'
        f"\n"
        f"`import {old}` and `from {old} import ...` keep working.\n"
        f"Prefer `{dotted}` in new code.\n"
        f'"""\n'
        f"from {dotted} import *  # noqa: F401,F403\n"
        f"\n"
        f"import {dotted} as _impl\n"
        f"_g = globals()\n"
        f"for _k in dir(_impl):\n"
        f'    if _k.startswith("__"):\n'
        f"        continue\n"
        f"    _g[_k] = getattr(_impl, _k)\n"
        f"del _k, _g, _impl\n"
    )


def main() -> int:
    for old, new_rel, dotted in MOVES:
        src = ROOT / f"{old}.py"
        dst = ROOT / new_rel

        if dst.exists():
            # Destination already written; ensure shim exists/correct
            if src.exists() and "Compatibility shim" not in src.read_text()[:200]:
                src.write_text(make_shim(old, dotted))
                print(f"REFRESHED shim {old}.py -> {dotted} (dst already moved)")
            else:
                print(f"SKIP {old}: already at {new_rel}")
            continue

        if not src.exists():
            print(f"ERROR: missing source {src}", file=sys.stderr)
            return 1

        text = src.read_text()
        tree = ast.parse(text, filename=str(src))
        tree = rewrite_imports(tree)
        new_text = ast.unparse(tree)
        header = (
            f"# Moved from {old}.py - shared middle-end (mojo/middle).\n"
            f"# Import rewrite performed via AST; original docstring/comments preserved below.\n"
        )
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(header + new_text)
        print(f"MOVED {old}.py -> {new_rel} ({len(new_text.splitlines())} lines)")

        src.write_text(make_shim(old, dotted))
        print(f"SHIM  {old}.py re-exports {dotted}")

    for pkg in ("mojo", "mojo/middle", "mojo/backend_gimple"):
        p = ROOT / pkg / "__init__.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
