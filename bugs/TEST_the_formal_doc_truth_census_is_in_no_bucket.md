# TEST_the_formal_doc_truth_census_is_in_no_bucket: `FORMAL.md`'s numbers are 8 rows stale and the file that measures them runs in no gate

**Area:** TEST (the harness — which tests a gate runs) / DOCS (`FORMAL.md`'s
published counts). Found 2026-10-05 on `work/formal25-5-r2`, while verifying
that `formal/` changes had not made a document's claims false.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_doc_truth.py
  citations: 171 checks
  abi: 129 checks
  opus: 15 checks

doc truth: PASS=425 FAIL=8
```

## What I saw

Eight rows, and **every one of them is `FORMAL.md` restating a count that has
moved** — not a claim about the backend's behaviour:

| the row | `FORMAL.md` says | the tree says |
|---|---|---|
| `§2.2 publishes 668 entry points` | 668 | `runtime_abi()` has **673** |
| `§2.2 publishes 262 word-shaped entry points` | 262 | **266** |
| `§2.2 publishes 406 non-word entry points` | 406 | **407** |
| `§1 says fire_runtime.h declares 565 entry points` | 565 | the header declares **570** |
| `§2.2 restates the non-word count as 406` | 406 | **407** (the same number, stated twice) |
| `§1 says fire_runtime.c is 486 KB` | 486 KB | **491 KB** |
| `§12 says 51 examples` | 51 | **52** |
| `§6 phase 2 publishes 262` | 262 | **266** |

**These are PRE-EXISTING and not this branch's.** Verified by reverting all
three files this branch changed in `formal/` (`formal/model.py`,
`formal/build.py`, `formal/imports.py`) to the pre-branch content and
re-running: the same **8** failures, `PASS=425 FAIL=8` both ways.

## Why it is a HOLE rather than eight stale numbers

**`test_formal_doc_truth.py` is registered in no bucket, so no gate runs it.**
`grep -rn test_formal_doc_truth tools/suite.py` returns nothing and
`python3 tools/suite.py --list | grep -i doc.truth` returns nothing. So the one
file in this repository whose job is *"does the document still say what the code
says"* is a test nobody runs, and eight of its rows have been red long enough
for every count in them to drift by 5 to 8.

This is the failure class `bugs/TEST_bracketed_method_field_set_ask_count_rows_and_the_file_is_in_no_bucket.md`
records for a different file — **a census that is not in a bucket is not a
census**, and the numbers it is watching are exactly the numbers a reader of
`FORMAL.md` will quote. `FORMAL.md` is the document a new contributor reads
first; its §1 and §2.2 are its map of the runtime ABI.

**And the drift is not uniform, which is the part worth noticing.** Five of the
eight are counts that grew as entry points were added (`673` vs `668`, `570` vs
`565`); three are a size and an example count. A file whose rows are *only*
growth-shaped would read as "the tree got bigger", and the cheap reading of
these eight is that. It is not: **`406 → 407` is the non-word count while
`262 → 266` is the word count**, so four entry points became word-shaped — which
is a *change in the shape of the ABI*, not a change in its size, and
`bugs/FORMAL_runtime_library_on_the_link_line.md` §0.3 documents at least one
such change landing in that window (the `typedef` resolution that made six
entry points callable, of which `mojo_close` was declared and `mojo_open` was
not). So a reader of `FORMAL.md` today cannot tell from it which entries are
word-shaped, which is the one fact §2.2 exists to state.

## What is NOT claimed

- **That the eight numbers are wrong.** The test computes them from
  `formal/model.py::runtime_abi()` and the headers, so they are a measurement;
  but *which* side is stale — the doc or the test's expectation — is not settled
  by anything here. Both read the same table.
- **That no gate catches this indirectly.** I checked
  `tools/suite.py` and `--list`; I did not run the gate, so a job that reads
  `FORMAL.md` by another route is not excluded.
- **Any connection between these eight and this branch's changes**, beyond the
  revert measurement above, which is the whole of it.

## The exact next step

Two lines, in this order, and the first is the one that matters:

1. **Register `test_formal_doc_truth.py` in a bucket** (`tools/suite.py`, and
   `docs/` or `check` — it needs no build, no Lean and no memory: it measured
   `PASS=425 FAIL=8` at 0.0 GB, so it is a `tiny` job and costs under a second).
   *This is `tools:gatefix10` / `tools:gatefix11`'s area, not this file's*, and
   the claim says so — a fix in `tools/suite.py` from a branch that does not
   hold that claim would collide. **Which is the argument for this doc: the
   hole is in the registry, and nobody holds the registry.**
2. **Refresh the eight numbers in `FORMAL.md`** from
   `runtime_abi()`, the header scan and the two file sizes, and — for the
   word/non-word pair — say in §2.2 *which* entries changed kind since the last
   refresh, because that is the fact a reader of §2.2 is there for and a bare
   updated pair of numbers would hide.

Rows 1 and 2 should land together: refreshing the numbers with the test
unregistered buys one green run and the drift resumes on the next entry point.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_doc_truth.py
$ grep -rn test_formal_doc_truth tools/suite.py ; echo $?     # no match: 1
$ python3 tools/suite.py --list | grep -i 'doc.truth' ; echo $?   # no match: 1
```
