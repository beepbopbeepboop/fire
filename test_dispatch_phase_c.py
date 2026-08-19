#!/usr/bin/env python3
"""Test DispatchSolver Phase C: GimpleGen integration and dispatch table emission."""

import gimple_codegen
from mojo_compiler import py_tokenize, Parser
from gimple_codegen import GimpleGen


def _make_selfhost_gen(**kwargs) -> GimpleGen:
    """Construct a GimpleGen configured as if compiling one of this
    repo's own self-hosting source files.

    This module's `myinterp_test`/`multi_pattern_test` sources are
    deliberate, self-contained repros of THIS COMPILER'S OWN self-hosted
    `Interpreter.execute`-style getattr-as-vtable-dispatch idiom (see the
    module docstring below) — exactly the pattern
    `DispatchSolver.allow_assume_all_methods` exists to recognize
    (gimple_codegen.py, gated to self-hosting compiles only since commit
    02b14c5's fix, to avoid misfiring on ordinary `getattr(self, attr)`
    delegation elsewhere — see bugs/hard/CODEGEN_selfhost_getattr_
    dispatch_heuristic_misfires_on_ordinary_code.md). `gen_module`'s
    `_is_selfhost_file` gate is path-based (is `self._current_filename`
    physically under this repo's own source directory?), so we opt in
    explicitly here the same way a real self-hosting compile would,
    rather than widening the production gate to cover non-self-host
    callers too.
    """
    gen = GimpleGen(**kwargs)
    gen._current_filename = gimple_codegen.__file__
    return gen


# Test case: myinterpreter pattern
myinterp_test = """
class Interpreter:
    def execute(self, node):
        method_name = f'execute_{type(node).__name__}'
        method = getattr(self, method_name, None)
        if method is None:
            return 0
        return method(node)

    def execute_Module(self, node):
        return 1

    def execute_FunctionDef(self, node):
        return 2

    def execute_StructDef(self, node):
        return 3
"""


def test_dispatch_table_emission_in_codegen():
    """Test that dispatch tables are emitted in generated C code."""
    print("Test 1: Dispatch table emission in GimpleGen...")

    tokens = py_tokenize(myinterp_test)
    stmts = Parser(tokens).parse_module()

    # Generate GIMPLE code with dispatch solver enabled
    gen = _make_selfhost_gen(do_imports=False, emit_str_pool=True, emit_struct_defs=True)
    gimple_code = gen.gen_module(stmts)

    print(f"  Generated code length: {len(gimple_code)} bytes")

    # Verify dispatch solver was run
    assert gen._dispatch_solver is not None, "DispatchSolver should have been instantiated"
    print("  ✓ DispatchSolver instantiated")

    # Verify dispatch tables were planned
    assert len(gen._dispatch_tables) > 0, "Should have planned dispatch tables"
    print(f"  ✓ Dispatch tables planned: {len(gen._dispatch_tables)}")

    # Verify typedef appears in generated code
    assert 'interpreter_execute_dispatch_t' in gimple_code, "Should have dispatch table typedef"
    print("  ✓ Dispatch table typedef emitted")

    # Verify initialization appears in generated code
    assert 'interpreter_execute_dispatch' in gimple_code, "Should have dispatch table initialization"
    print("  ✓ Dispatch table initialization emitted")

    # Verify it's after struct definitions but before functions
    typedef_pos = gimple_code.find('interpreter_execute_dispatch_t')
    init_pos = gimple_code.find('static const interpreter_execute_dispatch_t')
    main_pos = gimple_code.find('__GIMPLE')

    assert typedef_pos < init_pos < main_pos, "Order should be: typedef, init, functions"
    print("  ✓ Dispatch table definitions in correct order")

    print("\n  Sample generated dispatch table code:")
    # Find and print the dispatch table typedef
    start = gimple_code.find('typedef struct')
    if 'interpreter_execute' in gimple_code[start:start+500]:
        end = gimple_code.find('};', start) + 2
        sample = gimple_code[start:end]
        for line in sample.split('\n')[:8]:
            print(f"    {line}")
        print("    ...")


def test_dispatch_table_structure():
    """Test that emitted dispatch tables have correct structure."""
    print("\nTest 2: Dispatch table structure validation...")

    tokens = py_tokenize(myinterp_test)
    stmts = Parser(tokens).parse_module()

    gen = _make_selfhost_gen()
    gimple_code = gen.gen_module(stmts)

    # Extract typedef section
    typedef_start = gimple_code.find('typedef struct')
    typedef_end = gimple_code.find('};', typedef_start)
    typedef_section = gimple_code[typedef_start:typedef_end+2]

    print("  Checking typedef structure...")

    # Should have function pointers for each method
    assert 'execute_Module' in typedef_section, "Should have execute_Module method"
    assert 'execute_FunctionDef' in typedef_section, "Should have execute_FunctionDef method"
    assert 'execute_StructDef' in typedef_section, "Should have execute_StructDef method"
    print("  ✓ All methods present in typedef")

    # Should have function pointer syntax
    assert '(*' in typedef_section, "Should have function pointer syntax"
    # Parameters can be typed (Interpreter *self, int node) or generic (void *self, void *node)
    assert '*self' in typedef_section, "Should have self parameter"
    print("  ✓ Function pointer syntax correct")

    # Extract init section
    init_start = gimple_code.find('static const interpreter_execute_dispatch_t')
    init_end = gimple_code.find('};', init_start)
    init_section = gimple_code[init_start:init_end+2]

    print("  Checking initialization structure...")

    # Should initialize each method
    assert '.execute_Module' in init_section, "Should initialize execute_Module"
    assert 'Interpreter_execute_Module' in init_section, "Should reference execute_Module implementation"
    print("  ✓ Initialization assigns correct function pointers")

    print("\n  Sample dispatch table typedef:")
    for line in typedef_section.split('\n')[:10]:
        print(f"    {line}")


def test_multiple_dispatch_patterns():
    """Test handling multiple dispatch patterns."""
    print("\nTest 3: Multiple dispatch patterns...")

    multi_pattern_test = """
class Dispatcher:
    def dispatch_stmt(self, stmt):
        method = getattr(self, f'stmt_{stmt.__class__.__name__}', None)
        return method(stmt) if method else 0

    def stmt_If(self, stmt):
        return 1

    def stmt_While(self, stmt):
        return 2

    def dispatch_expr(self, expr):
        method = getattr(self, f'expr_{expr.__class__.__name__}', None)
        return method(expr) if method else 0

    def expr_BinOp(self, expr):
        return 3

    def expr_UnOp(self, expr):
        return 4
"""

    tokens = py_tokenize(multi_pattern_test)
    stmts = Parser(tokens).parse_module()

    gen = _make_selfhost_gen()
    gimple_code = gen.gen_module(stmts)

    # Should have detected multiple patterns
    assert len(gen._dispatch_tables) >= 1, "Should have planned dispatch tables"
    print(f"  ✓ Found {len(gen._dispatch_tables)} dispatch pattern(s)")

    # Both dispatch patterns might be merged or separate
    # Check that code contains evidence of both stmt_ and expr_ methods
    assert 'stmt_If' in gimple_code or 'Dispatcher_stmt_If' in gimple_code, "Should have stmt methods"
    assert 'expr_BinOp' in gimple_code or 'Dispatcher_expr_BinOp' in gimple_code, "Should have expr methods"
    print("  ✓ Both dispatch pattern families recognized")


def test_gimple_syntax_validity():
    """Test that generated dispatch table code is valid C syntax."""
    print("\nTest 4: Generated C syntax validity...")

    tokens = py_tokenize(myinterp_test)
    stmts = Parser(tokens).parse_module()

    gen = _make_selfhost_gen()
    gimple_code = gen.gen_module(stmts)

    # Check basic syntax elements
    print("  Checking C syntax elements...")

    # Should have proper typedef syntax
    assert 'typedef struct' in gimple_code, "Should have struct typedef"
    assert '};' in gimple_code, "Should have closing typedef"
    print("  ✓ Typedef syntax valid")

    # Should have static const
    assert 'static const' in gimple_code, "Should have static const initializer"
    print("  ✓ Static const initializer present")

    # Should have balanced braces/parens in dispatch tables
    typedef_start = gimple_code.find('typedef')
    func_start = gimple_code.find('__GIMPLE')
    dispatch_section = gimple_code[typedef_start:func_start]

    open_braces = dispatch_section.count('{')
    close_braces = dispatch_section.count('}')
    assert open_braces == close_braces, "Braces should be balanced"
    print("  ✓ Braces balanced")

    # Should have at least one dispatch table
    assert 'dispatch' in gimple_code.lower(), "Should contain dispatch table"
    print("  ✓ Dispatch table present in output")


def test_dispatch_tables_before_functions():
    """Test that dispatch tables are emitted before __GIMPLE functions."""
    print("\nTest 5: Dispatch tables positioned before functions...")

    tokens = py_tokenize(myinterp_test)
    stmts = Parser(tokens).parse_module()

    gen = _make_selfhost_gen()
    gimple_code = gen.gen_module(stmts)

    # Find positions
    typedef_pos = gimple_code.find('typedef struct')
    init_pos = gimple_code.find('static const')
    gimple_pos = gimple_code.find('__GIMPLE')

    print(f"  Typedef position: {typedef_pos}")
    print(f"  Initialization position: {init_pos}")
    print(f"  First __GIMPLE position: {gimple_pos}")

    if typedef_pos >= 0 and gimple_pos >= 0:
        assert typedef_pos < gimple_pos, "Typedef should come before __GIMPLE functions"
        print("  ✓ Typedef before functions")

    if init_pos >= 0 and gimple_pos >= 0:
        assert init_pos < gimple_pos, "Initialization should come before __GIMPLE functions"
        print("  ✓ Initialization before functions")


if __name__ == '__main__':
    try:
        test_dispatch_table_emission_in_codegen()
        test_dispatch_table_structure()
        test_multiple_dispatch_patterns()
        test_gimple_syntax_validity()
        test_dispatch_tables_before_functions()
        print("\n✓ All Phase C tests passed!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
