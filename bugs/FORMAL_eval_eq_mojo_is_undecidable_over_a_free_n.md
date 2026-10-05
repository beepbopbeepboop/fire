# An `if` whose condition reads a LOCAL leaves `eval_eq_mojo` unproved, and the goal it leaves is not decidable

**Status 2026-10-05 (`work/formal19-3-r2`): the Status section's central
conclusion is WRONG, and it was measured wrong because of a defect in the
harness this doc's own reproduce command runs through — now fixed. Read
§"Status 2026-10-05" before §"Status 2026-10-04"; the latter's measurements are
real but the thing they measure is not the AST literal.** The class is still
here and the emitter still emits the failing tactic; what changed is that the
next attempt now has the right target, and that the two experiments §"Status
2026-10-04" ran (`maxSteps`, and separating the unfolding) were taken through a
`check_proof_cached` that never reached the theorem.

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
## Status 2026-10-05 (`work/formal19-3-r2`): the AST LITERAL is not the centre —
the 64-branch ARITHMETIC is, and every measurement above was taken through a
harness that never read the theorem

**Two things, and the first is a defect in the instrument the doc's own
reproduce command runs through, so the second could not have been found without
it.**

### The instrument: `repo_root="."` made every run fail at `1:0`, and the failure was CACHED

§"Reproducing the measurement" above ends with

```sh
python3 -c '… check_proof_cached(".tmp/ppf/x86-gen/p22…_proof.lean", repo_root=".")'
```

`repo_root="."` is a RELATIVE root, and `formal/lean.py::_run_lean` handed
`LEAN_PATH` the `lib_dir` it was given, unresolved, while the elaborating
process's cwd is the proof's own directory. So `lib` resolved to
`<proofdir>/lib` and the run answered

```
p22…_proof.lean:1:0: error: unknown module prefix 'ProofLib'
No directory 'ProofLib' or file 'ProofLib.olean' in the search path entries:
  …/p22…  ./lib  …/leanprover--lean4---v4.32.2/lib/lean
```

**at `1:0`, before the theorem is read at all.** Through this command, §"Status
2026-10-04"'s three rows — `maxSteps 4000000`, `maxRecDepth 2000000`, and the
heartbeat breach "at line 38, which is `def ast`" — could not have been
produced, because nothing in that file was elaborated. `library_census` (line
1121) and `print_axioms` (line 1232) both already `abspath` the same variable,
and the first says why in a paragraph; `_run_lean` is the third site and it is
the only one whose mistake is a VERDICT rather than a census row. And the
verdict was **published** — `proof_verdict_key` hashes the proof's bytes and the
library's `.olean` digests, and neither records how the run FOUND the library —
so the same file replayed the same false failure for every later caller.
Measured with the path fixed and the key unchanged: identical detail,
`cached=True`. Fixed at `c28fa355` (`abspath` + verdict `v3 -> v4`; a flush is
not available from a worktree, the CAS is machine-wide and shared).

**What the class actually is, re-measured through the fixed entry point.** The
same generated program (seed `formal-proof-fuzz`, program 22, x86-64, 30
statements, **6** branch conditions reading locals), tactic replaced by hand and
nothing else changed:

| tactic | Lean says | wall |
|---|---|---|
| today's emitter | `` `simp` failed: maximum number of steps exceeded `` | 43.6 s |
| `rfl` | ``Tactic `rfl` failed: the left-hand side is not definitionally equal`` — i.e. the two sides genuinely differ and the theorem is not vacuous | 30 s |
| **`simp only [ast, evalFunc, MojoEnv, evalBody, evalBodyEnv, evalExpr]`** | **`unsolved goals`, with the goal already the whole 30-statement program's if/elif tree, fully unfolded** | **33.2 s** |
| …then the `by_cases` chain, then `simp_all` with NO arithmetic lemmas | `maximum recursion depth has been reached` | 60 s |
| …then the `by_cases` chain, then today's `simp_all +decide` (item 3's "separate the unfolding") | `` `simp` failed: maximum number of steps exceeded `` | 44 s |
| today's emitter with `ast` REMOVED from the simp set | `unsolved goals`, goal UNCHANGED | 38 s |

**So the centre is the 64-branch ARITHMETIC, not the AST literal, and §"Status
2026-10-04" concluded the opposite from a heartbeat breach it could not have
measured.** `simp only [ast, evalFunc, MojoEnv, evalBody, evalBodyEnv,
evalExpr]` reduces `evalFunc ast … [n]` — thirty statements, one nested
`MojoStmt`/`MojoExpr` constructor per token — to the program's if/elif tree, in
**33 s, inside every bound the emitter writes**, and hands back a goal. The
literal is not deep enough to be the problem; what is expensive is rewriting
that whole tree six-bit-wise across `2⁶ = 64` `by_cases` branches, because each
branch re-does the entire program's arithmetic.

**Two rows above are worth a reader's attention on their own.** The `rfl` row
is the soundness check nobody had made: it confirms the theorem is not vacuous
and that `unsolved goals` is a real gap rather than an already-true statement.
The last row is the one that names the target: **dropping `ast` from the simp set
does not change the goal at all** — with no `ast` the tactic cannot reduce
`evalFunc` and the statement survives verbatim — so the entire cost is inside the
one rewrite, and there is no smaller subgoal to aim at from outside it.

**Why this makes item 2 (the chain of per-statement `have`s) the RIGHT next step
rather than merely the untried one.** The doc's argument for it was "the
difficulty is a function of the program's size and a chain of *k* small steps is
not", and that argument is now measured rather than assumed: the branching factor
is what multiplies, and `evalBodyEnv`/`evalExpr` in `lib/ProofLib.lean` already
have exactly the per-statement shape a chain needs (`evalBodyEnv` is one
structural recursion whose `assign` arm extends the environment, so
`evalBodyEnv cf [sₖ] envₖ = (none, envₖ₊₁)` is one statement's worth of `simp`
per link, and the environments are nameable as the lambdas
`fun name => if name = "w" then evalExpr cf e env else env`). **This is still
unmeasured and no claim is made that it works** — it is the emitter's version of
an induction, it needs no `ProofLib` change, and it is the option this table
leaves. The shape of the work is a change to
`formal/arm64_proof_gen.py::eval_eq_mojo_proof`'s straight-line arm and
`formal/x86_64_proof_gen.py`'s, and on arm64 the same measurement is expected to
follow from `lib/ProofLib.lean` being shared and both arms carrying the same
unfolding set (`arm64_proof_gen.py`'s `simp_lems`) — it was not taken here
because arm64's universal-theorem walk refuses THIS program for an unrelated
reason ("universal theorem: 2 calls this walk cannot follow"), which is
`bugs/FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image`'s
subject and not this row's.

**What was tried and is now known NOT to be the answer**, so nobody re-runs it:
raising `simp`'s `maxSteps` (moves the bound to recursion, then to heartbeats);
raising the file-level `maxRecDepth` (moves it to heartbeats); and separating the
unfolding from the rewriting (identical failure at the same column — because the
unfolding was never the cost). Two further rows are worth recording because they
bound the space from the other side: a program whose conditions read locals but
whose body is **small** is not in this class at all — measured on both
architectures over 2, 4, 6, 8 and 12 statements with local-reading conditions,
every one typechecks at the generator's two-hole floor — so the class needs the
SIZE as well as the shape, which is consistent with the branch count being the
cost.

**Reproducing this section's table** (the generation step is cheap, 40 programs
in 20 s at 0.1 GB; each row is one Lean run, and every row is content-addressed
in `formal/lean.py`'s CAS):

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 -u tools/formal_proof_fuzz.py \
    --count 40 --arch x86_64 --no-check --work .tmp/ppf/gen
# then replace line 42 of .tmp/ppf/gen/p22.*_proof.lean with each tactic above and:
python3 tools/memslot.py --gb 8 --label t -- python3 -c \
    'import sys, time; sys.path.insert(0, "."); from formal.lean import check_proof_cached; \
     t=time.time(); print(check_proof_cached(".tmp/ppf/variants/<row>.lean", \
     repo_root=".", timeout=1400)[:1], "%.1fs" % (time.time()-t))'
```

`.tmp/ppf/variants/*.lean` and `.tmp/ppf/scale/` are scratch, not committed
(`.tmp/` is git-ignored, and the sweep maps do the same), so each row is
described by its tactic above rather than shipped.
