# `formal-proof-census-tool` is red: the committed census baseline records `fact.mojo`'s OLD source, so `test_each_row_is_tied_to_the_example_it_measured` fails

**Area:** FORMAL, the proof census (`tools/formal_proof_census_baseline.json`
and `test_formal_proof_census.py`). **Status: OPEN, measured 2026-10-08.** This
is the follow-on the deleted `FORMAL_proof_census_baseline_covers_52_of_93_
examples.md` predicted in its own next step #2 ("decide what a corpus file added
AFTER the last banking means for the tool's own test"). Its headline defect —
the baseline describing a 52-file corpus when `formal/examples` held 93 — was
fixed by `07cc3260`, which re-seeded all 93 rows. What is red now is a *changed*
example, not a missing one.

## What I ran, what I saw, what I expected

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
...
FAIL: test_each_row_is_tied_to_the_example_it_measured
AssertionError: '66e21e6ab48422dbe6c4fdca1b5fc98f3c033e39109799d687ffde1b114dd23b'
              != 'b2bbaf519f24c780c4ff33d73400b42a72b024c512007f65c7e...'
 : fact.mojo has changed since the baseline was written; re-seed with
   --write-baseline so the comparison is against this program
Ran 61 tests in 0.176s
FAILED (failures=2)
```

The baseline row for `fact` still carries
`source_sha256=66e21e6a…`, the hash of the program before commit `ffe27e1a`
("formal: `formal/examples/fact.mojo`'s contract is no longer FALSE — the
PRECONDITION takes the range `@refines` already claimed"). `ffe27e1a` is not an
ancestor of `07cc3260`, so the re-seed `07cc3260` performed could not have seen
it: the two commits landed on different branches and the `fact.mojo` change was
merged after the banking.

The other failure in the same run,
`TestCacheReport.test_library_state_agrees_with_the_question_it_asks`, is not a
content defect: it asserts `lib/` holds every `[L.LIBRARY_MODULES]` `.olean`
(`IEEE754`, `ProofLib`, `X86`, …), which are build products this fresh worktree
has not produced. It is green on a tree where the `prooflib` dependency has run
and is not what this document is about.

## Why it matters

`formal-proof-census-tool` is a registered gate job (`mem='tiny'`, no Lean of
its own), and this is a real red in the tally — no `expect=` covers it. The
ratchet's whole contract is "the committed row describes the program on disk",
and for `fact` it does not: `compare` would time this run's `fact` against a
row measured on a DIFFERENT `fact.mojo`, which is exactly the "wrong artifact
served from cache" failure the test exists to prevent. The check is right to be
red and must not be weakened to green.

## The exact next step

Re-seed the one row. The census is a timing measurement, so this is a Lean run
and belongs to whoever runs the gate, not to a light worker:

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label census-fact -- \
  python3 tools/formal_proof_census.py --only fact --write-baseline
```

`fact`'s last measured cost was **222 s wall / 227.7 s CPU / 2.91 GB peak**
(the `lean-*` row in the committed baseline), so it is a single bounded example
rather than a whole-corpus sweep. `--write-baseline` merges, so the other 92
rows are untouched. The run should flip `fact`'s status from `lean-rejected` to
whatever the corrected contract actually checks to — the `ffe27e1a` message
says the precondition now takes the range `@refines` already claimed, which is
a bug fix to the example and may well make the proof go through.

Then re-run `python3 test_formal_proof_census.py` (with `lib/*.olean` present)
and it should be 61/61.
