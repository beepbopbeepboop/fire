# TEST_formal_receiver_position_expect_marker_outlived_its_three_cases: the marker forgives three failures that no longer happen, so `formal-receiver-position` reports a FAILURE for PASSING

## Status

OPEN, and PRE-EXISTING ON MASTER — measured 2026-10-04 on `work/merge-formal20`
(the merge of `work/formal19-5` and `work/formal18-2`). Neither branch caused
it and neither branch can fix it: the marker is in `tools/suite.py`, which this
branch's claim (`merge:formal20`) does not cover and which CLAUDE.md's "do not
register anything in `tools/suite.py` unless your task says so" keeps out of
scope here.

`bugs/FORMAL_a_specialization_defeats_the_frame_escape_refusals.md` already
records that this marker's REASON STRING had gone stale ("it says `2 of 12` and
the file now has 3 of 14", and it has since been corrected to `3 of 14`). What
that doc does not have — and what this filing adds — is that the three cases are
no longer failing at all, so the marker is stale in kind rather than in its
count.

## What I ran, and what I saw

    $ python3 tools/memslot.py --gb 8 --label recvpos -- \
        python3 test_formal_receiver_position.py
    ...
    formal receiver position: PASS=33 FAIL=0
    memcap: done, peak 0.1 GB across up to 3 procs (ceiling 8.0 GB), child exit 0

Zero failures, exit 0, so the runner classifies the job `PASS`. And
`tools/suite.py::_apply_expectations` has one arm for exactly this:

```python
        elif status == PASS:
            state[name] = FAIL
            log.notice(f'  FAIL     {name}  (marked expect={reason!r} but it '
                       f'PASSES — drop the marker and fix whatever it was '
                       f'waiting for)', force=True)
```

So `formal-receiver-position` reports as a **FAILURE whose text is "it PASSES"**
whenever a bucket that runs it completes. It is in `proofs` only — not in
`check` or `gate` — which is why nobody has seen it: the buckets that run every
day never execute the job.

The marker's three named cases are, from that doc:

* `refuse_a_specialized_parameter_returned`
* `refuse_a_dotted_specialized_callee_names_it`
* `refuse_a_value_only_callee_through_a_specialization`

All three assert a REFUSAL. All three pass now, which means all three refuse
again with the sentences their rows pin — including
`refuse_a_dotted_specialized_callee_names_it`, which the doc says had "stopped
at a module-state refusal (`Box` has no home) before reaching the specialization
refusal its needle wants".

## Why it is pre-existing on master, measured

Master's own copies of the test and of the four `formal/` modules it drives,
extracted to a scratch tree and run there:

    $ git archive master formal mojo tools test_formal_receiver_position.py \
        $(git ls-tree --name-only master | grep -E '\.py$' | grep -v '^test_') \
        | tar -x -C .tmp/mt
    $ cd .tmp/mt && python3 .../tools/memslot.py --gb 8 -- python3 \
        test_formal_receiver_position.py
    ...
      PASS  refuse_a_one_field_holder_reading_a_frame_nothing_built
      PASS  refuse_a_store_through_a_one_field_holders_unbuilt_frame
    formal receiver position: PASS=33 FAIL=0

Same 33, same zero, on master. So the marker is stale there too, and the
"three of them no longer fail" fact belongs to work already on master — not to
either branch merged here. (`formal18-2`'s `03e3b7b6` does change WHICH 33:
it replaces two `REFUSALS` rows with two differential rows. The total and the
zero are the same either way.)

## The next step, exactly

1. **Delete the `expect=` on `formal-receiver-position`** in `tools/suite.py`
   (line ~2516, the `test(...)` call), and nothing else — the job is green, so
   the marker is the only thing wrong with it. `test_suite.py` already has a
   check for a registry row whose stated status is not the registry's; this is
   the runtime half of the same discipline.
2. Then correct `bugs/FORMAL_a_specialization_defeats_the_frame_escape_refusals.md`,
   which still reports those three rows as `FAIL ... (expected)` /
   `(not in the filing)` / `(different message)`. Its subject — a specialized
   call with a frame address at an argument position bypassing two refusals — is
   still worth the doc; its TRANSCRIPT is not, and a transcript that says three
   cases fail when they pass sends the next reader to re-fix a closed bug.
3. Do NOT re-add the marker with a smaller count. `_expect_count_drift` reads
   the count out of the marker's own prose and compares it with the run, so a
   marker stating "0 of 33" over a passing job is still reported as a FAILURE by
   the `PASS` arm above — the count is only ever consulted for a job that
   actually failed.

## Note for whoever merges next

This one is invisible to `make gate`, which is the whole reason it can sit on a
tree: a marker on a test no bucket but `proofs` runs cannot be observed going
green, and `expect=` was chosen for this job when the count was right. The same
blind spot is what a now-deleted document about markers on tests in no bucket
was about, from the other side — that one is closed, and this is the shape that
survived it: the job IS in a bucket, and the bucket is one nobody runs.

While the row is open, `tools/suite.py:490` should also stop saying
`# 2 s, 12 cases` for this job — it is 33 cases now, and a `MEMCLASS` comment is
the one place in the registry where a stale count is not machine-checked.
