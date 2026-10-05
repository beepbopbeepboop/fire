# FORMAL_phase2_export_ceiling_is_four_behind: `FORMAL.md` §6 publishes 206 word-shaped exports and the runtime dylib has 210

**Area:** FORMAL, the runtime link line. **Status: OPEN, measured 2026-10-05 on
`work/gatefix11` at `914a32ef`. Unowned.** Found while verifying an unrelated
`formal/model.py` change, and NOT fixed here — see "Why this is not fixed in the
same commit".

## What I ran

```console
$ python3 tools/suite.py formal-runtime-link --no-cache
  runtime dylib: export table: 585 of 586 runtime entry points advertised (0 misresolved, 1 undefined)
  runtime dylib:   declared with no definition in this dylib: py_tokenize
      arm64: 266 word-shaped, 210 of them exported by the runtime library, 170 of those reachable without a heap handle (40 need one the path cannot obtain)
FAIL arm64: 210 word-shaped entry points exported, FORMAL.md §6 phase 2 publishes 206
FAIL arm64: 170 reachable with no heap handle, FORMAL.md §6 phase 2 publishes 166
      x86_64: 266 word-shaped, 210 of them exported by the runtime library, 170 of those reachable without a heap handle (40 need one the path cannot obtain)
FAIL x86_64: 210 word-shaped entry points exported, FORMAL.md §6 phase 2 publishes 206
FAIL x86_64: 170 reachable with no heap handle, FORMAL.md §6 phase 2 publishes 166
155 passed, 4 failed, 159 checks
```

Both architectures agree, so it is a stale publication and not a backend
divergence.

## What it is

`FORMAL.md`'s §"phase 2" table has one column per ARCHITECTURE and neither is
"published" — both are measurements the document asserts as the phase's result,
and `test_formal_runtime_link.py` re-measures and compares against them:

| `FORMAL.md` §phase 2 | arm64 | x86_64 | live, both |
|---|---:|---:|---:|
| word-shaped entry points (`runtime_abi`) | 262 | 262 | 266 |
| …of which the runtime dylib actually **exports** | 206 | 206 | **210** |
| …reachable with no heap handle the formal path cannot obtain | **166** | **166** | **170** |

Two rows are out by the same **+4**, and the total is out by **+4** too, so four
word-shaped entry points landed — exported, and reachable without a heap handle —
and the table did not move with them. The text below the table repeats both
numbers ("166 word-shaped calls are callable", "40 of the 206", "56 of the
262"), so there are seven places to move rather than two.

The row's own summary line is what makes this a red rather than a note: it
prints `266 word-shaped, 210 of them exported…, 170 of those reachable`, so the
build knows all three numbers and disagrees with the document about two of them.

## Why this is not fixed in the same commit

Refreshing a published measurement is the same work whichever branch does it,
and doing it from a branch whose subject is a string-encoding refusal would put
an unrelated count change in a diff nobody expects to carry one. The four new
exports should also be NAMED — "4 more" is a number, and the reason a reader
wants the four is the same reason the row exists: an export nobody reaches is a
promise the runtime makes and the link line does not keep.

It is also plausibly a symptom rather than a defect: if the four landed by
accident — a `static` dropped, an export list widened — then the fix is to
REMOVE four exports, not to write four larger numbers into `FORMAL.md`, and the
two are opposite edits. Nothing here can tell which, and the next step says so.

## The exact next step

1. Find the four: the row's summary line already names the source
   (`runtime_abi()` is `formal/model.py`'s table and it reads every runtime
   header), so `git log -L` on `formal/model.py`'s `runtime_abi` since the
   commit that wrote 262/206/166 — or, more directly, diff the exported-symbol
   list the dylib advertises against the one in that commit.
2. Amend the three table rows in `FORMAL.md`'s phase-2 section (262/206/166 ->
   266/210/170) **and the prose below it** ("166 word-shaped calls", "40 of the
   206", "56 of the 262"), naming the four entries as the table's own style does
   for the ones it counts.
3. Re-run `python3 tools/suite.py formal-runtime-link`.

`formal-runtime-link` is in the `proofs` bucket only, which is why it is not
among the 17 gate failures on `77b24183` — it was never run.