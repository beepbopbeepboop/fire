#!/usr/bin/env python3
"""
mojo.py - Mojo interpreter/compiler system

Modes:
- mojo                             Interactive REPL
- mojo repl                        Interactive REPL (explicit)
- mojo <file.mojo>                 Interpret and execute file
- mojo build <file.mojo>           Compile to executable (output name = file basename)
- mojo build -o <output> <file>    Compile to executable with specified output name
- mojo --jit <file.mojo>           JIT compile and execute (ARM64)
- mojo --dump <file.mojo>          Generate .tok, .ast, .ci, .pyi files
- mojo --dump-full <file.mojo>     Generate single .ci with transitive closure (for bootstrap)
- mojo -h, --help                  Show usage
"""

import sys
import os
import re
import subprocess
import shutil
import sysconfig
import platform
import threading

# Set PATH to ensure tools like python3-config and gcc-15 can be found
os.environ['PATH'] = '/opt/homebrew/bin:/Users/mrs/bin:/opt/local/bin:/opt/local/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/X11/bin:/Library/Apple/usr/bin'

# Platform detection for cross-platform build support
_IS_DARWIN = platform.system() == 'Darwin'
from build_config import find_gcc, find_gxx
_GCC_BIN = find_gcc()
_GXX_BIN = find_gxx()

def _extract_codegen_flags(args: list):
    """Pull optimization (-O0/-O1/-O2/-O3/-Os/-Oz/-Og) and debug (-g/-g0../-g3)
    flags out of an argument list.

    Returns (opt_flag, debug_flag, remaining_args). Last occurrence wins, so
    `-O0 -O2` yields -O2. The literal flag strings are preserved and passed
    straight to gcc; they are also mixed into the JIT cache key, so -O0 vs -O2
    and -g vs -g2 never share a cache entry."""
    opt_flag = None
    debug_flag = None
    remaining = []
    for a in args:
        if re.fullmatch(r'-O[0-3sgz]?', a):
            opt_flag = a
        elif re.fullmatch(r'-g[0-3]?', a):
            debug_flag = a
        else:
            remaining.append(a)
    return opt_flag, debug_flag, remaining


def _calls_main(stmts, IfStmt, ExprStmt, CallExpr, IdentExpr):
    """Does this statement list call `main()` anywhere reachable at module
    scope — including the extremely common Python idiom
    `if __name__ == '__main__': main()`? A first version of this check only
    looked for a *bare* top-level `main()` call, so mojo.py's own
    `if __name__ == '__main__': main()` guard wasn't recognized as already
    having called it — main() got invoked once by that guard executing
    normally, then a second time by the auto-invoke fallback below,
    printing everything twice. Recurses into if/elif/else bodies (that
    covers the idiom; deeper nesting inside a loop or function call is
    deliberately not chased — main() is a module-scope entry point, not
    something reasonably called from inside a loop body)."""
    for s in stmts:
        if (isinstance(s, ExprStmt) and isinstance(s.value, CallExpr)
                and isinstance(s.value.func, IdentExpr) and s.value.func.name == 'main'):
            return True
        if isinstance(s, IfStmt):
            if _calls_main(s.then_body, IfStmt, ExprStmt, CallExpr, IdentExpr):
                return True
            for _cond, body in (s.elifs or []):
                if _calls_main(body, IfStmt, ExprStmt, CallExpr, IdentExpr):
                    return True
            if s.else_body and _calls_main(s.else_body, IfStmt, ExprStmt, CallExpr, IdentExpr):
                return True
    return False


def interpret_and_execute(src_code, filename=None, argv=None):
    """Runs the interpretation in a worker thread with a large native stack.

    Deep *Mojo-level* recursion (e.g. a recursive-descent parser written in
    Mojo, interpreted here) fans out into many nested Python frames per Mojo
    call (eval_expr -> eval_CallExpr -> invoke -> _invoke -> execute -> ...),
    so it exhausts the OS thread's real C stack well before any Python-level
    counter does. Since CPython 3.12 that hard C-stack limit is enforced
    independently of `sys.setrecursionlimit` (raising `RecursionError: Stack
    overflow (used ... kB)` right at the OS stack's real ceiling) — so
    raising the recursion limit alone, tried previously, did nothing; the
    thread's actual stack has to be made bigger.
    """
    exit_code = []
    # Real Python modules the interpreted script imports (argparse, etc.)
    # read the real sys.argv directly, bypassing myinterpreter.py's
    # _SysProxy (which only intercepts the script's own `sys` binding).
    # Left unpatched, real sys.argv still holds mojo.py's own leftover
    # CLI state (e.g. after popping the "run" subcommand it looks like
    # [mojo.py, <script path>]), so argparse.parse_args() would bind
    # the script's own path to the first declared positional instead of
    # correctly erroring out on a missing required argument.
    old_argv = sys.argv

    def _run():
        try:
            sys.argv = argv if argv is not None else [filename or "<stdin>"]
            from mojo_compiler import py_tokenize, Parser, FunctionDef, IfStmt, ExprStmt, CallExpr, IdentExpr
            from myinterpreter import Interpreter
            tokens = py_tokenize(src_code)
            stmts = Parser(tokens).with_filename(filename or "<stdin>").parse_module()
            interpreter = Interpreter(filename=filename, argv=argv)
            for stmt in stmts:
                interpreter.execute(stmt)

            # Real Mojo programs don't call main() themselves — `def main():` is
            # the entry point and gets invoked automatically (like C's main), the
            # same way the compiled path (gimple_codegen) wires it up. Scripts
            # written in the Python-style dialect (explicit `main()` call at file
            # scope, or guarded by `if __name__ == '__main__':`) already ran it
            # above, so only auto-invoke when nothing already called it.
            has_main_def = any(isinstance(s, FunctionDef) and s.name == 'main' for s in stmts)
            already_called = _calls_main(stmts, IfStmt, ExprStmt, CallExpr, IdentExpr)
            if has_main_def and not already_called:
                interpreter.eval_expr(CallExpr(func=IdentExpr(name='main')))
        except SystemExit as e:
            # A worker thread swallows SystemExit silently instead of ending
            # the process — a Mojo script's exit() builtin (mapped to
            # sys.exit(), see myinterpreter.py's `exit=sys.exit`) needs its
            # code carried back out to the main thread to actually exit.
            # Goes through str(e) rather than e.code: this file is itself
            # one of the self-hosted-compiled sources, and that compiler
            # has no field table for builtin exception attributes (only
            # for user-defined struct fields) — e.code fails to compile
            # ("request for member 'code' in something not a structure or
            # union"), while str(e)/.lstrip()/.isdigit() are ordinary
            # string operations it already handles elsewhere in this file.
            text = str(e)
            exit_code.append(int(text) if text.lstrip('-').isdigit() else 0)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            # An uncaught interpreter exception is a failed run, not a
            # successful one — without this, the worker thread finishes
            # "normally" after swallowing the exception, exit_code stays
            # empty, and the process below falls through to a bare return
            # (exit 0) despite the traceback just printed to stderr. Callers
            # (Makefiles checking $?, CI) saw a script crash reported as PASS.
            exit_code.append(1)
        finally:
            sys.argv = old_argv

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 1_000_000))
    # The big-stack worker thread is a CPython-hosting workaround: deep
    # *Mojo-level* recursion fans out into many nested Python frames per
    # Mojo call, exhausting the OS thread's real C stack (see docstring).
    # In the self-hosted compiled binary none of that applies — recursion
    # is native frames — and worse, this codegen has no threading support
    # at all: `threading.Thread(...)`/`.start()` lower to the generic
    # int64_t module-placeholder stubs, so the target NEVER runs and the
    # whole interpretation silently did nothing (rc 0, no output). Probe
    # whether a spawned thread actually executes its target; if not (the
    # compiled case), run _run() inline on the caller's stack instead.
    def _threading_runs_target():
        try:
            done = []
            probe = threading.Thread(target=lambda: done.append(1))
            probe.start()
            probe.join()
            return bool(done)
        except Exception:
            return False
    if _threading_runs_target():
        threading.stack_size(1024 * 1024 * 1024)
        t = threading.Thread(target=_run)
        t.start()
        t.join()
    else:
        _run()
    sys.setrecursionlimit(old_limit)
    if exit_code:
        sys.exit(exit_code[0])

def run_jit_repl(opt_flag=None, debug_flag=None):
    """Interactive REPL for Mojo code using JIT compilation."""
    from jit.arm64 import ARM64JIT

    jit = ARM64JIT(opt_flag=opt_flag, debug_flag=debug_flag)
    print("Mojo JIT REPL - type 'exit' or 'quit' to exit")
    print("(Note: Each expression is independently compiled)")
    print()

    while True:
        try:
            line = input(">>> ")
            if not line.strip():
                continue
            if line.lower() in ('exit', 'quit'):
                break

            try:
                # Wrap the expression in a function and call it
                # Check if line is a print call - if so, just execute it directly
                if line.strip().startswith('print('):
                    wrapped_code = f"""def _repl_expr():
    {line}

_repl_expr()
"""
                else:
                    wrapped_code = f"""def _repl_expr():
    result = {line}
    print(result)

_repl_expr()
"""
                jit.compile_and_execute(wrapped_code)
            except Exception as e:
                print("Error:", e)

        except KeyboardInterrupt:
            print("\nInterrupt")
            break
        except EOFError:
            print()
            break

    jit.cleanup()

def run_repl():
    """Interactive REPL for Mojo code."""
    try:
        from mojo_compiler import py_tokenize, Parser
        from myinterpreter import Interpreter
    except ImportError as e:
        print(f"Error: Could not import interpreter components: {e}")
        return

    interpreter = Interpreter(filename=None, argv=['<stdin>'])
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
                tokens = py_tokenize(line)
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

def jit_compile_and_execute(input_file: str, src: str, opt_flag=None, debug_flag=None, program_args=None):
    """JIT compile and execute Mojo source code for ARM64.
    
    Returns True on success, False on failure.
    """
    try:
        from jit.arm64 import ARM64JIT
        jit = ARM64JIT(opt_flag=opt_flag, debug_flag=debug_flag)
        return bool(jit.compile_and_execute(src, filename=input_file, program_args=program_args))
    except Exception as e:
        print(f"JIT error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return False

def link_executable(objs, exe_file, extra_ldflags=None, cxx=False):
    """Run the final link step for an executable — factored out of
    build_executable so the exact link-driver-selection logic is reusable by
    any caller linking in a non-gcc-compiled object (e.g. a C++-derived
    generator-coroutine object from the coroutine codegen path — see
    build_config.find_gxx()'s docstring; not yet produced by any real build,
    this milestone is toolchain plumbing only).

    cxx=True selects g++ (find_gxx()) as the link driver instead of gcc for
    just this invocation. Every individual .c/.ci compile step upstream is
    unaffected — only the final link driver choice changes. Defaults to
    cxx=False (gcc), so build_executable's ordinary all-C link is unchanged."""
    driver = _GXX_BIN if cxx else _GCC_BIN
    link_cmd = [driver, "-o", exe_file] + list(objs) + list(extra_ldflags or [])
    return subprocess.run(link_cmd, capture_output=True, text=True)


def build_executable(input_file, src, output=None, opt_flag=None, debug_flag=None):
    """Compile Mojo source to executable using GIMPLE codegen."""
    basename = os.path.splitext(os.path.basename(input_file))[0]
    # Default to a debuggable unoptimized build; -O*/-g* on the command line override.
    cg_flags = [opt_flag or "-O0", debug_flag or "-g3"]
    try:
        import gimple_codegen

        # Resolve paths relative to mojo-reference directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        runtime_dir = os.path.join(script_dir, 'runtime')
        runtime_src = os.path.join(runtime_dir, 'mojo_runtime.c')

        # Generate GIMPLE code (output C code, compile with -fgimple)
        # do_imports=True: inline transitive closure for a standalone binary
        #
        # Milestone B (C++20-coroutine generator codegen): a module that
        # mentions `yield` at all MIGHT contain a generator this codegen can
        # now compile natively (gimple_codegen.compile_to_gimple_with_cpp) —
        # cheaply pre-screened by module_may_have_supported_generator so the
        # overwhelmingly common case (no `yield` anywhere) keeps using the
        # existing CAS-cached compile_to_gimple_cached path completely
        # unchanged. cpp_code is '' whenever there's no ACTUAL supported
        # generator (module mentions `yield` but it's an unsupported shape,
        # or a false-positive textual match) — same single-.o build below.
        cpp_code = ''
        sibling_cpp_objs = []
        if gimple_codegen.module_may_have_supported_generator(src, filename=input_file):
            c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(
                src, do_imports=True, filename=input_file,
                link_objects_out=sibling_cpp_objs)
        else:
            c_code = gimple_codegen.compile_to_gimple_cached(src, do_imports=True, filename=input_file)
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
        compile_cmd = [_GCC_BIN] + cg_flags + ["-fgimple", "-I", runtime_dir] + py_cflags + ["-c", "-o", o_file, "-x", "c", ci_file]
        result = subprocess.run(compile_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Compilation failed: {result.stderr}", file=sys.stderr)
            return False

        # Compile runtime
        runtime_o = f"{basename}_runtime.o"
        runtime_cmd = [_GCC_BIN] + cg_flags + ["-I", runtime_dir] + py_cflags + ["-c", "-o", runtime_o, runtime_src]
        result = subprocess.run(runtime_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Runtime compilation failed: {result.stderr}", file=sys.stderr)
            return False

        # Milestone B: this module contains at least one supported generator
        # — compile its companion .cpp (Milestone A's g++ plumbing) into its
        # OWN object file and link it in alongside the ordinary -fgimple .o
        # (Milestone A's link_executable(cxx=True) selects g++ as the final
        # link driver so the C++ runtime/coroutine-support symbols resolve;
        # every individual .c/.ci compile step above is completely
        # unaffected — cxx=True only changes the driver for this final link).
        # Otherwise (the overwhelming common case) extra_objs/cxx_link stay
        # at their defaults and this is byte-for-byte the pre-Milestone-B
        # single-.o build.
        extra_objs = []
        cxx_link = False
        if cpp_code:
            cpp_file = f"{basename}_gen.cpp"
            with open(cpp_file, "w") as f:
                f.write(cpp_code)
            gen_o = f"{basename}_gen.o"
            cpp_cmd = ([_GXX_BIN] + cg_flags +
                       ["-std=c++20", "-I", runtime_dir, "-c", "-o", gen_o, cpp_file])
            result = subprocess.run(cpp_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Generator (.cpp) compilation failed: {result.stderr}", file=sys.stderr)
                return False
            extra_objs = [gen_o]
            cxx_link = True

            # Step B (compiled-path async/await codegen): this module's
            # generated .c/.ci preamble includes <mojo_async_runtime.h>
            # exactly when gimple_codegen's async pre-pass actually
            # compiled at least one `async def` (see GimpleGen.gen_module's
            # "if self._supported_async:" preamble block) — a reliable
            # textual proxy for "does this build need Step A's scheduler
            # linked in", same cheap-textual-check spirit as
            # module_may_have_supported_generator's own pre-scan, just
            # applied to the ALREADY-GENERATED C instead of the raw source
            # (no separate flag threaded out of gen_module needed). Compiled
            # with g++ (same toolchain as the generator .cpp unit, and for
            # the same reason: real C++20 coroutines), linked in as its own
            # object file alongside mojo_runtime.o and the generator/async
            # .cpp unit's own object — mirrors mojo_runtime.c always being
            # linked in for ordinary programs, just conditional on actually
            # needing it (this repo's own runtime/mojo_async_runtime.cpp has
            # never been linked into a real mojo.py build before this step —
            # Step A only proved it out via test_async_runtime_scaffold.py's
            # own hand-written, separately-linked test binary).
            if 'mojo_async_runtime.h' in c_code:
                async_rt_src = os.path.join(runtime_dir, 'mojo_async_runtime.cpp')
                async_rt_o = f"{basename}_async_runtime.o"
                art_cmd = ([_GXX_BIN] + cg_flags +
                           ["-std=c++20", "-I", runtime_dir, "-c", "-o", async_rt_o, async_rt_src])
                result = subprocess.run(art_cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"Async runtime compilation failed: {result.stderr}", file=sys.stderr)
                    return False
                extra_objs.append(async_rt_o)

        # The 4th coroutine-code source (see
        # _compile_imported_module's capture in gimple_gen_resolve.py):
        # transitively-imported sibling modules' own top-level generator/
        # async functions. Their coroutine units were already compiled to
        # CAS-cached objects during generation above; the client .o's .c
        # side references their __mojogen_<mod>_<fn>_* symbols, so without
        # linking them the build dies with undefined symbols exactly as if
        # no companion unit existed (bugs/
        # COMPILE_FAIL_Tools_cases_generator_parser.md — lexer.py's
        # tokenize(), reached only through parsing.py's own `import lexer`,
        # never by this root module). Each is a g++-compiled object, so
        # their presence requires a C++-aware final link for the same
        # reason a non-empty companion .cpp does above.
        for sibling_obj in sibling_cpp_objs:
            if sibling_obj not in extra_objs:
                extra_objs.append(sibling_obj)
                cxx_link = True

        # Link executable with CPython runtime
        exe_file = output if output else basename
        # Get Python library path
        try:
            configdir = subprocess.run(
                ["python3-config", "--configdir"],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            # Find the Python dylib/so by glob — version-agnostic
            import glob
            ext = "dylib" if _IS_DARWIN else "so"
            matches = glob.glob(os.path.join(configdir, f"libpython3*.{ext}"))
            if not matches:
                # Fall back to parent lib dir
                lib_dir = os.path.dirname(configdir)
                while lib_dir and lib_dir != os.path.dirname(lib_dir):
                    matches = glob.glob(os.path.join(lib_dir, f"libpython3*.{ext}"))
                    if matches:
                        break
                    lib_dir = os.path.dirname(lib_dir)
            py_lib = matches[0] if matches else ""

            py_ldflags = [f"-L{configdir}", "-ldl", py_lib]
            if _IS_DARWIN:
                py_ldflags.append("-framework")
                py_ldflags.append("CoreFoundation")
        except:
            py_ldflags = []

        result = link_executable([o_file, runtime_o] + extra_objs, exe_file, py_ldflags, cxx=cxx_link)
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
    # Pull -O*/-g* codegen flags out of argv first so they may appear anywhere.
    opt_flag, debug_flag, rest = _extract_codegen_flags(sys.argv[1:])
    sys.argv = [sys.argv[0]] + rest

    # No arguments: run REPL
    if len(sys.argv) < 2:
        run_repl()
        return

    # Check for help
    if sys.argv[1] in ('-v', '--version', 'version'):
        try:
            from version import version
            print(f"mojo {version()}")
        except Exception:
            print("mojo unknown")
        return

    if sys.argv[1] in ('-h', '--help', 'help'):
        print("""Usage:
  mojo                             Interactive REPL (interpreter)
  mojo --jit                       Interactive REPL (JIT mode, ARM64)
  mojo repl                        Interactive REPL (explicit, interpreter)
  mojo repl --jit                  Interactive REPL (explicit, JIT mode)
  mojo <file.mojo>                 Compile and run (falls back to the interpreter on failure)
  mojo run <file.mojo>             Run through the interpreter only (myinterpreter.py, no compile attempt)
  mojo --jit <file.mojo>           JIT compile and execute (ARM64)
  mojo build <file.mojo>           Compile to executable (same name as file, no extension)
  mojo build -o <output> <file>    Compile to executable with specified output name
  mojo dylib <file.mojo> [...]     Compile library module(s) to a standalone .dylib/.so
  mojo dylib -o <out> <file> [...] Same, with specified output path
  mojo --dump <file.mojo>          Generate .tok, .ast, .ci, .pyi files
  mojo --dump-full <file.mojo>     Generate single .ci with transitive closure (for bootstrap)
  mojo -v, --version               Show the compiler version (git SHA / release)
  mojo -h, --help                  Show this help message

Codegen flags (may appear anywhere; forwarded to gcc, mixed into the JIT cache key):
  -O0 -O1 -O2 -O3 -Os -Oz -Og      Optimization level (JIT default -Og, build default -O0, dylib default -O2)
  -g -g0 -g1 -g2 -g3               Debug info level (build default -g3)""")
        return

    # Check for repl command
    if sys.argv[1] == 'repl':
        # Check if --jit flag is present for JIT REPL
        if '--jit' in sys.argv:
            sys.argv.remove('--jit')
            run_jit_repl(opt_flag, debug_flag)
        else:
            run_repl()
        return

    # Check for JIT flag
    jit = '--jit' in sys.argv
    if jit:
        sys.argv.remove('--jit')
        # If --jit is the only argument, run JIT REPL
        if len(sys.argv) < 2:
            run_jit_repl(opt_flag, debug_flag)
            return

    # Check for run command — explicitly selects the interpreter (myinterpreter.py),
    # bypassing the default's compile-then-run attempt via driver.compile_program.
    # Real Mojo's own `mojo run <file>` also "builds and executes" rather than
    # interpreting (there's no separate interpreter in real Mojo) — but this
    # project has two real implementations (compiled and interpreted) worth
    # comparing directly, so `run` here means "run through the interpreter" and
    # `build`/the bare-filename default mean "run through the compiler".
    run_interp = False
    if sys.argv[1] == 'run':
        run_interp = True
        sys.argv.pop(1)

    # Check for build command
    build = False
    build_output = None
    if sys.argv[1] == 'build':
        build = True
        sys.argv.pop(1)
        # Check for -o <output> flag
        if '-o' in sys.argv:
            idx = sys.argv.index('-o')
            if idx + 1 < len(sys.argv):
                build_output = sys.argv[idx + 1]
                sys.argv.pop(idx)   # remove -o
                sys.argv.pop(idx)   # remove output filename

    # Check for dylib command: compile one or more .mojo LIBRARY modules
    # (no main()/top-level entry point needed — same "library module" shape
    # every stdlib file already compiles as) into a single, standalone,
    # self-contained shared library (.dylib on macOS, .so elsewhere),
    # callable directly from C/C++ via its plain C ABI. This is exactly
    # build_stdlib_dylib.build() — already used internally to compile the
    # whole stdlib as one dylib — exposed as a first-class command instead
    # of only being reachable by hand-importing build_stdlib_dylib.py. See
    # driver.compile_dylib's own docstring for the full design. Takes
    # multiple input files (unlike `build`, which takes exactly one) so
    # several library modules can be bundled into one output dylib.
    if sys.argv[1] == 'dylib':
        sys.argv.pop(1)
        dylib_output = None
        if '-o' in sys.argv:
            idx = sys.argv.index('-o')
            if idx + 1 < len(sys.argv):
                dylib_output = sys.argv[idx + 1]
                sys.argv.pop(idx)   # remove -o
                sys.argv.pop(idx)   # remove output filename
        dylib_inputs = sys.argv[1:]
        if not dylib_inputs:
            print("mojo dylib: at least one .mojo file is required", file=sys.stderr)
            sys.exit(1)
        import driver
        rc = driver.compile_dylib(dylib_inputs, output=dylib_output, opt_flag=opt_flag)
        sys.exit(rc)

    dump_full = '--dump-full' in sys.argv
    dump = '--dump' in sys.argv
    # Strip flags from sys.argv so input_file = sys.argv[1] works.
    # sys.argv.remove() is broken in the compiled binary (list method
    # dispatch fails), so rebuild the list instead.
    if dump_full or dump:
        sys.argv = [a for a in sys.argv if a not in ('--dump-full', '--dump')]

    if len(sys.argv) < 2:
        run_repl()
        return

    input_file = sys.argv[1]
    # Everything after the input file is the executed program's own argv,
    # not a mojo.py flag — keep it isolated from mojo.py's own CLI parsing.
    program_args = sys.argv[2:]

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

    # If JIT requested, compile and execute
    if jit:
        ok = jit_compile_and_execute(input_file, src, opt_flag, debug_flag, program_args)
        sys.exit(0 if ok else 1)

    # If build requested, compile to executable through the module-cache system
    # (link mode + per-import dylibs + CAS + reflection); fall back to the inline
    # builder if that path can't produce a binary.
    if build:
        try:
            import driver
            rc = driver.compile_program(input_file, src, output=build_output,
                                        run=False, opt_flag=opt_flag, debug_flag=debug_flag)
        except Exception:
            rc = None
        if rc is None:
            success = build_executable(input_file, src, output=build_output,
                                       opt_flag=opt_flag, debug_flag=debug_flag)
            rc = 0 if success else 1
        sys.exit(rc)

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
        # Each artifact below is independently best-effort (one failing
        # shouldn't stop the others from being generated), but a failure is
        # a real bug, not just diagnostic noise — track it so the process
        # exits nonzero instead of always reporting success. Callers that
        # want to keep going across many files (e.g. the Makefile's stage2/
        # stage3 dump loops) collect these failures across the whole run
        # and fail at the end, rather than stopping after the first file.
        any_failed = False
        try:
            import gimple_codegen

            # Tokenize ONCE and reuse for both .tok and .ast: these used to
            # call py_tokenize(src) independently, each re-running the full
            # O(source length) tokenizer pass over the same source a second
            # time for no reason (confirmed via a real call-count profile
            # while chasing the stage2-bootstrap performance blowup - see
            # doc/PLAN.md - self-hosted --dump of mojo.py itself was making
            # tens of millions of calls into runtime allocators for a ~900KB
            # file; this was one concrete, provable contributor, though not
            # the whole story). Parsing (.ast) still gets its own try/except
            # so a parse failure doesn't take .tok down with it.
            try:
                from mojo_compiler import py_tokenize
                tokens = py_tokenize(src)
            except Exception as e:
                print(f"Warning: Could not generate .tok: {e}", file=sys.stderr)
                print(f"Warning: Could not generate .ast: {e}", file=sys.stderr)
                any_failed = True
                tokens = None

            if tokens is not None:
                try:
                    # Format tokens for consistent output
                    def format_token(tok):
                        kind_str = tok.kind
                        val_repr = "'" + tok.value.replace("'", "\\'").replace("\\", "\\\\") + "'"
                        return f"Token(kind={kind_str}, value={val_repr}, line={tok.line}, col={tok.col})"
                    formatted = [format_token(t) for t in tokens]
                    with open(f"{basename}.tok", "w") as f:
                        f.write("[" + ", ".join(formatted) + "]")
                except Exception as e:
                    print(f"Warning: Could not generate .tok: {e}", file=sys.stderr)
                    any_failed = True

                try:
                    from mojo_compiler import Parser
                    ast = Parser(tokens).with_filename(input_file).parse_module()
                    with open(f"{basename}.ast", "w") as f:
                        f.write(repr(ast))
                except Exception as e:
                    print(f"Warning: Could not generate .ast: {e}", file=sys.stderr)
                    any_failed = True

            # Generate C intermediate (with transitive imports)
            # NOTE: call compile_to_gimple directly — compile_to_gimple_cached
            # imports cas.py which depends on CPython stdlib (hashlib, subprocess)
            # that the compiled binary can't run.
            try:
                c_code = gimple_codegen.compile_to_gimple(src, do_imports=False, filename=input_file)
            except Exception as e:
                import traceback; traceback.print_exc(file=sys.stderr)
                c_code = ''
            with open(f"{basename}.ci", "w") as f:
                f.write(c_code)

            # Generate Python interface stub
            with open(f"{basename}.pyi", "w") as f:
                f.write(f"# Type stubs for {basename}\n")

        except Exception as e:
            print(f"Error generating dump files: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            any_failed = True
        if any_failed:
            sys.exit(1)
        return

    # `mojo run <file>`: force the interpreter, no compile attempt at all.
    if run_interp:
        interpret_and_execute(src, filename=input_file, argv=[input_file] + program_args)
        return

    # Default for a .mojo program: compile and run it through the module-cache
    # system (link mode + per-import dylibs + CAS + reflection). Fall back to the
    # interpreter if it can't produce a binary.
    if input_file.endswith('.mojo'):
        try:
            import driver
            rc = driver.compile_program(input_file, src, run=True,
                                        opt_flag=opt_flag, debug_flag=debug_flag,
                                        program_args=program_args)
        except Exception as e:
            print(f"driver error, interpreting instead: {e}", file=sys.stderr)
            rc = None
        if rc is not None:
            sys.exit(rc)

    # Otherwise interpret as Mojo
    interpret_and_execute(src, filename=input_file, argv=[input_file] + program_args)

if __name__ == '__main__':
    main()
