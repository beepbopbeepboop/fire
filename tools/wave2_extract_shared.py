#!/usr/bin/env python3
"""Wave-2: extract shared middle-end code from mixed gimple_* files.

Strategy (preserves comments — unlike full AST unparse):
  1. Parse with AST to find top-level def/class boundaries.
  2. Classify each as shared / backend / mixed via source markers.
  3. Copy shared (and selected mixed) defs by LINE RANGE into new modules.
  4. Leave the original file with remaining defs + an import of the new module
     (so unqualified references inside remaining code still resolve).
  5. Rewrite the original's imports of the new module.

Also: gimple_gen_coro is ~96% shared AST desugar — move whole file to
mojo/middle/coro.py and leave register()/emit_c in backend_gimple/coro_emit.py.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Shared classifiers (same markers as the survey)
# ---------------------------------------------------------------------------
BACKEND_RE = re.compile(
    r"\b_emit\s*\(|_declare_var\s*\(|_new_bb\s*\(|_write_dest\s*\(|"
    r"compile_to_gimple|gimple_temp|_ensure_local\s*\(|_coerce_to_type\s*\(|"
    r"_cpp_|_register_sym\s*\(|_reset_func\s*\(|_func_csym\b|"
    r"STRING_POOL_BASE|_SELFHOST_DIR"
)
SHARED_RE = re.compile(
    r"isinstance\([^,]+,\s*(FunctionDef|ClassDef|ForStmt|IfStmt|WhileStmt|"
    r"AssignStmt|ReturnStmt|VarDecl|StructDef|FromImportStmt)|"
    r"ast\.walk\(|yield_kind|await_|eligible|Solver|infer_|"
    r"ClosureInfo|escape|capture|desugar|rewrite_|_lower_one|"
    r"TypeLattice|_walk_ast"
)


def classify_source(text: str) -> str:
    b = len(BACKEND_RE.findall(text))
    s = len(SHARED_RE.findall(text))
    if b == 0 and s == 0:
        return "util"
    if b > 0 and s > 0:
        if b >= 3 * max(s, 1):
            return "backend"
        if s >= 3 * max(b, 1):
            return "shared"
        return "mixed"
    return "backend" if b > 0 else "shared"


def toplevel_units(path: Path):
    """Yield (kind, name, start_line, end_line, source_text) for top-level defs."""
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text, filename=str(path))
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = n.lineno  # 1-based
            end = getattr(n, "end_lineno", n.lineno)
            src = "".join(lines[start - 1 : end])
            cls = classify_source(src)
            yield ("def", n.name, start, end, cls, src)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            # keep module-level constants with whichever side they serve
            start = n.lineno
            end = getattr(n, "end_lineno", n.lineno)
            src = "".join(lines[start - 1 : end])
            # assigns are usually shared tables
            name = None
            if isinstance(n, ast.Assign) and n.targets and isinstance(n.targets[0], ast.Name):
                name = n.targets[0].id
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                name = n.target.id
            if name:
                yield ("assign", name, start, end, "shared", src)


def extract_lines(path: Path, spans) -> str:
    """spans: list of (start, end) inclusive 1-based. Returns concatenated source."""
    lines = path.read_text().splitlines(keepends=True)
    out = []
    for a, b in sorted(spans):
        out.extend(lines[a - 1 : b])
        out.append("\n")
    return "".join(out)


def rewrite_file_imports(text: str, mapping: dict[str, str]) -> str:
    """Rewrite `import gimple_X` / `from gimple_X import ...` using mapping old->new dotted."""
    tree = ast.parse(text)

    class R(ast.NodeTransformer):
        def visit_Import(self, node):
            for a in node.names:
                root = a.name.split(".")[0]
                if root in mapping:
                    a.name = mapping[root]
                    a.asname = a.asname or root
            return node

        def visit_ImportFrom(self, node):
            if node.module and node.level == 0:
                root = node.module.split(".")[0]
                if root in mapping:
                    node.module = mapping[root]
            return node

    # Use textual regex instead of unparse to preserve comments
    for old, new in mapping.items():
        text = re.sub(
            rf"^(\s*)from\s+{re.escape(old)}\s+import\s+",
            rf"\1from {new} import ",
            text,
            flags=re.M,
        )
        text = re.sub(
            rf"^(\s*)import\s+{re.escape(old)}\s*$",
            rf"\1import {new} as {old}",
            text,
            flags=re.M,
        )
        text = re.sub(
            rf"^(\s*)import\s+{re.escape(old)}\s+as\s+",
            rf"\1import {new} as ",
            text,
            flags=re.M,
        )
    return text


# ---------------------------------------------------------------------------
# Task 1: gimple_gen_coro -> middle/coro.py (shared) + backend_gimple/coro_emit.py
# ---------------------------------------------------------------------------
def move_coro() -> None:
    src = ROOT / "gimple_gen_coro.py"
    if not src.exists():
        print("coro: already moved?")
        return
    text = src.read_text()
    tree = ast.parse(text, filename=str(src))
    lines = text.splitlines(keepends=True)

    # Find register and emit_c spans (backend)
    backend_spans = []
    shared_spans = []
    # Always keep module header (imports + constants before first def that is backend)
    first_def = None
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start, end = n.lineno, getattr(n, "end_lineno", n.lineno)
            if n.name in ("register", "emit_c"):
                backend_spans.append((start, end))
            else:
                # classify
                src_body = "".join(lines[start - 1 : end])
                if classify_source(src_body) == "backend":
                    backend_spans.append((start, end))
                else:
                    shared_spans.append((start, end))
            if first_def is None:
                first_def = start
        elif isinstance(n, (ast.Import, ast.ImportFrom)) or n is tree.body[0]:
            pass  # handled via header

    # Header: everything before first FunctionDef/ClassDef that's not imports/assigns
    # Simpler: lines 1 .. (first def start - 1)
    header_end = (first_def - 1) if first_def else 1
    header = "".join(lines[:header_end])

    # Split header imports: shared deps vs backend deps
    # Shared coro only needs ctypes + exprtypes + fire_compiler
    # register/emit_c may need more

    shared_body = extract_lines(ROOT / "gimple_gen_coro.py", shared_spans)
    backend_body = extract_lines(ROOT / "gimple_gen_coro.py", backend_spans)

    # Build shared module
    # Filter header imports: keep fire_compiler, ctypes/exprtypes, stdlib; drop gimple_codegen if any
    shared_header_lines = []
    for line in header.splitlines(keepends=True):
        # drop imports of backend modules
        if re.match(r"^\s*import\s+gimple_codegen\b", line):
            continue
        if re.match(r"^\s*import\s+gimple_gen_(?!coro)", line):
            continue
        if re.match(r"^\s*import\s+gimple_cpp", line):
            continue
        if re.match(r"^\s*import\s+gimple_module", line):
            continue
        # rewrite ctypes/exprtypes to new path
        line = re.sub(
            r"^(\s*)from\s+gimple_ctypes\s+import\s+",
            r"\1from mojo.middle.types import ",
            line,
        )
        line = re.sub(
            r"^(\s*)from\s+gimple_exprtypes\s+import\s+",
            r"\1from mojo.middle.exprtypes import ",
            line,
        )
        line = re.sub(
            r"^(\s*)import\s+gimple_ctypes\s*$",
            r"\1import mojo.middle.types as gimple_ctypes",
            line,
        )
        line = re.sub(
            r"^(\s*)import\s+gimple_exprtypes\s*$",
            r"\1import mojo.middle.exprtypes as gimple_exprtypes",
            line,
        )
        shared_header_lines.append(line)
    shared_header = "".join(shared_header_lines)

    shared_mod = (
        "# Moved from gimple_gen_coro.py — shared async/generator AST desugar.\n"
        "# No C/GIMPLE emission lives here; backend hooks are in\n"
        "# mojo/backend_gimple/coro_emit.py (register/emit_c).\n"
        + shared_header
        + "\n"
        + shared_body
    )
    (ROOT / "mojo/middle/coro.py").write_text(shared_mod)

    # Backend emit module: imports shared coro + keeps register/emit_c
    backend_header = '''"""Backend hooks for coroutine lowering (from gimple_gen_coro).

`lower` / eligibility live in mojo.middle.coro (shared AST desugar).
This module keeps `register` + `emit_c`, which emit GIMPLE/C and touch
GimpleGen state.
"""
from __future__ import annotations

import gimple_codegen  # register/emit_c need GimpleGen
from mojo.middle.coro import *  # re-export shared API for old importers
from mojo.middle.coro import (
    enabled, lower, _NATIVE_FUTURE_CLASSES,
    # plus any helpers register/emit_c call — star import covers module level
)
import mojo.middle.coro as _coro

# Re-bind shared names register/emit_c close over
'''
    # Actually register/emit_c reference sibling functions in same file.
    # Best approach: put them IN coro.py still, but that defeats the split.
    # Alternative: keep whole gimple_gen_coro in middle (it's 96% shared),
    # and only strip emit_c/register if they're cleanly separable.
    #
    # Decision: keep whole file in middle for now — register/emit_c are thin
    # enough and heavily coupled to shared helpers. Document as backend-touching
    # but co-located. True backend split deferred to when GimpleGen API stabilizes.

    # Abort partial backend write; just do whole-file move to middle.
    print("coro: moving entire module to mojo/middle/coro.py (register/emit_c coupled)")
    # Rewrite imports in whole file
    new_text = rewrite_file_imports(text, {
        "gimple_ctypes": "mojo.middle.types",
        "gimple_exprtypes": "mojo.middle.exprtypes",
    })
    header_note = (
        "# Moved from gimple_gen_coro.py — shared middle-end (async/generator\n"
        "# desugar). register()/emit_c still emit C and touch GimpleGen; they\n"
        "# remain here because they close over many shared helpers. Future:\n"
        "# split to mojo/backend_gimple/coro_emit.py once the GimpleGen API\n"
        "# for registration is isolated.\n"
    )
    (ROOT / "mojo/middle/coro.py").write_text(header_note + new_text)
    src.write_text(
        '"""Compatibility shim — implementation moved to `mojo.middle.coro`.\n\n'
        "`import gimple_gen_coro` and `from gimple_gen_coro import ...` keep working.\n"
        'Prefer `mojo.middle.coro` in new code.\n'
        '"""\n'
        "from mojo.middle.coro import *  # noqa: F401,F403\n"
        "\n"
        "import mojo.middle.coro as _impl\n"
        "_g = globals()\n"
        "for _k in dir(_impl):\n"
        '    if _k.startswith("__"):\n'
        "        continue\n"
        "    _g[_k] = getattr(_impl, _k)\n"
        "del _k, _g, _impl\n"
    )
    print("MOVED gimple_gen_coro.py -> mojo/middle/coro.py + shim")


# ---------------------------------------------------------------------------
# Task 2: extract clearly-shared top-level defs from mixed modules
# ---------------------------------------------------------------------------
# module -> (new_middle_name, {def_name -> True for shared})
EXTRACT = {
    # infra: pure type/container inference helpers used by both backends later
    "gimple_gen_infra.py": ("infra_infer", [
        "_infer_param_types",
        "_seed_addressed_locals",
        "_scan_container_elems",
        "_is_known_field",
        "_known_field_type",
        "_resolve_member_expr_type",
        "_function_has_reachable_fallthrough",
        "_is_free_eligible_function",
        "_compute_owned_free_candidates",
        "_empty_ctor_ctype",
        "_type_of",
        "_resolve_type",
        "_closure_info_for_ident",
        "_collect_return_types",
        "_infer_return_type",
        "_prepass_list_elem",
    ]),
    # resolve: name binding + type refinement
    "gimple_gen_resolve.py": ("resolve_shared", [
        "_lbn_target_names",
        "_lbn_walk",
        "_closure_value_locals",
        "_quick_type",
        "_infer_list_elem_type",
        "_collect_local_container_elems",
        "_collect_return_elems",
        "_infer_return_elem_type",
        "_infer_local_var_types",
        "_parse_fstring_parts",
        "_decode_str_literal_text",
        "_str_literal_to_slit",
        "_subst_idents",
        "_type_expr_to_ann",
        "_refine_generic_return_type",
        "_is_none_literal",
        "_is_sys_stderr",
        "_eval_const",
        "_module_const_int",
        "_calls_in_stmts",
        "_prepass_callee_key",
        "_register_closure_alias",
    ]),
    # funcs: signature/import resolution
    "gimple_gen_funcs.py": ("funcs_shared", [
        "_from_import_name_is_submodule",
        "_resolve_reexported_closure_func",
        "_signature_ctypes",
        "_param_ctype",
        "_note_vararg_trailing_param_types",
        "_imported_field_ctype",
        "_ris_collect",
        "_struct_method_overload_ids",
        "_struct_method_qualifier",
        "_resolve_import_module_qualifier",
        "_resolve_test_relative_module",
        "_parsed_import",
        "_local_sibling_module_exports",
        "_find_generic_source",
        "_find_imported_struct",
    ]),
    # module: collectors / symbol registration
    "gimple_module_gen.py": ("module_shared", [
        "_collect_import_modules",
        "_collect_import_modules_rec",
        "_register_sym",
        "_gmi_prefold_toplevel_comptime",
        "_gmi_find_comptime_one",
        "_gmi_phase17_collect_appends",
        "_gmi_collect_self_assigns",
        "_gmi_all_stmts_nonfunc",
        "_gmi_scan_import_modules",
        "_gmi_self_member",
        "_gmi_global_init_code",
        "_gmi_collect_global_stmts",
        "_gmi_scan_func_body_for_self_attr",
        "_gmi_collect_return_values",
        "_gmi_scan_try_imports",
        "_gmi_scan_cpp_nested_imports",
        "_selfhost_modglobal_is_pathcall",
        "_selfhost_module_scalar_globals",
        "_selfhost_struct_dict_field_val_types",
        "_selfhost_homogeneous_tuple_ret_funcs",
        "_selfhost_fn_reassigns_method",
        "_bytes_subclass_new_payload_name",
    ]),
    # stmts: AST iteration + narrowing analysis (shared)
    "gimple_gen_stmts.py": ("stmts_shared", [
        "_iter_ast",
        "_with_item_alias_name",
        "_seed_genexp_list_narrowing",
        "_narrow_key_for_expr",
        "_isinstance_narrow_struct",
        "_collect_isinstance_narrowings",
        "_handler_bind_name",
        "_annotation_dict_val_type",
        "_annotation_dict_nested_val_type",
        "_handler_exc_name",
        "_assign_target",
        "_is_except_as_member_target",
    ]),
    # calls: overload resolution helpers that aren't C emission
    "gimple_gen_calls.py": ("calls_shared", [
        "_ident_call_name",
        "_isinstance_type_name",
        "_default_expr_to_pair",
        "_resolve_overload",
        "_build_call_args_for_candidate",
        "_pack_kwargs_dict",
    ]),
    # loops: const fold + lifted closure analysis
    "gimple_gen_loops.py": ("loops_shared", [
        "_try_const_fold_int",
        "_tuple_elem_value",
        "_tuple_unpack_slot_elems",
        "_gfl_declare_target_name",
    ]),
    # methods: dispatch decisions
    "gimple_gen_methods.py": ("methods_shared", [
        "_gmm_callexpr_node",
        "_is_selfhost_sibling_alias",
    ]),
}


def extract_shared_from(filename: str, new_name: str, def_names: list[str]) -> None:
    path = ROOT / filename
    if not path.exists():
        print(f"SKIP {filename}: not found")
        return
    text = path.read_text()
    tree = ast.parse(text, filename=str(path))
    lines = text.splitlines(keepends=True)

    by_name = {}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            by_name[n.name] = (n.lineno, getattr(n, "end_lineno", n.lineno))

    spans = []
    found = []
    missing = []
    for d in def_names:
        if d in by_name:
            spans.append(by_name[d])
            found.append(d)
        else:
            missing.append(d)

    if missing:
        print(f"  {filename}: missing defs (skipped): {missing}")
    if not spans:
        print(f"  {filename}: nothing to extract")
        return

    extracted = extract_lines(path, spans)

    # Header for new module: docstring + stdlib + fire_compiler + middle deps
    # Build a minimal import header by scanning original imports
    header_lines = [
        f'"""Shared middle-end extracted from {filename}.\n',
        "\n",
        "These helpers perform AST analysis / name+type resolution with no\n",
        "C/GIMPLE emission. The original module keeps the emission paths and\n",
        "imports this module for the shared pieces.\n",
        '"""\n',
        "from __future__ import annotations\n",
        "\n",
    ]
    # Copy non-gimple imports from original (stdlib, fire_compiler, etc.)
    for n in tree.body:
        if isinstance(n, ast.Import):
            names = [a.name for a in n.names]
            if not any(x.startswith("gimple") for x in names):
                header_lines.append(ast.unparse(n) + "\n")
        elif isinstance(n, ast.ImportFrom):
            if n.module and not n.module.startswith("gimple") and n.level == 0:
                header_lines.append(ast.unparse(n) + "\n")
            elif n.level > 0:
                header_lines.append(ast.unparse(n) + "\n")
    # Shared middle imports
    header_lines.append(
        "from mojo.middle.types import *  # noqa: F401,F403\n"
        "from mojo.middle.exprtypes import *  # noqa: F401,F403\n"
        "from mojo.middle.solvers import *  # noqa: F401,F403\n"
    )
    # If original imported gimple_codegen for constants, we still need some —
    # leave a note; extracted code may reference gimple_codegen lazily.
    if re.search(r"^import gimple_codegen", text, re.M):
        header_lines.append("import gimple_codegen  # constants used by some extracted helpers\n")
    if re.search(r"^import gimple_ctypes", text, re.M):
        pass  # covered by star import from types
    if re.search(r"^import gimple_solvers", text, re.M):
        pass
    if re.search(r"^import gimple_exprtypes", text, re.M):
        pass
    # Cross-shared imports (e.g. funcs may need infra_infer)
    header_lines.append(
        "import mojo.middle.types as gimple_ctypes\n"
        "import mojo.middle.solvers as gimple_solvers\n"
        "import mojo.middle.exprtypes as gimple_exprtypes\n"
    )

    new_path = ROOT / f"mojo/middle/{new_name}.py"
    new_path.write_text("".join(header_lines) + "\n" + extracted)
    print(f"  EXTRACTED {len(found)} defs from {filename} -> mojo/middle/{new_name}.py")

    # Remove extracted spans from original, insert import of new module
    # Do this by rebuilding file from remaining top-level nodes (text-based)
    keep_spans = sorted(
        (n.lineno, getattr(n, "end_lineno", n.lineno))
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign))
        and n.lineno not in {s[0] for s in spans}
        and getattr(n, "end_lineno", n.lineno) not in {e for _, e in spans}
    )
    # More reliable: exclude any span that overlaps an extracted span
    extracted_set = set()
    for a, b in spans:
        extracted_set.update(range(a, b + 1))

    remaining_parts = []
    i = 1
    total = len(lines)
    # Walk top-level nodes; skip those whose lines intersect extracted_set
    extract_ranges = sorted(spans)
    # Build remaining by taking all lines not in any extract range, but preserving structure
    # Simpler approach: line mask
    mask = [True] * (total + 1)  # 1-based
    for a, b in extract_ranges:
        for ln in range(a, b + 1):
            if ln <= total:
                mask[ln] = False

    # Find import insertion point: after last remaining import / before first remaining def
    # Actually insert right after the original import block.
    insert_at = 1
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            insert_at = max(insert_at, getattr(n, "end_lineno", n.lineno))
        elif isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
            insert_at = max(insert_at, getattr(n, "end_lineno", n.lineno))  # docstring
        else:
            break

    import_line = f"\nfrom mojo.middle.{new_name} import *  # noqa: F401,F403  (shared extracted from {filename})\n"
    import_line += f"from mojo.middle.{new_name} import *  # also bind underscore via explicit:\n"
    # underscore re-export for internal use within this module:
    # `from X import *` skips _names — need explicit or import module
    import_line = (
        f"\nimport mojo.middle.{new_name} as _shared  # extracted shared helpers from this file\n"
        f"globals().update({{k: getattr(_shared, k) for k in dir(_shared) if not k.startswith('__')}})\n"
        f"del _shared\n"
    )

    # Rebuild file
    out_lines = []
    inserted = False
    for ln in range(1, total + 1):
        if ln == insert_at + 1 and not inserted:
            out_lines.append(import_line)
            inserted = True
        if mask[ln]:
            out_lines.append(lines[ln - 1])
    if not inserted:
        out_lines.append(import_line)

    path.write_text("".join(out_lines))
    print(f"  TRIMMED {filename}: removed {len(extracted_set)} lines, injected shared import")


def main() -> int:
    move_coro()
    print("\n=== Extracting shared defs from mixed modules ===")
    for filename, (new_name, defs) in EXTRACT.items():
        extract_shared_from(filename, new_name, defs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
