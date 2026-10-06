# `AXIOM_CLOSURE` is stale for FIVE of its SIX modules, and one of the five has `reaches` and `text_only` SWAPPED

**Area:** tests (`test_formal_admitted.py`'s `AXIOM_CLOSURE`, asserted by
`test_formal_sweep_truth.py::TestAxiomClosureCensus`). **Status: OPEN, measured,
PRE-EXISTING on `master` (77b24183), not fixed.** Found 2026-10-04 while merging
five finished formal branches into `work/merge-formal27a`. It is not caused by
them: none of the five touches `lib/` or `formal/admitted.py` (`git diff
master..HEAD -- lib/ formal/admitted.py` is empty), and the pinned numbers do
not describe master's own library.

**2026-10-05 (`work/gatefix12`): still open, one module this time, and the
arrival is now MEASURED — read "Addendum" at the end before re-pinning.** The
table was re-derived since this was filed (its `ProofLib` row is 297 where this
file's table says 255, and `IEEE754` reads the way this file measured it), and
today the loop stops on `ProofLib` alone. The cause is not a new bug but the
growth the model work brought: `lib/ProofLib.lean` has gained ~833
`bv_decide`/`native_decide` SITES since these ceilings were derived, in a
handful of very large step-lemma declarations, so the SITE pins are ~833 behind
while the THEOREM pins are 14 behind. Both are the same fact and they are
correctly different numbers; §"Addendum" has the measurements and what it means
for each pin.

**It is invisible until the library is BUILT**, which is why it has survived: the
class `skipTest`s without `lib/ProofLib.olean`, and the gate normally builds that
behind the `prooflib` dep — so a worktree that has never run a Lean-backed test
never sees it. My session built it at 22:35 as a side effect of running the
narrow formal suites, and the next run of the class went red.

## What I ran, what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
FAIL: test_the_closure_census_says_what_the_text_census_cannot
AssertionError: Tuples differ: (7, 0, 7, 0, 0, 0) != (7, 0, 6, 1, 0, 0)
 : Contracts: the closure census moved. asked/reaches/clean/text_only/
   closure_only/ofReduceBool = (7, 0, 7, 0, 0, 0), the table says (7, 0, 6, 1,
   0, 0).
```

That is the FIRST mismatch the loop reaches (`AXIOM_CLOSURE` is a dict, `Contracts`
is its first key), and it stops there. Read the whole census directly to see the
rest — same instrument, same library, one process:

```python
from formal import admitted as A
lib = A.lean_dir('.')
summary = A.axiom_census_summary(A.theorem_axiom_census('/Users/mrs/bin/lean', lib), lib)
```

`lean --version` is 4.32.2, which is what `lean-toolchain` pins
(`leanprover/lean4:v4.32.2`), so this is the toolchain the table claims to have
been read out of:

| module | pinned `AXIOM_CLOSURE` | measured now | what moved |
|---|---|---|---|
| `Contracts` | (7, 0, 6, **1**, 0, 0) | (7, 0, 7, **0**, 0, 0) | the one `text_only` site is kernel-checked |
| `IEEE754` | (24, **19**, 5, **0**, 0, 0) | (24, **0**, 5, **19**, 0, 0) | **`reaches` and `text_only` are SWAPPED** |
| `ProofLib` | (255, 51, 192, 3, 9, 0) | (**267**, 43, 214, 3, 7, 0) | 12 more theorems asked |
| `Refine` | (22, 0, 20, 0, **2**, 0) | (**29**, 0, 29, 0, **0**, 0) | 7 more asked, no closure-only left |
| `X86` | (73, 2, 69, 1, 1, 0) | (**78**, 2, 73, 1, 2, 0) | 5 more asked |
| `work` | (18, 0, 17, 0, 1, 0) | (18, 0, 17, 0, 1, 0) | — agrees |

## Why this is filed rather than fixed by copying the numbers in

Three of the five rows are the boring kind: `lib/` grew under them (`asked`
255→267, 22→29, 73→78), so the pins are behind their own library and re-pinning
is a transcription. **The `IEEE754` row is not that.** Its `reaches` and
`text_only` counts have traded places: 19 sites that the table says reach a
decide axiom now reach none, with `clean` (5) and `of_reduce_bool` (0) unchanged
and `answered` (24) unchanged. Only three things can do that:

1. `lib/IEEE754.lean` stopped using a decide tactic in those 19 theorems while
   keeping 24 declarations — which would ALSO have to leave `text_only` at 0,
   because `text_only` is "the site's own text names a decide tactic", so a
   tactic removal moves sites OUT of both columns, not from one into the other;
2. `formal/admitted.py`'s `axiom_site_tactic` / `axiom_census_summary` changed
   what it calls a "site" — the classifier moving under a pinned measurement is
   exactly what the swap looks like;
3. the census's `LEAN_PATH` is picking up a different `IEEE754`.

(1) is excluded by its own arithmetic, so it is (2) or (3), and **both are a
question about the instrument rather than about the tree**. Refreshing the table
without answering it would publish five numbers, one of which is a swapped pair,
and the swap would then be indistinguishable from a fact about `lib/`. That is
why the fix is not "paste the numbers in".

The class's own later assertions are the reason to read this rather than to
widen the tolerance: it requires `reaches + clean + text_only + closure_only ==
answered` (which the measured rows satisfy — this is a mis-classification or a
mis-source, not a lost theorem), requires that SOME theorem reach a decide axiom
(`every_site` non-empty), and requires zero `Lean.ofReduceBool`. Those still hold
on the measured run, so the mechanism works; it is the published row that does
not describe it.

## The exact next step

1. **Answer the `IEEE754` swap before touching the table.** Diff what
   `theorem_axiom_census` collects for `IEEE754` now against what
   `AXIOM_CLOSURE`'s comment says it collected ("19 reach a decide axiom and 5
   are kernel-checked"): print `census["axioms"]["IEEE754"]` and
   `census["sites"]["IEEE754"]` and look at one theorem end to end. If
   `axiom_site_tactic` now returns `None` for the axiom names `lib/IEEE754.lean`
   actually produces, the classifier is the bug, and `test_formal_axioms.py`'s
   own header is where the spelling belongs —
   `formal/lean.py::GENERATED_AXIOM_RE` is the one pattern that got it right, and
   it uses a greedy `.+` because a lazy one would hand `DylibExport` to `decl`
   and fail to match at all.
2. Re-pin the three boring rows from the measured run, with the date and the
   `lib/` growth in the comment the way `IEEE754`'s own comment already does
   ("Read out of a real `#print axioms` run over all 24 declarations").
3. **Do not loosen the assertion.** The table is a measurement and this test is
   the only thing that notices when it stops being one; a widened comparison
   converts a stale row into a permanently silent one.
4. If the library build is what exposes this, consider whether
   `formal-sweep-truth`'s registration should `deps` on `prooflib` — it is in
   `check` and today it SKIPS in every worktree that has not built the library,
   so the row can rot unnoticed in exactly the worktrees where nobody is running
   the Lean tier. That is a registration question, not a test change.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label pb -- python3 tools/suite.py prooflib
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
```
---

## Addendum 2026-10-05 (`work/gatefix12`, at 0487369a): ONE row stale, and the arrival measured

Reached from the `formal-sweep-truth` gate failure in
`bugs/`-terms: that job's `TestAxiomClosureCensus` SKIPs on a worktree with no
`lib/ProofLib.olean`, so this row only speaks on a tree that has run something
Lean-backed. It has, and the class is red again:

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label pb -- python3 tools/suite.py prooflib
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
FAIL: test_the_closure_census_says_what_the_text_census_cannot
AssertionError: Tuples differ:
- (311, 60, 243, 0, 8, 0)
+ (297, 46, 243, 0, 8, 0)
 : ProofLib: the closure census moved. asked/reaches/clean/text_only/
   closure_only/ofReduceBool = (311, 60, 243, 0, 8, 0), the table says
   (297, 46, 243, 0, 8, 0).
```

So the table was re-derived after this doc was filed — `IEEE754` now reads the
way this doc MEASURED it, and `ProofLib`'s pinned `asked` is 297 where the table
here shows 255 — and **one** row is behind: `asked` 297 → **311** and `reaches`
46 → **60**, with `clean` (243), `text_only` (0), `closure_only` (8) and
`of_reduce_bool` (0) all unmoved. The partition still holds exactly
(60 + 243 + 0 + 8 = 311), which is this doc's own test that a moved row is a
mis-classification or a mis-source rather than a lost theorem.

**`asked` is a declaration count, and 14 is all that moved there.** Measured
Lean-free, straight off the source:

```python
>>> from formal import admitted as A
>>> lib = A.lean_dir('.')
>>> rows = A.library_theorems(lib)['ProofLib']
>>> sum(1 for q, r in rows.items() if r.get('public', True))
311
```

(312 declarations, of which `ifUpdate_congr` is the one `private` the census
does not ask about.) So `lib/ProofLib.lean` gained 14 public declarations since
2026-10-04, and every one of them reaches a decide axiom.

### The SITE pins are ~833 behind the same arrival, and that is not a contradiction

`test_formal_admitted.py truth` is red on the same fact, at the site level:

```
FAIL  the Lean library's trust counts are pinned
      ProofLib: 1518 native_decide/bv_decide site(s), the ceiling is 685 (+833)
FAIL  the replaced native_decide count is what it claims
      FORMAL.md §7 row 10 publishes 707 site(s) remaining and lib/ has 1540
```

`rg -c 'bv_decide|native_decide' lib/ProofLib.lean` says 1545, so `library_trust`
is counting sites, not over-counting them, and the ceiling is simply behind. The
gap between "+833 sites" and "+14 theorems" is the finding, not a mystery: the
sites arrived inside a few very large step-lemma declarations — the same file
prints "1540 site(s) over 81 theorem(s)", with `work_step_stur` at 66 sites,
`work_step_tst` at 65 and `work_step_cmn` at 64 — so **a site is not a theorem
and the two pins are not supposed to move together**. `AXIOM_CLOSURE` counts
declarations by what their closure reaches; `LIBRARY_TRUST` counts tactic sites
in the text. `FORMAL.md` §7's `remaining 707` is the third copy of the same
number, and `test_formal_admitted.py` already checks that all the copies agree
("the axiom-carrying tactic count is in four places and they disagree").

### What this does NOT change about the fix

Still not "paste the numbers in", for the reason the section above gives, now
with a second one:

1. **`AXIOM_CLOSURE["ProofLib"]`**: +14 asked and +14 reaches with `clean` pinned
   is the shape "the library grew", and re-pinning it is a transcription — but
   it is a transcription of a number this doc has just watched go stale twice,
   so it wants the arrival named (`lib/ProofLib.lean` +14 public declarations,
   2026-10-05) in the row's comment the way `IEEE754`'s already is.
2. **`LIBRARY_TRUST["ProofLib"]`'s ceiling and `FORMAL.md` §7's total are a
   PAY-DOWN decision, not a transcription.** +833 sites is not drift, it is a
   debt that arrived with the model work, and FORMAL.md §7 row 10's LEDGER is
   where that decision is written down: a ceiling that goes up is a statement
   that the debt is accepted, and the `native_decide` → `decide` replacements in
   `test_formal_admitted.py::NATIVE_DECIDE_REPLACED` are how it is
   paid. That doc's 2026-10-04 status says `test_formal_admitted.py` was green;
   it is not, and the two rows above are the reason.
3. Do not widen either assertion. Both tables are measurements, and both tests
   are the only things that notice when they stop being one.

### This doc's step 4 is now answered, and the answer is not a `prooflib` dep

Step 4 asked whether `formal-sweep-truth` should `deps` on `prooflib`, on the
grounds that the class SKIPs in every worktree that has not built the library.
It should not, and the class's skip is unchanged by the 2026-10-05 fix:

* `formal/x86_64_endtoend_test.py` now establishes the library itself
  (`ensure_lean_ready` → `formal/lean.py::ensure_library`, locked and
  content-addressed), because it is the one emitter of four that generated
  `import X86` proofs without asking — its one caller with no `prooflib` dep is
  `formal-sweep-truth`, and that is what the gate failure was.
* `TestAxiomClosureCensus` runs BEFORE that (classes run alphabetically), so in
  a cold worktree it still skips, exactly as before, and in a warm one it runs
  and says what this addendum says. The registration keeps `deps=['preflight']`
  and takes `mem='module'`, so `check` still does not pay for the 27 MB build.
* The consequence to keep in mind: **building the library in a worktree is what
  turns this row from invisible into red.** That is not a reason to stop
  building it — it is the reason this table needs a re-derive rather than
  another worktree that never runs Lean.

### Reproducing (2026-10-05 figures)

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label pb -- python3 tools/suite.py prooflib
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
$ python3 test_formal_admitted.py truth        # the two SITE rows above
```

---

## Addendum 2026-10-05 (`work/merge-formal39`): the re-derive is DONE, and the answer was two rows

Found while merging `work/formal36-verified-peephole`, which added
`lib/Peephole.lean`. Both items below were this doc's subject arriving again, and
both were invisible to any assertion. **Both are now fixed in the same merge, from
a measurement rather than a transcription — so this addendum is the record of the
fix, not a new queue entry.** Step 2 of "The exact next step" above is answered;
step 1 (the `IEEE754` swap) was already answered by the `gatefix12` re-derive and
is not re-opened here, and step 3 (do not loosen the assertion) is honoured — the
assertion is untouched.

**What the tree said and what it measured, on one run of the same instrument**
(`A.theorem_axiom_census` through `formal/lean.py::run_lean`, pinned
`leanprover/lean4:v4.32.2`, after the library was built):

| module | pinned before | measured | verdict |
|---|---|---|---|
| `Contracts` | (7, 0, 7, 0, 0, 0) | (7, 0, 7, 0, 0, 0) | unchanged |
| `IEEE754` | (24, 19, 5, 0, 0, 0) | (24, 19, 5, 0, 0, 0) | unchanged |
| `ProofLib` | (311, 60, 243, 0, 8, 0) | (311, 60, 243, 0, 8, 0) | unchanged |
| `Refine` | (29, 0, 29, 0, 0, 0) | (29, 0, 29, 0, 0, 0) | unchanged |
| `X86` | (144, 2, 141, 0, 1, 0) | (144, 2, 141, 0, 1, 0) | unchanged |
| `work` | (19, 0, 17, 0, 2, 0) | (19, 0, 17, 0, 2, 0) | unchanged |
| **`Specs`** | (55, 0, 55, 0, 0, 0) | **(66, 0, 66, 0, 0, 0)** | **stale — re-pinned** |
| **`Peephole`** | *absent* | **(12, 1, 8, 0, 3, 0)** | **unmeasured — row added** |

Six of the eight rows were already right, which is the answer to "is the table
drifting or was it one arrival": it was arrivals, and two of them. `Specs` moved
because the specification layer has grown since its row was pinned, and it moved
in the shape that says the arrival is specifications and not new trusted
evaluation — `asked` and `clean` rise together and `reaches` stays 0. `Peephole`
had no row at all, and `test_formal_sweep_truth.py:2209` reads
`for mod, want in AXIOM_CLOSURE.items()` — it iterates the TABLE, not the library,
so a module nobody measured was a module nobody was checking, silently. Its row is
the fourth number in the tree: `LIBRARY_TRUST["Peephole"]` is nine `bv_decide`
SITES and this is 12 declarations of which 8 are kernel-checked and 1 reaches an
axiom (3 more reach one only through another declaration — the only module in
`lib/` besides `ProofLib` with a non-zero `closure_only`). Sites and declarations
are correctly different numbers, and the module's value is that 8 of its 12
declarations are checked by the kernel.

**2. `FORMAL.md` §7 row 10 published a FOURTH copy of these numbers, and it
disagreed with the table it summarises.** Its closing clause read "of `lib/`'s
**520** askable declarations, **67** rest on one of these axioms and **442** are
kernel-checked … 5.7 s over all **six** modules" — while the table summed to
589/81/497 over seven, and 67 + 442 = 509 ≠ 520 even on its own terms, so the
clause was never a sum of its two halves. It is now re-pinned from the run above
(612 asked, 82 reaching, 516 clean, 6.9 s over all EIGHT modules), with the
arrivals named in the clause rather than left for the next reader to subtract.

**Why that clause had drifted while the row's `total`/`replaced`/`remaining` triple
had not**, and it is the reusable finding here: the triple IS checked, by
`test_formal_admitted.py::test_the_axiom_tactic_count_is_consistent`, which reads
it by STRUCTURE out of the document, so it cannot drift silently. The closure
clause had no reader at all. A stated measurement with no test behind it is a
fourth copy of a number, and this repository already knows what that costs — §0.3
of `FORMAL_stdlib_module_names_are_not_classified.md` is the same failure in the
classification tables, where the docstring said "six strings" over a seven-row
table for two merges. **The open part of this, if anyone wants it, is a reader for
row 10's closure clause**: either publish it from `AXIOM_CLOSURE` or say in the
row that it is a narrative. That is a `FORMAL.md` change with a design decision in
it, which is why this merge re-pinned the numbers and left the reader alone.

### Reproducing (the re-derive above)

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label pb -- python3 tools/suite.py prooflib
$ python3 - <<'PY'
import sys; sys.path.insert(0, ".")
from formal import admitted as A, lean as L
lib = A.lean_dir(".")
print(A.axiom_census_summary(A.theorem_axiom_census(L.find_lean("."), lib), lib))
PY
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
```
