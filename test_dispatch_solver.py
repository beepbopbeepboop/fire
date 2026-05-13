#!/usr/bin/env python3
"""Test DispatchSolver Phase A implementation."""

from mojo_compiler import tokenize, Parser
from gimple_codegen import DispatchSolver

# Test case 1: Simple direct call graph
test_direct_calls = """
fn add(a: int, b: int) -> int:
    return a + b

fn main():
    x = add(3, 4)
    return x
"""

# Test case 2: getattr dispatch pattern
test_getattr_pattern = """
class Interpreter:
    def execute(self, node):
        method_name = f'execute_{node.__class__.__name__}'
        method = getattr(self, method_name, None)
        if method is None:
            return 0
        return method(node)

    def execute_Module(self, node):
        return 1

    def execute_FunctionDef(self, node):
        return 2
"""

# Test case 3: Dict dispatch pattern
test_dict_dispatch = """
_STMT_DISPATCH = {
    'Module': 'process_module',
    'Func': 'process_func',
}

fn dispatcher(stmt_type):
    handler = _STMT_DISPATCH[stmt_type]
    return handler(stmt_type)
"""


def test_call_graph_simple():
    """Test building call graph from simple direct calls."""
    print("Test 1: Direct call graph...")
    tokens = tokenize(test_direct_calls)
    stmts = Parser(tokens).parse_module()

    solver = DispatchSolver({}, {})
    solver._build_call_graph(stmts)

    # Verify main → add edge exists
    assert 'main' in solver.call_graph, "main not in call graph"
    assert 'add' in solver.call_graph['main'], "main should call add"
    print("  ✓ Direct call graph built correctly")
    print(f"    Call graph: {solver.call_graph}")


def test_getattr_pattern_detection():
    """Test detecting getattr dispatch patterns."""
    print("Test 2: getattr pattern detection...")
    tokens = tokenize(test_getattr_pattern)
    stmts = Parser(tokens).parse_module()

    struct_field_types = {'Interpreter': {'scope': 'int'}}
    func_return_types = {}

    solver = DispatchSolver(struct_field_types, func_return_types)
    solver.analyze(stmts)

    # Verify patterns were found
    assert len(solver.dispatch_patterns) > 0, "No dispatch patterns detected"
    print(f"  ✓ Found {len(solver.dispatch_patterns)} dispatch pattern(s)")

    for pattern_id, pattern in solver.dispatch_patterns.items():
        print(f"    Pattern: {pattern.pattern_type}")
        print(f"      ID: {pattern_id}")
        print(f"      Callees: {pattern.possible_callees}")


def test_struct_methods_mapping():
    """Test struct method mapping."""
    print("Test 3: Struct method mapping...")
    tokens = tokenize(test_getattr_pattern)
    stmts = Parser(tokens).parse_module()

    solver = DispatchSolver({}, {})
    solver._build_call_graph(stmts)

    # Verify struct methods are registered
    assert 'Interpreter' in solver.struct_methods, "Interpreter struct not found"
    interpreter_methods = solver.struct_methods['Interpreter']
    print(f"  ✓ Interpreter has {len(interpreter_methods)} methods")
    for method_name, full_name in interpreter_methods.items():
        print(f"    {method_name} → {full_name}")


def test_monomorphism_detection():
    """Test monomorphism detection (functions with single caller)."""
    print("Test 4: Monomorphism detection...")
    tokens = tokenize(test_direct_calls)
    stmts = Parser(tokens).parse_module()

    solver = DispatchSolver({}, {})
    solver._build_call_graph(stmts)

    # add() is called only by main(), so it's monomorphic
    assert solver.is_monomorphic('add'), "add should be monomorphic"
    assert solver.get_call_count('add') == 1, "add should have 1 caller"
    print("  ✓ Monomorphism detection works")
    print(f"    add() has {solver.get_call_count('add')} caller (is_monomorphic={solver.is_monomorphic('add')})")


if __name__ == '__main__':
    try:
        test_call_graph_simple()
        print()
        test_struct_methods_mapping()
        print()
        test_getattr_pattern_detection()
        print()
        test_monomorphism_detection()
        print("\n✓ All tests passed!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
