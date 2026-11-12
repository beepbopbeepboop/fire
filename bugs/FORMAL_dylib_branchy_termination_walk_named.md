# FORMAL: a branching export with no trap gets a named termination obligation, not a proof

Found 2026-11-12 while re-running `test_formal_dylib.py` after the overflow-guard contract fix (commit on
`work/bug-formal-wrong-spec-accepted-since-ove-10`). The failing row is "the last export's walk ignores the image tail".

## Symptom

`test_formal_dylib.py::test_the_last_exports_walk_ignores_the_image_tail` expects the branching export's termination to be
PROVED (`:=` then `DylibExport.total_of_halts ...`). The generator emits a named obligation instead:

    theorem dylib_export_1_branchy_semantics_total :
        DylibExport.Total dylib_image dylib_export_1_branchy := by
      sorry

with the comment "The constant-fuel CFG walk does not cover it: its control flow has a loop or a call, or a path ends in an
exit `svc` ...".

`branchy` has none of those: it is `if n > 3: return 1` then `return 0`. No loop, no call, no trap.

## Measured

- Source: `def head(n): return n + 1` and `def branchy(n): if n > 3: return 1; return 0`, built with
  `compile_formal_dylib(..., prove=False)`, then `generate_dylib_proof(..., {"head": "(fun n => (n + (1 : UInt64)))"})`.
- `branchy` LAST (entry `0x1000003ec`): `_semantics_total` is `by sorry`.
- `branchy` FIRST (entry `0x100000370`): also `by sorry`. So the failure is not specific to the export's position, and the
  test's docstring ("only the last export's extent reaches the image's tail") is not what the emitter is doing here.
- The test FAILS on pristine HEAD too. Measured by extracting `HEAD` with `git archive` into a scratch directory and running
  that one function there: `the last, branching export has no semantics_total theorem at all`. It is not a regression from the
  guarded-contract fix.

## Expected

A proved `dylib_export_1_branchy_semantics_total` (`total_of_halts` over a constant-fuel walk), as the test pins.

## Next step

Find where `_dylib_total_proof`'s constant-fuel walk (`_gen_universal_e2e_cfg`, `_acyclic`, `_gen_run_cert`) returns `None` for
`branchy`. Instrument the walk on the image above (both positions) and print which check fails first: the reachable-block set,
the acyclicity test, or the per-block run certificate. The conditional `B.cond` with a non-trap target is the first thing to
rule in or out, because a conditional is also the shape the overflow-guard reader refuses. Fix the walk; do not weaken the
test's "proved, not `sorry`" check.
