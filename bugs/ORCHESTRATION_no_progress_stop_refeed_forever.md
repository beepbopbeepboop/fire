# ORCHESTRATION_no_progress_stop_refeed_forever

## Summary
A bug doc that stays open is re-fed from master again and again, with no rule that stops a round that makes
no progress. Nothing says "this doc has had N rounds with no change to its failure". The only stop today is
manual.

## Evidence
- the class-rebind doc (since retired) had 33 superseded rounds (r2 to r31 plus 4223 and the fixers),
  and its status text never changed.
- The import-shapes chain ran 197 rounds before it was stopped by hand.

## Repro
Make a doc that no worker can fix. Watch `feed` re-queue it on every pass.

## Status
Open. Not started. Needs a rule that uses the doc's failure fingerprint, not commit counts or the worker's word DONE.

## Done when
A doc whose failing test output is unchanged across N rounds stops being fed and is flagged for a person,
with a test. Then delete this doc in the same commit.
