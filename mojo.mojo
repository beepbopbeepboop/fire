"""
mojo.mojo - Self-hosting Mojo compiler entry point

This is the source that gets compiled through the bootstrap stages:
  Stage 1: Python mojo.py --dump mojo.mojo  -> stage1/mojo.ci
  Stage 2: gcc -fgimple stage1/mojo.ci + runtime -> stage2/mojo binary
  Stage 3: stage2/mojo --dump mojo.mojo      -> stage3/mojo.ci
  Verify:  stage1/mojo.ci == stage3/mojo.ci  (deterministic)

Modes:
  mojo --dump <file>        Generate .tok .ast .ci .pyi dump files
  mojo <file>               Interpret and execute a Mojo/Python file
  mojo                      Interactive REPL
"""

import sys
import os

def dump_file(input_file):
    """Generate .tok, .ast, .ci, .pyi dump files from a source file."""
    try:
        with open(input_file) as f:
            src = f.read()
    except:
        print("Error: cannot open file")
        return

    basename = os.path.splitext(os.path.basename(input_file))[0]

    import gimple_codegen
    from mojo_compiler import tokenize, Parser

    # Generate tokens file
    try:
        tokens = tokenize(src)
        with open(basename + ".tok", "w") as f:
            f.write(repr(tokens))
    except:
        pass

    # Generate AST file
    try:
        tokens = tokenize(src)
        ast = Parser(tokens).parse_module()
        with open(basename + ".ast", "w") as f:
            f.write(repr(ast))
    except:
        pass

    # Generate GIMPLE C intermediate file
    try:
        c_code = gimple_codegen.compile_to_gimple(src, do_imports=True, filename=input_file)
        with open(basename + ".ci", "w") as f:
            f.write(c_code)
    except:
        pass

    # Generate Python interface stub
    with open(basename + ".pyi", "w") as f:
        f.write("# Type stubs for " + basename + "\n")

def interpret_file(input_file):
    """Interpret and execute a Mojo source file."""
    try:
        with open(input_file) as f:
            src = f.read()
    except:
        print("Error: cannot open file")
        return

    try:
        from mojo_compiler import tokenize, Parser
        from myinterpreter import Interpreter
        tokens = tokenize(src)
        stmts = Parser(tokens).parse_module()
        interpreter = Interpreter()
        for stmt in stmts:
            interpreter.execute(stmt)
    except:
        pass

def run_repl():
    """Interactive REPL for Mojo code."""
    try:
        from mojo_compiler import tokenize, Parser
        from myinterpreter import Interpreter
    except:
        return

    try:
        interpreter = Interpreter()
    except:
        return

    print("Mojo REPL - type 'exit' or 'quit' to exit")

    while True:
        try:
            line = input(">>> ")
            if not line or not line.strip():
                continue
            if line.lower() in ("exit", "quit"):
                break
            try:
                tokens = tokenize(line)
                stmts = Parser(tokens).parse_module()
                for stmt in stmts:
                    result = interpreter.execute(stmt)
            except:
                pass
        except:
            break

def main():
    if len(sys.argv) < 2:
        run_repl()
        return

    # --dump flag: generate .tok .ast .ci .pyi for each following file
    if sys.argv[1] == "--dump":
        i = 2
        while i < len(sys.argv):
            dump_file(sys.argv[i])
            i = i + 1
        return

    # Otherwise interpret the first file
    interpret_file(sys.argv[1])

if __name__ == '__main__':
    main()
