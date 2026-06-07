"""ARM64 JIT compiler for Mojo.

Compiles Mojo code to GIMPLE, then dynamically compiles to ARM64
machine code using GCC, and executes it via ctypes.

Uses SHA256-based caching to avoid recompilation of identical source code.
"""

import os
import sys
import tempfile
import subprocess
import ctypes
import platform
import hashlib
from pathlib import Path

from gimple_codegen import compile_to_gimple
from build_config import find_gcc


_IS_DARWIN = platform.system() == 'Darwin'
_GCC_BIN = find_gcc()

# Default codegen flags for the JIT compile path. -Og optimizes while keeping
# the result debuggable, which is the right default for JIT iteration.
_DEFAULT_OPT_FLAG = "-Og"
_DEFAULT_DEBUG_FLAG = None


def _toolchain_id() -> str:
    """A stable identity for the compilation toolchain and runtime, mixed into
    the cache key so that a different compiler, runtime, or target produces a
    distinct cache entry. Memoized on the function object."""
    cached = getattr(_toolchain_id, "_cached", None)
    if cached is not None:
        return cached
    parts = [
        f"gcc_bin={_GCC_BIN}",
        f"arch={platform.machine()}",
        f"system={platform.system()}",
    ]
    # gcc version string
    try:
        ver = subprocess.run([_GCC_BIN, "--version"],
                             capture_output=True, text=True, timeout=10)
        parts.append("gcc_ver=" + ver.stdout.strip().splitlines()[0])
    except Exception:
        parts.append("gcc_ver=?")
    # Runtime source/header contents — a runtime change must invalidate caches.
    runtime_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime")
    for name in ("mojo_runtime.c", "mojo_runtime.h"):
        path = os.path.join(runtime_dir, name)
        try:
            with open(path, "rb") as f:
                parts.append(f"{name}=" + hashlib.sha256(f.read()).hexdigest())
        except Exception:
            parts.append(f"{name}=?")
    cached = "\0".join(parts)
    _toolchain_id._cached = cached
    return cached


def _compiler_id() -> str:
    """Identity of the *codegen* itself — the content fingerprint of the compiler
    sources plus the version. The JIT key previously folded in only gcc + runtime,
    so a change to gimple_codegen.py etc. would not invalidate JIT caches; this
    closes that gap (and shares one definition with the CAS). Memoized."""
    cached = getattr(_compiler_id, "_cached", None)
    if cached is not None:
        return cached
    try:
        import cas
        cached = cas.compiler_fingerprint()      # codegen sources + version
    except Exception:
        try:
            import version
            cached = version.version()
        except Exception:
            cached = ""
    _compiler_id._cached = cached
    return cached


class ARM64JIT:
    """JIT compiler for ARM64 architecture with SHA256-based caching."""

    def __init__(self, opt_flag: str = _DEFAULT_OPT_FLAG,
                 debug_flag: str | None = _DEFAULT_DEBUG_FLAG):
        self.temp_dir = None
        self.loaded_libs = []
        # Codegen flags forwarded to gcc and mixed into the cache key.
        self.opt_flag = opt_flag or _DEFAULT_OPT_FLAG
        self.debug_flag = debug_flag
        # Initialize cache directory
        self.cache_dir = os.path.expanduser("~/.gmojo/jit")
        os.makedirs(self.cache_dir, exist_ok=True)

    def _codegen_flags(self) -> list[str]:
        """Optimization/debug flags passed to every gcc invocation."""
        flags = [self.opt_flag]
        if self.debug_flag:
            flags.append(self.debug_flag)
        return flags

    def _get_cache_filename(self, source_code: str, filename: str = "") -> tuple[str, str]:
        """Get cache filename and hash for source code.

        The cache key (the index into ~/.gmojo/jit) folds in everything that can
        change the produced binary: the source, the optimization (-O*) and debug
        (-g*) flags, and the toolchain/runtime identity. This guarantees that
        e.g. an -O0 build and an -O2 build, or a -g vs -g2 build, never collide.

        Returns (hash, filepath)
        """
        key = "\0".join([
            source_code,
            f"filename={filename}",          # feeds module-name derivation + #line
            f"opt={self.opt_flag}",
            f"debug={self.debug_flag or ''}",
            _toolchain_id(),
            f"compiler={_compiler_id()}",   # codegen-source fingerprint + version
        ])
        source_hash = hashlib.sha256(key.encode()).hexdigest()
        cache_file = os.path.join(self.cache_dir, f"{source_hash}")
        return source_hash, cache_file

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

    def compile_and_execute(self, mojo_src: str, filename: str = "") -> any:
        """Compile Mojo code to ARM64 and execute it.

        Uses SHA256-based caching to avoid recompilation of identical source.

        `filename` is threaded into compile_to_gimple so the --jit path produces
        byte-identical GIMPLE to the --dump-full/build path (filename feeds the
        module-name derivation and #line directives).
        """
        try:
            # Check cache first
            source_hash, cache_file = self._get_cache_filename(mojo_src, filename)

            if os.path.exists(cache_file):
                if os.environ.get('DEBUG_JIT'):
                    print(f"Using cached binary: {cache_file}", file=sys.stderr)
                # Execute cached binary
                result = subprocess.run([cache_file])
                if result.returncode != 0:
                    print(f"JIT execution failed with code {result.returncode}", file=sys.stderr)
                    return None
                return None

            # Generate GIMPLE code with transitive closure (do_imports=True)
            gimple_code = compile_to_gimple(mojo_src, do_imports=True, filename=filename)

            # Setup temporary compilation directory
            if self.temp_dir is None:
                self.temp_dir = tempfile.mkdtemp(prefix="mojo_jit_")

            c_file = os.path.join(self.temp_dir, f"{source_hash}.c")

            # Write GIMPLE code to C file
            with open(c_file, 'w') as f:
                f.write(gimple_code)

            # Get runtime directory for includes
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            runtime_dir = os.path.join(script_dir, 'runtime')
            runtime_src = os.path.join(runtime_dir, 'mojo_runtime.c')

            # Compile to object file with -fgimple, honoring the requested
            # optimization/debug flags (these are also folded into the cache key).
            o_file = os.path.join(self.temp_dir, f"{source_hash}.o")
            compile_cmd = [
                _GCC_BIN,
                *self._codegen_flags(),
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
            runtime_o = os.path.join(self.temp_dir, f"{source_hash}_runtime.o")
            runtime_cmd = [
                _GCC_BIN,
                *self._codegen_flags(),
                f"-I{runtime_dir}",
                "-c",
                "-o", runtime_o,
                runtime_src
            ]

            result = subprocess.run(runtime_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"JIT runtime compilation failed: {result.stderr}", file=sys.stderr)
                return None

            # Link executable to cache location
            link_cmd = [_GCC_BIN, "-o", cache_file, o_file, runtime_o]
            result = subprocess.run(link_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"JIT linking failed: {result.stderr}", file=sys.stderr)
                return None

            if os.environ.get('DEBUG_JIT'):
                print(f"Cached binary saved to: {cache_file}", file=sys.stderr)

            # Execute the compiled binary (don't capture output so it goes directly to stdout)
            result = subprocess.run([cache_file])
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
