# An `if` whose condition reads a LOCAL leaves `eval_eq_mojo` unproved, and the goal it leaves is not decidable

**Area:** FORMAL / proof generation. Found 2026-10-04 on
`work/formal17-fuzz-continue-b` by `tools/formal_proof_fuzz.py` — the
differential fuzzer for the PROOF layer, which builds each generated program
with `prove=True`, checks the emitted proof, and puts Lean's verdict next to
what the image did against CPython.
**NOT FIXED.** The generator emits the file and Lean rejects it; nothing here is
a false theorem, so this is coverage, not soundness. What it costs is stated
below and it is 7 of 40 programs on x86-64. **§"The next step"'s item 3 is
ANSWERED and it is NO** — see §"Status 2026-10-04" at the end, which also
corrects item 1's own experiment: the `simp_all (maxSteps 400000)` it measured
never parsed, so the knob was never turned. **§"Status 2026-10-05" adds four more
measured negatives AND corrects the attribution of §"Status 2026-10-04"'s
headline row: the fatal heartbeat timeout is in the `eval_eq_mojo` TACTIC, not in
`def ast`.** The class is unchanged and the remaining work is items 1 and 2 —
and §"Status 2026-10-05" says which of the two levers is NOT one of them.

## Status 2026-10-05 (`work/formal27-3`): four more negatives, and the row that
## said "the AST literal, not the tactic" is a MISATTRIBUTION

The class is still here and nothing was fixed. What is new is that the cost is
now located more precisely than §"Status 2026-10-04" located it, and three
plausible-looking levers are measured and **declined**. Reproduced on the
fuzzer's own corpus, seed `formal-proof-fuzz`, x86-64, program 31 (six
conditions, thirty statements — the largest `eval_eq_mojo` tactic body in the
40):

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label ppfgen -- python3 -u \
    tools/formal_proof_fuzz.py --count 40 --arch x86_64 --no-check --work .tmp/ppf/gen
```

**The library is a CAS HIT, so a light worker can make every one of these runs.**
`formal/lean.py::ensure_library` publishes and looks up each `lib/*.olean` by
content, and on this machine all six of `LIBRARY_MODULES` are present in
`~/.gmojo/cas`: the run below copied them in and peaked at **0.0 GB**, against
the 7.82 GB the table in `formal/lean.py` records for building `ProofLib`. That
removes the reason this doc's earlier passes gave for not re-measuring
("`lib/ProofLib.olean`'s build peaks at 7.82 GB, so a light worker with an 8 GB
ceiling cannot rebuild the library at all") — **provided the change under test
does not edit `lib/`**, which for this doc's remaining option it does not.

**The correction.** §"Status 2026-10-04"'s third row reads "…`(deterministic)
timeout at whnf, maximum number of heartbeats (20000000) has been reached` — **at
line 38, which is `def ast`**, not the tactic", and concludes "**The centre is
the AST LITERAL, not the tactic.**" On this tree that is not what line 38 is.
In the generated file `def ast` is **line 36** and line 38 is the `eval_eq_mojo`
declaration (its `/-- … -/` docstring, which is where Lean anchors the error);
`def ast` elaborates cleanly, and it is the only thing in the file that
elaborates cleanly at that size.

**Measured, one Lean run each, through `formal/lean.py::check_proof`** (the
uncached reader — `check_proof_cached` replays a verdict keyed on the proof's
bytes, so a re-run of an unchanged file returns the old answer and prints
`cached True`):

| # | tactic | verdict | wall / CPU / peak |
|---|---|---|---|
| 0 | **the emitter's own, unchanged** | `` `simp` failed: maximum number of steps exceeded`` ×8 at 42:818 | 55.4 s / 208.8 s / 3.95 GB |
| 1 | `simp only [ast, evalFunc, MojoEnv, evalBody, evalBodyEnv, evalExpr]` **alone** | **`unsolved goals` — ONE goal, and the unfolding is not the cost** | **30.1 s / 174.6 s / 3.92 GB** |
| 2 | #1 then `by_cases`×6 then `simp_all +decide` over the SAME set | maxSteps ×8 at 43:818 | 54.0 s / 216.9 s / 3.87 GB |
| 3 | #1 then `by_cases`×6 then `simp_all +decide` with the six already-unfolded names **dropped** | maxSteps ×8 at 43:818 | 61.7 s / 197.9 s / 3.98 GB |
| 4 | #0 with `simp_all (maxSteps := 4000000)` | maxSteps ×**3** (down from 8), then `timeout at whnf … heartbeats` at **38:0** | **595.9 s** / 727.9 s / 3.84 GB |
| 5 | #1, `simp only [ast, …]`, then **`have h0/h2/h4 := by decide`** for the three CLOSED conditions instead of `by_cases`, then `by_cases`×3 then `simp_all (maxSteps := 4000000) +decide` | **8 leaves instead of 64** — no maxSteps error at all, and `timeout at whnf … heartbeats` at 38:0 | **547.3 s** / 736.8 s / 3.95 GB |

**What the table says, and it is the useful part.**

* **Row 1 is the finding.** The `ast` literal unfolds, once, inside the bound: a
  30-statement body becomes one goal in 30 s at 3.9 GB, and the goal it leaves
  is the fully-unrolled `evalBodyEnv` fold — the semantic environment as a
  `fun n_1 => if (n_1 == "w1") = true then … else …` chain with the arithmetic
  inlined. So "the AST LITERAL" is not a wall; **rewriting the unfolded term is.**
* **Rows 2 and 3 are §"The next step"'s item 3 second half, measured again and in
  both forms.** Separating the unfolding from the rewriting does not help
  (row 2), and removing the six names that row 1 has already discharged does not
  help either (row 3). Both still die at the same column with the same sentence.
  §"Status 2026-10-04" had row 2 alone; **row 3 is new**, and it is the half
  that could have rescued the idea — the second `simp` is not re-unfolding
  anything, and it still runs out of steps.
* **Row 4 is the knob, turned properly at last** (item 3's first half, which no
  earlier pass had measured with a parseable spelling). It **works and does not
  finish**: 8 → 3 maxSteps errors, 55 s → 596 s. Raising the step budget is what
  moves the failure, and it moves it onto the declaration's 20 M heartbeat
  budget, which row 5 shows is not about the branch count either.
* **Row 5 is the lever nobody had pulled, and it is declined by the number.** Three
  of this program's six conditions are CLOSED — `h0 : (n &&& 65535) =
  (n &&& 65535)` is `rfl`, and `h2`/`h4` compare literal words — so `by_cases`
  splits 64 leaves where 8 suffice, and `have h2 : … := by decide` replaces each
  split with a fact. **8 leaves at `maxSteps := 4000000` produce no maxSteps
  error at all, and still hit the heartbeat wall at 547 s.** So the per-leaf cost
  is essentially independent of the leaf COUNT, and "reduce the branches" is not
  the lever. (The `have`-the-closed-conditions shape is also the more honest
  emission whatever else happens to it — a `by_cases` on a proposition `decide`
  settles outright is two goals where one fact is the whole content — but it is
  not a fix for this class and is not landed, because a change that makes no
  difference to the verdict is not one to land under this project's rule.)

**So the lever is the per-leaf TERM, whose size is a function of the program's
statement count, and the only shape in this file's own vocabulary that does not
grow with it is §"Status 2026-10-04"'s item 2 — the chain of per-statement
`have`s.** Item 1 (a library induction on the AST body) and item 2 (the
emitter's version of it) are now the only two options left, item 3 is measured
dead in four forms, and this pass did not attempt either. What the next one
should know before starting: **the per-step goal it has to beat is row 1's** —
one `simp only [ast, evalFunc, MojoEnv, evalBody, evalBodyEnv, evalExpr]`, which
already fits in 30 s / 3.9 GB — so the chain's *k*-th step is a `simp only` over
a **prefix** of that same fold, and the sizes to beat are `ceil` and not the
whole.

**One thing this class is NOT, recorded because it is measurable and would
otherwise be re-derived:** the failure direction is unchanged and still the safe
one. Rows 0-5 are all *coverage* — the file does not typecheck, no `sorry` moves,
and the census arithmetic in §"Why this is coverage and not soundness" is
untouched. `formal_proof_fuzz.py`'s `MISMATCH`-under-`pass` cell is still 0.

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label ppf-x86 -- \
  python3 -u tools/formal_proof_fuzz.py --count 40 --arch x86_64 -j 2 -t 400 \
  --work .tmp/ppf/x86-campaign
```

40 generated programs, `--mix plain`, 6 inputs each (the program's own, drawn
from the seed, plus `0 1 3 7 32768`). 555 s wall, peak 6.8 GB. Ledger (committed):
`bugs/sweeps/proof_fuzz_2026-10-04_x86_64.jsonl`.

## What was seen

| | n |
|---|---|
| `admitted` — proof typechecks at **2 holes**, this generator's designed floor | **33** |
| `lean-rejected` — Lean did not accept the file | **7** (10 after the environment fix) |
| `match` — image and CPython agreed at every input | **40** |
| **`SOUNDNESS-MISMATCH` — Lean accepted the proof AND the image disagreed** | **0** |

The 7 rejections are all one thing. Six are

```
p0_proof.lean:42:108: error: `simp` failed: maximum number of steps exceeded
```

on the `eval_eq_mojo` tactic, and the seventh is `41:59: error: unsolved goals`
— the same goal by a different route. The program is the smallest of the seven
(`tools/formal_proof_fuzz.py --print-program 0`, input 255, 21 lines):

```python
def main(n) -> Int:
    b1 = 0
    b2 = 0
    w3 = 0
    b4 = 0
    b1 = 1 if ((-7) >= (17)) else 0
    b2 = 1 if (((n & 0xFFFF)) >= (((b1 + n)) & 0xFFFF)) else 0
    w3 = (((b1 + b1) & 0xFFFF) & 7)
    b4 = 1 if ((b1) >= (((n & 0xFFFF)) & 0xFFFF)) else 0
    print(b1)
    return 0
```

and the emitted goal is

```lean
theorem eval_eq_mojo (n : UInt64) :
  evalFunc ast (fun name arg => if name = "main" then mojo arg else 0) [n] = mojo n := by
  by_cases h0 : ((3 ^^^ 0x8000000000000000) ≤ ((31 - 13) ^^^ 0x8000000000000000)) <;>
    simp_all +decide [h0, mojo, main_go, ast, evalFunc, MojoEnv, evalBody,
                      evalBodyEnv, evalExpr, u64pow, u64powGo, sKey,
                      u64_lt_iff_false_of_le, u64_le_iff_false_of_lt]
```

## Why, and what was tried

Two questions, both measured on the file above by hand
(`formal/lean.py::check_proof`, one Lean run each):

**1. Is it a fuel limit?** No — and the experiment that says so was measuring a
PARSE ERROR, which is corrected and re-measured below (2026-10-04,
`formal25-3`). `set_option maxSteps` does not exist in this toolchain (`error:
Unknown option 'maxSteps'`), and the real knob is `simp`'s own `maxSteps`
argument. Raising it 4x:

```lean
  by_cases h0 : … <;> simp_all (maxSteps 400000) +decide […]
```

gets past `` `simp` failed `` (13.6 s) and leaves the goal UNSOLVED:

```
⊢ evalFunc ast (fun name arg => if name = "main" then mojo arg else 0) [n] = mojo n
```

**THAT OBSERVATION IS AN ARTEFACT, and a future session must not inherit it.**
`simp_all (maxSteps 400000)` — the space form — is not a tactic at all in Lean
4.32.2: the configuration is a NAMED field, so the parse fails with `unexpected
token '('; expected command`, the tactic never runs, and the goal is reported
open. Measured on a three-`example` probe file through
`formal/lean.py::check_proof_cached`, one Lean run:

| spelling | verdict |
|---|---|
| `simp_all (maxSteps 400000) +decide []` | **`12:11: error: unexpected token '('; expected command`** |
| `simp_all (maxSteps := 4000000) +decide []` | accepted |
| `simp (maxSteps := 4000000)` | accepted |

So "gets past `simp` failed and leaves the goal unsolved" described a tactic that
did not parse. What the knob actually does is in §"Status 2026-10-04" below.

**2. Is the leftover goal decidable?** Not by the two procedures this framework
has. `simp … <;> bv_decide` (14.2 s) leaves the same goal. The statement is
about a *free* `n : UInt64`, and both `decide` and `native_decide` require a
closed goal; `bv_decide` is the framework's symbolic procedure and does not
recover a value out of `evalFunc ast` here.

So the limit is structural: `eval_eq_mojo` is discharged by rewriting, and the
rewrite has to reduce a `MojoFunc.mk` literal whose body is the whole program.
When the program's conditions read locals the term is deep enough that `simp`
either exceeds its steps or gives up with the goal open, and there is no
fallback that decides a universally quantified `UInt64` statement about a
recursive AST evaluator.

## Why this is coverage and not soundness

The failure direction is the safe one: Lean says "I cannot prove this" and the
build fails. Nothing is admitted and no theorem is asserted that is not
checked. It matters because it is the *denominator* of the census
(`bugs/FORMAL_proof_coverage_census_2026-10-03.md`): a program in this class
counts as "reached the proof layer" and then does not typecheck, so a census
that counts generation and a census that counts `pass` disagree by exactly these
7.

Two things about the class, both measurements rather than opinions.

**These programs are NEW to the corpus, and only because of the 2026-10-03 fix
in the same area.** `_cond_nodes` rendered every condition in `{param: param}`,
so a program whose condition reads a local had no proof at all — it was a
`proof-refused`. Widening the corpus moved it from "refused" to "rejected",
which is progress on the count and a new cost on the wall clock.

**It grew from 7 of 40 to 10 of 40 when the x86-64 environment fix landed, and
that is the same trade again.** Ten of the forty are two-parameter entries, and
for all ten the `eval_eq_mojo` bridge had been silently OMITTED (the file said
"this function's shape (recursive/looping): the bridge is not closed yet", which
is false of a straight-line program). The fix makes it EMITTED: seven of the ten
then check at the generator's two-hole floor and three land here. So the fix
removed ten holes and turned three quiet passes into reds — the right direction
for a census whose argument is that a hole is not a pass, and the reason this
doc exists rather than a `sorry`.

## The next step, and it is not a patch

The cheap experiment is already done and did not work (above). What would:

1. **Prove `eval_eq_mojo` by induction on the AST body** rather than by
   rewriting a literal. `evalBody` in `lib/ProofLib.lean` is a structural
   function; a `MojoFunc` whose body is a list of statements is the shape an
   induction wants. This is the honest fix and it is a library change.
2. Failing that, **generalise `n` away before deciding** — i.e. prove
   `∀ n, evalFunc ast cf [n] = mojo n` by `native_decide` over a *closed*
   instance and a `simp`-driven case split on the conditions' sign bits, which
   is what `bv_decide` is for. The measurement above says the current `ast`
   encoding is not in `bv_decide`'s fragment.
3. Failing that, **scale the tactics with the program** — `simp (maxSteps N)`
   with `N` proportional to the emitted `ast` size, plus `simp only [evalFunc,
   evalBody, evalBodyEnv]` before the arithmetic lemmas so the unfolding is
   separated from the rewriting. Cheapest to try, and it is worth one run to
   know whether the leftover goal is then closed or still open.

Item 3 is the one a session should try first: it is an hour, and its answer
decides whether items 1 and 2 are worth a library change.

## Status 2026-10-04 (`formal25-3`): item 3 is ANSWERED, and the answer is NO

**The doc's own question — is item 3 worth an hour, and does its answer decide
whether items 1 and 2 need a library change — is now answered: item 3 does not
work, and the reason is not a budget that can be raised.** Everything below is
measured on this tree, through `formal/lean.py::check_proof_cached` (so the
library bounds and the CAS apply), one Lean run per row.

**The class is still here and is not smaller.** The corpus has moved since the
section above (the program it quotes is not program 0 any more), so the failing
shape was re-found from scratch: seed `formal-proof-fuzz`, program 22, input 255,
30 statements and **6** branch conditions whose tests read locals. Generated
with `--no-check` (no Lean, no images: 40 programs in 20 s, peak 0.1 GB) and then
checked:

```
p22.6124220416_proof.lean:42:587: error: `simp` failed: maximum number of steps exceeded   (43.6 s, peak 4.2 GB)
```

which is the same sentence, on the same tactic, at the same column.

**Three bounds, in the order a run meets them.** The file-level options the
generator already emits are `maxRecDepth 100000` and `maxHeartbeats 20000000`;
`simp`'s own default `maxSteps` is 100000.

| what was changed | what Lean says | cost |
|---|---|---|
| nothing (today's emitter) | `` `simp` failed: maximum number of steps exceeded `` | 43.6 s |
| `simp_all (maxSteps := 4000000)` | `maximum recursion depth has been reached` | 32.7 s |
| …and file-level `maxRecDepth 2000000` | `(deterministic) timeout at whnf, maximum number of heartbeats (20000000) has been reached` — **at line 38, which is `def ast`**, not the tactic | 553.5 s |

**The centre is the AST LITERAL, not the tactic.** `line 38` is `def ast :
MojoFunc := MojoFunc.mk "main" [...] [...]`, one nested `MojoStmt`/`MojoExpr`
constructor per token of a thirty-statement body. Raising the two knobs moves
the failure from simp's step budget to simp's recursion budget to Lean's
heartbeat budget, and the third failure is in `whnf`ing that literal — which is
the term `eval_eq_mojo` is *about*. No budget large enough makes this a pass:
the wall bound for a proof is 1500 s and the third row is already 553 s of it.

**Item 3's second half — separate the unfolding from the rewriting — does not
help either**, and that is the one that looked most likely, because the `fib`
branch of the same generator already proves an `eval_eq_mojo` that way
(`have hunf : evalFunc ast _ [n] = … := by simp only [ast, evalFunc, MojoEnv,
evalBody, evalBodyEnv, evalExpr]; by_cases … <;> simp [h]`). Emitted as

```lean
  simp only [ast, evalFunc, MojoEnv, evalBody, evalBodyEnv, evalExpr]
  by_cases h0 : … <;> … <;> simp_all +decide [h0, …, mojo, main_go, u64pow, u64powGo, sKey, …]
```

it fails with **the same sentence at the same column** (39.4 s, peak 4.2 GB), and
dropping `+decide` changes it to `maximum recursion depth has been reached`
inside `simp` (38.1 s) with a `Possibly looping simp theorem: u64pow.eq_1`
warning beside it. So the cost is not the interleaving of the two simp sets.

**So items 1 and 2 ARE worth a library change, and §"The next step" should be
read as: skip item 3.** The consequence for the ledger's own arithmetic is
unchanged — this is coverage, not soundness, and every one of these programs
still fails the build rather than admitting a false theorem. What has changed is
that the cheap option is not cheap, and the expensive one is the only one left:

1. **an induction on the AST body** (item 1), or
2. **a chain of per-statement `have`s** — the emitter's version of item 1, needing
   no library change, where each step states "evaluating the first *k*
   statements gives the environment after *k*" and is one statement's worth of
   `simp`. **This is the shape worth trying first**, precisely because
   `eval_eq_mojo`'s difficulty is a function of the program's size and a chain of
   *k* small steps is not: it is the same decomposition the `fib` row already
   performs by hand, with the base case discharged by the same `simp only`. It is
   a change to `formal/arm64_proof_gen.py`'s `eval_eq_mojo_proof` arm and to
   `formal/x86_64_proof_gen.py`'s, and it is unmeasured — no claim is made here
   that it works, only that it is the option this section's measurements leave.

**Reproducing the measurement** (the generation step is cheap and the Lean runs
are the four rows above; each is content-addressed in `formal/lean.py`'s CAS, so
a re-run is a file read — **with the one caveat the table's own note gives: a
re-run of an UNCHANGED file replays the verdict, so a re-measurement needs a
changed tactic**):

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 -u tools/formal_proof_fuzz.py \
    --count 40 --arch x86_64 --no-check --work .tmp/ppf/gen
python3 tools/memslot.py --gb 8 --label t -- python3 -c \
    'import sys, os; sys.path.insert(0, "."); from formal.lean import check_proof; \
     print(check_proof(".tmp/ppf/gen/p22.6124220416_proof.lean", repo_root=os.getcwd())[:2])'
```

**The harness for the five rows is scratch and is described here so it can be
rebuilt**, because it is 30 lines and because the two things it has to get right
are the two the table is about. `.tmp/trybridge.py <proof.lean> <tactic-file>`:
read the proof, find the line ending `:= by` after `theorem eval_eq_mojo`, drop
everything up to the next blank line, indent the replacement tactic's EVERY line
by two spaces (a multi-line tactic whose second line is unindented ends the `by`
block and the file fails to parse — which cost this pass one run and is the
reason the row-2 measurement above was taken twice), write to a fresh path under
`.tmp/ppfrun/`, and call `check_proof_cached` with `repo_root=os.getcwd()` and
`FORMAL_LEAN_TRACE=1` for the wall / CPU / peak columns. `repo_root` must be
ABSOLUTE: `_run_lean` sets `cwd` to the proof's own directory, so a relative
`lib_dir` resolves `./lib` against the proof's directory and the run reports
`unknown module prefix 'ProofLib'` with a search path that looks correct.