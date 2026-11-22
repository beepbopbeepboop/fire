# Gate: bootstrap-stage2-dumps:bootstrap_test_classes.mojo is red on master

**Job:** `bootstrap-stage2-dumps:bootstrap_test_classes.mojo`. Filed by the full gate at `c0182fd365`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py bootstrap-stage2-dumps:bootstrap_test_classes.mojo`), then fix the cause.

## Status (2026-11-21): fixed upstream at the root cause; this item has no defect of its own

The item's red at `c0182fd365` was the **disabled-producer cascade**, not a defect of
`bootstrap_test_classes.mojo`. `bootstrap-stage2-dumps` depends on `bootstrap-stage2-cc`
(gcc over the stage1 closure), which is doc'd off (`bugs/gate-bootstrap-stage2-cc.md`), so
`stage2/mojo` was never built; the pre-`416ed660c` scheduler counted `DISABLED` as a
satisfied dependency and ran the whole fifty-item fanout anyway, every item dying in a
second on `FileNotFoundError: './mojo'` and one bug being filed fifty ways.

`416ed660c` ("suite: a disabled dep SKIPs its dependents, naming the doc that is the
switch") made `DEP_SATISFIED` `PASS` only, so the fanout now SKIPs behind its producer and
runs again the day that producer's doc is deleted.

Measured in this tree (master `1b94b71d4`, `python3 tools/suite.py bootstrap-stage2-dumps`):
`2 passed, 0 failed, 1 skipped, 2 disabled`, the item's own line
`[ 6/99] skip bootstrap-stage2-dumps:bootstrap_test_classes.mojo` with the reason
`dependency is disabled: bootstrap-stage2-cc (bugs/gate-bootstrap-stage2-cc.md is the switch)`,
and the same input passes at stage 1 (`bootstrap-stage1-dumps:bootstrap_test_classes.mojo`,
ok, 2.1s) — so the source file is valid and nothing per-item is owed.

The **"Skipped"** paragraph this doc was filed with is itself stale: a fanout ITEM has no
`test()`/`fanout()` registration of its own, so the ledger wrote no `disabled=` argument
naming this doc. `7d3eb22bb` now keys that paragraph on the marker the ledger actually
wrote (`marked`) and names the parent fanout instead. It is the same cascade and the same
resolution as the other item docs this fanout produced, none of which is an item defect.

## Done when

`python3 test_suite.py` passes — its `test_a_disabled_test_is_registered_but_never_runs`
pins the cascade (a disabled producer's dependent SKIPs, a fanout behind it spawns no item,
every item's skip names the doc, and the fanout is one skipped test rather than one red
apiece); it fails with the pre-`416ed660c` `DEP_SATISFIED`. Together with
`tools/test_gate_ledger.py`'s `ReportText` (a fanout item's doc never claims a `disabled=`
marker the ledger did not write) and `tools/test_gate_doc.py`'s
`test_one_doc_per_failing_test_not_per_fanout_item` (a red fanout is one job, so one doc,
not one per item), those are the pinning tests for this bug, and this doc is deleted in the
commit that records them passing.

## Gate ledger

- **Last known working:** `d0c0a1cc57` integrate bug-codegen-stdlib-syntax-six-files-red
- **First known not working:** `0b0316114e` integrate fix-gate-formal-host-import-shapes
- **Seen red in the full gate at:** `8a4b0af29f` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8a4b0af2.log`)
- The numbers above are the ledger's, and they are fabricated for this item: `d0c0a1cc57`
  SKIPped the fanout behind the same red producer, and `0b0316114e` is simply the first
  commit of the probed range. The tri-state reader that stops the ledger inventing them is
  `bugs/SUITE_ledger_counts_a_skip_as_green.md`.
