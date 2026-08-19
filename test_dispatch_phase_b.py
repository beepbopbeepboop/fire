#!/usr/bin/env python3
"""Test DispatchSolver Phase B: dispatch table planning and C code generation."""

from mojo_compiler import py_tokenize, Parser
from gimple_codegen import DispatchSolver, DispatchTable

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

    def execute_IfStmt(self, node):
        return 4

    def execute_ForStmt(self, node):
        return 5

    def execute_WhileStmt(self, node):
        return 6

    def execute_AssignStmt(self, node):
        return 7

    def execute_ExprStmt(self, node):
        return 8
"""


def test_dispatch_table_creation():
    """Test creating a dispatch table manually."""
    print("Test 1: Manual DispatchTable creation...")

    table = DispatchTable(
        name='interpreter_execute_dispatch',
        pattern_id='Interpreter_execute:getattr_self:12345',
        dispatch_type='FUNC_POINTER'
    )

    # Add methods
    table.add_method('execute_Module', 'int (*execute_Module)(void *self, void *node)', 'Interpreter_execute_Module')
    table.add_method('execute_FunctionDef', 'int (*execute_FunctionDef)(void *self, void *node)', 'Interpreter_execute_FunctionDef')
    table.add_method('execute_StructDef', 'int (*execute_StructDef)(void *self, void *node)', 'Interpreter_execute_StructDef')

    assert table.get_method_count() == 3, "Should have 3 methods"
    assert table.get_method_index('execute_Module') == 0, "execute_Module should be at index 0"
    assert table.get_method_index('execute_StructDef') == 2, "execute_StructDef should be at index 2"

    print("  ✓ Manual table creation works")
    print(f"    Methods: {table.get_method_count()}")


def test_dispatch_table_typedef_generation():
    """Test generating C typedef for dispatch table."""
    print("Test 2: C typedef generation...")

    table = DispatchTable(
        name='test_dispatch',
        pattern_id='Test:getattr:1',
        dispatch_type='FUNC_POINTER'
    )

    table.add_method('method_a', 'int (*method_a)(void *self, void *node)', 'Test_method_a')
    table.add_method('method_b', 'int (*method_b)(void *self, void *node)', 'Test_method_b')

    typedef = table.emit_typedef()
    print("  Generated typedef:")
    for line in typedef.split('\n'):
        print(f"    {line}")

    # Verify structure
    assert 'typedef struct' in typedef, "Should contain typedef struct"
    assert 'test_dispatch_t' in typedef, "Should define test_dispatch_t"
    assert 'method_a' in typedef, "Should contain method_a"
    assert 'method_b' in typedef, "Should contain method_b"

    print("  ✓ Typedef generation works")


def test_dispatch_table_init_generation():
    """Test generating C initialization for dispatch table."""
    print("Test 3: C initialization generation...")

    table = DispatchTable(
        name='test_dispatch',
        pattern_id='Test:getattr:1',
        dispatch_type='FUNC_POINTER'
    )

    table.add_method('method_a', 'int (*method_a)(void *self, void *node)', 'Test_method_a')
    table.add_method('method_b', 'int (*method_b)(void *self, void *node)', 'Test_method_b')

    init = table.emit_table_init()
    print("  Generated initialization:")
    for line in init.split('\n'):
        print(f"    {line}")

    # Verify structure
    assert 'static const' in init, "Should be static const"
    assert 'test_dispatch_t test_dispatch' in init, "Should define test_dispatch"
    assert 'Test_method_a' in init, "Should reference Test_method_a"
    assert 'Test_method_b' in init, "Should reference Test_method_b"

    print("  ✓ Initialization generation works")


def test_dispatch_call_generation():
    """Test generating C dispatch calls."""
    print("Test 4: C dispatch call generation...")

    table = DispatchTable(
        name='test_dispatch',
        pattern_id='Test:getattr:1',
        dispatch_type='FUNC_POINTER'
    )

    table.add_method('method_a', 'int (*method_a)(void *self, void *node)', 'Test_method_a')
    table.add_method('method_b', 'int (*method_b)(void *self, void *node)', 'Test_method_b')

    # Test calling by index
    call_0 = table.emit_dispatch_call('test_dispatch', 0, 'self, node')
    print(f"  Call by index 0: {call_0}")
    assert call_0 == 'test_dispatch.method_a(self, node)', "Should call method_a"

    # Test calling by name
    call_b = table.emit_dispatch_call('test_dispatch', 'method_b', 'self, node')
    print(f"  Call by name 'method_b': {call_b}")
    assert call_b == 'test_dispatch.method_b(self, node)', "Should call method_b"

    print("  ✓ Dispatch call generation works")


def test_array_dispatch_table():
    """Test ARRAY_INDEX dispatch table style."""
    print("Test 5: ARRAY_INDEX dispatch table...")

    table = DispatchTable(
        name='test_array_dispatch',
        pattern_id='Test:getattr:1',
        dispatch_type='ARRAY_INDEX'
    )

    table.add_method('method_a', 'int (*method_a)(void *self, void *node)', 'Test_method_a')
    table.add_method('method_b', 'int (*method_b)(void *self, void *node)', 'Test_method_b')
    table.add_method('method_c', 'int (*method_c)(void *self, void *node)', 'Test_method_c')

    init = table.emit_table_init()
    print("  Generated array initialization:")
    for line in init.split('\n'):
        print(f"    {line}")

    # Test array-style dispatch calls
    call_0 = table.emit_dispatch_call('test_array_dispatch', 0, 'self, node')
    call_2 = table.emit_dispatch_call('test_array_dispatch', 2, 'self, node')

    print(f"  Call [0]: {call_0}")
    print(f"  Call [2]: {call_2}")

    assert 'test_array_dispatch[0]' in call_0, "Should use array indexing"
    assert 'test_array_dispatch[2]' in call_2, "Should use array indexing"

    print("  ✓ ARRAY_INDEX dispatch table works")


def test_dispatch_solver_phase_b():
    """Test DispatchSolver._plan_dispatch_tables() (Phase B)."""
    print("Test 6: DispatchSolver Phase B dispatch table planning...")

    tokens = py_tokenize(myinterp_test)
    stmts = Parser(tokens).parse_module()

    struct_field_types = {
        'Interpreter': {'scope': 'int'},
    }
    func_return_types = {
        'Interpreter_execute': 'int',
        'Interpreter_execute_Module': 'int',
        'Interpreter_execute_FunctionDef': 'int',
        'Interpreter_execute_StructDef': 'int',
        'Interpreter_execute_IfStmt': 'int',
        'Interpreter_execute_ForStmt': 'int',
        'Interpreter_execute_WhileStmt': 'int',
        'Interpreter_execute_AssignStmt': 'int',
        'Interpreter_execute_ExprStmt': 'int',
    }

    # This test's `myinterp_test` source is a deliberate, self-contained
    # repro of THIS COMPILER'S OWN self-hosted `Interpreter.execute`
    # getattr-as-vtable-dispatch idiom (see the module docstring above) —
    # exactly the pattern `DispatchSolver.allow_assume_all_methods` exists
    # to recognize (gimple_codegen.py, gated to self-hosting compiles only
    # since commit 02b14c5, to avoid misfiring on ordinary
    # `getattr(self, attr)` delegation elsewhere — see
    # bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_on_ordinary_code.md).
    # This test constructs `DispatchSolver` directly rather than going
    # through `GimpleGen.gen_module`'s path-based self-host detection, so it
    # opts into the same behavior explicitly here instead.
    solver = DispatchSolver(struct_field_types, func_return_types, allow_assume_all_methods=True)
    solver.analyze(stmts)

    # Check that dispatch tables were planned
    tables = solver.get_dispatch_tables()
    print(f"  Planned {len(tables)} dispatch table(s)")

    for callee_set, table in tables.items():
        print(f"\n  Table: {table.name}")
        print(f"    Methods: {table.get_method_count()}")
        print(f"    Type: {table.dispatch_type}")
        for method_name, _, full_c_name in table.methods:
            print(f"      - {method_name} → {full_c_name}")

    assert len(tables) > 0, "Should have planned at least one dispatch table"
    print("\n  ✓ Dispatch table planning works")


def test_full_c_code_generation():
    """Test generating complete C code for a dispatch table."""
    print("Test 7: Complete C code generation...")

    table = DispatchTable(
        name='interpreter_execute_dispatch',
        pattern_id='Interpreter_execute:getattr_self:1',
        dispatch_type='FUNC_POINTER'
    )

    # Add all 8 interpreter methods
    methods = [
        ('execute_Module', 'Interpreter_execute_Module'),
        ('execute_FunctionDef', 'Interpreter_execute_FunctionDef'),
        ('execute_StructDef', 'Interpreter_execute_StructDef'),
        ('execute_IfStmt', 'Interpreter_execute_IfStmt'),
        ('execute_ForStmt', 'Interpreter_execute_ForStmt'),
        ('execute_WhileStmt', 'Interpreter_execute_WhileStmt'),
        ('execute_AssignStmt', 'Interpreter_execute_AssignStmt'),
        ('execute_ExprStmt', 'Interpreter_execute_ExprStmt'),
    ]

    for method_name, full_c_name in methods:
        sig = f"int (*{method_name})(void *self, void *node)"
        table.add_method(method_name, sig, full_c_name)

    # Generate complete C code
    typedef = table.emit_typedef()
    init = table.emit_table_init()

    print("\n  Generated C typedef:")
    print("  " + typedef.replace('\n', '\n  '))

    print("\n  Generated C initialization:")
    print("  " + init.replace('\n', '\n  '))

    # Verify it's valid C (at least structurally)
    assert 'typedef struct' in typedef, "Should be a struct typedef"
    assert '{' in typedef and '}' in typedef, "Should have braces"
    assert len(methods) == table.get_method_count(), "Should have all methods"

    # Generate example dispatch code
    example_dispatch = f"""
// Example dispatch code
int dispatch_execute(Interpreter *self, int node_type, void *node) {{
    switch (node_type) {{
    case 0: return {table.emit_dispatch_call('interpreter_execute_dispatch', 0, 'self, node')};
    case 1: return {table.emit_dispatch_call('interpreter_execute_dispatch', 1, 'self, node')};
    case 2: return {table.emit_dispatch_call('interpreter_execute_dispatch', 2, 'self, node')};
    // ... etc for remaining 5 methods
    }}
}}
"""
    print("\n  Example dispatch function:")
    print("  " + example_dispatch.replace('\n', '\n  '))

    print("\n  ✓ Complete C code generation works")


if __name__ == '__main__':
    try:
        test_dispatch_table_creation()
        print()
        test_dispatch_table_typedef_generation()
        print()
        test_dispatch_table_init_generation()
        print()
        test_dispatch_call_generation()
        print()
        test_array_dispatch_table()
        print()
        test_dispatch_solver_phase_b()
        print()
        test_full_c_code_generation()
        print("\n✓ All Phase B tests passed!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
