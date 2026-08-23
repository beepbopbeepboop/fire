# COMPILE_FAIL: Lib/importlib/_bootstrap.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py`

## Status (updated 2026-08-23 — RESOLVED, builds and links clean)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/importlib/
_bootstrap.py` fresh against master `626f3f0` (plus this cluster's own
commit fd909e9): **exit code 0, a linked executable is produced**
(`Built: .../_bootstrap`). The previously-open link-time blocker below
(`__WeakValueDictionary__KeyedRef` / `__WeakValueDictionary_data`
undefined symbols from `self.data[key]()` / `self._KeyedRef(default,
key)` inside `_WeakValueDictionary.setdefault`) no longer reproduces —
resolved by upstream call-lowering work landed between 2026-08-10 and
now (the SubscriptExpr-on-member call shape now lowers through a real
path instead of the bracket-generic-method misdispatch; most plausibly
1f26bb5's obj[key] protocol dispatch and f82b87c's weak-stub binding
for never-defined callees, which together turn those two call shapes
into either real lowerings or honest weak stubs that link). Not
independently re-investigated further since the repro is simply green.
All three originally-tracked issues (#1 `_verbose_message` vararg
packing, #2 `cls._SEP`, #3 `with`-statement `__exit__` literal casts)
remain fixed as documented below.

Closing this doc as RESOLVED against current master.

## Status (updated 2026-08-09)

Re-verified fresh. Substantial progress since the 2026-08-08 note below:

- **Issue #1 (`_verbose_message`'s line-951 call) is now FIXED.** Root
  cause: the vararg-trailing-param packing mechanism (the
  `_vararg_trailing_param_types` fix from 2026-08-08) had only ever been
  wired into `_lower_named_call`, the value-CONSUMING call-lowering path.
  `_verbose_message('import {!r} # {!r}', spec.name, spec.loader)` at
  line 951 is a bare, value-DISCARDING statement (its `None` return is
  never used) — that goes through `_gen_stmt_ExprStmt`, a completely
  separate, independently-duplicated general-call-building code path
  (the same "statement-level twin" duplication pattern already
  documented at half a dozen other sites in this file:
  len/list/tuple/exit/quit/main-redirect), which never had the
  equivalent trailing-param-packing logic at all. Fixed by extracting
  the packing logic into a new shared `_pack_vararg_trailing_params()`
  helper (gimple_codegen.py) and calling it from both
  `_lower_named_call` and `_gen_stmt_ExprStmt`. Confirmed: the
  "passing argument 2 of '_verbose_message' makes pointer from integer
  without a cast" error at line 951 no longer reproduces. Full 5-part
  quality gate run clean (247/0 test_gimple, 76/0 test_module_cache,
  check-selfhost clean, 0 skips on stdlib dylib rebuild, 664/664 0
  unexpected on compile_stdlib.py).
- **Issue #2 (`cls._SEP` dynamic class attribute) is now also resolved**
  — no longer produces any error, as a side effect of the separate,
  broader `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md`
  fix (Steps 1-4, landed 2026-08-07): `cls._SEP`/`cls._SEP = ...` now
  goes through real per-object dynamic-attribute storage instead of a
  hard "request for member in something not a structure or union"
  compile error.
- **Issue #3** (the `with`-statement `__exit__` dummy-arg / `_ensure_
  local` literal-cast bug) — already fixed 2026-08-07, unaffected.

**This file still does NOT compile end-to-end — a NEW, different,
previously-masked blocker is now the sole remaining issue**, surfaced
only once issues #1/#2 stopped blocking the compile earlier:

```
Undefined symbols for architecture arm64:
  "__WeakValueDictionary__KeyedRef", referenced from:
      __WeakValueDictionary_setdefault in _bootstrap.o
  "__WeakValueDictionary_data", referenced from:
      __WeakValueDictionary_setdefault in _bootstrap.o
ld: symbol(s) not found for architecture arm64
```

This is a LINK-time error, not a compile-time one — the whole file now
compiles to GIMPLE/C cleanly (0 `error:` from GCC), and only fails at
the final link step. Root cause: `_WeakValueDictionary` (lines 62-134,
a hand-rolled minimal weakref-values dict used by `_ModuleLock`) has:

```python
def __init__(self):
    class KeyedRef(_weakref.ref):     # locally-defined nested class
        ...
    self._KeyedRef = KeyedRef         # stashed as a callable-class attribute
    self.clear()

def clear(self):
    self.data = {}                    # a MojoDict*-typed field

def setdefault(self, key, default=None):
    try:
        o = self.data[key]()          # <-- subscript-then-call on an attribute
    except KeyError:
        o = None
    ...
        self.data[key] = self._KeyedRef(default, key)   # <-- call an attribute-held class
```

`self.data[key]()` and `self._KeyedRef(default, key)` are both call
expressions whose callee is `SubscriptExpr`/plain access on a
`MemberExpr` (`self.<attr>`). `_lower_call` (gimple_codegen.py, ~line
13901) has an existing special case: `if isinstance(node.func,
SubscriptExpr) and isinstance(node.func.obj, MemberExpr):` — designed
for Mojo's comptime-bracket-parametrized generic METHOD call pattern
(`self.some_method[T](args)`). That branch fires UNCONDITIONALLY for
ANY `<member>[<subscript>](<args>)` call shape, with no check that
`method_name` (`node.func.obj.member`, here `'data'`) is actually a
real declared method on the receiver's struct — it just discards the
subscript (`[key]`) entirely, treats the outer member name as a
method name, and lowers `self.data[key]()` as if it were the 0-arg
call `self.data()`. Since `data`/`_KeyedRef` are ordinary struct FIELDS
(not methods), this produces a call to a synthesized, never-actually-
defined weak-stub-style symbol (`_WeakValueDictionary_data`/
`_WeakValueDictionary__KeyedRef`) that only gets a *declaration*, not a
definition — hence the link-time (not compile-time) "symbol(s) not
found" failure.

This is a genuinely different bug from the file's originally-tracked
issues: two syntactically-identical call shapes (`obj.name[X](Y)`)
have different real Python semantics — a bracket-generic method call
vs. an ordinary "subscript a dict/list-valued attribute, then call the
retrieved value" — and the codegen's existing bracket-generic-method
special case has no disambiguation between them. **Classified as
structural/high-risk, not attempted**: this exact call-lowering branch
(comptime bracket-param generic method dispatch) is independently
flagged elsewhere in this session's history as an already-known-buggy,
high-value/high-risk area (`f[N](...)` silently compiling to 0), and
`_lower_call`/`_lower_named_call` are both extremely large, heavily
cross-cutting shared functions with documented history of narrow-
looking fixes causing broad silent regressions elsewhere in this
codebase (the "_tuplegetter incidents"). A safe fix would need to
verify `method_name` is a genuine registered method of `_struct_name`
before taking this branch, and provide a real fallback lowering for
"call the value produced by subscripting a struct member" (which does
not currently exist anywhere in `_lower_call` — the nearest neighbor,
the `not isinstance(node.func, IdentExpr)` block a few dozen lines
below, only handles `CallExpr`/`LambdaExpr` callees, not
`SubscriptExpr(MemberExpr)` ones) — real, but nontrivial, scoped work
for a future session, not a one-line guard.

## Status (updated 2026-08-08)

Issue #1's real root cause was misdiagnosed in the note below (it is
NOT an instance of #143's unannotated-param bug — `_verbose_message`'s
`message` param has no annotation, but that's not what's wrong here).
Actual cause: `_verbose_message(message, *args, verbosity=1)` — a
vararg followed by a real trailing (keyword-only) parameter, with no
`**kwargs`. `_emit_call`'s packing-sentinel check only fires when
`'...'` is the LAST entry of a callee's param-type list; here it isn't
(`verbosity` follows it), so packing silently never happens and the
call's extra positional arguments get coerced 1:1 against the wrong
concrete param types. Root-caused, fixed at the call-lowering level
(`_lower_named_call`, `gimple_codegen.py`) — a new `_vararg_trailing_
param_types` persistent table plus packing logic generalized to find
the sentinel anywhere in the signature, not just the last position.
Confirmed correct via 3 hand-written repros (basic case, an explicit
keyword override of the trailing param, and no regression on the
sibling `#142` args/kwargs fix) and the full 5-part gate.

**This specific file still does not compile end-to-end** — the exact
call site at line 951 continues to fail with the same symptom even
after the fix, for a reason not yet isolated (confirmed NOT a caching
artifact — reproduced with a fully isolated `GMOJO_HOME`). Direct
inspection shows `self._vararg_trailing_param_types['_verbose_message']`
holds the CORRECT signature by the time `gen_module` finishes for this
file, so the gap is somewhere between that correct registration and
this one call site's actual lowering — possibly a further code path
in `_lower_call`/`_lower_named_call` not yet identified for a file this
large and structurally complex. The underlying mechanism fix is real,
tested, and gate-verified (worth keeping), but does not yet close this
doc. Left as a genuine open item rather than force-closing it.

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
