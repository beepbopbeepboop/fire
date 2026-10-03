# FORMAL_nested_short_circuit_chain_in_a_condition: `((a or b) or c)` is still unproved

`if a or b:` and `if a and b:` as a whole condition are **proved** (the
per-path entry statement they needed is in `formal/arm64_proof_gen.py`;
`formal/examples/either.mojo` and `both.mojo` build AND typecheck). A chain
NESTED inside a chain is not, and this says why and what closes it.

## What was measured

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