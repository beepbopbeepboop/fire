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
translation unit, and these bodies need four things the isolated TU does not have. Classes 1 and 2
are fixed here; 3-4 are the remaining work, with the exact failure measured for each.

1. **A `where` clause over a dot-relative dtype spelling.** `check_where_clauses` falls back to
   `elaborate._is_float_dtype`, which recognized only `Float32` and `DType.float32`; `.float32`
   (the text `_type_expr_to_ann` renders for a `DottedLiteral`) therefore answered "not a float"
   and the call was rejected with
   `type '.float32' does not satisfy constraint 'dtype.is_floating_point()'`. **Fixed in this
   commit** in `mojo/middle/comptime.py::dtype_predicate_for_spelling` (one definition of the
   dtype spellings, shared with the `comptime if` folder); `elaborate._is_float_dtype` /
   `_is_int_dtype` now delegate to it. Measured on the branch tree: `test/builtin/test_simd.mojo`,
   `test/math/test_exp.mojo` and `test/math/test_math.mojo` turn PASS (3 of 7).
2. **A bare `List(...)` constructor did not keep a container type. — FIXED.**
   `var buckets = List([0]) * num_buckets` lowered the call through `_lower_opaque_ctor`
   (`mojo/backend_gimple/emit_calls.py`, the opaque-uppercase arm) to `(int64_t)list`, so
   `buckets` was declared `int64_t` and the `*` became pointer-integer multiplication; the loop
   then asked an `int64_t` for `mojo_list_get_str`/`mojo_list_get_int`. Measured on master before
   this commit, the erasure was also a silent wrong answer: `var a = List([1, 2]); var b = a * 3;
   return len(b)` compiled to `_t5 = (int64_t)_t1; a = _t5; _t7 = a * 3LL;` and the program
   SEGFAULTED (exit 139) where `python3 fire.py run` answers 3.
   **Fixed in this commit** by `_lower_bare_list_ctor`: a bare-`List(...)` arm ahead of the
   opaque-uppercase arm returns `MojoList *` and reuses the existing container machinery —
   `List()` -> empty list, `List(<iterable>)` -> `list(...)`'s own
   `_lower_ctor_from_iterable` walk (so the element type, kinds and boxed-handle resolution are
   the same ones), `List(1, 2, 3)` -> a list display, and `List(length=, fill=)` -> a synthetic
   `[fill for _ in range(length)]` (the fill is lowered once, outside the loop). Its regression
   test is `test_gimple.py::gate_stdlib_syntax_bare_list_constructor`, which RUNS the five forms
   and requires `2 / 1 2 / 4 7 7 / 0 / 2 2 / 3 3`; the old lowering segfaults on its first line. All seven
   files above still compile through `compile_stdlib.transpile_file` after the change.
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

Classes 3-4 are the remaining work, and both are in code the held branch's own fix owns
(`monomorphize.instantiate`/`elaborate.py`'s import table, and the custom-self suppression in
`emit_funcs.py`); they are not reproducible on master because master does not yet render the
string/dot bracket arguments that make the calls elaborate. The doc stays until 3-4 land: the
landing gate is `stdlib-syntax` only (`tools/gates.json`), so the branch still cannot land, and
this is its work item.

## Done when

`python3 test_where_clause_call_site_diagnostic.py` reports `ok
test_dot_relative_dtype_satisfies_a_dtype_where_clause` (class 1; it raised
`type '.float32' does not satisfy constraint` before its commit — measured — and covers the three
files class 1 fixed), **and** `python3 test_gimple.py` reports `PASS
gate_stdlib_syntax_bare_list_constructor` (class 2; the pre-fix lowering segfaults on its first
line — measured), **and** all seven files above compile through
`compile_stdlib.transpile_file` on the landing tree (classes 3-4). Classes 1 and 2 have landed;
3-4 are the remaining work described above.
