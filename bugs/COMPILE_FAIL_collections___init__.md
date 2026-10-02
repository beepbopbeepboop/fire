# COMPILE_FAIL: Lib/collections/__init__.py

## Status (2026-09-30, branch work/compile-fail-stdlib-misc — down to TWO own-file errors, and neither is one of the clusters below)

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py`
(17 s, peak 0.1 GB, exit 1). **9 `error:` lines total, 2 of them in
`collections/__init__.py`:**

```
collections/__init__.py:515:11: error: too many arguments to function 'mojo_type'; expected 1, have 3
collections/__init__.py:1192:33: error: passing argument 2 of 'mojo_dict_union' makes pointer from integer without a cast [-Wint-conversion]
```

- **515** is `namedtuple`'s `result = type(typename, (tuple,), class_namespace)`
  — the 3-argument `type()` form, which this codegen lowers to a 1-arg
  `mojo_type`. A real feature gap (dynamic class construction), not narrow.
- **1192** is `UserDict.__ior__`'s `self.data |= other`, i.e. `|=` on a dict
  with a second operand whose type is not statically a `MojoDict *`.
  `mojo_dict_union`'s own dict-`|`-dict branch in
  `_lower_binary_tail` handles the typed case; the untyped-`other` case is
  the "cannot coerce" refusal surface one level down.

The other 7 errors are `Lib/keyword.py` ×4 (a `MojoList` passed where a
pointer is expected — `makes pointer from integer without a cast`) and
`Lib/reprlib.py` ×3 (`char *` assigned into an `int64_t` local, plus the
two `conflicting types` for `operator_eq_2dbb98` /
`reprlib_recursive_repr_d719e0`).

**Everything the historical entries below track as this file's blocker is
gone.** The tuple-valued-`yield` / `reversed(...)` cluster, the
`_tuplegetter` redefinition, the `OrderedDict.__new__` / `__func__` /
`__doc__` dynamic-attribute instances, and the `Counter`
incompatible-types class all no longer appear at all — none of the
generator `cannot compile module` refusals in those entries is raised.
Two further module-level soft fallbacks appear in the closure
(`_collections_abc`'s `generator .close()` and `typing`'s
`MojoDict *`→`MojoList *` coercion), both of which other docs own.

Doc kept open on the two errors above.

## Status (2026-09-06 — Stage-4 optional tail LANDED: `.get()/.keys()/.values()/.items()/.update()/.pop()/.setdefault()/.clear()` + `for k in d` delegation on a dict-subclass instance)

Inherited container METHODS on a builtin-`dict`-subclass instance now
delegate to the hidden `_data` backing store, exactly like `d[k]` /
`k in d` / `len(d)` already did:

- `gimple_gen_methods.py` `_lower_method_call` — a new delegation block
  (right after the generator-method check, before every generic
  fallback) routes `.get / .keys / .values / .items / .update / .pop /
  .setdefault / .clear` on a `_dict_subclass_of(ot)` receiver to
  `_lower_dict_method(inst->_data, ...)`, UNLESS the struct or a local
  base up its MRO defines its own override (`_dict_subclass_defines`,
  new helper in `gimple_gen_calls.py`, walks `_struct_bases`). `update`
  also unwraps a dict-subclass ARGUMENT to its `_data`.
- `gimple_gen_loops.py` — `for k in <dict-subclass instance>` (no
  `__iter__`/`__next__`/`__has_next__` override) iterates
  `it_val->_data` via `_gen_for_dict`. `for k, v in d.items()` already
  worked once `.items()` returns the real `mojo_dict_items` list.
- `gimple_module_gen.py` `_scan_body_for_local_field_access` — no longer
  mints phantom `int` fields named `get`/`keys`/`values`/`items`/… on a
  dict-subclass struct from `d.get(...)` call sites (they were being
  lowered as function-pointer field calls → `mojo_obj_call1` stub).

Collections isolated probe (`compile_to_gimple(do_imports=False)` on
`/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py`): still
compiles, still clean under `gcc-mp-15 -fgimple -fsyntax-only`. The
generic dynamic-dispatch fallback (`mojo_obj_call1`) in the generated C
dropped **16 → 2**; `mojo_dict_items` 9 → 19, `mojo_dict_values` 0 → 1,
`->_data` 48 → 56 — i.e. substantially more of Counter/OrderedDict's
inherited container operations now lower to real dict ops.

Full gate green: check-linkmode 3/3, check-selfhost, stdlib dylib
from-scratch **0 skips**, `compile_stdlib.py` **664/664, 0 unexpected**,
`make bootstrap` all 180 files byte-identical across 3 stages.
test_gimple.py 278/0, test_gimple_runner.py 24/0, test_module_cache.py
76/0, test_gimple_generator_runner.py 80/4 (4 pre-existing, unrelated).

Still open: the whole-program `fire.py build` PERF barrier below.

## Status (2026-09-06 — whole-program `fire.py build` of a dependent (asyncio/queues.py) is now PERF-bound, not codegen-bound)

`isolated` `compile_to_gimple` of `collections/__init__.py`, `asyncio/
queues.py` and `asyncio/futures.py` all succeed (blocker 1 fixed, below).
A whole-program `python3 fire.py build Lib/asyncio/queues.py` — which
compiles the full asyncio + collections + inspect + _collections_abc
transitive closure from scratch — was observed running >34 min at 100%
CPU / 1.7 GB without completing: this is the separately-tracked
`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
quadratic `_walk_ast` re-scan on a large import graph, NOT a codegen
refusal. The codegen side of the asyncio/collections chain is done; the
remaining barrier to an end-to-end binary is compile-time perf.

## Status (2026-09-05 — BLOCKER 1 (builtin `dict` subclassing) FIXED; `Lib/collections/__init__.py` now compiles isolated, clean under `gcc -fgimple -fsyntax-only`)

Real builtin-`dict`-subclass support landed as a feature, in stages
(session `session_017xcwMuCdoVEHt8VFT4ihHm`):

- **Stage 1 — representation + storage synthesis.** `gen_module_impl`
  now computes `self._dict_subclass_structs`: every user struct whose
  transitive base list bottoms out at builtin `dict` (directly, or via
  another local dict-subclass, or via `OrderedDict`/`Counter`/
  `defaultdict`). Each gets a synthesized hidden `_data: MojoDict *`
  field, and `_alloc_<Struct>` allocates it (`_p->_data =
  mojo_dict_new()`), exactly like the `__mojo_type_id` header. The
  self-attr scan no longer needs a workaround — recent code already
  stopped misregistering inherited method names (`values`/`items`/
  `get`) as int fields.
- **Stage 2 — inherited container ops route to the backing dict.**
  `d[k]` / `d[k] = v` / `d[k] += n` (read, write, aug-assign),
  `k in d` / `k not in d`, and `len(d)` on an instance of a known
  dict-subclass with no corresponding dunder override now lower to
  `mojo_dict_get_int` / `mojo_dict_set_{int,str}` / `mojo_dict_contains`
  / `mojo_dict_len` against `inst->_data`. `_struct_data_field` was
  taught to exclude dict-subclass structs so the old Span/List
  `_mojo_at_` pointer-arithmetic path can't hijack the new `_data`.
- **Stage 3 — `__missing__` on subscript-read miss.** `d[k]` for a
  dict-subclass whose class defines `__missing__` compiles to
  `mojo_dict_contains(...) ? mojo_dict_get_int(...) :
  <Struct>___missing__(inst, k)` (proper basic-block form), matching
  CPython's `type(d).__missing__(d, k)`. This is what lets `Counter`'s
  `self[elem] += count` start from 0.
- **Stage 4 — override precedence.** A subclass that defines its own
  `__getitem__` / `__setitem__` / `__contains__` / `__len__` still wins
  (the existing `_lower_struct_subscript_dunder` dispatch runs first for
  get/set; the `in`/`len` paths check `_struct_defines_method`).

Isolated probe: `compile_to_gimple(open('Lib/collections/__init__.py'))`
now succeeds (was: `RuntimeError: cannot compile module: \`Counter[...]
= ...\` subscript store ...`), and the generated C passes `gcc -fgimple
-fsyntax-only` with only one benign `-Wint-to-pointer-cast` warning in
`OrderedDict___reduce__`. The `reversed(self._mapping)` generator
refusal the older entries below tracked as "blocker 2" no longer
reproduces on this path (the three `__reversed__` generators are
skipped as un-compilable rather than aborting the module).

Dependent re-probe (isolated `compile_to_gimple`):
- `Lib/asyncio/queues.py`, `Lib/asyncio/futures.py` — now compile
  clean (were blocked here via the `collections` import).
- `Lib/zipfile/__init__.py`, `Lib/importlib/metadata/__init__.py` —
  blocker 1 cleared; they now hit a *different*, unrelated wall (plain
  generator functions `split` / `read` / `_convert_egg_info_reqs_to_
  simple_reqs` in the straight-line codegen), tracked by the generator-
  codegen docs, not this one.

Regression tests: `test_gimple.py` (`dict_subclass_backing_store_and_
subscript`, `dict_subclass_missing_dunder_on_read_miss`, `dict_subclass_
transitive_and_getitem_override_wins`) and `test_gimple_runner.py`
(`gimple_dict_subclass_counter_shape`, a real build-and-run checking
`b[k] += n` from 0 via `__missing__`, `in`, `not in`, `len`).

Not yet done: `.get()` / `.keys()` / `.items()` / `.values()` /
iteration delegation to the backing dict (Stage 4's optional tail) —
`collections/__init__.py` compiles without it because `OrderedDict`
defines its own and `Counter` inherits `dict`'s at the interpreter
level; add it when a compiled program actually calls e.g.
`counter.values()`. Doc kept open pending a whole-program (`fire.py
build`) confirmation and that delegation tail; `git rm` once both land.

---

## Status (re-verified 2026-08-26, this session, master fast-forwarded to `9c0e7a8` — tried hard for a narrow fix per explicit task framing, none found; unchanged, both blockers confirmed genuinely structural)

This pass was specifically asked to try hard for a narrow fix here,
since a fix might have outsized value for other docs blocked on the
same Counter/OrderedDict dict-subclass gap. Fresh isolated
`compile_to_gimple_with_cpp` probe confirms the SAME first blocker as
every prior session: the three `__reversed__` generator methods refuse
on unresolved callee `reversed(...)`.

Traced `self._mapping` (the `reversed(self._mapping)` receiver in
`_OrderedDictItemsView`/`_OrderedDictValuesView`, and `_OrderedDictKeysView.
__reversed__`'s `yield from reversed(self._mapping)`) to its actual
origin: `_mapping` is never assigned anywhere in THIS file at all — it's
set by `_collections_abc.MappingView.__init__(self, mapping): self.
_mapping = mapping` (`Lib/_collections_abc.py:835`), a DIFFERENT module,
inherited by `_OrderedDictKeysView(_collections_abc.KeysView)` etc. The
`mapping` parameter has no annotation, so this codegen's cross-module
self-attr field-type scan boxes it as the generic `int64_t` default —
this is why `_mapping`'s inferred field type is scalar `'int'`, not a
real `OrderedDict *`/`MojoDict *`: it isn't a same-module unannotated-
param quirk, it's a genuinely CROSS-MODULE inherited-`__init__` field
whose type evidence lives in a different file's AST entirely.

This means even a full, general `reversed(<arbitrary-typed local>)` ->
`<expr>.__reversed__()` delegation implementation (the mechanism
wtRest19b's 2026-08-26 entry below already scoped out as 3 sub-steps of
real work) would NOT fix this file: `self._mapping` would still resolve
to a scalar `int64_t`, with no real `OrderedDict` struct pointer behind
it to delegate onto in the first place. The actual blocking gap is one
level deeper than `reversed()` itself — it's cross-module inherited-
field type propagation for a base class's own `__init__`-assigned
`self.<field>` (a distinct, unexplored gap from anything previously
attributed to this doc's "reversed() lowering" framing). Fixing THAT
generically (making the self-attr scan follow inheritance across module
boundaries to find `_mapping`'s real assigned type) is itself broad,
cross-cutting type-inference machinery — squarely the class of change
this project's history already flags as high-regression-risk when
attempted narrowly (the `_tuplegetter` incidents), and per this task's
own explicit instruction NOT to force a risky broad change to shared
subscript/type-inference machinery for this doc. Not attempted.

Confirmed (via `git stash`-style A/B, matching prior sessions'
methodology) that Counter's `Counter[...] = ...` dict-subclass
subscript-store gap remains completely unaffected by anything landed
this session (`filter()` coroutine-body support — see
COMPILE_FAIL_importlib_metadata___init__.md — is unrelated to dict-
subclass storage). Its status is unchanged from the 2026-08-23 root-
cause writeup below (no backing MojoDict field, its own method names
misregistered as int fields by the self-attr scan, no `__getitem__`/
`__setitem__`) — real support needs builtin-dict-subclass storage
synthesis + inherited container-method dispatch + `__missing__`, still
feature-sized. Doc stays open on both blockers; no code change for this
file specifically.

Source file: `/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py`

## Status (re-verified 2026-08-26, worktree agent-ae936147a68675d97 — independently re-derived from scratch; both stacked blockers confirmed, no narrow fix found)

Per this round's explicit instruction, tried hard to find a real narrow
fix here given this doc's outsized value (the Counter/OrderedDict
dict-subclass subscript-store gap blocks several other bugs
project-wide). Fresh isolated `compile_to_gimple_with_cpp(do_imports=
False)` probe: byte-identical to every prior entry — three
`__reversed__` generator methods refuse first on `reversed(self.
_mapping)`: "a call to unresolved callee 'reversed(...)' is not
supported in a compiled generator/coroutine body". Confirmed directly
in `gimple_cpp_core.py` (~line 5325-5345): the coroutine-body emitter
only special-cases `reversed(range(...))`/`reversed(range(start,
stop))` inside a `for` statement's iterable position — there is no
general `reversed(<expr>)`-as-callee case, and no dunder-dispatch
rewrite to `<expr>.__reversed__()`. Building that (recognizing the
builtin, generalizing the sub-generator delegation receiver beyond the
hardcoded `self` literal, and threading it through the for-loop
delegate-detection path too) is real subsystem work, not a one-line
whitelist add — matches every prior session's conclusion.

Did not stop there: experimentally neutralizing the three
`__reversed__` bodies (to look one layer deeper, as the doc's own
established methodology does) still surfaces the Counter dict-subclass
`Counter[...] = ...` subscript-store refusal next — `class Counter
(dict)` has no backing MojoDict field (`Counter.__init__` never
allocates one) and its `values`/`items`/`get` methods get misregistered
as int fields by the self-attr scan, so `self[elem] += count` has no
correct lowering. Fixing this specific instance narrowly (special-
casing `Counter` by name) would be exactly the kind of parallel-
implementation hack CLAUDE.md's Code Quality rule forbids; the honest
fix is general builtin-dict-subclass storage synthesis (constructor
backing-store allocation + inherited container-method dispatch +
`__missing__`), which is the same feature-sized gap this doc has
tracked since 2026-08-23. No narrow fix found for either blocker. No
code change; doc stays open.

## Status (re-verified 2026-08-26 — checked against this session's new loop-as-expression codegen; UNAFFECTED)

This session implemented real loop-as-expression codegen for `list(x)`/
`set(x)`/comprehension-as-value inside a compiled generator/coroutine
body (see `bugs/CODEGEN_generator_function_Lib_codecs.md`'s entry of the
same date for the implementation writeup). This file's three
`__reversed__` refusals are all `reversed(...)` used as a plain builtin
CALL (producing a value), not a `list()`/`set()`/comprehension shape —
`reversed()` itself still has no codegen anywhere in this emitter except
the narrow `for i in reversed(range(...)):` for-loop-iterable special
case, unaffected by this session's work — so no change was expected.

A/B'd via `git stash`: strict-mode `compile_to_gimple_with_cpp(do_imports
=False)` refusal is byte-identical (`__reversed__` x3, same `reversed
(...)` reason each). The relaxed-mode/direct `gen_module` path (this
doc's own established methodology) hits an unrelated, EARLIER hard
refusal before reaching generator-eligibility at all — `Counter[...] =
...` subscript-store on the `Counter` struct having no `__setitem__`/
backing container field — also byte-identical before/after. Confirmed
unaffected; doc stays open.

## Status (re-verified 2026-08-26, worktree fix/opencode-genlib2 — BOTH stacked blockers confirmed live, from two independent build modes)

Fresh verification from both directions, no compiler change:

1. **As BUILD ROOT** (`python3 fire.py build .../Lib/collections/
   __init__.py`, safety-wrapped; fails in ~5s, no runaway): the module
   refuses up front on the three `__reversed__` generator methods —
   "a call to unresolved callee 'reversed(...)' is not supported in a
   compiled generator/coroutine body" ×3. Byte-consistent with the
   wtRest19b/canalyzer2 entries.
2. **As an IMPORTED dependency** (observed fresh inside a bounded
   `fire.py build` of `Lib/asyncio/queues.py`, which imports this
   module): the nested compile surfaces the DEEPER blocker instead —
   "cannot compile module: \`Counter[...] = ...\` subscript store on
   user-defined struct 'Counter' (no `__setitem__` method and no
   backing container field) ... falling back to interpreting this
   module from source". This independently corroborates canalyzer2's
   probe conclusion (neutralize the three `__reversed__` bodies →
   Counter aborts the module anyway): the imported path evidently
   retries past skipped generators (relaxed handling) and reaches
   Counter's own refusal directly.

Both mechanisms remain exactly as previously assessed: fixing
`reversed()` for this file would only lower to zero-iteration
scalar-stubs (`_mapping` is int-typed via the excluded unannotated-
param family) with zero runtime-behavior gain, and Counter needs
builtin-dict-subclass storage synthesis + inherited container-method
dispatch + `__missing__` — feature-sized. Doc stays open on both.

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

Fresh full `python3 fire.py build .../Lib/collections/__init__.py` against
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
