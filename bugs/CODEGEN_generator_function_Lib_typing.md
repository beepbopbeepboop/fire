# CODEGEN_generator_function: Lib/typing.py

## Status (updated 2026-08-25, worktree fix/opencode-group2 — the 08-24 "isolated clean" claim was stale; 2 real .cpp-emitter bugs found + FIXED; typing's own generator now honestly refused on a genuinely-unrepresentable shape)

Re-ran the isolated coroutine-path compile fresh:
**6 g++ errors**, NOT clean — confirmed identical at this session's
pre-session commit (`4220964`, separate `git worktree add`), so the
2026-08-24 entry's "still succeeds cleanly" was stale. Root-caused
into two real .cpp-emitter bugs, BOTH FIXED in shared source
(commit `34f9b94`):

1. **The .cpp preamble's module-globals mirror copied global C types
   verbatim, including user-struct pointers whose typedefs no
   generator body reaches** (`_DeprecatedGenericAlias * ByteString`,
   `_CallableType * Callable`, `_TupleType * Tuple`,
   `_LazyAnnotationLib * _lazy_annotationlib`, `_Sentinel * _sentinel`
   → "'X' does not name a type" ×5 — the typedef BFS only pulled
   structs generator bodies actually touch). Fix: the mirror now emits
   forward decls + full typedefs for every struct its fields name
   (transitive-field BFS, deduped against already-emitted ones),
   falling back to layout-identical int64_t boxing when no resolved
   layout exists.
2. **`yield Unpack[self]` (`_BaseGenericAlias.__iter__`) lowered to
   garbage**: `Unpack` is an `@_SpecialForm`-decorated def IN THIS
   MODULE, but the SubscriptExpr string-slice fallback emitted
   `mojo_cstr_slice((char *)(_root_globals.Unpack), self, self+1)` —
   against a name that isn't even a member of the emitted globals
   struct ("has no member named 'Unpack'"), and semantically nonsense
   (slicing a function value's bytes) had it linked. Fix: subscripting
   a bare identifier that names a real function now refuses honestly.

Net state change for typing.py itself: the compiled path now refuses
at the ELIGIBILITY gate (`__iter__`: "subscript base resolves to a
function/special-form value") instead of emitting a broken .cpp unit —
the project's standard honest-refusal convention, strictly safer.
Closing the refusal for real needs runtime dynamic dispatch on
special-form/callable objects (`Unpack[self]` constructs an
`_UnpackGenericAlias` through `_SpecialForm.__getitem__`) — same
dynamic-receiver family as pickletools' `getpos`; feature-sized, not
attempted. Full gate for both fixes: test_gimple.py 256/256,
test_module_cache.py 76/76, generator runner 53/53, check-selfhost
clean, from-scratch stdlib dylib rebuild EXIT=0 / 0 skips. Doc stays
open.


## Status (updated 2026-08-24, worktree fix/gen-core — re-verified, isolated coroutine-path compile still clean)

Re-ran the isolated coroutine-path compile fresh, post-`fd909e9`
("refuse unresolved callees honestly") and post-this-session's own
`6e92df8` (class-body dunder-alias methods — applies here: `typing.py`
defines `__call__ = _idfunc` and `__instancecheck__ =
__subclasscheck__` via the single-target form of the idiom, now
correctly registered as real methods instead of silently becoming bogus
data fields; no error-shape change observed, since neither alias was
previously implicated in the 4 documented residuals). `compile_to_
gimple_with_cpp(do_imports=False)` on typing.py still succeeds cleanly
— unlike `pickletools.py`/`weakref.py`/`tokenize.py` in this cluster,
typing.py's own generator sites were never relying on the
now-corrected silent-miscompile behavior `fd909e9` fixed. The 4 raw
own-code error lines from a real whole-program build remain exactly as
documented below (all already-tracked deferred families). Doc stays
open.

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — re-verified; 4 own residuals, all in already-documented deferred families)

Re-verified against current HEAD via a real `python3 mojo.py build
.../Lib/typing.py`. typing.py's own generator sites still compile
cleanly (no refusals). Remaining own-code errors (4 raw lines), each
confirmed to belong to an already-tracked deferred family rather than a
new mechanism:

- `1348/1353 '_CallableGenericAlias' has no member named
  '__parameters__'/'__module__'` — the 2026-08-20 qualifier-priority fix
  below resolved the redefinition errors, but the bare-name struct
  collision itself remains: whichever same-named struct definition wins
  the whole-program TU lacks the subclass's fields. Same deferred family
  as `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`.
- `3357 '_TypedDictMeta' has no member named '__orig_bases__'` — dynamic
  attribute set on a call RESULT (`td.__orig_bases__ = (TypedDict,)`),
  the `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md` family.
- `430 assignment to '_Sentinel *' from 'int64_t'` on `_sentinel =
  _Sentinel()` — the global's field is declared `_Sentinel *` but the
  Phase 1.7 semantic conclusion for a zero-arg constructor call falls to
  int64_t; isolated repros of global = StructCall compile and run fine,
  so this is specific to `_Sentinel`'s registration ordering inside
  typing.py's own large module — left for a dedicated pass.

Doc stays open (transitive contextlib cascade + above).

## Status (updated 2026-08-20): `_CallableGenericAlias` redefinition FIXED, file still fails on unrelated errors

The `redefinition of '_collections_abc__CallableGenericAlias___repr__'`/
`___reduce__` pair noted below (and the related `conflicting types for
'..___getitem__'`/`'_CallableGenericAlias' has no member named
'__parameters__'/'__module__'`) is now fixed — same root cause and same
fix as `bugs/CODEGEN_generator_function_Lib_mailbox.md`'s 2026-08-20
entry: `_struct_method_qualifier` (gimple_codegen.py ~line 25808) wrongly
preferred the shared, whole-program `_imported_struct_home` registry
over a struct's own genuine local declaration. `Lib/typing.py` defines
its own `class _CallableGenericAlias(_NotIterable, _GenericAlias,
_root=True):` (line 1615), bare-name-identical to `Lib/_collections_
abc.py`'s completely unrelated `class _CallableGenericAlias
(GenericAlias):` — the exact same bare-name-collision shape as
mailbox.py's `Message`, just an accidental same-name collision rather
than a real subclass relationship. Fixed by the same qualifier-priority
reorder (see that doc / the code comment at the fix site for full
detail).

Verified via a fresh `python3 mojo.py build /Users/mrs/net/Python-3.14.6/
Lib/typing.py`: the `_collections_abc__CallableGenericAlias` redefinition
errors are gone (was present). **typing.py still does not build** — 223
errors remain, dominated by the already-tracked, separate `Lib/
contextlib.py` cascade (`bugs/COMPILE_FAIL_Lib_contextlib_request_for_
member_module_in_something_not_a_structure_or_union.md`) and other
unrelated issues; none struct-collision-shaped. Doc kept open.

## Status (re-verified 2026-08-09)

Fresh from-scratch `python3 mojo.py build /Users/mrs/net/Python-3.14.6/
Lib/typing.py` on current master. Classification unchanged: **NOT a
generator-codegen-cluster failure** — typing.py's own 4 generator sites
(lines 1533, 3129, 3132, 3135, all bare `yield <name>` inside
`__iter__`-style methods) produce zero errors and no "not eligible"
refusal.

Two more previously-open patterns from this doc are now confirmed GONE:
- The `module_toplev_struct_never_fully_defined` cluster (`struct
  _tokenize_toplev`/`struct _inspect_toplev`, 9th occurrence as of
  2026-08-06): 0 occurrences in the current build output.
- The `stray '\' in program` textwrap.py tokenizer bug (7th occurrence
  as of 2026-08-06): 0 occurrences in the current build output.

The dominant pattern in the current build (412 of 650 total `error:`
lines) is now `Lib/contextlib.py` — a large cascade, not investigated
here, consistent with the already-tracked, separate
`bugs/COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_
something_not_a_structure_or_union.md` non-scalar-`__aenter__`-return
structural gap. typing.py's own remaining errors (20 lines, all
non-generator) are: `non-register as LHS of unary operation` (171),
`redefinition of 'traceback__Sentinel___repr__'` (424), `assignment to
'_Sentinel *' from 'int64_t'` (430), `passing argument 1 of
'_is_dunder_79c856' makes integer from pointer without a cast` (1300),
`'_CallableGenericAlias' has no member named '__parameters__'`/
`'__module__'` (1348/1353), `conflicting types for
'_collections_abc__CallableGenericAlias___getitem__'` (1371),
`redefinition of '_collections_abc__CallableGenericAlias___repr__'`/
`___reduce__` (1536/1624), and `'_TypedDictMeta' has no member named
'__orig_bases__'` (3357, unchanged from 2026-08-07). None of these
implicate typing.py's own generators — still out of scope for this
generator-codegen cluster; no code change made here.

## Status (updated 2026-08-07)

Two of this doc's previously-open patterns are now FIXED — see
`bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
mismatches.md` for the full writeup:
- The "comprehension/`_quick_type`-family 'non-trivial conversion'
  pattern (lines 1275/1491)" mentioned below was actually
  `_isinstance_one_type`'s `isinstance(x, type)`-always-False stub
  emitting a bare `0` into a `_Bool`-declared temp (`_new_val`'s digit-
  literal auto-cast guard only covered `int64_t`, not `_Bool` — that
  doc's Mechanism 2). Fixed.
- The "`passing argument 1 of '..._dir__' from incompatible pointer
  type`" pattern was `super().method(...)` calls passing `self` typed
  as the DERIVED struct pointer to a BASE class method expecting the
  base struct pointer, with no actual C-level cast ever emitted (that
  doc's Mechanism 3). Fixed — an isolated `typing.py`-only compile went
  from 14 errors (with only Mechanism 2 fixed) to 2 once this landed
  too.
- Still open, untouched: the `module_toplev_struct_never_fully_defined`
  cluster (per that doc's own status — check there for current state),
  the textwrap.py tokenizer bug, `'_TypedDictMeta' has no member named
  '__orig_bases__'`, and one `non-register as LHS of unary operation`
  error (global-struct-field assignment) — none investigated further.

## Status (updated 2026-08-06, PARTIALLY STALE — see above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-31 `_DeprecatedGenericAlias`/`_CallableType`/`_PlaceholderType`
errors no longer reproduce. `typing.py`'s own 4 generator sites (lines
1533, 3129, 3132, 3135) do not appear anywhere in the current (~100+
error) output and have no "not eligible" refusal — they appear to
compile cleanly.

**Classification: NOT a generator-codegen-cluster failure anymore.**
By far the dominant pattern (60+ occurrences) is the already-cross-
referenced `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md` (9th confirmed occurrence — `struct _tokenize_toplev`,
`struct _inspect_toplev` — this file has the largest RAW occurrence
count of that pattern seen in this cluster). Also present: the recurring
`stray '\' in program` textwrap.py tokenizer bug (7th occurrence), the
comprehension/`_quick_type`-family "non-trivial conversion" pattern
(lines 1275/1491), and several unrelated-looking errors (`'_TypedDictMeta'
has no member named '__orig_bases__'`, `redefinition of
'_collections_abc__CallableGenericAlias___repr__'`, `passing argument 1
of '..._dir__' from incompatible pointer type` — the same property/
bound-method-access family noted in `ipaddress.py`'s re-diagnosis).

None of this implicates typing.py's own generators. Not investigated
further — out of scope for this generator-codegen cluster.

## Build error

```
error: '_DeprecatedGenericAlias' does not name a type
error: '_CallableType' does not name a type
error: '_PlaceholderType' does not name a type
```

## Fixed errors (this session)
- `Unpack` not declared → fixed (package import scan)

Source file: `/Users/mrs/net/Python-3.14.6/Lib/typing.py`
