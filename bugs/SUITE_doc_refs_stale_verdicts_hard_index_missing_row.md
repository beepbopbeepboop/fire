# SUITE: `doc-refs-stale-verdicts` is red on master — the `bugs/hard` index is missing a row

Status (2026-11-17): open. Found while verifying a different fix (branch
`work/bug-land-land-doc-summary-cites-deleted`, which ran
`python3 test_dangling_doc_refs.py` as its existing-test check); the two files
this failure reads are untouched by that branch, so it is pre-existing on master.

## What I ran

```
python3 test_dangling_doc_refs.py     # the `doc-refs-stale-verdicts` job, in `check`
```

## What I saw

```
FAIL: test_every_hard_doc_is_indexed (__main__.HardIndexIsTrue.test_every_hard_doc_is_indexed)
AssertionError: Lists differ: ['GATE_recover_land_remainder.md'] != []
```

`bugs/hard/GATE_recover_land_remainder.md` (added to master by `7c8d85a5f`,
"bugs: GATE_recover_land_remainder") has no row in `bugs/hard/README.md`, the
hand-maintained index that `HardIndexIsTrue` checks in both directions (every
indexed doc exists, every on-disk doc is indexed). The doc landed without its
index row, and the `check` job has been red since.

## What I expected

7/7 in `test_dangling_doc_refs.py`: every `bugs/hard/*.md` except `README.md`
carries a row in the index table.

## Exact next step

Add the row in alphabetical position in `bugs/hard/README.md` (between
`FORMAL_svc_exit_handling_incomplete.md` and
`GATE_red_recover-land_2026-11-02-part5.md`), matching the table's shape:

```
| `GATE_recover_land_remainder.md` | see doc | workers |
```

then re-run `python3 test_dangling_doc_refs.py` and confirm 7/7.
