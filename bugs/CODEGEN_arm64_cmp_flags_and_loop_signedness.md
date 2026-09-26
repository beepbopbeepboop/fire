# CODEGEN_arm64_cmp_flags_and_loop_signedness: arm64 conditional/loop codegen, and the signedness of unannotated `int`

Consolidated report for the arm64 formal backend's conditional and loop
lowering, and for the signedness model underneath it. `BUG.md` in the repo root
carries the running session log for this work; this document is the durable
statement of what is **open**, so a reader does not have to reconstruct it from
a diff.

## Status (2026-09-26 — conditional/loop selection LANDED; signedness PARTIAL; proof work PARKED)

| area | state |
|---|---|
| `B.cond` at every conditional site | landed, all runtime suites green |
| `for i in range(...)` loop exits | landed (they were absent entirely) |
| Spill-slot displacement sign | landed (was corrupting the caller's frame) |
| arm64 formal proofs | **40 pass / 3 known-gap / 0 fail** (was 30/3/10) |
| x86-64 formal proofs | 43/43, unchanged throughout |
| Negative-literal comparisons | **partially** fixed; see "still open" |
| Remaining formal sorries | 13, in 9 of 43 proofs; both sites have a known cause |

Runtime: `test_formal_run.py` 33/33, `test_arm64_emission.py` 5/5,
`test_arm64_encoders.py` 221/221, `test_formal_imports.py` 11/11,
`test_formal_dylib.py` 9/9.

## Still open 1: signedness only when BOTH operands are typeless literals

`formal/types.py` reports a negated literal as `IntType(64, True)`, because a
negative value cannot be an unsigned one. That fixes literal-vs-literal, and
range counters (whose seed was the unsigned default, so *every* range was
unsigned regardless of bounds). It does **not** fix anything involving a
variable, because an unannotated local gets `DEFAULT_INT_TYPE` — which is
`IntType(64, signed=False)` — and `common_type` resolves mixed
signed/unsigned to **unsigned** (the C rule, documented at
`formal/types.py:63`).

Measured after the fix (every row a real build + run, `test -3 < -5` included
because the negative-of-negative case is the one most likely to be wrong):

| source | result | correct | |
|---|---|---|---|
| `a = -3; if a < 2:` | 1 | 1 | ok — literal vs literal |
| `a = -3; if a < -5:` | 0 | 0 | ok — literal vs negated literal |
| `a = -3; if a > 2:` | 0 | 0 | ok — `>` too, so the inversion is fine |
| `for i in range(2, -3, -1)` | 5 | 5 | ok — counter seed fixed |
| `a = 0 - 3; if a < 2:` | 0 | 1 | **WRONG** — `0 - 3` is a `BinaryOp`, still typeless |
| `a = -3; b = 2; if a < b:` | 0 | 1 | **WRONG** — `b` is an unannotated local, so unsigned |

So the literal-vs-literal case is genuinely closed, in both directions and for
`range` in both directions. What is still broken is narrow and specific:

1. **A negative value produced by arithmetic.** `0 - 3` and, by the same route,
   `n - k` where the result is negative, do not go through `UnaryOp('-', …)`, so
   they keep the bare-literal rule and stay typeless. Folding a constant
   `BinaryOp` in `infer_expr` would cover the literal-literal subcase; the
   general case needs value analysis, which is out of scope here.
2. **Comparing a negative literal against a variable.** This is the deeper one
   and is the design point below.

So the remaining gap is a **consequence of the documented design**, not an
oversight in the fix: unannotated `int` is modelled as `UInt64`, and Python/Mojo
integers are signed and unbounded. Any comparison of a negative quantity
against a variable is still wrong.

**Why this is not a one-line change.** The knob is how `function_var_types`
types an unannotated local, and that decision is shared with the truncator
helpers, the width selection in `CSET`, the shift mnemonics
(`formal/x86_64_codegen.py:967`), and the comparison mnemonics (`:2100`,
`:2135`). Changing the default to signed moves all of them at once. Two
candidate directions, neither cheap:

* **Signedness by assignment.** Type an unannotated local from the type of its
  initializer, so `a = -3` is signed and `b = 2` is... still unsigned, which
  leaves the mixed case broken. Only fully solving the mixed rule (e.g. "signed
  wins" instead of the C rule) fixes the table above, and that changes
  `common_type` for every consumer.
* **Signed default for unannotated `int`.** Matches Python/Mojo semantics, and
  is one line — but it silently reinterprets existing unsigned code paths
  (shift, division, truncators), so it needs the full gate, not a spot check.

**Done when:** the four wrong rows above are right, and arm64 formal 40/3/0 plus
x86-64 43/43 both still hold. Also needs `Int8`/`Int16` negative literals
checked — they currently infer as `Int64`, which is a width mismatch rather than
a signedness one.

## Still open 2: 13 formal sorries, both sites from one root cause

Census at 40/3/0, counted by running Lean over the generated file with
`LEAN_PATH` set (a plain build reports `verified from cache` and never runs
Lean, so grepping its output returns 0 for every file — the wrong answer).

| site | files | cause |
|---|---|---|
| `cd_loop` value-flow goals | 9 | `while_dec_exit_contract`'s test is register-shaped |
| `loop_cond_flag` register half | 4 | same, from the other side |

`while_dec_exit_contract` states its step obligation over
`arm64_reg cr st = 0` (the generator passes `cr = 0`) because it was written for
the `CSET` lowering, which *wrote* the boolean into X0. `B.cond` branches on
`nzcv` and writes no register, so the contract asks for a fact the instruction
no longer produces — and the state at the loop header is arbitrary subject only
to its pc, so no tactic recovers it.

**The fix is one parameterisation**, replacing `arm64_reg cr st = 0` with a
caller-supplied `q : Arm64State → Bool` in `hstep`, `hcondFlag` and the three
internal uses. Verified in a WIP pass: `ProofLib` compiles with the change, and
the countdown shape (`b.ls`, raw code 9) is **fully proved** with no sorry, via

```
simp only [<block defs>, arm64_reg, arm64_set_reg]
rw [mem_read_push_low s.mem s.sp]     -- resolve the STP/LDP pair FIRST
rw [arm64_flag_le]
simp (disch := decide) [mem_read_after_write_u64, ..., u64_ofNat_add]
```

The wall: the closing arithmetic lemma is **per condition code**, not per shape.
`countdown` (raw 9) builds; `wdiff` (raw 0) needs `Iff.rfl`; `wge` (raw 3)
against a bound of 1 needs a `u64_lt_one` sibling of `u64_le_zero_iff`. So the
remaining work is a small table beside `_COND_LEMMA` mapping each raw code to
(flag lemma, arithmetic lemma). Suite went 40/3/0 → 38/3/2 while that was
incomplete, which is why it was reverted rather than committed; the full writeup
is in `BUG.md`.

**After that:** `while_lt_exit_contract`, the counting generalisation at
`ProofLib` ~3002, has the same register-shaped `hstep` and was not touched, so
the two will drift.

## Not open, but easy to re-break

* **`_STEP_CONDS` overlapping pairs.** Entries 3/5 (SUB/NEG), 4/47 (MUL/MSUB)
  and 48/50 (LSR/LSL) can match the same word. `_step_facts` now decides per
  *word* rather than per table, leaving a shadowed entry unconstrained instead
  of negating it, and `audit_step_table()` enforces (a) the condition sets match
  and (b) for every overlapping pair the table-earlier entry is also
  `ProofLib`-earlier. `test_formal.py` calls it before any Lean runs. The
  tempting alternative — rule out only the entries *before* the chosen one — is
  unsound: the two orders do not agree globally (`B.cond` is model position 18,
  table index 51).
* **Spill slots are below X29.** `_spill_off` returns the distance *down*; the
  `ldur`/`stur` fast path must negate it. The positive form addresses the
  caller's frame and silently corrupts it. Invisible to any single-variable
  test, and it needed >10 locals to show up at all.
* **Every expected value in `test_formal_run.py` must fit in a byte.** A process
  exit status is 8 bits; comparing an 8-bit code against a wider sum produced a
  convincing phantom "14+ spilled locals" bug that cost real time. See the
  retraction in `BUG.md`.
