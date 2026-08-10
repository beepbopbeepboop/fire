# CODEGEN_generator_function: Lib/test/test_deque.py

## Status (updated 2026-08-09)

Re-verified against current master with a real rebuild. Confirmed (and
now fixed) the "`deque`-name-collision" angle this doc's 2026-08-06 note
flagged as unconfirmed-but-worth-investigating: it was a genuine, narrow
codegen bug, NOT related to generator codegen, and NOT specific to this
file.

**Root cause:** the file has `class Deque(deque): ...` (line 801,
subclassing the module-level `from collections import deque` import).
Every `_MOJO_STUB_<NAME>`-guarded auto-stub/extern site in
`gimple_codegen.py` (16 call sites) built its guard macro via
`f'_MOJO_STUB_{name.upper()}'`. The struct-typedef path for `class Deque`
emits `#define _MOJO_STUB_DEQUE` right after the typedef (to suppress any
later stub of the same name — the guard's actual documented intent). But
because `.upper()` case-folded the name, that same macro also guards the
*unrelated* `deque` function's own weak-stub definition (`_lower_named_
call`'s "unresolved import used as a call" fallback) — its `#ifndef
_MOJO_STUB_DEQUE` sees the struct's `#define` already in effect and
silently skips emitting a stub, leaving `deque` with **no declaration
anywhere** in the translation unit → `implicit declaration of function
'deque'` at every one of the ~50 `deque(...)` call sites, cascading into
`error: unexpected RHS for assignment before ';' token` at each of those
assignment sites (`d = deque(...)`).

**Fix:** added a canonical `_stub_guard_name(name)` helper
(`gimple_codegen.py`, right after `_safe_name`) and switched all 16
`_MOJO_STUB_<NAME>` guard-construction sites to use it instead of each
independently re-deriving `f'_MOJO_STUB_{X.upper()}'`. The helper is
case-PRESERVING (`_MOJO_STUB_{name}`, no `.upper()`) — every site's
matching half always compared the exact same real C identifier string
already (confirmed by reading all 16 call sites' surrounding comments;
none relied on case-insensitive matching), so `.upper()` was purely
cosmetic SCREAMING_SNAKE_CASE styling that incidentally made the shared
guard namespace case-insensitive and let `Deque` (struct) and `deque`
(function) collide. Removing the fold eliminates the false collision
with no change to any genuine same-name dedup case.

Rebuilding `test_deque.py` after the fix: the `deque`-collision errors
(implicit-declaration + all the cascading "unexpected RHS" ones, ~55 of
the previous ~80 errors) are gone. The file still does not compile
clean — remaining errors are unrelated: `Lib/test/support/__init__.py`
import-time errors (a separate, pre-existing issue affecting any file
that imports `test.support`), the `_quick_type`/comprehension
"non-trivial conversion"/"mismatching comparison operand types" family
at lines 50/579/590/834 (`bugs/hard/CODEGEN_comprehension_return_type_
defaults_int64.md`'s sibling pattern — note line 834's exact error shape
recurred even though task #145 itself is fixed, so this is a distinct,
still-open trigger of the same general family, not a regression of #145),
and `error: expected expression before 'SubclassWithKwargs'` at line 920
(unrelated, not investigated). None of these implicate the file's own 2
generators (`yield 1` line 16, `yield next(task)` line 1012) — still not
a generator-codegen-cluster failure. Kept as a per-file record since the
file still doesn't compile clean, but the specific bug this doc's
history focused on (the `deque` collision) is resolved.

Full mandatory gate run after the fix: `test_gimple.py` 247/0,
`test_module_cache.py` 76/0, `make check-selfhost` clean, from-scratch
`libmojostdlib.dylib` rebuild 0 `skip <module>:` lines, `compile_stdlib.py
-j8` 664/664 passed 0 unexpected — all matching baseline exactly.

## Status (updated 2026-08-07, superseded above)

`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md` (task
#145, referenced below re: the lines-332/438/834 "non-trivial
conversion"/"type mismatch" pattern) is now fixed. This file's own
mention was only ever a speculative "sibling family" match, not
independently traced to a confirmed bare-`return`-comprehension shape
in this file's source, and this file was already classified as "NOT a
generator-codegen-cluster failure" dominated by unrelated errors — not
re-investigated further here.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'SyntaxError' was not declared` .cpp error no longer
reproduces. `test_deque.py`'s own 2 generator sites (`yield 1` line 16,
`yield next(task)` line 1012) do not appear in the current error list
and have no "not eligible" refusal.

**Classification: NOT a generator-codegen-cluster failure.** The file
has ~80 current errors, almost all `error: unexpected RHS for assignment
before ';' token` at dozens of distinct lines plus `error: implicit
declaration of function 'deque'` — this codegen appears to be failing on
an ordinary top-level construct used pervasively throughout this file
(possibly `self.assertRaises(...)`-style context-manager assignment
idioms, or the `deque(...)` constructor call itself colliding with a
reserved/builtin name similar to `tokenize.py`'s `any`/`perror`
collisions found elsewhere in this session's pass — not confirmed which,
given the volume). Also present: the recurring comprehension/`_quick_
type`-family "non-trivial conversion"/"type mismatch" pattern
(`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md`'s
sibling family) at lines 332/438/834. None of this implicates the file's
own 2 generators. Not investigated further — out of scope for this
generator-codegen cluster; the `deque`-name-collision angle in
particular looks worth a dedicated non-generator report given how many
lines it affects.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_deque.py
