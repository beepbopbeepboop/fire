"""
mojo_main.mojo - Mojo interpreter/compiler system

Modes:
- mojo                         Interactive REPL
- mojo file.mojo               Interpret and execute file
- mojo --dump file.mojo        Generate .ci file
"""

import sys

def run_repl():
    """Interactive REPL for Mojo code."""
    try:
        from mojo_compiler import tokenize, Parser
        from myinterpreter import Interpreter
    except:
        return

    interpreter = Interpreter()
    print("Mojo REPL - type 'exit' or 'quit' to exit")

    while True:
        try:
            line = input(">>> ")
            if not line or not line.strip():
                continue
            if line == "exit" or line == "quit":
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

    dump_mode = False
    if len(sys.argv) > 2 and sys.argv[1] == '--dump':
        dump_mode = True
        input_file = sys.argv[2]
    else:
        input_file = sys.argv[1]

    try:
        with open(input_file) as f:
            src = f.read()
    except:
        return

    if dump_mode:
        try:
            import gimple_codegen
            c_code = gimple_codegen.compile_to_gimple(src)
            with open("mojo.ci", "w") as f:
                f.write(c_code)
        except:
            pass
        return

    # Otherwise interpret as Mojo
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

if __name__ == '__main__':
    main()
