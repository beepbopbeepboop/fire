#!/usr/bin/env python3
"""
mojo.py - Mojo interpreter/compiler system

Modes:
- mojo                         Interactive REPL
- mojo repl                     Interactive REPL (explicit)
- mojo file.mojo               Interpret and execute file
- mojo --dump file.mojo        Generate .tok, .ast, .ci, .pyi files
- mojo build file.mojo         Compile to executable
"""

import sys
import os
import subprocess
import shutil
import sysconfig

# Platform detection for cross-platform build support
# Check if gcc-mp-15 exists (macOS via MacPorts), otherwise use gcc
_GCC_BIN = "gcc-mp-15" if os.path.exists("/opt/local/bin/gcc-mp-15") else "gcc"

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

def run_repl():
    """Interactive REPL for Mojo code."""
    try:
        from mojo_compiler import tokenize, Parser
        from myinterpreter import Interpreter
    except ImportError as e:
        print(f"Error: Could not import interpreter components: {e}")
        return

    interpreter = Interpreter()
    print("Mojo REPL - type 'exit' or 'quit' to exit")
    print()

    while True:
        try:
            # Read
            line = input(">>> ")
            if not line.strip():
                continue
            if line.lower() in ('exit', 'quit'):
                break

            # Eval
            try:
                tokens = tokenize(line)
                stmts = Parser(tokens).parse_module()

                # Print results for expressions
                for stmt in stmts:
                    result = interpreter.execute(stmt)
                    # If it's an expression statement with a result, print it
                    if result is not None and not isinstance(result, str):
                        print(result)
            except Exception as e:
                print("Error:", e)

        except KeyboardInterrupt:
            print("\nInterrupt")
            break
        except EOFError:
            print()
            break

def build_executable(input_file, src):
    """Compile Mojo source to executable using GIMPLE codegen."""
    basename = os.path.splitext(os.path.basename(input_file))[0]
    try:
        import gimple_codegen

        # Resolve paths relative to mojo-reference directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        runtime_dir = os.path.join(script_dir, 'runtime')
        runtime_src = os.path.join(runtime_dir, 'mojo_runtime.c')

        # Generate GIMPLE code (output C code, compile with -fgimple)
        # do_imports=False: don't inline imports, we'll link against .so files instead
        c_code = gimple_codegen.compile_to_gimple(src, do_imports=False, filename=input_file)
        ci_file = f"{basename}.ci"
        with open(ci_file, "w") as f:
            f.write(c_code)

        # Get Python include directory
        py_cflags = subprocess.run(
            ["python3-config", "--cflags"],
            capture_output=True, text=True, check=True
        ).stdout.strip().split()

        # Compile to object file with -fgimple for GIMPLE code generation
        o_file = f"{basename}.o"
        compile_cmd = [_GCC_BIN, "-O2", "-fgimple", "-I", runtime_dir] + py_cflags + ["-c", "-o", o_file, "-x", "c", ci_file]
        result = subprocess.run(compile_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Compilation failed: {result.stderr}", file=sys.stderr)
            return False

        # Compile runtime
        runtime_o = f"{basename}_runtime.o"
        runtime_cmd = [_GCC_BIN, "-O2", "-I", runtime_dir] + py_cflags + ["-c", "-o", runtime_o, runtime_src]
        result = subprocess.run(runtime_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Runtime compilation failed: {result.stderr}", file=sys.stderr)
            return False

        # Link executable with CPython runtime
        exe_file = basename
        # Get Python library path
        try:
            configdir = subprocess.run(
                ["python3-config", "--configdir"],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            if _IS_DARWIN:
                py_lib = os.path.join(configdir, "libpython3.13.dylib")
                if not os.path.exists(py_lib):
                    for name in ["libpython3.so", "libpython3.dylib"]:
                        alt = os.path.join(configdir, name)
                        if os.path.exists(alt):
                            py_lib = alt
                            break
            else:
                py_lib = os.path.join(configdir, "libpython3.12.so")
                if not os.path.exists(py_lib):
                    for name in ["libpython3.so", "libpython3.12.so"]:
                        alt = os.path.join(configdir, name)
                        if os.path.exists(alt):
                            py_lib = alt
                            break

            py_ldflags = [f"-L{configdir}", "-ldl", py_lib]
            if _IS_DARWIN:
                py_ldflags.append("-framework")
                py_ldflags.append("CoreFoundation")
        except:
            py_ldflags = []

        link_cmd = [_GCC_BIN, "-o", exe_file, o_file, runtime_o]
        link_cmd.extend(py_ldflags)

        result = subprocess.run(link_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Linking failed: {result.stderr}", file=sys.stderr)
            return False

        # Make executable
        os.chmod(exe_file, 0o755)
        print(f"Built: {exe_file}")
        return True

    except Exception as e:
        print(f"Error building: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return False

def main():
    # No arguments: run REPL
    if len(sys.argv) < 2:
        run_repl()
        return

    # Check for repl command
    if sys.argv[1] == 'repl':
        run_repl()
        return

    # Check for build command
    build = False
    if sys.argv[1] == 'build':
        build = True
        sys.argv.pop(1)

    dump_full = '--dump-full' in sys.argv
    if dump_full:
        sys.argv.remove('--dump-full')

    dump = '--dump' in sys.argv
    if dump:
        sys.argv.remove('--dump')

    if len(sys.argv) < 2:
        run_repl()
        return

    input_file = sys.argv[1]

    # Bootstrap case: if interpreting a .py file with 'repl' next arg,
    # modify sys.argv so the interpreted code will run repl on next main() call
    if input_file.endswith('.py') and len(sys.argv) > 2 and sys.argv[2] == 'repl':
        sys.argv = [sys.argv[0], 'repl']

    try:
        with open(input_file) as f:
            src = f.read()
    except Exception as e:
        print(f"Error reading {input_file}: {e}", file=sys.stderr)
        return

    # Execute bootstrap-validate.mojo as Python (it contains Python code)
    if 'bootstrap-validate' in input_file:
        result = subprocess.run([sys.executable] + sys.argv[1:])
        sys.exit(result.returncode)

    # If build requested, compile to executable
    if build:
        success = build_executable(input_file, src)
        sys.exit(0 if success else 1)

    # If --dump-full requested, generate single .ci with transitive closure (for bootstrap)
    if dump_full:
        basename = os.path.splitext(os.path.basename(input_file))[0]
        try:
            import gimple_codegen
            c_code = gimple_codegen.compile_to_gimple(src, do_imports=True, filename=input_file)
            with open(f"{basename}.ci", "w") as f:
                f.write(c_code)
            print(f"✓ Generated {basename}.ci (transitive closure)", file=sys.stderr)
        except Exception as e:
            print(f"Error generating --dump-full: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
        return

    # If --dump requested, generate .tok, .ast, .ci, .pyi files
    if dump:
        basename = os.path.splitext(os.path.basename(input_file))[0]
        try:
            import gimple_codegen

            # Generate tokens
            try:
                from mojo_compiler import tokenize
                tokens = tokenize(src)
                with open(f"{basename}.tok", "w") as f:
                    f.write(repr(tokens))
            except Exception as e:
                print(f"Warning: Could not generate .tok: {e}", file=sys.stderr)

            # Generate AST
            try:
                from mojo_compiler import Parser, tokenize
                tokens = tokenize(src)
                ast = Parser(tokens).parse_module()
                with open(f"{basename}.ast", "w") as f:
                    f.write(repr(ast))
            except Exception as e:
                print(f"Warning: Could not generate .ast: {e}", file=sys.stderr)

            # Generate C intermediate (with transitive imports)
            c_code = gimple_codegen.compile_to_gimple(src, do_imports=True, filename=input_file)
            with open(f"{basename}.ci", "w") as f:
                f.write(c_code)

            # Generate Python interface stub
            with open(f"{basename}.pyi", "w") as f:
                f.write(f"# Type stubs for {basename}\n")

        except Exception as e:
            print(f"Error generating dump files: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
        return

    # Otherwise interpret as Mojo
    interpret_and_execute(src)

if __name__ == '__main__':
    main()
