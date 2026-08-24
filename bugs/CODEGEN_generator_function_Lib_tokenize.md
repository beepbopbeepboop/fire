# CODEGEN_generator_function: Lib/tokenize.py

## Status (updated 2026-08-24, worktree fix/gen-core — "own error count now ZERO" was stale; two own generators refuse honestly on real remaining gaps)

Same `fd909e9`-timing issue as this cluster's `pickletools.py`/
`weakref.py` 2026-08-24 entries: re-run fresh, the isolated coroutine-
path compile this doc's 2026-08-23 entry relied on now raises (`fd909e9`
landed later the same day): `_generate_tokens_from_c_tokenizer` calls
`type(...)` (Python's dynamic-type-introspection builtin — no
coroutine-body lowering exists for it, a real, separate feature) and
`tokenize` (the free function) calls `TokenInfo(...)` — a dynamically-
created `collections.namedtuple('TokenInfo', ...)` type, not a `class`
statement, so it never registers as a known struct constructor the
coroutine emitter can dispatch to. Both are genuine, different
structural gaps (dynamic `type()` reflection; a compile-time-invisible
namedtuple-as-class), not narrow bugs — not attempted, matching this
cluster's scoping for the sibling opaque-value/dynamic-reflection gaps.

tokenize.py's own `def open(filename)`/`def any(*choices)` shadowing
fixes and the `__author__` cross-contamination fix (below) all still
hold — this is a NEW pair of refusals only now visible because
`fd909e9` turned what used to be a silent bare-identifier miscompile
into an honest one. Doc stays open; not a narrow fix.

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — tokenize.py's own error count now ZERO)

The last tokenize.py-own error (`23:28 assignment to 'char *' from
'int64_t'` on `__author__ = 'Ka-Ping Yee <ping@lfw.org>'`, noted in the
2026-08-09 entry below) is FIXED — and it was NOT a dunder/string-literal
bug: root cause is the same shared-flat-`_global_var_types`
cross-contamination documented for tarfile.py's `ENCODING` (see that
doc's 2026-08-23 entry). `io.py`'s and `inspect.py`'s own `__author__`
globals (both transitively imported by tokenize.py) overwrite the shared
bare-name entry between tokenize's Phase 1.7 scan and its own assignment
emission, so the string literal got coerced to the wrong type. Fixed by
the new per-instance `_own_global_var_types` overlay +
`_global_dst_ctype` (commit 65706f3); verified via a real
`mojo.py build .../Lib/tokenize.py`: **0 errors attributed to
tokenize.py's own source**. The build still fails end-to-end solely on
the already-documented transitive cascade (`codecs.py` 12× "expected
expression before int64_t", `argparse.py` %-dict cluster,
`enum.py`, ...), so the doc stays open per convention.

Quality gate: `test_gimple.py` 250/250, `test_module_cache.py` 76/76,
`make check-selfhost` clean, stdlib dylib rebuild 0 skips.

## Status (updated 2026-08-20)

The `any` half of the "`any`/`perror` name collisions" blocker (the
`perror` half was fixed 2026-08-18, see below) is now ALSO FIXED. Three
separate root causes, all found and fixed in `gimple_codegen.py` /
`runtime/mojo_runtime.{h,c}`:

1. **Call-site dispatch had no shadowing gate.** `tokenize.py` defines
   its own top-level `def any(*choices): return group(*choices) + '*'`
   (line 61), called with exactly 1 argument at line 68
   (`Ignore = Whitespace + any(r'\\\r?\n' + Whitespace) + maybe(Comment)`).
   The `fname_raw in ('all', 'any') and len(node.args) == 1` dispatch
   check (`_lower_named_call`, just above the pre-existing `open` gate)
   routed this straight to the builtin `_lower_builtin_all_any` instead
   of the user's own function — exactly the same class of bug already
   fixed for `open` (see the `_locally_binds_name` mechanism). Fixed by
   adding the identical `and not self._locally_binds_name(fname_raw)`
   gate to the `all`/`any` dispatch check.

2. **`_quick_type`'s return-type heuristic had the same gap.** The
   `_BUILTIN_SCALARS` table (`isinstance`/`all`/`any` → `_Bool`) used
   during return-type inference had no shadowing check either — a call
   to the LOCAL `any` (which really returns `char *`) quick-typed to
   `_Bool`, so `Whitespace + any(...) + maybe(...)`'s `+` joined
   `char *` with `_Bool`, producing the reported line-124 "invalid use
   of void expression". Fixed with the same `_locally_binds_name` gate.

3. **The actual C-level symbol collision**: `runtime/mojo_runtime.h`/
   `.c` declared and defined a genuinely dead, unreferenced `int any(void
   *iterable)` — grep-confirmed nothing in this codebase ever calls it
   (the real `any()`/`all()` builtin dispatch has always gone through
   `mojo_list_any`/`mojo_list_all` instead, per `_lower_builtin_all_any`).
   Being unprefixed (unlike every other runtime export, which uses the
   `mojo_` prefix precisely to avoid this), it collided at the C level
   with `tokenize.py`'s own compiled `any` function: since `any(*choices)`
   is variadic, its overload-mangling suffix is empty (`_overload_suffix`
   returns `''` for a `...`-shaped signature) and it's referenced from
   within its own module (empty qualifier too), so `_func_csym('any')`
   legitimately collapses to the literal bare name `any` — directly
   colliding with the runtime's dead declaration/definition
   ("conflicting types for 'any'; have 'char *(MojoList *)'"). Removed
   the dead runtime symbol entirely (both the `mojo_runtime.h` decl and
   the `mojo_runtime.c` definition) rather than re-guarding it, since it
   was never called by anything.

   A 4th, related fix was needed to get a fully clean isolated compile:
   `_lower_UnaryOp`'s spread-detection (`*iterable` in a call/list
   context) only recognized `MojoList *`/`MojoDict *`/`MojoSet *` as
   spread-pass-through types, not the generic `void *` that
   `map()`/`filter()`/`zip()` return in C (`mojo_map`: `void
   *mojo_map(void *func, void *iterable) { return iterable; }`). Real:
   `Special = group(*map(re.escape, sorted(EXACT_TOKEN_TYPES,
   reverse=True)))` (line 124) — `*map(...)` fell through to the
   "pointer dereference" branch, emitting a literal `*_t211` on a
   `void *` value (always invalid C, never a case a real dereference
   could have produced valid output for regardless of the cast applied
   afterward — this was dead/broken for every caller). Fixed by adding
   `'void *'` to the recognized spread-pass-through types.

   **NOT fixed, found but out of scope**: even after all 4 fixes,
   `group(*map(...))`'s SEMANTICS are still wrong — `_emit_call`'s
   general `param_types[-1] == '...'` vararg-packing (and the sibling
   `_pack_vararg_trailing_params`) unconditionally treats every element
   of `arg_pairs` as a scalar to `mojo_list_append_int`-pack into a
   fresh list, with no awareness that a single already-`MojoList *`/
   `void *`-typed spread argument should be passed through AS the
   vararg list, not wrapped as one more element of a new one. Confirmed
   with an isolated repro
   (`def group(*choices): ...; group(*parts)` where `parts` is a real
   list) — `parts` gets appended as a single raw-pointer-cast-to-int64
   element into a brand new list, which `group` then receives instead
   of its real elements. Also confirmed a second, distinct instance of
   the SAME missing-type-awareness bug: a literal (non-spread) call
   like `any("cat")` into a `*choices`-vararg function packs the `char
   *` argument via `mojo_list_append_int` unconditionally, corrupting
   it (verified end-to-end: `print(any("cat"))` printed the string's
   raw pointer value as a decimal number, not `"(cat)"`). Both are
   pre-existing (present before this session's fixes; the void* passthrough
   fix above only stopped a REAL COMPILE ERROR, it didn't touch this
   packing logic) and orthogonal to the `any`/`all` builtin-shadowing
   class of bug this pass targeted — general vararg-argument packing
   ignoring the real per-argument C type is a much bigger, riskier
   change spanning every `*args`-taking function call in the codebase,
   not attempted here. Not yet filed as its own doc.

Verification:
- Isolated `Lib/tokenize.py` compile (`compile_to_gimple` +
  `gcc-mp-15 -fgimple -fsyntax-only`): all 3 originally-reported errors
  (`any`×2, line-124 void-expression) are gone — 0 errors.
- Real `mojo.py build` of the real
  `/Users/mrs/net/Python-3.14.6/Lib/tokenize.py`: 0 `any`/`perror`/
  line-124-class errors remain for `tokenize.py` itself. One unrelated,
  already-documented `tokenize.py`-own error remains (the `__author__ =
  'Ka-Ping Yee <ping@lfw.org>'` pointer-from-integer assignment noted in
  the 2026-08-09 status below), plus the already-documented, unrelated
  cascading failures in transitively-imported files (`codecs.py` 47,
  `argparse.py` 33, `typing.py` 16, `inspect.py` 12, `enum.py` 10,
  `posixpath.py` 9, `os.py` 9, ...). The file does NOT build fully clean
  end-to-end yet — doc kept open, not deleted.
- Regression repro (real `mojo.py build` + run, not just isolated
  compile): a module defining its own non-vararg `def any(x): return x
  + x` called as `any("cat")` correctly prints `catcat` (was previously
  misrouted to the builtin stub). A module NOT shadowing `any`/`all`
  still gets correct builtin behavior: `any([True, False])` → `1`
  (True), `any([False, False])` → `0` (False).
- Quality gate: `test_gimple.py` 248/248, `test_module_cache.py` 76/76,
  `make check-selfhost` pass (unchanged). A from-scratch
  `build_stdlib_dylib.build_stdlib()` rebuild: 0 skipped modules both
  before (baseline worktree at 476050f) and after — no regression.
  `compile_stdlib.py -j8`: 664/664 passed, 0 unexpected, matching the
  documented baseline — no regression.

## Status (updated 2026-08-18)

The `perror` half of the "`any`/`perror` name collisions" blocker
described below is now FIXED (gimple_codegen.py). Root cause was NOT a
libc-name-specific gap: `_gen_stmt_ExprStmt` (the codegen's dedicated
lowering path for a bare, value-discarding call statement — e.g.
`perror("...")` used as its own statement, not assigned/consumed) had
its own independent copy of the "is this call to a nested sibling
closure" resolution logic, and that copy never got the
`_lambda_outer_closures` sibling-closure fallback that `_lower_call`
(the value-CONSUMING call path) already had. So a nested `def` calling
one of its OWN SIBLING nested `def`s (e.g. `tokenize.py`'s `_main()`
defining both `perror(message)` and `error(...)`, with `error()` calling
`perror(...)` as a bare statement) fell through to the generic
unqualified-name path and emitted a bare, unmangled `perror (...)` C
call — which collides with libc's real `perror` (declared via
`<stdio.h>`), producing `conflicting types for 'perror'`. Confirmed via
a minimal isolated repro (a module-level function with two nested
`def`s, one calling the other by bare statement) and by direct
inspection of the emitted `.ci`: before the fix, calls to a nested
`perror` sibling from within another sibling closure's body emitted
bare `perror (_t6);`; after the fix they correctly emit the mangled
`_main_perror (_t6);` (matching the qualified symbol the closure was
actually defined under).

Fix: added the same `_lambda_outer_closures.get(raw_name)` sibling-
closure lookup already used by `_lower_call` to `_gen_stmt_ExprStmt`'s
closure-call handling, right after its existing (enclosing-scope-only)
`self._closure_envs` check.

Re-verified via a real, direct `mojo.py build` of the actual
`/Users/mrs/net/Python-3.14.6/Lib/tokenize.py` (not just the isolated
repro): `grep -c "conflicting types for 'perror'"` on the build output
is now 0 (previously nonzero, confirmed reproduced pre-fix in this same
session). The build as a whole **still fails** — the `any` builtin-name
collision noted below is untouched (separate, unrelated mechanism —
`_lower_named_call`'s own `fname_raw in ('all', 'any')` special case, not
investigated/fixed here), plus a large number of other, already-
documented unrelated cascading failures in transitively-imported stdlib
files (`Lib/codecs.py`, `Lib/argparse.py`, `Lib/typing.py`, etc., per the
2026-08-09 status below). Only the specific `perror`/libc-collision error
class is confirmed resolved.

Quality gate: `test_gimple.py` (248/248), `test_module_cache.py`
(76/76), `make check-selfhost` all pass unchanged. A from-scratch
`build_stdlib_dylib.build_stdlib()` rebuild shows 0 skipped modules both
before and after the fix (no regression).

## Status (updated 2026-08-09)

Re-verified against current master (98e5aa3) with a real rebuild (real
gcc-mp-15/g++-mp-15 via `mojo.py build`, top-level target). **Still NOT
diagnosable as a generator-codegen-cluster issue** — same conclusion as
the 2026-08-06/07 passes, confirmed unchanged. `tokenize.py`'s own
`any`/`perror` name collisions (this codegen's builtin `any()` and libc
`perror` handling) still block compilation well before the generator-
eligibility pass is ever reached for `tokenize()`'s own `yield from
_generate_tokens_from_c_tokenizer(...)`:
```
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:63:8: error: conflicting types for 'any'; have 'char *(MojoList *)'
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:3265:31: error: conflicting types for 'perror'; have 'int64_t()' {aka 'long long int()'}
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:124:9: error: invalid use of void expression
```
One additional, previously-unseen error in this file itself (line
numbers shifted slightly vs. the 2026-08-06 pass due to unrelated
upstream changes, but the `any`/`perror` collisions are the same named
symbols as before):
```
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:23:28: error: assignment to 'char *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
```
— `__author__ = 'Ka-Ping Yee <ping@lfw.org>'`, a plain top-level string
literal assignment to a dunder name; not investigated further (ordinary
codegen, unrelated to generators, and this file's build is already
blocked by the other 2 errors regardless).

The overall build (500 errors total across the whole transitive closure)
is now completely dominated by unrelated cascading failures in
transitively-imported stdlib files reached from `tokenize.py`'s own
`import re`/`from codecs import lookup, BOM_UTF8` etc. chain — chiefly
`Lib/codecs.py` (346 errors alone), plus `Lib/argparse.py` (40),
`Lib/typing.py` (20), `Lib/inspect.py` (12), `Lib/enum.py` (12),
`Lib/posixpath.py` (9), `Lib/os.py` (8), `Lib/contextlib.py` (7),
`Lib/gettext.py` (5), `Lib/functools.py` (5) — none of which implicate
`tokenize.py`'s own generators or code.

**Classification unchanged: NOT actually diagnosable as a generator-
codegen-cluster issue from the current build output.** The `any`/
`perror` builtin/libc name-collision fix remains out of scope for this
doc (a separate, already-known, ordinary free-function-naming gap); not
attempted here. Whether `tokenize()`'s own `yield from
_generate_tokens_from_c_tokenizer(...)` refusal (previously observed
only when reached transitively via `enum.py`, cross-referenced in
`bugs/hard/CODEGEN_generator_function_symbol_not_module_qualified.md`,
now FIXED per that doc) still reproduces once the name-collision
blockers are fixed remains unconfirmed either way.

## Status (updated 2026-08-07, superseded above)

`bugs/hard/CODEGEN_generator_function_symbol_not_module_qualified.md`
(cross-referenced below) is now FIXED. Not independently re-verifiable
for THIS specific file, though: as this doc's own 2026-08-06 note
already found, `tokenize.py`'s build is blocked by unrelated `any`/
`perror` name collisions before compilation ever reaches the generator-
eligibility pass, so whether the module-qualification fix actually
changes this file's outcome remains unconfirmed either way — not
investigated further (the `any`/`perror` collision fix is out of scope
here, same as before).

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, but the failure has moved well before the generator
codegen stage. Re-diagnosed against current master (`2b0c4c5`); the
2026-07-30 `'detect_encoding' was not declared` .cpp error no longer
reproduces, and — notably — `MOJO_DEBUG=1` when `tokenize.py` is built as
the TOP-LEVEL file shows NO "not eligible" refusal for `tokenize()`
itself at all (contrast with `bugs/CODEGEN_generator_function_Lib_enum.md`'s
re-diagnosis, which — reaching `tokenize.py` only as a TRANSITIVE import
— did see `tokenize`'s own `yield from
_generate_tokens_from_c_tokenizer(...)` refused for delegating to a
non-Python/C-extension generator target; that refusal apparently isn't
even reached when building this file directly, because the build aborts
earlier).

Current failure is two ordinary top-level name collisions with this
codegen's builtin/libc name handling, reached BEFORE the generator
eligibility pass runs at all:

```
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:63:8: error: conflicting types for 'any'; have 'char *(MojoList *)'
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:2275:31: error: conflicting types for 'perror'; have 'int64_t()' {aka 'long long int()'}
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:124:9: error: invalid use of void expression
```
`tokenize.py` defines its own top-level `def any(*choices): return
group(*choices) + '*'` (line 61) and (unconfirmed line, not located in
this pass) a `perror`-named symbol — both collide with this codegen's
own builtin-name (`any()`) / libc (`perror`) handling, an ordinary
free-function-naming gap unrelated to generators.

**Classification: NOT actually diagnosable as a generator-codegen-
cluster issue from the current build output** — the file never reaches
far enough into compilation for `tokenize()`'s own generator eligibility
to be evaluated when built as the top-level target. Given the OTHER
(enum.py-transitive) run DID see `tokenize()` refused for the C-extension
`yield from` delegation target, that refusal — cross-referenced in
`bugs/CODEGEN_generator_function_Lib_enum.md` and
`bugs/hard/CODEGEN_generator_function_symbol_not_module_qualified.md` —
is presumably still real and would resurface once the `any`/`perror`
name-collision blockers are fixed. Not investigated further here (name-
collision fix is out of scope for this generator-codegen cluster).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/tokenize.py
