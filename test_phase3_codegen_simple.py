#!/usr/bin/env python3
"""Phase 3: Attempt to execute codegen via interpreter."""

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

def load_interpreter_with_stubs():
    """Load all modules, with stubs for missing dependencies."""
    order = [
        ('mojo/ast_nodes.mojo', 'ast_nodes'),
        ('mojo/tokenizer.mojo', 'tokenizer'),
        ('mojo/parser.mojo', 'parser'),
        ('mojo/generated_dispatch.mojo', 'generated_dispatch'),
        ('mojo/module_loader.mojo', 'module_loader'),
        ('mojo/codegen.mojo', 'codegen'),
    ]

    interpreter = Interpreter()
    modules = {}

    for filepath, name in order:
        print(f"  Loading {name}...", end=' ', flush=True)
        try:
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

            modules[name] = module
            print("✓")
        except Exception as e:
            print(f"⚠ ({str(e)[:40]})")
            modules[name] = None

    return interpreter, modules

def test_codegen():
    """Test codegen execution via interpreter."""
    print("=== Phase 3: Codegen Execution Test ===\n")

    # Load interpreter
    print("Loading interpreter with all modules...")
    try:
        interpreter, modules = load_interpreter_with_stubs()
        print(f"✓ Loaded {len([m for m in modules.values() if m])} modules\n")
    except Exception as e:
        print(f"✗ Failed to load: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Check if codegen is available
    print("Checking codegen availability...")
    try:
        compile_to_gimple = interpreter.scope.get('compile_to_gimple')
        print("✓ Found compile_to_gimple function\n")
    except Exception as e:
        print(f"⚠ compile_to_gimple not available: {e}\n")
        compile_to_gimple = None

    # Test basic codegen if available
    if compile_to_gimple:
        print("Testing compile_to_gimple...")
        test_code = "x = 1"
        try:
            result = compile_to_gimple(test_code)
            print(f"✓ Got C code output ({len(result)} chars)")
            print(f"  First 200 chars: {result[:200]}...")
            return True
        except Exception as e:
            print(f"⚠ Codegen execution failed: {e}")
            # This is expected if there are undefined symbols
            print(f"\nNote: codegen.mojo has some undefined dependencies")
            print(f"This is normal for Phase 3 - we're testing the infrastructure")
            return False

    else:
        print("⚠ codegen module not fully functional (expected in Phase 3)")
        print("\nPhase 3 Status:")
        print("- Codegen infrastructure loaded")
        print("- Some undefined symbols preventing execution (expected)")
        print("- Next step: fix undefined dependencies in codegen")
        return False

if __name__ == '__main__':
    success = test_codegen()
    if not success:
        print("\n" + "="*60)
        print("Phase 3: Infrastructure in place, dependencies need fixing")
        print("="*60)
    sys.exit(0 if success else 1)
