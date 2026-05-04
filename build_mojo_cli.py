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
Mojo CLI compiler - wraps the generated mojo_compiler.py and provides build tools.
"""
import sys
import os
import subprocess
from pathlib import Path

# Add parent directory to path to import mojo_compiler
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    if len(sys.argv) < 2:
        print(f"mojo: missing command")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == '--version':
        print("mojo 0.1.0 (APEX reference implementation)")
        return

    if cmd == 'build':
        handle_build(sys.argv[2:])
        return

    if cmd == 'compile':
        handle_compile(sys.argv[2:])
        return

    print(f"mojo: unknown command '{cmd}'")
    sys.exit(1)

def handle_build(args):
    """Handle: mojo build <input.mojo> -o <output>"""
    import_name = None
    output = None

    i = 0
    while i < len(args):
        if args[i] == '-o' and i + 1 < len(args):
            output = args[i + 1]
            i += 2
        elif args[i].endswith('.mojo'):
            import_name = args[i]
            i += 1
        else:
            i += 1

    if not import_name:
        print("mojo build: no input file specified")
        sys.exit(1)
    if not output:
        print("mojo build: -o output not specified")
        sys.exit(1)

    # Attempt to compile the mojo file using the generated compiler
    try:
        from gimple_codegen import compile_to_gimple

        with open(import_name, 'r') as f:
            src = f.read()

        # Compile the mojo source to GIMPLE (C code)
        gimple = compile_to_gimple(src)

        # Write C code to temp file and compile with cc
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
            f.write(gimple)
            c_file = f.name

        try:
            # Compile C to dylib using gcc-mp-15 with -fgimple for GIMPLE code
            runtime_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'runtime'
            )

            try:
                result = subprocess.run(
                    ['/opt/local/bin/gcc-mp-15', '-fgimple', '-dynamiclib',
                     f'-I{runtime_dir}', '-o', output, c_file],
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
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                print(f"gcc-mp-15 not available or timed out: {e}")
                sys.exit(1)
        finally:
            try:
                os.unlink(c_file)
            except:
                pass

    except ImportError as e:
        print(f"mojo build: compiler not fully initialized ({e})")
        sys.exit(1)
    except Exception as e:
        print(f"mojo build error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def handle_compile(args):
    """Handle: mojo compile <input.mojo> (for compatibility)"""
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
