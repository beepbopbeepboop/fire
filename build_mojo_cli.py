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
    if cmd.endswith('.mojo') or cmd.endswith('.🔥'):
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

EXAMPLES:
    mojo repl                     Start the REPL
    mojo run hello.mojo           Run hello.mojo
    mojo hello.mojo               Same as above (shorthand)
    mojo build hello.mojo -o out  Build to executable 'out'
"""
    print(help_text)

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
        from gimple_codegen import compile_to_gimple

        with open(input_file, 'r') as f:
            src = f.read()

        # Compile the mojo source to GIMPLE (C code)
        gimple = compile_to_gimple(src)

        # Write C code to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
            f.write(gimple)
            c_file = f.name

        try:
            # Compile and link with runtime
            runtime_dir = os.path.join(os.path.dirname(HERE), 'runtime')

            with tempfile.NamedTemporaryFile(suffix='', delete=False) as f:
                exe_file = f.name

            try:
                # Try gcc-mp-15 first (MacPorts on macOS)
                cc_cmd = ['/opt/local/bin/gcc-mp-15', '-fgimple']
                try:
                    subprocess.run([cc_cmd[0], '--version'],
                                 capture_output=True, timeout=2)
                except:
                    cc_cmd = ['gcc', '-fgimple']  # Fallback to system gcc

                result = subprocess.run(
                    cc_cmd + ['-I', runtime_dir, '-o', exe_file, c_file],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode != 0:
                    print(f"Compilation failed: {result.stderr}")
                    sys.exit(1)

                # Run the executable
                result = subprocess.run([exe_file], capture_output=True, text=True)
                if result.stdout:
                    print(result.stdout, end='')
                if result.stderr:
                    print(result.stderr, end='', file=sys.stderr)
                sys.exit(result.returncode)

            finally:
                try:
                    os.unlink(exe_file)
                except:
                    pass

        finally:
            try:
                os.unlink(c_file)
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
        from gimple_codegen import compile_to_gimple

        with open(input_file, 'r') as f:
            src = f.read()

        gimple = compile_to_gimple(src)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
            f.write(gimple)
            c_file = f.name

        try:
            runtime_dir = os.path.join(os.path.dirname(HERE), 'runtime')

            cc_cmd = ['/opt/local/bin/gcc-mp-15', '-fgimple']
            try:
                subprocess.run([cc_cmd[0], '--version'],
                             capture_output=True, timeout=2)
            except:
                cc_cmd = ['gcc', '-fgimple']

            result = subprocess.run(
                cc_cmd + ['-I', runtime_dir, '-o', output, c_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                print(f"Built {output}")
                return
            else:
                print(f"Compilation failed: {result.stderr}")
                sys.exit(1)
        finally:
            try:
                os.unlink(c_file)
            except:
                pass

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
