# `formal-proof-census-tool` is red on master: `fact.mojo`'s source changed after the baseline was written

**Area:** FORMAL, the proof-regression ratchet.

**Status: open, one row, and it is not the row this replaces.**
`tools/formal_proof_census_baseline.json` was
re-banked on 2026-10-06T04:04:35Z (`tag: formal-proof-census-v2`) and now holds
**93 records for the 93 `formal/examples/*.mojo`** — so the "52 rows against a
93-file corpus" defect is FIXED, and
`test_formal_proof_census.TestCommittedBaseline.test_every_example_has_a_row_and_every_row_a_status`
passes. What remains is a STALE ROW: one example's source changed after the
baseline was written.

## What I ran, what I saw, what I expected

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
...
FAIL: test_each_row_is_tied_to_the_example_it_measured
  self.assertEqual(r.source_sha256, on_disk,
      f"{stem}.mojo has changed since the baseline was written; re-seed with "
      f"--write-baseline so the comparison is against this program")
AssertionError: '66e21e6ab48422dbe6c4fdca1b5fc98f3c033e39109799d687ffde1b114dd23b'
              != 'b2bbaf519f24c780c4ff33d73400b42a72b024c512007f65c7f0e69a38360606'
  : fact.mojo has changed since the baseline was written; ...
```

**Exactly one of the 93 rows mismatches**, measured off the baseline itself:

```console
$ python3 - <<'EOF'
import json, os, hashlib
d = json.load(open("tools/formal_proof_census_baseline.json"))
bad = [s for s, r in d["records"].items()
       if hashlib.sha256(open(f"formal/examples/{s}.mojo", "rb").read()).hexdigest()
       != r.get("source_sha256")]
print(len(bad), bad)
EOF
1 ['fact']
```

`formal/examples/fact.mojo` no longer hashes to the `source_sha256` the baseline
records, so the ratchet's comparison for that row is against a program that is
not in the tree. The comparison still runs (the other 92 rows are tied to their
sources), but `formal-proof-census-tool` — a registered `tiny` gate job — exits
non-zero, and a red gate job is the whole of why this is filed rather than left
to the next re-bank.

**The other failure in the same file is NOT this doc's.** `test_library_state_
agrees_with_the_question_it_asks` fails on a fresh worktree because `lib/*.olean`
are untracked build artifacts (`git ls-files lib/` lists only the eight `.lean`
sources) and are absent until a Lean build runs; it is a property of the
checkout, not of the tree, and it is green once the library has been built.

## The exact next step

Re-seed the one row. `--only` narrows the workload and `--write-baseline`
MERGES, so this rewrites only `fact`'s record:

```console
$ python3 tools/memslot.py --gb 8 --label census -- \
    python3 tools/formal_proof_census.py --only fact --remeasure --write-baseline
```

`--remeasure` is required rather than optional: without it a row already in the
baseline is left as it is (the tool's own docstring: `--only <stem> --remeasure
--write-baseline` is how a row written from an OLD source is re-derived). The
command is a Lean run — the measurement is `compile_formal(prove=True,
check=True)`, the call `fire.py build --formal` makes — which is why it is filed
here rather than closed: a light worker is not permitted a Lean proof run beyond
the one test that covers its own change, and this row needs a real elaboration
of `fact`'s proof to be re-timed.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
# 61 tests, 2 failures: this row, plus the fresh-worktree lib/ one above.
```
