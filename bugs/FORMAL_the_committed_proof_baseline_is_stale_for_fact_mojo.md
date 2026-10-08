# `tools/formal_proof_census_baseline.json`'s `fact` row no longer matches `formal/examples/fact.mojo`, so `formal-proof-census-tool` is RED on master

**Area:** FORMAL proof ratchet. **Status: OPEN, found 2026-10-07 on
`work/formal132-docs` while checking the old "the baseline covers 52 of 93
examples" report, which is no longer accurate — the baseline now has 93 rows and
that report was deleted with its fix.** This is the residual of the same
instrument: the row count is right, one row's `source_sha256` is not.

## What I ran, what I saw, what I expected

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
...
FAIL: test_each_row_is_tied_to_the_example_it_measured
AssertionError: '66e21e6ab48422dbe6c4fdca1b5fc98f3c033e39109799d687ffde1b114dd23b'
  != 'b2bbaf519f24c780c4ff33d73400b42a72b024c512007f65c7f0e69a38360606'
  : fact.mojo has changed since the baseline was written; re-seed with
    --write-baseline so the comparison is against this program
Ran 61 tests in 0.435s
FAILED (failures=2)
```

(The second failure, `test_library_state_agrees_with_the_question_it_asks`, is a
different thing: it asserts `lib/*.olean` exists and this is a clean worktree
where the `prooflib` build has not run. It is not the row staleness and is not
counted here.)

`fact` is the ONLY stale row, measured over all 93:

```console
$ python3 - <<'EOF'
import json, hashlib, os
d = json.load(open("tools/formal_proof_census_baseline.json"))
for stem, rec in d["records"].items():
    p = os.path.join("formal/examples", stem + ".mojo")
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    if h != rec.get("source_sha256"):
        print(stem, "CHANGED", rec.get("status"))
EOF
fact CHANGED lean-rejected
```

## Why, and why it is a real red rather than a bookkeeping nit

`ffe27e1a` ("`formal/examples/fact.mojo`'s contract is no longer FALSE — the
PRECONDITION takes the range `@refines` already claimed", 2026-10-05 17:50)
edited the example. The baseline was regenerated on the `formal66-loop-invariants`
branch by `07cc3260` and merged; that branch's tree did not carry `ffe27e1a`'s
edit, so the committed `fact` row still records the PRE-`ffe27e1a` program
(`source_sha256 66e21e6…`, status `lean-rejected`) against a tree whose file
hashes `b2bbaf…`.

`test_each_row_is_tied_to_the_example_it_measured` exists precisely to refuse
this: a row must not claim a verdict for a program it did not measure. The tool
itself reads a CHANGED example as `INFO not in the baseline` and does not
compare it (`test_a_changed_example_is_not_compared`), so the ratchet is not
comparing the current `fact.mojo` at all — the committed row is dead weight and
the test is the only thing that notices. The fix is to re-bank that row, not to
edit the stored hash: writing the new hash onto the old verdict would be exactly
the "a baseline nobody can trust" failure the row shape exists to prevent.

## The exact next step

One bounded `lean` measurement, through the census tool (which goes through
`formal/lean.py::run_lean`), for the one stem:

    python3 tools/memslot.py --gb 8 --label census-fact -- \
      python3 tools/formal_proof_census.py --only fact --write-baseline

Measured cost of that row in the committed baseline: **`wall_s` 222.5,
`lean_peak_gb` 2.91, `phase` check** — so it is ~4 minutes and well inside the
8 GB reservation, not the multi-hour whole-corpus pass. `--write-baseline`
MERGES, so only `fact` moves. Then `python3 test_formal_proof_census.py` should
be back to the single `lib/*.olean` failure in a clean worktree (and 0 failures
where `prooflib` has run).

The `--arch x86_64` half of the ratchet still has no baseline file at all
(`tools/formal_proof_census_baseline_x86_64.json` does not exist); that is a
separate, larger item and is not what this row is about.

## Reproducing

    export PATH=/opt/homebrew/bin:$PATH
    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
    # 61 tests, 2 failures; the fact one is this doc, the lib/olean one is the
    # clean-worktree artefact described above.
