"""
Build script to create a mojo CLI executable in the build directory.

This creates a simple mojo command that can handle:
  mojo build <input.mojo> -o <output.dylib>
  mojo --version
  etc.
"""
import os
import sys
import stat

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(HERE, 'build')

MOJO_CLI_SCRIPT = '''#!/usr/bin/env python3
"""
Mojo CLI - compiler and REPL frontend.
Supports: mojo repl, mojo run <file>, mojo build <file>, mojo <file> (run shorthand)
Also: --dump-{tokens,ast,c,gimple,all} for bootstrap verification.
"""
import sys
import os
import subprocess
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

VERSION = "0.1.0"

def main():
    if len(sys.argv) < 2:
        print("mojo: missing command")
        print("Use 'mojo --help' for usage information")
        sys.exit(1)

    cmd = sys.argv[1]

    # Handle flags
    if cmd in ('-h', '--help'):
        print_help()
        return

    if cmd in ('-v', '--version'):
        print(f"mojo {VERSION} (APEX reference implementation)")
        return

    if cmd in ('--dump-tokens', '--dump-ast', '--dump-c', '--dump-gimple', '--dump-all'):
        if len(sys.argv) < 3:
            print(f"mojo {cmd}: no input file specified")
            sys.exit(1)
        handle_dump(cmd, sys.argv[2])
        return

    if cmd == 'repl':
        handle_repl(sys.argv[2:])
        return

    if cmd == 'run':
        handle_run(sys.argv[2:])
        return

    if cmd == 'build':
        handle_build(sys.argv[2:])
        return

    if cmd == 'compile':
        handle_compile(sys.argv[2:])
        return

    # Shorthand: mojo <file.mojo> is equivalent to mojo run <file.mojo>
    if cmd.endswith('.mojo') or cmd.endswith('.\\U0001f525'):
        handle_run([cmd] + sys.argv[2:])
        return

    print(f"mojo: unknown command '{cmd}'")
    print("Use 'mojo --help' for usage information")
    sys.exit(1)

def print_help():
    help_text = f"""mojo {VERSION} - Mojo language compiler and REPL

USAGE:
    mojo [OPTIONS] [COMMAND] [ARGS]

COMMANDS:
    repl                          Start interactive REPL
    run <file.mojo>               Run a Mojo file
    build <file.mojo> -o <out>    Build to ELF executable
    compile <file.mojo>           Compile to object file
    <file.mojo>                   Shorthand for 'mojo run <file.mojo>'

OPTIONS:
    -h, --help                    Show this help message
    -v, --version                 Show version information
    -o <file>                     Output file (used with build/compile)
    --dump-tokens <file>          Print token stream and exit
    --dump-ast <file>             Print AST and exit
    --dump-c <file>               Print generated C source and exit
    --dump-gimple <file>          Print GIMPLE-annotated C and exit
    --dump-all <file>             Print all four dumps with section headers

EXAMPLES:
    mojo repl                     Start the REPL
    mojo run hello.mojo           Run hello.mojo
    mojo hello.mojo               Same as above (shorthand)
    mojo build hello.mojo -o out  Build to executable 'out'
    mojo --dump-all hello.mojo    Dump all intermediate representations
"""
    print(help_text)

def _collect_stmts(entry_path, visited=None):
    """Walk the transitive import closure of entry_path.

    Returns an ordered list of (path, stmts) pairs in topological order
    (dependencies before dependents), with no file visited twice.
    Local .mojo imports are resolved relative to the entry file's directory;
    stdlib / site-package imports are skipped (they have no .mojo peer).
    """
    from mojo_compiler import tokenize, Parser, ImportStmt, FromImportStmt

    if visited is None:
        visited = {}   # path -> [(path, stmts), ...]  (memoised per root call)
    results = []       # ordered list for this subtree

    path = os.path.realpath(entry_path)
    if path in visited:
        return []       # already processed in this traversal

    visited[path] = True

    with open(path) as f:
        src = f.read()

    tokens = tokenize(src)
    try:
        stmts  = Parser(tokens).parse_module()
    except SyntaxError as e:
        # TODO: Parser doesn't support all Mojo syntax yet (e.g., slices x[1:2]).
        # During bootstrap, if transitive deps fail to parse, skip them and
        # let the later compilation stage handle imports (gimple_codegen will resolve them).
        import sys
        print(f"# WARNING: skipping {path} due to parse error: {e}", file=sys.stderr)
        return []

    base_dir = os.path.dirname(path)

    # Walk imports in the order they appear so declaration order is preserved
    for stmt in stmts:
        if isinstance(stmt, (ImportStmt, FromImportStmt)):
            module = stmt.module
            # Only follow local .mojo files — skip Python stdlib / packages
            candidate = os.path.join(base_dir, module + '.mojo')
            if os.path.exists(candidate):
                results.extend(_collect_stmts(candidate, visited))

    results.append((path, stmts))
    return results


def _compile_transitive_gimple(entry_path):
    """Compile entry_path and its full import closure to a single GIMPLE C string."""
    from gimple_codegen import GimpleGen

    ordered = _collect_stmts(entry_path)

    # Merge all statements into one GimpleGen pass so the C preamble
    # appears exactly once and all functions share one type-inference context.
    all_stmts = []
    for _path, stmts in ordered:
        all_stmts.extend(stmts)

    return GimpleGen().gen_module(all_stmts)


def handle_dump(flag, input_file):
    """Dump intermediate representations for bootstrap verification."""
    if not os.path.exists(input_file):
        print(f"mojo {flag}: file not found: {input_file}")
        sys.exit(1)

    try:
        from mojo_compiler import tokenize, Parser

        want_all = (flag == '--dump-all')

        if flag == '--dump-tokens' or want_all:
            if want_all:
                print("=== TOKENS ===")
            with open(input_file) as f:
                src = f.read()
            tokens = tokenize(src)
            for tok in tokens:
                print(f"{tok.kind} {tok.value!r}")
            if want_all:
                print()

        if flag == '--dump-ast' or want_all:
            if want_all:
                print("=== AST ===")
            with open(input_file) as f:
                src = f.read()
            tokens = tokenize(src)
            stmts = Parser(tokens).parse_module()
            for stmt in stmts:
                print(repr(stmt))
            if want_all:
                print()

        if flag == '--dump-c' or want_all:
            if want_all:
                print("=== C ===")
            from mojo_compiler import compile as mojo_compile
            with open(input_file) as f:
                src = f.read()
            print(mojo_compile(src))
            if want_all:
                print()

        if flag == '--dump-gimple' or want_all:
            if want_all:
                print("=== GIMPLE ===")
            print(_compile_transitive_gimple(input_file))

    except ImportError as e:
        print(f"mojo {flag}: compiler not initialized ({e})")
        sys.exit(1)
    except Exception as e:
        print(f"mojo {flag}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def handle_repl(args):
    """Interactive REPL - execute Mojo code interactively"""
    print(f"Mojo {VERSION} REPL - Type 'exit()' or Ctrl+D to quit")
    print("Type 'help()' for help")
    print()

    try:
        import readline  # Enable line editing
    except ImportError:
        pass

    commands = []
    while True:
        try:
            line = input(">>> ").strip()
            if not line:
                continue

            if line in ('exit()', 'quit()'):
                print("Bye!")
                break

            if line in ('help()', 'help'):
                print("Mojo REPL - type Mojo code to execute")
                print("Special commands:")
                print("  exit() - quit the REPL")
                print("  help() - show this help")
                continue

            commands.append(line)
            # Simple execution simulation
            try:
                # Try to evaluate as Python for now
                result = eval(line)
                if result is not None:
                    print(repr(result))
            except SyntaxError:
                try:
                    exec(line)
                except Exception as e:
                    print(f"Error: {e}")
            except Exception as e:
                print(f"Error: {e}")

        except EOFError:
            print()
            print("Bye!")
            break
        except KeyboardInterrupt:
            print()
            continue

def _find_cc():
    cc = '/opt/local/bin/gcc-mp-15'
    if os.path.exists(cc):
        return [cc, '-fgimple']
    return ['gcc', '-fgimple']

def _gimple_to_elf(gimple, output, runtime_dir):
    """Write gimple C to a temp file, compile to ELF, return subprocess result."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
        f.write(gimple)
        c_file = f.name
    try:
        return subprocess.run(
            _find_cc() + ['-I', runtime_dir, '-o', output, c_file],
            capture_output=True, text=True, timeout=60
        )
    finally:
        try:
            os.unlink(c_file)
        except:
            pass

def handle_run(args):
    """Execute: mojo run <input.mojo>"""
    if not args:
        print("mojo run: no input file specified")
        sys.exit(1)

    input_file = args[0]
    if not os.path.exists(input_file):
        print(f"mojo run: file not found: {input_file}")
        sys.exit(1)

    try:
        gimple = _compile_transitive_gimple(input_file)
        runtime_dir = os.path.join(os.path.dirname(HERE), 'runtime')

        with tempfile.NamedTemporaryFile(suffix='', delete=False) as f:
            exe_file = f.name
        try:
            result = _gimple_to_elf(gimple, exe_file, runtime_dir)
            if result.returncode != 0:
                print(f"Compilation failed: {result.stderr}")
                sys.exit(1)
            result = subprocess.run([exe_file])
            sys.exit(result.returncode)
        finally:
            try:
                os.unlink(exe_file)
            except:
                pass

    except ImportError as e:
        print(f"mojo run: compiler not initialized ({e})")
        print("Run 'make' or 'python run.py' first")
        sys.exit(1)
    except Exception as e:
        print(f"mojo run error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def handle_build(args):
    """Handle: mojo build <input.mojo> -o <output>"""
    input_file = None
    output = None

    i = 0
    while i < len(args):
        if args[i] == '-o' and i + 1 < len(args):
            output = args[i + 1]
            i += 2
        elif args[i].endswith('.mojo'):
            input_file = args[i]
            i += 1
        else:
            i += 1

    if not input_file:
        print("mojo build: no input file specified")
        sys.exit(1)
    if not output:
        print("mojo build: -o output not specified")
        sys.exit(1)

    try:
        gimple = _compile_transitive_gimple(input_file)
        runtime_dir = os.path.join(os.path.dirname(HERE), 'runtime')
        result = _gimple_to_elf(gimple, output, runtime_dir)
        if result.returncode == 0:
            print(f"Built {output}")
        else:
            print(f"Compilation failed: {result.stderr}")
            sys.exit(1)
    except ImportError as e:
        print(f"mojo build: compiler not initialized ({e})")
        sys.exit(1)
    except Exception as e:
        print(f"mojo build error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def handle_compile(args):
    """Handle: mojo compile <input.mojo> (compatibility)"""
    if not args:
        print("mojo compile: no input file specified")
        sys.exit(1)
    handle_build(args + ['-o', args[0].replace('.mojo', '')])

if __name__ == '__main__':
    main()
'''

def create_mojo_cli():
    """Create the mojo CLI script in build/mojo"""
    os.makedirs(BUILD_DIR, exist_ok=True)

    mojo_path = os.path.join(BUILD_DIR, 'mojo')
    with open(mojo_path, 'w') as f:
        f.write(MOJO_CLI_SCRIPT)

    # Make it executable
    os.chmod(mojo_path, os.stat(mojo_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Created {mojo_path}")
    return mojo_path

if __name__ == '__main__':
    create_mojo_cli()
