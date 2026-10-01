## Status (2026-09-27 — NOT ATTEMPTED: the only remaining work here is `formal/`, and that was out of scope this session)

Recorded so the next session with a `formal/` budget does not re-derive this.

"Still open 3" (below) is **entirely** inside `formal/`: the `dec`-while
and `range` loop MODELS, `prog_correct`'s induction split, and two
`sum_range` holes. Nothing in the compiler, the runtime, the interpreter
or the test suites is outstanding for this document — the CODEGEN half
and the 13-case runtime matrix were both complete before this session
(see the 2026-09-26 entry above).

**Not verified this session:** `test_formal.py` was deliberately NOT run
(it is what deadlocked the machine earlier on 2026-09-27, orphaning
`fire.py build --formal` workers on `lib/ProofLib.olean.buildlock`), and
no Lean proof was written or chased. The 91/91 `test_formal_run.py` and
the 38/5/0 arm64 proof census above are the 2026-09-26 numbers, carried
forward unverified.

The next action is unchanged and is the "Optimization"-free part of the
plan recorded below: the `Nat`-to-two's-complement signed-order lemma in
ProofLib, then `pred_iff`/`countdown_go`, then `prog_correct`'s step
case, then `sum_range_loop_cond_flag`.

## Status (2026-09-26 — BOTH halves landed; the loop MODELS are the one remaining gap)

| area | state |
|---|---|
| `B.cond` at every conditional site | landed |
| `for i in range(...)` loop exits | landed |
| Spill-slot displacement sign | landed |
| `while_dec_exit_contract` / `while_lt_exit_contract` parameterised over the loop TEST | **landed** — the register-shaped `cr` is gone |
| The 8 loop-contract `sorry`s (4 files) | **closed** — 0 remaining in those proofs |
| arm64 formal proofs | 38 pass / 5 known-gap / 0 fail (was 40/3/0; the 2 extra known-gaps are new and named below) |
| arm64 `sorry` census | 7 declarations (was 5): the 5 pre-existing `*_compiles_correctly_universal` run-test leaves, plus 2 in `sum_range` |
| x86-64 formal proofs | 43/43, unchanged |
| `test_formal_run.py` | 91/91 (was 33/33) — 15 signedness cases added |
| Unannotated `int` | **now SIGNED**, and `common_type` is signed-wins |
| Loop MODELS (`dec`-while, `range`) still assume a non-negative counter | **OPEN — see "Still open 3"** |

Both halves of this document's "Done when" are met for the CODEGEN and the
13-case runtime matrix; the formal side has two newly-recorded known-gaps, and
they are recorded because the obligation is genuinely unprovable, not merely
unproved (see "Still open 3").

## FIXED 1: signedness — `DEFAULT_INT_TYPE` is signed and `common_type` is signed-wins

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
incomplete, which is why it was reverted rather than committed. The per-step recipe, including the two
tactic orderings that each cost a cycle, is in the "Not open, but easy to
re-break" section above.

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
  convincing phantom "14+ spilled locals" bug that cost real time; that retraction is
  summarised in `FORMAL_arm64_instruction_coverage.md`.

## FIXED 2: the 13 loop-contract `sorry`s (the count was 8, in 4 files, not 13 in 9)

The census this document used was wrong, and the way it was wrong is the useful
part. It counted the WORD `sorry` in the generated proofs, which counts
*hypothetical* holes: every `all_goals (first | … | sorry)` fallback keeps the
word even when an earlier alternative won, so the textual count cannot go down.
Worse, the doc counted greps of a plain `lean` run, and a plain run reports
nothing when Lean serves a cached verdict. The real number — declarations Lean
itself reports as "uses `sorry`" — was **8, in 4 files** (`countdown`,
`sum_range`, `wdiff`, `wge`): 4 `loop_cond_flag` register halves and 4 loop-test
`hstep` obligations. The other 5 real holes (`count`, `fact`, `pow2`, `sqsum`,
`sum`, one `*_compiles_correctly_universal` each) are a different root cause and
are still open.

`formal/lean.py::_run_lean` now counts `declaration uses` in the real Lean
output and `check_proof_cached` returns it (4th element; the verdict key moved
to `formal-proof-verdict-v2` because the stored body changed shape).
`test_formal.py` reports the census after every run, so the number is always
authoritative and the loop contract's holes are visible in the tally rather than
in a hand-run grep.

**What closed them**, in `lib/ProofLib.lean` + `formal/arm64_proof_gen.py`:

- `while_dec_exit_contract` and `while_lt_exit_contract` are parameterised over
  `q : Arm64State → Bool` (`true` = leave the loop) instead of a register index
  `cr`. The register shape described the old `CSET`-then-`CBZ` lowering; the
  current lowering branches on the `CMP`'s flags and writes no register, so the
  obligation asked for a value-flow fact no instruction produces.
  `loop_test_def` emits one `def <name>_loop_q` per example, so the `refine`,
  the `hstep` tactic and the `cond_flag` lemma quote one symbol rather than three
  copies of the same expression.
- `_cond_flag_lines` + `_COND_ARITH` close the `cond_flag` leaf: unfold `q`,
  unfold the condition block's state chain, resolve the STP/LDP pair, rewrite
  with the flag lemma for the raw condition code (`_COND_LEMMA`, which already
  covered all ten), then close the arithmetic. The default closer is
  `decide | omega | grind`, which is enough for every shape the 43 examples
  contain.
- `_cond_step_tactic` is now a `by_cases` on `<name>_loop_q s = true` followed
  by `simp [<name>_loop_q, hs, hc]`, and it closes. Nothing is admitted.
- `while_dec_exit_contract`'s induction was also generalised, because a signed
  `int` means a NEGATIVE counter also leaves the loop: `hcondFlag`'s
  `q = true ↔ x19 = 0` became `hcondZero` (`x19 = 0 → q = true`) +
  `hcondStep` (`q ≠ true → x19 ≠ 0`) + `hcondDone` (`q = true → exit x0 = done
  x19`), and the step case splits on the test rather than deriving `¬q` from
  `x19 ≠ 0`. `hcondDone` is a real new obligation — before, the exit block's x0
  was pinned by `hexX0` under `x19 = 0`, which a loop that exits with a nonzero
  counter never satisfies.
- The generator's `loop_exit_x0` lost its `hpc` hypothesis: the obligation is
  pure value flow, its proof never reads `s.pc`, and once the contract was
  parameterised the caller holds the condition block's post-state, whose pc is
  the loop test and NOT the exit branch's target — so the hypothesis was not
  merely unused but unsatisfiable.

## Still open 3: the generated loop MODELS assume a non-negative counter

This is what the signed default exposes, and it is the one thing from this
document that is not done. With a signed `int`, `while n > 0: n -= 1` on
`n = -1` must return `-1` — the loop never runs. Two things still believe
otherwise, and both are the MODEL, not the machine:

1. `_gen_dec_while_block` (`formal/arm64_proof_gen.py`) emits `pred_iff` as the
   UNSIGNED `0 < UInt64.ofNat m`, and the model `countdown_go : Nat → UInt64`
   is `| 0 => 0 | k+1 => countdown_go k`, i.e. it returns 0 for every input. For
   `m >= 2^63` the loop test is false, so both statements are false, and
   `prog_correct`'s induction (which splits only on `m % 2^64 = 0` vs
   `0 < m % 2^64`) has no case for it. `wdiff` (`while n != 0`) is unaffected —
   equality is signedness-independent and the loop always reaches 0 — and still
   proves.
2. `sum_range`'s `loop_cond_flag` states the exit condition as the UNSIGNED
   `¬ (i < bound)`, so for a negative bound it is false and the leaf falls to
   the `sorry` (`rw [arm64_flag_ge_s]` rewrites the flag to a SIGNED `≥`, which
   is not what the statement says). Two holes there, up from zero.

Both are recorded rather than hidden: `countdown` and `wge` are in
`test_formal.py`'s `EXPECTED_FAILURES` with the reason, and `test_formal.py`
reports a stale entry as a failure if either starts passing. The fix is a model
change in two places, not a tactic:

- `pred_iff` becomes the signed test related to the Nat value with the
  `m < 2^63` conjunct the sign bit forces, proved from `UInt64.ofNat m`'s
  `m % 2^64`; the model becomes `if n < 2^63 then 0 else UInt64.ofNat (n % 2^64)`;
  and `prog_correct`'s step case splits on `m % 2^64 < 2^63` as well as on
  `eq_zero_or_pos`, with the new branch being one `runF_while_false` step.
- `sum_range_loop_cond_flag` is restated as `¬ (signed i < signed bound)` and
  `_gen_range_loop_model` is given the same `n < 2^63` split.

A signed `runF` arithmetic lemma pair (`sKey`-based order on `UInt64.ofNat`)
would be the reusable piece for both; ProofLib's `sKey` and its
`arm64_flag_*_s` lemmas are already the right shape, they just need the bridge
from `Nat` to the two's-complement word.
