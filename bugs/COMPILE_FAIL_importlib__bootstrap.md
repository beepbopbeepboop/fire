# COMPILE_FAIL: Lib/importlib/_bootstrap.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py`

## Status (updated 2026-08-06)

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

### 3. Not yet investigated: line 393

```
error: non-trivial conversion in 'integer_cst'
```
at `_ModuleLock.__repr__`:
```python
def __repr__(self):
    return f'_ModuleLock({self.name!r}) at {id(self)}'
```
`_ModuleLock.__init__(self, name): self.name = name` is ALSO an
unannotated-param field (same shape as issue #1 above) — plausible this
is a THIRD manifestation of the same hard bug, but NOT confirmed: several
narrower standalone repros (a class with the same `self.name = name`
shape, with and without `_thread.RLock()`/`allocate_lock()` fields
added, with and without the exact `f'...{self.name!r}...{id(self)}'`
f-string shape) all compiled and LINKED successfully (producing wrong
*values*, matching the hard bug's expected silent-wrong-output symptom,
not a compile error) — none reproduced this specific "non-trivial
conversion in 'integer_cst'" GIMPLE error. The real `_ModuleLock` class
has more going on (real `_thread` primitives, multiple methods with
try/except and while loops around `self.count`/`self.waiters`/
`self.owner`) that a narrower repro didn't capture. Not root-caused
further — worth a focused follow-up once issue #1's hard bug has a real
fix (it may simply resolve on its own, given how strongly the shape
matches).
