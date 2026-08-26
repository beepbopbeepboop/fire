# COMPILE_FAIL: Lib/collections/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py`

## Status (updated 2026-08-26, wtOpencode_canalyzer2 — re-verified fresh; both
## stacked blockers confirmed live, neither tractable within scope)

Isolated `compile_to_gimple_with_cpp(do_imports=False)` fresh: the
`reversed(self._mapping)` refusal is byte-identical to the 2026-08-26
entries below. Probed past it by experimentally neutralizing ONLY the
three view `__reversed__` bodies in the source text (no compiler
change): the module's NEXT blocker is then exactly the long-tracked
`Counter[...] = ...` subscript-store honest refusal — so even a
complete `reversed()` fix would NOT make this file compile; Counter
still aborts the whole module.

Also probed whether either gap got cheaper:

- **`reversed()`**: `_mapping`'s inferred field type in all three view
  structs is scalar (`'int'`), so the sibling `__iter__` methods
  already compile as zero-iteration scalar-stubs per this emitter's
  established convention; a new `reversed(<expr>)` case for THIS file
  would lower to the same zero-iteration stubs — no runtime-behavior
  gain, and the file still refuses on Counter afterward. A "real"
  reversed-over-MojoDict lowering exists as a template (the
  coroutine-body `sorted()` case already composes
  `mojo_reversed(mojo_dict_sorted_keys(...))`), but no file in this
  session's doc group reaches it, and the general delegation-receiver
  generalization remains the flagged high-risk shape. Not attempted.
- **Counter**: still `{values: int, items: int, get: int}` — its three
  inherited-dict method names STILL land as int FIELDS from the
  self-attr scan, with zero method signatures and NO backing MojoDict
  field (unlike OrderedDict, whose own `__init__`'s literal
  `self.__map = {}` gives it a real one). Real support needs builtin-
  dict-subclass storage synthesis + inherited container-method
  dispatch + `__missing__` — feature-sized, unchanged since the
  2026-08-23 analysis. Not attempted.

Doc stays open on both blockers.

## Status (re-verified 2026-08-26, wtRest19b — same `reversed()` blocker; investigated feasibility, confirmed feature-sized)

Fresh `MOJO_DEBUG=1` build against current tree: byte-identical to the
prior 2026-08-26 entry below — same 3 refusals (`_OrderedDictKeysView`/
`_OrderedDictItemsView`/`_OrderedDictValuesView`'s `__reversed__`, all
on `reversed(self._mapping)`), Counter's dict-subclass gap still masked
behind it, unreached.

Investigated whether `reversed(x)` -> `x.__reversed__()` delegation
(where `x` is `self._mapping`, an `OrderedDict`, whose own
`__reversed__` is itself a compiled generator over its internal linked
list) is a tractable narrow fix, per this round's instruction to check.
It is not: the existing sub-generator delegation machinery
(`_cpp_for_generator_delegate`/`_cpp_iterable_is_delegatable_generator_
call` in gimple_cpp_async.py/gimple_cpp_core.py) only recognizes a bare
`name(...)` free-function generator call or a literal `self.method(...)`
call — its own docstring states this explicitly: "a generator method
can only ever be consumed via `self.<method>()` in this scalar body
model, never through an arbitrary struct-typed local". Supporting
`reversed(<arbitrary expr>)` would need: (1) recognizing the `reversed`
builtin as a dunder-dispatch rewrite to `<expr>.__reversed__()`, (2)
generalizing the delegation receiver from the hardcoded `self` literal
to an arbitrary evaluated expression (with its own type resolved to
find the right struct's `_generator_method_api` entry), and (3) for
the tuple-target/`for key in reversed(...)` for-statement shape
specifically, wiring that same generalized receiver through
`_cpp_iterable_is_delegatable_generator_call`'s CallExpr-shape checks
too. This is real extension work on the same call-argument/lowering
machinery this project's history already flags as high-risk for
narrow-looking edits (the "_tuplegetter incidents") — feature-sized,
not attempted. No code change.

## Status (updated 2026-08-26, worktree fix/rest-remainder17 — re-verified; a DIFFERENT, EARLIER blocker now surfaces first, Counter's dict-subclass gap not re-reached this pass)

Fresh full `python3 mojo.py build .../Lib/collections/__init__.py` against
this worktree (branched from master `1e0f3f2`, `build/libmojostdlib.dylib`
freshly rebuilt, 0 skips). The build now fails EARLIER than the Counter
subscript-store refusal this doc has tracked since 2026-08-23: three
`__reversed__` generator methods (`OrderedDict.__reversed__` and 2
others) are refused up front — `a call to unresolved callee
'reversed(...)' is not supported in a compiled generator/coroutine
body`. This is a genuinely different, NEW-to-this-doc gap: `reversed()`
isn't in this coroutine-body emitter's builtin-call allowlist at all
(distinct from `sorted()`, which is supported). Per this session's
explicit instruction for this doc, **NOT attempted** — the assignment
was to re-verify the dict-subclass/`Counter[...]=...` mechanism
honestly, not to fix new gaps found along the way; adding `reversed()`
support is its own separate, non-trivial scope (would need to decide a
representation — reverse-iterate the same accessor the forward-iteration
codegen uses — and isn't guaranteed to even reach Counter's issue next).

The previously-documented Counter/`Counter[...] = ...` dict-subclass
gap (issue **explicitly out of scope for this pass** per this session's
own instructions — "do NOT attempt a fix for this specific mechanism")
was not re-reached this pass because the `reversed()` refusal now fires
first and aborts the whole module before Counter's own body is ever
reached. Its status is therefore unverified this pass (may or may not
still reproduce verbatim once `reversed()` is dealt with) — the doc's
2026-08-23 diagnosis of that mechanism (no backing MojoDict storage,
methods misregistered as int fields, no `__getitem__`/`__setitem__`) is
architecturally unchanged (nothing landed touches dict-subclass storage
representation), so there is no reason to believe it's actually
resolved — just that it's currently masked. Doc stays open, status
updated honestly; do not `git rm`.

Quality gate (no compiler-source change made for this doc): unaffected
by this session's OTHER changes (`gimple_cpp_core.py`'s dynamic
exception-value re-raise + MemberExpr-receiver container-method fixes,
see `CODEGEN_generator_function_Lib_test_test_finalization.md`) —
`test_gimple.py` 256/256, `test_module_cache.py` 76/76 both still pass
after those changes.

## Status (updated 2026-08-23, wt09 fix/stdlib-mods `945af88` — UserDict error FIXED; Counter blocked by builtin-dict subclassing, now refused honestly)

Two of the three 2026-08-06 issues below are gone (other agents'
sessions), and this pass fixed/clarified the remainder:

- Issue #1 (`_tuplegetter` redefinition) and issue #2 (the three
  dynamic-attribute instances) no longer reproduce — the build gets well
  past them.

- **Issue #3's `Counter` errors at lines 944/957 (`__iadd__`/`__isub__`,
  `self[elem] += count`) are now precisely understood and honestly
  refused instead of miscompiled.** Root cause chain: `class
  Counter(dict)` subclasses a BUILTIN type — the compiled `struct
  Counter` is `{int64 __mojo_type_id; int values; int items; int get;}`
  (its METHODS `values`/`items`/`get` even got misregistered as int
  FIELDS by the self-attr scan): there is NO backing MojoDict storage at
  all, `Counter.__init__` never allocates one, and Counter registers
  neither `__getitem__` nor `__setitem__`. So `self[elem] += count` has
  no correct compiled lowering whatsoever — the read degraded to an
  opaque `(int64_t)self` handle (struct-subscript fallback,
  gimple_gen_calls.py) and the write emitted raw C `self[elem] = ...`
  against a non-array struct pointer. Real dict-subclass support
  (backing store allocation in `__init__`, inherited container-protocol
  dispatch) is the feature-sized gap this doc already flagged in 2026-
  08-06's issue #3; NOT implemented here.

  What DID change this pass (commit `1f26bb1` + `945af88`): subscript
  read/write on user structs that DO define `__getitem__`/`__setitem__`
  now dispatches to those real methods (fixing the third error class —
  see next bullet), and subscript stores on user structs with NEITHER a
  registered dunder NOR a `_data` backing field now raise the codegen's
  established honest module-refusal ("cannot compile module:
  `Counter[...] = ...` subscript store on user-defined struct 'Counter'
  ... falling back to interpreting this module from source") instead of
  silently dropping the store or emitting invalid C. The whole-program
  build still fails as a unit (exit 1), but with a precise diagnosis
  naming the exact unsupported construct.

- **The 2026-08-10 blocker (`UserDict.get`'s `return self[key]`, GCC
  "invalid types in nop conversion") is FIXED** by the same `__getitem__`
  dispatch: `obj[key]` on a user struct whose class registers the dunder
  now calls the struct's own compiled `UserDict___getitem__` instead of
  treating the instance as an array container (`UserDict.data` was being
  indexed as an array of MojoDict headers — wrong semantics AND a hard
  `-fgimple` error at any struct-valued element). Write side
  (`obj[key] = v` → `__setitem__`) handled symmetrically, including the
  augmented-assignment shape. Verified value-correct via an isolated
  compile-and-run repro with typed params.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; a separate, pre-existing gap now blocks)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). Confirmed via an isolated compile: `_OrderedDictItemsView.
__reversed__`'s `yield (key, self._mapping[key])` is no longer refused
— its own tuple-boxing text is syntactically valid C++, correctly
boxing `key` as int64_t and the dict-subscript value as `char *`
(inferred via `_infer_simple_expr_ctype`'s `SubscriptExpr` case).

**This file still does not build**, blocked by an INDEPENDENT,
pre-existing gap one statement earlier in the SAME method:
`for key in reversed(self._mapping):` — `reversed(...)` has no lowering
in the coroutine-body expression emitter — g++: "'reversed' was not
declared in this scope". Unrelated to tuple-yield. Since this blocker
occurs before the file reaches C compilation of its non-generator code
at all, the three issues documented in the 2026-08-06 section below
(`_tuplegetter` redefinition, dynamic-attribute gaps, `Counter`
incompatible-types) remain unconfirmed either way — not re-checked here
(same caveat the 2026-08-07/09 statuses already carried). Not attempted
here. Doc kept open (not deleted).

## Status (re-verified 2026-08-09 against master `d3d4c68`)

Still reproduces, still stops at the same earlier blocker as the
2026-08-07 update below, and `MOJO_DEBUG=1` now pins the exact cause
down precisely (this wasn't captured before):

```
[gimple_codegen] generator method _OrderedDictItemsView.'__reversed__'
  not eligible for C++ coroutine path, falling back to honest refusal:
  __reversed__: every `yield` must carry a value, and all values must
  agree on one scalar type (int64_t/double/_Bool)
```

The actual source (`_OrderedDictItemsView.__reversed__`,
`collections/__init__.py:76-78`):

```python
def __reversed__(self):
    for key in reversed(self._mapping):
        yield (key, self._mapping[key])
```

This is a plain instance of the already-documented, already-structural
**tuple-valued `yield` in a generator** gap (the current coroutine
promise design only supports a single scalar `int64_t`/`double`/`_Bool`
yield type; `_infer_generator_yield_ctype` deliberately returns `None`
for a `TupleExpr` yield value). Not narrow, not attempted here — same
class of gap as `bugs/COMPILE_FAIL_asyncio_futures.md`'s
value-carrying-`return` refusal (both are "the coroutine promise type
can't represent this value shape" gaps in the same shared machinery).
`_OrderedDictKeysView.__reversed__` (`yield from reversed(...)`) and
`_OrderedDictValuesView.__reversed__` (`yield self._mapping[key]`,
single scalar-ish value) are NOT the blocker — only the tuple-yielding
`_OrderedDictItemsView.__reversed__` is.

Because this blocker occurs before all three issues in the
2026-08-06 section below are reached, whether those are still live
remains unconfirmed (same caveat as the 2026-08-07 update — not
re-checked, would require fixing or patching around this generator
limitation first, out of scope for a structural gap).

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
