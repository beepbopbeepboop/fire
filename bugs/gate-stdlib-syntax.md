# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `work/bug-codegen-nested-bracket-generic-call` (task `bug-codegen-nested-bracket-generic-call`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/bug-codegen-nested-bracket-generic-call`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `std/simd.mojo`
- `test/builtin/test_simd.mojo`
- `test/builtin/test_sort_issue_1018.mojo`
- `test/hashlib/test_ahash.mojo`
- `test/hashlib/test_fnv1a.mojo`
- `test/math/test_exp.mojo`
- `test/math/test_math.mojo`

## Status 2026-11-13 — master is green; the red is the held branch's value-argument rendering

**This is not a master red.** Measured on this tree through the stdlib-syntax job's own per-file
unit — `compile_stdlib.transpile_file`, which is exactly what `compile_stdlib.py` runs for each file
(same `linkable=False` codegen, same `gcc -fgimple -I runtime -fsyntax-only
-D__MOJO_STDLIB_MODE__`):

    PASS std/simd.mojo
    PASS test/builtin/test_simd.mojo
    PASS test/builtin/test_sort_issue_1018.mojo
    PASS test/hashlib/test_ahash.mojo
    PASS test/hashlib/test_fnv1a.mojo
    PASS test/math/test_exp.mojo
    PASS test/math/test_math.mojo

The branch the integrator's gate round named was retired and held (merge `1cdb1806b`, not on
master), so none of its changes are in this tree. Reproduced on that branch's tree
(`039cf6198 = 1cdb1806b`'s tree): all seven FAIL. A `git archive` of each commit through the same
per-file unit bisects the red to one commit:

| tree | result |
|---|---|
| `364122631` (elaborate bracketed calls nested in an instantiation) | 7/7 PASS |
| `4a0675349` (fold dot-relative DType predicates in `comptime if`) | 7/7 PASS |
| `6158c593e` (render string/dot bracket args) | 6 FAIL (all but `std/simd`) |
| `733e97b60` (test only) | 7/7 PASS |
| `039cf6198` (the branch merged with master) | 7 FAIL (`std/simd` joins) |

**Root cause of the red:** `6158c593e` renders a `StringLiteral`/`DottedLiteral` bracket argument,
so calls such as `assert_fill_factor["AR", hasher0](...)`, `_sort_test[.int8, "int8"](...)` and
`f[.float32](...)` are now ELABORATED. Each one monomorphizes the callee into an isolated
translation unit, and these bodies need four things the isolated TU does not have. Classes 1 is
fixed here; 2-4 are the remaining work, with the exact failure measured for each.

1. **A `where` clause over a dot-relative dtype spelling.** `check_where_clauses` falls back to
   `elaborate._is_float_dtype`, which recognized only `Float32` and `DType.float32`; `.float32`
   (the text `_type_expr_to_ann` renders for a `DottedLiteral`) therefore answered "not a float"
   and the call was rejected with
   `type '.float32' does not satisfy constraint 'dtype.is_floating_point()'`. **Fixed in this
   commit** in `mojo/middle/comptime.py::dtype_predicate_for_spelling` (one definition of the
   dtype spellings, shared with the `comptime if` folder); `elaborate._is_float_dtype` /
   `_is_int_dtype` now delegate to it. Measured on the branch tree: `test/builtin/test_simd.mojo`,
   `test/math/test_exp.mojo` and `test/math/test_math.mojo` turn PASS (3 of 7).
2. **A bare `List(...)` constructor does not keep a container type.**
   `var buckets = List([0]) * num_buckets` lowers the call through `_lower_opaque_ctor`
   (`mojo/backend_gimple/emit_calls.py` ~5291, the opaque-uppercase arm) to `(int64_t)list`, so
   `buckets` is declared `int64_t` and the `*` becomes pointer-integer multiplication; the loop
   then asks an `int64_t` for `mojo_list_get_str`/`mojo_list_get_int`. Next step: a bare-`List(...)`
   arm ahead of the opaque-uppercase arm, mirroring the subscript `List[T](...)` arm at ~3413:
   `List()` -> empty list, `List(<list/tuple/iterable>)` -> a copy/materialized list,
   `List(length=, fill=)` -> the same length/fill lowering; it must return `MojoList *` and carry
   `_elem_types`. Without it `test/hashlib/test_ahash.mojo` and `test/hashlib/test_fnv1a.mojo`
   cannot compile. Measured on master without the branch, the same erasure is a silent wrong
   answer: `var a = List([1, 2]); var b = a * 3; return len(b)` compiles to
   `_t5 = (int64_t)_t1; a = _t5; _t7 = a * 3LL;` and the program SEGFAULTS (exit 139) where
   `python3 fire.py run` answers 3.
3. **The fragment TU has no import table.** `rand(p)`, `sort(p)` and `List(length=...)` in an
   elaborated body emit bare `rand`, `sort`, `List` extern stubs; the generated C declares
   `int64_t List(...)` and calls libc `rand`, which rejects the argument ("too many arguments to
   function 'rand'"). `monomorphize.instantiate` builds a fresh `GimpleGen`, so the caller module's
   imported symbols/aliases never reach it. Next step: pass the caller's import table
   (`gen.imported_symbols` / `_imported_overloads` / the module aliases) into the instantiation's
   `GimpleGen`, or emit the qualified externs the caller would. Without it
   `test/builtin/test_sort_issue_1018.mojo` cannot compile.
4. **A generic struct's whole body is compiled.** `SIMD[.bfloat16, 2]`'s `__and__` carries
   `comptime assert Self.dtype.is_integral() or Self.dtype == DType.bool`, which is false for
   `bfloat16`; the method is emitted even though nothing in that instantiation calls it.
   `6158c593e`'s suppression covers only a custom-self annotation that provably names a DIFFERENT
   instantiation, which `Self.dtype` is not. Next step: extend the inapplicability test to a
   `Self.<param>` receiver whose concrete value differs from the one being compiled, or emit a
   generic struct's methods lazily. Without it `std/simd.mojo` cannot compile after the merge with
   master (it PASSES on the branch tip alone, so that is also a merge-coherence datapoint).

The doc stays until 2-4 land: the landing gate is `stdlib-syntax` only (`tools/gates.json`), so the
branch still cannot land, and this is its work item.

## Done when

`python3 test_where_clause_call_site_diagnostic.py` reports `ok
test_dot_relative_dtype_satisfies_a_dtype_where_clause` (class 1; it raises
`type '.float32' does not satisfy constraint` before this commit — measured — and covers the three
files class 1 fixed), **and** all seven files above compile through
`compile_stdlib.transpile_file` on the landing tree (classes 2-4). The first half lands in this
commit; the second half is the remaining work described above.
