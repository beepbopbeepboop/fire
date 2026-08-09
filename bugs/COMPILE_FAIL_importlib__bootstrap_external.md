# COMPILE_FAIL: Lib/importlib/_bootstrap_external.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py`

## Status (updated 2026-08-09)

Three of the four originally-found issues are now FIXED (commit fd29316
and the platform-branch-selection fix 7014dde from prior sessions, plus
the `_write_atomic.__code__` dunder-member fix landed this session — see
below). Re-verifying against current master, the previously-open "invalid
conversion in gimple call" issue at lines 960/1190 no longer reproduces
either (fixed as a side effect of unrelated upstream codegen work; not
independently re-investigated since it's simply gone).

Fixing the `_write_atomic.__code__` compile error exposed a NEW,
deeper blocking issue past it: a LINK-time failure (5 undefined
symbols) rooted in two separate, genuinely structural gaps in how
`self.method(...)` calls resolve their target when the method isn't
defined on the statically-declared receiver class itself. See
"NOT FIXED: multiple-inheritance mixin / instance-callable-field
link failures" below — left open, not attempted, per CLAUDE.md's
guidance against forcing narrow fixes onto shared method-call-lowering
machinery.

### FIXED: `_write_atomic.__code__` at module scope (this session)

```
error: implicit declaration of function '_write_atomic'; did you mean '_write_atomic_132aaf'? [-Wimplicit-function-declaration]
```
at:
```python
_code_type = type(_write_atomic.__code__)
```
Root-caused precisely (the prior write-up's "likely a MODULE-level
analogue of `_closure_value_locals`" theory was never confirmed and
turned out to be looking in the wrong place). The actual culprit is
`_lower_MemberExpr`'s "zero-arg function used in member-access context"
heuristic (`gimple_codegen.py`, ~line 8916, comment `# e.g.
block_idx.x`): it exists so a GPU-intrinsic accessor like `block_idx.x`
— where `block_idx` is itself a zero-arg function returning a struct —
gets CALLED first before `.x` is read off the result. The heuristic
keys only on "MemberExpr whose base is a bare identifier naming a
known function" — it can't distinguish that shape from `f.__code__`,
where `f` is an ordinary (non-zero-arg, in this case 3-arg)
top-level function and `.__code__` is a real Python attribute of the
FUNCTION OBJECT ITSELF, never of some call result. It fired anyway,
emitting a genuinely invalid bare `_write_atomic ()` zero-arg call to
a real 3-parameter function.

Fixed by excluding dunder-named members (`node.member` matching
`__*__`) from the heuristic — real GPU-intrinsic accessor fields are
always lowercase (`x`/`y`/`z`), so this can't affect the case the
heuristic exists for. Excluded, the call falls through to the
`else` branch, which lowers the bare function identifier through
`_lower_IdentExpr`'s pre-existing "C function name used as a value"
branch (a `_funcptr_*` static void* — the exact mechanism this
codegen already uses everywhere else a function is referenced without
being called), and the surrounding `.{__code__}` MemberExpr access
then resolves through the ordinary opaque-pointer dynamic-dispatch
fallback (`_mojo_dispatch_getattr`), which compiles cleanly (returns
an inert `int64_t` — this codegen has no real notion of Python code
objects, same as the many other "class attr ... UNRESOLVED" runtime
stubs already established elsewhere in this file for obscure
introspection that this compiler doesn't model).

Full 5-part quality gate verified clean: `test_gimple.py` 247/247,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
dylib rebuild 0 `skip <module>:` lines, `compile_stdlib.py -j8` 664/664
passed (0 unexpected).

### FIXED: platform-conditional-def branch selection (7014dde, prior session)

`if _MS_WINDOWS: def _path_join(...): ...(Windows logic)... else: def
_path_join(...): ...(POSIX logic)...` used to always compile the WINDOWS
branch regardless of actual platform — a silently-wrong-runtime-behavior
bug, not just a compile failure. `gen_module`'s conditional-toplevel-def
promotion now resolves `sys.platform`-derived conditions and picks the
actually-correct branch.

### FIXED: global-list element type + conditional-global visibility (fd29316, this session)

```
error: assignment to 'int64_t' from 'char *' makes integer from pointer without a cast
```
at `_path_join`'s own `return path_sep.join([...])` (POSIX branch, now
correctly selected per the fix above) and a second occurrence at line
329. Root-caused to TWO compounding gaps in `gen_module`'s "Phase 1.7"
global-variable pre-scan:

1. It recorded a global list/tuple literal's own C type (`MojoList *`)
   but never its ELEMENT type, so `_quick_type`'s `SubscriptExpr` case
   (reading element types from `self._elem_types`) always fell through
   to `int64_t` for `OTHER = SOME_GLOBAL_LIST[idx]` — the real shape here
   is `path_sep = path_separators[0]`, `path_separators` being a global
   list of one-character strings.
2. The pre-scan only recognized a plain top-level `AssignStmt`, never
   descending into an `IfStmt`'s branches — so `path_separators` itself,
   assigned via `if _MS_WINDOWS: path_separators = [...] else:
   path_separators = [...]`, was invisible to the pre-scan (and thus fix
   #1 above) entirely.

Fixed both: element-type recording for global list/tuple literals, and
an iterative (non-self-recursive, matching this file's own established
self-host-safety convention for the def-promotion pass) flattening pass
that resolves any top-level conditional whose condition folds to a known
platform-constant bool down to just its correct branch before the
pre-scan runs. Full quality gate verified clean (test_gimple.py 247/247,
test_module_cache.py 76/76, check-selfhost clean, dylib rebuild 0 skips,
compile_stdlib.py -j8 664/664 0 unexpected).

### RESOLVED as a SEPARATE bug (2026-08-07 follow-up note, superseded)

The 2026-08-07 note previously here investigated whether `_write_atomic
.__code__` and `Tools/c-analyzer/c_analyzer/__main__.py`'s `FORMATS =
{'raw': fmt_raw, ...}` (bare-function-as-dict-value) shared one root
cause, and correctly concluded they don't (the c-analyzer instance is
a generator-function-as-value gap, part of the already-tracked
compiled-generator/async-codegen project — out of scope, unrelated).
It left `_write_atomic.__code__` itself "genuinely unexplained." It is
no longer unexplained: see "FIXED: `_write_atomic.__code__` at module
scope" above for the actual root cause (the `block_idx.x`-style
zero-arg-function-call heuristic in `_lower_MemberExpr` misfiring on a
dunder attribute access) and its fix.

### NOT FIXED (structural): multiple-inheritance mixin / instance-callable-field link failures

The previously-open "invalid conversion in gimple call" issue at lines
960/1190 no longer reproduces (fixed as a side effect of unrelated
upstream codegen work between 2026-08-06 and now; not independently
re-investigated, since the build now gets past that point cleanly).

With the `_write_atomic.__code__` fix landed, `python3 mojo.py build
Lib/importlib/_bootstrap_external.py` now compiles every translation
unit successfully but FAILS AT LINK TIME with 5 undefined symbols:

```
Undefined symbols for architecture arm64:
  "_SourceLoader_get_data", referenced from: _SourceLoader_get_source, _SourceLoader_get_code
  "_SourceLoader_get_filename", referenced from: _SourceLoader_is_package, _SourceLoader_get_source, _SourceLoader_get_code
  "__LoaderBasics_get_code", referenced from: __LoaderBasics_exec_module
  "__LoaderBasics_get_filename", referenced from: __LoaderBasics_is_package
  "__NamespacePath__path_finder", referenced from: __NamespacePath__recalculate
```

This traces to TWO distinct, both genuinely structural, gaps in how
`_lower_struct_method_call` (`gimple_codegen.py`, ~line 12461) resolves
a `self.method(...)` call site. It resolves purely from the STATIC
declared type of the receiver (`struct_name = _struct_name_of(ot)`,
`ot` being `self`'s own declared `{EnclosingClass} *` C type) and mangles
straight to `{struct_name}_{method}` — there is no virtual/vtable
dispatch honoring the concrete runtime subtype's actual MRO, and no
distinction between "method" and "instance field holding a callable."

**Gap 1 — mixin methods, both directions of the Template Method pattern.**
`SourceLoader(_LoaderBasics)` (source, line 767) defines `get_code`/
`get_source`, whose bodies call `self.get_data(path)` /
`self.get_filename(fullname)` — but `get_data`/`get_filename` are
defined only on the UNRELATED sibling class `FileLoader` (line 912, not
a base of `SourceLoader` at all), combined with `SourceLoader` only in
a THIRD, concrete class further down: `SourceFileLoader(FileLoader,
SourceLoader)` (line 962). Real Python resolves `self.get_data` at
runtime via `SourceFileLoader`'s MRO, landing on `FileLoader.get_data`
— this codegen has no such per-instance mechanism; it emits a static
call to `SourceLoader_get_data`, a symbol that is never defined
anywhere (only `FileLoader_get_data` exists), because `get_data` was
never written as a method of `SourceLoader` or any of ITS ancestors.
The inverse shape appears too: `_LoaderBasics.exec_module`/`is_package`
(line 737, the actual base class) call `self.get_code`/`self.get_filename`,
methods that `_LoaderBasics` itself never defines — real Python's
classic "base class calls a method the subclass must override" pattern,
which again needs dispatch on the concrete instance, not the
statically-declared base type.

An existing partial mechanism (`_lower_struct_method_call`'s
"auto-stub" — see the `if (mangled not in self._KNOWN_SIGS and ...
mangled not in self._auto_stubbed ...)` block just below the mangled-
name computation) already emits a real weak-linkage stub definition
for an unresolved call, but ONLY when `struct_name in
self._structs_with_unresolved_base` — i.e. only when the receiver's
base class is an EXTERNAL/unmodeled class this compiler never parsed a
`StructDef` for at all (e.g. `html.parser.HTMLParser`). Neither
`SourceLoader` (base `_LoaderBasics`, fully resolved and defined in
this same file) nor `_LoaderBasics` (no base at all) qualifies, so both
fall into the OTHER branch — a bare forward declaration
(`int64_t {mangled} (...);`) with no body, which is exactly what leaves
an undefined symbol at link time. The auto-stub's own scoping was
deliberately narrow (see its comment: "a same-struct sibling method not
yet emitted, which gets a real definition later" is the case a bare
forward-decl is fine for) — it was never meant to, and doesn't, cover
cross-class mixin resolution.

**Gap 2 — instance field holding a callable, invoked directly.**
`_NamespacePath.__init__` (line ~1101) does `self._path_finder =
path_finder` (storing an ordinary callable passed into the
constructor as plain instance state), and `_recalculate` (line 1117)
later does `self._path_finder(self._name, parent_path)`. This is not a
method call at all in Python — it's "read a field, then call whatever
it holds" — but `_lower_method_call`'s dispatch fires on syntax alone
(`obj.name(args)` where `obj`'s type is a known struct) without first
checking `self.struct_field_types[struct_name]` for a same-named FIELD
that would take precedence over a same-named method. It resolves
straight to a nonexistent `_NamespacePath__path_finder` function
symbol instead of reading the `_path_finder` field and invoking it as
a stored function pointer.

**Why this is left open, not fixed.** Both gaps require real design
work on shared, load-bearing method-call-lowering machinery
(`_lower_struct_method_call`/`_lower_method_call`), not a local stub
or missing-case fill-in:
- Gap 1 needs either genuine per-instance virtual dispatch (a vtable
  keyed by the concrete constructed type, threaded through every
  `self.method(...)` call site — a new value-representation concern
  this codegen doesn't have at all for structs today) or, at minimum,
  widening the existing auto-stub's `_structs_with_unresolved_base`
  condition to ALSO cover "method genuinely undefined anywhere in the
  whole compiled closure, receiver's base fully resolved or not" —
  which risks silently papering over a call that SHOULD be a hard
  compile error for other, genuinely-buggy Mojo source (the auto-stub
  degrades to a runtime "unavailable in compiled mode" printout rather
  than failing the build), a real semantic tradeoff, not a mechanical
  fix.
- Gap 2 needs `_lower_method_call` to check `struct_field_types` for a
  field shadowing the method name BEFORE treating `obj.name(...)` as a
  static method-call mangle — a real priority-ordering change to a
  dispatch decision every single method/attribute call in every
  compiled file goes through, exactly the kind of shared call-lowering
  machinery CLAUDE.md's quality-gate section warns has caused broad,
  silent regressions before when changed on a single narrow
  motivating case.

Per CLAUDE.md's explicit guidance ("a structural/systemic gap ... do
NOT force a fix ... just update the doc with an accurate, thorough
root-cause writeup and move on"), neither gap was attempted this
session. A future fix attempt should design Gap 1 and Gap 2 as
separate, deliberate features (real vtable dispatch and
field-before-method resolution ordering, respectively), each verified
against the full 5-part stdlib-breadth quality gate given how central
`_lower_method_call`/`_lower_struct_method_call` are to every compiled
Mojo file that uses classes.
