# CODEGEN_generator_function: Lib/tokenize.py

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
