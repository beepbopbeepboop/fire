# GATE: the bootstrap dependents report `ERROR ... dependency not selected: ` with the dependency NAME EMPTY

## Status (2026-10-31, OPEN, filed from a full `make bootstrap` run; runner diagnostic)

After `bootstrap-stage1-dumps` failed, the rest of the chain printed

    ERROR bootstrap-stage2-dumps:abfulltest_driver.mojo  (0s)  dependency not selected:
    ERROR bootstrap-stage3-dumps:abfulltest_driver.mojo  (0s)  dependency not selected:
    ERROR bootstrap-verify  (0s)  dependency not selected:

and counted them as `[ERROR]` failures (`FAILED: bootstrap-stage2-dumps (0s) [ERROR]`, ...), with
`bootstrap-stage2-cc`, `-transitive` and `bootstrap-validate` SKIPPED.

Two problems in `tools/suite.py`:

1. the message ends after `dependency not selected:`: the name of the dependency is missing, so the
   reader cannot tell which job was not selected;
2. a dependent whose dependency FAILED should be reported the way the others are (SKIPPED with the
   upstream failure named), not as a separate ERROR that doubles the failure count. `abfulltest_driver.mojo`
   is a stage-2 item whose dependency is the stage-1 item of the same file; that item is not in the
   run's plan (stage1 lists only part of the same corpus?), which is the "not selected" part.

## Next step

Find where `dependency not selected` is formatted in `tools/suite.py` and print the dependency name; then
decide whether `abfulltest_driver.mojo` is genuinely missing from the stage-1 plan (a registry bug: the
stage-2/3 fanout has an item the stage-1 fanout does not) or only looks that way because stage 1
aborted. Test: `python3 tools/suite.py --dry-run bootstrap` lists a stage-1 item for every stage-2 item.
