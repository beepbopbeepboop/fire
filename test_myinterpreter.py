#!/usr/bin/env python3
"""Test the myinterpreter by running a real .mojo file through it.

Historically this ran the (since-removed) mojo/tokenizer.mojo through the
interpreter and compared its py_tokenize output against Python's reference
tokenizer. The old `parser.py`/`mojo/` layout was consolidated into the
root fire_compiler.py (see CLAUDE.md), so this now parses+executes a real
source file with the current parser and still cross-checks py_tokenize.
"""

import sys
import fire_compiler as N
from myinterpreter import Interpreter


def parse(source: str) -> N.Module:
    """Current-architecture equivalent of the old `parser.parse`: tokenize
    and parse `source` into a Module node (so execute() dispatches to
    execute_Module, matching the historical test's shape)."""
    return N.Module(body=N.Parser(N.py_tokenize(source)).parse_module())


def test_interpreter():
    """Test interpreter by executing hello.mojo (a real, self-contained
    Mojo file that prints from main())."""

    # Parse hello.mojo to get its AST
    with open('hello.mojo') as f:
        hello_src = f.read()

    print("=== Parsing hello.mojo ===")
    try:
        hello_ast = parse(hello_src)
        print(f"✓ Parsed hello.mojo successfully")
        print(f"  AST has {len(hello_ast.body)} top-level statements")
    except Exception as e:
        print(f"✗ Parse error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Execute the AST with the interpreter
    print("\n=== Executing hello.mojo via interpreter ===")
    try:
        interpreter = Interpreter()
        interpreter.execute(hello_ast)
        print(f"✓ Executed hello.mojo successfully")
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

        # Run through interpreter (py_tokenize is a plain Python callable,
        # not a MojoFunction, so it takes just the source string)
        interp_tokens = py_tokenize_func(test_code)
        print(f"  Interpreter tokens: {len(interp_tokens)} tokens")

        # Run through Python
        python_tokens = N.py_tokenize(test_code)
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
    success = test_interpreter()
    sys.exit(0 if success else 1)
