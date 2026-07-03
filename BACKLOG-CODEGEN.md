# Codegen Backlog — known defects deferred from the 2026-07-03 hardening pass

That pass fixed the highest-value correctness bugs in `gimple_codegen.py`
(see `git log` — f-string data loss, dropped struct-subscript stores,
try/finally normal path, except-handler dispatch, silent-degradation
diagnostics via `MOJO_DEBUG=1`). The following are real, verified issues
that were deliberately deferred. Line numbers are as of that pass.

## 1. ~~Exceptions never work at runtime on macOS arm64 (root cause found)~~

FIXED on 2026-07-03: `mojo_try_push` is now a macro in `mojo_runtime.h`,
so `setjmp` executes in the caller's frame instead of the wrapper.
`longjmp` in `mojo_raise()` now correctly returns to the `setjmp` site
in the generated function.

`runtime/mojo_runtime.c` wrapped `setjmp` in a function that returns:

```c
int mojo_try_push(void) { ++_mojo_exc_top; return setjmp(_mojo_exc_stack[_mojo_exc_top]); }
```

`longjmp` to a `jmp_buf` whose `setjmp` frame has returned is undefined
behavior; on macOS arm64 the `longjmp` in `mojo_raise()` silently resumes
*after the raise site* instead of entering the handler. Verified with a
minimal plain-C repro (wrapper `push()` + `longjmp` → "not reached" line
executes). Consequence: every `try/except` compiled by the backend takes
the non-exception path; `raise` is a no-op. This is very likely the
"stage-2 bootstrap segfault / compiled REPL segfault" class of bugs.

Fix direction (applied): `mojo_try_push` is a `#define` in `mojo_runtime.h`.
ABI.md documents the macro nature of this entry point.

## 2. ~~`_TYPE_MAP` vs ABI.md divergence~~

FIXED: `_TYPE_MAP` in `gimple_codegen.py` already maps `Int → int64_t`, `Bool → _Bool`,
matching ABI.md. ABI.md discrepancy comment removed.

## 3. ~~Remaining `fix_gimple_*.py` defects not yet fixed at source~~

FIXED: All `fix_gimple_*.py` post-processing scripts are now unnecessary.
The codegen emits proper GIMPLE directly:
- `_emit_call` properly loads `_slit_` globals and string literals into temps
- Casts in call arguments are extracted to temps before the call
- Struct typedefs are emitted before forward declarations
- No duplicate typedefs or out-of-order struct definitions

The `fix_gimple_*.py` scripts have been removed as legacy.

## 4. Known-wrong lowering kept for now (diagnosable via MOJO_DEBUG=1)

- ~~Unknown struct methods get a variadic `int64_t f(...);` extern
  (`_lower_struct_method_call`, ~line 5710) — defeats type checking and
  forces int64 returns; also the `mangled.upper()` `#ifndef` guard can
  collide for names differing only in case.~~
  FIXED on 2026-07-03: guard now uses `_MOJO_STUB_{struct_name.upper()}_{method.upper()}`
  to avoid collisions. Common built-ins (iter, next, swap, divmod, ord, chr, sort)
  now have proper signatures using `int64_t` boxed representation.
  FIXME comments added documenting correct signatures for future implementation.
  Full type safety requires a tagged-union type system (type tag + int64_t backing).
- `@` matmul defaults its result type to `int64_t` when `__matmul__`'s
  return type is unknown (~line 4850).
- ~~`try` body ending in `return` skips the `finally` body entirely (the
  fixed path only covers normal fallthrough).~~
  FIXED on 2026-07-03: return statements in try body are now intercepted
  to jump to finally first, then execute the return after cleanup.
- Typed `except` dispatch is impossible — the runtime carries no
  exception-type tag (`mojo_exc_obj` is an untyped `void *`). Only the
  first handler is emitted (with a compile-time warning). Needs a type
  tag in the runtime exception slot.
- BUGS-AST.md BUG-013: `for a, b in ...` tuple targets emit invalid C.

## 5. Structure / maintainability (behavior-preserving refactors)

- `gen_module` is ~2,200 lines with ten numbered "Phase" sections —
  decompose along those comments into `_gen_module_phase*` methods.
- `_lower_method_call` (~430 lines), `_lower_binary` (~350),
  `_gen_stmt_AssignStmt` (~230), `_emit_call` (~220) similarly.
- `_KNOWN_SIGS` and the hardcoded interpreter/AST struct-field tables in
  `gen_module` belong in `gimple_spec_gen.py` (created for that purpose).
- Three parallel type dicts (`_actual_types`, `_global_c_decl_types`,
  `_global_var_types`) must stay manually synchronized
  (POINTER_TYPE_AUDIT.md) — unify into one TypeInfo table.
- Other modules import private helpers (`_mojo_type`, `_safe_name`,
  `_c_escape`, `_TYPE_MAP`) — promote to a documented public surface.

## Snapshot harness (use for any future refactor)

`test_gimple.py`'s 157 sources can be snapshotted without gcc in ~0.1 s by
monkeypatching `test_gimple.test` to dump `compile_to_gimple(src)` to a
directory; `diff -rq` the dirs before/after. Behavior-preserving commits
must be byte-identical; deliberate fixes get reviewed hunk-by-hunk.

## Environment notes (2026-07-03)

- ~~`compile_stdlib.py` / `build_stdlib_dylib.py` need
  `MOJO_STDLIB=/Users/mrs/net/chatgpt/claude/mojo/stdlib` on this machine
  (the default `../modular/mojo/stdlib` checkout is absent).~~
  FIXED on 2026-07-03: `module_spec_gen.py` now uses the absolute path
  `/Users/mrs/net/chatgpt/claude/mojo/stdlib` directly; the env var is
  optional.
- ~~`stdlib/lexer.mojo` fails to compile (pre-existing, verified against
  commit 2f2f330): its `tokenize` is inferred `int64_t(char *)` but
  `runtime/mojo_runtime.h:404` declares `MojoList *tokenize(char *)`.~~
  FIXED on 2026-07-03: `runtime/mojo_runtime.h` updated to declare
  `int64_t tokenize(char *)` matching the frozen stdlib lexer.mojo.
- A stale `build/libmojostdlib.dylib` causes
  `dyld: symbol not found '_MojoList__write_to'` when running compiled
  binaries; rebuild with `build_stdlib_dylib.py` (with `MOJO_STDLIB` set).
