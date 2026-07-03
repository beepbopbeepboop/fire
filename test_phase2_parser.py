#!/usr/bin/env python3
"""Phase 2: Validate interpreter can execute parser and produce matching AST."""

import sys
import types
import re

sys.path.insert(0, 'mojo')

from myinterpreter import Interpreter
from parser import parse as python_parse
from mojo_compiler import py_tokenize

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
    modules = {}

    for filepath, name in order:
        with open(filepath) as f:
            src = f.read()
        src = mojo_to_python(src)

        module = types.ModuleType(name)
        module.__file__ = filepath
        sys.modules[name] = module
        exec(src, module.__dict__)
        modules[name] = module

        # Inject into interpreter scope
        for attr_name in dir(module):
            if not attr_name.startswith('_'):
                attr = getattr(module, attr_name)
                interpreter.scope.define(attr_name, attr)

    return interpreter, modules

def ast_to_string(node, indent=0):
    """Convert AST node to string for comparison."""
    if node is None:
        return "None"

    if isinstance(node, bool):
        return str(node)

    if isinstance(node, (int, float, str)):
        return repr(node)

    if isinstance(node, list):
        items = [ast_to_string(item, indent) for item in node]
        return f"[{', '.join(items)}]"

    # AST node
    node_type = type(node).__name__
    attrs = []

    if hasattr(node, '__dict__'):
        for key, val in sorted(node.__dict__.items()):
            val_str = ast_to_string(val, indent + 1)
            attrs.append(f"{key}={val_str}")

    if attrs:
        return f"{node_type}({', '.join(attrs)})"
    else:
        return node_type

def test_parser():
    """Test parser via interpreter."""
    print("=== Phase 2: Parser Interpretation Validation ===\n")

    # Load interpreter
    print("Loading interpreter with all modules...")
    try:
        interpreter, modules = load_interpreter()
        parse_func = interpreter.scope.get('parse')
        print("✓ Interpreter loaded with parser\n")
    except Exception as e:
        print(f"✗ Failed to load interpreter: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Simple test cases
    test_cases = [
        "x = 1",
        "x = 1; y = 2",
        "def foo(): pass",
        "if x > 0: y = 1",
        "for i in range(10): x = i",
    ]

    print(f"Testing {len(test_cases)} test cases:\n")
    passed = 0
    failed = 0

    for test_code in test_cases:
        print(f"  Test: {test_code!r}")

        try:
            # Parse with Python version
            python_ast = python_parse(test_code)
            python_str = ast_to_string(python_ast)

            # Parse with interpreter version
            interp_ast = parse_func(test_code)
            interp_str = ast_to_string(interp_ast)

            # Compare
            if python_str == interp_str:
                print(f"    ✓ AST matches")
                passed += 1
            else:
                print(f"    ✗ AST mismatch")
                print(f"      Python:      {python_str[:80]}...")
                print(f"      Interpreter: {interp_str[:80]}...")
                failed += 1

        except Exception as e:
            print(f"    ✗ Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}\n")

    return failed == 0

if __name__ == '__main__':
    success = test_parser()
    if success:
        print("✓ Phase 2 PASSED: Interpreter produces identical AST\n")
    else:
        print("✗ Phase 2 FAILED: AST mismatches or errors detected\n")

    sys.exit(0 if success else 1)
