# COMPILE_FAIL: Apple/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Apple/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-26, branch fix/opencode-importlib — RUNTIME crash chain root-caused via lldb; three of four links FIXED for real; final remaining link is the fully-stubbed argparse subsystem, feature-sized)

Reproduced the runtime crash fresh (`/tmp/apple_main --help` →
`Unhandled exception: AttributeError: name`, exit 1) and root-caused
it under lldb (`break set -n mojo_raise; run; bt`) — which showed the
doc's 2026-08-25 guess ("argparse subparser setup") was WRONG about
the location: the crash fired at MODULE LEVEL, line 59
(`SCRIPT_NAME = Path(__file__).name`), long before argparse. Walking
the crash chain link by link (rebuild → rerun → lldb each time),
four distinct links were found; the first three are now genuinely
fixed (commit 78bf853), the fourth is a real feature gap:

1. **FIXED — `Path(x).name` crashed as `AttributeError: name`.**
   `_lower_opaque_ctor` passed its single string argument through as
   the "constructed object" but re-boxed it to untyped int64_t, so the
   `.name` member read fell to `_mojo_dispatch_getattr` on a bare
   char*, which `mojo_obj_getattr` cannot serve → fatal. Fix:
   one-positional-arg/zero-kwargs/char*-arg opaque ctors now pass the
   arg through WITH its `char *` static type; `.name`/`.parent` on a
   char*-typed receiver lower to the existing os.path runtime helpers;
   `.resolve()` lowers to a new `int64_t_realpath` (POSIX realpath(3),
   strict=False); `_quick_type` mirrors all of it so global/local
   variable typing agrees with lowering (SCRIPT_NAME/PYTHON_DIR are
   now declared and printed as real strings). Verified end-to-end with
   a minimal repro printing the basename correctly.

2. **FIXED — `AttributeError: stdout` at the entry tail.**
   `for stream in [sys.stdout, sys.stderr]: stream.reconfigure(...)` —
   `sys` binds to a NULL module marker, so `sys.stdout` fell to
   dynamic getattr on obj=NULL. Fixed: `sys.stdout`/`sys.stderr`/
   `sys.stdin` value reads now lower to their POSIX fds (0/1/2) as
   opaque handles; the unknown-method scalar stub makes `.reconfigure`
   an honest no-op (this runtime's printf output is already
   unbuffered).

3. **FIXED — `AttributeError: SIGTERM` in main().**
   `signal.signal(signal.SIGTERM, signal_handler)` — `signal.SIG*`
   reads on the module marker crashed identically. Fixed: the eleven
   ABI-fixed portable POSIX signal numbers lower to their real values
   (BSD/Linux-only members deliberately still refuse rather than risk
   a wrong number).

4. **NOT FIXED (feature-sized) — `context.cross_build_dir`, i.e.
   compiled argparse itself.** With 1-3 landed the program reaches
   main() → parse_args(), and the generated .ci shows argparse was
   NEVER compiled: `argparse.ArgumentParser(...)` is the opaque-ctor
   passthrough of the `argparse` module marker (int64_t 0), every
   method (`add_subparsers`/`add_parser`/`add_argument`/
   `parse_args`) is an `int64_t.X() stubbed` passthrough returning its
   receiver, so parse_args() returns 0 and `context.cross_build_dir`
   getattr-crashes. There is no embedded-interpreter escape hatch that
   helps: runtime/mojo_python.c's CPython bridge is extern-declared
   but has no codegen path, and bridging OO usage (parser instances,
   method chains, Namespace attribute reads) would require building a
   foreign-object model first. Real compiled-argparse semantics
   (usage/help text generation, option/subcommand parsing, error
   handling) are a whole subsystem — same size class as the pickle
   engine judged out-of-scope in dbpickle.md. Doc kept open: compiles
   + links clean, starts correctly through module level + signal
   setup + argparse stub construction, crashes at the first genuine
   use of the stubbed parse result.

Quality gate after the fixes: test_gimple.py 256/256,
test_module_cache.py 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild exit 0 with 0 `skip <module>:` lines.

## Status (updated 2026-08-25, worktree fix/rest-remainder12 — COMPILE stage now fully fixed end-to-end; RUNTIME crash found, separate gap, NOT fixed)

`python3 fire.py build .../Apple/__main__.py` now exits 0 and produces a
working executable. Four root-cause fixes landed in the coroutine/
generator-body C++ emitter (`gimple_cpp_core.py`), each found by walking
this file's blocker one step at a time:

1. **`mojo_c_getenv`/platform/subprocess runtime-wrapper calls refused
   as "unresolved callee"**: `ast_rewriter.py`'s idiom-rewrite rules
   (`os.environ` get/`[]`/`in`, `platform.system()`/`machine()`,
   `subprocess.run(...)` + `.returncode`/`.stdout`/`.stderr`, `sys.stdin.
   read()`) all lower to a direct `CallExpr(IdentExpr('mojo_<...>'), ...)`
   — bypassing every MemberExpr-keyed case this emitter's `_cpp_expr`
   CallExpr dispatch has, so it always fell to the generic "unresolved
   callee" refusal even though these names are fixed `extern "C"`
   wrappers unconditionally declared in `<mojo_runtime.h>` (already
   `#include`d by every generated `.cpp`). Root cause of the `group()`
   generator's `if "GITHUB_ACTIONS" in os.environ:` guard refusing.
   Fixed: whitelist these 8 names for a direct call in `_cpp_expr`.
2. **Bare zero-arg `print()`**: the existing single-scalar-arg `print()`
   special case in `_cpp_stmt` required `len(args) == 1`, so `group()`'s
   teardown-half `else: print()` (line 239, no args) fell all the way
   through to the same generic "unresolved callee 'print(...)'"
   refusal. Fixed: added a zero-arg case emitting `printf("\n");`.
3. **String repetition (`"=" * (70 - len(text))`) had no `_cpp_expr`
   `*`-operator lowering** (the ordinary non-coroutine GIMPLE path's
   `mojo_cstr_repeat` case was never mirrored into the coroutine-body
   emitter) — g++ error `invalid operands ... 'const char [2]' and
   'int64_t' to binary operator*`. Fixed: added a char*/int64_t (both
   operand orders) case dispatching to `mojo_cstr_repeat`, mirroring
   `gimple_gen_exprs.py`'s existing GIMPLE-path lowering.
4. **F-strings inside a generator/coroutine body were a SILENT
   MISCOMPILE, not a refusal**: `_cpp_expr`'s `StringLiteral` case just
   C-escaped `node.value` verbatim with no f-string decode/interpolation
   step at all — so `f"===== {text} "` compiled to the literal C string
   `"f\"===== {text} \""` (the `f"`/`"` source delimiters included,
   `{text}` never substituted) instead of interpolating `text`. Found
   via g++ rejecting the resulting nonsense expression
   (`"=" * (70 - ...)` against a string constant), not by CI passing
   silently — but a case reached without the `*` error right behind it
   would have compiled and RUN with wrong output. Fixed: added
   `_cpp_string_literal_expr` (mirrors `_lower_StringLiteral`'s
   decode/parse-parts/interpolate/`mojo_str_cat`-chain logic, adapted
   to this emitter's single-expression-string return convention, incl.
   a `_cpp_apply_fstring_spec` counterpart of `_apply_fstring_spec` for
   `{x:04d}`-style specs) and wired it into the `StringLiteral` case.

With all four landed, the ENTIRE file (GIMPLE .ci stage — already clean
per the 2026-08-23 entry below — AND the C++20-coroutine `.cpp` stage)
compiles clean, links, and produces `/tmp/apple_main` (133KB, exit 0).

**Residual, NOT fixed — separate runtime gap**: running the built
binary (`apple_main --help`, mirroring real CPython's own working
`python3 Apple/__main__.py --help`) immediately raises an uncaught
`AttributeError: name` and exits nonzero, before printing anything.
Traced to the runtime's own `AttributeError: %s` formatting (`attr`
= `"name"`, `runtime/mojo_runtime.c` ~line 2632) — some object's
`.name` attribute lookup fails via the dynamic-dispatch getattr path
(`_mojo_dispatch_getattr`), most likely inside this file's `argparse`
subcommand-parser setup (`ArgumentParser`/subparsers construction, the
first thing `main()` does before any of the four fixes above's code
paths run). NOT investigated further this pass — this is a genuinely
separate bug from the compile-stage gaps this session fixed, and
tracing which specific object/attribute shape argparse's subparser
machinery hits here is real, undirected work, not a narrow one-spot
fix. Doc kept open (not deleted) — this file compiles clean now but
does not run correctly yet.

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` check:
the module-level refusal now names `group` (the same generator the
2026-08-23 entry's `print()`/string-repeat gap was found in) for a
DIFFERENT, EARLIER reason:

```
Unsupported shape(s): group: a call to unresolved callee
'mojo_c_getenv(...)' is not supported in a compiled generator/coroutine
body
```

Root cause: `group`'s guard `if "GITHUB_ACTIONS" in os.environ:` — the
ordinary (non-coroutine) GIMPLE path has a real, working `X in
os.environ` -> `mojo_truthy_cstr(mojo_c_getenv(X))` lowering (confirmed
via a minimal isolated repro's generated `.ci`), but NOTHING under
`gimple_*.py` mentions `'environ'` by name anywhere (confirmed via
grep) — the mechanism that produces this lowering was not traced to
its exact site this pass. The coroutine-body emitter's own generic
unresolved-callee refusal catches the resulting `mojo_c_getenv(...)`
call instead of silently mis-lowering it (correct, honest behavior),
but has no case recognizing this specific libc-wrapper name as safe to
call directly (unlike ordinary GIMPLE-path calls, which go through
`_KNOWN_SIGS`/`_LIBC_SIGS` in a way the coroutine emitter doesn't
consult for arbitrary libc function names). NOT investigated to a
fix this pass — the exact `os.environ` "in" lowering mechanism needs
tracing first, and this file also has the previously-documented
string-repeat/`print()` gap waiting immediately behind this one (the
2026-08-23 entry's finding, not yet re-reached/re-verified). Doc stays
open; not attempted.

## Status (updated 2026-08-23, wt09 fix/stdlib-mods `2daa41e` — ALL FOUR GIMPLE-stage errors FIXED at root cause; file still fails later, in the generator-body emitter — PARTIAL)

The residual listed below (4x `invalid operands to binary / (have
'char *' and 'int64_t')` at lines 548/661/712/789) is fixed by two
root-cause changes:

1. **`for slice_name, slice_parts in HOSTS[platform].items():` unpack
   targets** (`__main__.py:532`, the line-548 error): `_gen_for_list`
   pre-declared EVERY tuple-unpacking loop target as plain `int64_t`
   BEFORE its own per-slot analysis ran — and `_declare_var` is
   deliberately first-decl-wins, so the dict-items key slot was
   permanently boxed even though the analysis knew it was `char *`.
   Fixed by resolving per-slot element types (dict-items → char* key +
   dict-value-type value; `_tuple_slot_types` for heterogeneous tuple-
   literal lists) BEFORE declaring, via a new shared helper
   `_tuple_unpack_slot_elems` (gimple_gen_loops.py).

2. **`CROSS_BUILD_DIR / <boxed>` path joins** (lines 661/712/789):
   these RHS values are dynamic-getattr results (`context.platform`) /
   unannotated locals that lower to untracked int64_t. The `/` lowering
   already dispatched on an int64_t-boxed LHS but required exactly
   `char *` on the RHS. Since real Python `str / <non-path>` raises
   TypeError, a genuinely-char*-LHS `/` can only ever be a path join —
   coercing a boxed int64_t RHS through its pointer bits there is
   semantics-preserving, while numeric division (always non-char* LHS)
   never reaches that branch. Fixed in `_lower_binary_tail`.

With both landed, the ENTIRE GIMPLE (.ci) stage of this ~800-line file
compiles clean. **The build still fails**, now further along, inside the
C++20-coroutine translation of the module's generators
(`__main___gen.cpp`): `"=" * (70 - len(text))` (string repetition with a
computed count) has no lowering in the coroutine-body expression emitter
`_cpp_expr`, and neither does `print(...)` ("'print' was not declared in
this scope") — the SAME documented "_cpp_expr is narrower than the
ordinary compiled path" structural theme as zipfile/_path and pathlib.
Feature-sized; not attempted here.

## Status (updated 2026-08-06)

Re-ran; the original ~650-line GCC warning dump below is STALE (the
`join_command`/`shlex.join` `int64_t`-from-`void *` error it was
truncated at no longer reproduces — a different, earlier gate now fires
first). Current failure is an honest up-front refusal, not a GCC error:

```
Error building: cannot compile module: function(s) group (generator
function(s), contain a `yield`/`yield from`) — this codegen compiles
every function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event
loop / suspend-resume codegen for async functions, yet, so these cannot
be represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

This is a generator codegen refusal, part of the separate, already-
tracked compiled-generator/async-codegen project (tasks #95-135) — not
investigated further here per that project's scope.

## Update 2026-08-09: root cause was NOT the generator/async project gap — FIXED

Re-investigated with `MOJO_DEBUG=1`, which showed the REAL refusal
reason behind the generic "contain a `yield`/`yield from`" message:

```
[gimple_codegen] generator 'group' not eligible for C++ coroutine
  path, falling back to honest refusal: print() argument must be a
  scalar int64_t/double/_Bool/char* expression
```

`group()` (`__main__.py:223-239`, a `@contextmanager` generator) does:

```python
else:
    print(f"===== {text} " + "=" * (70 - len(text)))
```

The narrow-generator-body sub-compiler's own scalar-type estimator,
`_infer_simple_expr_ctype` (`gimple_codegen.py`, then ~line 2535), had
no case for a bare `len(...)` call — every `CallExpr` it didn't
recognize fell through to `return None` ("don't know, refuse"). That
`None` poisoned the enclosing `70 - len(text)` (`BinaryOp`, `-`) and
then the enclosing `"=" * (...)` (`BinaryOp`, `*`) and then the
`print()` argument's own `+`-concatenation — despite the actual
runtime value being an ordinary `char *` string, the type estimator
had no way to know that because `len()`'s int-typed result was
unmodeled, so it conservatively refused the WHOLE function (and, per
`gen_module`'s combined-refusal design, the whole module).

This is a genuinely narrow, self-contained bug — `len()` (and `ord()`,
same shape) unconditionally return a plain int in Python regardless of
their argument's type, so recognizing them needs no argument-type
inspection, unlike almost every other builtin. **Fixed** in
`gimple_codegen.py`'s `_infer_simple_expr_ctype`: added `len`/`ord` to
the recognized-builtins case, returning `'int64_t'` unconditionally.

This is NOT an instance of the tracked generator/async-codegen project
gap (tasks #95-135) — `group()`'s generator shape itself (a single
bare `yield` with no value, `@contextmanager`-style) was always within
that project's already-supported scope; it never got a chance to
compile because of this separate, narrower type-inference bug firing
first.

### Residual: the file still does not fully compile, for an UNRELATED reason

With the `len()`/`ord()` fix in place, `group`'s refusal is gone and
the build progresses much further, but now hits a genuinely different,
already-well-known class of bug — an un-annotated `for k, v in
d.items():` tuple-unpacking target (`slice_name`, from `for slice_name,
slice_parts in HOSTS[platform].items():` at `__main__.py:532`) whose
type isn't inferred from the dict's actual value type and defaults to
`int64_t`, so `CROSS_BUILD_DIR / slice_name` (`Path.__truediv__`,
`__main__.py:548`) fails to compile:

```
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:548:15: error: invalid
  operands to binary / (have 'char *' and 'int64_t')
```

(plus 3 more instances of the same class at lines 661/712/789). This
is the same recurring "unannotated local defaults to `int64_t`" family
already tracked in `bugs/hard/` (e.g.
`CODEGEN_ctor_arg_field_type_scalars_only.md`,
`CODEGEN_multi_assign_local_var_type_not_inferred.md`), just for a
for-loop dict-unpacking target specifically rather than a parameter or
chained assignment — a distinct, separate gap from this doc's original
`len()` bug and out of scope for a narrow fix here per this task's
guidance (broad type-inference-machinery change, not a one-spot fix).
Not attempted. Doc kept (this file still fails `fire.py build`
end-to-end) rather than deleted.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:69:11: warning: unused variable '_tag' [-Wunused-variable]
   69 |     "iOS": {
      |           ^~  
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 |             "arm64-apple-ios-simulator": "arm64-iphonesimulator",
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:94:11: warning: unused variable '_tag' [-Wunused-variable]
   94 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:103:13: warning: unused variable '_tag' [-Wunused-variable]
  103 |     """Run a command in an Apple development environment.
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function 'subdir_dd9b3c':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:521:7: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  521 |     except FileExistsError:
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:520:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  520 |         package_path.mkdir()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:517:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  517 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:502:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  502 |     in the lib directory.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function 'run_e1e570':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:128:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
  128 |         return str(args)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:117:7: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  117 |         print(">", join_command(command))
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:99:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   99 |     env: EnvironmentT | None = None,
      |           ^~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:97:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   97 |     *,
      |          ^  
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function 'join_command_584a43':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:130:8: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
  130 |         return shlex.join(map(str, args))
... (650 more lines)
```

Exit code: 1
Elapsed: 5.37s
