# An imported generic is never elaborated, so the generated C calls a symbol
# nothing defines

## Status

OPEN, and the headline number in this doc was wrong by 4x. Measured and
corrected 2026-10-01 (second session): `tools/undef_import_census.py` reported
"424 sites / 157 names / 194 files"; it was counting the codegen's own guarded
forward declaration for every imported name, called or not. The real figure is
**96 sites / 51 names / 60 files** (108 before that session's fixes). See "What
was wrong with the measurement" below — it is the most important section here.

**2026-10-03: `monomorphize.mangle` is injective — the blocker the previous
session named is gone. Nothing else moved, and that is the honest report.**

### Landed 2026-10-03: `mangle` is a FUNCTION of the instantiation

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