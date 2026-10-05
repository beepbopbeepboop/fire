# The runtime export ladder is five behind, and five prose copies of the ABI census are stale with it

Found 2026-10-04 while making `len()` ask the runtime what a type-erased word
is instead of assuming a list (`mojo_len_of_word`, one new runtime export), whose
fix adds one rung to `test_runtime_header_scan.py`'s declaration ladder.

## What I ran

```sh
python3 test_runtime_header_scan.py
```

**On this branch's base, before my change** — 38 passed, 9 failed:

```
FAIL  fire_runtime.h: 565 declarations scanned: got 570
FAIL  formal/model.py: the quoted total count is 673: the text says 668; `runtime_abi()` says 673
FAIL  formal/model.py: the quoted total count is 673: the text says 668; `runtime_abi()` says 673
FAIL  bugs/FORMAL_known_limits.md: the quoted total count is 673: the text says 668; `runtime_abi()` says 673
FAIL  bugs/FORMAL_known_limits.md: the quoted word count is 266: the text says 262; `runtime_abi()` says 266
FAIL  bugs/FORMAL_known_limits.md: the quoted box count is 407: the text says 406; `runtime_abi()` says 407
FAIL  bugs/FORMAL_known_limits.md: the quoted word count is 266: the text says 262; `runtime_abi()` says 266
FAIL  bugs/FORMAL_known_limits.md: the quoted total count is 673: the text says 668; `runtime_abi()` says 673
FAIL  build_stdlib_dylib.py: the quoted fire_runtime_h count is 570: the text says 565; `runtime_abi()` says 570
```

Every one of those is a 5-or-more gap on a file I did not touch. `rthdrscan`
is registered in `tools/suite.py` with **no `expect=`**, so this is a red in
`make check` that nothing accounts for.

## Why it drifted

The ladder in `test_every_declaration_is_seen` was last moved to 565 by
`bugs4-9`. Two commits after that added runtime exports and did not move it or
say so:

| commit | `runtime/fire_runtime.h` | 
|---|---|
| `24f1e5e8` (merge of `work/bugs4-9-c`) | the 565 ladder entry |
| `a35765a0` "str's `[start[, end]]` window was dropped…" | +22/-8 lines of header |
| `d8cdca63` "a compiled pattern's `.split()` and a pointer parameter's null default" | +5 lines of header |
| base of the branch that filed this | **570** scanned |

The same two commits left the five prose copies of the census behind too, which
is the whole point of `test_the_quoted_census_is_the_live_census`: it is a check
that exists precisely so a number cannot go stale in two places at once, and it
is the only thing that noticed.

## Exact next step

1. The five prose numbers, all mechanical, all named by the failing checks:
   - `formal/model.py`: `668` -> `674`, in BOTH the "the shape answers the same
     question for all N entry points the headers declare" comment and the
     "a rule that refuses all N entry points for that reason" one. Two
     patterns, two sites — grep for the digits, they are the only occurrences
     the patterns match.
   - `bugs/FORMAL_known_limits.md`: the `entry points declared` row `668` ->
     `674`, `every type crossing the boundary is one word` `262` -> `267`,
     `a box in an argument or the return` `406` -> `407`, and the
     `**262 of 668** is what a link line converts` sentence -> `**267 of 674**`.
     (`FORMAL_known_limits.md` is a formal-area doc; it is not in the claims of
     the branches that caused the drift, which is why it is being left here.)
   - `build_stdlib_dylib.py`: the `fire_runtime.h`'s `565` entry points comment
     -> `571`.
2. Re-run `python3 test_runtime_header_scan.py`; it should be 47/47 with no
   FAIL. Every number is `runtime_abi()`'s, so re-derive rather than
   transcribing: `len(reflect.collect_runtime_exports_h('runtime/fire_runtime.h'))`
   and `formal.model.runtime_abi()`.
3. The structural half, which is what would have stopped this: the ladder is a
   count, so a new export is invisible to it unless a human counts. Adding a
   rung per name is the existing discipline and it is what failed twice in a
   row — both times on a merge, not on a single branch, which is the tell. A
   `git log`-scoped check ("every commit touching `runtime/fire_runtime.h`
   since <date> is named in this ladder") is not obviously expressible in the
   runner, but the merge-range case is: the ladder comment already records whose
   base a rung was counted from, and both of these commits changed the count
   without touching a file whose check reads it.

## Not mine to fix

`bugs4-9`, `a35765a0` and `d8cdca63` are in other claims'
(`formal*`, `bugs7-1`) write sets, and `formal/model.py`,
`bugs/FORMAL_known_limits.md` and `build_stdlib_dylib.py` are formal-area files
under active merge pressure. The `fire_runtime.h` ladder entry itself IS
already fixed on this branch — `mojo_len_of_word` (+1) and the five
unattributable names it sits on top of are both named there — so what remains
is three files' worth of prose numbers, which is one sed away and somebody
else's to run.