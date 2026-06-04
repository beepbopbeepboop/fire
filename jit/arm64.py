"""ARM64 JIT compiler for Mojo.

Compiles Mojo code to GIMPLE, then dynamically compiles to ARM64
machine code using GCC, and executes it via ctypes.
"""

import os
import sys
import tempfile
import subprocess
import ctypes
import platform
from pathlib import Path

from gimple_codegen import compile_to_gimple
from build_config import find_gcc


_IS_DARWIN = platform.system() == 'Darwin'
_GCC_BIN = find_gcc()


class ARM64JIT:
    """JIT compiler for ARM64 architecture."""

    def __init__(self):
        self.temp_dir = None
        self.loaded_libs = []

    def _create_wrapper(self, gimple_code: str, func_name: str, return_type: str = "long") -> str:
        """Wrap GIMPLE code with a main function that calls the target function."""
        if return_type == "void":
            wrapper = f"""
#include <stdio.h>
{gimple_code}

int main() {{
    {func_name}();
    return 0;
}}
"""
        else:
            wrapper = f"""
#include <stdio.h>
{gimple_code}

int main() {{
    {return_type} result = {func_name}();
    printf("%ld\\n", (long)result);
    return 0;
}}
"""
        return wrapper

    def _compile_to_so(self, gimple_code: str, so_name: str) -> bool:
        """Compile GIMPLE code to a shared library (.so or .dylib)."""
        if self.temp_dir is None:
            self.temp_dir = tempfile.mkdtemp(prefix="mojo_jit_")

        c_file = os.path.join(self.temp_dir, f"{so_name}.c")
        o_file = os.path.join(self.temp_dir, f"{so_name}.o")
        so_file = os.path.join(
            self.temp_dir,
            f"{so_name}.{'dylib' if _IS_DARWIN else 'so'}"
        )

        # Write GIMPLE code to C file
        with open(c_file, 'w') as f:
            f.write(gimple_code)

        # Compile to object file with -fgimple
        compile_cmd = [
            _GCC_BIN,
            "-O0", "-g3",
            "-fgimple",
            "-fPIC",
            "-c",
            "-o", o_file,
            "-x", "c",
            c_file
        ]

        result = subprocess.run(compile_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Compilation failed: {result.stderr}", file=sys.stderr)
            return False

        # Link to shared library
        if _IS_DARWIN:
            link_cmd = [_GCC_BIN, "-shared", "-o", so_file, o_file]
        else:
            link_cmd = [_GCC_BIN, "-shared", "-o", so_file, o_file]

        result = subprocess.run(link_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Linking failed: {result.stderr}", file=sys.stderr)
            return False

        return so_file

    def compile_and_execute(self, mojo_src: str) -> any:
        """Compile Mojo code to ARM64 and execute it.

        For now, expects code that defines a main() function or returns a value.
        """
        try:
            # Generate GIMPLE code
            gimple_code = compile_to_gimple(mojo_src, do_imports=True)

            # Compile to executable and run it directly (simpler for testing)
            if self.temp_dir is None:
                self.temp_dir = tempfile.mkdtemp(prefix="mojo_jit_")

            c_file = os.path.join(self.temp_dir, "jit_code.c")
            exe_file = os.path.join(self.temp_dir, "jit_exe")

            # Write GIMPLE code to C file
            with open(c_file, 'w') as f:
                f.write(gimple_code)

            # Get runtime directory for includes
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            runtime_dir = os.path.join(script_dir, 'runtime')
            runtime_src = os.path.join(runtime_dir, 'mojo_runtime.c')

            # Compile to object file with -fgimple
            o_file = os.path.join(self.temp_dir, "jit_code.o")
            compile_cmd = [
                _GCC_BIN,
                "-O0", "-g2",
                "-fgimple",
                f"-I{runtime_dir}",
                "-c",
                "-o", o_file,
                "-x", "c",
                c_file
            ]

            if os.environ.get('DEBUG_JIT'):
                print(f"JIT compile command: {' '.join(compile_cmd)}", file=sys.stderr)

            result = subprocess.run(compile_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"JIT compilation failed: {result.stderr}", file=sys.stderr)
                return None

            # Compile runtime
            runtime_o = os.path.join(self.temp_dir, "mojo_runtime.o")
            runtime_cmd = [
                _GCC_BIN,
                "-O0", "-g2",
                f"-I{runtime_dir}",
                "-c",
                "-o", runtime_o,
                runtime_src
            ]

            result = subprocess.run(runtime_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"JIT runtime compilation failed: {result.stderr}", file=sys.stderr)
                return None

            # Link executable with runtime
            link_cmd = [_GCC_BIN, "-o", exe_file, o_file, runtime_o]
            result = subprocess.run(link_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"JIT linking failed: {result.stderr}", file=sys.stderr)
                return None

            # Execute the compiled binary (don't capture output so it goes directly to stdout)
            result = subprocess.run([exe_file])
            if result.returncode != 0:
                print(f"JIT execution failed with code {result.returncode}", file=sys.stderr)
                return None

            return None  # Output already printed to stdout

        except Exception as e:
            print(f"JIT error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return None

    def cleanup(self):
        """Clean up temporary files."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            import shutil
            try:
                shutil.rmtree(self.temp_dir)
            except:
                pass
