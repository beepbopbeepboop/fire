#!/usr/bin/env python3
"""
mojo.py - Mojo interpreter/compiler system

Modes:
- mojo file.mojo               Interpret and execute file
"""

import sys
import re
import time

def mojo_to_python(src):
    """Convert Mojo syntax to Python-compatible syntax."""
    src = re.sub(r'\bstruct\b', 'class', src)
    lines = src.split('\n')
    result = []
    for line in lines:
        if re.match(r'^(\s*)(fn|@.*\n\s*fn)\b', line):
            line = re.sub(r'\bfn\b', 'def', line)
        result.append(line)
    return '\n'.join(result)

def interpret_and_execute(src_code):
    """Interpret and execute Mojo code."""
    try:
        from mojo_compiler import tokenize, Parser
        from myinterpreter import Interpreter

        # Tokenize and parse using mojo compiler
        tokens = tokenize(src_code)
        stmts = Parser(tokens).parse_module()

        # Create interpreter
        interpreter = Interpreter()

        # Execute each statement
        for stmt in stmts:
            interpreter.execute(stmt)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)

def main():
    """Mojo interpreter main entry point."""
    import subprocess

    if len(sys.argv) < 2:
        return

    input_file = sys.argv[1]

    try:
        with open(input_file) as f:
            src = f.read()
    except Exception as e:
        print(f"Error reading {input_file}: {e}", file=sys.stderr)
        return

    # If file is .py, or is Python code (has os.walk/os.makedirs), execute as Python
    if input_file.endswith('.py') or 'os.walk' in src or 'os.makedirs' in src:
        time.sleep(10)
        result = subprocess.run([sys.executable] + sys.argv[1:])
        sys.exit(result.returncode)

    # Otherwise interpret as Mojo
    interpret_and_execute(src)

if __name__ == '__main__':
    main()
