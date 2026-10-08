# `formal_proof_census_baseline.json` is stale for `fact.mojo`, so `test_formal_proof_census.py` is RED on master, plus `formal-proof-census-tool` declares no `prooflib` dep

**Area:** FORMAL proof census (`tools/formal_proof_census.py`,
`tools/formal_proof_census_baseline.json`, `test_formal_proof_census.py`).
**Status: OPEN, measured 2026-10-07 on `work/formal153-docs` (master @
`4113d50e`).** This is the residual after the doc that recorded the *coverage*
half of the same tool — `FORMAL_proof_census_baseline_covers_52_of_93_examples.md`
— was resolved: the baseline now holds all **93** rows (it did on `4113d50e`,
with the corpus at 93), so `test_every_example_has_a_row_and_every_row_a_status`
passes. Two other assertions are still red for two separate reasons.

## What I ran, and what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
...
FAIL: test_each_row_is_tied_to_the_example_it_measured
AssertionError: '66e21e6ab48422dbe6c4fdca1b5fc98f3c033e39109799d687ffde1b114dd23b'
                != 'b2bbaf519f24c780c4ff33d73400b42a72b024c512007f65c7f0e69a38360606'
  : fact.mojo has changed since the baseline was written; re-seed with
    --write-baseline so the comparison is against this program

FAIL: test_library_state_agrees_with_the_question_it_asks
AssertionError: ['IEEE754', 'ProofLib', 'X86', 'work', 'Refine', 'Contracts',
                 'Peephole', 'Specs'] != []
  : lib/ is missing [...]; every key would miss and the report would be
    reporting the wrong thing

Ran 61 tests in 0.147s
FAILED (failures=2)
```

## The first red: the `fact` row's source hash is stale

`formal/examples/fact.mojo` was rewritten by `ffe27e1a` ("the PRECONDITION takes
the range `@refines` already claimed", 2026-10-05 17:50), and the baseline's
`fact` row still carries the pre-change `source_sha256`
(`66e21e6a…`) while the file on disk hashes to `b2bbaf51…` (`ffe27e1a` IS an
ancestor of `4113d50e`, measured). The row also records a status
(`lean-rejected`) and a measured `lean_cpu_s` that were taken against the OLD
program, so the ratchet is comparing a new program against a verdict about a
different one.

**The exact next step** is the bounded re-bank the tool provides (measured at
**~222 s wall / 227.7 s CPU / 2.9 GB** for this row, i.e. inside the light-worker
8 GB budget but a Lean proof run, so it belongs to whoever may run Lean):

    export PATH=/opt/homebrew/bin:$PATH
    python3 tools/memslot.py --gb 8 --label census-fact -- \
      python3 tools/formal_proof_census.py --only fact --write-baseline

`write_baseline` merges, and `--only` narrows the Lean workload to the one
example, which is the same shape `c6b8105f` used to bank eleven rows earlier.
If `fact` is no longer `lean-rejected` after the contract change, the row's
status moves with it — which is the point of re-measuring rather than patching
the hash by hand: editing `source_sha256` alone would tie a NEW program to the
OLD verdict and make the ratchet compare the wrong pair.

## The second red: the job declares no `prooflib` dep

`test_library_state_agrees_with_the_question_it_asks` asserts that every
`lib/*.lean` module key appears in `lib/` as a built artifact (`lib/*.olean`).
On a checkout where `lib/ProofLib.olean` has not been built — every fresh
worktree, and any parallel proofs bucket that starts this job before the shared
build — the assertion is red for the same eight modules. `formal-proof-census-tool`
is registered in `tools/suite.py` with `deps=['preflight']` only, so nothing
orders it after the ProofLib build (`prooflib`), and a machine whose `.olean`s
are cold fails a job about the census's arithmetic over a missing prerequisite.

**The exact next step is one word in `tools/suite.py`**: add `prooflib` to that
registration's `deps`, which is the class `CLAUDE.md`'s "Shared expensive
dependencies" section describes. It is not taken here because a `deps` change
touches the gate registry and this worker is not permitted to run the gate.

## Why it is filed and not fixed here

Both halves need a Lean-capable runner: the first is a Lean proof-census
re-measurement, the second is a `tools/suite.py` dependency edge whose effect
can only be shown by a gate run. `test_formal_proof_census.py` is a registered
gate job with `mem='tiny'`, so this is a real red in the tally and is declared
by no `expect=`.
