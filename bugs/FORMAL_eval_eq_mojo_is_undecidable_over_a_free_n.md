# An `if` whose condition reads a LOCAL leaves `eval_eq_mojo` unproved, and the goal it leaves is not decidable

**Area:** FORMAL / proof generation. Found 2026-10-04 on
`work/formal17-fuzz-continue-b` by `tools/formal_proof_fuzz.py` — the
differential fuzzer for the PROOF layer, which builds each generated program
with `prove=True`, checks the emitted proof, and puts Lean's verdict next to
what the image did against CPython.
**NOT FIXED.** The generator emits the file and Lean rejects it; nothing here is
a false theorem, so this is coverage, not soundness. What it costs is stated
below and it is 7 of 40 programs on x86-64.

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label ppf-x86 -- \
  python3 -u tools/formal_proof_fuzz.py --count 40 --arch x86_64 -j 2 -t 400 \
  --work .tmp/ppf/x86-campaign
```

40 generated programs, `--mix plain`, 6 inputs each (the program's own, drawn
from the seed, plus `0 1 3 7 32768`). 555 s wall, peak 6.8 GB. Ledger:
`.tmp/ppf/x86-campaign/findings.json`.

## What was seen

| | n |
|---|---|
| `admitted` — proof typechecks at **2 holes**, this generator's designed floor | **33** |
| `lean-rejected` — Lean did not accept the file | **7** |
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

**1. Is it a fuel limit?** No. `set_option maxSteps` does not exist in this
toolchain (`error: Unknown option 'maxSteps'`), and the real knob is
`simp`'s own `maxSteps` argument. Raising it 4x:

```lean
  by_cases h0 : … <;> simp_all (maxSteps 400000) +decide […]
```

gets past `` `simp` failed `` (13.6 s) and leaves the goal UNSOLVED:

```
⊢ evalFunc ast (fun name arg => if name = "main" then mojo arg else 0) [n] = mojo n
```

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

Note also that these 7 programs are NEW to the corpus, and only because of the
2026-10-03 fix in the same area (`_cond_nodes` rendered every condition in
`{param: param}`, so a program whose condition reads a local had no proof at
all — it was a `proof-refused`). Widening the corpus moved them from "refused"
to "rejected", which is progress on the count and a new cost on the wall clock.

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