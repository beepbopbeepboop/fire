#!/usr/bin/env python3
"""Wave-2c: make underscore names resolve in mojo/middle modules.

`from X import *` skips `_foo`. Several extracted functions reference
underscore helpers from types/exprtypes/solvers (and peer shared modules).
This script:

  1. Builds a provider map: name -> module that defines it (middle/* first,
     then gimple_codegen constants).
  2. Free-var scans each mojo/middle/*.py function.
  3. Appends an explicit `from provider import name, ...` block for anything
     still free (excluding known false positives).
  4. Repeats until fixpoint (deps of deps).
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIDDLE = ROOT / "mojo" / "middle"

# False positives: walrus targets, except-as, nested imports, etc.
KNOWN_FP = {
    "_mlmod", "_imp", "_glob", "_re", "elaborate", "copy",
    "self", "cls", "True", "False", "None", "annotations",
}

# Search order for providers
PROVIDER_CANDIDATES = [
    MIDDLE / "types.py",
    MIDDLE / "exprtypes.py",
    MIDDLE / "solvers.py",
    MIDDLE / "coro.py",
    MIDDLE / "infra_infer.py",
    MIDDLE / "resolve_shared.py",
    MIDDLE / "funcs_shared.py",
    MIDDLE / "module_shared.py",
    MIDDLE / "stmts_shared.py",
    MIDDLE / "calls_shared.py",
    MIDDLE / "loops_shared.py",
    MIDDLE / "methods_shared.py",
    ROOT / "gimple_codegen.py",
]


def toplevel_defs(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return set()
    names: set[str] = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
        return_ = names  # noqa
    return names


def build_provider_map() -> dict[str, Path]:
    prov: dict[str, Path] = {}
    for p in PROVIDER_CANDIDATES:
        if not p.exists():
            continue
        for name in toplevel_defs(p):
            prov.setdefault(name, p)
    return prov


def module_path_to_dotted(path: Path) -> str:
    rel = path.relative_to(ROOT)
    return str(rel.with_suffix("")).replace("/", ".")


def free_names(func: ast.FunctionDef | ast.AsyncFunctionDef, bound: set[str]) -> set[str]:
    local: set[str] = set()
    a = func.args
    for arg in (
        list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
        + ([a.vararg] if a.vararg else [])
        + ([a.kwarg] if a.kwarg else [])
    ):
        local.add(arg.arg)
    for sub in ast.walk(func):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            local.add(sub.id)
        if isinstance(sub, ast.arg):
            local.add(sub.arg)
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and sub is not func:
            local.add(sub.name)
        if isinstance(sub, ast.ExceptHandler) and sub.name:
            local.add(sub.name)
        if isinstance(sub, ast.alias):
            local.add(sub.asname or sub.name.split(".")[0])
        if isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
            local.add(sub.target.id)
        if isinstance(sub, ast.Global):
            local.update(sub.names)
    free: set[str] = set()
    for sub in ast.walk(func):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            nid = sub.id
            if nid in local or nid in bound or nid in KNOWN_FP:
                continue
            if nid.startswith("__"):
                continue
            if nid in dir(builtins):
                continue
            free.add(nid)
    return free


def already_imported(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name != "*":
                    names.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
    return names


def star_modules(tree: ast.Module) -> list[str]:
    mods = []
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names):
            if n.module:
                mods.append(n.module)
    return mods


def star_exported(dotted: str) -> set[str]:
    """Names actually exported by star-import of dotted module (public only)."""
    path = ROOT / Path(*dotted.split(".")).with_suffix(".py")
    if not path.exists():
        return set()
    return {n for n in toplevel_defs(path) if not n.startswith("_")}


def main() -> int:
    prov = build_provider_map()
    print(f"provider map: {len(prov)} names")

    # Fixpoint: up to 8 rounds
    for round_i in range(1, 9):
        added_any = False
        for path in sorted(MIDDLE.glob("*.py")):
            if path.name == "__init__.py":
                continue
            text = path.read_text()
            tree = ast.parse(text, filename=str(path))

            bound = already_imported(tree)
            for sm in star_modules(tree):
                bound |= star_exported(sm)
            # Also: globals().update patterns in originals don't apply here

            needed: dict[str, str] = {}  # name -> dotted provider
            for n in tree.body:
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for name in free_names(n, bound):
                    if name in prov:
                        dotted = module_path_to_dotted(prov[name])
                        # Don't import from self
                        if dotted == module_path_to_dotted(path):
                            # defined later in same file (dep order) — ensure it's in bound next round
                            # if truly later toplevel, it's already in already_imported
                            continue
                        needed[name] = dotted
                    else:
                        print(f"  R{round_i} NO PROVIDER {path.name}::{n.name} needs {name}")

            if not needed:
                continue

            # Group by provider
            by_prov: dict[str, list[str]] = {}
            for name, dotted in needed.items():
                by_prov.setdefault(dotted, []).append(name)

            # Append import block if not already present
            lines_out = []
            existing = text
            to_add = []
            for dotted, names in sorted(by_prov.items()):
                for name in sorted(names):
                    # check if already imported this name from anywhere
                    if name in already_imported(tree):
                        continue
                    # check if a line already imports it
                    if re_search_import(existing, name, dotted):
                        continue
                    to_add.append((dotted, name))

            if not to_add:
                continue

            block = [
                "",
                f"# --- explicit underscore/shared imports (wave2c r{round_i}) ---",
            ]
            # group consecutive same-provider
            cur = None
            buf: list[str] = []
            groups: list[tuple[str, list[str]]] = []
            for dotted, name in to_add:
                if dotted != cur:
                    if cur is not None:
                        groups.append((cur, buf))
                    cur = dotted
                    buf = [name]
                else:
                    buf.append(name)
            if cur is not None:
                groups.append((cur, buf))

            for dotted, names in groups:
                block.append(f"from {dotted} import {', '.join(names)}")

            with path.open("a") as f:
                f.write("\n" + "\n".join(block) + "\n")
            print(
                f"  R{round_i} {path.name}: +{len(to_add)} imports "
                f"({', '.join(sorted(n for _, n in to_add))})"
            )
            added_any = True

        if not added_any:
            print(f"fixpoint at round {round_i}")
            break

    # Final report
    print("\n=== Final free-var check ===")
    bad = 0
    for path in sorted(MIDDLE.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text())
        bound = already_imported(tree)
        for sm in star_modules(tree):
            bound |= star_exported(sm)
        # multi-round: also treat any from-import in file as bound (already)
        # plus names defined anywhere in file (already in already_imported for toplevel)
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            free = free_names(n, bound)
            # one more pass: names defined later/earlier in file are in already_imported
            # names from peer modules imported at bottom — reparse
            if free:
                # re-check after reload of full bound including bottom imports
                pass
        # Full re-parse bound including appended imports
        text = path.read_text()
        tree = ast.parse(text)
        bound = already_imported(tree)
        for sm in star_modules(tree):
            bound |= star_exported(sm)
        # ALL from-imports any position
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name != "*":
                        bound.add(a.asname or a.name)
            if isinstance(n, ast.Import):
                for a in n.names:
                    bound.add(a.asname or a.name.split(".")[0])
        # ALL toplevel defs (any order)
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(n.name)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        bound.add(t.id)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                bound.add(n.target.id)
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            free = free_names(n, bound)
            if free:
                bad += 1
                print(f"  STILL {path.name}::{n.name}: {sorted(free)}")
    if bad == 0:
        print("  clean")
    return 1 if bad else 0


def re_search_import(text: str, name: str, dotted: str) -> bool:
    import re
    # from dotted import ... name ...
    for m in re.finditer(rf"^from\s+{re.escape(dotted)}\s+import\s+(.+)$", text, re.M):
        parts = [p.strip().split(" as ")[0].strip() for p in m.group(1).split(",")]
        if name in parts:
            return True
    # from anywhere import name
    for m in re.finditer(r"^from\s+[\w.]+\s+import\s+(.+)$", text, re.M):
        parts = [p.strip().split(" as ")[0].strip() for p in m.group(1).split(",")]
        if name in parts:
            return True
    # import dotted as ...
    if re.search(rf"^import\s+{re.escape(dotted)}\b", text, re.M):
        # attribute access only — still need name
        pass
    return False


if __name__ == "__main__":
    sys.exit(main())
