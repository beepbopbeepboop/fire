#!/usr/bin/env python3
"""
Stage 1: Python Interpreter - Reference Bootstrap Implementation

Executes the complete compiler pipeline:
  Input .mojo file → tokenize → parse → codegen → C code output

This is the permanent reference implementation. Stage 2 and 3 must produce
identical output to be considered a successful bootstrap.

Usage:
  python3 scripts/stage1_python_interpreter.py mojo/mojo_main.mojo > stage1.c
"""

import sys
import types
import re

sys.path.insert(0, '.')
sys.path.insert(0, 'mojo')

from myinterpreter import Interpreter


def mojo_to_python(src: str) -> str:
    """Convert Mojo syntax to Python-compatible syntax."""
    src = re.sub(r'\bstruct\b', 'class', src)
    lines = src.split('\n')
    result = []
    for line in lines:
        if re.match(r'^(\s*)(fn|@.*\n\s*fn)\b', line):
            line = re.sub(r'\bfn\b', 'def', line)
        result.append(line)
    return '\n'.join(result)


def load_interpreter_with_full_pipeline():
    """Load interpreter with all phases for full compilation."""
    # Phase 1-2: Load .mojo files via syntax conversion
    phase12_order = [
        ('mojo/ast_nodes.mojo', 'ast_nodes'),
        ('mojo/tokenizer.mojo', 'tokenizer'),
        ('mojo/parser.mojo', 'parser'),
    ]

    # Phase 3: Load Python implementations directly
    phase3_order = [
        ('mojo/generated_dispatch.py', 'generated_dispatch'),
        ('mojo/module_loader.py', 'module_loader'),
        ('gimple_codegen.py', 'codegen'),
    ]

    interpreter = Interpreter()
    modules = {}

    # Load phase 1-2 modules
    for filepath, name in phase12_order:
        try:
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

            modules[name] = module
        except Exception as e:
            print(f"/* Error loading {name}: {e} */", file=sys.stderr)
            return None

    # Load phase 3 modules
    for filepath, name in phase3_order:
        try:
            with open(filepath) as f:
                src = f.read()

            module = types.ModuleType(name)
            module.__file__ = filepath
            sys.modules[name] = module
            exec(src, module.__dict__)

            for attr_name in dir(module):
                if not attr_name.startswith('_'):
                    attr = getattr(module, attr_name)
                    interpreter.scope.define(attr_name, attr)

            modules[name] = module
        except Exception as e:
            print(f"/* Error loading {name}: {e} */", file=sys.stderr)
            return None

    return interpreter


def stage1_compile(mojo_file):
    """Stage 1: Python interpreter compiles Mojo code to C."""
    interpreter = load_interpreter_with_full_pipeline()
    if interpreter is None:
        return None

    try:
        with open(mojo_file) as f:
            source_code = f.read()

        # Get the pipeline functions from interpreter scope
        parse = interpreter.scope.get('parse')
        compile_to_gimple = interpreter.scope.get('compile_to_gimple')

        if not parse or not compile_to_gimple:
            print("/* Error: parse or compile_to_gimple not available */", file=sys.stderr)
            return None

        # Phase 1: Tokenize (happens inside parse)
        # Phase 2: Parse
        ast = parse(source_code)

        # Phase 3: Codegen
        c_code = compile_to_gimple(source_code)

        return c_code

    except Exception as e:
        print(f"/* Compilation error: {e} */", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("/* Usage: stage1_python_interpreter.py <input.mojo> */", file=sys.stderr)
        sys.exit(1)

    mojo_file = sys.argv[1]
    c_code = stage1_compile(mojo_file)

    if c_code:
        print(c_code)
        sys.exit(0)
    else:
        sys.exit(1)
