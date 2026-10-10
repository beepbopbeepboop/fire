# `formal-proof-census-tool` is red because `fact.mojo` changed after the baseline was written, and the write that banked the 41 new rows did not refresh it

**Area:** FORMAL, `tools/formal_proof_census_baseline.json` and
`test_formal_proof_census.py`. **Status: OPEN, measured 2026-10-06 on
`work/formal113-docs`.** This is the RESIDUAL of the baseline that held 52 rows
against a 93-file corpus: `07cc3260` fixed that (the baseline now holds all 93),
and what is left is one stale row that keeps the registered gate job
`formal-proof-census-tool` red on master.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
...
FAIL: test_each_row_is_tied_to_the_example_it_measured
AssertionError: '66e21e6ab48422dbe6c4fdca1b5fc98f3c033e39109799d687ffde1b114dd23b'
                != 'b2bbaf519f24c780c4ff33d73400b42a72b024c512007f65c7f0e69a38360606'
 : fact.mojo has changed since the baseline was written; re-seed with
   --write-baseline so the comparison is against this program
Ran 61 tests in 0.148s
FAILED (failures=2)
```

The other failure, `test_library_state_agrees_with_the_question_it_asks`, is
environmental: it asserts `lib/` has no missing `.olean`, and a fresh worktree
has none until the library is built. It is not this doc's subject and is
expected to clear on the integrator's tree (or when `prooflib` has run).

## What I saw

The baseline holds a row for every one of the 93 examples (`load_baseline` is
93, `corpus` is 93, `missing` is `[]`), so `07cc3260`'s banking is complete. But
one row's recorded `source_sha256` no longer matches its example:

```
$ python3 - <<'EOF'
import json, hashlib, os
rec = json.load(open('tools/formal_proof_census_baseline.json'))['records']
for stem in rec:
    p = os.path.join('formal/examples', stem + '.mojo')
    h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    if rec[stem].get('source_sha256') != h:
        print(stem, rec[stem].get('status'))
EOF
fact lean-rejected
```

`fact` is the ONLY stale row. The reason is a merge order, not a bug in the
banking run: `07cc3260` regenerated the baseline on a tree where `fact.mojo` was
still the pre-`ffe27e1a` text, and `ffe27e1a` ("`formal/examples/fact.mojo`'s
contract is no longer FALSE — the PRECONDITION takes the range `@refines`
already claimed") is **not** an ancestor of `07cc3260`. Both are on master, so
the committed baseline describes a program the tree no longer has.

`test_each_row_is_tied_to_the_example_it_measured` is right to fail: the row's
`source_sha256` is the anchor that makes a verdict a claim about a program rather
than about a filename, and comparing `fact`'s old verdict against its new source
would be exactly the "silent green over an unseen change" the ratchet exists to
prevent.

## The exact next step

Re-bank `fact`, which is one bounded Lean run through the tool's own launcher
(`formal/lean.py::run_lean`), not a hand-edited JSON:

    export PATH=/opt/homebrew/bin:$PATH
    python3 tools/memslot.py --gb 8 --label census-fact -- \
      python3 tools/formal_proof_census.py --only fact --remeasure --write-baseline

`--remeasure` is required, not optional: the verdict cache is content-addressed
on the proof's exact bytes, and this proof's bytes changed with the source, so a
replayed write would either miss (cold cache) or keep a timing and verdict that
belong to the old program. `--write-baseline` merges, so the other 92 rows are
untouched. `fact`'s recorded cost is ~222 s wall / 2.9 GB, and a cold tree also
builds `lib/*.olean` first (~90 s a module); the run is therefore minutes, not
the full census's 5219 s, but it is a real Lean run and belongs to whoever is
allowed to spend it.

This is filed rather than fixed here because this branch is a light worker: the
task's own rule is "never run a lean proof run beyond the one test that covers
your change", and re-banking a baseline row is not that test.

## Why the coverage doc is gone

The doc that filed the 52-of-93 gap is deleted in the same commit: its subject is
fixed by `07cc3260`, and this file carries what remains. The pinning test for the
fix is `test_formal_proof_census.py::TestCommittedBaseline::
test_every_example_has_a_row_and_every_row_a_status`, which is green.
