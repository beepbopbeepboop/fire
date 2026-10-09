# FORMAL_the_memcheck_ledger_coverage_check_compares_basenames_to_paths

**Area:** FORMAL, the memcheck harness's own self-test.
`test_formal_memcheck.py::test_ledger`'s
`the ledger covers every corpus row on both backends`.

**Status: OPEN, diagnosed, not fixed. Pre-existing on this tree and
unrelated to the subscript-diagnostic work it was found beside.**

## What I ran

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_memcheck.py
    ...
    FAIL  the ledger covers every corpus row on both backends  120 rows for 101 programs
    Results: 55 passed, 1 failed, 2 skipped

## What was seen

`test_ledger` asserts

```python
    check("the ledger covers every corpus row on both backends",
          len(rows) == len(M.memcheck_sources() + M.example_sources()) * 2,
          "%d rows for %d programs" % ...)
```

so it only asks whether the two COUNTS agree — and they do not, because the
ledger's keys and the corpus's paths are in two different namespaces:

```python
>>> list(json.load(open(M.DEFAULT_LEDGER))["rows"])[:2]
['absval.mojo|arm64', 'absval.mojo|x86_64']
>>> M.memcheck_sources()[0]
'/Users/mrs/net/chatgpt/claude/work-516/formal/memcheck/blob_alloc_free.mojo'
```

The ledger is keyed `basename|backend` (that is what
`tools/formal_memcheck.py --write-ledger` writes, and it is what the OTHER two
checks in the same function read: `every ledger row names a verdict` and
`the ledger records the corpus's documented findings` both split on
`os.path.basename(...)`). This one check compares a length against
full-path entries and so never matches anything.

**So the count mismatch is not a stale ledger.** 120 rows for 101 programs is
not 51 missing rows either — it is 101 programs × 2 backends = 202 expected
against 120 written, and the file has been gaining programs (there are 52
`formal/examples` and 8 `formal/memcheck` rows today) without being rewritten.
Both facts are true at once and the check reports neither.

## Why it matters even though it is only a test

`test_formal_memcheck.py` is the one suite that would notice a memcheck row
regressing, and its ledger section currently fails on every run, so the run is
red for a reason that has nothing to do with the corpus. That is the
`tools/suite.py` `expect=` situation in miniature and nobody declared it,
which means this test file has been red-and-tolerated for at least as long as
the ledger has been behind — the memcheck corpus grew from a handful of rows to
eight, and the examples corpus from a few to 52.

## What was expected

Either

1. **the key check be a real coverage check** — build the expected key set the
   way the writer does (`os.path.basename(p) + "|" + backend`) and report the
   programs that are MISSING, which is the only form of this assertion a
   reader can act on; or
2. **the check be dropped**, on the grounds that `--write-ledger` is a manual
   step and a length comparison against a namespace it does not share is not a
   statement about coverage at all.

(1) is the right one: the ledger IS a baseline, and "which programs have no
row" is exactly the question that would have caught it going stale.

## The exact next step

Rewrite `test_ledger`'s first check to compare SETS of `basename|backend` keys
against `{basename(p) for p in memcheck_sources() + example_sources()} ×
{"arm64", "x86_64"}`, and name the missing programs in the failure text. Then
run `python3 tools/formal_memcheck.py --write-ledger` once to bring the file up
to date — which is a deliberate act and not something to do inside the test.

**Not done in the branch that found it:** that branch's claim is the arm64
subscript diagnostics, and rewriting another area's self-test and its committed
baseline from inside it is the merge conflict this project's rules exist to
avoid. The finding is exact enough to be twenty minutes of work.
