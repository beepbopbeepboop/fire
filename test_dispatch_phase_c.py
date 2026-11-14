#!/usr/bin/env python3
"""DispatchSolver phase C: GimpleGen integration and dispatch table emission.

Phase C plans dispatch tables in `gen_module` and emits them into the generated
C. `mojo/backend_gimple/module_gen.py` solves dispatch for ordinary programs
only: for this compiler's OWN sources (`_is_selfhost_file`) it skips the solve
entirely, because the python3 reference and the self-hosted binary would
otherwise emit different tables (a stage1-vs-stage2 divergence). So this file
pins both halves of that policy:

  * an ordinary program gets its dispatch table planned, emitted, and ordered
    before the functions that call through it;
  * a self-host source gets no solver run and no table, even for a pattern
    that would be planned for an ordinary program.

Both are checked on the same source text, so the only variable is the path
the compile claims to come from.
"""

import gimple_codegen
from fire_compiler import py_tokenize, Parser
from gimple_codegen import GimpleGen


# A path that is not one of this compiler's own sources, so dispatch is solved.
ORDINARY_PATH = '/not-the-compiler/user_program.py'
# A path that IS one of this compiler's own sources, so dispatch is skipped.
SELFHOST_PATH = gimple_codegen.__file__

# A getattr-as-vtable dispatch with a concatenated name: the shape the solver
# recognises for ordinary code (`_infer_getattr_targets` on `'prefix' + x`).
DISPATCHER = """
class Dispatcher:
    def dispatch_stmt(self, stmt):
        method = getattr(self, 'stmt_' + stmt.kind, None)
        return method(stmt) if method else 0

    def stmt_If(self, stmt):
        return 1

    def stmt_While(self, stmt):
        return 2
"""

# Two dispatch families in one class: each gets its own table.
TWO_FAMILIES = """
class Dispatcher:
    def dispatch_stmt(self, stmt):
        method = getattr(self, 'stmt_' + stmt.kind, None)
        return method(stmt) if method else 0

    def stmt_If(self, stmt):
        return 1

    def stmt_While(self, stmt):
        return 2

    def dispatch_expr(self, expr):
        method = getattr(self, 'expr_' + expr.kind, None)
        return method(expr) if method else 0

    def expr_BinOp(self, expr):
        return 3

    def expr_UnOp(self, expr):
        return 4
"""


def _gen(path: str, source: str):
    """Compile `source` as if it were the file at `path`; return (gen, C code)."""
    gen = GimpleGen(do_imports=False, emit_str_pool=True, emit_struct_defs=True)
    gen._current_filename = path
    stmts = Parser(py_tokenize(source)).parse_module()
    return gen, gen.gen_module(stmts)


def _init_target(code: str, field: str) -> str | None:
    """The C function the dispatch initialiser binds `.field` to, or None."""
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith(f'.{field} = '):
            # `.field = (int64_t (*)(...))Target,` -> `Target`
            return stripped.rsplit(')', 1)[-1].rstrip(',')
    return None


def test_ordinary_program_plans_and_emits_dispatch_table():
    """An ordinary program's table is planned, emitted, and ordered correctly."""
    print("Test 1: ordinary program dispatch table...")
    gen, code = _gen(ORDINARY_PATH, DISPATCHER)

    assert gen._dispatch_solver is not None, "DispatchSolver should have run"
    assert len(gen._dispatch_tables) == 1, f"expected 1 table, got {len(gen._dispatch_tables)}"
    (callees,) = gen._dispatch_tables.keys()
    assert callees == frozenset({'Dispatcher_stmt_If', 'Dispatcher_stmt_While'}), callees
    print("  ✓ table planned for both stmt_ methods")

    typedef = 'dispatcher_stmt_dispatch_t'
    init = 'static const dispatcher_stmt_dispatch_t dispatcher_stmt_dispatch'
    assert f'}} {typedef};' in code, "typedef should be emitted"
    assert init in code, "initialiser should be emitted"
    assert _init_target(code, 'stmt_If') == 'Dispatcher_stmt_If', "initialiser should bind the If method"
    assert _init_target(code, 'stmt_While') == 'Dispatcher_stmt_While', "initialiser should bind the While method"
    print("  ✓ typedef and initialiser emitted")

    typedef_pos = code.find(f'}} {typedef};')
    init_pos = code.find(init)
    func_pos = code.find('__GIMPLE Dispatcher_dispatch_stmt')
    assert 0 <= typedef_pos < init_pos < func_pos, "order should be typedef, init, functions"
    print("  ✓ typedef, initialiser, then functions")


def test_dispatch_section_is_well_formed_c():
    """The emitted dispatch section has balanced braces and a typedef on each table."""
    print("Test 2: dispatch section is well-formed C...")
    _, code = _gen(ORDINARY_PATH, DISPATCHER)

    start = code.find('typedef struct')
    end = code.find('__GIMPLE')
    assert start >= 0 and end > start, "typedef struct should precede the functions"
    section = code[start:end]
    assert section.count('{') == section.count('}'), "braces should balance"
    assert 'dispatcher_stmt_dispatch' in section, "table should be in that section"
    print("  ✓ braces balanced and table present")


def test_two_families_get_two_tables():
    """Two independent dispatch families each produce their own table."""
    print("Test 3: two dispatch families...")
    gen, code = _gen(ORDINARY_PATH, TWO_FAMILIES)

    assert len(gen._dispatch_tables) == 2, f"expected 2 tables, got {len(gen._dispatch_tables)}"
    assert _init_target(code, 'stmt_If') == 'Dispatcher_stmt_If', "stmt family should be emitted"
    assert _init_target(code, 'expr_BinOp') == 'Dispatcher_expr_BinOp', "expr family should be emitted"
    print("  ✓ both families planned and emitted")


def test_selfhost_source_plans_no_dispatch():
    """A self-host source skips dispatch solving, even for a pattern that is
    planned for an ordinary program (see the module docstring)."""
    print("Test 4: self-host source skips dispatch...")
    gen, code = _gen(SELFHOST_PATH, DISPATCHER)

    assert gen._dispatch_solver is None, "DispatchSolver must not run on a self-host source"
    assert gen._dispatch_tables == {}, "no table may be planned on a self-host source"
    assert 'dispatcher_stmt_dispatch_t' not in code, "no dispatch typedef on a self-host source"
    print("  ✓ solver skipped, no table, no typedef")


if __name__ == '__main__':
    try:
        test_ordinary_program_plans_and_emits_dispatch_table()
        test_dispatch_section_is_well_formed_c()
        test_two_families_get_two_tables()
        test_selfhost_source_plans_no_dispatch()
        print("\n✓ All Phase C tests passed!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
