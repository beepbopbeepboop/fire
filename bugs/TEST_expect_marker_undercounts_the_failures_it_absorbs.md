# TEST_expect_marker_undercounts_the_failures_it_absorbs: `formal-receiver-position` is `expect=`-marked for 2 failures and now fails 3, and the third is a different construct

**Status: found 2026-10-01, NOT fixed.** `CLAUDE.md`'s known-failure rule says an
`expect=` marker is anti-rot **because** it reports a test that starts passing as
a FAILURE. It cannot notice a test that starts failing **differently** — the
marker forgives `FAIL`/`ERROR` wholesale, so a NEW failure inside an
already-marked test is absorbed silently and the tally still says `EXPECTED`.
This is that case, on this tree.

## What is there

`tools/suite.py`:

```python
test('formal-receiver-position', [PY, 'test_formal_receiver_position.py'],
     mem='tiny', deps=['preflight'],
     expect='bugs/FORMAL_a_specialization_defeats_the_frame_escape_refusals.md '
            '— 2 of 12: a specialized call with a frame address at an argument '
            'position bypasses both the returned-frame and the value-only-callee …')
```

and the doc it names (`bugs/FORMAL_a_specialization_defeats_the_frame_escape_refusals.md`,
Status, line 7): "**2 of 12 cases fail, on arm64.**"

## What is measured

```
$ python3 test_formal_receiver_position.py
formal receiver position: PASS=9 FAIL=3

  FAIL  refuse_a_specialized_parameter_returned            ← the marker's #1
  FAIL  refuse_a_dotted_specialized_callee_names_it        ← NOT in the marker
  FAIL  refuse_a_value_only_callee_through_a_specialization ← the marker's #2
```

The third one, in full, because it is a different defect wearing the same test:

```
--backend=arm64 refused, but not with the expected words 'The callee of this
call is Box.run[1], which names no function this pass has a parameter list
for': cause the function assigns it somewhere, and the emitted image has no
way to mean "unbound" — so the read would return whatever the CALLER left in
that register …
```

That is a **module-state storage** refusal (`'Box'` has no home), not the
specialization-bypasses-a-refusal defect the marker and its doc are about. Two
independent consequences:

1. **A reader is misled.** The doc says 2, the file says 3, and the suite prints
   `EXPECTED` with the marker's reason — so the discrepancy is visible nowhere
   except by running the file by hand.
2. **A new regression here is free.** Any future break of this test is forgiven
   by the marker, whether or not it is the one the marker names.

Pre-existing on this tree, not caused by any change in the session that found it:
the identical three fail with `formal/build.py`'s `_frame_valued_calls` neutered.

## The next step

Two independent pieces, and the second is the one that matters:

1. **Triage `refuse_a_dotted_specialized_callee_names_it`** — it now stops at a
   module-state refusal before reaching the specialization refusal its needle
   wants. Either the `'Box'` global gets a home (that is
   `bugs/FORMAL_module_state_no_storage.md`'s row) or the case's fixture is
   changed so the name is bound where it is written, which is what its own
   message recommends.
2. **Make the marker state its count**, or make the suite check it. A marker
   whose reason says "N of M" should be compared against what the run actually
   produced; `tools/suite.py` already has the machinery to report an
   `expect=`-marked test that PASSES, and "fails MORE than the reason claims" is
   the same class of signal for the same reason — both mean the marker no longer
   describes the test.

The second piece is in `tools/suite.py`, which no claim covers today
(`bugs/TEST_expect_marked_tests_in_no_bucket_never_run.md` and
`bugs/TEST_registered_tests_in_no_bucket_never_run.md` are about a different
gap — tests in no bucket).