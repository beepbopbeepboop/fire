#!/usr/bin/env python3
"""Wave-2b: pull missing module-level dependencies into the extracted shared modules.

After wave2_extract_shared.py, free-var analysis found these undefined names
(defined in the pre-wave2 originals but not copied along):

  infra_infer.py    <- gimple_gen_infra.py:     _FC_SEP, _POINTER_CTOR_NAMES
  resolve_shared.py <- gimple_gen_resolve.py:   KNOWN_LEAF_RETS, _collect_calls_in_stmt,
                                                _record_closure_alias
  funcs_shared.py   <- gimple_gen_funcs.py:     _selfhost_gen_self_param_ctype, _ris_base,
                                                _sgfs_resolve_ann, _scan_from_imports_flat
  module_shared.py  <- gimple_module_gen.py:    _SELFHOST_MODGLOBAL_CACHE, _UNKNOWN_FIELD_CTYPE,
                                                _gmi_as_str
  stmts_shared.py   <- gimple_gen_stmts.py:     _is_genexp
  methods_shared.py <- gimple_gen_methods.py:   _SELFHOST_SIBLING_MODULE_PREFIXES
  coro.py:                                       missing `import copy`

Strategy: copy the definition line-range from the PRE-wave2 original into the
shared module; leave a re-export in the original so remaining code there still
resolves (original already has `globals().update` from shared, but only for
names IN shared — so originals that still need these get them back via the
shared import which they already have). Also remove the definition from the
original to avoid dual-definition drift... actually keep original definitions
for names the original's remaining code uses, and have original import them
from shared. Simplest: put defs ONLY in shared; original already does
globals().update from shared, so remaining original code sees them.

False-positive free names (walrus/except/as) are ignored: _mlmod, _imp, _glob, _re, elaborate.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRE = Path("/tmp/gimple_pre_wave2")

# shared_module_path_rel -> (pre_original_filename, [names])
NEEDS = {
    "mojo/middle/infra_infer.py": (
        "gimple_gen_infra.py",
        ["_FC_SEP", "_POINTER_CTOR_NAMES"],
    ),
    "mojo/middle/resolve_shared.py": (
        "gimple_gen_resolve.py",
        ["KNOWN_LEAF_RETS", "_collect_calls_in_stmt", "_record_closure_alias"],
    ),
    "mojo/middle/funcs_shared.py": (
        "gimple_gen_funcs.py",
        [
            "_selfhost_gen_self_param_ctype",
            "_ris_base",
            "_sgfs_resolve_ann",
            "_scan_from_imports_flat",
        ],
    ),
    "mojo/middle/module_shared.py": (
        "gimple_module_gen.py",
        ["_SELFHOST_MODGLOBAL_CACHE", "_UNKNOWN_FIELD_CTYPE", "_gmi_as_str"],
    ),
    "mojo/middle/stmts_shared.py": (
        "gimple_gen_stmts.py",
        ["_is_genexp"],
    ),
    "mojo/middle/methods_shared.py": (
        "gimple_gen_methods.py",
        ["_SELFHOST_SIBLING_MODULE_PREFIXES"],
    ),
}


def find_spans(pre_path: Path, names: list[str]):
    text = pre_path.read_text()
    tree = ast.parse(text, filename=str(pre_path))
    lines = text.splitlines(keepends=True)
    found = {}
    wanted = set(names)
    for n in tree.body:
        nm = None
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nm = n.name
        elif isinstance(n, ast.Assign) and n.targets and isinstance(n.targets[0], ast.Name):
            nm = n.targets[0].id
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            nm = n.target.id
        if nm in wanted:
            found[nm] = (n.lineno, getattr(n, "end_lineno", n.lineno))
    # Also catch Assign tuples like `A, B = ...` — rare; skip
    # Also multi-name assigns: `KNOWN_LEAF_RETS = {...}` is simple
    missing = [n for n in names if n not in found]
    return found, missing, lines


def remove_from_original(orig_path: Path, spans) -> None:
    """Remove extracted spans from the live original (it imports shared)."""
    if not orig_path.exists():
        return
    text = orig_path.read_text()
    lines = text.splitlines(keepends=True)
    mask = [True] * (len(lines) + 1)
    for a, b in spans:
        for ln in range(a, b + 1):
            if ln <= len(lines):
                mask[ln] = False
    out = [lines[i - 1] for i in range(1, len(lines) + 1) if mask[i]]
    orig_path.write_text("".join(out))


def main() -> int:
    if not PRE.exists():
        print(f"ERROR: pre-wave2 snapshot missing at {PRE}", file=sys.stderr)
        return 1

    for shared_rel, (orig_name, names) in NEEDS.items():
        shared_path = ROOT / shared_rel
        pre_path = PRE / orig_name
        if not shared_path.exists():
            print(f"SKIP {shared_rel}: missing")
            continue
        if not pre_path.exists():
            print(f"SKIP {shared_rel}: pre snapshot {orig_name} missing")
            continue

        found, missing, pre_lines = find_spans(pre_path, names)
        if missing:
            print(f"  {shared_rel}: NOT IN PRE: {missing}")
        if not found:
            print(f"  {shared_rel}: nothing to add")
            continue

        # Extract code
        chunks = []
        for nm, (a, b) in sorted(found.items(), key=lambda kv: kv[1][0]):
            chunks.append(f"# --- dependency {nm} (from {orig_name}) ---\n")
            chunks.extend(pre_lines[a - 1 : b])
            chunks.append("\n")
            print(f"  + {nm} L{a}-{b} -> {shared_rel}")

        # Append to shared module
        with shared_path.open("a") as f:
            f.write("\n# ---------------------------------------------------------------------------\n")
            f.write(f"# Dependencies extracted with the shared API (originally {orig_name})\n")
            f.write("# ---------------------------------------------------------------------------\n\n")
            f.write("".join(chunks))

        # Remove from live original so it doesn't shadow / drift
        # (original already does globals().update from this shared module)
        orig_live = ROOT / orig_name
        # Only remove if the name is still defined there (wave2 may have left it)
        if orig_live.exists():
            live_found, _, _ = find_spans(orig_live, list(found.keys()))
            if live_found:
                remove_from_original(orig_live, live_found.values())
                print(f"  - removed {list(live_found)} from live {orig_name}")

    # coro: ensure `import copy`
    coro = ROOT / "mojo/middle/coro.py"
    if coro.exists():
        text = coro.read_text()
        if not re.search(r"^import copy\b", text, re.M):
            # insert after future import or at top after comments
            lines = text.splitlines(keepends=True)
            insert_at = 0
            for i, line in enumerate(lines):
                if line.startswith("from __future__"):
                    insert_at = i + 1
                    break
                if line.startswith("import ") or line.startswith("from "):
                    insert_at = i
                    break
            if insert_at == 0:
                insert_at = min(10, len(lines))
            lines.insert(insert_at, "import copy\n")
            coro.write_text("".join(lines))
            print("  + import copy -> mojo/middle/coro.py")

    # Verify: free-var re-scan
    print("\n=== Re-scan free vars ===")
    import builtins

    def toplevel_bound(tree):
        s = set(dir(builtins))
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                s.add(n.name)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        s.add(t.id)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                s.add(n.target.id)
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name != "*":
                        s.add(a.asname or a.name)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    s.add(a.asname or a.name.split(".")[0])
        return s

    # star providers
    star = set()
    for p in [
        "mojo/middle/types.py",
        "mojo/middle/exprtypes.py",
        "mojo/middle/solvers.py",
    ]:
        pp = ROOT / p
        if pp.exists():
            star |= toplevel_bound(ast.parse(pp.read_text()))

    known_fp = {"_mlmod", "_imp", "_glob", "_re", "elaborate", "copy"}
    any_missing = False
    for p in sorted((ROOT / "mojo/middle").glob("*.py")):
        if p.name == "__init__.py":
            continue
        tree = ast.parse(p.read_text())
        avail = toplevel_bound(tree) | star | {"annotations"}
        # imports of gimple_codegen?
        for n in tree.body:
            if isinstance(n, ast.Import) and any(a.name == "gimple_codegen" for a in n.names):
                avail |= toplevel_bound(ast.parse((ROOT / "gimple_codegen.py").read_text()))
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            local = set()
            args = n.args
            for a in (
                list(args.posonlyargs)
                + list(args.args)
                + list(args.kwonlyargs)
                + ([args.vararg] if args.vararg else [])
                + ([args.kwarg] if args.kwarg else [])
            ):
                local.add(a.arg)
            for sub in ast.walk(n):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    local.add(sub.id)
                if isinstance(sub, ast.arg):
                    local.add(sub.arg)
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and sub is not n:
                    local.add(sub.name)
                if isinstance(sub, ast.ExceptHandler) and sub.name:
                    local.add(sub.name)
                if isinstance(sub, ast.alias):
                    local.add(sub.asname or sub.name.split(".")[0])
                if isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
                    local.add(sub.target.id)
            free = set()
            for sub in ast.walk(n):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                    if (
                        sub.id not in local
                        and sub.id not in avail
                        and sub.id not in known_fp
                        and not sub.id.startswith("__")
                        and sub.id not in ("self", "cls", "True", "False", "None")
                    ):
                        free.add(sub.id)
            if free:
                any_missing = True
                print(f"  STILL MISSING {p.name}::{n.name}: {sorted(free)}")
    if not any_missing:
        print("  All free vars resolved (known FP excluded).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
