# FORMAL_arm64_known_proof_gaps: the three arm64 examples whose proof is a documented gap

The arm64 formal suite is **40 pass / 3 known-gap / 0 fail**. The three gaps are
listed in `EXPECTED_FAILURES` in `test_formal.py`, and that list is the
authority on whether they are still gaps — a stale entry is reported by the
harness's own check. This document says *why* each one is hard and what closing
it needs, which the inline comments do not.

Per the harness's own contract: an entry here means "known unproven, for the
stated reason" — **not** "passing". Nothing is ever stubbed with `sorry` to go
green, because a `sorry` makes Lean accept the theorem, which would assert
exactly the semantics these examples exist to check.

## `either` and `both` — short-circuit conditions need a per-path statement

`either` is `if n > 10 or n == 0:`; `both` is `if n > 0 and n < 10:`. Same
shape, and the same missing piece.

A short-circuit `and`/`or` lowers to a `CBZ`/`CBNZ` **of its own**, which closes
a basic block exactly the way the `if`'s own branch does. The merge block
therefore has **two entry paths carrying different values in the condition
register** — the left operand on the short-circuit path, the right operand's
`CSET` on the fallthrough. A single `arm64_reg 0 <state> = 0` statement cannot
describe that; the entry condition has to be stated **per path**, and the
generator's per-block `def` chain cannot yet express that.

The CFG metadata that identifies the real `if` branch already exists
(`info["cond_branches"]` in `formal/arm64_codegen.py`, consumed by
`_gen_universal_e2e_cfg`). **What is missing is only the path-split statement.**

**Done when:** the entry-condition emission can state one proposition per entry
path of a merge block. The two short-circuit forms deliberately keep their
`CSET` + `CBZ` lowering — a short circuit genuinely needs a value, because there
are no flags to read — so this gap is orthogonal to the `B.cond` work and is not
closed by it.

## `fib` — a tree-recursion `FrameOk` window read

`fib(n) = fib(n-1) + fib(n-2)`, tree recursion, one goal left.

The caller's `FrameOk` window read sits over the callee's store stack, whose
addresses the frame canonicalisation's `u64_sub_add` splits into `sp - (K - 8)`.
`mem_read_write_below` peels a single store at `sp - UInt64.ofNat K`, so the
split has to be folded back first — and the nesting depth is data-dependent.

**Per-depth collapse lemmas were tried, and each one exposed the next form.**
That is recorded here so nobody restarts the ladder. The right fix is to teach
`mem_read_write_below` the split form so that nothing needs collapsing at all.

## Relationship to the `B.cond` work

These three are **pre-existing** and independent of
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md`. That work took the suite from
30 pass / 10 fail to 40 / 0 without touching them, and its 13 remaining sorries
are a separate matter again (two sites, one root cause: `while_dec_exit_contract`
is written register-shaped). Three distinct problems, and the counts should not
be conflated:

| | count | owner |
|---|---|---|
| known gaps (fail, documented reason) | 3 | this document |
| sorries in passing proofs | 13, in 9 of 43 | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` |
| passing proofs with no assumption | 34 of 40 | — |
