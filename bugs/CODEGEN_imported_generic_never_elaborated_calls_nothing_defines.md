# An imported generic is never elaborated, so the generated C calls a symbol
# nothing defines

## Status

OPEN, and the headline number in this doc was wrong by 4x. Measured and
corrected 2026-10-01 (second session): `tools/undef_import_census.py` reported
"424 sites / 157 names / 194 files"; it was counting the codegen's own guarded
forward declaration for every imported name, called or not. The real figure is
**96 sites / 51 names / 60 files** (108 before that session's fixes). See "What
was wrong with the measurement" below — it is the most important section here.

**2026-10-03 (round 4): 96 / 51 / 60 is a LOWER BOUND, and the census now
measures the total as 1938 / 851 / 381 — 20x larger. `tools/undef_import_census.py`
has a second section** (see below). It is the same defect, measured the way the
linker sees it.

### Landed 2026-10-03 (3): census section 2 — the total, not a lower bound

`tools/undef_import_census.py` gained `--section 2` (`check_undefined`), which
for every file that COMPILES compiles its generated C with
`gcc -fgimple -D__MOJO_STDLIB_MODE__ -c`, reads `nm -u`, and subtracts every
symbol the runtime objects, `build/libmojostdlib.arm64.dylib` and the platform's
own libraries define (the last read out of the SDK's `.tbd` stubs, so libc is
subtracted by DATA rather than by an allowlist). Measured over the same 610-file
sweep:

| | section 1 (existing) | section 2 (new) |
|---|---|---|
| sites | 96 | **1938** |
| distinct names | 51 | **851** |
| files affected | 60 | **381** |

Why section 1 was a lower bound, and it is not a rounding difference.
`check()`'s own comment says a call to a MANGLED symbol
(`copysign_Float64_1`, `size_of_6_target_17_…`) is credited, "on the grounds
that a mangled call names a CAS object the caller links". True for the ones that
have one; false for the ones that do not; and nothing in that tool can tell,
because it never links. The concrete hole, measured:

    $ grep -n size_of_6_target_17_CompilationTarget_4_type_3_Int  build/linkcheck/test_collections_test_list.c
    909:extern int64_t size_of_6_target_17_CompilationTarget_4_type_3_Int (void);
    1816:  _t9 = size_of_6_target_17_CompilationTarget_4_type_3_Int ();      <- a CALL
    $ nm -g --defined-only build/libmojostdlib.arm64.dylib | grep -c size_of_6_target_17_CompilationTarget_4_type_3_Int
    0

`test/collections/test_list.mojo` is a GREEN file. It calls a symbol nothing
defines, and section 1 does not report it — `size_of` is absent from all 51
section-1 names, while `Set` (a generic STRUCT, matched by the bare-name rule)
is present.

Of the 851 names / 1938 sites section 2 finds: **397 names / 500 sites are
length-prefixed mangled symbols** (the `monomorphize.mangle` encoder's own
shape, `_\d+_[A-Za-z]`) — i.e. the elaborated-and-still-unlinkable population
section 1 is structurally blind to; **12 names / 444 sites are test-helper
stubs** (`std.testing`'s `assert_equal`/`assert_true`/… and `test_utils`'
`check_write_to`), which `tools/linkcheck.py` documents as deliberately stubbed
in its link; and **994 sites are residual** — imported non-generic symbols that
nothing defines. Named examples, all confirmed absent from the runtime objects,
the dylib and the SDK: `conforms_to` (22), `type_of` (21), `check_bounds` (8),
`int64_t_unsafe_bitcast` (18), `FormatStruct` (15), `ThinAllocation` (12),
`Span_as_bytes` (9), `Path` (17), `Bench`/`BenchConfig` (25/24).

**`_mojo_abort` (31 sites) is a RUNTIME gap and the smallest item in this
document.** `mojo/middle/types.py:1113`'s `_FORCE_RENAME_RESERVED` contains
`abort`, so every stdlib `abort(...)` lowers to `mojo_abort(...)`; the codegen
emits a guarded declaration for it (`module_gen.py:8299`) and
`runtime/fire_runtime.c` defines NO `mojo_abort`. Not landed here: a
`fire_runtime.c`/`.h` change is compiled into everything and owed a full gate,
which this session was asked to postpone. `mojo_index` (11) is the same shape.

**2026-10-03: `monomorphize.mangle` is injective AND in-TU instantiation landed
— the census did not move (96 / 51 / 60), and one family of three went green.**

### Landed 2026-10-03 (2): in-TU instantiation, 3 of the 22, and what actually blocks the rest

`mojo/backend_gimple/elab_intu.py` (new), one call site in
`mojo/backend_gimple/module_gen.py`, two suppression hooks in
`emit_resolve.py`, and `gen._ambiguous_struct_methods` (published in
`gimple_codegen.py`, filled in `module_gen.py`, read by `emit_loops.py` and
`emit_calls.py`). Full write-up, the per-file `nm -g` evidence, and the
measured boundary of the feature are in
`bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md`'s Status
section. The three points this doc needs:

- **`compile_stdlib.py` 588 / 22 / 0 → 591 / 19 / 0**, with
  `test/iter/test_empty.mojo`, `test/iter/test_once.mojo` and
  `test/itertools/test_repeat.mojo` removed from `EXPECTED_FAILURES`.
- **The census is unchanged and CANNOT be, for this change.** It counts call
  sites in files that COMPILE; these three did not compile before, so there was
  no census row to remove. The census will move only when the remaining 19
  compile, which needs the two things enumerated there: dependent return types
  through `Self.<comptime member>`, and overload selection on a trait bound.
- **The `conflicting types` story is settled, and it is NOT `mangle`.** That
  failure is a definition with real parameter types beside a declaration with
  the elaborator's erased ones, and it comes from the two routes BOTH claiming
  one instantiation. Suppressing the `.o` route for anything the pre-pass
  defines removes the second claim: **zero `conflicting types` across the
  591-file sweep.** The blocker that is actually left is DIFFERENT and was
  previously unmeasured — in-TU turns an erased struct into a REAL one, and
  this codegen's real-struct machinery is incomplete (`[i] = v` on a now-real
  container; an overloaded non-protocol method's call site still holding the
  erased view). 11 files, itemised with the exact gcc message each way, in the
  other doc.

### Landed 2026-10-03 (1): `mangle` is a FUNCTION of the instantiation

`mangle` was `'_'.join(safe_suffix(str(type_args[k])) for k in sorted(type_args))`.
Two independent defects, both measured over the same generated corpus of 1752
`(name, type_args)` pairs (`test_module_cache.py::test_mangle_is_injective`
builds a 4,920-pair one; 1512 of the 1752 collided):

| defect | example | why it is a soundness bug |
|---|---|---|
| **ambiguous segmentation** — the parameter VALUES joined under `_` with no key names and no escaping | `mangle('Box', {'T':'A_B'}) == mangle('Box', {'T':'A','o':'B'}) == 'Box_A_B'` | two genuinely different instantiations, one C symbol: `conflicting types` in one TU, `duplicate symbol` across two |
| **a LOSSY escape** — `safe_suffix` mapped every non-`[A-Za-z0-9]` char to `_`, and `_` itself to `_` | `{'T':'List[Int]'}` == `{'T':'List_Int'}` == `{'T':'A B'}` == `{'T':'A.B'}` == `{'T':'A_B'}`; and `{'T':'_'}` == `{'T':' '}` == `{'T':'.'}` | a collision with ONE parameter needs no segmentation at all, so fixing only the join would have left this half of it |

Note the correction the previous session recorded in its own Status section:
"it keys the mangled name on the sorted bracket-parameter VALUES only, so two
DIFFERENT instantiations whose parameter sets differ only in their NAMES
mangle to the SAME symbol" is **wrong as stated** — `{T: Int64, o: MutOrigin}`
and `{T: MutOrigin, o: Int64}` are the same dict, and
`{T:Int64,o:MutOrigin}` vs `{T:MutOrigin,o:Int64}` as *name/value* pairings are
distinct instantiations that the old code in fact named differently. The
collision is the segmentation and the lossy escape, and the parameter NAME is
now in the key for a different and real reason (two templates may share a base
name and differ only in what they call their parameter — `struct Foo[T]` vs
`struct Foo[U]`, which a value-only key cannot separate).

The encoding: every component is `{len(key)}_{key}_{len(value)}_{value}`,
length-prefixed, so the key/value and component/component boundaries are fixed
by a count rather than by a character a value could contain; `safe_suffix` now
ESCAPES (`_x` + 4 uppercase hex, `_X` + 8 outside the BMP) instead of
collapsing, and escapes `_` too, so no type argument can manufacture a
structural character. Uppercase hex is load-bearing:
`mojo/middle/types.py::demangle_overload` recognises `___<6 lowercase hex>$` as
an overload-hash tail, and the test suite asserts no mangled name contains
`___` at all. Measured: **0 collisions over 19,676 generated instantiations**,
every output a legal C identifier, and all 4,920 suffixes decode back to their
(key, value) pairs.

The same defect was independently present on a second spelling —
`elaborate.Elaborator.elaborate_overload_call` did
`fn_name + '__' + safe_suffix('_'.join(ptypes))`, ambiguous segmentation AND
lossy. It now uses `monomorphize.mangle_signature`, the same encoder keyed by
positional index.

**What this invalidates, enumerated and measured.**

- **Every elaborated instantiation's C symbol changes spelling.** `mangle` is
  used in exactly two places (`monomorphize.monomorphize_source`, which renames
  the definition, and nothing else), so every mangled name appears in generated
  C as a struct typedef, a method symbol `{Struct}_{method}{overload_suffix}`,
  an `extern` declaration, a `func_return_types`/`func_param_types` key, and an
  elaborated overload symbol. `grep` for `mangle(`/`safe_suffix` finds no other
  caller.
- **Measured on `std/math/math.mojo`'s generated C** (a large succeeding case
  with real instantiations — `abs`, `log`, `ldexp`, `copysign`, `isinf`,
  `isnan`): 21 lines changed, 21 removed / 21 added, every one of them a single
  symbol rename with the types and the call shape unchanged
  (`abs_Int64` -> `abs_1_T_5_Int64`, `log_Float64_1` ->
  `log_5_dtype_7_Float64_5_width_1_1`). Renaming those 8 symbols back makes the
  new file **byte-identical** to the old, so nothing else moved.
  `std/builtin/_format_float.mojo` and `std/collections/dict.mojo` are
  byte-identical before and after (they elaborate nothing).
- **The CAS.** `cas.instantiation_key` keys on `(template source, type_args,
  comptime_args)` and folds in `compiler_fingerprint()`, which hashes
  `monomorphize.py` by content (`cas.py:_COMPILER_SOURCES`). So every object
  built under the old spelling is unreachable rather than silently served under
  the new one. This is stated because the alternative failure — a warm CAS
  serving an object whose symbols no longer match the declarations — is exactly
  the class of bug this doc keeps finding. No key was migrated.
- **Tests pinning the old spelling** were updated: `test_module_cache.py`
  asserted `box_Int64`, `Box_Int64`, `run_Num`, `Box_Num`, `pick__Int64`,
  `s5_id_Int64`, `Wrap_int64_t`, `outer_int64_t`, `box_List_Int_`, and
  `_Empty_Int___next__`. `test_generic_instantiation_symbol_agreement` now
  DERIVES the struct name from `mm.mangle(...)` (its subject is that the TU
  and the caller agree on one string, which hardcoding a spelling made it look
  like it was testing the spelling instead); the spelling itself is pinned by
  the new `test_mangle_is_injective`.

**Numbers.** `compile_stdlib.py` 588 / 22 / 0 before and after.
`tools/undef_import_census.py` 96 / 51 / 60 before and after — unchanged, and
expected: a naming fix creates no instantiations, and the census only counts
files that COMPILE, so the 22 red ones are not in it either way.
`test_module_cache.py` 120 passed / 0 failed -> **131 passed / 0 failed**
(the 11 added checks are the injectivity corpus, its C-identifier and `___`
properties, five named collisions, the `mangle_signature` counterpart, and the
round-trip). `test_gimple.py` 354 passed / 0 failed.

**2026-10-02: the census did NOT move (96 / 51 / 60, unchanged), and four
defects landed that make three of this document's "PROVEN blockers" provable
rather than inferred.** They are listed first because they change what the next
session should trust.

### Landed 2026-10-02

| fix | file | why it is correct |
|---|---|---|
| the instantiation TU and its caller named the same function DIFFERENTLY, so nothing this compiler had ever materialized could link | `monomorphize.py` | it built the TU with `module_name=mangled`, and a struct method's C symbol is `{home-module}_{Struct}_{method}{overload_suffix}`, so it emitted `MoveOnly_Int64_MoveOnly_Int64___eq__` where the caller declared `MoveOnly_Int64___eq__`. Verified by linking `test/collections/test_array.mojo`'s generated C against its own CAS object: `ld: undefined _MoveOnly_Int___eq__`. Built with `module_name=''` — the existing "no module identity" convention — which leaves the top-level function identical (`no_mangle` protects it) |
| the elaborator READS the TU's symbols instead of composing them | `elaborate.py` + `mojo/backend_gimple/emit_resolve.py` | `elaborate_generic_struct` now returns `symbols` (`nm`, the tool `build_stdlib_dylib` already depends on) and `_register_generic_struct` registers each method under the name the object ACTUALLY defines. This makes the "duplicate method name disqualifies" rule a measurement: `_Empty[T]`'s two `__iter__` are reported as `_Empty_Int___iter___0120be` / `_0120be_2`, neither of which is the bare name a caller composes, so the refusal is demonstrably the honest state. The overloading wall below is CONFIRMED by measurement, not inference |
| a generic struct with NO FIELDS registers like any other | `mojo/backend_gimple/emit_resolve.py` | `struct _Empty[T]` has none; refusing it on that ground alone is what kept `var it = empty[Int]()` typed as a boxed `int64_t`. Field-count is not a soundness property — the duplicate-method guard is |
| a generic's RETURN annotation is materialized like a FIELD annotation already was | `mojo/middle/resolve_shared.py` + `mojo/backend_gimple/emit_resolve.py` | `_refine_generic_return_type` gained a `materialize` hook (the materializer lives one layer up, in the gimple backend, and this file is the middle tier that backend imports), so `empty[T]() -> _Empty[T]` reaches `_Empty_Int *` instead of `int64_t`. `_register_generic_structs_named` makes the returned struct discoverable when the importer never names it — the name is in the generic's RETURN annotation, never in the importer's `from … import` |

Suite: `test_module_cache.py` 120 passed / 0 failed, including
`test_generic_instantiation_symbol_agreement` (11 checks).
`compile_stdlib.py` is 588 / 22 / 0 throughout.

### The three "PROVEN blockers" — two are now MEASURED, and one is a property of `mangle`

**`FormatStruct` (15 sites): the overload suffix is not recoverable — CONFIRMED,
and now the refusal is exact.** `overload_suffix_for` is a pure module-level
function, so the hasher was never the obstacle; the INPUT is. The TU defines
`_fields_6ca16d` and `_fields_93095a` and `_register_generic_struct` composes
`_fields`, which the object does not define. With the symbols now read from the
object, this is a lookup that comes back empty rather than a name that would be
wrong — so the honest unblock is unchanged and now precisely stated: the CALLER
must know the real C parameter types, i.e. the in-TU route.

**`ThinAllocation` (8 sites) and `alloc` (10 sites): unchanged.** `T` is the
POINTEES, load-bearing, and `Foo *` does not name a Mojo type; `global_constant
[T, value: T]()` is a comptime VALUE parameter with no runtime argument.
Neither is reachable without a new parameter-passing / Ctype→Mojo-type model,
and inventing either is the `bogus-binding` silent-wrong case.

### In-TU instantiation: MEASURED WORKING, then reverted — the blocker was `monomorphize.mangle`

**RESOLVED 2026-10-03; see "Landed 2026-10-03" at the top of this file.**
`mojo/backend_gimple/elab_intu.py` was written in full and made
`test/iter/test_empty.mojo` compile AND LINK (the module's own object DEFINES
`empty_Int` and `_Empty_Int___next__`, `nm -g` after a real `gcc -c`). It was
reverted: it regressed five currently-compiling files with `error: conflicting
types for '<name>'` — an in-TU DEFINITION with real parameter types beside an
elaborated EXTERN with erased ones.

The recorded root cause was "**The root cause is `monomorphize.mangle`, and it
is a defect in its own right** ... so two DIFFERENT instantiations whose
parameter sets differ only in their NAMES mangle to the SAME symbol", with the
prescription "key the mangled name on the parameter NAMES as well".

**Both halves of that statement were wrong, and the second was wrong in the
direction that mattered.** Differing only in parameter NAMES does not collide
under the old code (`{T: Int64, o: MutOrigin}` and `{T: MutOrigin, o: Int64}`
are one dict; as distinct pairings they are distinct instantiations that the old
code named differently). The real defect was ambiguous segmentation of the
joined VALUES together with a LOSSY escape that collapsed `'A B'`, `'A.B'`,
`'A_B'` and `'List[Int]'`/`'List_Int'` onto one fragment. Keying on the
parameter NAME was still the right medicine, but as a *completeness* fix (two
templates may share a base name and differ only in what they call their
parameter), not as the collision.

**The other half — that fixing `mangle` makes in-TU land — is NOT verified, and
should not be assumed.** The five regressions were `conflicting types`: a
definition with real parameter types beside a declaration with erased ones,
which is a statement about the *caller's* view of a signature and not about the
name being unique. Injectivity removes one way to produce it (two different
templates landing on one name); whether it was THE cause is exactly what the
next pass must establish by landing in-TU and re-running the sweep, not by
reasoning. `bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md`
carries the experiment's shape and the two restrictions already tried.

### Landed 2026-10-01

| fix | file | before → after |
|---|---|---|
| census: declarations are not calls | `tools/undef_import_census.py` | 424 → 108 |
| census: reproducible replay set | `tools/elab_fail_census.py` | 653 / 286 files → 1226 / 507 files, same both ways |
| census: compile failures were never counted | `tools/elab_fail_census.py` | `instantiate-failed` 0 → 278 (all non-gcc: 247 `RecursionError`, 29 `SyntaxError`, 2 `ValueError`) |
| a defaulted `[...]` parameter is not a required one | `elaborate.py` | `too-few-targs` 526 → 178 |
| `comptime for` induction variable emitted a bare `int` into an `int64_t` | `mojo/backend_gimple/emit_funcs.py` | `IndexList`/`Array` instantiations now compile (gcc) |
| `Self.<param>` readable as `<param>` by inference | `elaborate.py` | — |
| a generic struct constructed with NO bracket arguments | `elaborate.py` + `mojo/backend_gimple/emit_resolve.py` + `emit_calls.py` | `FormatStruct` 15 → 0, `Named` 6 → 0, `Repr` 3 → 0 |

## What was wrong with the measurement

**1. The 424 counted DECLARATIONS, not calls.** `check()`'s test was

```python
if not re.search(rf'(?m)\b{re.escape(local)}\s*\(', c):
    continue
bad.append((rel, local, mod))
```

over the whole generated file. The codegen emits, for **every** name a module
imports — used or not — a guarded forward declaration in the preamble:

```c
#ifndef size_of
#define size_of
extern int64_t size_of (...);  /* from std.sys.info */
#endif
```

which that regex matches. So `std/builtin/sort.mojo`, which imports `alloc`
and `Layout` and calls *neither*, was reported as two undefined call sites. A
forward declaration is harmless: it links fine, because nothing references it.
`_bare_call` now excludes exactly the two machine-marked generated-declaration
forms (`#ifndef NAME` guards, and any line carrying this codegen's own
`/* from <module> */` / `/* stub from <module> */` marker) plus occurrences
inside a string literal — this codegen emits every docstring as one, and
`std/utils/coord.mojo`'s docstring literally contains the text
`Coord(Coord(2, 3), Coord(4, 5))`. Nothing else is filtered, because a
"does this line look like a declarator" heuristic would silently drop real
calls, which is the one failure mode a census must not have.

**424 → 108**, and the residue is real: `FormatStruct` 15, `alloc` 10,
`ThinAllocation` 8, `Named` 6.

**2. `explicit-failed` never described a failed instantiation.**
`monomorphize.instantiate`'s gcc step is `subprocess.run(..., check=True)`,
which RAISES. The exception propagates out of
`Elaborator.elaborate_generic_call` — which does not catch — past the
`elab_fail_census` wrapper that was recording attempts, and is finally
swallowed by the call site's blanket `except Exception` → `info = None`. So
the reason counted only paths that RETURNED `None`. Split into `too-few-targs`
and `instantiate-failed`, and the "populate" becomes:

| reason | count | what it needs |
|---|---|---|
| `unbound` | 255 | parameter shapes inference does not cover (`origin: Origin`, `**kw`, `Some[T]`, a pointee that is not a type name) |
| `instantiate-failed` | 278 | **not gcc** — 247 `RecursionError` (caller-stack-depth dependent; the fragment compiles standalone), 29 `SyntaxError` (e.g. `_is_nvidia_gpu_any[_SM_80X_ARCHS]`), 2 `ValueError` |
| `too-few-targs` | 178 | after the defaults fix: a default this code cannot turn into a concrete argument — `element_type=_` (a wildcard), `origin_of()._mlir_origin`, `words_en()` |
| `no-type-params` | 46 | name routed here that is not parametric after all |
| `no-overload-match` | 6 | trait-bounded overload selection |

So "the numeric library's instantiation TUs do not compile" was not the
finding. **Zero** of the 278 are gcc errors. The one real gcc bug in that
family (`IndexList`/`Array`'s `non-trivial conversion in 'integer_cst'`) is
fixed, below.

**3. The replay set was 40 names out of a `set`,** so it moved with
`PYTHONHASHSEED`: two consecutive runs on an unchanged tree replayed 286 and
399 files and reported 653 and 1705 attempts. The cap is gone (a substring test
per file is nothing next to the compile that follows) and `flagged` is sorted.

## Fixed: `comptime for`'s induction variable was a bare `int` literal

`_gen_stmt_ComptimeForStmt` unrolled with
`gen._emit(f"  {node.target} = {i};")` — raw Python formatting, bypassing the
`_safe_coerce_emit` chokepoint every other store goes through. An unadorned
integer literal has C type `int`, and GIMPLE's verifier rejects the widening
to an `int64_t` rather than inserting the conversion the C front end would:

```
$ cat > a.c <<'EOF'
int64_t __GIMPLE f (int64_t g)
{  int64_t i;
bb_2:  i = 5;  return g + i; }
EOF
$ gcc-mp-15 -fgimple -fPIC -c a.c
error: non-trivial conversion in 'integer_cst'
int64_t
int
i = 5;
```

which is `error: non-trivial conversion in 'integer_cst'` — the exact
`IndexList_Dtype_int32_2___init__` / `Array_Int_3___init__` failure. It was
never about SIMD, `Some[def]`, `self[...]`, or 32-bit narrowing: the
subscript is incidental, and the failure moves to whatever the unrolled loop
does next. (`compile_stdlib.py`'s gcc step is `-fgimple -fsyntax-only`, which
DOES report it, so the class is not invisible to the gate — it is simply rare:
only `std/utils/index.mojo`'s `IndexList` among 610 files reaches the unrolled
store into a variable that is not already `int`-typed. An earlier reading of
this section claimed `test/collections/test_dict.mojo`'s
`comptime for i in range(10, 14)` carried the same construct; it does not —
checked function-locally, its `i` is `int`-typed. Reproduce with
`python3 tools/repro_indexlist.py`.)

Fixed by routing the induction-variable store through
`gen._safe_coerce_emit('int', <target's declared ctype>, str(i), target)`, so
the emitted form is decided by the destination type like every other store.
`python3 tools/repro_indexlist.py` now exits 0 and the unrolled body is
correct (`idx = 0LL; … self[idx] = elems[idx]; idx = 1LL; …`).

## Fixed: a defaulted `[...]` parameter is not a required one

`elaborate_generic_call`/`elaborate_generic_struct` required one explicit type
argument per bracket parameter:

```python
if not params or len(type_args) < len(params):
    return None
```

Mojo's bracket head is a Python-like parameter list and its parameters can be
optional exactly as value parameters can — and `target: CompilationTarget =
CompilationTarget.current()` is the second parameter of **every** target query
in `std/sys/info.mojo`. So `size_of[UInt8]()`, written exactly as the stdlib
writes it, was declined before anything was compiled. `bind_type_args` now
fills a missing trailing parameter from its default through
`_default_type_arg`, which accepts only two provable shapes — a literal
(`copy: Bool = False`, `N: Int = 8192`) and a type-named expression
(`CompilationTarget.current()` → `CompilationTarget`, the type it denotes).
Anything else — `element_type=_`, `origin_of()._mlir_origin`, `words_en()` —
binds nothing and the call declines exactly as before.

`too-few-targs` 526 → 178.

`parse_bounds` had the matching bug: `target: CompilationTarget =
CompilationTarget.current()` parsed as the bound
`'CompilationTarget = CompilationTarget.current()'`, so every conformance
check silently degraded to "unknown trait, accept". Now stripped at the `=`.

## Fixed: a generic struct constructed with no bracket arguments

**56 of the 108 real undefined-call sites.** The stdlib overwhelmingly spells a
generic-struct constructor without its bracket arguments, because the types are
written in the parameters:

```mojo
struct FormatStruct[T: Writer, o: MutOrigin](Movable):
    var _writer: Pointer[Self.T, Self.o]
    def __init__(out self, ref[Self.o] writer: Self.T, name: StaticString):
```

```mojo
_t3 = FormatStruct (writer, _t2);   /* nothing defines this */
```

`_elaborate_generic_struct_call` fired only on a `SubscriptExpr` callee, so
every bare `Struct(...)` fell through to the ordinary call path.
`infer_struct_type_args` now reads the type args off the `__init__`
annotations, and `_lower_call` routes a bare `IdentExpr` callee there when the
name is a registered imported generic struct. `FormatStruct` 15 → 0, `Named`
6 → 0, `Repr` 3 → 0, `_DictEntryIter`/`_DictValueIter`/`_DictKeyIter` → 0.

Three supporting pieces, each of which was a way the inference and the
SUBSTITUTION disagreed about the same text:

- **`Self.<param>` is `<param>`.** `_unify_param_ann` compared the annotation
  to the parameter list with `==`, so `writer: Self.T` bound nothing while
  `monomorphize_source` substituted `Self.T` happily. It now strips a leading
  `Self.`, which is exactly what the substitution does.
- **`o: MutOrigin` binds, and provably cannot change the answer.**
  `elaborate.erased_only_params` counts, over CODE only, whether EVERY
  occurrence of a parameter falls in a position `_mojo_type` discards: the
  `ref[...]`/`mut[...]`/`inout[...]`/`owned[...]`/`borrowed[...]` qualifier, or
  any argument of `Pointer[`/`Ref[`/`UnsafePointer[` after the FIRST (a comma
  inside the bracket is required, or the load-bearing pointee would match too).
  Measured, the second argument is discarded outright:

      Pointer[Formatter, MutOrigin] -> 'int64_t *'   Ref[Formatter, MutOrigin] -> 'int64_t'
      Pointer[Formatter, Int64]     -> 'int64_t *'   Ref[Formatter, Int64]     -> 'int64_t'
      Pointer[Formatter, __junk__]  -> 'int64_t *'   MutOrigin                  -> 'int64_t'

  and the emitted C for `FormatStruct[String, MutOrigin]`,
  `FormatStruct[String, Int64]` and `FormatStruct[String, ZZZ_unknown]` is
  **byte-identical** once the mangled name and the temp path are normalised
  (`tools/`-free check, reproduced from `elaborate.extract_struct_source` +
  `monomorphize.monomorphize_source` + `GimpleGen.gen_module`). That is the
  evidence this is output-equivalent rather than a guess. A parameter that is
  NOT erased-only is still left unbound, so the all-params-bound requirement
  still declines it.
- **Ambiguity is refused.** Every `__init__` whose arity matches is tried and
  the type args must AGREE; two constructors inferring different `T`s from the
  same call returns `None` rather than preferring the first, the same rule
  `myinterpreter.MojoOverloadSet` states.

**The risk this carries, stated plainly.** `c_to_mojo` is a scalar reverse-ABI
table: `char *` → `String`, anything else → `Int`. A struct whose field is
annotated with the bare parameter (`struct Box[T]: var v: Self.T`) constructed
from a `char *` now gets a real struct at a layout inferred from that table,
where before it got a link error. This is the SAME inference model the
function path (`elaborate_generic_call_inferred`) has always used, extended to
structs; it is not a new class of guess, but it is a guess, and
`tools/elab_fail_census.py`'s `bogus-binding` reason is the label for it.

**`ThinAllocation` (8) is NOT fixed and honestly cannot be**, for exactly that
reason: `struct ThinAllocation[T: AnyType]` declares
`unsafe_owned_ptr: Pointer[Self.T, MutUntrackedOrigin]` — `T` is the POINTEES,
which is load-bearing, and the argument's C type (`SomeStruct *`) does not name
a Mojo type. Binding it would be `bogus-binding`, i.e. the silent-wrong case.

## `FormatStruct` (15) — the largest remaining item, and precisely why

It does NOT elaborate, deliberately. The struct instantiates and its
instantiation TU compiles cleanly, but `_struct_layout_anns` reports methods by
their BARE name, while the TU mangles an OVERLOADED method by signature:

```
the real TU:  FormatStruct_Int64_MutOrigin_..._fields_93095a (self, MojoList *)
              FormatStruct_Int64_MutOrigin_..._fields_75c303 (self, int64_t)
              FormatStruct_Int64_MutOrigin_..._fields (...)          <- dispatcher
the registry: extern void FormatStruct_Int64_MutOrigin_fields (FormatStruct_Int64_MutOrigin *, int64_t);
```

So registering it declares a symbol nothing defines, with ONE of the two
arities — and the other arity's call site is a hard gcc error, not a silent
wrong answer: `test/format/test_utils.mojo` went to
`error: too many arguments to function 'FormatStruct_Int64_MutOrigin_fields';
expected 2, have 3` the moment the guard was weakened. The old guard only
fired when the ERASED signatures differed, and these defeat it:
`_mojo_type('*Ts')` and `_mojo_type('Some[def[T:Writer](mutT)]')` are both
`int64_t`, so they compared equal while the real symbols do not. Any duplicate
method name is now disqualifying, unconditionally, and 589/21/0 is restored.

**This is the real remaining work, and it is one thing, not a family:** teach
`elaborate._struct_layout_anns` the SAME signature mangling the instantiation TU
uses, so `_register_generic_struct` declares the mangled names the definitions
actually have. That is a pure naming change with no new inference in it, and it
would take `FormatStruct` 15 → 0 and unblock `test/format/test_utils.mojo`'s
real behaviour rather than its refusal. It was NOT attempted here because the
mangling suffix (`_93095a` / `_75c303`) is produced by the codegen's own
overload hasher, and reproducing it outside `GimpleGen` means either exporting
that hasher or re-deriving it — both of which need the gate this session was
asked to postpone.

## The measurement (ORIGINAL text — inflated 4x, kept for the record)

> **SUPERSEDED — read the correction at the top of this file first.** The 424 /
> 157 / 194 below counts forward DECLARATIONS, not calls; the real figure was
> 108 / 56 / 60, and is 96 / 51 / 60 as of 2026-10-01. Everything below is kept
> because its per-site *analysis* is sound and re-derived on the true
> population, but the COUNTS are not. Where this section says "424 sites", read
> "108 sites".

`python3 tools/undef_import_census.py` over the same 610-file sweep
`compile_stdlib.py` uses:

```
undefined-imported-generic call sites: 424
distinct names:                         157
files affected:                         194
```

Top of the list: `external_call` (36), `CompilationTarget` (21),
`_get_kgen_string` (16), `FormatStruct` (15), `Layout` (13), `alloc` (11),
`TypeNames` (10), `size_of` (10), `global_constant` (10), `ThinAllocation` (9),
…

**Every one of the 15 `external_call` "sites", all 21 `CompilationTarget`, all
16 `_get_kgen_string`, all 13 `Layout` and all 10 `size_of` entries above is
the preamble declaration alone** — see "What was wrong with the measurement".
`external_call` has its own real lowering (`_lower_external_call`) and is
resolved in all of them; `std/builtin/sort.mojo` accounts for `Layout` and
`alloc` and calls neither.

## What one site looks like

`reflect.export_exclusions` deliberately keeps every GENERIC template out of a
module's export table (ELABORATION.md: a generic has no single concrete symbol,
so importers are supposed to instantiate it on demand). When that on-demand
elaboration does not happen, the codegen emits an extern and calls it:

```c
#ifndef peekable
#define peekable
extern int64_t peekable (...);  /* from std.iter */
```

`test/iter/test_peek.mojo` is not in the 194 because it does not compile at
all — it is one of the 21 declared `EXPECTED_FAILURES` in `compile_stdlib.py`
(`bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md`). So the
21 and these 194 are the SAME defect at two stages: where the refusal catches
it, the file is red; where nothing refuses, the file is green and wrong.

And the wrongness is not theoretical. `nm -gU build/libmojostdlib.arm64.dylib
| grep -c peekable` is **0** — the stdlib dylib that `stdlib-dylib` reports as
building cleanly from 249 modules does not define `peekable` at all, so any
program that imports it cannot link.

## Why `compile_stdlib.py` never saw any of it

It is `gcc -fgimple -fsyntax-only`. That checks the translation unit's
*internal* consistency — a call to a declared-but-undefined function is
perfectly legal C. Nothing in the step links, and nothing else links the
`test/` tree. The dylib build does link, but only checks its own reflection
export table ("declared with no definition in this dylib: standardize_string_slice,
ord, ascii, atol") — never the `extern`s a module emits for names it imported.

## Why it is not a gate step yet

194 files. Landing it as a failure would turn `stdlib-syntax` red on 194 files,
158 of which are outside the 21 already declared. That is the right long-term
state — the check is honest and the reds are real — but it is a decision about
the suite's shape, not a bug fix, and it should not arrive as a surprise
attached to a codegen change.

Interim: the census is a tool, and its number is recorded here so the next
session does not re-derive it.

## What the 424 sites actually are (measured, so nobody re-derives it)

> **COUNTS SUPERSEDED — see above; "424" means 108.** The classifications
> below were computed over the inflated set, so the per-reason split is
> proportionally wrong, but the conclusion they support (every site is a
> bracket template; registration works; the elaborator is asked and declines)
> was re-derived on the true population and still holds.

Three measurements narrow this from "424 sites" to one mechanism, and the last
one is the one that decides the project's size.

**1. Every one of them is a bracket-parametrized template.** Classifying each
site by the rule `reflect.export_exclusions` reports gives `EXCL_GENERIC` 253,
`EXCL_PRIVATE` 112, `EXCL_OVERLOADED` 49, not-excluded 10 — but that split is an
artifact of the *reporting* order, not of the code: `export_exclusions` tests
private → clib → overloaded → generic and files a name under the first rule
that matched, so a private or overloaded name that is ALSO a template is
reported under the earlier rule. Checking the source directly, all of them are
templates: `def size_of[T, ...]` (std/sys/info.mojo:1416), `def _heap_sort[...]`
(std/builtin/sort.mojo:136), `def _memchr[...]`
(std/collections/string/iterators… string_span.mojo:2649), `def peekable(...)`.

**2. The exporting module does not define them either.** Compiling the
*exporting* module on its own and searching its generated C for a top-level
definition: 1 of 112 for the `private`-reported sites, 5 of 49 for the
`overloaded`-reported ones. So this is not a registration bug on the importing
side — the symbol genuinely does not exist anywhere.

**3. Registration already works; the elaborator correctly declines.** For
`std/builtin/_format_float.mojo`, which does `from std.sys.info import size_of`:
`size_of` IS in `gen._imported_generics` (so `_register_imported_generics` and
`_find_generic_source` did their job), and `_elaborate_generic_call` IS reached
— it returns `None` because `infer_type_args` cannot bind the parameter:

```python
# elaborate.py
for i, (_pname, ann) in enumerate(fn.params):
    if ann in params and ann not in binding and i < len(arg_ctypes):
        binding[ann] = c_to_mojo(arg_ctypes[i])
if any(p not in binding for p in params):
    return None
```

**That last point is the whole finding.** A large share of these templates —
`size_of`, `align_of`, `bit_width_of`, `simd_width_of`, `is_gpu`,
`is_nvidia_gpu`, … — take **no arguments at all**. Their type argument comes
from the *use site*: `size_of()` appears inside `Struct[Elem, N]`'s annotation,
where only bidirectional inference can recover `[Elem]`. There is nothing to
elaborate from, so the elaborator's refusal is correct and no amount of wiring
will change it.

So this is one defect with three necessary mechanisms behind it, and none of
them is a wiring change:

1. **Bidirectional, use-site-driven type inference**, for the zero-argument
   templates above. This is the largest item and the one nothing else can be
   sequenced around.
2. **Dependent return types**, for the argument-driven ones
   (`peekable(list)` → `_PeekableIterator[type_of(iterable).IteratorOwnedType]`,
   i.e. `List.IteratorOwnedType` = `_ListIterOwned[Self.T]`,
   std/collections/list.mojo:361). Needs `Self.<comptime member>` resolved from
   the struct's own `comptime` declarations, not textually substituted.
3. **In-TU instantiation**, so the materialized struct's methods land in
   `struct_field_types` / `func_return_types` where `next`/`for` dispatch on
   them — the `.o` route cannot work, because `peekable`'s body is
   `return {iter(iterable)}` and `iter` is itself a template.

## Two real defects found and fixed inside this (2026-10-01)

`tools/elab_fail_census.py` wraps the three `Elaborator` entry points and
classifies every decline. Its first run gave **1254 declines**, and 903 of them
were one shape. Two one-line defects, both silent:

**1. `//` was being reported as a type parameter** (`elaborate.type_param_names`
skipped `'/'` and `'*'` but the stdlib writes Mojo's current `//`). So
`def ceildiv[T: CeilDivable, //](...)` reported `['T', '//']`, `infer_type_args`
was required to bind *both*, nothing can bind `//`, and **every template
written with the current marker was declined outright** — which is the entire
numeric library. Now filtered by character (`_is_param_marker`).

**2. a type parameter nested inside a parameter's annotation never bound.**
`infer_type_args` tested `ann in params` — exact equality — so
`def copysign[dtype, width](magnitude: SIMD[dtype,width], ...)` bound neither.
Now a structural unifier (`_unify_param_ann`) that also reads
`SIMD[<param>, <param>]`. `width` binds to `1`, which is not a guess: this
codegen erases SIMD outright (`_mojo_type('SIMD[Float64, 4]')` is `int64_t`,
`_TYPE_MAP` has no SIMD key), so every value that reaches the elaborator is a
scalar. Any shape it does not recognise returns `{}`, and the
all-params-bound requirement means an unrecognised shape binds nothing at all —
so it declines exactly as before.

Declines: **1254 → 715**. And the calls really resolve, not merely move:
`std/math/math.mojo` now emits `copysign_Float32_1` / `copysign_Int64_1` /
`ldexp_Float32_1` and contributes 8 CAS link objects, with **no bare `extern
int64_t copysign (...)` left in its generated C**. `compile_stdlib.py` is
unchanged at 589/21/0 — it never links, so it cannot see the improvement; that
is this doc's original point, not a contradiction of it.

Pinned by `test_module_cache.py::test_type_param_markers_and_simd_unification`
(11 cases, including that an unrecognised annotation shape still declines and
that a partial bind is impossible), which joins the 8 cases of
`test_self_qualified_type_param_substitution`. Suite: 102 passed / 0 failed.

## What is still open, and the one population

**Correction to an earlier version of this section, which claimed the census's
names and the elaborator's declined names were "disjoint sets". They are not,
and the claim was wrong.** `size_of` and `alloc` appear in both. The real
picture is simpler:

- **Every one of the census's 157 names IS a bracket template.** Checked
  directly against each declaring module's source: 409 of 424 sites resolve to
  a `def`/`fn`/`struct NAME[...]`; only 15 do not.
- **Registration already works.** `size_of` is in `gen._imported_generics` for
  `std/builtin/_format_float.mojo`, so `_register_imported_generics` and
  `_find_generic_source` did their job and `_elaborate_generic_call` *is*
  reached.

So there is one population — 424 sites where the elaborator is asked to
instantiate and declines — with four measured reasons (715 attempts total
after the two fixes above):

| reason | count | what it needs |
|---|---|---|
| `explicit-failed` | 367 | an explicit `f[T](...)` whose **instantiation's own TU does not compile** |
| `unbound` | 296 | the remaining un-understood parameter shapes — `origin: Origin`, `**kw`, `Some[T]`, `Pointer[T]` — and templates whose type argument only the *use site* knows (`size_of[T]()`, `align_of[T]()`, `bit_width_of[T]()`) |
| `no-type-params` | 44 | name routed here that is not parametric after all |
| `no-overload-match` | 8 | trait-bounded overload selection |

**`explicit-failed` is the cheapest real population and it has not been looked
at.** It is not an inference problem at all: `elaborate_generic_call` resolves
the overload and calls `monomorphize.instantiate`, which monomorphizes the
template and compiles it as its own translation unit — and that TU fails. Two
concrete failures visible in the run's stderr, both real codegen bugs in the
instantiated fragment rather than anything to do with types:

- `IndexList_Dtype_int32_2___init__` and `Array_Int_3___init__`:
  `error: non-trivial conversion in 'integer_cst'` — `int64_t` vs `int` in an
  unrolled `fill_with_unrolled[i]` loop, i.e. the same 32-bit-truncation class
  `_local_value_type`'s docstring already documents for unannotated locals.
- `getsize_String`: `error: implicit declaration of function 'stat'` — the
  instantiation TU has no `<sys/stat.h>`, so the preamble that the main pipeline
  relies on is not reaching it. That one is a missing include and is almost
  certainly a few lines.

## Next step

Start with `explicit-failed`, because it is neither inference nor registration:
make the instantiation TU compile. Progress metric is
`tools/elab_fail_census.py`'s decline count — profiler-independent.

### `getsize_String`: the missing `<sys/stat.h>` — analysed, and the obvious fix is NOT safe

The instantiation TU's preamble is `stdint/stdlib/string/math/stdio/setjmp/dlfcn`
plus `fire_runtime.h`, and it emits `_t4 = stat (_t3);`. `fire_runtime.h`
includes `<sys/types.h>` and (off Apple) `<time.h>` but **not** `<sys/stat.h>`,
so `stat` is called with no prototype — and gcc rejects it:
`error: implicit declaration of function 'stat'` (implicit declarations are an
error in C23, which is why this is fatal rather than a warning).

The obvious fix is to add `#include <sys/stat.h>`, and **it breaks the build**,
for exactly the reason documented at `runtime/fire_runtime.h:1581-1596` for
`<time.h>`: `std/os/_macos.mojo:137` reaches the same symbol through
`external_call["stat", Int32](...)` and emits its own declaration, so the
header's prototype and the module's would collide — the identical
`error: conflicting types for 'clock_gettime'` that stopped `<time.h>` from
being included unconditionally.

So this is the same unresolved problem `<time.h>`'s comment already names, and
its own verdict applies: *"Fixing it properly means auditing every
`external_call` in the stdlib against its real C signature, which is its own
project."* `stat` is in `_C_RESERVED_FUNCS` and is reached by BOTH spellings —
bare (`getsize`) and `external_call` (`_macos`) — so the audit has to cover both
before the header can change. Not landable as a few lines, and not landable at
all without a gate.

### `IndexList_Dtype_int32_2___init__` / `Array_Int_3___init__`: `non-trivial conversion in 'integer_cst'`

`error: non-trivial conversion in 'integer_cst'`, three times for `IndexList`,
once per unrolled index.

**Correction to an earlier version of this section**, which attributed it to
`Array`'s `init_with=lambda () {ref} -> Self.T: fill_with_unrolled[i]()` and
implied a `Some[def]`/lambda shape. The `IndexList` instance is simpler than
that. Monomorphizing `std/utils/index.mojo`'s
`struct IndexList[size: Int, *, element_type: DType = .int64]` for
`{size: 2, element_type: Int32}` puts the failure at concrete-source lines 94-95:

```mojo
comptime for idx in range(2):
    self[idx] = elems[idx]
```

gcc points the diagnostic at line 96, i.e. just past the unrolled body, and the
interleaved `int64_t` / `idx = 0;` in the error text is the declaration and its
first assignment. The two shapes share only the outer feature — a
`comptime for` unrolled inside a monomorphized generic struct's `__init__`,
with the loop variable then used as a SUBSCRIPT index. `Array`'s instance is
the same feature with a lambda on the right-hand side; treat them as one bug
until the two are shown to differ.

What is NOT the cause, checked rather than assumed:

- **`comptime for` itself is fine.** `comptime for i in range(3): total += i`
  in an ordinary function unrolls correctly: `i = 0; _t1 = total + i; i = 1; …`.
- **The `Some[def(Int) -> T]` lambda shape is not generally dropped.** A
  `comptime for` whose body is `self.data.unsafe_offset(i).unsafe_write(...)`
  vanishes from the generated C — but that is a *different*, narrower gap and
  it is not this one.

**RESOLVED, and it was none of the above.** The whole "the trigger is the
unrolled index flowing into a subscript" line is wrong: the subscript is
incidental and so is the lambda. `_gen_stmt_ComptimeForStmt` emitted the
induction-variable store with `gen._emit(f"  {node.target} = {i};")` — raw
Python formatting — bypassing the `_safe_coerce_emit` chokepoint every other
store in the tree goes through. An unadorned integer literal has C type `int`,
and GIMPLE rejects the widening to the loop variable's own `int64_t`
declaration. Fixed and reproduced by `tools/repro_indexlist.py`; see "Fixed:
`comptime for`'s induction variable was a bare `int` literal" above.

### `getsize_String`: still open, and the census now says why it is not the plan's problem

`error: implicit declaration of function 'stat'` is real, but with
`elaborate_generic_call`'s exceptions now RECORDED rather than sailing past the
instrument, it turns out **zero** of this session's `instantiate-failed`
population (278) is a gcc error: 247 are `RecursionError` and 29 `SyntaxError`.
`getsize_String` is a `SyntaxError`-class neighbour, not the numeric library's
problem. The `<sys/stat.h>` analysis above stands unchanged and is still not
landable as a few lines.

## Where this actually stands (2026-10-01, end of session)

| | before | after |
|---|---|---|
| `undef_import_census.py` | 424 sites / 157 names / 194 files **(mis-measured)** | **96 sites / 51 names / 60 files** |
| …of those, generic STRUCT constructors | 56 | 41 |
| `elab_fail_census.py` declines, on the SAME 507-file / 157-name replay | 1226 recorded (+ an unknown number that escaped the instrument entirely) | **542 recorded, including 187 that used to escape it** |
| `compile_stdlib.py` | 589 / 21 / 0 | 589 / 21 / 0 |

The 542 breaks down as `unbound` 172, `instantiate-failed:RecursionError` 157,
`too-few-targs` 134, `no-type-params` 45,
`instantiate-failed:SyntaxError` 29, `no-overload-match` 4,
`instantiate-failed:ValueError` 1. The like-for-like run used a throwaway
driver (`/tmp/ab.py`) that pins the replay set to the ORIGINAL 157 flagged
names, because the corrected census flags fewer names and would otherwise shrink
the denominator and make the counts look like they went UP.

Remaining, in the order the next session should take them:

1. **`FormatStruct` (15)** — method-overload mangling in `_struct_layout_anns`.
   One naming change, no new inference. See its section above.
2. **`alloc` (10) / `ThinAllocation` (8)** — `Pointer[T, o]` where `T` is the
   POINTEES, so it is load-bearing, and the argument's C type (`Foo *`) does not
   name a Mojo type. Needs a Ctype→Mojo-type table the elaborator does not
   have. Binding it today would be the `bogus-binding` silent-wrong case.
   `alloc` is the largest single name in the instrument at all: 52 declines
   (22 `unbound`, 30 `too-few-targs`), of which the 30 are
   `std/builtin/globals.mojo`'s `def global_constant[T: Copyable &
   Deinitable, //, value: T]()` — a `value:` comptime parameter with NO default
   and no runtime argument, which is a whole parameter-passing model this
   elaborator does not have.
3. **`_FlushingWriteBuffer` (4), `_to_string_list` (4),
   `_is_utf8_continuation_byte` (3), `write_sequence_to` (3), …** — the
   `unbound` shapes: `origin: Origin`, `**kw`, `Some[T]`.
4. **247 `RecursionError`s** — an exception that escapes
   `elaborate_generic_call` because the fragment's own compile blows the
   stack, and it is CALLER-STACK-DEPTH dependent (the same `size_of[UInt8]()`
   instantiates fine standalone and from a shallow caller). That is a
   stack-depth fragility in the elaboration path, not a per-template bug, and
   it wants its own diagnosis before any of the 247 are attributed to their
   templates.

### The 247 `RecursionError`s — DO NOT REPRODUCE (2026-10-01, re-measured)

A previous pass reported "247 `RecursionError`s, caller-stack-depth dependent —
`size_of[UInt8]()` instantiates fine standalone and from a shallow caller" and
flagged it as the most suspicious remaining finding. **Re-measured on the
current tree (post-merge of the formal5 batch): zero, by every route tried.**

- `size_of[UInt8]()` via `Elaborator().elaborate_generic_call(...)` at
  `sys.setrecursionlimit` of 2000 / 4000 / 8000 / 16000 / 30000 — **OK at
  every one**, so it is nowhere near a recursion ceiling.
- The same call from a deliberately nested caller at depths 0 / 50 / 150 / 300
  — **OK at every one**.
- A pass wrapping all three `Elaborator` entry points to count
  `RecursionError` separately, replaying every file that references any flagged
  name: **0 `RecursionError`s, 0 by name, 0 by entry point.**

So the 247 was an artifact of whatever ran that pass, not a property of those
templates and not a fragility in the elaboration path. Two likely causes, worth
knowing before anyone re-reports it: that pass may have run without
`build_stdlib_dylib.compile_module_to_c`'s `sys.setrecursionlimit(120000)` and
1 GiB thread stack in effect, and it chose its replay set with
`list(flagged)[:40]` over a **set** — hash-order dependent, so two runs on an
unchanged tree replayed different files (it reported 286 files / 653 attempts
once and 399 files / 1705 attempts the next).

Do not spend a pass on this. The metric worth spending passes on is
`tools/undef_import_census.py`: **96 sites / 51 names / 60 files**, with a
fixed replay set.

### `FormatStruct` (15 sites) — the overload suffix is NOT recoverable; this is not a naming change

A previous pass called this "one naming change" and attributed it to needing
`GimpleGen`'s overload hasher. **The hasher is not the obstacle and the gate
would not buy it.** `overload_suffix_for(c_param_types)`
(`mojo/backend_gimple/emit_funcs.py:1562`) is a pure module-level function of a
C parameter-type list — no `GimpleGen` instance, and its own docstring says it
is shared with `reflect` precisely so both agree. So the suffix is callable
from the elaborator. The problem is that the elaborator cannot compute the
right INPUT.

Measured on `struct FormatStruct[T: Writer, o: MutOrigin]`, which has two
`fields` methods — `def fields[*Ts: Writable](self, *args: *Ts)` and
`def fields(self, fields_fn: Some[def[T: Writer](mut T)])`. Its instantiation
TU defines **three** symbols:

```
FormatStruct_String_MutOrigin_FormatStruct_String_MutOrigin_fields
FormatStruct_String_MutOrigin_FormatStruct_String_MutOrigin_fields_6ca16d
FormatStruct_String_MutOrigin_FormatStruct_String_MutOrigin_fields_93095a
```

while `_struct_layout_anns` reports exactly two, both as `('fields', 'void',
['int64_t'])` — because `_mojo_type('*Ts')` and `_mojo_type('Some[def...]')`
are both `int64_t`. And the suffix the caller CAN compute is wrong:

```
overload_suffix_for(['int64_t'])  ->  '_9f63a2'
```

which is none of `''`, `_6ca16d` or `_93095a`. So the two overloads are not
merely ambiguous to the elaborator, they are **indistinguishable**: the erasure
that makes them look identical is exactly the erasure that destroys the
function the suffix is computed from. `overload_suffix_for` is a function of the
C parameter types, and the elaborator's C parameter types are not the
instantiation TU's — the TU infers them properly, the elaborator erases them.
The information is gone in one direction and cannot be reconstructed.

That is why the existing guard (a duplicate method name disqualifies the struct)
is the only sound response available today rather than a cop-out: registering
either suffix would declare a symbol nothing defines, which is what previously
took `test/format/test_utils.mojo` to a hard `too many arguments to function`.
The honest unblock is to give the elaborator the codegen's REAL parameter
inference for the instantiated fragment — i.e. ask the instantiation TU what it
named its methods — which is a much larger change than a rename and does not
depend on the gate.

### The 247 `RecursionError`s — DO NOT REPRODUCE (2026-10-01, re-measured)

| item | sites | blocked on |
|---|---|---|
| `FormatStruct` | 15 | the instantiation TU's real parameter inference — NOT the gate, and not a rename (see above) |
| `alloc` | 10 | partly a different model: `global_constant[T, value: T]()` is a comptime value parameter with no runtime argument |
| `ThinAllocation` | 8 | genuinely blocked today: `T` is the *pointee*, load-bearing, and the argument's C type (`Foo *`) does not name a Mojo type |

The earlier `explicit-failed` / `unbound` split no longer describes what is
left: the two elaborator defects this doc names are fixed, and what remains is
dominated by names whose type argument is either a comptime value or a pointee
the C type cannot express.

Acceptance for the whole family is unchanged and unmet: the census must reach
**0 sites** and the declared `EXPECTED_FAILURES` must empty.

### Landed 2026-10-20: `getsize`'s first defect is closed (measured), and the
field-resolution fix it exposed changed 4 files — all verified, none a regression

**Defect 1 of the `getsize` family is fixed.** `__fspath__()` on a String
receiver was stubbed to 0 in the monomorphized `getsize_String` TU — the call
was `stat(0)`. stdlib's `String.__fspath__` returns the receiver unchanged,
and in this codegen's model a String IS its char* buffer, so
`emit_methods._lower_str_method` now lowers `__fspath__` on a char* receiver
as the identity (the `readlink`-family precedent: an honest passthrough, not
the generic 0-stub). Measured in the monomorphized TU's generated C:

    before:  _t2 = 0;  /* TODO: char*.__fspath__ */
             _t3 = stat (_t2);
    after:   _t2 = stat (path);

The main-pipeline caller of the same shape (`open(file_path, ...)` in
`test/os/test_stat.mojo`) moved with it: `mojo_open (file_path, mode)` where
it was `mojo_open ((char *)0, mode)`. `test_getsize` REMAINS in
`EXPECTED_FAILURES` — the TU still fails gcc -c, and the reason string now
names the two defects that remain (below). This is not a syntax-only green:
both defects are value-level and would still be wrong at runtime.

**The two defects that remain, precisely:**

1. **Bare `stat` — a cross-stdlib call the isolated TU cannot see.** The
   monomorphized `getsize_String` body spells `stat(path)` bare; `stat` is
   the generic `stat[PathLike: stdPathLike]` (std/os/fstat.mojo:179), and the
   isolated TU carries no import knowledge — so gcc sees `implicit
   declaration of function 'stat'`. Needs transitive elaboration of the
   callee (PathLike=String, inferred from the arg), a call rewrite to the
   mangled `stat_8_PathLike_6_String` symbol, and the callee's object on the
   link line. Same imported-generic family as the R1 doc's call site.
2. **The result model.** `stat(...)`'s return is boxed `int64_t`, re-
   interpreted `void *`, and `.st_size` is a dynamic
   `_mojo_dispatch_getattr`. The real signature is `int stat(const char *,
   struct stat *)` — an OUT-param filling a caller-owned struct — so a
   prototype pinning does not fix it (it would add an argument-count error,
   and the value would still come from the return register, not the out-
   struct). Needs `stat_result` materialized with its real layout so `.st_
   size` is a direct field read.

**The field-resolution fix (landed for the R1 doc's nested splice) changed 4
files' generated C — all four verified by a full-tree A/B (every file's C
hashed, baseline vs current; exactly 4 differ, zero status transitions):**

| file | change | verdict |
|---|---|---|
| `test/os/test_stat.mojo` | the `__fspath__` identity above | intended, measured |
| `std/ffi/__init__.mojo` | `OwnedDLHandle._handle: _DLHandle` (a struct VALUE — source: `var _handle: _DLHandle`) resolves `_DLHandle *` per the universal struct-as-pointer convention instead of `int64_t`; locals follow; `_DLHandle`'s `mojo_close` is called with the pointer | improvement — the baseline int64_t view was the erasure this family removes; both versions compile |
| `std/random/_rng.mojo` | `_RandomState._generator: _PhiloxWrapper` resolves `_PhiloxWrapper *`; the Box-Muller path's `log(u1)` dtype inference corrected `Int64` -> `Float64` (source: `u1 = self._generator.next_float64()` — a float; the baseline's `log_5_dtype_5_Int64` instantiation was the wrong one) | improvement, source-verified |
| `std/runtime/_asyncrt.mojo` | `TaskGroup`/`_AsyncContext` typedef positions move within the preamble; `TaskGroup.chain: _Chain` (a struct value) resolves `_Chain *` | improvement / position-only; compiles |

The A/B also established codegen determinism for these files (two
fresh-process runs of the same file in the same tree produce byte-identical
C — session log: `c_hashes_rerun.tsv`).

**Correction to the A/B above (measured, 2026-10-20 continued session):** that
comparison ran against the 05:02 `c_hashes_baseline.tsv`, which was a
MID-SESSION snapshot of the working tree (mid-edit state), not the
before-state. The true before-state is clean master (c947025a), measured via
a git worktree. Against that true baseline — in BOTH run shapes (the
12-worker pool over all 610 files, which is the shape the sweep uses, and
the fresh-process single-file compilation, which is the trustworthy per-file
shape): `std/ffi/__init__.mojo`, `std/random/_rng.mojo`,
`std/runtime/_asyncrt.mojo` and `test/os/test_stat.mojo` are **byte-identical**
between the working tree and clean master. The resolutions the table
describes (`_DLHandle *`, `_PhiloxWrapper *`, the Float64 dtype correction)
therefore also exist in clean master's C — identical bytes — and come from
earlier commits, not from this session's uncommitted work. Read the table as
a delta between two mid-session states of the working tree; it is kept as
history, not as a session-vs-master delta. Cross-module contamination
(contributing to the original over-count) is real and measured: compiling
multiple files in one process, or via the 12-worker pool, changes the
generated C — module-level state persists across files — so only a
fresh-process single-file comparison is trustworthy per file. The session's
ONE true full-tree C delta against clean master was the 3 iterator test
files, and it is since fixed to zero; see
`bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md`,
"2026-10-20 (continued)".
## 2026-10-20 (further): the function-level import hole is closed for factory
names; the declared-red population is 14 files, 3 reasons, EXIT 0

### What changed for this family

The lift documented in the R1 doc
(`CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md`,
"2026-10-20 (further)") closed the first end-to-end slice of this family's
imported-name half. The piece that belongs to THIS doc: `elab_intu.
_import_name_map` now recurses into FUNCTION bodies (a `FromImportStmt`
anywhere; first declaration, outermost-then-source-order, wins). Before, a
function-level `from std.itertools import take` — exactly the shape of
`test_drop_then_take_composition`, which imports INSIDE the test function —
was invisible to the factory-home lookup, so the call stayed on the plain
imported-name path: `extern int64_t take(...)` with nothing that defines it,
a link failure with the same "imported generic, never elaborated, calls
nothing that defines" signature this doc is named for. Measured before/after
in the generated C; the function now seeds through its home module and the
call resolves to the in-TU materialization (test_drop: ladder 14/14 with
real values, including that composition test).

NON-factory imported names are still refused, not stubbed: their
`_factory_returns` is empty, so the plain-imported-name path declines to
emit the call — the declared-red behaviour this dict exists to publish, not
a silent `extern`.

### Where the population stands now (measured sweep, 2026-10-21, final code)

Sweep **599 PASSED / 11 FAILED — 11 expected, 0 unexpected, EXIT 0**
(baseline of this campaign: 592/18; after lift-4: 596/14). The 11 declared-red entries, 3 distinct
reasons:

| reason | files |
|---|---|
| `_NEXT_ON_STRUCT` — the dependent-return imported-iterator family (the reason text's "UPDATE 2026-10-20" records the materialization half closed by the nested monomorphization fix; what remains is the CALL itself: overload selection (pass-mode + conformance), dependent-return resolution, and call-site container-iterator construction — see the R1 doc) | `test/collections/string/test_iterators.mojo`, `test/collections/test_set.mojo`, `test/iter/test_chain.mojo`, `test/iter/test_map.mojo`, `test/iter/test_zip.mojo`, `test/itertools/test_drop_while.mojo`, `test/itertools/test_product.mojo`, `test/itertools/test_take_while.mojo`, `test/python/test_python_object.mojo` |
| `test_cycle` narrowed — 15/17 sites work with real values; the 2 user-owned `IterableOwned` sites are the local-generic-elaboration gap (R2 sibling), same failure surface on clean master | `test/itertools/test_cycle.mojo` |
| `getsize` — the 2 remaining defects of the "Landed 2026-10-20" section above (cross-stdlib `stat` + the out-param result model) | `test/os/path/test_getsize.mojo` |

Of the four List-container members of the first population
(`test_peek`/`test_enumerate`/`test_take`/`test_drop`), the lift removed all
four from the dict with value-ladder evidence (the REMOVED-2026-10-21 comment
in `compile_stdlib.py` carries the per-file counts). Later the same day the
2 home modules and `test_count` lifted (the "## 2026-10-21" section below),
leaving the 9 that remain exercise the shapes the lift did not take on —
multi-container factories (`chain`, `zip`, `product`), `peekable`'s
overload-ambiguous call site, `map`/`drop_while`/`take_while` and the
string-iterator family — and their reason strings say exactly which half is
missing, per file.

### Acceptance (unchanged, still unmet)

The census must reach **0 sites** and the declared `EXPECTED_FAILURES` must
empty. The measured remainder is the 14 above; none of them is a stub or a
silent green — every one of the 14 fails a real `gcc -c`/link with a named
reason, which is the state this dict exists to declare.

## 2026-10-21: one live false green of this class is resolved; declared-red
is 11

### std/iter's `next_12_IteratorType_5_Int64` — resolved

While measuring the definition-site generic-method fix (R1 doc,
"2026-10-21"), clean master's `std/iter/__init__.mojo` C was found to carry
4 calls to a mangled `next_12_IteratorType_5_Int64` with 1 extern
declaration and **0 definitions anywhere** — a live member of this doc's
"imported generic, never elaborated, calls nothing that defines" class,
green on the `-fsyntax-only` gate and invisible to everything else (nothing
links the `test/`/`std/` tree in this pipeline). The final fix (R1 doc,
item 1) resolves it with two cooperating pieces: a FALSE-GREEN GUARD in
`emit_resolve._elaborate_generic_call`'s inferred branch refuses the
inference when the argument is a `self`-field whose annotation names an
unbound type parameter of the enclosing struct (the erased
`Self.InnerIteratorType` field erases to `int64_t`, so inference binds the
callee's `Iterator`-bounded parameter to that scalar — a placeholder no
monomorphization can define) AND the callee's own template treats that
parameter as a container (`<param>.Element` / `.IteratorType` /
`.IteratorOwnedType` access — `next[IteratorType: Iterator] ->
IteratorType.Element` matches); the refusal then lands the method as
prototype-only through the same per-method TRANSACTIONAL FALLBACK in
module_gen that lifts the two home modules — the prototype and the
`_mojo_getattr` arm remain. Measured before/after in the generated C: all 4
calls gone (the 4 methods — `_Enumerate.__next__`, `_MapIterator.__next__`,
`_PeekableIterator.__next__`, `_PeekableIterator.peek` — are prototype-only
with diagnostic comments), and the removed-definition A/B check on the
final tree reports 0 undefined-and-referenced symbols.

### test_getsize — still blocked (the two 2026-10-20 defects, unchanged)

Fresh measurement (2026-10-21, fresh process): the monomorphized TU
`getsize_8_PathLike_6_String` still fails real `gcc -c` —
`error: implicit declaration of function 'stat'` (the spliced source's line
16): the CROSS-STDLIB `stat[PathLike: stdPathLike]` (std/os/fstat.mojo) is
not transitively elaborated with `PathLike=String`, and a prototype alone
would not fix the result model either (`int64_t` reinterpreted as `void *`
with a dynamic `st_size` getattr, versus the real `int stat(const char *,
struct stat *)` out-param filling a caller-owned struct). Same surface as
2026-10-20.

### test_cycle — the 2 user-owned sites unchanged

`test_cycle_owned` still refuses with the receiver typed `int64_t`
(measured 2026-10-21): the user-defined `IterableOwned` struct's local
comptime-parametrized materialization is non-mangled and its local-fn
return boxes — the local-generic-elaboration gap, same surface as clean
master. 15/17 `cycle(...)` sites work with real values (R1 doc).

### Where the declared red stands

**11** (was 14): the 2 home modules + `test_count` lifted with the evidence
in the R1 doc's "2026-10-21" section; the other 8 each carry a per-file
measured reason (emitting function, measured receiver type, root-cause
shape — the shape table lives in the R1 doc). This doc's own census
(`tools/elab_fail_census.py` decline counts) is a different measurement: it
counts the elaborator's INSTANTIATION declines, and the two lifts act on
the call-site side — the census numbers are what they were at the end
of the 2026-10-20 session (not re-run in this one).

## 2026-10-21 (further): declared-red 11 -> 9; this session's A/B removes
no site of this class; the two remaining members re-measured

### The declared-red reduction (the R1 doc carries the evidence)

The R1 doc's "2026-10-21 (further)" section lifted the thin-FUNCTION type
argument (`test_take_while` 14/14, `test_drop_while` 14/14 ladder), the set-
literal container (`test_set` out of the sweep — floor-green; the full-file
ladder stays red on five INDEPENDENT measured gap families A-F, none of them
of either doc's class), and the map mechanism (`test_map` 2/2 scratch ladder
with real values; the file stays red on ONE cross-module test_utils struct).
Declared red: **11 -> 8** in the sweep (602 PASSED / 8 FAILED, 0 unexpected,
0 stale, EXIT 0); 9 entries counted including the floor-green `test_set`
whose ladder-level red is documented in the R1 doc. Interpreter note:
the session's first measurements ran under PATH 3.15 (homebrew); a probe of
every changed codegen path proved 3.15 and the mandated /opt/local 3.14.8
emit byte-identical C (the CAS is keyed on inputs only), so the A/B below
stands, and all gates (ladders, sweep, warn set, bucket 53/53 rc 0,
ps-verified) were remeasured under 3.14.8 — see the R1 doc's interpreter-
verification section.

### This session's full-tree A/B removes NO site of this class

The fresh-process A/B vs 5179db5a (610 files) is 603 identical / E->C 3 /
E->E 1 / C->E 0 / C->C 3 — and the one C->C file that touches a
this-session mechanism in a green file (`test/builtin/test_bool.mojo`,
`map[gt0](l)` in `test_all` / `test_any`) did NOT remove an undefined-extern
site: the baseline C boxes the `map[gt0](l)` call to `int64_t` (verified in
the before-C — the R1 doc's false-green guard removed std/iter's 4
`next_12_IteratorType_5_Int64` calls at 5179db5a, and map's baseline
lowering is the erased scalar, not a mangled call with 0 definitions).
Removed-symbol cross-reference on the 3 changed files: **0** undefined-and-
referenced symbols.

### test_getsize — still blocked (the two 2026-10-20 defects, re-measured
today, unchanged surface)

Fresh measurement (2026-10-21 (further), fresh process): the monomorphized TU
`getsize_8_PathLike_6_String` still fails real `gcc -c` — attempt 1 of 3:
`error: implicit declaration of function 'stat'` at the spliced line 16
(`return stat(path.__fspath__()).st_size`): the CROSS-STDLIB `stat[PathLike:
stdPathLike]` (std/os/fstat.mojo) is not transitively elaborated with
`PathLike=String`, and a prototype alone would not fix the result model
either (int64 reinterpreted as `void *` with a dynamic `st_size` getattr,
versus the real `int stat(const char *, struct stat *)` out-param filling a
caller-owned struct). Same surface as 2026-10-20/21.

### test_cycle — the 2 user-owned sites (remeasured; the refusal moved up
to the seed, the gap is the same)

Remeasured 2026-10-21 (further): the 2 sites (`cycle(_owned3(1, 2, 3))` /
`cycle(_owned1(42))`) are now refused at the SEED's container gate (x2
measured notes: `cycle(...): container argument is not a statically
resolvable local List / range / nested factory`) — the container is a LOCAL
FUNCTION CALL returning a USER-DEFINED `IterableOwned` struct
(`_CopyableOwned[3]`, in-TU `_CopyableOwnedIter[3]` over `Array[Int, 3]`) —
and the boxed `it` local then hits next()'s hard refusal (receiver `int64_t`,
in `test_cycle_owned`, unchanged from 5179db5a). The gap is the
local-generic-elaboration sibling (R1 doc), not an elaborated-callee-
undefined site: no mangled call with 0 definitions is emitted for these 2
sites (the call never seeds a record at all). 15/17 sites work with real
values.

### Where this doc's own census stands

The elaborator-decline census (`tools/elab_fail_census.py`) counts a
DIFFERENT population (instantiation declines); the 3 E->C lifts and the 3
C->C deltas above act on the call-site side. The census is not re-run in
this session (same treatment as the 2026-10-21 section above it); the
declared-red population it complements is the 9 entries named above.

## 2026-10-22 (further, part 4): remeasured — the declared-red dict is
8 -> 5; this doc's own entries are unchanged, the product refusal
relocated to the owned site

The part-4 campaign lifts 3 of the 8 declared-red entries — all three from
the R1 doc's census (chain/zip via the out-res factory subpath,
test_python_object via the pyobj-list arm; see the R1 doc's
"2026-10-22 (further, part 4)" section for the measured mechanisms and the
full gate record: sweep 605/5, A/B C->E 0, ladders with parity). From this
doc's perspective the measured surface is unchanged, plus one relocation:

- `test/os/path/test_getsize.mojo` — still fails real `gcc -c` on the
  monomorphized `getsize_8_PathLike_6_String` TU (implicit declaration of
  `stat`, 3 attempts) — same surface as 2026-10-21 (further); the
  cross-stdlib `stat[PathLike]` transitive elaboration and the out-param
  result model are untouched by the part-4 changeset (A/B E->E, no
  message change).
- `test/itertools/test_cycle.mojo`'s 2 user-owned sites — still refused at
  the seed's container gate (a local fn call returning a user-defined
  `IterableOwned`, the local-generic-elaboration sibling); A/B E->E, no
  message change; 15/17 sites still work with real values.
- `test/itertools/test_product.mojo` (listed in this doc's family table for
  the shared R2 local-fn-call family) — the refusal RELOCATED, measured
  2026-10-22: the part-4 two-container factory seed lifts the NON-OWNED
  shapes (`test_product2`/`_param`/`_unequal`/`_copies` — products of two
  List locals — now lower; the module compiles through them), and the
  remaining site is `test_product2_owned`: `product(_owned3(1, 2, 3),
  _owned2(10, 20))` — the container arguments are LOCAL FUNCTION CALLS
  returning owned values, the same family as the cycle sites above. The
  seed cannot file records for them, the boxed `it` stays `int64_t`, and
  `next(it)` hits the hard refusal (measured: receiver `int64_t`, in
  function `test_product2_owned`).

The elaborator-decline census is not re-run (same treatment as the
2026-10-21 sections above). The declared-red population it complements is
now the 5 entries named in the R1 doc's 2026-10-22 table (plus the
floor-green `test_set`, out of the sweep).

## 2026-10-22 (part 5): re-measured — test_getsize unchanged, the closure
mapped in full; the declared-red population is 5 -> 2

The part-5 campaign (struct-fn container kind + struct-literal-element
subpath; see the R1 doc's "2026-10-22 (part 5)" section for the measured
mechanisms, the ladder evidence, and the full gate record: sweep 608/2,
A/B both shapes C->E 0, warn set 19/294 identical, no-new-casts 19
unchanged) lifts 3 of the 5 declared-red entries (test_map, test_cycle,
test_product — all from the R1 doc's census). From this doc's
perspective the measured surface is unchanged, plus the closure mapping:

- `test/os/path/test_getsize.mojo` — RE-MEASURED 2026-10-22, unchanged:
  codegen fails (`gcc -c failed for the monomorphized
  getsize_8_PathLike_6_String (exit 1, 3 attempts)`; `implicit
  declaration of function 'stat'`); the emitted body is still
  `stat (path)` + `_mojo_dispatch_getattr(..., "st_size")` — the result
  modelled as a word, `.st_size` fetched dynamically. The factory changes
  do not touch this file (no dependent-return factory call; the failure
  is in the monomorphized module compile — A/B ERROR->ERROR, no message
  change). This session mapped the closure in full, and it is a C-ABI-FFI
  sub-campaign, not a next-fix: std/os/fstat.mojo's `stat[PathLike]`
  selects the platform arm with a comptime branch
  (`CompilationTarget.is_macos()`); `_stat_macos` is
  `external_call["stat", Int32](path.as_c_string_span(),
  Pointer(to=stat))` — an FFI call with an OUT PARAMETER filling the
  `_c_stat` C-ABI struct (17 mixed-width fields incl. `_CTimeSpec` +
  `Array[Int64, 2]`), which the in-TU materializer does not lay out in
  C-ABI order; the result travels through `_to_stat_result()` (18-field
  projection + `Int(...)` casts) and the 18-argument keyword constructor
  of `stat_result`. Every link of that chain (C-ABI struct layout,
  external_call out-struct, `as_c_string_span`, the comptime target
  branch, the `Error("unable to stat '", path, "'")` raise) is an
  unmeasured mechanism. The `#include <sys/stat.h>` route stays closed:
  every TU includes fire_runtime.h and std/os/_macos.mojo declares `stat`
  itself via `external_call["stat", Int32]` (conflicting types).
- `test/collections/string/test_iterators.mojo` (listed in this doc's
  family table for the shared method-call dependent-return family) —
  RE-MEASURED 2026-10-22, unchanged: `s.bytes()` on a local `StringSlice`
  lowers to the zero stub `_t2 = 0; /* TODO: char*.bytes */` and
  `next(bytes)` hits the hard refusal (A/B ERROR->ERROR, no message
  change). The part-5 struct-fn kind does not reach it: its one
  factory-shaped site is a METHOD call, and its closure (the
  StringSpan[origin] method family, ~100 methods, + Span/_SpanIter
  nesting + alias/origin inference) is Part-6 scale.

The elaborator-decline census is not re-run (same treatment as the
2026-10-21 sections above). The declared-red population it complements is
now the 2 entries above (plus the floor-green `test_set`, out of the
sweep, and the floor-green `test_product`, ladder-red on the 4 measured
families A-D in the R1 doc).

## 2026-10-22 (part 6): re-measured — test_getsize and test_iterators
unchanged; gap (C) closed in the R1 doc (ladder-red 4 -> 3)

The part-6 campaign's first target was the R1 doc's gap (C) — the
tagged-Optional field side-band + the dead-guard fold in
`monomorphize_source` (see the R1 doc's "2026-10-22 (part 6)" section for
the measured mechanism, the GIMPLE strictness rule, the ladder evidence
(`test_product_bounds` FAIL -> PASS, full 6,5,4,3,2,1,0 sequence, zero
regressions), and the full gate record: sweep 608/2 in both trees, A/B
C-hash 610 files with EXACTLY 3 C->C changes (test_once, test_peek,
test_product — the measured blast radius), warn set 19/294 byte-identical,
no-new-casts 19 unchanged). From this doc's perspective the declared-red
surface is UNCHANGED, re-measured on the part-6 sweep:

- `test/os/path/test_getsize.mojo` — RE-MEASURED 2026-10-22 (part 6),
  unchanged: same failure (`gcc -c failed for the monomorphized
  getsize_8_PathLike_6_String (exit 1, 3 attempts)`; `implicit
  declaration of function 'stat'`), same emitted body (`stat (path)` +
  `_mojo_dispatch_getattr(..., "st_size")`). The family-C side-band does
  not touch this file (no in-TU `Optional[...]` field; A/B ERROR->ERROR,
  no message change). The `#include <sys/stat.h>` route stays closed
  (conflicting types with fire_runtime.h / _macos.mojo's own
  `external_call["stat", Int32]` declaration); the fix is the C-ABI-FFI
  sub-campaign mapped in the part-5 section above, plus the
  NamedTemporaryFile/`with`/`.write`/`.byte_length` closure the test
  needs.
- `test/collections/string/test_iterators.mojo` — RE-MEASURED 2026-10-22
  (part 6), unchanged: `s.bytes()` still lowers to the zero stub,
  `next(bytes)` still hits the hard refusal (A/B ERROR->ERROR, no message
  change; the method-call dependent-return closure is the next sub-
  campaign).

The declared-red population is still these 2 entries. `test_product`
remains floor-green and ladder-red, now on the 3 measured families
A/B/D (family C closed by this section's mechanism — the staged next
mechanisms for A/B/D are in the R1 doc's part-6 section, and the value-
level Optional representation for the bounds-guard shape is the staged
next mechanism for any non-list iterator arg to the product family).

## 2026-10-23 (part 6, family D piece 1): re-measured — test_getsize and
test_iterators unchanged; the copies-family template-symbol hazard is
removed (R1 doc)

The part-6 campaign's second target was the R1 doc's gap (D) piece 1 —
the DIRECT wrapper constructor subpath in `elab_intu` (the bare
`_ProductN(local-struct args)` spelling the copies tests use), which
removes the old-path `extern int64_t _Product2 (...);` template symbol
the -fsyntax-only gate cannot see, plus the trait-default `bounds`
synthesis on the local inner struct (see the R1 doc's "2026-10-23 (part
6, family D piece 1)" section for the measured mechanism, the ladder
evidence — hazard gone from the object, TU links, 12 ladder-red tests at
the identical first assert, zero PASS->FAIL — and the full gate record:
sweep 608/2 in both trees, A/B C-hash 610 files with EXACTLY 1 C->C
change, `test/itertools/test_product.mojo` (the intended file), warn set
19/294 byte-identical, no-new-casts 19 unchanged). From this doc's
perspective the declared-red surface is UNCHANGED, re-measured on the
D1 sweep. (Gate note: the D1 bucket's first run failed the self-host
census check `every_ast_mutation_site_invalidates_the_walk_memo` on the
new `sd.methods.append` site in elab_intu — fixed with
`_walk_ast_invalidate(sd)`, zero generated-C change, gimple job green;
see the R1 doc's 2026-10-23 gate record.)

- `test/os/path/test_getsize.mojo` — RE-MEASURED 2026-10-23 (part 6,
  family D piece 1), unchanged: same failure (`gcc -c failed for the
  monomorphized getsize_8_PathLike_6_String (exit 1, 3 attempts)`;
  `implicit declaration of function 'stat'`), same emitted body. The
  direct-ctor subpath does not touch this file (no bare constructor call
  to an imported generic struct — its `stat(...)` is an FFI call; A/B
  ERROR->ERROR, no message change). The `#include <sys/stat.h>` route
  stays closed; the fix is the C-ABI-FFI sub-campaign mapped in the
  part-5 section above.
- `test/collections/string/test_iterators.mojo` — RE-MEASURED 2026-10-23
  (part 6, family D piece 1), unchanged: `s.bytes()` still lowers to the
  zero stub, `next(bytes)` still hits the hard refusal (A/B ERROR->ERROR,
  no message change; the method-call dependent-return closure is the
  next sub-campaign).

The declared-red population is still these 2 entries. `test_product`
remains floor-green and ladder-red, now on 3 measured families A/B/D
with D's LINK HAZARD removed (the copies family's remaining red is
value-level — the staged D2: test_utils inlining + constructor-based
field copy, in the R1 doc's 2026-10-23 section; the element_copies
false green it documents is the same D2's second half).

## 2026-10-23 (part 6, family D piece 2): re-measured — the two
declared-reds unchanged; the fillable-default constructor hazard is
taken over exactly where strict inference refuses

The R1 doc's "2026-10-23 (part 6, family D piece 2)" section carries
the measured mechanism (the fill_defaults inference + the vote-rule
fix + the kwarg-bracket placeholder, the ref-scalar parameter ABI, the
`.value()` identity, the constructor field copy, the E1/E2 element
inference + pointer-slot unpack, and the strict-refusal gate), the
ladder evidence (idx 2 FAIL→PASS with real values, the other 16 tests
byte-identical status, zero PASS→FAIL; idx 8/13 non-vacuous with the
named Family-A remainder), and the full gate record. From this doc's
perspective:

- `test/os/path/test_getsize.mojo` — RE-MEASURED 2026-10-23 (part 6,
  family D piece 2), unchanged: same failure (`gcc -c failed for the
  monomorphized getsize_8_PathLike_6_String (exit 1, 3 attempts)`;
  `implicit declaration of function 'stat'`), same emitted body (A/B
  ERROR->ERROR, byte-identical message). The D2 constructor subpath does
  not touch this file (no bare constructor call to an imported generic
  struct; its `stat(...)` is the C-ABI-FFI shape the part-5 section
  maps as a sub-campaign).
- `test/collections/string/test_iterators.mojo` — RE-MEASURED 2026-10-23
  (part 6, family D piece 2), unchanged: `s.bytes()` still lowers to the
  zero stub, `next(bytes)` still hits the hard refusal (A/B ERROR->ERROR,
  byte-identical message; the method-call dependent-return closure is the
  next sub-campaign).

The zero-stub hazard surface this doc tracks: the D2 piece removes the
copies family's template-symbol hazard (D1) AND takes over the BARE-
LITERAL constructor calls whose type arguments the `.o` route's strict
inference refuses — measured split in the R1 doc: `CopyCounter(1)`
strict refuses (the fillable `trivial_copy` comptime value parameter) so
the in-TU materialization owns it; `Interval(1, 10)` / `Optional(123)` /
`ArcPointer(4)` / `Repr(42)` strict answers, so the `.o` route owns
them (the strict-refusal gate in `_infer_struct_args` is the boundary;
the full-sweep regression it fixed is documented there). The A/B C-hash
(population-wide, 610 files, fresh per-file process both trees): 0
status changes, 23 C->C, every one classified in the R1 doc's gate
record (16 files the `.value()` identity, 6 files the in-TU counter/
random-struct materialization, test_product the D2 core), 0 E-message
changes, 0 removed definitions, zero dangling references. `test_product`
remains floor-green and ladder-red: the copies family is VALUE-GREEN
(idx 2), the element_copies family (idx 8/13) is now NON-VACUOUS and
red on the measured Family-A comptime-alias remainder, and families
A/B hold the other reds (R1 doc).

## 2026-10-23 (part 6, family A): re-measured — test_getsize and
test_iterators unchanged; the nested-product zero-stub population is
materialized in-TU (78 definitions, 0 removed, 0 dangling)

- `test/os/path/test_getsize.mojo` and `test/collections/string/
  test_iterators.mojo`: re-measured through the 610-file A/B — their
  ERROR signatures are BYTE-IDENTICAL to the D2 master, so both
  `EXPECTED_FAILURES` entries stay accurate without a refresh. The
  closure maps hold: `getsize`'s `stat(...)` C-ABI path (`_c_stat` 17-
  field struct, `external_call["stat", Int32]`, the 18-field projection)
  and test_iterators' `s.bytes()` dependent-return factory +
  `StringSpan[origin]` method family remain the next items.
- The zero-stub hazard surface this doc tracks, the nested-product
  half: at D2 the comptime aliases (`Self._Product2Type` /
  `Self._OuterProduct2Type`, `itertools.mojo`) erased to words, so the
  spliced `_Product3`/`_Product4` `__init__` constructor calls became
  `int64_t.<alias>() stubbed` — a stub emits NO call, so the hazard was
  invisible while the whole nested chain was dead code (the ladder's
  idx 8/13 crashed on the NULL tuple the stubbed `__next__` returned).
  Family A evaluates the aliases to the named instantiations' mangled
  names (R1 doc, the mechanism) and materializes them in-TU in the same
  closure: 13 new nested `_Product2` instantiations (CC / Int / TCI /
  owned / borrowed-ListIter element families, including the nested-
  mention shapes `_Product2[A, _Product2[B, C]]` and `_Product2[A,
  _Product3[B, C, D]]`) with 78 added DEFINITIONS — every
  `P2_bc___next__` / `___init__` / `bounds` the spliced wrappers now
  call is defined in the same TU. Removed-symbol check: 0 removed
  definitions, zero dangling references; the 610-file A/B confirms no
  other TU's surface changed (0 status changes, 1 C→C = test_product,
  0 E-message changes).
- Result: the ladder's element_copies / copies / product3 / product4
  families go GREEN with their pinned copy counts (R1 doc, the
  measurements); the remaining reds on the product ladder are the
  comptime-FOR-parameter family (idx 4/10/16, trip_count 0 — family B),
  byte-identical to the D2 signatures.

## 2026-10-23 (part 6, family B): re-measured — the two declared reds
unchanged; the product ladder's comptime-for family is no longer a
declared-red population (17/17)

- `test/os/path/test_getsize.mojo` and `test/collections/string/
  test_iterators.mojo`: re-measured through the 610-file A/B — their
  ERROR signatures are BYTE-IDENTICAL to the Family-A master (fresh
  worktree at 9cf074f8), so both `EXPECTED_FAILURES` entries stay
  accurate without a refresh. The closure maps hold: `getsize`'s
  `stat(...)` C-ABI path and test_iterators' `s.bytes()`
  dependent-return factory + `StringSpan[origin]` method family remain
  the next items.
- The product ladder's comptime-for family (idx 4/10/16) is CLOSED:
  family B unrolls `comptime for ... in product(range(...), ...)` at
  codegen time (R1 doc, the mechanism), so the three tests assert on
  the real accumulated trip counts (4/8/16, negative-control-verified)
  and the ladder is 17/17 — no product-ladder reds remain to declare.
  A/B: 0 status changes, exactly 1 C→C (test_product — the only file
  with the pattern; the 14 non-param functions byte-identical after
  per-TU `_slit_` normalization, 0 removed/added definitions), 0
  E-message changes.

## 2026-10-23 (part 6, family S): test_iterators closed (sister doc);
test_getsize re-measured — unchanged, and its entry stays accurate

- `test/collections/string/test_iterators.mojo`: CLOSED by this piece —
  sweep ERROR → C, 7/7 ladder with real values + negative control,
  entry REMOVED from `EXPECTED_FAILURES` (measured-removal comment in
  compile_stdlib.py). The mechanism — the four hand-built in-TU
  string-iterator structs, the char*-intrinsic method subset, the
  comptime-string provenance machinery — is documented in the sister
  doc `CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md`
  (family-S section); this doc's share of the evidence is the A/B:
  the 610-file C-hash diff shows the file's ERROR signature gone
  (the lone status change, ERROR→C) and its `next()` refusal no
  longer in the E-message column (0 E-message changes tree-wide —
  the only remaining E is test_getsize below, byte-identical).
- `test/os/path/test_getsize.mojo`: RE-MEASURED, unchanged. The whole
  family-S piece (in-TU siter structs, comptime string reads,
  as_bytes word-boxing, the String() ctor actuals record, the
  provenance gate) does not touch this file's failure: the sweep
  reports the same codegen error (`gcc -c failed for the
  monomorphized getsize_8_PathLike_6_String`; `implicit declaration
  of function 'stat'`), and the A/B TSV diff shows its E-message
  byte-identical (0 E-message changes across all 610). The closure
  map holds verbatim: `stat[PathLike]`'s comptime
  `CompilationTarget.is_macos()` platform branch, `_stat_macos`'s
  `external_call["stat", Int32](path.as_c_string_span(),
  Pointer(to=stat))` with the OUT parameter filling the 17-field
  `_c_stat` C-ABI struct (incl. `_CTimeSpec` + `Array[Int64, 2]`)
  that the in-TU materializer does not lay out in C-ABI order, the
  18-field `_to_stat_result()` projection + Int casts, and the 18-
  argument keyword constructor of `stat_result`. `#include
  <sys/stat.h>` stays closed: conflicting types with fire_runtime.h
  and _macos.mojo:137. The `EXPECTED_FAILURES` entry carries the
  2026-10-23 (part 6, family S) re-measurement note.
- Sweep state this piece: **608/2 → 609/1** — the only remaining
  declared red is test_getsize itself; the next piece is its
  C-ABI-FFI sub-campaign (bar: the mangled stat path defined in-TU +
  a real run returning the right st_size for a real scratch file).

## 2026-10-23 (part 6, closing piece): test_getsize CLOSED — the
C-ABI-FFI sub-campaign lands, the 610-file sweep is 610/0, and the
2026-10-03 false-PASS bar is met with real values

### The two defects, closed in the emitted C (measured before/after)

Pre-fix, the monomorphized `getsize_8_PathLike_6_String` TU's body was
`_t2 = stat (path);` (bare `stat`, no prototype — `implicit declaration
of function 'stat'`, a C23 hard error that killed `gcc -c` on 3
attempts) whose result was modelled as a boxed `int64_t` word,
reinterpreted `(void *)`, with `.st_size` fetched by dynamic
`_mojo_dispatch_getattr (_t3, "st_size")`. Post-fix, the same body is:

    before:  _t2 = stat (path);
             _t3 = (void *)_t2;
             _t4 = _mojo_dispatch_getattr (_t3, _t5);  /* "st_size" */
             return _t4;
    after:   _t2 = stat_8_PathLike_6_String (path);
             _t3 = _t2->st_size;
             return _t3;

`stat_8_PathLike_6_String` (the campaign mangle of `stat[PathLike]`
with `PathLike=String`, same scheme as the caller's own
`getsize_8_PathLike_6_String`) is a `static` in-TU materialization
emitted once per TU by `emit_calls._CABI_STAT_BLOCK` (driven by the
gated branch at the tail of `_lower_call` + `module_gen`'s
`_needs_cabi_stat`). Its body is the REAL measured chain
(`std/os/path/path.mojo:382` → `std/os/fstat.mojo:179` comptime-if
macos arm → `std/os/_macos.mojo:136` → the `_to_stat_result` projection
at `_macos.mojo:114`): a zero-filled C-ABI `gs_cstat` (the `_c_stat()`
default-init, measured `memset 0`), the REAL 2-arg system call
`extern int stat (const char *, gs_cstat *)` with the OUT parameter
filling the caller-owned struct (no 1-arg prototype), `err == -1` →
`Error("unable to stat '<path>'")` via `mojo_str_cat` +
`mojo_exc_type_set (471634805)` (the crc32 `Error` tag) +
`mojo_raise`, and the 15-field projection (11 `Int`-widening casts +
the 4 `_CTimeSpec` word pairs) into the in-TU `gs_stat_result` — whose
typedef the TU's own struct-emit pass spells from the branch's
`struct_field_types` registration, the same registration that makes
the chained `.st_size` resolve as a direct `->` field read instead of
the dynamic getattr.

The gate is narrow by construction: a bare `stat(<one char* arg>)`
call in a TU with NO import and NO local binding for `stat` — the
isolated monomorphized TU only. `std/os/path/path.mojo` IMPORTS
`stat` (from `..fstat`) and `std/os/fstat.mojo` locally BINDS it, so
neither main-pipeline TU can fire the branch; the 610-file A/B
confirms exactly one file's C changed (see below). The
`#include <sys/stat.h>` route stays CLOSED per the decision
(conflicting types with fire_runtime.h and the `_macos` TU's own
`external_call` declaration of `stat` — the `<time.h>`/`clock_gettime`
precedent); the C-ABI layout is spelled in codegen instead.

### The C-ABI layout: measured on this platform, validated twice

The SDK header's `struct stat` (Darwin 27, arm64) measures as 144
bytes, align 8, with offsets 0/4/6/8/16/20/24/32/48/64/80/96/104/112/
116/120/124/128 — note the packed `dev`/`mode`/`nlink`/`ino` head
(u32/u16/u16/u64) is THIS platform's measured ABI, not the
x86_64-era layout the earlier closure map assumed. The codegen
spelling was validated before landing, both ways: (1) an offsetof
probe compiled with the same gcc compares the spelled struct against
the header's — all 18 fields + sizeof + align matching; (2) a real
run of the EXACT block shape (own-spelled struct, own 2-arg
prototype, system `stat` call) against a real 12345-byte scratch
file returned `size=12345 ino=94996773 mode=100644 uid=505
dev=16777230` — byte-identical to the system-header reference run.

A latent layout bug was caught and fixed by the real run before
landing: the first block version embedded the TU's `gs_ctimespec`
typedef in `gs_cstat` — which the struct-emit pass spells with the
campaign's 8-byte type-tag header (24 bytes) — shifting `st_size`
from its real ABI offset 96 to 128, so the ladder's 15-byte file
answered 0. The timespecs are inlined 16-byte C-ABI structs and the
projection copies them word by word (C forbids assigning between
distinct struct types); documented in `_CABI_STAT_BLOCK`'s own
comment.

### Ladder: the 2026-10-03 bar, met with real values

- `nm` on the monomorphized object: the instantiation's stat path is
  DEFINED in the module's own object — `t _stat_8_PathLike_6_String`
  (static — one definition per TU is all the link needs, and static
  keeps two TUs that ever both materialize `stat` from colliding) and
  `T _getsize_8_PathLike_6_String` (the caller's entry); the only
  undefined stat-path symbol is the SYSTEM `stat`, which the real
  link resolves from libSystem.
- The real link (test driver + the monomorphized object +
  `build/libmojostdlib.arm64.dylib`) leaves no undefined symbol for
  the stat path, and the binary runs.
- REAL RUN against real scratch files of known size (created in the
  scratch dir, cleaned up after): 0/15/999 bytes → `got=0/15/999`
  (LADDER PASS rc=0). This is the false-PASS cautionary tale's
  answer: the vacuous 0-stub shape (both sides answering 0) would
  have passed a syntax-only gate; the 15/999 cases cannot.
- Negative control: patching a COPY of the C's `st_size` projection
  `+1` rebuilds to `got=1/16/1000` (LADDER FAIL rc=1) — the values
  flow from the real `stat()`, not a stub.

### Field counts, corrected (measured against the stdlib source)

The family-S section's closure map carried "17-field `_c_stat`" and
"18-field `_to_stat_result()` projection / 18-argument keyword
constructor". Measured this piece: `_c_stat`
(`std/os/_macos.mojo:33`) has **18** Mojo fields;
`stat_result` (`std/os/fstat.mojo:44`) has **15** fields (11 `Int` +
4 `_CTimeSpec`), and the 15-arg keyword constructor — the projection
copies exactly those 15 (11 casts + 4 timespecs). The earlier "18"
conflated the two.

### Battery

- Sweep: current tree **610/0** (0 expected, 0 unexpected, rc=0; the
  stale-entry hygiene gate fired once pre-removal, clean after);
  fresh master worktree at 1057cd70: **609/1** (test_getsize, the
  baseline). The campaign arc lands: 592/18 → … → 608/2 → 609/1 →
  **610/0** — the 610-file stdlib compiles, end to end.
- A/B (610 files, both trees, fresh process per file): exactly ONE
  changed file — `test/os/path/test_getsize.mojo`, ERROR → C (the
  file whose isolated TU this piece fixed; its own C now exists).
  Zero C→E, zero unclassified. Removed-symbol hazard check: the
  master's file never produced an object (its compile failed), so it
  contributed no symbols to remove, and the other 609 files' C is
  byte-identical — no TU's symbol surface changed elsewhere.
- Warn set: 19 files / 294 total, byte-identical from both
  full-sweep logs. no-new-casts: 19 (baseline). formal_doc_index:
  133 documents, block current.
- `EXPECTED_FAILURES`: the final entry REMOVED with the
  measured-removal comment in compile_stdlib.py — the dict is now
  empty and the hygiene gate passes on a clean re-sweep.

### Staged remainder (pre-existing main-pipeline class, not this
piece's)

The full test BINARY's wrapper still cannot link, for reasons that
pre-date and do not touch the stat chain: the test's own
`NamedTemporaryFile(delete=False)` call lowers to a zero-arg
`NamedTemporaryFile ()` whose bare ctor symbol no object defines
(the struct-ctor qualifier-mismatch class named in
`monomorphize.build`'s docstring — the home TU defines
`std_tempfile_tempfile_NamedTemporaryFile___init__`, not the bare
name), and `std_testing___init___assert_equal` / `main` the same.
Measured: the link's undefined list is exactly those plus
runtime/libc symbols, none stat-related. That closure is a separate
sub-campaign; the stat chain itself — the subject of this doc — is
closed.

### Status

CLOSED. The headline figure in the first section (96 sites / 51
names / 60 files, later the 1938/851/381 total) is the class; this
piece closes its last live member: the 610-file sweep is 610/0 with
every remaining execution-level gap either closed with real-value
ladders (this doc's and the sister doc's families) or declared and
measured in the staged remainders named above.
