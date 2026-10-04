# FORMAL_x86_64_end_to_end_proof: a vacuous step lemma, a form proved as the wrong instruction, and the end-to-end theorem that hides both

## Status (2026-10-03 — B26/B27: the return is followed, and the byte facts are computed)

Two more of the same kind of bug, both found by making the prover handle a
program larger than the corpus:

**B26. The path tree stopped at the callee's `ret`, so every program with a call
had no theorem at all.** `_tree` now gives a `ret` with a frame to return to the
successor the matching `call` pushed and walks the caller's continuation. The
step needs `s_k.rip`, which the model says is read out of the frame rather than
stated, so the emitter introduces it as `hpop{k}` and rewrites the step with
`rw [← hpop{k}]` — **backwards**, because the successor already carries the
literal and the literal has to become `(mem_read_bytes …).toNat` again for
`x86_step_ret`'s conclusion to match. **The step is still proved by the model**,
which is the whole point of doing it this way round; B25's failure was a step
proved as something the machine does not run, and this is the opposite
arrangement. `hpop{k}` and, for a chain that crossed a frame, the closing `hrip`
are admitted.

**B27. Every hypothesis about the code handed `simp` the whole `all_bytes`.**
`b0..b3`, the immediates and the displacements were `simp [read_i32_le, read_i8,
hb]`, and `hb` is one conjunct per byte of the function — so one byte fact cost a
`simplifier` pass proportional to the size of the program, five times per
instruction. This is invisible at 45 examples and fatal at 164: measured on a
24-argument call, `maxHeartbeats 4000000` was exhausted at `whnf` on step 19's
`h_b1` and again on step 105's `h_disp`, and the file **died** both times, because
a heartbeat timeout is not a tactic failure and the guard cannot admit its way out
of one (B23's fourth point, and the first time it has been the *cause* rather
than a footnote). `first | native_decide | simp [read_i32_le, read_i8, hb]`
settles each one outright and keeps the simplifier as the fallback.

| | 2026-10-02 | 2026-10-03 |
|---|---|---|
| `.tmp/w24np.mojo` — 24 arguments, 164 steps | `no tree: returns into a caller` | **`terminates: proved, 1 sorry`** (127 s, 5.0 GB) |
| `formal/examples/wide_recv.mojo` | `no tree: returns into a caller` | **`terminates: proved, 1 sorry`** (34 s, 2.3 GB) |
| `no finite tree` — the "returns into a caller" column | 1 | **0** |
| `bitops`, `const2` (no-call controls) | `PROVED` | **`PROVED`, reports identical with and without B27** |

**The 45-example sweep was NOT re-run** — this was a light pass and the sweep is
a heavy run — so every row of the 2026-10-02 table below stands as written, and
the one to check first is **`terminates proved with no sorry`, which must still
read 32**: B26's code is unreachable for an image with no `call`, and B27's is a
fallback-preserving change, and both facts are pinned Lean-free by
`test_formal_sweep_truth.py::TestX86EndToEndEmitter`.

**And the number the reader will want is not the number the report gives.** Lean
reports "declaration uses `sorry`" once per DECLARATION, and
`formal/lean.py::_census_from_output` de-duplicates by name, so a chain with four
admitted `hpop`s reads as `proved, 1 sorry` exactly like a chain with one gap.
That is the same conclusion this doc reached about `augassign` from the other
end — a `sorry` is not a unit of missingness — and here it is a statement about
the *census*, not about the proof: the holes are countable by NAME in the
generated file, and nothing in the report counts them.

**Still open, unchanged by this pass:** the ten loop examples, `group3:idiv`, and
the value theorem's 12 open. The one entry this pass does close is the
"returns into a caller" row of the table, and the separation fact behind the
admitted `hpop` is written down exactly, with its measurement, in
`bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`.

## Status (2026-10-03 (b) — B28: the applicability check that was itself vacuous, and B29: a successor check that had never existed)

Two more of the same kind, and the first is the worst instance of the class in
this file, because it is the check that exists to catch a vacuous lemma.

**B28. `formal/x86_64_model_coverage_test.py`'s step-lemma applicability check
reported green no matter what Lean said.** `lemma_check_failures` compared the
diagnostic's file against the bare string `"StepLemmas.lean"`, but `run_lean` is
handed an ABSOLUTE scratch path and Lean prints the path it was given — so no
diagnostic was ever attributed to a check. Measured, by planting both kinds of
falsehood this file exists to catch:

    x86_rex_w 0x40 = true (a false hypothesis)      ->  "every hypothesis
                                                         satisfiable", exit 0
    the movq successor with the ModRM halves swapped  ->  the same, exit 0

It now matches on the basename, and reports by name:

    movq xmm, R12  hypothesis 10 `(220 : UInt8).toNat >>> 6 = 3` does not hold
                    at 66 49 0f 6e dc — the lemma is vacuous there

So B1's failure mode — a lemma that proves its goal about nothing — was being
checked for, by a check that could not fail. That is the doc's own sentence
about a check being worse than no check, and it was true of the guard rather
than of the thing the guard guards. The fix immediately found a real defect in
the row B29 adds: its `h_mod` hypothesis was written `"%d.toNat >>> 6 = 3"`, and
`_rex_mod3_hyps`'s docstring already explains that Lean reads a bare `192.toNat`
as a malformed decimal and `(192).toNat` elaborates 192 as a `Nat` with no
`toNat` field — so the row was an elaboration ERROR, i.e. a check that did not
run.

**B29. The applicability rows say nothing about a SUCCESSOR, and a successor is
a second copy of the model.** `cqo`'s `_SUCCS` row named `x86_sign_extend32`
while the model's arm computes `x86_cqo`, which left every hypothesis
satisfiable — B1's green — and made every `cqo` step a proof of a different
instruction. That is the argument B2 makes about a form NAME, one level down,
and it had no check at all.

`SUCCESSOR_FORMS` therefore reads the encoding off the ENCODER and the successor
out of `_resolve`, and `native_decide` checks the two agree on `rip` and on the
one field the instruction writes. Records go through a PROBE rather than being
compared whole, because `Decidable` is not synthesizable for equality on two of
them (`mem : Nat -> UInt8`) — an attempt that reports "failed to synthesize
Decidable" is an error that says nothing about the successor, which is the same
trap B23's fourth point is about. `RDI` is the `movq` source on purpose:
`X86State.init 10` puts 10 in RDI and 0 elsewhere, so the value is non-zero and
swapping the two halves of the ModRM shows up. Both mutants measured caught.

**B28 and B29 are the same lesson as B1 and B21, from the guard's side rather
than the lemma's: a check is a claim about the world, and a claim needs its own
check.** The census that proves it can fail is B28's fix measured by planting a
falsehood; the argument for B29 existing at all is B2's.

**Also closed alongside, from the same pass, and each measured in its own
commit:**

* `movq xmm, r64` — the GPR-to-SSE move, the first instruction this project
  emits into a formal x86-64 image that crosses register FILES, which neither
  `formal/x86_64_decode.py` nor `lib/X86.lean` knew. `X86State` gains
  `xmm0`..`xmm7`, one `UInt64` each; `x86_step_op66` is a new decoder because
  `0x66` is not a REX byte; and the step lemma quotes the model's own
  expressions, which is B3's rule reached from B10's direction.
* `formal/x86_64_endtoend_test.py`'s verdict counted Lean's per-DECLARATION
  `sorry` lines, so `wide_recv`'s five admitted holes read `proved, 1 sorry`.
  They are now counted by name, in two classes, off the generated text.

**What this pass does NOT do, and it is the same list as above:** the ten loop
examples, `group3:idiv`, the value theorem's 12 open, and the `hpop` separation.
The last has a number now — 5 admitted facts on `wide_recv`, 4 `hpop` and 1
`hrip` — which the report prints and which is the number the separation work has
to move. The stack/frame tracker the separation needs is specified in
`bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`; it is not
landed.

**NOT RE-MEASURED.** The 45-example sweep was not re-run — it is a heavy run and
this pass is a light one — so every number in the 2026-10-02 and 2026-10-03
tables stands as written. What *was* measured, one program at a time, is in the
commits: `formal/x86_64_model_test.py` 48 agree / 0 WRONG / 0 NO-RUN, the
coverage test at 151 samples over 57 forms with 23 lemmas at 50 encodings, and
`wide_recv` at `proved, 5 admitted, 112 guarded`.

## Status (2026-10-02 — B24 closed; the last `terminates` sorry was a FALSE theorem, not missingness)

| | 2026-09-26 | 2026-10-01 | 2026-10-02 |
|---|---|---|---|
| `formal/x86_64_model_test.py` — model vs hardware | 43/43 agree | 44 agree, 1 WRONG (`udivmod`) | **45 agree, 0 WRONG** |
| `formal/x86_64_model_coverage_test.py` | 151 samples over 57 forms, all steppable | 151/57, plus step-lemma APPLICABILITY at 17 lemmas x 38 real encodings, 354 hypotheses | 151/57, applicability at **22 lemmas x 48 real encodings, 482 hypotheses** |
| `formal/x86_64_endtoend_test.py` — terminates, no sorry | **10** | **31** | **32** |
| `formal/x86_64_endtoend_test.py` — terminates, a sorry | 14 | **2** | **0** |
| no finite path tree | 19 (4 loop, 15 uncovered form) | **12** (10 loop, 2 not) | **13** (10 loop, 2 uncovered form, **1 returns into a caller**) |
| value theorem — proved / open | 3 / 0 | 3 proved, 12 open | 3 proved, 12 open |
| failing | 0 | **0** | **0** |

**B24. A form name covering every SIB load, wired to one register pair.** Fixed
2026-10-02, `work/formal8-14`. `augassign` off the `sorry` list, and the proof
count 31 → 32.

`mov_r64_rm64_sib` is what `_shapes` calls *every* no-displacement SIB memory
load, and `_FORMS` wired it to `x86_step_mov_rax_sib_rsp`, whose statement pins
the REX byte to `0x48` and writes the destination as the literal field `rax`.
The lemma's docstring defended that with a true statement about the wrong thing:
"every SIB operand the backend emits has this shape". That is the SIB **byte**.
It is false of the instruction — `formal/x86_64_codegen.py`'s
`_pop_slot(Reg.R11)` emits `4c 8b 1c 24`, a `mov r11, [rsp]`.

So this is **B2's mechanism at the level of a whole addressing mode**, and it
failed in the one way B1 says is the worst available: not silently, and not as a
proof failure either. The step lemma was applied by form name, its two byte
hypotheses (`code m = 0x48`, `code (m + 2) = 0x04`) were **false** at that
encoding, and the per-step side-condition guard — `try (…) <;> all_goals sorry`,
the same guard B23 describes — **admitted** them. Five such instructions exist in
the 45-example corpus (`augassign`, `subscript_var`, `sum_range`), and
`augassign` reported `terminates: proved, 1 sorry` about a chain containing a
step that is not the instruction the machine runs. `failing` was 0 throughout:
an inapplicable step is admitted, not reported.

Both no-displacement SIB lemmas are now general over the REX byte and over the
register the instruction names, which is exactly the treatment the two `disp`
siblings already had (`x86_step_mov_mem_sib_disp8` / `_disp32` take `rex` as an
argument; only the no-displacement pair pinned it, and only the load's pinned
destination). The load's destination is the concrete `dst` with
`reg + x86_rex_r rex = dst` beside it, for B10's reason — `x86_set_reg` is a
`match` on its index and `simp` will not reduce one on a non-literal. The store
lost its `h_rr : x86_rex_r 0x48 = 0` hypothesis entirely, which was a statement
that the source register is in r0–r7.

**And the check that would have said so was not run, because both lemmas had no
row in `formal/x86_64_model_coverage_test.py`.** That file's whole subject is
"a step lemma is covered only when a REAL ENCODING satisfies every one of its
hypotheses, checked by `native_decide` on each" — and the two forms the backend
emits most often (95 `mov [rsp], rax` and 90 `mov rax, [rsp]` in this corpus)
were absent from it. Five rows are now there, three for the load at rax / r11 /
r15 and two for the store at rax / r12, so both REX.R settings and the top of
the register file are covered. Measured, the check has teeth: pointed at the
same `4c 8b 1c 24` encoding with the old pinned `dst`, it reports
``hypothesis 10 `3 + x86_rex_r 76 = 0` does not hold at 4c 8b 1c 24 — the lemma
is vacuous there``.

The general lesson, and it is B2's own: **a form NAME is a promise about every
encoding that reaches it**, so the applicability check has to be keyed on the
generator's form names and not on a hand-written list of lemmas. A lemma with
no row is a lemma nobody is asking about.

**B25. The `sorry` that was left was a theorem that is not TRUE.** Same commit.

The last `terminates` sorry was `wide_recv`, and the entry below describes its
residual goal as a memory-separation problem: "`b` is not a literal, `a + 8 <= b`
has no `decide` to give it". That is what the goal LOOKS like. What it is, is a
false statement.

`wide_recv`'s path contains a `call` — it is the only example in the corpus that
has one — and the path tree made every `ret` the end of the run. So the chain
stopped at the CALLEE's return and the closing fact was

```lean
have hrip : s40.rip = 0
```

while the model's own `ret` successor is
`rip := (mem_read_bytes s39.mem (s39.rsp.toNat) 8).toNat`, and the word in that
slot is the return address the `call` at 4294967946 pushed:
`UInt64.ofNat (4294967946 + 5)` = **4294967951**. So `hrip` claims 0 and the
machine says 4294967951, the theorem is unprovable at any cost, and the reason
it reports `proved, 1 sorry` rather than `FAIL` is that the `sorry` sits inside
the closing fact's guard.

Two consequences, and the second is the lesson:

* **A `sorry` is not a unit of missingness.** This one was covering for a claim
  that was wrong. Closing it required changing the TREE, not the proof.
* **The same defect is the whole of `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`.**
  That doc measured a 24-argument call timing out at `whnf` and concluded the
  closing `simp` does not scale. The 24-argument program's chain ends in the same
  false `hrip` — its `call` at 4294968254 pushes 4294968259 — so its timeout is
  `simp` grinding at a goal that cannot be closed, and neither raising the
  heartbeat budget nor splitting the `simp` can help. See that doc.

`ret` with a frame to return to is now its own reported outcome, so the case
says why instead of proving something untrue. The `sorry` count going 1 → 0 is
therefore **not** a proof getting stronger: `wide_recv` moved from the proved
column to the "no tree" column, where it belongs, and
`FORMAL_x86_64_endto_end_proof`'s "STILL OPEN" note on `wide_recv` is
superseded — what remains there is the return-following, not a separation lemma
parameterised over a symbolic address (though that is still needed once the tree
follows the return).

Everything below is the 2026-10-01 state and is left as written.

One row above is not this pass's doing and is worth saying so: `udivmod` used to
be the corpus's one WRONG (`real=4 model=7905747460161236410`, blamed on an
untyped-`n` collapse in `“`formal/`: `DEFAULT_INT_TYPE` became signed `Int`”` and
`bugs/FORMAL_pointer_value_model.md`, both other workers' claims). Re-measured
here for the table and it now answers `ok: 4`, so the suite reads 45/45 agree
and 0 WRONG. Nothing in this branch touches the model — the two `X86.lean` edits
are `theorem`s and add no `def` — so this was fixed elsewhere between the
recording and today. **Whoever owns those two docs should re-measure and delete
them if the model is right;** that was not investigated here.

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

## Status (2026-10-01 — the uncovered-form work is done; B1–B23 recorded below)

| | 2026-09-26 | 2026-10-01 |
|---|---|---|
| `formal/x86_64_model_test.py` — model vs hardware | 43/43 agree | **44 agree, 1 WRONG** (`udivmod`, see below) |
| `formal/x86_64_model_coverage_test.py` | 151 samples over 57 forms, all steppable | 151/57, plus **step-lemma APPLICABILITY** at 17 lemmas x 38 real encodings, 354 hypotheses |
| `formal/x86_64_endtoend_test.py` — terminates, no sorry | **10** | **31** |
| `formal/x86_64_endtoend_test.py` — terminates, a sorry | 14 | **2** |
| no finite path tree | 19 (4 loop, 15 uncovered form) | **12** (10 loop, 2 not) |
| value theorem — every input, `rax` a fixed constant | 3 proved | 3 proved, 12 open (reported by reason) |
| failing | 0 | **0** |

The shape of the change is **two bottlenecks, in the order they appeared.**
Fifteen forms were wired, which is most of the coverage work, and that exposed
the second one: B18's memory separation was NOT a research problem. One word —
`repeat` in front of the `rw` that peels a write out of a read's chain — took
`terminates proved with no sorry` from 15 to 31 and the `sorry` count from 25 to
2. See the entry below; the doc's own claim that the inequality "is not closed"
was wrong, and wrong in the same way as most claims in this file that were never
run.

What is left is 10 loops, 2 examples whose tree leaves the function, and 2
sorries. See **Open, in the order I would take them** below for all of them.

The one thing this pass did NOT touch is the model itself — `lib/X86.lean` gains
17 theorems and changes no `def`, which is what `git diff master...HEAD -- lib/
X86.lean` shows and it is worth checking rather than asserting. The one WRONG in
`x86_64_model_test.py` is `udivmod` (`real=4 model=7905747460161236410`), it is
**pre-existing**, and it is already written down twice: see
`“`formal/`: `DEFAULT_INT_TYPE` became signed `Int`”` ("very likely the same
untyped-`n` / `int` collapse") and `bugs/FORMAL_pointer_value_model.md`. Both are
other workers' claims, so it is neither fixed nor re-filed here. What it does
mean is that this doc's older "43/43 agree, 0 wrong" line was counting a
different corpus, and that `udivmod`'s end-to-end proof — the one example left
with an uncovered form — is the same example whose model is wrong, which is worth
knowing before spending effort on `group3:idiv`.

Two theorems of very different strength, and the gap between them is the whole
story of B21. The value theorem is the stronger statement but can only be
*formulated* for the examples whose result does not depend on their input, so it
proves for 3. The termination theorem makes no claim about the value and covers
33 — and `identity` is the example that shows why it is the one to chase: it
returns its argument, so the value theorem can never say anything about it, and
here it is proved.

The sorries are not free. Each is a real step lemma or a memory-separation
inequality Lean declined, and Lean reports them per file, so the gap stays
countable instead of becoming either a build failure or a silent omission.

One piece of infrastructure added since, and it is the thing B1 asks for: a step
lemma is now covered only when a REAL ENCODING satisfies every one of its
hypotheses, checked by `native_decide` on each. "The file builds" is the signal
that could not see `x86_step_setcc_r8`'s contradictory hypotheses, and it cannot
see them — a lemma that cannot be applied is not a lemma that failed.

Commits, oldest first: `f6046f3` (the model), `cc7e67b` (prologue lemmas),
`1b2bdb9` (memory separation + per-instruction certificates), `4d6f3ca` (the
first end-to-end proof), `438cb68`/`471782d`/`f918072`/`9bda629` (generalising
the step lemmas), `f9830d4` (the vacuous lemma), `1b35d73` (the termination
theorem), `3f2cb34` (the `rbp+disp8` load), `694433c` (`imul` + admitted side
conditions); then `work/formal3-10` for the fifteen forms and the applicability
check, whose commits are listed in their own messages.

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

Re-measured 2026-10-01 by running `formal/x86_64_endtoend_test.py` over all
45 examples after wiring the forms below. The doc's own numbers said
`terminates proved with no sorry` **10** and **19** without a tree; the current
numbers are **15** and **5**.

| | 2026-09-26 | 2026-10-01 |
|---|---|---|
| value — proved, no sorry | 3 | **3** |
| value — open | 0 | **12** (9 of them now *stated and reported*, see below) |
| terminates — proved, no sorry | 10 | **15** |
| terminates — proved, a sorry | 14 | 25 |
| no finite tree | 19 (4 loop, 15 uncovered form) | **5** (4 loop, **1** uncovered form) |
| failing | 0 | **0** |

**~~`call_rel32` (7 examples) — the last big uncovered form.~~ CLOSED, and the
fault was not where the risk was.** The entry below used to say the wiring was
"NOT VERIFIED" and name the open risk as being at the continuation past the
target. Running it found three faults, none of them there:

1. `takes_imm` was `True`, so `_resolve` appended the decoded displacement
   after the `off` its own branch had already supplied — two arguments where
   `x86_step_call_rel32` takes one, because `off` **is** the immediate. The
   error was `numerals are data in Lean, but the expected type is a
   proposition` **on the displacement**, reported at the instruction after the
   call.
2. A backward `call` has a negative displacement, and Lean's application is
   left-associative: `… s rc m -158 (by …)` is `(… m - (158 (by …)))`. The
   error is `Function expected at 158`. Same latent trap in `jmp_rel32` and
   `jcc_rel32`, unreachable there only because a backward branch is a loop.
3. The successor carried its two addresses as pre-computed literals where the
   lemma carries `(Int.ofNat m + 5 + off).toNat` and `UInt64.ofNat (m + 5)`.
   That is the same record up to two fields, so closing the step is an
   `isDefEq` over a 22-field structure whose `mem` is a `Nat → UInt8`, and the
   congruence check gives up: `Type mismatch`, both sides printed, neither
   naming the field. **Quoting the model's expressions makes the two records
   syntactically identical**, so the step closes by `rfl`.

This is B2's mechanism one level up, and the generalisation of B12: a successor
table must quote the model's expression, and a literal is only safe where the
conversion it needs is one field's worth.

**The remaining uncovered forms: one.** After the forms below, `group3:idiv` is
the only name left, and it is not a wiring job. See its own entry.

**The forms wired since the last pass**, and the trap each one carried:

| form | examples unblocked | the thing that was easy to get wrong |
|---|---|---|
| `movsx_r64_r8` | n8, sgt8, sle8 | general over both registers because the corpus emits TWO shapes for it and ONE for `movzx` — so the same table has a concrete lemma for one and a general one for the other |
| `alu_rr:and/or/xor` | bitops | one model arm for all three, with the operation selected out of an `if` chain on the opcode, so three theorems over a literal opcode and not one over the chain |
| `shift_imm8:shl/shr/sar` | shiftlr (+ subscript_var) | the count's clamp to 64 IS the semantics, so there is no `n < 64` to discharge; and `sar` is the `else` arm, not a third `if` |
| `alu_ri32:add_reg`, `alu_ri32:and`, `alu_ri8:cmp` | ug8 (+ sum_range, subscript_var) | `81` and `83` differ in LENGTH as well as width; and `cmp` writes no register at all |
| `mov_*_nodisp`, `mov_*_disp8` (base-register), `mov_*_disp32`, `lea …_disp32` | wide_recv, subscript_var | `_shapes` named only two of the three addressing modes, so `mov [rbp-0x410], rax` was reachable under the name of `mov [rbp+disp8], rax`. **Every mode now has its own name**, and an unmapped one is reported |
| `cqo` | — (one half of udivmod's pair) | the model changed under the lemma and the lemma did not: `da151f0c` made `x86_cqo` the 64-bit extension where it had been `cdq`, and `x86_step_cqo` still stated `x86_sign_extend32` — so the theorem contradicted the definition it was about and **the library stopped elaborating**. See `FORMAL_x86_64_cqo_step_lemma_contradicts_the_model`, deleted with its fix (`2eb418c5`, `60300077`) |
| `movq_xmm_rm64` | — (only a floating `printf`, which the corpus has none of) | the first instruction crossing register FILES, so a successor with no register in it: `X86State` had no XMM file, and the alternative to adding eight `UInt64`s was a step that decoded the instruction and recorded no effect — a FALSE step, which is B2 at the level of a whole register file |

Two of those six were found by the coverage getting better rather than by
reading: `alu_ri32:add_other` was reported for `sum_range`, and `sum_range`'s
only remaining blocker is its LOOP, which no lemma reaches.

**The last two rows were added 2026-10-03, and the `cqo` one is here because
this table was part of why the cqo incident took as long as it did.** A row
reading "wired" under a column headed "the trap each one carried" looked like
"wired and proved", and it was neither for a while: `x86_step_cqo` stated a
DIFFERENT INSTRUCTION from the one `x86_step` decodes, so the library did not
elaborate and every Lean-checking build failed — while this file, the coverage
rows and the applicability rows were all green. The two rows now say what each
form's trap actually was, because the trap is the part worth carrying forward and
the row with a `—` in the trap column is a row that reads as done.

**`group3:idiv` — the one form left, and why a lemma is not enough.**
`x86_idiv128` returns `none` when the divisor is zero, so the model's arm is
`match x86_idiv128 (x86_signed s.rdx) (x86_signed s.rax) (x86_signed a) with |
some (q, rem) => … | none => none` and the STEP IS PARTIAL. That is the honest
model of an instruction that faults, and it is why `group3:div` was already
skipped ("the step is not total"). What the doc did not say is why no lemma
shape can be chained:

* naming `q` and `rem` in the successor needs a hypothesis
  `x86_idiv128 … = some (q, rem)`, and the generator cannot discharge it —
  `s` is symbolic, so the quotient of two symbolic 128-bit values is not
  something `decide`, `simp` or `omega` produces. It would be admitted, and
  with it every later `rip` in the chain.
* keeping the `match` in the successor IS total and provable, but then the
  successor's `rip` is behind a `match` on the divisor and **the next step's
  address does not reduce** — so every subsequent step's `rip` side condition
  goes to `sorry` and the theorem stops saying anything.

Next step, in order of cost: **a `#eval`-free lemma that the divisor is not
zero.** It cannot come from the compiler — nothing in the encoding says the
value is nonzero — so it has to come from the PROGRAM, which means the theorem
has to be about a function that has already established `r11 ≠ 0`. `udivmod`
does establish it; the end-to-end chain has no way to carry that fact, because
`X86State` has no precondition slot and the generator's state variables are
successor records. **The concrete next step is therefore in the generator, not
in `X86.lean`: an `assume` of side conditions between steps.** `_resolve`
already has a guarded side-condition channel per step (`try … <;> all_goals
sorry`), and `h_idiv` is what should go there — as a fact the generator states
from the SOURCE (`udivmod` compares `r11` against zero immediately before the
`idiv`), which is a dataflow question the method does not currently answer.
Until that exists, `udivmod` has one uncovered form and the other 44 examples
are covered.

**B18 WAS WRONG, and the fix is one word.** The entry above says the
memory-separation inequalities "are not closed", that `decide` reports `Expected
type must not contain free variables` "which names the tactic rather than the
inequality that would have closed it", and that this is "the sole reason 14
termination proofs carry a sorry". The inequality was always closedable and the
tactic was always the right one; the emitted proof applied it **once**:

```lean
try (rw [key _ _ _ _ (by first | decide | omega)]) <;>
```

`rw` rewrites ONE occurrence. The goal is a `mem_write_bytes` chain N deep, and
peeling the outermost write exposes the next one — so `rw` fired once, the rest
of the chain survived, and `all_goals sorry` admitted the remainder. That is the
whole bug, and it was invisible for the reason B21 describes: the report said
"proved, 1 sorry", which is a gap, and the gap looked like a limitation.

```lean
try (repeat rw [key _ _ _ _ (by first | decide | omega)]) <;>
```

Every peel's side condition is `a + 8 <= b` over CLOSED literals — the frame is
allocated at a literal offset and the closing read is at the exit sentinel — so
`decide` closes each one and `repeat` runs until there is no write left. **The
depth of the chain does not matter and never did.** Measured, same 45 examples,
same chain, same lemmas: **15 -> 31 proved with no sorry, 25 -> 2 with a sorry.**

The lesson is the file's own, arriving from a new direction: **`simp only
[key]` does not work and `repeat rw [key]` does.** A conditional rewrite whose
side condition `simp` has to discharge by `Decidable` made *no progress at all*
on these goals, while `rw` with an explicit `by decide` peels every layer. The
two look equivalent and are not.

**The 2 remaining sorries, and they are different problems.** *(written
2026-10-01, before B24; `augassign` is closed — see the Status at the top — so
there is 1 left.)*

* `wide_recv` — the residual goal contains a `mem_read_bytes` whose ADDRESS is
  itself a `mem_read_bytes`: `mem_read_bytes (… .toNat) 8`, where the inner read
  loaded a pointer out of the frame. So `b` is not a literal, `a + 8 <= b` has no
  `decide` to give it, and no amount of repeating helps. This is the real form of
  B18, and closing it needs the separation lemma parameterised over a symbolic
  address with the inner read's own separation supplied — a two-level statement,
  not a repeat count.
  **SUPERSEDED as a diagnosis (B25).** The goal's shape is as described and its
  cause is not: `wide_recv`'s path contains a `call`, the tree stopped at the
  callee's `ret`, and the closing fact was `s40.rip = 0` where the machine pops
  4294967951. Nothing about a two-level separation statement will close a goal
  that is false. The symbol**ic**-address separation is still real work — it is
what the step after a `ret` needs once the tree follows the return — but it is
   not what was wrong here.
   **AND B26 (2026-10-03) has now built the tree that follows the return**, so
   that "once the tree follows the return" is the present tense: `wide_recv`
   reports `terminates: proved, 1 sorry`, and the separation this entry describes
   is the admitted `hpop{k}` — whose goal is exactly the two-level statement above
   and whose proof is measured at >1500 s of wall while the read address is
   symbolic. The address has to be computed for it to close, which is the
   remaining work and is written down in the companion doc.
* `augassign` — a single admitted SIDE CONDITION on a `mov rax, [rsp]` step (the
  SIB form), not a `hrip`. `simp [read_i32_le, read_i8, hb]` reports `False`, so
  one of that instruction's byte facts is not in `all_bytes`. Worth ten minutes:
  it is the only remaining case where the report cannot say which of the two
  kinds of sorry this is.
  **CLOSED as B24, and the entry's own diagnosis was wrong in an instructive
  way.** The byte fact was in `all_bytes`; the instruction was simply not the one
  the lemma describes. Read `simp …` reporting `False` as "a byte fact is
  missing" and the next question is always "which instruction is this lemma
  actually about" — a missing fact and a mismatched one fail identically here,
  and only one of them is a missing hypothesis. Measured: three
  `x86_step_mov_rm64_sib_rsp` steps in `augassign`, each with two false
  hypotheses (`code m = 0x48` against `0x4c`, `code (m + 2) = 0x04` against
  `0x1c`), and the report said `proved, 1 sorry` — which is B21's failure with a
  new coat of paint, since a step that is not the one the machine runs is a
  *wrong proof* and not a missing one.

**The 10 loop examples** — `countdown`, `sum_range`, `wdiff`, `wge`, and the six
RECURSIVE ones (`count`, `fact`, `fib`, `pow2`, `sqsum`, `sum`). The chain walks
one straight line, so a back edge has no finite unfolding; these need induction
over it. A limit of the method as built, not a proof failure.

The six recursive ones are in this list because of a second bug, and the way it
presented is worth recording. The path tree treated `call rel32` as a
**fall-through** rather than a jump, so after a call it stepped the instruction
at `m + 5` — which the model's own successor says is never executed, because the
call's `rip` is `m + 5 + off`. That step's `rip` side condition was therefore
false, `simp` turned it into `False`, the guard admitted it, and **six examples
reported `terminates: proved, 1 sorry` while proving a chain that walks code the
machine does not run.** `failing` was 0 throughout. Following the target fixes
the tree and moves all six to `loops`, where they belong; `_has_loop` had to
learn that a recursive call is a back edge too, or they read `no tree: body
loops, or branches out of the function`, which names two different reasons.

This is B22 again — one wrong thing conceals the state of everything after it —
and it is worth contrasting with B22's own case, because here the concealment ran
the other way. B22: a MISSING lemma hides a side condition. This: a CORRECT lemma
hides a wrong tree. A green file with a `sorry` in it is the signature of both,
and neither one shows up as a failure.

**The value theorem's 12 open**, and why it went UP from 0: eleven of them are
examples whose result **is** input-independent and whose proof could not be
finished, and they used to be reported under a form name instead. The honest
outcomes are now separated (`BRANCHING`, `loops`, `depends on the input`,
`no lemma`, `proved with a sorry`, `FAIL`), which is B21's fix arriving one
theorem late: until every form had a lemma, none of these distinctions could be
told apart.

**The generalisation rule this file keeps relearning**, worth stating once:
generalise a form when the backend actually emits more than one shape of it, and
not otherwise. `movzx r64, r8` is emitted as the identical `48 0f b6 c0` in all
33 instances, so the concrete `x86_step_movzx_rax_al` already in `X86.lean`
covers them and a register- and nibble-parameterised version would be machinery
nothing calls. Conversely every form that *was* pinned to one register pair
turned out to need generalising (B7), so the rule is a heuristic, not a proof.
The pair of rows for `movzx` and `movsx` are the rule applied in both directions
in one place, which is the clearest statement of it this file has.

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
immediately. The number to watch is **terminates proved with no sorry** (32 as
of 2026-10-02, 31 before B24) — a change that pushes it down has taken a real
proof away even
if the file still builds, which is precisely the failure mode B1 and B11 had and
B21 now makes visible. The second number to watch is **`failing`, which must be
0**: every form added since has first shown up as a failure at some later step
(`call_rel32` twice, `$imm` once, the value theorem's unguarded closing facts
once), and a report that says `FAIL` at a step far from the cause is the one
thing this generator is bad at.

**And the third is a `sorry` that was counting a WRONG PROOF.** `augassign`'s
one remaining `sorry` was not missingness at all: it was an inapplicable step
the guard admitted, so the "proof" included a step that was not the instruction
the machine runs. Generalising the lemma is what took it off the list — the
count did not go down because something was proved that was not, it went down
because something false stopped being counted as proved. A `sorry` is therefore
not a uniform unit of missingness, and the count is a bound and nothing more.
B24 is the shape to look for when the count will not move: take the generated
file, replace `all_goals sorry` with `all_goals trace_state`, and read the goal.
It is `⊢ False`, and the question is never "which byte fact is missing" but
"which instruction is this lemma about".

**And B25 is the other shape, one level further out.** `wide_recv`'s `sorry` was
not in a side condition at all — it was in the final `hrip`, and the goal there
was `⊢ (mem_read_bytes …) = 0`, not `⊢ False`. A `False` goal at least tells you
something contradicted; this one just sat there being unprovable, and the reading
was "the separation is hard". It was `s_N.rip = 0` where the machine pops the
address after a `call`. So there are two questions to ask of a `sorry`, in this
order: **is the goal `False` (a side condition that does not hold) or is it a
positive claim that is not true (a theorem that cannot be proved)?** The first is
B1/B24 territory. The second means the TREE is wrong, and no amount of lemma
work reaches it — `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`
is the same defect in a program too long to read by hand.

**And there is a third shape, which B26/B27 found: the goal is TRUE, the
attempt is unaffordable, and the report calls it a FAILURE.** That is what the
24-argument program was — `simp [read_i32_le, read_i8, hb]` exhausting
`maxHeartbeats` on step 19's byte fact, which killed the file rather than
admitting it, so twenty minutes of Lean produced "FAIL" and nothing else. So the
third question, after "is it `False`" and "is it true", is **can this attempt be
paid for at all**, and the answer has to be structural rather than a budget:
B27's answer is that a fact over `rc` at a literal address is computable and
never needed the simplifier at all, and B26's is that a chain which crossed a
frame takes the cheap route at its closing read rather than the affordable-looking
one. A bound is the instrument; a heartbeat timeout is not catchable, so anything
relying on the guard needs the goal to be small enough that the guard is reached.

If you are adding a form: the four places that must agree are `_FORMS` (lemma,
`takes_imm`, side conditions), `_SUCCS` (the successor shape), the branch in
`_resolve` (extra arguments and placeholder values), and **`_shapes`** — the
split that decides which NAME the instruction gets, which is now the one that
fails silently. A form wired into three and forgotten in the fourth does not
error at all; it is reachable under a name that belongs to a neighbouring
instruction, and that is B2. A form wired into two of three fails as a
`KeyError` at `_SUCCS[form]` or, worse, applies the wrong `$rm`/`$rex` defaults
(B19). `_resolve`, `_shapes` and `_header` are shared between the straight-line
and path-tree emitters precisely so a form cannot be wired into one and
forgotten in the other.

Two rules that cost the most time here and are worth not relearning:

  * **A successor quotes the MODEL'S expression, never a value computed from the
    encoding.** `movsx`'s is `x86_sign_extend8 (get &&& 0xFF)` and `cmp r64,
    imm8`'s names no register; a literal in either place is a statement about a
    different instruction. Where a literal IS unavoidable — the `jmp`/`jcc`
    successors, whose address must be a numeral for the next step — check that
    the conversion it needs is one field's worth, because it is not two (see the
    `call_rel32` entry above).
  * **A step's own closing facts are `try`-guarded and the `sorry` is counted.**
    `emit`'s and `emit_terminates`' `hrax`/`hrip` are the two places a function
    that spills its argument stops, and reporting them as FAILURES is B21's
    failure mode with a new coat of paint.

When a side condition will not close, add it to the `try … <;> all_goals sorry`
guard rather than working around it, and check afterwards that the no-sorry
count did not fall (B23).
