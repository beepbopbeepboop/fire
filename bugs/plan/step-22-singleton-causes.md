# plan/step-22: the 19 singleton direct causes (diagnostic accuracy)

**Source:** `bugs/FORMAL_known_limits.md` §3 (the small shapes table) and §6.3
(lever #5); `bugs/FORMAL_known_limits.md`'s own guidance.
**Master plan:** `doc/finish-formal.md` §"Step 22".

## Goal

The 19 files each with their own direct cause. The doc's guidance for this row:
**prefer fixing a wrong message to adding a capability** — several are weak
messages rather than missing capabilities.

## What to add

One row per singleton: the file, the refusal, whether it is a true limit, and
either the message fix or the capability. This is a sweep, so the step doc
carries the checklist and each verdict is entered as it is measured.

**Re-measure first.** Families move with the walk; the doc records one family
changing by an order of magnitude "without anything being wrong". A stale table
is exactly the false claim the doc exists to prevent.

## Structure-only rule

Each row's verdict must be a *measurement* (a build, a diff), not a reading.
Where a capability is added, scaffold its proof obligation with `sorry`; where a
message is fixed, prove the new text true of the file.

## Files

`formal/model/`, `test_refusal_taxonomy.py`, the affected messages.

## Verification

A fresh sweep (`tools/formal_sweep.py`) before and after; the per-row pins.

## Done when

- [ ] every singleton has a measured verdict
- [ ] each is either fixed or recorded as a true limit with a reason true of the
      file
- [ ] `tools/formal_doc_index.py --check` and the ratchet stay green

## Dependencies

step-01 (holes only). Should land after steps 10–18 so the residual is fresh.
