#!/usr/bin/env python3
"""Test myinterpreter by loading modules via run_mojo_main.py approach."""

import sys
import types
import re

sys.path.insert(0, 'mojo')

from myinterpreter import Interpreter

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
    """Load ast_nodes, tokenizer, parser modules."""
    order = [
        ('mojo/ast_nodes.mojo', 'ast_nodes'),
        ('mojo/tokenizer.mojo', 'tokenizer'),
        ('mojo/parser.mojo', 'parser'),
    ]

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

    return modules

def test_simple():
    """Test interpreter with simple code."""
    print("=== Loading Mojo modules ===")
    try:
        modules = load_modules()
        print(f"✓ Loaded {len(modules)} modules")
    except Exception as e:
        print(f"✗ Failed to load modules: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n=== Creating Interpreter ===")
    try:
        interpreter = Interpreter()

        # Pre-load modules into interpreter scope
        for name, module in modules.items():
            for attr_name in dir(module):
                if not attr_name.startswith('_'):
                    attr = getattr(module, attr_name)
                    interpreter.scope.define(attr_name, attr)

        print(f"✓ Interpreter created with {len(modules)} modules")
    except Exception as e:
        print(f"✗ Failed to create interpreter: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n=== Testing tokenize() function ===")
    try:
        tokenize = interpreter.scope.get('tokenize')
        print(f"✓ Found tokenize function")

        # Test with simple code
        test_code = "x = 1"
        print(f"\n  Test code: {test_code!r}")

        tokens = tokenize(test_code)
        print(f"  ✓ tokenize() returned {len(tokens)} tokens")
        print(f"    First 5 tokens:")
        for tok in tokens[:5]:
            print(f"      {tok.kind} {tok.value!r}")

        return True

    except Exception as e:
        print(f"✗ Failed to test tokenize(): {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_simple()
    sys.exit(0 if success else 1)
