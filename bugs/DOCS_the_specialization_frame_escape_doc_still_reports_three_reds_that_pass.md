# DOCS: the specialization frame-escape doc's transcript still reports three REDS that have been green since the fix it describes

**Area:** `bugs/FORMAL_a_specialization_defeats_the_frame_escape_refusals.md`
(its §Status transcript and the `formal-receiver-position` paragraph at line
~31). **Claim:** `bug:FORMAL_a_specialization_defeats_the_frame_escape_refusals`
is held by `formal25-1`, so this doc is filed rather than edited.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label recvpos -- python3 test_formal_receiver_position.py
  PASS  refuse_a_specialized_parameter_returned      (and the other 37)
  PASS  refuse_a_dotted_specialized_callee_names_it
  PASS  refuse_a_value_only_callee_through_a_specialization
formal receiver position: PASS=38 FAIL=0
memcap: done, peak 0.1 GB across up to 3 procs (ceiling 8.0 GB), child exit 0
```

## What the doc still says

Its §Status block, as of this commit:

```
    $ python3 test_formal_receiver_position.py
    formal receiver position: PASS=11 FAIL=3
...
Re-measured 2026-10-02 on `work/formal8-1`, unchanged and for the same three
reasons: **PASS=13 FAIL=3**, and the three are the same three names
(`refuse_a_specialized_parameter_returned`,
`refuse_a_dotted_specialized_callee_names_it`,
`refuse_a_value_only_callee_through_a_specialization`) with the same messages.
...
      FAIL refuse_a_specialized_parameter_returned            (expected)
      FAIL refuse_a_dotted_specialized_callee_names_it        (not in the filing)
      FAIL refuse_a_value_only_callee_through_a_specialization (different message)
```

and, thirty lines on:

> `formal-receiver-position` in `tools/suite.py` still carries an `expect=` for
> this doc and forgives them; its reason string says "2 of 12" and the file now
> has 3 of 14 … **that edit is the integrator's, and this worker did not touch
> `tools/suite.py`.**

Both halves are now false. The `expect=` is gone (`tools/suite.py`, 2026-10-04 —
its `expect=` forgave exactly these three cases, all of which pass, so
`suite.py`'s `PASS` arm was reporting the job red as "marked expect=… but it
PASSES"; the marker is deleted and the job moved to `check` so the next red is
visible in the everyday gate), and the file has 38 cases green rather than 13
with 3 red.

## Why the doc is not simply deleted

Its SUBJECT is still worth a file, which is why this is a transcript correction
rather than a `git rm`: what it describes — a comptime specialization with a
frame address at an argument position bypassing two refusals — is the reason
`formal/model.py::struct_returned_frame_sites` calls
`M.call_callee_name(node.func)` instead of reading `node.func.name`, and
`formal/build.py::_frame_return_status` classifies a specialized call as
returning a frame. Both of those are in the tree and are load-bearing. What is
stale is the measurement block, the "still carries an `expect=`" sentence, and
the three case names presented as failing.

## Exact next step

One edit, in the doc you already own:

1. Replace the §Status transcript with the measured `PASS=38 FAIL=0` above and
   the date, keeping the three names as the cases the marker used to forgive and
   saying they refuse again with the sentences their rows pin — that is the fact
   that made the marker removable, so it belongs in the doc that named them.
2. Rewrite the paragraph at line ~31: the `expect=` is deleted, the job is in
   `check` and `proofs`, and the "that edit is the integrator's" sentence goes
   with it.
3. `python3 tools/dangling_doc_refs.py --ratchet` in the same commit. Nothing
   else in the tree cites the TEST doc that carried this step, and it was deleted
   with its fix, so the ratchet is reported clean at this commit — which is the
   check that will tell you if step 2 has reintroduced one.