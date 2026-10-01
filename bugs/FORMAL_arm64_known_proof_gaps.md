# FORMAL_arm64_known_proof_gaps: the arm64 examples whose proof is a documented gap

The arm64 formal suite is **39 pass / 6 known-gap / 0 fail** (measured
2026-10-01, `python3 test_formal.py`). The six gaps are listed in
`EXPECTED_FAILURES` in `test_formal.py`, and that list is the authority on
whether they are still gaps — a stale entry is reported by the harness's own
check. This document says *why* each one is hard and what closing it needs,
which the inline comments do not.

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

## `countdown` and `wge` — the generated loop MODEL, not the machine

These two are the `while n > 0` / `while n >= 1` spellings of one shape, and the
shape is a MODEL, not a lowering. The measurement that settles it (and that the
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md` entry now records) is that a
negative counter really does leave the loop immediately and is returned
unchanged — so `countdown_go`'s `| 0 => 0 | k+1 => countdown_go k` is the wrong
function of the source for exactly the inputs the sign bit selects.

`wge` is the same gap as `countdown` (`≥ 1` rather than `> 0`); `wdiff`
(`while n != 0`) is NOT affected, because equality is signedness-independent,
and it passes with no hole. Both are in `EXPECTED_FAILURES` with the reason.

**Owner:** `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` §"Still open 3",
which names the three generator sites and the statements each has to become.
This document does not repeat them; the two are one piece of work and the
other one is the precise version.

## `subscript_var` — a runtime index has no domain in the model

`a = [10,20,30]; i = 1; return a[i]`. The program builds, runs and returns 20
on both architectures, and the x86-64 generator proves it. On arm64 the
*machine* half is proved — every `LDR`/`STR` through a non-SP base gets a correct
step RESULT lemma, and the block certificates build. What is missing is the
*source* half, and it is not a dataflow question: the semantic model is
`UInt64 → UInt64`, so a list has no domain in it and `a[i]` has no value; and
the list's storage (a blob whose first word is its count) is never related to
the source literal.

**Owner:** `FORMAL_wide_receiver_by_reference.md`, which records both halves
(a list domain in the model, and a `Frame.frameToEnv`-shaped fact about the
blob). Left out of the sections above only because it is that document's
subject, not this one's.

## Relationship to the `B.cond` work

These gaps are **pre-existing** and independent of
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md`'s CODEGEN half. That work took
the suite from 30 pass / 10 fail to 40 / 0 without touching them. Three
distinct problems, and the counts should not be conflated:

| | count | owner |
|---|---|---|
| known gaps (fail, documented reason) | 6 | this document (`either`/`both` = 1 shape, `fib` = 1, `countdown`/`wge` = 1, `subscript_var` = 1) |
| sorries in passing proofs | 2, both in `sum_range` | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` ("Still open 3", item 2: the range loop's `loop_cond_flag` states an UNSIGNED order) |
| passing proofs carrying no `sorry` at all | 38 of 39 | — |

The `either`/`both` and `fib` entries above are the original three gaps of this
document; `countdown`, `wge` and `subscript_var` were added later and are
recorded in `test_formal.py`'s inline comments with the same contract.
