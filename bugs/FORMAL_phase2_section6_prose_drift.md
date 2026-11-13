# FORMAL.md §6 phase 2: the prose around the surface rows contradicts the rows

**Area:** `formal/model.py` (the `runtime_abi()` census the rows measure).
**Filed:** 2026-11-13, while closing `gate-formal-doc-truth` (the census
percentage that took the job red). This is the part of that doc's "not done:
the prose copies `--fix` does not reach (§6 rows)" that is still true.

## What is wrong

`FORMAL.md` §6 phase 2 publishes a three-row measured surface:

```
| word-shaped entry points (`runtime_abi`) | 431 | 431 |
| …of which the runtime dylib actually exports | 369 | 369 |
| …reachable with no heap handle … | 323 | 323 |
```

The prose immediately below it does not add up to those rows:

- "not the **430** of §2.2" — §2.2 publishes **431** (and row 1 above, which
  `test_formal_runtime_link.py::_published_phase2_surface` checks against
  `runtime_abi()`, is 431). 430 is a stale copy of the same figure.
- "**56 of the 431** the dylib does not export at all" — the table says 369 of
  the 431 are exported, so the not-exported gap is **62** (431 − 369), not 56.
- "**46 of the 369** … take a `void *`" — this one agrees: 369 − 46 = 323.

The sentence itself explains why rows 2/3 are stale: "the three declarations
added since the last re-measure are defined in `fire_runtime.c`, a default
unit, so the next rebuild counts them as exported, not among the 56". So the
369/323 pair and the 56 gap predate the current 431, and the prose carries the
old gap beside the new total.

## Why nothing caught it

- `test_formal_doc_truth.py` does not read these sentences (its census group
  reads §2.2 and the restatements it knows by name), so the job that was red
  stayed silent on this.
- `test_formal_runtime_link.py` checks rows 1–3 — but it builds the runtime
  dylib and is registered in the `proofs` bucket only, so the gate never runs
  it. The prose gaps are not checked by anything.

## Next step

1. Build the runtime dylib and run `python3 test_formal_runtime_link.py`
   (`proofs` bucket; heavy, ~minutes and a built library) to get the live
   `len(linked)` and `len(linked) - len(handles)` for arm64 and x86_64.
2. Re-measure the three rows and rewrite the two prose gaps from them:
   the §2.2 total to the live `word`, and "N of the 431 the dylib does not
   export" to `word - exported`.
3. Add those two prose figures to a checker (the natural home is
   `_published_phase2_surface` reading them beside the rows, or
   `test_runtime_header_scan.py`'s quote table for the one that is a copy of
   §2.2's `word`), so the next re-measure cannot leave them behind again.

**Done when:** `python3 test_formal_runtime_link.py` passes with the rows
re-measured, and the two prose figures are read by a check that fails if they
disagree with the measured triple.
