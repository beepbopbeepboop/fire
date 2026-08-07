# COMPILE_FAIL: Lib/importlib/_bootstrap.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py`

## Status (updated 2026-08-07, Track B continuation session)

Issue #3 (below) is now FIXED — see its own updated section. Down to a
single remaining error (issue #1, `_verbose_message`), which is a
confirmed instance of an ALREADY-EXCLUDED hard bug for this session
(`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`,
task #143 — explicitly on this session's "do not touch" list) — not
attempted. Issue #2 (`cls._SEP` dynamic class attribute) was NOT
re-verified this pass (the build now stops at issue #1's single
remaining error before reaching whatever issue #2's line would produce;
not otherwise re-tested standalone).

## Status (updated 2026-08-06, historical — issue #3 below now fixed)

Three distinct issues found. None fixed in this file directly, but one
investigation (issue #1) led to discovering a major, previously-unknown
hard bug now tracked separately with its own high-value fix plan.

### 1. Root cause found (not fixed in this session): unannotated `__init__` params default struct fields to `int64_t`

```
error: passing argument 2 of '_verbose_message' makes pointer from integer without a cast
```
at:
```python
_verbose_message('import {!r} # {!r}', spec.name, spec.loader)
```

`ModuleSpec.__init__(self, name, loader, *, origin=None, ...)` — `name`
and `loader` are BOTH unannotated, no-default parameters, directly
assigned to `self.name`/`self.loader`. This is the exact triggering
shape of a newly-discovered, high-priority hard bug:
**bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md**.
Root cause: `gen_module`'s struct-field-type collection
(`_collect_self_assigns`) types a field assigned from a plain
`self.field = param` as `param`'s OWN declared type, but for an
unannotated no-default parameter that's an unconditional `int64_t`
fallback — never cross-referencing how the class is ACTUALLY
constructed elsewhere (`ModuleSpec(name, loader)` real call sites in
this same codebase). `spec.name`/`spec.loader` end up declared `int64_t`
in the generated C struct, and passing them to `_verbose_message`
(which expects pointer/string arguments for its `{!r}` format
placeholders) is a hard GIMPLE type error — the concrete, compile-
FAILING manifestation of a bug the hard-bug doc's own minimal repro
otherwise shows as a SILENT wrong-VALUE bug (still compiles, just prints
garbage) when the mistyped field is consumed in a more permissive
context (e.g. list/string concatenation, which happens to also accept a
bare int64_t without complaint).

Not fixed here — see the hard-bug doc for the full root cause, why it's
scoped as high-risk (same call/parameter-type-inference machinery
already responsible for two real regressions elsewhere this session),
and the concrete fix-direction plan (extend the existing free-function
"cross-call scalar contract" pass, currently scoped only to
`_free_params`, to also observe constructor call sites and feed
`_collect_self_assigns`).

### 2. Dynamic-attribute hard-bug instance (#136)

```
error: request for member '_SEP' in something not a structure or union
```
at:
```python
@classmethod
def _resolve_filename(cls, fullname, alias=None, ispkg=False):
    ...
    try:
        sep = cls._SEP
    except AttributeError:
        sep = cls._SEP = '\\' if sys.platform == 'win32' else '/'
```
`cls` (a classmethod's implicit class-reference parameter) is opaque to
this compiler, and `_SEP` is a dynamically-stashed class attribute (set
lazily via `hasattr`/`AttributeError`-catch idiom) — the same shape as
the hard bug's own `cls.__slot_names__` examples. Added as a confirmed
instance.

### 3. FIXED (2026-08-07): line 393 was a #line misattribution — the real site was `_ModuleLock.acquire`'s `with`-statement `__exit__` dummy-arg plumbing

```
error: non-trivial conversion in 'integer_cst'
```

The `393` (`_ModuleLock.__repr__`'s f-string) turned out to be a RED
HERRING — GCC reports the LAST `#line` directive still active for a
statement sequence that has none of its own, and the actual generated
statements at fault (`_t48 = 0; _t49 = (MojoList *)_t48;` etc., visible
in the raw `.ci`) live inside `_ModuleLock.acquire`'s compiled `with
_blocking_on(self, tid):` handling, several hundred `.ci` lines earlier
than the last real `#line` marker — a instance of the same "#line
mislabels inherited/synthesized text" class of diagnostics confusion
already documented elsewhere in this bug database (see `bugs/CODEGEN_
generator_function_Lib_weakref.md`'s earlier finding #1).

**Root cause**: `_gen_stmt_WithStmt`'s `_emit_exits()` (gimple_codegen.py,
~line 18851) pads a compiled `__exit__` call with dummy `('int64_t',
'0')` arguments for Python's `exc_type`/`exc_val`/`exc_tb` protocol
params on the normal (non-exceptional) exit path. When `__exit__`'s real
parameter type at that position is a POINTER (e.g. `MojoList *`/
`MojoDict *`, as `_BlockingOnManager.__exit__`'s signature has here),
`_emit_call`'s "semantic types match but C types differ" coercion branch
(~line 5771) does `aval_local = self._ensure_local('int64_t', aval)`
then `self._emit(f'  {ip3} = {aval_local};')` where `ip3` is a freshly
declared `int64_t` temp — but `_ensure_local` used to return a BARE
digit-literal string (`'0'`) completely unchanged whenever `val` was a
plain numeric literal, regardless of what `ctype` the caller actually
needed it typed as. GIMPLE (unlike ordinary C) requires the RHS of a
plain assignment to already carry the EXACT declared type of the LHS —
a bare literal `0` defaults to plain `int`, so `int64_t _t48; ... _t48 =
0;` is a real "non-trivial conversion in 'integer_cst'" error, not a
warning.

**Fix**: `_ensure_local` (gimple_codegen.py, ~line 6028) now wraps a
numeric-literal `val` in an explicit `({ctype})` cast whenever `ctype`
doesn't match the literal's own natural GIMPLE type (`int` for a
decimal integer literal, `double` for one containing `.`) — matching
the `(int64_t)0`/`(int64_t)1`-style casts this same file already emits
correctly at dozens of OTHER call sites for the identical situation.
Scoped narrowly to the literal branch only; the existing variable/global
branch (declared-type-mismatch cast, `_declared_int_ctype`) is
untouched. `_ensure_local` has 48 call sites across `gimple_codegen.py`
— a genuinely cross-cutting helper — so this went through the FULL
5-part quality gate below, not just `test_gimple.py`/
`test_module_cache.py`.

**Verification**: `Lib/importlib/_bootstrap.py`'s 4 "non-trivial
conversion in 'integer_cst'" errors are gone (`grep -c 'error:'` 5 → 1,
the remaining one being issue #1, already excluded from this session).
Minimal repro (a `with`-statement over a context manager whose
`__exit__` takes pointer-typed extra params) also confirmed fixed
directly against `gimple_codegen.compile_to_gimple`.

**Quality gate (2026-08-07)**:
1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`1 passed, 0 failed`).
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — **664/664 passed, 0 unexpected
   failures** (unchanged from baseline).
