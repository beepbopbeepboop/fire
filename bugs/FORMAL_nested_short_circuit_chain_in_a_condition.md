# FORMAL_nested_short_circuit_chain_in_a_condition: `((a or b) or c)` is still unproved

`if a or b:` and `if a and b:` as a whole condition are **proved** (the
per-path entry statement they needed is in `formal/arm64_proof_gen.py`).
A chain NESTED inside a chain is not, and this says why and what closes it.

**Status 2026-10-05 (`work/formal23-4`): the MODEL half is FIXED on both
architectures, and the doc's premise that the whole failure is the machine half
is only HALF of what a run reports. `eval_eq_mojo` — the AST evaluator against
the semantic model — was ALSO left open for this shape, on both architectures,
and is now proved. What remains is the machine half: 16 `counterexample`s on the
`hcond` statements in the universal theorem, plus the kernel's memory ceiling on
the same file.** Read this before every section below; §"Status 2026-10-04"
describes a tree on which the model half had not been looked at separately, and
its "NO FIX ATTEMPTED, and the reason is that this area is not VERIFIABLE today"
is right about the machine half and wrong as a statement about the file.

## What landed, and what it was

`formal/arm64_proof_gen.py::eval_split_conds`, asked by BOTH generators (the
x86-64 one imports the arm64 module as `AP`, so the two architectures cannot
split on different propositions). It walks the same `_cond_nodes`
`_collect_conds` walks, emits each source condition exactly as before, and
appends the LEAVES of any chain that is genuinely nested, rendered the way
`_truth_go` renders an operand of a chain.

The reason it was needed is `lib/ProofLib`'s own spelling of a binary `or`:
`evalExpr` renders it `¬x → y` (which is `x ∨ y`), so `((a or b) or c)` nests
that to `¬(a ∨ b) → c`, which curries to `¬a → ¬b → c` — **not** the
disjunction the emitted `by_cases` hypothesis carries. From `h0 : (A ∨ B) ∨ C`
the goal needs `¬B → C`, so it has to know whether `B` holds, and one split on
the whole condition cannot say so. The generated goal, verbatim:

    case pos
    n : UInt64
    h0 : (10 ^^^ 9223372036854775808 < n ^^^ 9223372036854775808 ∨ n = 0) ∨
         n ^^^ 9223372036854775808 < -4 ^^^ 9223372036854775808
    ⊢ (match (if n ^^^ 9223372036854775808 ≤ 10 ^^^ 9223372036854775808 →
                    ¬n = 0 → n ^^^ 9223372036854775808 < -4 ^^^ 9223372036854775808
              then (some 1, fun name => if name = "n" then n else 0)
              else (some 0, fun name => if name = "n" then n else 0)).fst with
        | some v => v
        | none => 0) = 1

Measured, through `formal/lean.py::run_lean`, on the generated file truncated to
just that theorem — the honest way to check a statement the machine half's
ceiling makes unreachable, and a real check rather than a weakened one because
a truncation that cuts a theorem in half is a syntax error and Lean says so:

| | before | after |
|---|---|---|
| arm64 `eval_eq_mojo` | `rc 1`, the goal above | **`rc 0`** |
| x86-64 `eval_eq_mojo` | `rc 1`, the same goal | **`rc 0`** |

This doc's §"No claim about x86-64" is therefore no longer true of the model
half; it was measured on both architectures, and the x86-64 generator needed the
same one-line change for the same reason.

**It costs nothing, measured the way `CLAUDE.md` asks for a change that is
supposed to be behaviour-preserving: byte-identical generated C/proof.** A flat
chain has no `and`/`or` descendant, so no extra proposition exists. All 52
`formal/examples/` stems on both architectures — 101 generated proofs, `cmp`
against the same 101 built with this generator reverted: **101 identical**, and
the 4 stems that raise the same `FormalBuildError` before and after.

`test_formal_short_circuit_cond.py` grows `TestLeanModelBridge` for it (the
truncated theorem, both architectures, asserting zero `sorry`), two generator
tests (`a_nested_chain_splits_on_its_leaves`, and
`a_flat_chain_still_splits_on_nothing_extra` as the guard), and its
`KNOWN_GAP["nested_or"]` entry now says which half is proved.

## What is left, and it is only the machine half

Re-measured on this tree, the full generated file still fails, and the failures
are the ones the sections below name plus the ceiling:

```
nested_or_proof.lean:25:56:   error: unsolved goals                  -- was this one; FIXED
nested_or_proof.lean:3362:263: error: counterexample                x16, on the `hcond`s
nested_or_proof.lean:3216:8:   error: (kernel) excessive memory consumption detected
```

and the canary is still red for the memory reason alone:

```
$ python3 tools/memslot.py --gb 32 --label either -- … check_proof_cached(…)
either_proof.lean:2684:8: error: (kernel) excessive memory consumption detected
memcap: done, peak 13.6 GB across up to 2 procs (ceiling 32.0 GB), child exit 0
```

So §"Status 2026-10-04"'s blocker is confirmed rather than removed: with the
library current, `either` — one conditional branch, two operands — needs 13.6 GB
and Lean's kernel refuses it. `bugs/FORMAL_a_generated_proof_over_leans_memory_
ceiling_is_rejected.md` owns that, its §2 bisection is still the best account of
it (the cost is `bv_decide`/`native_decide` in the per-block branch-condition
facts, and with those 44 sites removed the file elaborates in 2.82 GB), and its
§3 fix direction is the one this doc's machine half needs. **Until that lands,
no change to `_hcond_mem_rws`, to the `simp only` set or to the `hcond`
statement's right-hand side can be checked** — which is what §"Status 2026-10-03"
measured from the other end and what this session's re-measurement confirms.

**So the next step for THIS document is unchanged and it is not in this file.**
The generator-level recording question §"Where the machinery actually stops"
raises — `_cond_pairs` recording a pair per CHAIN and `_cond_nodes` yielding one
entry per chain, so the inner chain's merge becomes a block the generator knows
about — is still the right diagnosis of the machine half, and it cannot be
landed or refuted until the memory ceiling is down. What §"Status 2026-10-04"
misses is only that the MODEL side was a separate, separable failure: it is not
evidence about the machine half either way, and it is now closed.

## The next step for the model half, and what it did NOT need

Nothing: the fix is the split list, and the "decompose per operand and
recombine" machinery §"The next step, now that the discriminator is known"
proposes is for the `hcond` STATEMENTS, not for this theorem. Recording that
here because the doc below proposes it in a place where a simpler thing was
enough, and a reader who follows that paragraph will build machinery that is not
what the failing goal wanted.

## The instrument defect is FIXED

§"One instrument defect found while measuring this" recorded that
`formal/lean.py::proof_verdict_key` does not cover the proof's DIRECTORY, so a
run with a relative `repo_root` publishes a verdict `unknown module prefix
'ProofLib'` that is then served for the same bytes from anywhere else. The
workaround is still to pass an ABSOLUTE `repo_root` (`os.path.abspath(".")`),
and the poisoned CAS entry under the relative key had to be deleted by hand once
more here. The doc is still right that the cache cannot see the directory; it is
still an open defect, and
`bugs/FORMAL_the_proof_verdict_cache_key_cannot_see_the_proof_directory.md`
still owns it.

**Status 2026-10-04 (`work/formal29-3`): NO FIX ATTEMPTED, and the reason is
that this area is not VERIFIABLE today — on this tree `formal/examples/either.mojo`
and `both.mojo` do NOT typecheck**, which is the premise every earlier Status
section below rests on ("`either`/`both` are the canary and must keep proving").
Measured, both, this session, through `formal/lean.py::check_proof_cached`:

```
either_proof.lean:2600:8: error: (kernel) excessive memory consumption detected
   → peak 6.9 GB across 2 processes
both_proof.lean:2600:8:   (the same line, the same error)  → peak 7.0 GB
```

That is the whole of `test_formal_short_circuit_cond.py::TestLean` red, it is
`bugs/FORMAL_a_generated_proof_over_leans_memory_ceiling_is_rejected.md`'s
subject (that doc's Status measures the cause as the `bv_decide` cost of the
per-block branch-condition facts and says what is missing is a lemma for a
short-circuit condition's value flow — an UNOWNED doc), and it means a generator
change here could not be checked even if it were right: the change that fixes the
nested chain would land in the same file that emits the 6.9 GB proof the kernel
already refuses. The project's own rule names that outcome as the worst one
("statements which LOOK right and are not proved"), and this document's own 2026-10-03
section declines the work for the same reason at a smaller scale. So this session
measured the next step instead, which is below and is new.

### Where the machinery actually stops, measured (this is the new part)

**An inner chain gets NO merge block, NO statement and NO travelling fact — and
that is upstream of everything the two Status sections above hypothesised.** Read
off the generator's own tables for `n > 10 or n == 0 or n < -4` (11 blocks: five
`cbz`, two `ret`, four `seq`; the outer chain's own branch is the `cbz` at
`4294968124` and the outer merge is `4294968164`):

| what | measured |
|---|---|
| `_cond_nodes(fn, …)` yields | **ONE** node — the outer `or`. The inner `or` is not a separate entry |
| the codegen's `_cond_pairs` records | **ONE** pair — `(4294968164, <the whole condition>)` |
| `_sc_by_merge` therefore holds | **ONE** entry: `{m: 4294968164, s: 4294968124, kind: or, l: <the inner chain's VALUE>, r: C}` |
| the `hcond` statements in the emitted proof | **TWO distinct shapes**, `hcond_6` ×8 and `hcond_8` ×16 — and **no statement at all about the inner merge's register** |

So the inner chain's truth value reaches the outer chain's own branch as a bare
register, and the statement there is `arm64_reg 0 s_6 ≠ 0 ↔ ((A ≠ 0) ∨ (B ≠ 0))`
— a proposition about the machine that is TRUE, and one that `by_cases h : …`
plus `simp [h]` cannot discharge because the register arrived along two
different `cset`s and only one of them is unfolded into the goal's shape. The
`hcond_8` at `4294968164` is the same statement with the sense flipped, and its
other shape (`↔ ¬(C ≠ 0)`) is the passing two-operand one, on the path where the
register really does hold C's `cset`.

**The next step is therefore one level UPSTREAM of the two Status sections
below**, and it is a codegen-side recording question rather than a statement to
re-word: **`_cond_pairs` must record a pair per CHAIN in the condition tree, and
`_cond_nodes` must yield one entry per chain, so that the inner chain's merge
becomes a block the generator knows about.** Then the inner merge gets its own
per-operand statement (the shape `hcond_8 ↔ ¬(C ≠ 0)` already has), its own
travelling fact, and the outer chain's left operand is a NAME (`hscL_<inner
merge>`) rather than a re-derivation of `A ∨ B` at a place where two `cset`s meet.
Until that recording exists, no change to `_hcond_mem_rws`, to the `simp only`
set or to the statement's right-hand side can reach this program — which is what
the 2026-10-03 measurement ("the `rw`/`simp only` lines are character-for-character
the passing case's") was already telling us, read from the other end.

**What is NOT claimed:** that the recording change is small. It is in
`formal/arm64_codegen.py` (what `info["cond_branches"]` records) and in
`_cond_nodes`, and the recording is what `either`/`both`'s passing proofs depend
on — so it needs the memory problem above fixed first, or at least measured
against it.

### One instrument defect found while measuring this, filed rather than fixed

`formal/lean.py::proof_verdict_key` does not cover the proof's DIRECTORY, and
`_run_lean`'s `LEAN_PATH` puts that directory FIRST, so two byte-identical
proofs in different directories are not the same proposition to Lean — while the
cache cannot tell them apart. Measured here: a run from `.tmp/sc` with
`repo_root='.'` (which makes `lib_dir` relative and therefore unresolvable from
the proof's own directory) cached the failure `unknown module prefix 'ProofLib'`,
and that verdict was then served for the same bytes from `.tmp/scroot` where the
library resolves. Filed as
`bugs/FORMAL_the_proof_verdict_cache_key_cannot_see_the_proof_directory.md`; the
poisoned CAS entry had to be deleted by hand to get a real run, which is the
"a red that no fix can clear" shape this project keeps arguing against.

## Status 2026-10-03 (`work/formal13-4`): NOT FIXED, and BOTH of the 2026-10-03
## Status section's hypotheses are now MEASURED FALSE. The discriminator is
## identified, and it is not which side the sub-chain is on.

The next step this document asks for is step 1 of its last section — "compare the
`try rw [...]` list in `hcond_2` against the one in `either.mojo`'s passing
`hcond`: if the nested one is missing a slot write, that is the whole failure and
it is a one-line set difference". **It is not a set difference, and the flow is
not short a block.** Read off the two emitted files (both generated without
running Lean, by calling `formal.build.compile_formal(..., prove=True,
check=False)`, which writes `<stem>_proof.lean` and stops):

| | `either.mojo`'s passing `hcond_2` (line 4222) | `nested_or`'s failing `hcond_2` (line 5272) |
|---|---|---|
| statement | `arm64_reg 0 s_2 = 0 ↔ ¬(A ≠ 0)` | `arm64_reg 0 s_2 ≠ 0 ↔ ((A ≠ 0) ∨ (B ≠ 0))` |
| `rw` | `[hsid_2]` | `[hsid_2]` |
| `simp only` block lemmas | `either_b2_*` | `f_b2_*` |
| predecessors in `simp only` | `hsid_2, hsid_0`, `either_b0_*` | `hsid_2, hsid_0`, `f_b0_*` — **the same two, and the whole prior prefix** |
| `mem_read_two_writes_adj_uint` address | `…sp -16 -16 -32 -16` | **the same expression, character for character** |
| flag lemma | `arm64_flag_gt_s` | `arm64_flag_gt_s` |
| closer | `by_cases h : … <;> simp [h, …] <;> bv_decide` | the same |

So `ctx["flow_blocks"]` reaches every predecessor (both `hsid`s and the whole
`b0` prefix are unfolded in the failing proof, which is what the comment on
`either`'s `_cset_bi != bi` branch asks for), and `_hcond_mem_rws`' set is not
short of anything. **The only difference is the shape of the right-hand side: a
nested chain's VALUE (an `Or`) where a single-operand chain has one term.**

**And it is the `Or`, not the nesting direction.** The control is one program:

```python
def f(n):
    if n > 10 or (n == 0 or n < -4):      # the sub-chain on the RIGHT
        return 1
    else:
        return 0
```

built through `formal/lean.py::check_proof_cached` (one Lean run, 3.1 GB peak,
under the bounds): **FAILED, with the same signature** — one `unsolved goals` on
`eval_eq_mojo` at 25:54 and two `counterexample`s (5478:264 and 5651:266) against
four for the left-nested spelling. Its failing statement is the mirror image:

    have hcond_3 : (arm64_reg 0 s_3 = 0) ↔ ¬((B ≠ 0) ∨ (C ≠ 0)) := by

with the register holding **B**'s compare result (`arm64_flag_eq` in the `simp`,
and B's slot at `… -16 -16 -32 -16 + 16`). So this document's §"Why the two-path
statement does not reach it" is right that the statement is the problem and wrong
about the trigger being a LEFT operand that is itself a chain.

**Why the `Or` fails, in one sentence:** `simp [h]` does not split a
disjunction, so on the path where operand K's cset wrote the register the goal is
`(if K then 1 else 0) ≠ 0 ↔ ((A ≠ 0) ∨ (B ≠ 0))` with the *other* operand's
disjunct unconstrained — and `bv_decide` is right to report a counterexample for an
equivalence that does not hold on that path. Lean says so itself, and its witness
is the tell: `Consider the following assignment: n = 0, x19✝¹ = 0, … ,
arm64_reg 0 {…} = 0` — every register free, because the register was left OPAQUE
by the rewrite chain, exactly as the 2026-10-03 section recorded for `either.mojo`.

### The next step, now that the discriminator is known

**Decompose the statement per operand and recombine, and the decomposition is
already half-written in this file's §"The next step":** for a merge block whose
register was written by operand K's cset on this path, state
`arm64_reg r <merge> = 0 ↔ ¬(K ≠ 0)` — which is what the passing two-operand case
already emits — and build the CHAIN's value fact from K with `Or.inl`/`Or.inr`,
so `hscL` is `Or.inl (hcond_M.mp hc_M)` rather than `hcond_M.mp hc_M`. The
travelling fact then stays a fact about the sub-chain's value, which is what both
spellings already need, and the depth stops mattering because nothing in the
statement is a chain any more.

The part that is NOT free, and is the reason this is not a one-line change: the
outer merge's travelling fact is `¬((A ≠ 0) ∨ (B ≠ 0))` on the fall-through path,
and `¬(K ≠ 0)` alone does not give it — the other operands' falsity is a fact
about the PATH, not about the register, so it has to come from the sub-chain's own
per-operand statements (`hcond_2`/`hcond_3` on the same path) rather than from the
merge. That is a second mechanism and it is the reason the doc's §"The next step"
proposed the value-fact route in the first place.

**Not attempted, and why (unchanged from 2026-10-03, with one measurement added):**
this is Lean-level debugging of a 500 KB generated proof at ~80 s per iteration,
the failure mode of a half-finished change here is a generator that emits
statements which LOOK right and are not proved, and both `either` and `both` are
the canary that must keep proving. What is new here costs nothing to keep: the two
hypotheses above are settled, so the next session does not re-measure them.

## What was measured (original, 2026-10-02)

```
$ cat .tmp/nc/nested_or.mojo
def f(n):
    if n > 10 or n == 0 or n < -4:
        return 1
    else:
        return 0
$ python3 fire.py build --formal -o .tmp/nc/nested_or.aout .tmp/nc/nested_or.mojo
nested_or_proof.lean:25:54:      error: unsolved goals        -- eval_eq_mojo
nested_or_proof.lean:5277:259:   error: counterexample       -- a merge hcond
nested_or_proof.lean:5324:261:   error: counterexample
nested_or_proof.lean:5668:257:   error: counterexample
nested_or_proof.lean:5720:259:   error: counterexample
```

The failure is honest — Lean rejects the file rather than accepting a
`sorry`-backed theorem — so nothing is silently wrong; the program simply has
no proof.

## Why the two-path statement does not reach it

`_emit_truthy_word` recurses, so a nested chain is a chain of chains and the
OUTER merge block has **four** entry paths, not two, each with a *different*
cset having written the condition register:

| path | X0 holds |
|---|---|
| outer taken, inner taken (`a`) | `a`'s cset |
| outer taken, inner fall (`b`) | `b`'s cset |
| outer fall (`c`) | `c`'s cset |

The machinery that was added states the merge block's register as ONE
operand's cset, found by looking back along the path for the block whose cset
wrote that register (`_cset_registers` in `formal/arm64_proof_gen.py`). That
works for a two-operand chain because each entry path has exactly one cset
before it. Here the outer merge's left operand is *itself* a chain, so
"the left operand's condition" is not one operand's cset — it is the value of
a sub-chain, and the fact that pins it (`hscL`) describes the sub-chain's
left operand, not the outer one.

## The next step

Recurse instead of stopping at two levels: make the travelling fact a *value*
fact rather than a boolean one. Concretely, the merge block's statement should
be

    arm64_reg r <merge> = 0 ↔ ¬(<the operand whose cset wrote r, on this path>)

with the cset's OWN condition recovered from the block it is in (the flag
lemma plus the block's `qT` chain, which `_cond_flag_lines` already does for
`loop_cond_flag`), rather than from the source AST. That makes the statement
independent of how many chains are nested, because every entry path then names
the machine's own answer instead of a source-level operand.

Two things to keep:

  * the recombination step (`_sc_merge_hsrc`) still needs the OTHER operand's
    fact, and for a nested chain "the other operand" is a sub-chain, so
    `hscL` has to be a fact about a sub-chain's VALUE. The natural shape is a
    `def <chain>_val (left : Bool) (right : Bool) : Bool` in the generated
    file with a `by_cases` proof of the `or`/`and` law, which then composes at
    any depth;
  * `either`/`both` must keep proving after that — they are the canary for the
    non-nested case and `test_formal_short_circuit_cond.py` is where that is
    asserted.

**Done when:** the program above builds and its proof typechecks, and
`test_formal_short_circuit_cond.py`'s `KNOWN_GAP` entry for it is deleted.

## Status 2026-10-03 (`work/formal8-8-r2`): NOT FIXED, and the diagnosis above
## is partly wrong in a way that matters

Re-measured on this tree and the failure is byte-for-byte the one above
(`5 errors, 0 holes`: one `unsolved goals` on `eval_eq_mojo` at 25:54 and four
`counterexample` at 5277:259, 5324:261, 5668:257, 5720:259 — the same four
lines, so nothing about the generator has moved). **What did move is the
understanding**, and the two corrections below are what a next session should
not re-derive:

**1. The generated statements are already per-path, correctly scoped, and
already about the sub-chain's VALUE.** Read the emitted file rather than the
generator's source:

```
have hcond_2 : (arm64_reg 0 s_2 ≠ 0) ↔ (a ≠ 0 ∨ b ≠ 0) := by …     -- a = n > 10, b = n = 0
  have hscL_2 : (a ≠ 0 ∨ b ≠ 0) := hcond_2.mp hc_2
have hcond_4 : (arm64_reg 0 s_4 = 0) ↔ ¬(a ≠ 0 ∨ b ≠ 0) := by …
  have hsrc_4 : ¬((a ≠ 0 ∨ b ≠ 0) ∨ c ≠ 0) :=
    fun (_ : …) => absurd hscL_2 (hcond_4.mp hc_4)
    have hsrc_4 : ((a ≠ 0 ∨ b ≠ 0) ∨ c ≠ 0) := Or.inl hscL_2
```

So `hscL_2` is `(a ≠ 0 ∨ b ≠ 0)` on one path and `¬(a ≠ 0 ∨ b ≠ 0)` on another,
in different bullet scopes and correctly shadowed; the outer chain's left
operand is rendered as an `Or`, not as one of its leaves; and `_sc_merge_hsrc`
already closes the merge by `absurd`/`Or.inl`/`Or.inr` against it. **The doc's
§"Why the two-path statement does not reach it" and its `hscL` bullet above are
both describing a generator that is not this one** — `_truth_go` recurses
through `_cmp_go` for `and`/`or`, so a nested left operand has been an `Or`
all along, and the travelling fact has been a fact about the sub-chain's value.
A `def <chain>_val` helper is therefore probably not the missing piece either.

**2. What actually fails is the VALUE FLOW of the `hcond` proof, not the
statement's shape.** Lean says so itself, on all four:

```
- It abstracted the following unsupported expressions as opaque variables:
  [arm64_reg 0 { x0 := x0✝¹, … x19 := x19✝¹, … }]
- The following potentially relevant hypotheses could not be used:
  [hsid_0, hcert_2, hsid_2, hcert_0, hcbz_0, hn, hs_0, h_adv_2, hg_0, hrun_2, hbnd, hrun_0, h_adv_0]
Consider the following assignment:  x19✝¹ = 0,  n = 0,
  arm64_reg 0 { … x19 := x19✝¹ … } = 9223372036854775808
```

`arm64_reg 0 s_2` is left OPAQUE, so the goal `(arm64_reg 0 s_2 ≠ 0) ↔ (a ≠ 0
∨ b ≠ 0)` is decided about an unconstrained variable and `bv_decide` is
right to object. The emitted proof *does* `rw [hsid_2]`, *does* put `hsid_2`
and `hsid_0` in the `simp only [...]` list and *does* `try rw
[mem_read_two_writes_adj_uint …]` — and Lean reports all of them unused, which
means the rewrite chain stops before the register is reduced. This is the
SAME symptom `arm64_proof_gen.py`'s own comment on the `_cset_bi != bi` branch
records for `either.mojo` ("Unfolding only the cset's own block … leaves the
register unreduced (`bv_decide` reports `arm64_reg 0 {…}` as an opaque
variable …), because the operand is read back out of a slot the chain's own
branch pushed and the rewrite that peels it needs the earlier block's store"),
and there the fix was to unfold the whole prior prefix in one term. **Here the
prefix is two chains deep, so the peel needs block 0's store AND block 2's, and
`ctx["flow_blocks"]` cannot be reaching both.**

**So the next step is in the flow, not the statement.** Two things to try, in
this order:

1. **Check that `ctx["flow_blocks"]` is the whole path for a nested chain.**
   `hcond_2`'s proof emits `hsid_2` and `hsid_0` — two predecessors — so the
   path IS two deep and the list looks right; what is missing is more likely the
   `_hcond_mem_rws(_all_instrs, …)` set, which is computed from
   `ctx["flow_blocks"]` and decides which memory slots get rewritten. Compare
   the `try rw [...]` list in `hcond_2` against the one in `either.mojo`'s
   passing `hcond`: if the nested one is missing a slot write, that is the
   whole failure and it is a one-line set difference.
2. **Then the `def <chain>_val` helper** — but as a way of making the
   SUB-CHAIN's merge statement composable, not as a fix for `hscL`'s shape,
   since (1) above shows that shape is already right.

`either`/`both` and `formal/examples/` must keep proving throughout; they are
the canary and `test_formal_short_circuit_cond.py` is where that is asserted,
with this program's `KNOWN_GAP` entry to delete when it lands.

**Not attempted here, and why:** this is Lean-level debugging of a 500 KB
generated proof at ~80 s per iteration with no bound on the number of
iterations, and the failure mode of a half-finished change in this file is a
generator that emits statements which LOOK right and are not proved — the
outcome this project treats as worst. The measurement above is worth more to
the next session than a partial rewrite would be.

## What is NOT claimed

* The failure was measured through `formal/lean.py::run_lean` on this tree
  (Lean found, `lib/*.olean` current, `LEAN_PATH` set to `lib`), 4.0 GB peak,
  under the wall/CPU bounds. The emitted file is
  `.tmp/nc/nested_or_proof.lean` for the exact program at the top; it is not
  committed.
* "The statements are already per-path and already about the sub-chain's
  value" is read off the emitted Lean, not inferred from the generator's
  source. It says the SHAPE is right; it does not say the statements are
  provable as written, and the four counterexamples say they are not proved
  today.
* No claim about x86-64: the two `*_cond_flag` / short-circuit mechanisms this
  file is about are the arm64 generator's, and nothing here was measured on the
  other architecture.