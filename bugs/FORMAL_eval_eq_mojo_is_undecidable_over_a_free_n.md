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
never parsed, so the knob was never turned. The class is unchanged and the
remaining work is items 1 and 2.

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
a re-run is a file read):

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 -u tools/formal_proof_fuzz.py \
    --count 40 --arch x86_64 --no-check --work .tmp/ppf/x86-gen
python3 tools/memslot.py --gb 8 --label t -- python3 -c \
    'import sys; sys.path.insert(0, "."); from formal.lean import check_proof_cached; \
     print(check_proof_cached(".tmp/ppf/x86-gen/p22.6124220416_proof.lean", repo_root=".")[:2])'
```