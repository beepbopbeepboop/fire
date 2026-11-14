# CODEGEN_stdlib_dylib_degraded_module_not_refused: `stdlib-dylib` links a module built through a failed elaboration

**Class:** easy (needs a policy decision, see next step)
**Found:** 2026-11-14 on `work/bug-codegen-stdlib-failed-elaboration-co`, while
fixing the sweep-side verdict (`compile_stdlib.py` now reports such a module
FAILED, commit 77d940fba).

## Symptom

`build_stdlib_dylib.py`'s dylib build path compiles every module with
`_compile_one_object` → `compile_module_to_c` and never reads
`last_degradations()`. So a module whose generic-struct elaboration failed is
lowered against its un-elaborated template (every type parameter `int64_t`),
linked into the dylib, and no `skip <module>:` line is printed.

That is the same condition the sweep now refuses to call a pass: the compiler's
own message says the module's C is "NOT the program its source describes". The
dylib is the artifact every compiled program links against, so shipping that C
is worse than a miscount.

Measured before the refusal below was fixed (this tree, `std/simd.mojo`):

    python3 -c "from compile_stdlib import get_stdlib_path, transpile_file; \
      print(transpile_file(str(get_stdlib_path()/'std'/'simd.mojo'))[:2])"
    → (False, "elaboration: 2 generic struct elaboration(s) failed, ...")

The same codegen call in `_compile_module_job` is treated as success.

## Why it was not fixed here

The dylib's existing honest-degradation path is `skip <module>: <error>` and a
source fallback, and CLAUDE.md makes the `stdlib-dylib` `skip` count a gate
verdict that must not increase. The measured case was `std/simd.mojo`, whose
`advance without converging` refusal was a false positive; that refusal is
fixed (2026-11-14), so no stdlib module degrades today and the fix cannot be
measured against a live case. The defect is still real — the branch is not
reached at all, so the first future refusal is linked silently. The right
change is a decision between:

1. refuse → skip (no module degrades today, so the skip count does not move
   until a new refusal appears, and then the skip is honest), or
2. refuse → fail the build loudly (no silent dylib).

## Exact next step

In `build_stdlib_dylib._compile_module_job`/`_compile_one_object`, read
`last_degradations()` after the compile and return it as the job's `error`
(so the caller's existing `skip <module>: ...` path handles it), behind the
same measurement: compare `stdlib-dylib`'s `skip` count and the failing-module
list before/after. There is no live degrading module to measure with now, so
land it with a narrow test that forces a degraded compile through the job (a
stubbed `last_degradations()`, the way `compile_stdlib`'s verdict test does),
or mark the affected modules in one place the way
`compile_stdlib.EXPECTED_FAILURES` does for the sweep.

## Acceptance

- A module whose elaboration failed is never silently linked into the dylib:
  the build prints either `skip <module>: <reason>` or fails.
- The `stdlib-dylib` skip count does not increase for modules that compile
  cleanly today.
