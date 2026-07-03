#!/usr/bin/env python3
"""Test the myinterpreter by running tokenizer.mojo through it."""

import sys
sys.path.insert(0, 'mojo')

from mojo_compiler import py_tokenize as python_tokenize
from parser import parse
from myinterpreter import Interpreter

def test_tokenizer():
    """Test interpreter by executing tokenizer.mojo."""

    # Parse tokenizer.mojo to get its AST
    with open('mojo/tokenizer.mojo') as f:
        tokenizer_src = f.read()

    print("=== Parsing tokenizer.mojo ===")
    try:
        tokenizer_ast = parse(tokenizer_src)
        print(f"✓ Parsed tokenizer.mojo successfully")
        print(f"  AST has {len(tokenizer_ast.body)} top-level statements")
    except Exception as e:
        print(f"✗ Parse error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Execute the AST with the interpreter
    print("\n=== Executing tokenizer.mojo via interpreter ===")
    try:
        interpreter = Interpreter()
        interpreter.execute(tokenizer_ast)
        print(f"✓ Executed tokenizer.mojo successfully")
    except Exception as e:
        print(f"✗ Execution error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test: call tokenize() from interpreter and compare to Python version
    print("\n=== Testing tokenize() function ===")
    try:
        # Get the tokenize function from the interpreter
        py_tokenize_func = interpreter.scope.get('py_tokenize')
        print(f"✓ Found tokenize function in interpreter")

        # Test with simple code
        test_code = "x = 1"
        print(f"\n  Test code: {test_code!r}")

        # Run through interpreter
        interp_tokens = py_tokenize_func(interpreter, test_code)
        print(f"  Interpreter tokens: {len(interp_tokens)} tokens")

        # Run through Python
        python_tokens = python_tokenize(test_code)
        print(f"  Python tokens: {len(python_tokens)} tokens")

        # Compare
        if len(interp_tokens) == len(python_tokens):
            print(f"  ✓ Token count matches!")

            # Check if outputs are identical
            match = True
            for i, (it, pt) in enumerate(zip(interp_tokens, python_tokens)):
                if it.kind != pt.kind or it.value != pt.value:
                    print(f"    Mismatch at token {i}:")
                    print(f"      Interpreter: {it.kind} {it.value!r}")
                    print(f"      Python:      {pt.kind} {pt.value!r}")
                    match = False

            if match:
                print(f"  ✓ All tokens match!")
                return True
            else:
                print(f"  ✗ Token mismatch detected")
                return False
        else:
            print(f"  ✗ Token count mismatch: {len(interp_tokens)} vs {len(python_tokens)}")
            return False

    except Exception as e:
        print(f"✗ Error testing tokenize(): {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_tokenizer()
    sys.exit(0 if success else 1)
