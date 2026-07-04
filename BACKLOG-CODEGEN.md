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
  were briefly given concrete `int64_t`-typed signatures, but that only
  compiles when every call site happens to pass an int64_t — real callers
  pass pointer types (e.g. `MojoList *`) too, which is a hard error
  (`-Wint-conversion`) on GCC 14+, not a warning. Reverted to variadic
  `(...)` declarations on 2026-07-03 (same day) after this broke 13 files
  in `compile_stdlib.py` against the real modular stdlib.
  FIXME comments document the correct (non-variadic) signatures for future
  implementation. Full type safety requires a tagged-union type system
  (type tag + int64_t backing).
- `@` matmul defaults its result type to `int64_t` when `__matmul__`'s
  return type is unknown (~line 4850).
- ~~`try` body ending in `return` skips the `finally` body entirely (the
  fixed path only covers normal fallthrough).~~
  FIXED on 2026-07-03: return statements in try body are now intercepted
  to jump to finally first, then execute the return after cleanup.
- ~~Typed `except` dispatch is impossible — the runtime carries no
  exception-type tag (`mojo_exc_obj` is an untyped `void *`). Only the
  first handler is emitted (with a compile-time warning). Needs a type
  tag in the runtime exception slot.~~
  FIXME on 2026-07-03: To support typed dispatch, runtime needs:
  1. Add `_mojo_exc_type` (vtable pointer or enum tag) to exception state
  2. Modify `mojo_raise(type_tag)` to store the type
  3. Codegen: pass exception type when raising, check type in handlers
  (See: runtime/mojo_runtime.c:35, gimple_codegen.py:8505-8514)

- ~~GIMPLE `setjmp` address computation uses invalid `&_array[idx]`
  syntax. Should use pointer arithmetic: `(void *)&_array[idx]` with
  proper cast through void*.~~
  FIXED on 2026-07-03: Updated to use `(void *)&_mojo_exc_stack[idx]`
  pattern which compiles correctly in GIMPLE.
- BUGS-AST.md BUG-013: `for a, b in ...` tuple targets emit invalid C.

## 4b. ~~`test/memory/test_span.mojo`'s last error: `span[0].data`~~

FIXED on 2026-07-04: `compile_stdlib.py` reaches **595/0** — every stdlib
file now compiles. This was the last of the original 3 failures
(`test_unsafe_pointer_v2.mojo`, `test_string_slice.mojo`, `test_span.mojo`).

An earlier same-day attempt regressed 3 other files and was reverted (see
git history / `compile-stdlib-boxing-stub-regression.md` for the full
account) because it tried to fix the ambiguity in `_lower_binary`'s
`_is_raw_ptr` dispatch directly. The actual fix took a different path that
never needed to touch `_is_raw_ptr` at all:

- `_lower_slice`'s `Span *` `_len` computation mixed an uncast integer
  literal with an int64_t temp when the stop bound was a bare literal
  (`start_v` was defensively re-cast before use, `stop_v` wasn't) — mirrored
  the fix.
- `_mojo_type`'s `UnsafePointer[X, Origin]` branch passed the *entire*
  multi-arg bracket interior to the recursive element-type lookup, so it
  never matched anything and silently defaulted to `int64_t` for any such
  two-arg annotation — added `_split_top_level_commas`.
- `_resolve_type` learned to resolve a bracket's element against
  `struct_field_types` too (not just the whole annotation string), so
  `UnsafePointer[MoveOnly_Int, MutExternalOrigin]` resolves to
  `MoveOnly_Int *` instead of falling through to `_mojo_type`'s int64_t
  default. Guarded so `_TYPE_MAP` scalar newtypes (`Int`, `UInt8`, ...) still
  win — they're real `struct X(...)` definitions too but are deliberately
  erased to raw C scalars everywhere else.
- That alone is safe, but real struct pointers flowing through `alloc[T]`'s
  return type exposed two dormant assumptions that only ever mattered once a
  buffer pointer's pointee could be a genuine (non-scalar-newtype) struct:
  `_gen_stmt_MultiAssignStmt`'s subscript-write case had no raw-pointer
  branch at all (only `_gen_stmt_AugAssignStmt`'s did); `_lower_pointer_method`'s
  `init_pointee_*` methods assumed the pointee was always scalar, casting a
  pointer directly to a struct *value* type (invalid — needs a dereference).
  Both fixed to match their already-correct sibling patterns.
- Nested generic-struct type arguments (`alloc[MoveOnly[Int]]`) needed
  pre-elaborating the inner generic (`_ensure_generic_struct`, factored out
  of `_elaborate_generic_struct_call`) and re-deriving the outer generic's
  return type via `_resolve_type` (elaborate.py's bare `_mojo_type` has no
  `struct_field_types` access). This also required making
  `_imported_generic_structs` actually get populated for the first time —
  it turned out to be entirely dead code before (the only writer was a
  `scan()` closure gated behind `link_imports`, a flag `compile_stdlib.py`
  never sets) — via a new `_register_imported_generic_structs`, plus
  `_find_generic_source` gaining struct-lookup support and a test-relative
  module-resolution fallback for local packages like `test_utils` that
  aren't on `imports.py`'s `MOJO_PATH`-based search at all. Making that
  registration real exposed two *more* dormant bugs in the
  never-before-exercised `_elaborate_generic_struct_call` path: no
  concreteness check on type args (self-referential generics like
  `StaticTuple[Self.size]` used inside `StaticTuple`'s own methods got
  wrongly monomorphized against the unbound placeholder) and no
  signature-aware method mangling (a struct with overloaded methods, e.g.
  `LinkedList.pop()`/`pop(index)`, produced two conflicting `extern`
  declarations for the same C symbol). Both fixed by aborting elaboration
  entirely on either condition, falling back to whatever path already
  handled that struct correctly before this registration existed.
- Finally, `Span`'s own subscript gained the same `_elem_types` side-table
  tracking `MojoList *` already has, populated at construction time from
  whichever argument supplies the real element type.

Commits: `c3ec7d9`, `9a56490`, `b608a09`, `2b96926`.

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
  FIXED on 2026-07-03, then corrected later the same day:
  `module_loader.py`/`module_spec_gen.py` hardcode the absolute path
  `/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib` (the real modular
  stdlib checkout, not the small `mojo/stdlib` mock used briefly mid-day)
  directly; the env var is optional and no longer needs to be passed.
- ~~`stdlib/lexer.mojo` fails to compile (pre-existing, verified against
  commit 2f2f330): its `tokenize` is inferred `int64_t(char *)` but
  `runtime/mojo_runtime.h:404` declares `MojoList *tokenize(char *)`.~~
  FIXED on 2026-07-03: `runtime/mojo_runtime.h` updated to declare
  `int64_t tokenize(char *)` matching the frozen stdlib lexer.mojo.
- A stale `build/libmojostdlib.dylib` causes
  `dyld: symbol not found '_MojoList__write_to'` when running compiled
  binaries; rebuild with `build_stdlib_dylib.py`.
