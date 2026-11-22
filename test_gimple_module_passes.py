#!/usr/bin/env python3
"""Passes of `gen_module_impl` are their own functions.

`tools/extract_arm.py --phase` moves one WHOLE top-level statement of a
function that is a sequence of passes into a top-level function that returns
nothing, and leaves a call in its place (doc/GIR.md, "Stage 6, passes of
`gen_module_impl`").  The tool refuses a statement that returns, that binds a
name the parent or one of its nested functions reads afterwards, or that calls
a nested function, and it checks that the moved statement is the same syntax
tree.

This pins the state of that split, the way `test_gimple_arms_extracted.py`
pins the arm split:

  * every `_gmp_*` function `gen_module_impl` calls is a top-level function
    called exactly ONCE, which is what makes it a pass rather than a helper;
  * the passes this round extracted still have the parameter annotations they
    were extracted with.  An annotation is not cosmetic: it is what the
    self-hosted compiler types the parameter from, so dropping one silently
    changes that function's C.  These rows were verified against the C types
    the parent's locals had in the compiler's own output (`fire.py --dump
    mojo/backend_gimple/module_gen.py`); a later round appends its own rows;
  * `gen_module_impl`'s own length, which may only shrink.

A pass inlined back into the parent, an annotation dropped, or a new pass
written inline makes this test fail.  The byte-identical-C half of the
verification is `tools/c_oracle.py check` over `tools/pydiff_corpus`, which is
too slow to run here.

    python3 test_gimple_module_passes.py
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, 'mojo', 'backend_gimple', 'module_gen.py')

# (function, signature as spelled in the file, without `def`/`-> None:`).
# Each one is a pass of `gen_module_impl` extracted by `extract_arm.py
# --phase`; the annotation is the C type the local had in the parent's own
# compiled output (`int64_t` is the empty annotation).
ROUND_2026_11_21 = [
    ('_gmp_preseed_ast_struct_tables', 'self, _pseed_claimed: bool'),
    ('_gmp_release_compile_tables', 'self, imported_stmts: list'),
    ('_gmp_emit_device_sidecar',
     'self, _device_kernels_meta: dict, _device_parts: list[str], '
     '_mg_introspected, parts: list[str]'),
    ('_gmp_emit_str_pool_registration', 'self, parts: list[str]'),
    ('_gmp_emit_str_pool_globals', 'self, parts: list[str]'),
    ('_gmp_forward_selfhost_syms', 'self, _is_selfhost_file: bool, parts: list[str]'),
    ('_gmp_emit_generator_typedef', 'self, parts: list[str]'),
    ('_gmp_emit_imported_toplevel_decls',
     'self, all_modules_to_declare: dict, our_mod: str, parts: list[str]'),
    ('_gmp_emit_entry_point',
     'self, stmts: list, func_parts: list[str], has_toplevel_code: bool'),
    ('_gmp_emit_toplevel_function',
     'self, func_parts: list[str], has_toplevel_code: bool, toplevel_stmts: list'),
    ('_gmp_fix_global_call_slot_types', 'self, stmts: list'),
    ('_gmp_fix_funcparam_ptr_types', 'self, func_defs: list'),
    ('_gmp_infer_global_var_types_early', 'self, _early_gvt_items: list'),
]

# The parent's own line span; it may only shrink as passes move out.  A pass
# written inline here instead of extracted makes this fail.
PARENT_LINES = 9107


def main() -> int:
    src = open(PATH).read()
    tree = ast.parse(src)
    failures = []

    parent = None
    top = {}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef):
            top[n.name] = n
            if n.name == 'gen_module_impl':
                parent = n
    if parent is None:
        print('FAIL: gen_module_impl is gone')
        return 1

    # A `_gmp_*` callee of the parent is a pass: top-level, called once.
    calls = {}
    for n in ast.walk(parent):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id.startswith('_gmp_')):
            calls[n.func.id] = calls.get(n.func.id, 0) + 1
    for name in sorted(calls):
        if name not in top:
            failures.append(f'{name}: called from gen_module_impl but not a '
                            f'module-level function')
        elif calls[name] != 1:
            failures.append(f'{name}: called {calls[name]} times from '
                            f'gen_module_impl; a pass is called once')

    for name, sig in ROUND_2026_11_21:
        want = f'def {name}({sig}) -> None:'
        if not re.search(r'(?m)^' + re.escape(want) + r'$', src):
            failures.append(f'{name}: signature is not {want!r}')
        if calls.get(name) != 1:
            failures.append(f'{name}: not called exactly once from '
                            f'gen_module_impl')

    lines = parent.end_lineno - parent.lineno + 1
    if lines > PARENT_LINES:
        failures.append(f'gen_module_impl is {lines} lines, over the '
                        f'{PARENT_LINES}-line ratchet: extract the new pass '
                        f'with tools/extract_arm.py --phase instead of '
                        f'inlining it')

    for f in failures:
        print(f'FAIL: {f}')
    print(f'{len(ROUND_2026_11_21)} pass(es) pinned, gen_module_impl '
          f'{lines}/{PARENT_LINES} lines, '
          f'{len(failures)} failure(s)')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
