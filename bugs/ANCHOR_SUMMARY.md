## Objective
Unblock real stdlib `.py` modules (os.py, mimetypes.py, typing.py, …) through the `compile_to_gimple_with_cpp` + gcc/g++ pipeline; keep quality gates green.

## Important Details
- Stdlib `.py` source: `/Users/mrs/net/Python-3.14.6/Lib/`. Mojo stdlib `.mojo`: `/Users/mrs/net/modular/mojo/stdlib/std/`.
- Gates: `make check-selfhost` → `python3 test_selfhost.py` (mojo.py self-compile, real `-c`+link, no segfault exec); stdlib dylib `rm -f build/libmojostdlib.dylib; python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)"` (real `-fgimple -c -o .o` compile per module, NOT `-fsyntax-only`); `test_gimple.py` (247 tests, `-fgimple -fsyntax-only` for the `.ci` path); `test_gimple_async_runner.py` (31+5 tests, REAL compile+link+execute of `.cpp` coroutines).
- Cache invalidation: `cas._COMPILER_SOURCES` includes `gimple_codegen.py` (line 65) → `compiler_fingerprint()` changes → all CAS objects (stdlib `.o`, py3.14 cache) rebuild fresh. CAS cache lives under `~/.gmojo` (override `$GMOJO_HOME`).
- Toolchain: `gcc`/`g++` on PATH is clang; real compiler is `/opt/local/bin/gcc-mp-15` (+ `g++-mp-15`); per-module compile = `gcc -fgimple -fPIC -D__MOJO_STDLIB_MODE__ -I runtime -c -o x.o f.ci` (dylib) / `g++ -std=c++20 -c -I runtime ...` (cpp).
- **Rigorous verification note**: `-fsyntax-only` can mask codegen/optimizer bugs (per reviewer). The `.cpp` fix was re-verified with a FULL `-O2 -c` compile, and the async runner already compiles+LINKS+EXECUTES real coroutines (e.g. `dt=0.37s` sleeps) — both rigorous.

## Work State
### Completed (this session)
- **`.cpp` coroutine local-scope hoist** (`gimple_codegen.py`):
  - `__init__`: added `self._cpp_func_scope_decls: list[str] | None = None` (None outside coroutine units).
  - `_cpp_stmt` AssignStmt handler (~18853): a local's first-assign now emits only the (block-scoped) ASSIGNMENT inline; the DECLARATION (`{_c_to_cpp_scalar_type(ctype)} {name};`) is deferred into `self._cpp_func_scope_decls` (guarded `if is not None` so the `.ci`/non-coroutine path is untouched).
  - `_gen_cpp_generator_unit` (~19989) AND `_gen_cpp_async_unit` (~20482): init `func_decls=[]`/`self._cpp_func_scope_decls=[]` before the body scan, capture `func_decls = list(self._cpp_func_scope_decls)` inside `try` (before `finally` clears it to None), and emit `*(f"    {d}" for d in func_decls)` at the TOP of the `impl` coroutine body (just after `{`) in BOTH units — generator emitter (~20083) and async emitter (~20742).
  - Rationale: a C++ coroutine frame outlives every block, so function-scope locals are sound and match Python's function (not block) scoping. Fixes the `mimetypes` `ctype` (assigned in `try:`, read in `else:`) and the `shelve`-analogue shape.
- **Verified clean** (no regressions):
  - `make check-selfhost`: PASS — `Results: 1 passed, 0 failed` (mojo.py compiles+mojo.py self-compile clean; rc=0). Exercises my cpp path on mojo.py's OWN coroutines.
  - stdlib dylib (cache CLEARED `~/.gmojo`): WITH my edits = **1 skip (pathlib)**; baseline (stashed) = **1 skip (pathlib)** → **delta = 0** (skip count did not increase). The single skip is the pre-existing `pathlib` `listdir` extern bug (see Active), in the `.ci` path, byte-identical baseline↔edited, and NOT touched by my cpp hoist.
  - `test_gimple.py` (.ci path, 247 tests): **247 passed, 0 failed** — confirms the `.ci`/`gen_stmt` path is unaffected (my edit is gated to `_cpp_func_scope_decls is not None`, only set inside the cpp coroutine units).
  - `test_gimple_async_runner.py` (cpp path, real compile+execute): **31 passed, 5 failed — IDENTICAL to clean baseline** (5× `*_still_refused: compile succeeded instead`, pre-existing from `128ebe5`; zero new failures).
  - `mimetypes.py` `.cpp`: **rc=0, 0 errors under `-O2 -c` full compile** (was `'ctype' was not declared` at mimetypes.cpp:126). Fix confirmed.

### Active (frontier — NOT caused by / not blocked by the hoist)
- **POSIX-extern frontier** (the `.ci` path, gimple_codegen.py `_LIBC_DECLARED`/`_LIBC_SIGS` ~10236-10277 + `_known_sigs` arg-padding ~14884-14910): the `.ci` preamble includes only stdint/stdlib/string/math/stdio/setjmp/dlfcn — no `<unistd.h>`/`<sys/stat.h>`/`<sys/wait.h>`. So POSIX syscalls referenced by stdlib are emitted as `extern` decls in the preamble but the matching C headers aren't pulled in → "implicit declaration" at `-c` time:
  - `pathlib/path.mojo:564` `Path.listdir` → `listdir` (from `os`) undeclared → pathlib SKIPPED in the dylib (verified pre-existing: identical on clean baseline).
  - `os.py` (Lib): `fork`, `mkdir`, `rmdir` undeclared; `execv` arg-count mismatch; `waitpid` arg-padding mismatch. (Note: `execve` is OK — already auto-stubbed `int64_t execve(...)`.)
  - Fix shape: gate `<unistd.h>`/`<sys/stat.h>`/`<sys/wait.h>` inclusion on whether any POSIX symbol is emitted; reconcile `waitpid`/`execv` arg-padding between the two call-lowerers (`_known_sigs` vs `_cpp_expr` ArgListExpr path). Concrete impl location identified; out of scope for the hoist task.
- **functools.partial `.ci` blocker** (pre-existing, `class partial:` bare-class-type `unknown type name 'partial'`): transitively blocks the os.py→mimetypes→… `.py` closure's standalone `.o` compile (853 cascading errors in mimetypes `.ci`). NOT my hoist.
- **shelve.py** `.cpp` residual: `'self->dict' is non-class type 'int64_t'` (mimetypes.cpp:117) — a `Shelf`/`dict` ATTRIBUTE field-type-inference bug (the `dict` field defaults to int64_t instead of a struct pointer), NOT the local-scope hoist bug. Different root cause; out of scope.

### Blocked
- No `.py` module has reached 100% (both `.ci` + `.cpp` clean) yet, so NO stale reports are ready for removal. The 8 trivially-passing `CODEGEN_generator_function_Lib_*.md` modules had no prior reports.
- `functools.partial` (`.ci`) blocks os.py's transitive-closure `.o`.

## Next Move
1. (Rigorous verification — DONE.) Hoist fix verified clean across selfhost + dylib(delta 0) + test_gimple(247/0) + async runner(31/5 identical) + mimetypes `-O2 -c` (0 errors).
2. **Ask whether to proceed** on the separate POSIX-extern frontier (concrete impl at gimple_codegen.py ~10236-10277 + ~14884-14910) — the next genuine unblocking step for os.py/pathlib `listdir`/`fork`/`mkdir`/`rmdir`/`waitpid`. (Separate subproject: `.ci` path, not the `.cpp` hoist.)

## Relevant Files
- `gimple_codegen.py`: `_cpp_stmt` (~18642) AssignStmt handler (~18853, my hoist); `_gen_cpp_generator_unit` (~19833, body scan/try/finally ~19989-20000, `impl` emitter ~20083); `_gen_cpp_async_unit` (~20265, try/finally ~20482-20546, `impl` emitter ~20742); `__init__` `_cpp_func_scope_decls` (~3273); `_LIBC_DECLARED`/`_LIBC_SIGS` (~10236-10277); `_known_sigs` arg-padding (~14884-14910).
- `test_gimple.py`, `test_gimple_async_runner.py`, `test_selfhost.py`, `build_stdlib_dylib.py` — gates.
- `/Users/mrs/net/Python-3.14.6/Lib/{os.py,mimetypes.py,shelve.py,functools.py}` + `/Users/mrs/net/modular/mojo/stdlib/std/pathlib/path.mojo` — probe targets.
- `bugs/CODEGEN_generator_function_Lib_mimetypes.md` (keep: `.ci` still blocked by functools.partial), `bugs/ANCHOR_SUMMARY.md` (this file).
