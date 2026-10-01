# FORMAL_x86_64_end_to_end_proof: a vacuous step lemma, a form proved as the wrong instruction, and the end-to-end theorem that hides both

## Scope of this doc

Every x86-64 bug found and fixed while building the Lean formal layer for the
x86-64 backend — `lib/X86.lean` (the machine model and its step lemmas) and
`formal/x86_64_*.py` (the proof generator, the end-to-end theorem emitter, the
model-vs-hardware test). These are the bugs I have direct visibility into.

Deliberately **not** in here: the bulk per-module sweep results, which live in
`COMPILE_FAIL_*` and `CODEGEN_*` docs and are mechanical findings rather than
analysis. Two bugs below (`FORMAL`-numbered B16, B17) were *found* by running
the generator across the repo rather than over `formal/examples`, but what is
recorded is the bug and its fix, not the sweep.

Bug numbers (`B1`…`B23`) are this doc's own, for cross-reference.

## Status (2026-09-26 — 24 of 43 examples proved; B1–B23 recorded below)

The x86-64 backend now has a Lean model that agrees with the hardware on all 43
examples, per-instruction step lemmas for most of what the backend emits, and a
real end-to-end theorem:

| | result |
|---|---|
| `formal/x86_64_model_test.py` — model vs hardware | **43/43 agree**, 0 wrong |
| `formal/x86_64_model_coverage_test.py` | **151 samples over 57 forms**, all steppable |
| `test_formal.py --backend x86_64` | **43/43 PASS**, 0 known gaps, 0 fail |
| `make check-formal-x86-endtoend` | **exit 0**, 0 failing |
| value theorem — *every* input, `rax` a fixed constant | **3 proved**, 0 open |
| termination theorem — *every* input reaches the exit pc | **10 proved no-sorry, 14 proved with a sorry** |
| no finite path tree | 19 (4 loop, 15 uncovered form) |

Two theorems of very different strength, and the gap between them is the whole
story of B21. The value theorem is the stronger statement but can only be
*formulated* for the 7 input-independent examples, so it proves for 3. The
termination theorem makes no claim about the value and covers 24 — and
`identity` is the example that shows why it is the one to chase: it returns its
argument, so the value theorem can never say anything about it, and here it is
proved.

The 14 sorries are not free. Each is a real step lemma or a memory-separation
inequality Lean declined, and Lean reports them per file, so the gap stays
countable instead of becoming either a build failure or a silent omission.

Commits, oldest first: `f6046f3` (the model), `cc7e67b` (prologue lemmas),
`1b2bdb9` (memory separation + per-instruction certificates), `4d6f3ca` (the
first end-to-end proof), `438cb68`/`471782d`/`f918072`/`9bda629` (generalising
the step lemmas), `f9830d4` (the vacuous lemma), `1b35d73` (the termination
theorem), `3f2cb34` (the `rbp+disp8` load), `694433c` (`imul` + admitted side
conditions).

---

## B1. A step lemma with contradictory hypotheses — green, and proving nothing

**The worst bug in this file, because it is a proof-integrity bug rather than a
wrong answer.** `f9830d4`

`x86_step_setcc_r8` carried the hypothesis `¬ ((0x80 : UInt8) ≤ op2)`. Every
`setcc` opcode byte is at least `0x90`, so the hypotheses were contradictory.

A lemma with contradictory hypotheses still compiles, still typechecks against
the model, and still proves its goal. It simply cannot be applied to anything.
So the file was green and the lemma was doing nothing at all — and that is
strictly worse than its absence, because an absent lemma shows up as a gap
while a vacuous one looks like proof. 26 examples' worth of `setcc` were in
this state.

Only the **upper** bound of the `jcc` range needs excluding, since `0x90 ≤ op2`
already places a `setcc` byte above that range.

Fixed, and — the part worth keeping — **checked rather than assumed**: all nine
of the lemma's hypotheses are now shown satisfiable at a real `setne al` site,
by `native_decide` on each. "The file builds" is exactly the signal that missed
this bug, so the check that replaces it has to be a different one.

## B2. A form proved as a different instruction

`f9830d4`

A legacy `mov_rm64_r64` entry still mapped to `x86_step_mov_rbp_rsp` — one
register pair — under a form name covering an entire opcode. `_shapes` had no
case for the SIB store, so `48 89 04 24` (`mov [rsp], rax`) was being proved as
`mov rbp, rsp`.

The key is deleted, so an unmapped shape is *reported* instead of silently
satisfied by whatever lemma happens to share its name, and
`x86_step_mov_mem_sib_rsp` was added for the real form.

## B3. Placeholder substitution was positional, and broke any BUILT successor

`f9830d4`

Successor templates were substituted positionally: `$s` and `$m` first, then the
per-form values. Any form whose successor is itself *built from* those values
had `$s` and `$rex` land in the output after their own replacement had already
run — four ALU forms, reported as:

```
term.pseudo.antiquot has not been implemented
```

which names neither the form nor the substitution that broke. Now a **fixpoint
over one table**: a value substituted in can itself contain placeholders, and
no fixed ordering survives that. Sorting by length only moves the breakage to a
different form.

## B4. `takes_imm` true for three forms that have no immediate to take

`f9830d4`

`takes_imm` was set for `jcc_rel32`, `jmp_rel32` and `setcc`, whose immediates
already arrive through `extra_args` — so a spurious imm32 was read out of bytes
that are not there.

## B5. `all_bytes` was one `native_decide` over the whole function

`f9830d4`

A single `native_decide` over a conjunction of every byte in the function. A few
hundred conjuncts exhaust instance synthesis and it fails. Now chunked with
`And.intro` / `native_decide` per conjunct.

## B6. The `0x0F` escape has two dispatches and they disagree on length

`9bda629`

The costliest single bug here, and the one most likely to be reintroduced.

The `0x0F` escape is dispatched **twice** — once in `x86_step_rex`, once in
`x86_step_plain` — and the two disagree:

| | length | `x86_rm_write` at | `rex` |
|---|---|---|---|
| `x86_step_rex` (prefixed) | **four** bytes | `rip + 3` | the real prefix |
| `x86_step_plain` (no prefix) | **three** bytes | `rip + 2` | hardcoded `0` |

A successor stated with the wrong one is *a proof of a different instruction*.
It fails as `⊢ False` after `simp` has mangled the goal, which says nothing at
all about the length being the problem. It was got wrong twice before being
spotted by reading `x86_step_plain` rather than reasoning about it.

## B7. Register/field sense read backwards still typechecks

`438cb68`

The destination is the ModRM `reg` field extended by `REX.R`; the source is the
`rm` field extended by `REX.B`. For the store direction that swaps.

Read the other way round, it still typechecks while both indices are symbolic
— which is exactly how `x86_step_mov_rbp_rsp`, a single register pair, came to
be filed as if it were the general lemma. The parameters are named `reg`/`rm`
rather than `src`/`dst` precisely so the next reader does not re-derive this and
get it wrong the same way.

## B8. `x86_rex_w`/`_r`/`_b` tested bits on `UInt8`

`438cb68`

Same values, but `simp` reduces `Nat` literal arithmetic and knows no lemmas for
`UInt8`'s, so the `UInt8` form left `if 72 &&& 1 = 0 then …` unreduced — which
is what every symbolic register index turns into. Now `Nat`-based.

## B9. A step equation passed straight into `obtain` left hypotheses as metavariables

`438cb68`

The step equation is now stated with its successor **explicitly** before the
`obtain`. Passing the step lemma directly into the anonymous constructor leaves
the lemma's own hypotheses as metavariables.

## B10. `x86_set_reg` is a `match`, and `simp` will not reduce it on a non-literal

`3f2cb34` — the deepest one, and the reason a whole class of lemma does not go
through

The `rbp + disp8` **load** could not be generalised with a symbolic destination.
The destination is `x86_set_reg s (reg + x86_rex_r rex) …`; `x86_set_reg` is a
`match` on its index, and `simp` does not reduce a match on a non-literal. The
goal survives as two 20-field structures that differ in a `match`, which
displays the entire field list and says nothing about which field or which term
is at fault.

The **store** next to it has the same shape and normalises fine, because there
the index only ever appears inside `x86_get_reg`. That asymmetry is the whole
difficulty, and it is why the store was fixable by generalising and the load was
not.

The load takes the destination as a **concrete argument**, with
`reg + x86_rex_r rex = dst` beside it, and the caller — which can read the
destination out of the encoding — supplies it. With a literal index the match
reduces and the goal closes. Covers the 10 disp8 loads carrying REX `4c`; took
the termination theorem from 6 examples to 9.

The same `dst` treatment is why `imul`'s lemma (B20) is written the way it is.

## B11. A store pinned `x86_rex_r rex = 0` while the backend emits `4c`

`1b35d73`

The `rbp + disp8` store was stated with `x86_rex_r rex = 0`, but the backend
emits REX `4c` — W and R — for an `r8` source in 10 of the 33 disp8 stores. The
lemma was inapplicable to a third of the sites it was supposed to cover, and
inapplicability here is indistinguishable from a proof (see B1). Now general in
both REX bits.

## B12. The simplifier does not fold large `Nat` literals

`1b35d73`

`simp` does not reduce `4294967868 + 4` to `4294967872`. A successor stated as
an addition therefore leaves every subsequent `rip` comparison unprovable, and
the failure reads as a bare `False` from the `simp` that was trying.

Every successor address is now emitted as a **literal**, not `$m + length`.

## B13. Branch target computed from the wrong base

`1b35d73`

A relative branch's target is `addr + instruction_length + displacement`. Getting
the base wrong puts both successors somewhere else in the image, so the path tree
follows a chain that does not exist and the failure is a bare `False` at some
much later step.

## B14. A fork taken on the wrong state, and with its children in the wrong order

`1b35d73`

Two independent errors, each producing a failure that named something else:

- The condition belongs to the state the branch **reads**, not its successor. A
  `jcc`'s successor carries `rip := if x86_cond cc s_k … else …`, so splitting
  on the successor's own flags yields a hypothesis that rewrites nothing and
  leaves the next address an `if`.
- `by_cases` presents the **true** case first, so the taken path has to be the
  **first** child. With the fall-through first, each arm gets the other's
  hypothesis.

## B15. Nesting successors makes the kernel hit deep recursion

`4d6f3ca`

Rewriting a run with the step lemma nests each successor into the next. By the
sixth instruction the term is deep enough that the kernel reports deep
recursion *while proving the last step*, which is a long way from saying
anything about the sixth.

The fix is to never substitute: each successor is an `obtain`-introduced
**variable**, so every side condition is stated over one state and the term the
kernel normalises stays a single structure update deep however long the function
is. The successor's own equation comes from the step lemma one
`Option.some.inj` at a time; later steps read what they need out of it with
`simp`.

This is what makes the method scale to whole functions at all.

## B16. The model was applied to a guessed argument type and a guessed argument name

`14ca294`, `0d2ef70`

`mojo` applied the semantic model with a **guessed** argument: `n.toNat` when a
countdown/`while` pattern matched, `n` otherwise, and `n` for the parameter
*name*. So:

- a `for` loop over `range` fires the `while` pattern but produces a
  `UInt64`-parameterised model — a type mismatch that failed the whole proof for
  a function the model handles perfectly well;
- a function whose parameter is called `x` emitted `def mojo (n) := double_go x`
  — with `x` not in scope.

The model's parameter **type** is now read out of the generated definition, and
the model is applied **positionally** to `mojo`'s own parameter, so neither can
drift. Both emitted shapes are recognised — `def f_go (n : Nat) : UInt64 :=` for
a bounded model, and the curried `def f_model : Nat → UInt64` with equation
clauses for the tree-recursive one; matching only the first broke `fib`.

## B17. Three generator bugs whose failures all read as "the machine model is wrong"

`14ca294`, `0d2ef70` — the most misleading class in this doc, because each
failure blames the model for a program whose arithmetic is fine

- **A model referencing a function it never defines.** A class constructor
  lowers to `Point_go` with no `Point_go` anywhere. The model is now checked
  against itself: every `<name>_go`/`<name>_model` it mentions has to be one it
  defines, and one that fails falls back to the placeholder.
- **A run test that could never hold.** `classify` returns a string, and the
  machine's result is the **address** of an interned literal. No numeric model
  of `return "small"` is that address, so the comparison failed for an entirely
  correct program. A function returning a string literal is now detected and
  says so.
- **Run tests emitted for images that call `print`** — a branch to a
  `__TEXT,__stubs` trampoline *outside* the image, which the model has no memory
  for. The run stops there, the termination obligation fails, and the failure
  says "the machine model is wrong". The section's docstring already claimed
  such programs were excluded; the code never did. It does now, naming the
  symbols it excludes and why.

With all four suppressed-for-the-right-reason cases in place, a run test that
fails now means the model and the source semantics disagree — which is the only
thing it was ever evidence for.

## B18. A memory-separation statement that could not be combined

`1b2bdb9`

`mem_read_bytes` recurses on the read **width** and `mem_write_bytes` on the
byte **count**, so a single induction sees through only one of them, and a
combined statement leaves eight unreduced `if i = a` tests in the goal.

Split in two, each induction is single-headed: the write is the identity
pointwise outside its range, and a read through it is the read of the original
memory. Four lemmas, for writes and reads, above and below.

**What this still does not close.** For a function that spills its argument, the
closing read's address is a `mem_write_bytes` chain whose offsets are literals
but whose *value slot* is symbolic, so the inequality the separation lemma needs
is not closed. `decide` reports `Expected type must not contain free variables`,
which names the tactic rather than the inequality that would have closed it, and
`omega` cannot see through `mem_write_bytes`. This is the sole reason 14
termination proofs carry a sorry.

## B19. `imul`'s ModRM is at `raw[3]`, not `raw[2]`

`694433c` — the most recent, and a good illustration of B3

`imul r64, r64` is `REX.W 0F AF /r`: the ModRM is two opcode bytes further out
than for every other form, so it sits at `raw[3]`. The generator's generic `$rm`
default reads the ModRM from `raw[2]` — which for `imul` is the **second opcode
byte** — and so silently supplied `0xaf &&& 7 = 7` as the source register.

The result is a `Type mismatch` that displays the entire successor record and
names neither the form nor the byte it got wrong. Pinning `$rm`/`$reg`/`$rex` in
the form's own branch fixes it.

`imul` is also the one form whose destination is the `reg` field — the same field
the first multiplicand is read from — so it is `reg := reg * rm`, and it sets no
flags, so its successor is just the register and the rip.

## B20. The input-independence probe was always true, and every attribution it made was bogus

`9bda629`

The probe wrote `native_decide` without `by`, so it always reported "depends on
the input". With it fixed, **7 of 43** examples are input-independent — which is
the real ceiling on the constant-result value theorem, and much lower than it
had looked.

## B21. The reporter conflated proved, not-applicable, and uncovered — as "failing"

`9bda629`, `694433c` — worth recording because it hid everything else

Three different outcomes were all being reported as failures:

- a result that **depends on the input**, where the value theorem cannot even be
  *formulated*;
- a function with a **loop**, where the chain walks one straight line — a limit of
  the method, not a proof that broke;
- a form with **no step lemma**, where the theorem cannot be attempted at all.

At one point this read as **36 failing** out of 43. The real number was 2, and
after B23 it is 0. The reporting now distinguishes `[PROVED]`, `proved with a
sorry`, `depends on the input`, `loops`, `no lemma: <form>`, and `FAIL`.

## B22. An absent lemma and an unproved step are indistinguishable — and it hid a real gap

`694433c`

`imul` had no step lemma, which put 8 examples outside the path tree
altogether. But the reason those 8 were also failing was **not** the missing
`imul` lemma: the `rsp + disp8` load's own side conditions do not close, and the
file never got far enough to say so. They reported "no tree" when the truth was
"tree, one step unproved".

So a form with no lemma is not merely a gap — it **conceals** the state of every
other form in the same function, because the file dies before reaching them.
Wiring a form up is therefore also a diagnostic act, and the 8 came back proved
as soon as the side conditions were admitted.

## B23. Two shapes of `sorry` guard that do not work, both of which kill the file

`694433c` — the last thing to get right, and both failures are silent

Guarding a proof so an unclosed step is *admitted and reported* rather than
fatal, in the user's words "use sorries for anything hard", has exactly two
non-obvious requirements. Getting either wrong takes the whole suite from 23
proved to 0.

1. **The guard must be inside the inline `by`.** An unsolved goal inside
   `(by simp [hs12])` is an **elaboration error**, not a tactic failure. Nothing
   enclosing it catches it: not an enclosing `try (exact …)`, not
   `first | exact … | sorry` around the whole step. The file dies.
2. **It must be `try (… ) <;> all_goals sorry`, not `first | … | …`.** `first`
   commits to the first alternative that does not **throw**, not the first that
   **closes the goal**. A `simp` that runs and simplifies nothing counts as a
   success, so the `sorry` alternative is never reached and the goal is reported
   unsolved at the `sorry`.

A third, purely layout: `first | ( … ) | sorry` written across lines is
fragile in a way that is not worth the risk — a `| sorry` one column out is read
as an alternative of the *enclosing* tactic and the file stops parsing with
`unexpected token '|'`. The sequential `try … <;> all_goals sorry` form has no
such failure mode.

A fourth, and it is not a guard at all: a **heartbeat timeout is not catchable
by `try`**. `elif3`'s closing separation `simp` exceeded the 800 000 budget and
reported a deterministic timeout. The budget is now 4 000 000; raising it is the
only lever, because a timeout is not a tactic failure.

---

## Open, in the order I would take them

**`call_rel32` (7 examples) — the last big uncovered form.** It needs *two*
successors *and* a memory write: it pushes the return address and jumps. The
pushed word has to be shown separated from the callee's frame, and the callee
must be in the path tree at all. This is a bigger job than `imul` was, and worth
thinking about before writing.

**The remaining uncovered forms**, after `call_rel32`: `movsx_r64_r8` (3
examples) and eight singletons — `alu_rr:and`/`:or`/`:xor`, `alu_rr32:xor`,
`shift_imm8:shl`/`:shr`, `group3:div`, `alu_ri32:and`, one example each. That
is 12 distinct forms over 18 example-slots; an earlier draft of this line said
"15 uncovered forms" and listed `alu_ri32:add_other` as well, both of which
measurement contradicts — the gate prints 15 *examples* with no coverage, which
is a different quantity from the number of distinct forms. Counts re-measured
against `emit_terminates` rather than a proxy; see `OPEN_WORK.md` D2 for the
separate loop-count discrepancy, which is still unresolved.

**The 14 sorries** (B18): the symbolic `mem_write_bytes` separation inequalities.

**The 4 loop examples** — `countdown`, `sum_range`, `wdiff`, `wge`. No finite
path tree, because the chain walks one straight line; these need induction over
the back edge. A limit of the method as built, not a proof failure.

**The generalisation rule this file keeps relearning**, worth stating once:
generalise a form when the backend actually emits more than one shape of it, and
not otherwise. `movzx r64, r8` is emitted as the identical `48 0f b6 c0` in all
33 instances, so the concrete `x86_step_movzx_rax_al` already in `X86.lean`
covers them and a register- and nibble-parameterised version would be machinery
nothing calls. Conversely every form that *was* pinned to one register pair
turned out to need generalising (B7), so the rule is a heuristic, not a proof.

## Nested comprehensions, both backends — FIXED 2026-09-30

Both x86-64 observables below were ONE bug, and it was not the recursion.
`_emit_range_list` named its labels `_rz{id}` / `_rd{id}` / `_rabs{id}` /
`_rok{id}` / `_rfill{id}` / `_rdone{id}` so two `range()` calls in one
function could not collide — and then reassigned `abs_label` to the rid-LESS
`_rabs`, a few lines later, defeating it. The label table keeps the LAST
address for a name, so the FIRST `range()` in a function branched into the
SECOND one's `abs` block and left through the second's `jmp div_label`. Its
blob was never built and its base never stored; the outer generator looped
over a callee-saved register nothing had written, and read the count from
address 0 or from whatever the caller left there. Hence a wrong sum, a wrong
count, and a SIGSEGV that came and went between runs of one binary.

Measured on the real binaries under Rosetta, before -> after:

| case | x86-64 before | x86-64 after |
|---|---|---|
| `[i+j for i in range(5) for j in range(5)]`, summed | 98 | **100** |
| `len` of the same | 4 | **25** |
| `[i+j for i in range(2) for j in range(2)]`, summed | 241 | **4** |
| `[i+j+k for i in range(2) ... for k in range(2)]`, summed | 1 / -11 | **12** |
| two `range()` calls in one function, both summed | 38 | **9** |

The arm64 residual (4x4 sum exactly double) was this same x86-64 measurement
being read against arm64, which was already correct; 4x4 is right on both now.

All of it is a case in `test_x86_64_containers.py` (`nested-comprehension*`,
`two-ranges-one-function`), which now also cross-checks every expectation
against CPython — the first version of that harness's notes had two sums
computed at n=4 and read by a harness that runs at n=5.

The dict-comprehension half of the same cluster (right keys, wrong values) and
the arm64 refusal of a comprehension as a subscript base were separate bugs and
are fixed too; see the two commits on `work/codegen-old-divergences`.

## How to continue

`make check-formal-x86-endtoend` is the gate, and it reports both theorems
separately with a per-example breakdown, so a regression in either is visible
immediately. The number to watch is **terminates proved with no sorry** (10) —
a change that pushes it down has taken a real proof away even if the file still
builds, which is precisely the failure mode B1 and B11 had and B21 now makes
visible.

If you are adding a form: the three places that must agree are `_FORMS` (lemma,
`takes_imm`, side conditions), `_SUCCS` (the successor shape), and the branch in
`_resolve` (extra arguments and placeholder values). A form wired into one and
forgotten in the other fails as a `KeyError` at `_SUCCS[form]` or, worse, applies
the wrong `$rm`/`$rex` defaults (B19). `_resolve`, `_shapes` and `_header` are
shared between the straight-line and path-tree emitters precisely so a form
cannot be wired into one and forgotten in the other.

When a side condition will not close, add it to the `try … <;> all_goals sorry`
guard rather than working around it, and check afterwards that the no-sorry
count did not fall (B23).
