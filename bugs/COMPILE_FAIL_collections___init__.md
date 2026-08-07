# COMPILE_FAIL: Lib/collections/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py`

## Status (re-verified 2026-08-07, Track B continuation session)

A fresh build now stops EARLIER than all three issues below, at an
honest generator-codegen refusal:

```
cannot compile module: function(s) __reversed__ (generator function(s),
contain a `yield`/`yield from`) ...
```

`OrderedDict.__reversed__` (a generator method) hits the same scalar-
yield/return-only limitation documented in `bugs/CODEGEN_generator_
function_Lib_weakref.md`'s 2026-08-07 update and `bugs/hard/CODEGEN_
generator_struct_typed_param_refused.md` (task #147, explicitly out of
scope this session). Whether issues #1-#3 below are still live can't be
re-confirmed without either fixing that generator limitation first or
patching around it locally — not attempted, consistent with this
session's scope. (Issue #2's dynamic-attribute findings may be at least
PARTIALLY moot now — `bugs/hard/CODEGEN_dynamic_attribute_on_generic_
object.md`'s Steps 1-4 landed earlier the same day and explicitly cover
`MojoBoundMethod` as a "fixed-layout runtime struct" sub-case — but this
wasn't independently re-verified since the build never reaches that far
anymore.)

## Status (updated 2026-08-06, historical — see above, a new earlier blocker now masks these)

Multiple distinct issues, none yet fixed. Root-caused three of them; a
fourth not yet investigated.

### 1. `redefinition of '_tuplegetter'` — two independent weak-stub mechanisms collide

```python
try:
    from _collections import _tuplegetter
except ImportError:
    _tuplegetter = lambda index, doc: property(_itemgetter(index), doc=doc)
```

`_collections` is a C-implemented builtin module this compiler's
`load_module()` can't resolve. TWO INDEPENDENT weak-stub mechanisms in
gimple_codegen.py both decide `_tuplegetter` needs a weak
"unavailable in compiled mode" definition, under DIFFERENT guard-macro
conventions, so BOTH textually emit a real C function definition:

- `_lower_named_call`/`_gen_stmt_ExprStmt`'s auto-stub path (the
  `_is_unknown` branch), guarded by `_MOJO_STUB_{NAME}`.
- `_emit_stdlib_import_externs`'s pre-existing "stub from {module}"
  mechanism (gimple_codegen.py ~line 30919), guarded by `#ifndef
  {bare_name}` — a DIFFERENT macro name, so neither guard covers the
  other.

Result: `int64_t _tuplegetter (...)` gets defined TWICE in one
translation unit — "redefinition of '_tuplegetter'".

**Two fix attempts tried 2026-08-06, BOTH REVERTED — do not repeat
either without addressing why they failed:**

1. Share a Python-level `_emitted_unresolved_stub_syms` set (module-level,
   already used by the two pre-existing sites) between all FOUR
   consumers, skipping re-emission if a name is already present. This
   compiles collections/__init__.py clean, but broke `compile_stdlib.py`
   broadly: 5 UNEXPECTED failures (`test_stencil.mojo`,
   `test_ref_iteration.mojo`, `test_tanh.mojo`, `test_span.mojo`,
   `test_unsafe_pointer.mojo`), each losing an UNRELATED symbol's own
   needed declaration (`FormatStruct`/`TypeNames`/`CompilationTarget`/
   `mojo_abort`/`unlikely` — none of these are Python-stdlib-import-
   related at all). Root cause: the shared set is used by OTHER,
   unrelated purposes elsewhere in the file too broadly — some other
   name's registration into the set (for an entirely different, correct
   reason) caused a LATER, genuinely-needed declaration for an unrelated
   symbol to be wrongly suppressed.
2. Change the auto-stub path's OWN guard to match the OTHER mechanism's
   convention (bare C symbol name, `#ifndef {fname}`, no Python-level
   state at all — just relying on the C preprocessor). This ALSO broke
   compile_stdlib.py, WORSE than attempt 1: 8+ unexpected failures, all
   with an IDENTICAL new symptom ("expected identifier or '(' before
   '...' token") at a suspiciously consistent line (~342) across many
   unrelated monomorphized generic-instantiation files. Root cause not
   fully traced, but strongly suggests using a BARE function name as a
   `#ifndef` guard collides with some OTHER, unrelated declaration
   elsewhere that ALSO happens to use the bare name as ITS OWN guard for
   a completely different purpose (e.g. a real, typed forward
   declaration that then gets suppressed by my weak variadic stub's
   guard firing first).

Both attempts passed test_gimple.py/test_module_cache.py cleanly — this
regression was ONLY visible via the full compile_stdlib.py -j8 664-file
run, not the fast suites. Reverted both; `git diff` confirmed a byte-
identical return to the last-known-good commit, re-verified 664/664
clean.

**What a real fix needs**: something MUCH more narrowly scoped than "any
name ever stubbed anywhere in this compile" or "the bare C symbol name
itself". Candidate approach not yet tried: have `_lower_named_call`/
`_gen_stmt_ExprStmt`'s auto-stub path specifically check whether
`_emit_stdlib_import_externs` will ALSO handle this exact name — e.g. by
checking `fname_raw in self.imported_symbols` (which `_emit_stdlib_
import_externs` iterates directly) — and skip ITS OWN stub emission only
in that specific, narrow case, rather than any shared "already stubbed"
signal. This keeps the two mechanisms' guard conventions untouched
(avoiding the attempt-2 regression) and doesn't touch unrelated names at
all (avoiding the attempt-1 regression).

### 2. Dynamic-attribute hard bug instances (3 confirmed here)

- `OrderedDict.__new__`: `self = dict.__new__(cls)` (opaque `self`) then
  `self.__hardroot = _Link()` / `.prev` / `.next` — "request for member
  '__root'/'prev'/'next' in something not a structure or union".
- `expected identifier before '__func__'` (line 460/490) — a
  `__func__`/bound-method dunder-attribute access.
- `'MojoBoundMethod' has no member named '__doc__'` (line 469).

All three are instances of bugs/hard/CODEGEN_dynamic_attribute_on_generic_
object.md (task tracked separately — see that doc's plan, Steps 1-4 for
the generic-object case, Step 0 doesn't cover these since `__hardroot`/
`__func__`/`__doc__` are genuinely NEW attributes, not reflectable
known-fields).

### 3. `incompatible types when assigning to type 'Counter' from type 'int64_t'` (line 944, 957)

Not yet investigated. Likely a return-type or constructor-lowering gap
specific to `Counter` (a `dict` subclass) — worth checking whether it's
related to `Counter.__init__`'s `*args, **kwds` signature or its
`dict.__new__`-style construction pattern, given `Counter` is defined via
`class Counter(dict):` (subclassing a BUILTIN type, not a user struct —
possibly the same general class of gap as `OrderedDict.__new__`'s `dict.
__new__(cls)` above).
