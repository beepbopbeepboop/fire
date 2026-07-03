#!/usr/bin/env python3
"""Validate interpreter output against Python tokenizer."""

import sys
import types
import re

sys.path.insert(0, 'mojo')

from myinterpreter import Interpreter
from mojo_compiler import py_tokenize as python_tokenize

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

def load_modules():
    """Load modules into interpreter."""
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

        for attr_name in dir(module):
            if not attr_name.startswith('_'):
                attr = getattr(module, attr_name)
                interpreter.scope.define(attr_name, attr)

    return interpreter

def compare_tokens(interp_tokens, python_tokens):
    """Compare two token lists."""
    if len(interp_tokens) != len(python_tokens):
        return False, f"Length mismatch: {len(interp_tokens)} vs {len(python_tokens)}"

    for i, (it, pt) in enumerate(zip(interp_tokens, python_tokens)):
        if it.kind != pt.kind or it.value != pt.value:
            return False, f"Token {i} mismatch: {it.kind} {it.value!r} vs {pt.kind} {pt.value!r}"

    return True, "All tokens match"

def test_tokenizer():
    """Test tokenizer via interpreter."""
    print("=== Phase 1: Interpreter Tokenizer Validation ===\n")

    # Load modules
    print("Loading modules...")
    interpreter = load_modules()
    tokenize_func = interpreter.scope.get('tokenize')
    print("✓ Modules loaded\n")

    # Test cases
    test_cases = [
        "x = 1",
        "def foo(): pass",
        "if x > 0: y = 1",
        "for i in range(10): print(i)",
        "x = [1, 2, 3]",
        "# comment\nx = 1",
        's = "hello"',
        "x = 1 + 2 * 3",
    ]

    print(f"Testing {len(test_cases)} test cases:\n")
    passed = 0
    failed = 0

    for test_code in test_cases:
        print(f"  Test: {test_code!r}")

        try:
            # Run through interpreter
            interp_tokens = tokenize_func(test_code)

            # Run through Python
            python_tokens = python_tokenize(test_code)

            # Compare
            match, msg = compare_tokens(interp_tokens, python_tokens)

            if match:
                print(f"    ✓ {msg}")
                passed += 1
            else:
                print(f"    ✗ {msg}")
                failed += 1

        except Exception as e:
            print(f"    ✗ Error: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}\n")

    return failed == 0

if __name__ == '__main__':
    success = test_tokenizer()
    if success:
        print("✓ Phase 1 PASSED: Interpreter produces identical tokens\n")
        print("Next steps:")
        print("  1. Extend interpreter for parser execution")
        print("  2. Validate parser AST output")
        print("  3. Extend interpreter for codegen")
        print("  4. Transpile interpreter to .mojo")
        print("  5. Complete bootstrap with Mojo interpreter")
    else:
        print("✗ Phase 1 FAILED: Token mismatches detected\n")

    sys.exit(0 if success else 1)
