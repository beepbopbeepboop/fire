# the stack-floor guard's `exit(2)` call target is outside the image: the path tree now ends there, and the theorem is a disjunction over halt addresses

**Status: the path tree is FIXED (2026-10-04, `work/gatefix6`), the guard's
cost is MEASURED and PINNED, and the guard's own two branches are DECIDED
(2026-10-04, `work/formal22-guard-branches`), so `wide_recv` emits at last —
the section "what the guard still costs" is kept as the record of what the cost
was and where the measurement is.** The defect this doc filed — "no end-to-end
path tree exists", every example reporting `body loops, or branches out of the
function` — no longer happens, and the theorem that is emitted instead is one the
model can support.

## Status (2026-10-04 — the guard's two branches are DECIDED, and `wide_recv` emits)

**The doubling is gone, and the fix is the one this doc's "next step" named:
decide the guard's own two branches instead of walking both arms.** Both are
settled by arithmetic over the initial state, so walking them was work for an
answer already known.

* **`JNE done`** — has the floor word been parked already?  In the ENTRY function
  it reads 0, because `X86State.init`'s memory is a constant zero function.  In
  a CALLEE it is what the entry parked, which is non-zero **because
  `X86State.init`'s stack pointer is the LITERAL `0xfffffffffffffff0` and not a
  function of the input** — that is what makes the whole comparison arithmetic on
  Python integers rather than an obligation about `n`.
* **`JAE ok`** — SP on a path is a sum of literal frame movements, so
  `sp >= sp - BUDGET` is arithmetic on two literals.  Nothing about the two
  obligations below was needed: no new library lemma, no model change, and the
  wrapping `UInt64` comparison closes in `decide` like any other ground fact.

`_Abs` (in `formal/x86_64_endtoend_test.py`) is the constant propagation that
answers them, `_abs_cond` is `x86_cond`'s own `match` transcribed nibble for
nibble, and `_tree` asks it at every `jcc`: **a settled condition is followed
into ONE arm and the other is never built.**  A form the table does not model
wipes the state and a store whose ADDRESS is unknown drops the memory model, so a
gap in the analysis costs the old behaviour and nothing else — and **a decision
it gets wrong costs a rejected file, not a wrong theorem**, because every
decision is emitted as a `have hdec{k} : x86_cond … = …` whose proof has no
`sorry` in it anywhere.

**The proof is one step of unfolding, not a `simp` over the chain, and that part
was not obvious.**  `s{k}` is one nested term (`s1 = {i0 with …}, s2 = {s1 with
…}`), so the direct proof is a single `simp [hs1 … hs{k}]`, and it is
superlinear: measured on `wide_recv`, one such `simp` at step 41 cost seconds
and the same one at step 131 **was still running at `PROOF_WALL_S` (1500 s)**,
with `mem_write_bytes`'s `ite` chain and the nested `Int.ofNat … + disp`
addresses re-normalised at every one of the 131 levels.  So the values are stated
one step at a time instead — `hval{k}` is `s{k}`'s own field values, proved from
`hs{k}` and `hval{k-1}`, which is a projection reduction and some literal
arithmetic — and the decision then reads the last fact.  The whole chain costs
what one step costs times the number of steps.

| | before | after |
|---|---|---|
| `emit_terminates` over `formal/examples` | 38 of 50 emitted | **39 of 50** |
| corpus leaves / step equations | 218 / 6 315 | **69 / 2 718** |
| corpus emitted bytes | 4.31 MB | **3.02 MB** |
| `ret42` | 4 leaves, 58 steps | **1 leaf, 16 steps** |
| `bittest` | 10 leaves, 457 steps | **4 leaves, 220 steps** |
| `twoifs` | 10 leaves, 409 steps | **4 leaves, 196 steps** |
| `wide_recv` | **REFUSED, too large** (12 241 steps / 94 leaves / 29 908 lines) | **1 leaf, 150 steps, 4 013 lines** |

Lean, on the two files this doc's own "Reproducing" line names:
`ret42` **3.9 s**, `wide_recv` **161.6 s** — 1.6 % of `PROOF_WALL_S` — both with
no errors.  `wide_recv`'s five admissions are four `hpop`s and the closing
`hrip`, counted by name in the report and unchanged by this; the point of the
table is that the file now EXISTS to be measured at all.

**What the remaining leaves are, so the table is not read as "the guard is the
only branch".**  `twoifs`, `elif3`, `deepif` and `bittest` keep four, four, three
and four leaves, and every one of them is a branch on the program's INPUT —
nothing an emitter can settle, since the theorem is quantified over `n`.  The
guard's own two branches per guarded prologue are gone from all of them; what is
left is `2^(branches on the path)` over the program's own conditionals, which is
what a path tree is for.

**Still open, unchanged by this pass: the VALUE theorem.**  `emit()` has no path
structure at all — it walks straight-line from the entry and refuses on the first
`jcc` or `call` — so with two branches and a `call_rel32` in every prologue it
declines every example (`ret42` reports `value: - (branches: call_rel32,
jcc_rel32)`).  Fixing it is the same decide-the-guard work plus `by_cases` in an
emitter that has none, and it is NOT started.  The section below is the record
of the other half.


**ADDENDUM 2026-10-04 (`work/formal25-6`): the decision below IS ALREADY MADE —
on `work/formal22-guard-branches`, which is NOT merged.** That branch carries
two commits this doc's next step asks for, and a queue that reads only `master`
would re-derive a day of work:

* `55f45626` "formal: decide the stack-floor guard's two branches instead of
  walking both" — `_Abs` (constant propagation over the instruction forms), an
  `_abs_cond` that transcribes `x86_cond`'s own `match`, and `_tree` asking it
  at every `jcc`, so a settled condition is followed into ONE arm and the other
  is never built. Each decision is emitted as `have hdec{k} : x86_cond … = …`
  with NO `sorry` in it, so a decision the analysis gets wrong makes Lean reject
  the file rather than admit a claim. Measured, `emit_terminates` alone over
  `formal/examples` (Lean-free): emitted 38 → 39 of 50, leaves 218 → 69, step
  equations 6 315 → 2 718, emitted bytes 4.31 MB → 3.02 MB; `ret42` 4 leaves /
  58 steps → 1 leaf / 16 steps; `wide_recv` REFUSED-too-large → 1 leaf / 150
  steps. Lean, on the two files this doc's own Reproducing line names: `ret42`
  3.9 s, `wide_recv` 161.6 s, no errors, five admitted facts on `wide_recv` (four
  `hpop`s and the closing `hrip`).
* `8c338ced` updates this doc's Status with the same table, plus the emitter
  tidy-ups the measurement found (`_abs_step`'s REX detection is the high
  nibble, `lea`'s RIP-relative address uses the instruction's length, `cqo` is
  handled before the ModRM decode, and `_MAX_CHAIN_STEPS`'s table is labelled the
  BEFORE state).

**What is left for whoever picks this up, and it is smaller than the section
below says:** merge that branch (or rebase its two commits), then re-measure the
VALUE theorem, because the payoff the section predicts — "`emit()`'s coverage of
0 back to the 7 of 43 the guard cost" — is still open and the guard's `call_rel32`
is still in every prologue even with both its branches decided. The tripwire
`test_formal_sweep_truth.py::TestTheStackFloorGuardIsWhatGatesTheValueTheorem`
pins the three path counts and that `emit()` covers nothing, so merging the
branch should move the first three and leave the last alone; if it moves the
last one too, that is worth a measurement rather than a surprise.

## What landed

1. **`_tree`: a `call_rel32` whose target is not in the image is a LEAVE**, with
   the halt address the call's OWN address, and the walk stops there without
   stepping it. `info["compiler_traps"]` is not consulted for this — the test is
   "is the target an instruction the image has", which is what `by_addr` already
   answers, and which is the same test that makes an extern `printf` the same
   kind of leaf.
2. **`emit_terminates` states the theorem as a DISJUNCTION**, one disjunct per
   leaf of the tree, each naming that leaf's halt address: the exit sentinel `0`
   for the outermost `ret`, and the call's address for a leaf that leaves the
   image. Each arm picks its own with `right`×index and (except on the last)
   `left`; the index is on the node (`_Node.halt`), assigned by `_leaf_halts`,
   so the statement and the walk cannot read two different leaves as one.
3. **`_MAX_CHAIN_STEPS = 2000`**, refused as `_NoTree("size")` and counted as
   `too large to prove` in the reporter's own line — see "what the guard costs"
   below for why this is a refusal rather than a bigger number.

The reading of the model that decides (2) is the one this doc's "Next step" step
1 asked for, written down: `rc` is 0 outside the image, `x86_step_plain` has no
arm for the byte `0x00`, so `x86_step` returns `none`, so `x86_exec_go_exit`
returns `none` there (`x86_exec_go_exit_stuck`). **So a trap path does not reach
the exit sentinel and the old statement was FALSE for it** — it could not have
been fixed by walking that arm, only by changing what is claimed. The
`= none` disjunct is NOT the alternative: `Option.isSome = false` and `= none`
are the same statement, and fuel exhaustion ends a run with `none` too, so
`A ∨ = none` holds for every `Option` and says nothing. Only a NAMED halt
address carries information — and `x86_exec_go_exit` tests `st.rip = exit`
BEFORE it steps, which is what makes "the run reaches the call" a theorem rather
than a hope. This is the arm64 generator's own answer to the same question
(`formal/arm64_proof_gen.py::_call_boundary`'s "opaque" kind and
`_gen_universal_e2e_cfg`'s `exit_at`: *"the fix is not to admit the `none` branch
but to state the theorem the model CAN support, with the call as the halt
address"*), applied to every opaque call rather than to the first one.

### Measured, on this tree

Emission is Lean-free, so the whole corpus was measured with
`emit_terminates` alone. Steps = the sum of path lengths, which is what the
emitted file contains; leaves = the disjuncts.

| | before | after |
|---|---|---|
| `formal/examples/ret42.mojo` | `body loops, or branches out of the function` | 4 leaves, 58 steps, 397 lines, **`terminates: proved, 2 admitted (hrip), 26 guarded`** |
| `TestX86EndToEndEmitter.SOURCE` | same | 10 leaves, 1624 lines, **Lean accepts, 8 admitted**, 24 s |
| `TestX86EndToEndEmitter.STRAIGHT` | same | 4 leaves, 825 lines, **Lean accepts, 2 admitted**, 11 s |
| 50 examples in `formal/examples/` | **0** with a tree | **38** emit; 10 are recursive (`count`, `countdown`, `fact`, `fib`, `pow2`, `sqsum`, `sum`, `sum_range`, `wdiff`, `wge` — a backward call, refused as `loops` before and after); `udivmod` has no step lemma for `group3:idiv`; `wide_recv` is refused as too large |
| corpus emitted bytes | 0 | 4.3 MB over 38 files |

The two Lean runs above are the only Lean this branch ran, and they are the ones
that cover the change (`formal/x86_64_endtoend_test.py`'s own entry point is 43
Lean proofs and is not in a gate bucket).

## What the guard still costs, and the exact next step

**SUPERSEDED (2026-10-04) — kept as the record of the cost and of where the
measurement is. Both branches are decided now; the Status above has the fix and
the after-table.** Everything below describes the state this section was written
against, and the "exact next step" it ends with is the one that was taken.

**The guard's two branches per prologue are a per-path TREE, so they multiply.**
`_tree` walks every branch outcome and there is no way to share the two arms of
a fork whose arms converge (`JNE done` and `JAE ok` both land on the same `done`
/ `ok` label, through states that differ), so each guarded function on a path
doubles the number of paths through it:

| | leaves | steps | emitted |
|---|---|---|---|
| `ret42` (1 function) | 4 | 58 | 397 lines |
| `bittest` (1 call) | 10 | 457 | 2338 lines |
| `wide_recv` (5 functions) | 94 | 12241 | 29908 lines |

`wide_recv` is the corpus's one image whose tree is past what a proof can be:
attempting it spends `PROOF_WALL_S` (1500 s) and then reports a FAILURE whose
message is about the clock, which is B21's lesson from the other side — so it is
refused with its size in the line instead.

**The fix is not a bigger bound. It is to decide the guard's own two branches
instead of walking both arms**, and both are decidable from facts the emitter
can compute:

* **`JNE done`** (has the floor word been stored already?). In `main`'s guard
  the word reads 0 — `X86State.init`'s memory is zero, and
  `lib/X86.lean::x86_init_mem_reads_zero` says so — so the branch is NOT taken.
  In a CALLEE's guard the word is what `main`'s guard stored, so it IS taken.
  The library has both shapes it needs — `mem_read_bytes_write_above` (which
  the emitter already emits as `key`) and `mem_read_bytes_write_same`
  (`lib/X86.lean:2452`) — so the obligation is that read followed by `v ≠ 0` for
  a ground `v`, and whether the second half closes is a `decide` away and
  untried.
* **`JAE ok`** (is SP still above the floor?). The floor word is
  `SP_at_first_guard − model.STACK_FLOOR_BUDGET_BYTES`, and SP on a path is a sum
  of literal frame sizes (`push`, `sub rsp, imm32`, and the `call`'s own 8), so
  the emitter can keep a LOWER BOUND on the depth below the entry and conclude
  "not trapped" whenever that bound is inside the budget — 7.5 MiB against a
  measured worst case of 76 frames (1.2 MiB on x86-64,
  `tools/formal_call_depth_census.py`). This needs no model change; it needs the
  wrapping `UInt64` comparison to close, which `simp … <;> decide` should do on
  ground terms but has not been tried.

Both must be emitted as a PROOF, not as a dropped path: the surviving arm gets a
`have` that the discarded side's condition holds and the other arm closes with
`simp [that] at <the by_cases hypothesis>`. A decision the emitter gets wrong
then makes the file Lean-rejects, which is the property that makes the static
analysis safe to have — B21's "a pin nobody can run is not a pin" applies to the
analysis too.

**The VALUE theorem is a second, separate loss from the same guard, and it is
not fixed.** `emit()` (the constant-result theorem) has no path structure at
all — it walks straight-line from the entry and refuses on the first `jcc` or
`call` — so with two branches and a `call_rel32` in every prologue it declines
EVERY example: measured, `ret42` reports `value: - (branches: call_rel32,
jcc_rel32)`. Before the guard it covered 7 of 43. Fixing it is the same
decide-the-guard project plus `by_cases` in an emitter that has none; it is not
started.

## Status 2026-10-04 (earlier the same day, before the decision above): the guard is MEASURED and PINNED; the decision is not made

**SUPERSEDED (2026-10-04) by the Status section above, and kept whole as
the record of what the guard cost and of where the measurement is: the
"exact next step" this section ends with is the one that was taken, and the
tripwire it landed is still in place.** The numbers above were exact on the
tree this section was written against, and one of them is sharper than this doc
states it.** Re-measured, Lean-free, over `formal/examples/`:

| | this doc, 2026-10-03 | 2026-10-04 |
|---|---|---|
| `ret42` | 4 leaves, 58 steps | **4 leaves, 58 steps** |
| `bittest` | 10 leaves, 457 steps | **10 leaves, 457 steps** |
| `wide_recv` | 94 leaves, 12241 steps, refused as `size` | **94, 12241, refused as `size`** |
| `emit()` — the VALUE theorem | "declines EVERY example", "before the guard it covered 7 of 43" | **emitted 0, refused 49, plan-failed 1 — and every one of the 49 names `call_rel32`** |

**The sharp part: `emit()`'s coverage of 0 is gated on the `call_rel32`, not on
the `jcc_rel32`.** Every refusal names the guard's CALL, and a program with no
branch of its own (`ret42`, `seven`, `swapadd`) is declined for the compiler's
own guard rather than for anything it wrote. So the payoff of deciding the guard
is a NUMBER — `0` back to the 7 of 43 the guard cost — and not a proportion, and
it is `call_rel32` that has to go first.

### What landed, and what it is for

`test_formal_sweep_truth.py::TestTheStackFloorGuardIsWhatGatesTheValueTheorem`,
beside the class that already checks this emitter's text. Lean-free by
construction (`_plan` and `_tree` are text), 0.96 s, on every run:

* the three path counts, with the failure message naming BOTH ways the number can
  move — a third guard branch, or a function added — and what crossing
  `_MAX_CHAIN_STEPS` does to the example;
* `wide_recv`'s refusal is `size` and its sentence names the CAUSE;
* **`emit()` covers nothing and every refusal names `call_rel32`** — the
  tripwire, whose failure message says which of the two things happened (the
  guard left the prologue, or its branches were DECIDED), because those are the
  only two ways this number can change. The other direction is pinned too: a
  refusal that does NOT name `call_rel32` means some example is now gated on a
  branch the PROGRAM wrote, which is a different subject;
* the corpus itself, so the row cannot pass by `formal/examples/` emptying out.

Before this, nothing noticed when any of it moved, and `emit()` refusing every
example reads exactly like a corpus no straight-line theorem is possible for —
which is a different claim and a wrong one.

### What is NOT attempted here, and the reason

Deciding `JNE done` and `JAE ok` means emitting a `have` that the surviving arm
closes with `simp [that] at <the by_cases hypothesis>`, and **whether those
obligations close is a Lean question.** This doc's own instrument for it is

```console
$ python3 formal/x86_64_endtoend_test.py formal/examples/ret42.mojo formal/examples/wide_recv.mojo
```

which is 43 Lean proofs and is not in a gate bucket. Landing the decision without
running it is exactly the "a pin nobody can run is not a pin" failure this project
already has a rule about, so what landed here is the measurement and the tripwire
and the next step below is unchanged.

### The exact next step, restated with today's numbers

1. **`JNE done` first, and it is the cheaper of the two.** In `main`'s guard the
   floor word reads 0 (`X86State.init`'s memory is zero, and
   `lib/X86.lean::x86_init_mem_reads_zero` says so), so the branch is NOT taken;
   in a CALLEE's it IS. The library has both shapes — `mem_read_bytes_write_above`
   (already emitted as `key`) and `mem_read_bytes_write_same`
   (`lib/X86.lean:2452`) — so the obligation is that read followed by `v ≠ 0`
   for a ground `v`. `wide_recv` is 4 of its 94 leaves in callee guards, so this
   half alone is a 2x.
2. **`JAE ok` second, and it needs no model change.** The floor word is
   `SP_at_first_guard − model.STACK_FLOOR_BUDGET_BYTES`, and SP on a path is a sum
   of literal frame sizes (`push`, `sub rsp, imm32`, and the `call`'s own 8), so
   the emitter can keep a LOWER BOUND on the depth below the entry and conclude
   "not trapped" whenever it is inside the budget. 7.5 MiB against a measured
   worst case of 76 frames (1.2 MiB on x86-64,
   `tools/formal_call_depth_census.py`). Whether the wrapping `UInt64` comparison
   closes is a `simp … <;> decide` away and has still not been tried.
3. **Measure after each, with `emit_terminates` alone** — leaves and steps are
   the numbers the tripwire pins, so a decision that does not halve them has not
   worked, and that is visible without a proof.

## Reproducing

    python3 tools/memslot.py --gb 8 --label fst -- python3 test_formal_sweep_truth.py
    python3 test_formal_x86_64_call_tree.py            # the `_tree` arm, no image, no Lean
    python3 formal/x86_64_endtoend_test.py formal/examples/ret42.mojo formal/examples/wide_recv.mojo

The first was `FAILED (errors=6)` on `work/gatefix6`'s base commit — six
`ValueError: body loops, or branches out of the function` from
`TestX86EndToEndEmitter`, which is what the gate reported as
`formal-sweep-truth`. It is 101 tests, all passing.