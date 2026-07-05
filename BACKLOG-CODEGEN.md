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

UPDATE 2026-07-04: the setjmp fix above was necessary but not sufficient —
the "stage-2 bootstrap segfault / compiled REPL segfault" class turned out
to be at least nine separate, independent bugs, found and fixed one at a
time by actually running stage2/stage3 under lldb until they stopped
crashing (`stage2/mojo --dump ../mojo.py`, then every `.mojo`/`.py` file
`stage2`/`stage3` dump):
- `os.environ.get`/`[]`/`in`/assignment had no lowering at all (fell to
  `mojo_obj_getattr`'s stub → null deref) — see `ast_rewriter.py`'s
  `os_environ_*` rules.
- `str.rsplit` was an unimplemented stub returning `0` typed `int`, boxed as
  a null `MojoList *` — real `mojo_str_rsplit` added.
- No list/string accessor normalized negative indices (`list[-1]` read
  `data[-1]`, out of bounds) — fixed in `mojo_list_get_int/get_double/
  get_str/set_*` and `mojo_str_char_at` (`runtime/mojo_runtime.c`).
- Container truthiness (`if some_list:`) was a pointer-null check, not a
  length check — an allocated-but-empty list was always "truthy". Fixed in
  `_ensure_bool_cond`/`_lower_UnaryOp`/`_lower_TernaryExpr`
  (`gimple_codegen.py`) to call `mojo_list_len`/`mojo_dict_len`/
  `mojo_set_len`/`mojo_truthy_cstr`, all now NULL-safe.
- Ternary expressions evaluate *both* branches unconditionally (no real
  branch in the generated C) — see §4d. Two real crashes traced to this;
  worked around at the two call sites, not fixed at the root (§4d).
- `subprocess.run(...).returncode`/`.stdout`/`.stderr`, `sys.stdin.read()`,
  `platform.system()`/`.machine()` had no implementation — real runtime
  functions added (`mojo_subprocess_run`, `mojo_stdin_read`,
  `mojo_platform_system`/`_machine`) and wired via `ast_rewriter.py`.
- `_TYPE_MAP` (`gimple_codegen.py`) had a literal `None` dict key — crashed
  building the dict (`MojoDict` is string-keyed only, no way to represent a
  `None` key). Entry was dead code (`_mojo_type`'s `if not ann: return
  'int64_t'` already short-circuits before any lookup); removed.
- `__name__` was hardcoded to the literal `"__main__"` for *every* compiled
  module, root or transitively imported — every inlined script's own
  `if __name__ == '__main__': main()` guard fired, running that script's
  CLI entry point as a side effect of merely being imported into the
  closure (e.g. `build_stdlib_dylib.py`'s `main()` running `argparse`
  during a plain `--dump` of `mojo.py`). Now resolves per-module via
  `self.module_name`.
- Fixing `__name__` above then exposed a genuine double-invocation bug it
  had been masking: the auto-generated C `main()` wrapper called
  `_toplevel()` (which now correctly runs the root's own
  `if __name__ == '__main__': main()`) *and then* called the renamed
  `_gimple_main()` again unconditionally right after. Every self-hosted
  program's `main()` was running twice.

With all of the above, `make bootstrap`'s stage1/stage2/stage3/verify
sequence passes cleanly (see CLAUDE.md). Three real generalizations were
deliberately deferred rather than fixed on the spot — see §4c/4d/4e.

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

## 4c. Deferred generalizations found building `ast_rewriter.py` (2026-07-04)

`ast_rewriter.py` (an AST-to-AST rewrite pass, run between parsing and
`gimple_codegen.py`, that gives the "Python idiom -> concrete runtime call"
mappings a real rule table instead of inline `elif` chains — see its module
docstring, and the `os_environ_*` rules for the motivating case) is itself
part of the self-hosted closure, so it had to stay inside the currently
self-hostable Python subset. That ruled out three genuinely useful features,
each real, standalone compiler work — logged here rather than solved on the
spot:

- **Real `type()`/RTTI.** `mojo_type()` and `mojo_obj_getattr` (see the
  latter's doc comment in `runtime/mojo_runtime.c` — it now `abort()`s with
  the attribute name instead of silently returning 0, precisely so gaps like
  this show up immediately instead of as a null-deref three calls later)
  are stubs because there is no runtime type tag on boxed values. Fixing
  this for real needs a tagged-union object representation (type tag +
  int64_t backing) — the same conclusion item 4 above already reached from
  a different direction. Highest payoff of the three: fixes every future
  generic/dynamic-idiom gap, not just this one. `ast_rewriter.py` works
  around it today with a literal `isinstance` chain (`_node_type_name`)
  instead of `type(x).__name__`.
- **Generators (`yield`).** No coroutine/iterator-state-machine codegen
  exists; a generator function can't currently be self-hosted at all.
  `ast_rewriter.py` avoids this by returning lists instead of yielding.
- **Tuple-keyed dicts.** `MojoDict` is string-keyed only; there's no
  composite-key hashing. `ast_rewriter.py`'s discrimination trie encodes
  what would naturally be a `(path, kind, value)` tuple key as a single
  string key (`_edge_key`) instead.

## 4d. Ternary expressions evaluate both branches eagerly (2026-07-04)

`_lower_TernaryExpr` (`gimple_codegen.py`) lowers `a if cond else b` by
unconditionally emitting code for *both* `then_val` and `else_val` at codegen
time, then selecting between the two already-computed results — there's no
branch in the generated C that skips the untaken side. For pure expressions
this is merely wasteful, but for anything with a side effect (I/O, a
function call) it's a correctness bug: the untaken branch's side effect
still happens. Found via `mojo_compiler.py:2625`'s
`sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1]).read()` —
compiled and run with an argv file present (so the `else` should be taken),
it still called `sys.stdin.read()` unconditionally, which is what actually
hit the `.stdin` `mojo_obj_getattr` gap during the bootstrap bug hunt (see
`ast_rewriter.py`'s `sys_stdin_read` rule, added to give it a real
implementation rather than leave it to crash). The real fix is emitting an
actual `if/else` with each branch's evaluation inside its own block —
broader and riskier than fixing on the spot (every ternary in the
self-hosted closure is affected), so logged here instead of changed live.

## 4e. `re` module flags are stubbed constants, not honored (2026-07-04)

`ast_rewriter.py`'s `re_multiline`/`re_dotall`/`re_ignorecase`/`re_verbose`
rules give `re.MULTILINE` etc. their real CPython integer values so
evaluating the constant doesn't crash (same `mojo_obj_getattr` gap class as
`os.environ`). But the regex engine backing this runtime
(`mojo_re_sub_fn`, `runtime/mojo_runtime.c`) calls POSIX `regcomp` with a
hardcoded `REG_EXTENDED` and never consumes a flags argument at all — so
`re.compile(pattern, re.MULTILINE)` compiles and runs, but multiline
anchoring (or DOTALL/IGNORECASE/VERBOSE) has no actual effect. Real fix
needs `mojo_re_*` to translate the flags int into `regcomp`'s
`REG_ICASE`/etc. (MULTILINE and VERBOSE have no direct POSIX ERE
equivalent and would need pattern preprocessing instead).

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
