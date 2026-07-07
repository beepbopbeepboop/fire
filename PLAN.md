# Known Bugs and Outstanding Work

This document tracks verified, still-open defects and deferred feature work.
See `IMPL.md` for what's already implemented and working, and `STDLIB.md` for
stdlib transpilation status. Historically this file also tracked the GIMPLE
bootstrap error-fixing plan from the project's early phase (May 2026) and
`BACKLOG-CODEGEN.md` tracked defects deferred from the 2026-07-03 hardening
pass — both are long since resolved or superseded and have been folded in
here (open items) and into `IMPL.md` (fixed items). `BACKLOG-CODEGEN.md`
itself is now a thin redirect, kept only because a number of in-code
comments still reference its old section numbers (`§4d`, `§4f`, etc.).

---

## Known bugs (verified, real, still open)

- **`@` matmul defaults its result type to `int64_t`** when `__matmul__`'s
  return type is unknown (`_lower_matmul`, `gimple_codegen.py` ~line 5323).
- **Typed `except` dispatch is impossible** — the runtime carries no
  exception-type tag (`mojo_exc_obj` is an untyped `void *`), so only the
  first `except` handler is ever emitted (with a compile-time warning:
  "multiple except handlers are not supported"). Needs a type tag in the
  runtime exception slot: (1) add `_mojo_exc_type` to exception state, (2)
  `mojo_raise(type_tag)` stores it, (3) codegen passes the type when
  raising and checks it in handlers. See `runtime/mojo_runtime.c` (near the
  exception stack) and `gimple_codegen.py`'s except-handler dispatch.
- **`for a, b in ...` tuple for-targets emit invalid C** — `BUGS-AST.md`
  BUG-013, still listed there as outstanding. The for-loop target isn't
  validated as a plain identifier before being spliced into the generated
  C loop variable name.
- **Struct reflection (`getattr()`/`setattr()`/`dataclasses.fields()`/the
  new field-by-field `repr()`) is keyed by bare struct *name*, which
  collides across modules that happen to define a same-named class** —
  root-caused 2026-07-07 chasing a stale symptom of this same bug (the
  `example_imports.mojo` `.ast` failure below). Concretely:
  `mojo_compiler.py` and `ast_nodes.py` (imported by `myinterpreter.py`,
  which is part of the same self-hosted closure) each define their own
  unrelated `FunctionDef` dataclass with a *different* field layout.
  `struct_field_types` (`gen_module`, `gimple_codegen.py`) is a plain
  `dict[str, dict]` keyed by class name, so scanning both modules leaves
  only whichever definition was scanned last; `_struct_type_id`
  (a hash of the bare name) then dispatches *every* runtime `FunctionDef`
  instance — from either module — to that one field layout. A `FunctionDef`
  instance that's really `ast_nodes.py`'s shape gets read through
  `mojo_compiler.py`'s field list (or vice versa): wrong offsets, an
  `is_static` field that doesn't exist on the other class, garbage values
  for everything after the point their layouts diverge. Reproduced via
  `repr(ast)` on `hello.mojo`'s own trivial two-statement AST once
  self-hosted — `FunctionDef(... is_static=0)` with every field beyond
  that point corrupted to a raw address. Real fix needs struct type IDs
  (and `struct_field_types`'s dict key) to be module-qualified, not just
  the bare class name — a real, standalone fix, not a quick patch found
  this late in an unrelated session.
- **`example_imports.mojo`'s `.ast` generation used to hard-crash when
  self-hosted** (found 2026-07-06); no longer crashes as of 2026-07-07 (the
  underlying `mojo_obj_getattr` abort is fixed — see `IMPL.md`), but its
  `.ast` output is still wrong, for the reason above: `example_imports.mojo`
  exercises `FromImportStmt` + several `FunctionDef`/`CallExpr` nodes, and
  once self-hosted those get corrupted the same way `hello.mojo`'s do. Not
  a distinct bug — merged into the entry above.
- **`re.search()`/`re.match()` (and `.group()`/`.start()`/`.end()` on their
  result) have zero real implementation as expressions** — confirmed
  2026-07-06 investigating `monomorphize.py`. `re`/a compiled pattern is
  typed as a plain scalar (`int64_t`) at the call site, so `re.search(pat,
  s)` falls through to `_lower_method_call`'s generic "unknown method on a
  scalar receiver" fallback (~line 5941, `gimple_codegen.py`): it silently
  returns the *receiver's own value* unchanged, annotated
  `/* {ot}.{method}() stubbed */`. Concretely, `m = re.search(pat, s)`
  compiles to `m = re;` (the `re`-module marker, always non-null), so
  `if m:` is *always true* regardless of whether a match occurred, and
  `m.group(1)` similarly returns garbage (the same non-null marker,
  reinterpreted as `char *` — a wild pointer, not the captured text).
  This is a **silent miscompile**, not a crash — worse than the
  `re.sub()` bug below in that GCC's `-fsyntax-only` check (what
  `compile_stdlib.py` validates) can't catch it, since the generated C is
  syntactically fine. It *is* diagnosable today via `MOJO_DEBUG=1` (uses
  the existing `_stub_result`/`_debug_note` mechanism — see
  `monomorphize.py`'s own `compile_fn`, whose `m = re.search(...)` /
  `name = m.group(1)` is exactly this). Real fix needs `re.search()`/
  `.match()` to return a genuine Match-or-None representation (probably a
  side-table keyed the same way `.finditer()`'s per-iteration match vars
  are, but for a single expression rather than a for-loop) — a real,
  standalone feature, not a quick patch.
- **`re.sub(pattern, repl, src)` where `repl` is a plain replacement
  *string* (not a callback) crashed with `SIGILL`** — fixed 2026-07-06,
  see `IMPL.md`. Confirmed via `monomorphize.py`'s own
  `safe_suffix`/`monomorphize_source`, both of which use exactly this form
  (`re.sub(r'[^A-Za-z0-9_]', '_', s)`, `re.sub(rf'\b{re.escape(tp)}\b',
  str(concrete), src)`). Pre-existing bug (not introduced by this
  session's regex-engine work — the callback-resolution logic was only
  extracted into a shared helper, not changed), just newly exposed because
  `safe_suffix`'s pattern is compile-time-foldable and so now actually
  reaches the real engine instead of silently no-opping via the old
  POSIX-regcomp fallback.
- **`elaborate.py`'s own `re.sub(..., f'fn {mangled}', src, count=1)`**
  would hit the same `repl`-is-a-string shape (now fixed) **but the file
  doesn't currently parse through this compiler at all** (`SyntaxError:
  Unexpected INDENT`, an unrelated, pre-existing front-end gap) — so this
  specific call site is unreachable/moot until that's fixed separately.
  Also note: `count=1` (limit to first replacement) isn't honored by
  either `re.sub()` backend — always replaces every match. Not yet known
  to matter for any *reachable* call site.
- **`consolidate_string_pool.py`'s `re.sub()` calls** use the same
  string-replacement form (now fixed) but the file isn't imported by
  anything and isn't part of the self-hosted closure — a standalone dev
  script, always run interpreted. Not a live risk.

## Known feature gaps (regex)

- **`re.findall()`/`re.split()` have no codegen lowering at all** — only
  `.finditer()` and `.sub()` (with a compile-time-foldable pattern) are
  implemented (see `IMPL.md`'s regex-engine section). `.match()`/`.search()`
  don't even have a stub type in `_quick_type` that matches their real
  shape (returns a dummy `int`) — see the confirmed silent-miscompile bug
  above for what actually happens at the real lowering site.
- **`re` module flags are stubbed constants, not honored.**
  `ast_rewriter.py`'s `re_multiline`/`re_dotall`/`re_ignorecase`/`re_verbose`
  rules give `re.MULTILINE` etc. their real CPython integer values so
  evaluating the constant doesn't crash, but neither regex backend
  (`mojo_re_sub_fn`'s POSIX `regcomp`, or the new compile-time engine in
  `regex_compile.py`/`mojo_regex_search`) actually consumes a flags
  argument. `re.compile(pattern, re.MULTILINE)` compiles and runs, but the
  flag has no effect. Real fix: for the POSIX path, translate the flags int
  into `regcomp`'s `REG_ICASE` etc. (`MULTILINE`/`VERBOSE` have no direct
  POSIX ERE equivalent and would need pattern preprocessing); for the new
  engine, it could honor flags directly at compile time (e.g. case-fold
  character ranges for `IGNORECASE`), which is more tractable now that a
  real compile-time-known-pattern engine exists.
- **Lookahead/lookbehind assertions (`(?=...)`, `(?!...)`, etc.) are
  unsupported** by the new regex engine (`regex_compile.py`) — found via
  `gimple_codegen.py`'s own `\b(inout|borrowed|...)\s+(?=\w)` pattern
  during the `re.sub()` fix. Falls back to the POSIX backend gracefully
  (no crash), but POSIX ERE doesn't support lookahead either, so such a
  pattern silently no-ops via `re.sub`'s "compile failed, return input
  unchanged" behavior either way.

## Deferred generalizations (2026-07-04, still open)

Found while building `ast_rewriter.py` (an AST-to-AST rewrite pass giving
"Python idiom → concrete runtime call" mappings a real rule table instead of
inline `elif` chains). `ast_rewriter.py` is itself part of the self-hosted
closure, so it had to stay inside the currently self-hostable Python subset —
that ruled out three genuinely useful features, each real standalone compiler
work:

- **Real `type()`/RTTI.** `mojo_type()` and `mojo_obj_getattr` are stubs
  because there is no runtime type tag on boxed values. Fixing this for
  real needs a tagged-union object representation (type tag + int64_t
  backing) — same root need as the typed-`except`-dispatch bug above.
  Highest payoff of the three: fixes every future generic/dynamic-idiom
  gap, not just this one. `ast_rewriter.py` works around it today with a
  literal `isinstance` chain (`_node_type_name`) instead of
  `type(x).__name__`.
- **Generators (`yield`).** No coroutine/iterator-state-machine codegen
  exists; a generator function can't currently be self-hosted at all.
  `ast_rewriter.py` avoids this by returning lists instead of yielding.
- **Tuple-keyed dicts.** `MojoDict` is string-keyed only; there's no
  composite-key hashing. `ast_rewriter.py`'s discrimination trie encodes
  what would naturally be a `(path, kind, value)` tuple key as a single
  string key (`_edge_key`) instead.

## Struct method type safety (deferred)

Unknown struct methods get a variadic `int64_t f(...);` extern
(`_lower_struct_method_call`) — defeats type checking and forces int64
returns for anything not already known. Concrete (non-variadic) signatures
for common built-ins (`iter`, `next`, `swap`, `divmod`, `ord`, `chr`, `sort`)
were tried and reverted (broke 13 files in `compile_stdlib.py` against the
real modular stdlib, since real callers pass pointer types too — a hard
`-Wint-conversion` error on GCC 14+, not a warning). Full type safety here
needs the same tagged-union type system (type tag + int64_t backing) called
for above.

## Structure / maintainability (behavior-preserving refactors)

Pure tech debt — no known bug, just size/organization:

- `gen_module` is ~2,200 lines with ten numbered "Phase" sections —
  decompose along those comments into `_gen_module_phase*` methods.
- `_lower_method_call` (~430 lines), `_lower_binary` (~350),
  `_gen_stmt_AssignStmt` (~230), `_emit_call` (~220) similarly.
- `_KNOWN_SIGS` and the hardcoded interpreter/AST struct-field tables in
  `gen_module` belong in `gimple_spec_gen.py` (created for that purpose).
- Three parallel type dicts (`_actual_types`, `_global_c_decl_types`,
  `_global_var_types`) must stay manually synchronized
  (`POINTER_TYPE_AUDIT.md`) — unify into one `TypeInfo` table.
- Other modules import private helpers (`_mojo_type`, `_safe_name`,
  `_c_escape`, `_TYPE_MAP`) — promote to a documented public surface.
- The regex-detection/pattern-folding logic embedded in `gimple_codegen.py`
  (`_try_const_fold_str`, the `re.sub`/`.finditer()` branches in
  `_lower_call`, the Phase 1.7 `_regex_patterns` module-level scan) is a
  good candidate to move into `ast_rewriter.py`'s declarative rule table —
  but only the *detection* side moves cleanly; the actual C emission
  (compile-time array generation, custom for-loop control flow, per-match
  accessors) is inherently codegen work and can't be expressed as a pure
  AST-to-AST rewrite. Worth doing once the regex feature gaps above are
  closed, not before (no point relocating logic that's still being
  actively extended). See conversation 2026-07-06 for the full analysis.

## Tooling notes for future refactor work

- **Snapshot harness**: `test_gimple.py`'s 157 sources can be snapshotted
  without gcc in ~0.1s by monkeypatching `test_gimple.test` to dump
  `compile_to_gimple(src)` to a directory; `diff -rq` the dirs before/after.
  Behavior-preserving commits must be byte-identical; deliberate fixes get
  reviewed hunk-by-hunk. Use this for any of the structure refactors above.
- **A stale `build/libmojostdlib.dylib` causes**
  `dyld: symbol not found '_MojoList__write_to'` (or similar) when running
  compiled binaries — rebuild with `build_stdlib_dylib.py` after any
  codegen or runtime.c change (see `CLAUDE.md`'s quality-gates section).
