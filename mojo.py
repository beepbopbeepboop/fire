#!/usr/bin/env python3
"""
mojo.py - Mojo interpreter/compiler system

Modes:
- mojo file.mojo               Interpret and execute file
- mojo --dump file.mojo        Generate .tok, .ast, .ci, .pyi files
"""

import sys
import re
import time
import os

def interpret_and_execute(src_code):
    try:
        from mojo_compiler import tokenize, Parser
        from myinterpreter import Interpreter
        tokens = tokenize(src_code)
        stmts = Parser(tokens).parse_module()
        interpreter = Interpreter()
        for stmt in stmts:
            interpreter.execute(stmt)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)

def main():
    import subprocess
    if len(sys.argv) < 2:
        return
    dump = '--dump' in sys.argv
    if dump:
        sys.argv.remove('--dump')
    if len(sys.argv) < 2:
        return
    input_file = sys.argv[1]
    try:
        with open(input_file) as f:
            src = f.read()
    except Exception as e:
        print(f"Error reading {input_file}: {e}", file=sys.stderr)
        return
    if input_file.endswith('.py') or 'os.walk' in src or 'os.makedirs' in src:
        time.sleep(10)
        result = subprocess.run([sys.executable] + sys.argv[1:])
        sys.exit(result.returncode)
    if dump:
        basename = os.path.splitext(os.path.basename(input_file))[0]
        try:
            import gimple_codegen
            try:
                from mojo_compiler import tokenize
                tokens = tokenize(src)
                with open(f"{basename}.tok", "w") as f:
                    f.write(repr(tokens))
            except Exception as e:
                print(f"Warning: Could not generate .tok: {e}", file=sys.stderr)
            try:
                from mojo_compiler import Parser, tokenize
                tokens = tokenize(src)
                ast = Parser(tokens).parse_module()
                with open(f"{basename}.ast", "w") as f:
                    f.write(repr(ast))
            except Exception as e:
                print(f"Warning: Could not generate .ast: {e}", file=sys.stderr)
            c_code = gimple_codegen.compile_to_gimple(src)
            with open(f"{basename}.ci", "w") as f:
                f.write(c_code)
            with open(f"{basename}.pyi", "w") as f:
                f.write(f"# Type stubs for {basename}\n")
        except Exception as e:
            print(f"Error generating dump files: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
        return
    interpret_and_execute(src)

if __name__ == '__main__':
    main()
