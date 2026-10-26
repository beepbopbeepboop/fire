# CODEGEN: a generic-struct elaboration that fails for a transient reason
# lowers a DIFFERENT program, and the content-addressed store remembered it

## Status

OPEN, and now with the two halves that could be closed closed:

* **The wrong artifact can no longer be cached.** `compile_module_to_c_cached`
  publishes a module only when nothing about it degraded, and says so on
  stderr when something did.
* **A nested `gcc -c` failure now carries its own stderr**, so the next
  occurrence is diagnosable instead of inferred from a gcc error three stages
  downstream.

The stderr line is already paying for itself: it names six files in the
stdlib's own `std/` tree that are degraded on EVERY run, deterministically, for
two reasons that were previously invisible (see "What the diagnostics found").
What is still open is the transient that hit the gate, which was not
reproducible on this tree.

## What it looks like

`stdlib-syntax` reported one UNEXPECTED failure on master (d0796643, gate run
2026-10-02 08:39):

    UNEXPECTED failed files:
      test/iter/test_ref_iteration.mojo
        → gcc: .../test/iter/test_ref_iteration.mojo:211:4: error: request for member

Line 211 is `x.value += 1` inside `for ref x in list:`, where `list` is a
`MoveOnlyList[MoveOnlyInt]`. Nothing about iterators is wrong; a `str` field
read on something that is not a struct is.

## How it was identified

The gate's own artifact was still in the CAS — `stdlib-compile` is
content-addressed, so the generated C that failed is on disk. Comparing it with
a fresh compile of the same file at the same commit:

| | bytes | `MoveOnlyList_MoveOnlyInt` | verdict |
|---|---|---|---|
| fresh compile | 86422 | present, with methods and a `T`-free layout | gcc clean |
| the artifact the gate compiled | 107704 | **absent entirely** | gcc: request for member |

So the gate did not compile a different thing. It compiled a module in which
`MoveOnlyList[MoveOnlyInt]` was never monomorphized: only the raw `MoveOnlyList`
template is in that C, its `T` field typed `int64_t`, `append` taking
`int64_t`, `__iter__` returning `int64_t`. `for ref x in list` then binds `x`
to an `int64_t` and `x.value` is the member request.

Reproduced byte for byte: forcing `monomorphize.instantiate` to raise and
recompiling gives 107688 characters against the artifact's 107688 —
`IDENTICAL`. That is what pins the mechanism rather than merely suggesting it.

`emit_resolve._ensure_generic_struct` is the only thing between the two: it
swallows every exception from `Elaborator.elaborate_generic_struct` into
`info = None`, and `None` means "not a generic struct I can elaborate", so the
call site fell through to the plain struct-constructor path.

## Why the raw-template fallback cannot simply become a refusal

Measured, because it is the obvious fix and it is wrong. Turning the swallow
into a refusal took **six of the stdlib's 252 `std/` files** from compiling to a
hard failure, all of them currently green:

    std/os/os.mojo                          List[String]
    std/os/process.mojo                     List[Optional[CStringSpan[ImmutAnyOrigin]]]
    std/python/_cpython.mojo                Array[Int, 3]
    std/simd.mojo                           SIMD[exp.dtype, self.length]
    std/collections/interval.mojo           Deque[Tuple[Self._IntervalNodePointer, String, Bool]]
    std/collections/string/_parsing_numbers/parsing_floats.mojo
                                            Array[Byte, CONTAINER_SIZE]

Those are not marginal constructs; they are `List[String]` and `Array[Int, 3]`.
The elaborator's own bound check (`elaborate.check_bounds` →
`check_conformance`, a textual method-signature comparison) is the strictest
thing in the path and it rejects types that genuinely conform. So the fallback
is load-bearing and stays; what changed is that its result can no longer be
cached, and that its reason is recorded instead of discarded.

## What the diagnostics found, on the first run

With the reason recorded instead of discarded, a 252-file `std/` sweep says six
files are degraded on every run — deterministically, and for two reasons that
were not previously visible anywhere:

    std/collections/interval.mojo      Deque[Tuple[Self._IntervalNodePointer, String, Bool]] from
                                        std/collections/deque.mojo:
                                        AttributeError: 'AssignStmt' object has no attribute 'name'
    std/collections/string/_parsing_numbers/parsing_floats.mojo
                                        Array[Byte, CONTAINER_SIZE] from std/collections/array.mojo:
                                        AttributeError: 'AssignStmt' object has no attribute 'name'
    std/os/os.mojo                     List[...]        (same AttributeError)
    std/os/process.mojo                List[...]        (same AttributeError)
    std/python/_cpython.mojo           Array[Int, 3]     (same AttributeError)
    std/simd.mojo                      SIMD[exp.dtype, self.length] from std/simd.mojo:
                                        SyntaxError: .../SIMD_exp_dtype_self_length.mojo:2662:32:
                                        Expected RBRACKET got ASSIGN('=')

Neither is a transient and neither is the gate's failure:

* `'AssignStmt' object has no attribute 'name'` is a gap in the elaborator's
  struct extraction — it walks a method body and meets an assignment. The
  fallback then compiles the file against the raw template, so those modules
  are wrong today and have been; `gcc -fsyntax-only` cannot see it.
* `Expected RBRACKET got ASSIGN('=')` is the textual monomorphizer producing
  source that does not re-parse (`Self.<member> = <default>` at line 2662 of
  the substituted template), so the instantiation cannot be compiled at all.

Both are worth their own fixes — the second is `monomorphize_source`
emitting invalid source, which is a real defect — and both are now visible in
one stderr line per file per run.

## What was ruled out

* **Not the bound check on this pair.** `check_bounds(module_src,
  'MoveOnlyInt', 'Movable & Deinitable')` is pure text over the file's own
  source and returns "conforms" every run — the correct 86422-byte artifact,
  which does contain `MoveOnlyList_MoveOnlyInt`, comes out of it.
* **Not a stale key.** `cas.instantiation_key` is content-only (template
  source, type args, gcc, flags) and `cas.compiler_fingerprint` deliberately
  omits `fire.py`/`myinterpreter.py`, so a same-commit rebuild legitimately
  hits. The 2026-10-02 timestamps say the other way round anyway: the
  instantiation's `.o` was built at 09:28 by a run that SUCCEEDED, and the
  artifact that failed was written at 08:09 — before that `.o` existed, by a
  run that therefore had to build it, and whose build must have failed.
* **Not cross-file state.** The same file compiled correctly as the first, the
  last and the tenth file in one process, and inside a 22-file process pool
  (`stdlib-syntax`'s own shape) alongside all 21 files that are in
  `compile_stdlib.py`'s `EXPECTED_FAILURES`. Whatever it was, it was not
  "what this worker process did earlier".

## What is left to look at

`monomorphize.instantiate`'s `build()` is the only impure step in
`elaborate_generic_struct`, and it is where the failure had to be: a nested
`GimpleGen(...).gen_module(...)` over the monomorphized template plus a
`gcc -fgimple -fPIC -c`. On a 18-worker sweep, each worker spawning gcc for
every instantiation it needs, the candidates are an `OSError` from the fork
under load, and a gcc killed by the OS.

The next step is to make the next occurrence observable rather than to keep
guessing, and both halves of that are in place: the nested build's stderr
travels in the exception, and `compile_module_to_c_cached` writes the failing
`Struct[Args] from <source>: <exception>` to stderr instead of caching. A
recurrence now prints the gcc error that caused it, on the run that hit it.

If it recurs and the reason turns out to be load-dependent, the fix belongs in
the sweep's concurrency (or in a bounded retry around the nested build, which
is defensible precisely because the build is content-keyed and deterministic —
a second attempt either succeeds or fails identically, so it cannot hide a
real defect). If it turns out to be something else, the stderr line names it.

**Landed 2026-10-04: the bounded retry.** `monomorphize.instantiate`'s
`build()` now runs the nested `gcc -c` up to three times and keeps every failed
attempt's stderr in the exception. The argument above is the whole argument,
and it is what makes the retry safe rather than a way of making a red go away:
`cas.instantiation_key` covers the template source, the type args, the gcc and
the flags, so the build is deterministic and a second attempt either succeeds —
which is the transient — or fails with the SAME stderr, which is a real defect
and is still raised. Measured both ways in
`test_module_cache.py::test_instantiation_nested_gcc_is_retried`: a gcc that
fails twice then succeeds produces the object on attempt 3, and a gcc that
always fails still raises after 3 attempts carrying all three stderrs.

That leaves exactly one thing open, and it is the same one as before: the
sweep's own concurrency. The retry is deliberately the smaller half — it makes
a recurrence *observable* (three stderrs and an attempt count, on the run that
hit it) without claiming to know the cause. If the stderrs of a future
occurrence are all DISTINCT, the retry is not the answer and the concurrency
is; if they are identical, the transient was not the nested gcc and the stderr
line names whatever it was.

## Where

* the swallow: `mojo/backend_gimple/emit_resolve.py`, `_ensure_generic_struct`
* the cache decision: `build_stdlib_dylib.py`, `compile_module_to_c_cached`
  and `compile_module_to_c`'s `_LAST_DEGRADED`
* the nested build: `monomorphize.py`, `instantiate`'s `build()`
* the regression: `test_module_cache.py`,
  `test_elaboration_failure_is_not_cached`