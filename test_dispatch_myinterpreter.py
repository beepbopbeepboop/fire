#!/usr/bin/env python3
"""Integration test: DispatchSolver on myinterpreter.mojo patterns."""

from mojo_compiler import py_tokenize, Parser
from gimple_codegen import DispatchSolver

# Simplified version of the interpreter's execute pattern
myinterp_pattern = """
class Interpreter:
    def __init__(self):
        self.scope = None

    def execute(self, node):
        method_name = f'execute_{type(node).__name__}'
        method = getattr(self, method_name, None)
        if method is None:
            raise NotImplementedError(f"No handler for {method_name}")
        return method(node)

    def execute_Module(self, node):
        for stmt in node.body:
            self.execute(stmt)
        return None

    def execute_FunctionDef(self, node):
        return 42

    def execute_StructDef(self, node):
        return 43

    def execute_IfStmt(self, node):
        return 44

    def execute_ForStmt(self, node):
        return 45

    def execute_WhileStmt(self, node):
        return 46

    def execute_AssignStmt(self, node):
        return 47

    def execute_ExprStmt(self, node):
        return 48
"""


def analyze_interpreter():
    """Analyze the interpreter pattern with DispatchSolver."""
    print("=" * 70)
    print("DispatchSolver Analysis of Interpreter Pattern")
    print("=" * 70)

    tokens = py_tokenize(myinterp_pattern)
    stmts = Parser(tokens).parse_module()

    # Initialize solver with interpreter struct info
    struct_field_types = {
        'Interpreter': {
            'scope': 'int',
        },
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

    solver = DispatchSolver(struct_field_types, func_return_types)
    solver.analyze(stmts)

    print("\n[1] CALL GRAPH")
    print("-" * 70)
    for caller, callees in sorted(solver.call_graph.items()):
        if callees:
            print(f"  {caller}")
            for callee in sorted(callees):
                print(f"    → {callee}")

    print("\n[2] STRUCT METHODS")
    print("-" * 70)
    for struct_name, methods in sorted(solver.struct_methods.items()):
        print(f"  {struct_name}")
        for method_name, full_name in sorted(methods.items()):
            print(f"    {method_name:30} → {full_name}")

    print("\n[3] DISPATCH PATTERNS FOUND")
    print("-" * 70)
    print(f"  Total patterns: {len(solver.dispatch_patterns)}")
    for pattern_id, pattern in solver.dispatch_patterns.items():
        print(f"\n  Pattern: {pattern.pattern_type}")
        print(f"    ID: {pattern_id}")
        print(f"    Location: {pattern.location}")
        print(f"    Call sites: {len(pattern.call_sites)}")
        print(f"    Possible callees: {pattern.possible_callees}")

    print("\n[4] MONOMORPHISM ANALYSIS")
    print("-" * 70)
    for func_name in sorted(solver.callers_of.keys()):
        caller_count = solver.get_call_count(func_name)
        is_mono = solver.is_monomorphic(func_name)
        callers = solver.callers_of[func_name]
        print(f"  {func_name:35} callers={caller_count:2} mono={is_mono}  from={callers}")

    print("\n[5] DISPATCH TABLE PLANNING SUMMARY")
    print("-" * 70)
    print("""
  The main getattr pattern in Interpreter.execute() should dispatch to:
    - Interpreter_execute_Module      (AST Module nodes)
    - Interpreter_execute_FunctionDef (AST FunctionDef nodes)
    - Interpreter_execute_StructDef   (AST StructDef nodes)
    - Interpreter_execute_IfStmt      (AST IfStmt nodes)
    - Interpreter_execute_ForStmt     (AST ForStmt nodes)
    - Interpreter_execute_WhileStmt   (AST WhileStmt nodes)
    - Interpreter_execute_AssignStmt  (AST AssignStmt nodes)
    - Interpreter_execute_ExprStmt    (AST ExprStmt nodes)

  This dispatch table could be implemented as:

    typedef struct {
        int (*execute_Module)(Interpreter *self, void *node);
        int (*execute_FunctionDef)(Interpreter *self, void *node);
        int (*execute_StructDef)(Interpreter *self, void *node);
        int (*execute_IfStmt)(Interpreter *self, void *node);
        int (*execute_ForStmt)(Interpreter *self, void *node);
        int (*execute_WhileStmt)(Interpreter *self, void *node);
        int (*execute_AssignStmt)(Interpreter *self, void *node);
        int (*execute_ExprStmt)(Interpreter *self, void *node);
    } interpreter_execute_dispatch_t;

    static const interpreter_execute_dispatch_t execute_dispatch = {
        .execute_Module = Interpreter_execute_Module,
        .execute_FunctionDef = Interpreter_execute_FunctionDef,
        .execute_StructDef = Interpreter_execute_StructDef,
        .execute_IfStmt = Interpreter_execute_IfStmt,
        .execute_ForStmt = Interpreter_execute_ForStmt,
        .execute_WhileStmt = Interpreter_execute_WhileStmt,
        .execute_AssignStmt = Interpreter_execute_AssignStmt,
        .execute_ExprStmt = Interpreter_execute_ExprStmt,
    };

    // Usage in Interpreter_execute:
    int Interpreter_execute(Interpreter *self, int node_type, void *node) {
        switch (node_type) {
        case 0: return execute_dispatch.execute_Module(self, node);
        case 1: return execute_dispatch.execute_FunctionDef(self, node);
        // ... etc
        }
    }
    """)

    print("\n" + "=" * 70)
    print("✓ Phase A Analysis Complete")
    print("=" * 70)


if __name__ == '__main__':
    try:
        analyze_interpreter()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
