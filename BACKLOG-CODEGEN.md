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

## 4b. `test/memory/test_span.mojo`'s last error: `span[0].data` (deferred 2026-07-04)

The final failure in `compile_stdlib.py` (594/1) is `span[0].data` where
`span: Span[MoveOnly[Int]]`. Root-caused fully; deliberately deferred because
a full fix regressed 3 other files and requires resolving a real
pre-existing ambiguity, not just adding a new capability. Two independent
sub-problems, only the first of which is fixed:

- FIXED: `Span(data)[:0]`'s slice `_len` computation mixed an uncast integer
  literal with an int64_t temp (`_lower_slice`'s `Span *` arm, ~line 7446) —
  `start_v` was defensively re-cast before use but `stop_v` wasn't. Fixed by
  mirroring the same re-cast for `stop_v`.
- DEFERRED: `_lower_subscript`'s `Span *` arm always assumes the element is a
  raw byte (`struct_field_types['Span'] = {'_data': 'char *', ...}`,
  ~line 10558), regardless of what `Span[T]` was actually constructed from —
  so `span[0]` is always typed `char`, and `.data` (a `MoveOnly` field) fails
  with "request for member 'data' in something not a structure or union".

  Fixing this requires tracking `Span`'s real element type (mirroring the
  existing `_elem_types` side-table already used for `MojoList *`), which in
  turn requires `alloc[MoveOnly[Int]]` to actually resolve to a real
  `MoveOnly_Int *` return type instead of the generic `int64_t *` fallback.
  That's reachable — `_mojo_type`'s `UnsafePointer[X, Origin]` branch already
  had an unrelated pre-existing bug (fixed 2026-07-04: it passed the *entire*
  multi-arg bracket interior, including trailing origin params, to the
  recursive element-type lookup, so it never matched anything and silently
  defaulted to `int64_t`; now split on top-level commas first — see
  `_split_top_level_commas`) — but teaching `_resolve_type` to *also* resolve
  a bracket's element type against `struct_field_types` (not just the whole
  annotation string) surfaces a real ambiguity in `_lower_binary`'s raw
  pointer-arithmetic dispatch (`_is_raw_ptr`, ~line 4849, added 2026-07-03):
  it distinguishes a genuine buffer pointer (`alloc[T]`'s `T *` return) from
  a *boxed scalar* self-receiver (`self: Int *` inside `Int.__neg__`) by
  checking whether `T` is a registered struct name — which breaks the moment
  a buffer pointer's element type genuinely *is* a registered struct (exactly
  what this fix produces). Substituting a "is this literally the `self`
  parameter" check instead (the only place a struct's own name is used as a
  boxed-scalar pointer — `_gen_struct_method` seeds
  `self.var_types['self'] = f"{struct_name} *"` by name, nothing else does)
  was tried and made things *worse* (591/4: new regressions in
  `std/collections/dict.mojo`, `std/python/_cpython.mojo`,
  `test/memory/test_memory.mojo`), meaning there's at least one more
  boxed-scalar-via-struct-name pattern beyond `self` that isn't yet
  identified. Needs dedicated investigation into every place a struct's own
  name is used as a non-buffer pointer before `_is_raw_ptr`/`_resolve_type`
  can be safely broadened. Reverted; `_resolve_type` and `_is_raw_ptr` are
  unchanged as of this note.

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
