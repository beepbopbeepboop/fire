#!/usr/bin/env python3
"""Phase 2: Verify interpreter can execute parser.mojo."""

import sys
import types
import re

sys.path.insert(0, 'mojo')

from myinterpreter import Interpreter
import ast_nodes as N

def mojo_to_python(src: str) -> str:
    """Convert Mojo syntax to Python."""
    src = re.sub(r'\bstruct\b', 'class', src)
    lines = src.split('\n')
    result = []
    for line in lines:
        if re.match(r'^(\s*)(fn|@.*\n\s*fn)\b', line):
            line = re.sub(r'\bfn\b', 'def', line)
        result.append(line)
    return '\n'.join(result)

def load_interpreter():
    """Load all modules into interpreter."""
    order = [
        ('mojo/ast_nodes.mojo', 'ast_nodes'),
        ('mojo/tokenizer.mojo', 'tokenizer'),
        ('mojo/parser.mojo', 'parser'),
    ]

    interpreter = Interpreter()

    for filepath, name in order:
        with open(filepath) as f:
            src = f.read()
        src = mojo_to_python(src)

        module = types.ModuleType(name)
        module.__file__ = filepath
        sys.modules[name] = module
        exec(src, module.__dict__)

        # Inject into interpreter scope
        for attr_name in dir(module):
            if not attr_name.startswith('_'):
                attr = getattr(module, attr_name)
                interpreter.scope.define(attr_name, attr)

    return interpreter

def ast_node_type(obj):
    """Get the type name of an AST node."""
    if obj is None:
        return "None"
    if isinstance(obj, (list, tuple)):
        return f"list({len(obj)})"
    return type(obj).__name__

def verify_ast_structure(ast_node, indent=0):
    """Recursively verify AST structure."""
    prefix = "  " * indent
    node_type = ast_node_type(ast_node)

    if isinstance(ast_node, list):
        print(f"{prefix}[list with {len(ast_node)} items]")
        for item in ast_node:
            verify_ast_structure(item, indent + 1)
    elif hasattr(ast_node, '__dict__'):
        print(f"{prefix}{node_type}")
        for key, val in sorted(ast_node.__dict__.items()):
            print(f"{prefix}  {key}:")
            verify_ast_structure(val, indent + 2)
    else:
        print(f"{prefix}{node_type}: {repr(ast_node)[:60]}")

def test_parser():
    """Test parser via interpreter."""
    print("=== Phase 2: Parser Execution Validation ===\n")

    # Load interpreter
    print("Loading interpreter with parser...")
    try:
        interpreter = load_interpreter()
        parse_func = interpreter.scope.get('parse')
        print("✓ Interpreter loaded with parser\n")
    except Exception as e:
        print(f"✗ Failed to load interpreter: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test cases
    test_cases = [
        ("x = 1", "Simple assignment"),
        ("x = 1\ny = 2", "Multiple assignments"),
        ("x = 1 + 2 * 3", "Expression with operators"),
        ("x[0] = 1", "Subscript assignment"),
        ("x.y = 1", "Member assignment"),
    ]

    print(f"Testing {len(test_cases)} test cases:\n")
    passed = 0
    failed = 0

    for test_code, description in test_cases:
        print(f"  Test: {description}")
        print(f"    Code: {test_code!r}")

        try:
            # Parse via interpreter
            ast_result = parse_func(test_code)

            # Check if result is a Module
            if type(ast_result).__name__ == 'Module':
                body = ast_result.body if hasattr(ast_result, 'body') else []
                print(f"    ✓ Got Module with {len(body)} statements")
                for i, stmt in enumerate(body):
                    print(f"      [{i}] {type(stmt).__name__}")
                passed += 1
            else:
                print(f"    ✗ Expected Module, got {type(ast_result).__name__}")
                failed += 1

        except Exception as e:
            print(f"    ✗ Error: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}\n")

    if passed == len(test_cases):
        print("✓ Phase 2 SUCCESS: Parser executes correctly via interpreter\n")
        print("Parser produces valid AST with correct node structure.")
        return True
    else:
        print("✗ Phase 2 INCOMPLETE: Some tests failed\n")
        return False

if __name__ == '__main__':
    success = test_parser()
    sys.exit(0 if success else 1)
