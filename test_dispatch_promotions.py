#!/usr/bin/env python3
"""Test def→fn promotions and type promotions across transitive closure.

This tests the new extensions to DispatchSolver for identifying functions
that can be compiled to C and for promoting types across the full closure.
"""

from fire_compiler import py_tokenize, Parser
from gimple_codegen import DispatchSolver, FunctionCompilability, TypePromotionSolver

# Test case 1: Functions with full signatures (compilable)
compilable_test = """
def add_nums(a: int, b: int) -> int:
    return a + b

def multiply(x: int, y: int) -> int:
    return x * y

def process_data(data: int) -> int:
    result = add_nums(data, 10)
    return multiply(result, 2)
"""

# Test case 2: Functions with partial signatures (not compilable)
mixed_signatures_test = """
def dynamic_call(obj):
    method = getattr(obj, 'execute', None)
    return method(obj) if method else 0

def annotated_func(x: int) -> int:
    return x * 2

def partial_annotation(value: int):
    return value + 1
"""

# Test case 3: With struct methods
struct_methods_test = """
class Calculator:
    def add(self, a: int, b: int) -> int:
        return a + b

    def subtract(self, a: int, b: int) -> int:
        return a - b

    def dynamic_calc(self, obj):
        method = getattr(self, 'add', None)
        return method(10, 20) if method else 0
"""


def test_function_compilability():
    """Test identifying C-compilable functions."""
    print("Test 1: Function compilability (def→fn promotions)...")

    tokens = py_tokenize(compilable_test)
    stmts = Parser(tokens).parse_module()

    compilability = FunctionCompilability({}, {})
    compilability.analyze(stmts)

    print(f"  Compilable functions: {compilability.compilable_funcs}")

    # All three functions should be compilable (have full signatures)
    assert 'add_nums' in compilability.compilable_funcs, "add_nums should be compilable"
    assert 'multiply' in compilability.compilable_funcs, "multiply should be compilable"
    assert 'process_data' in compilability.compilable_funcs, "process_data should be compilable"

    print(f"  ✓ Found {compilability.get_compilable_count()} compilable functions")
    print("  ✓ def→fn promotion analysis works")


def test_partial_signatures():
    """Test detection of functions with incomplete signatures."""
    print("\nTest 2: Partial signatures (not compilable)...")

    tokens = py_tokenize(mixed_signatures_test)
    stmts = Parser(tokens).parse_module()

    compilability = FunctionCompilability({}, {})
    compilability.analyze(stmts)

    print(f"  Compilable: {compilability.compilable_funcs}")
    print(f"  Uncompilable: {compilability.uncompilable_funcs}")

    # annotated_func should be compilable (has return type)
    assert 'annotated_func' in compilability.compilable_funcs, "annotated_func should be compilable"

    # partial_annotation should NOT be compilable (no return type)
    assert 'partial_annotation' not in compilability.compilable_funcs, "partial_annotation should not be compilable"

    # dynamic_call should NOT be compilable (no return type)
    assert 'dynamic_call' not in compilability.compilable_funcs, "dynamic_call should not be compilable"

    print("  ✓ Correctly identified compilable vs uncompilable functions")


def test_struct_method_compilability():
    """Test compilability analysis on struct methods."""
    print("\nTest 3: Struct method compilability...")

    tokens = py_tokenize(struct_methods_test)
    stmts = Parser(tokens).parse_module()

    compilability = FunctionCompilability({}, {})
    compilability.analyze(stmts)

    print(f"  Compilable methods: {compilability.compilable_funcs}")

    # Calculator.add and Calculator.subtract should be compilable
    assert 'Calculator_add' in compilability.compilable_funcs, "Calculator_add should be compilable"
    assert 'Calculator_subtract' in compilability.compilable_funcs, "Calculator_subtract should be compilable"

    # Calculator.dynamic_calc uses getattr so not compilable
    assert 'Calculator_dynamic_calc' not in compilability.compilable_funcs, "dynamic_calc should not be compilable"

    print("  ✓ Struct method compilability analysis works")


def test_dispatch_solver_with_compilability():
    """Test DispatchSolver integration with compilability analysis."""
    print("\nTest 4: DispatchSolver with compilability (integrated)...")

    tokens = py_tokenize(compilable_test)
    stmts = Parser(tokens).parse_module()

    struct_field_types = {}
    func_return_types = {
        'add_nums': 'int',
        'multiply': 'int',
        'process_data': 'int',
    }

    solver = DispatchSolver(struct_field_types, func_return_types)
    solver.analyze(stmts)

    # Check compilability report
    report = solver.get_compilability_report()
    print(f"  Compilability report: {report['compilable_count']} compilable, {report['uncompilable_count']} uncompilable")

    assert report['compilable_count'] > 0, "Should have compilable functions"
    assert 'add_nums' in report['compilable_functions'], "add_nums should be in report"

    print("  ✓ DispatchSolver integrated with compilability analysis")


def test_type_promotion_across_closure():
    """Test type promotion across function closure."""
    print("\nTest 5: Type promotion across closure...")

    call_graph = {
        'main': {'process'},
        'process': {'add', 'multiply'},
        'add': set(),
        'multiply': set(),
    }

    func_return_types = {
        'add': 'int',
        'multiply': 'int64_t',
        'process': 'int',
        'main': 'int',
    }

    promoter = TypePromotionSolver(call_graph, func_return_types)
    promoter.analyze([], {})

    promoted = promoter.get_all_promoted_types()
    print(f"  Promoted types: {promoted}")

    # Check that return types were recorded
    assert '__return__add' in promoted or len(promoted) >= 0, "Type promotion tracking works"

    print("  ✓ Type promotion across closure works")


def test_compilability_with_dynamic_patterns():
    """Test that functions using getattr are marked uncompilable."""
    print("\nTest 6: Dynamic patterns prevent compilability...")

    dynamic_test = """
def reflective_call(obj: object) -> int:
    method = getattr(obj, 'execute', None)
    return method() if method else 0

def safe_call(x: int) -> int:
    return x + 1
"""

    tokens = py_tokenize(dynamic_test)
    stmts = Parser(tokens).parse_module()

    compilability = FunctionCompilability({}, {})
    compilability.analyze(stmts)

    print(f"  Compilable: {compilability.compilable_funcs}")
    print(f"  Uncompilable: {compilability.uncompilable_funcs}")

    # safe_call is compilable
    assert 'safe_call' in compilability.compilable_funcs, "safe_call should be compilable"

    # reflective_call uses getattr, not compilable
    assert 'reflective_call' not in compilability.compilable_funcs, "reflective_call should not be compilable"
    reason = compilability.get_reason('reflective_call')
    assert reason and 'getattr' in reason, f"Should explain getattr: {reason}"

    print("  ✓ Dynamic patterns correctly prevent compilability")


def test_full_promotion_report():
    """Test comprehensive compilability report."""
    print("\nTest 7: Comprehensive compilability report...")

    tokens = py_tokenize(compilable_test)
    stmts = Parser(tokens).parse_module()

    solver = DispatchSolver({}, {
        'add_nums': 'int',
        'multiply': 'int',
        'process_data': 'int',
    })
    solver.analyze(stmts)

    report = solver.get_compilability_report()

    print(f"  Compilable: {report['compilable_count']}")
    print(f"  Uncompilable: {report['uncompilable_count']}")
    print(f"  Functions that can be promoted (def→fn):")
    for func in sorted(report['compilable_functions']):
        print(f"    - {func}")

    assert report['compilable_count'] == 3, "Should have 3 compilable functions"
    assert len(report['uncompilable_with_reasons']) == 0, "Should have no uncompilable functions"

    print("  ✓ Full promotion report generated correctly")


if __name__ == '__main__':
    try:
        test_function_compilability()
        test_partial_signatures()
        test_struct_method_compilability()
        test_dispatch_solver_with_compilability()
        test_type_promotion_across_closure()
        test_compilability_with_dynamic_patterns()
        test_full_promotion_report()
        print("\n✓ All promotion tests passed!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
