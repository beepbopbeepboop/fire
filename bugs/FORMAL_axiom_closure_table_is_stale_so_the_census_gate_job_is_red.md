# The published axiom-closure table is stale, so `formal-sweep-truth` is RED on
# `master` and nobody has said so

**Area:** FORMAL (the axiom census). Found 2026-10-04 on `work/formal25-3`
while verifying an unrelated change; **NOT FIXED HERE** — the table belongs to
`bugs/FORMAL_native_decide_axiom.md`, which is UNOWNED, and rewriting a
measured table is that document's work rather than a passing note's.

## What I ran

`python3 test_formal_sweep_truth.py` on `master` at `faef18b3`, plus the census
itself in one Lean run so the numbers are the tool's and not a reading of the
failure message:

```console
$ python3 tools/memslot.py --gb 8 --label axc -- python3 -c "
import sys, os, time
sys.path.insert(0, '.')
from formal import admitted as A
import formal.lean as L
lean = L.find_lean(os.getcwd()); lib = A.lean_dir(os.getcwd())
census = A.theorem_axiom_census(lean, lib)
s = A.axiom_census_summary(census, lib)
for mod in sorted(s):
    g = s[mod]
    print(f\"{mod:>10} answered={g['answered']} reaches={len(g['reaches'])} \"
          f\"clean={len(g['clean'])} text_only={len(g['text_only'])} \"
          f\"closure_only={len(g['closure_only'])}\")"
elapsed 4.3s
```

## What I saw

`test_formal_sweep_truth.py` fails, and it is the ONLY failure in 116 tests:

```
FAIL: test_formal_sweep_truth.TestAxiomClosureCensus.test_the_closure_census_says_what_the_text_census_cannot
AssertionError: Tuples differ: (7, 0, 7, 0, 0, 0) != (7, 0, 6, 1, 0, 0)
 Contracts: the closure census moved. asked/reaches/clean/text_only/closure_only/ofReduceBool = (7, 0, 7, 0, 0, 0), the table says (7, 0, 6, 1, 0, 0).
```

**The table is stale, and it is stale in BOTH directions — the library grew and
it got cleaner.** `bugs/FORMAL_native_decide_axiom.md`'s §"the measurement"
table (written by `1afe11a7`, "native_decide: 63 closed-fact sites become
kernel-checked") and `test_formal_admitted.py`'s `AXIOM_CLOSURE` constant carry
the same five numbers, and here is what the tree says now:

| module | asked | reaches | clean | text_only | closure_only | `ofReduceBool` |
|---|---:|---:|---:|---:|---:|---:|
| `Contracts` | 7 **(+0)** | 0 | **7 (+1)** | **0 (−1)** | 0 | 0 |
| `ProofLib` | **264 (+9)** | **43 (−8)** | **211 (+19)** | 3 | **7 (−2)** | 0 |
| `Refine` | **29 (+7)** | 0 | **29 (+9)** | 0 | **0 (−2)** | 0 |
| `X86` | **78 (+5)** | 2 | **75 (+6)** | **0 (−1)** | 1 | 0 |
| `work` | 18 | 0 | 17 | 0 | 1 | 0 |
| **total** | **396 (+21)** | **45 (−8)** | **339 (+35)** | **3 (−2)** | **9 (−4)** | **0** |

Three things in there are worth reading rather than transcribing:

* **`Contracts`' one `text_only` is gone.** The doc names it —
  `Contracts.spec_triple_ne_identity`, "a losing tactic alternative is still
  text". It is still in `lib/Contracts.lean` at line 332, and it no longer
  carries a decide tactic, so the `text_only` column is 0 for the module. The
  column's own explanation ("a replacement would have changed nothing") is
  exactly right and is now demonstrated rather than argued.
* **`reaches` FELL by 8 while `asked` rose by 21.** The `53 of 375` in the
  document's title is now **45 of 396**, so the doc's headline claim ("53 is what
  the sites were standing in for") needs restating as a claim about
  `1afe11a7`'s tree and not about this one. 21 commits have touched `lib/` since,
  including `4a90fe65`/`a40f1b54` (the `//` floor correction, closed by proof
  rather than by decide) and `6f2bbe97` (an x86-64 read proved by EVALUATING it).
* **`text_only` is the column that moved least and it is the one the instrument
  exists for**, which is the argument the document makes about a losing tactic
  alternative being text — so the three rows that remain are the ones to keep
  naming: `ProofLib.DylibExport.Semantics_refutable`,
  `ProofLib.DylibExport.backward_branch_in_image` and
  `ProofLib.DylibExport.backward_branch_run_none`.

## What I expected

Not this, in the sense that matters: **`formal-sweep-truth` is a registered gate
job with no `expect=` marker, so `make gate` is red on `master` today** and the
red is in a table nobody re-derives. `bugs/OPEN_WORK.md` and the document itself
both still say the closure census is DONE, which is true of the INSTRUMENT and
not of its published numbers.

## The exact next step

One edit in each of two places, and the numbers above are the edit:

1. `test_formal_admitted.py`'s `AXIOM_CLOSURE` — five tuples to
   `Contracts (7, 0, 7, 0, 0, 0)`, `ProofLib (264, 43, 211, 3, 7, 0)`,
   `Refine (29, 0, 29, 0, 0, 0)`, `X86 (78, 2, 75, 0, 1, 0)`,
   `work (18, 0, 17, 0, 1, 0)`. The test then asserts them in both directions
   (`test_formal_sweep_truth.py::TestAxiomClosureCensus` compares the live census
   against this constant, and the assertion message already names which column
   moved).
2. `bugs/FORMAL_native_decide_axiom.md` — the §"the measurement" table with the
   same rows plus a **total** row, the title's "53 of `lib/`'s 375 theorems"
   restated as 45 of 396 with the commits named that moved it, and the
   `spec_triple_ne_identity` row deleted from the `text_only` list with the
   sentence "`Contracts` is now 0 for that column, which is the claim the column
   makes, demonstrated".

Re-run `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py`
(116 tests, ~36 s, peak 1.2 GB) and `test_formal_admitted.py` (Lean-free).

**Why it is filed rather than fixed here:** it is not this task's area, the
document that owns the numbers is unowned but specific, and a table that is
rewritten by whoever noticed it is how two documents end up disagreeing about
which one is the measurement. **The ratchet that would have caught this is the
one the census itself is**: `AXIOM_CLOSURE` IS the anti-rot, and it did its job
— it went red rather than letting the corpus drift silently. The only defect is
that nobody is on the hook for a red in it.