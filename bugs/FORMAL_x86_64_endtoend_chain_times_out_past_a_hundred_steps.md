# the x86-64 end-to-end chain cannot close past about a hundred steps, so the first program with a stack argument is unprovable

**Area:** FORMAL (the x86-64 end-to-end prover). **Status: the premise is wrong
and the premise was the bug; the read at a `ret` is now EVALUATED rather than
simplified and closed where the chain is short, two guards that could not work
are fixed, and what is left is one real boundary — the chain's LENGTH — named
exactly, bounded, and measured on both sides.** Found 2026-10-02 while finishing
the SysV stack-argument convention's proof half
(`“`x86_step_mov_rm64_mem_disp32` does not exist”`,
deleted with its fix — the lemmas it asked for are in `lib/X86.lean` and wired in
`formal/x86_64_endtoend_test.py`). Re-opened and rewritten 2026-10-02 on
`work/formal8-14`.

## Status (2026-10-04 — the read at a `ret` is EVALUATED rather than simplified; the chain's LENGTH is still the wall)

The doc's own advice was "evaluate the closed term instead of simplifying it into
one", and it was right, and it is now what the emitter does — **where the chain
is short enough to pay for it, which is not where the remaining holes are.**
Two of the three things below are bugs that were true and unpinned, and the
third is the boundary itself, still open and now bounded instead of unbounded.

**1. The read is proved, not admitted, at 19 equations of chain.**
`formal/x86_64_endtoend_test.py::_concrete_read` unfolds the path's successor
equations with `simp only` and then lets `native_decide` EVALUATE the result.
That is the route this doc argued for and it is what the simplifier's failure
hid: `s{k}.mem` is a `mem_write_bytes` chain one link per instruction and `simp`
reduces all of it symbolically, while every one of its addresses is a LITERAL
(`X86State.init` gives `rsp` the literal `0xfffffffffffffff0`, and this backend
addresses memory through `rsp`/`rbp` only), so the term is closed and evaluating
it is linear where simplifying it was not.

Getting there needed a fact `lib/X86.lean` did not have: **no lemma said a
register or flag write leaves memory alone.** A `.mem` projection stops at the
first `x86_set_reg` — the only wrappers that return a state through a `match` or
an opaque `def` — and brings the sixteen register fields with it, one of which
is `rdi`, where `X86State.init` puts the program's input; `native_decide` refuses
a term with a free variable in it. Five `_mem` lemmas now
(`x86_set_reg_mem`, `x86_set_xmm_mem`, `x86_flags_logic_mem`,
`x86_flags_add_mem`, `x86_flags_sub_mem`), plus the wrapper definitions and this
file's own sixteen `[simp]` REX decodings named in the set, because the write
ADDRESSES are projections out of the same wrappers. Measured on `const2`: 3.4 s,
1.4 GB, `rc=0`, and with the two closing-read admissions deleted the file still
checks — so the read is closed there, and the hole this doc's `const2` row
carried was real.

**2. `try (…) <;> all_goals sorry` never admitted anything.** Every side
condition in every generated file was written that way, on the strength of
B23's second point in the companion doc — and `try t1 <;> t2` does not run `t2`
when `t1` throws. A firing side condition was therefore an `unsolved goals`
error and the file DIED, which is the exact failure B23 exists to prevent. It
was hidden because no side condition in the corpus failed, so nothing could tell
a working guard from a broken one. Measured, both shapes over the same
unsatisfiable goal:

    exact (by try (first | native_decide | decide) <;> all_goals sorry)
      -> `unsolved goals ... ⊢ a + 1 = 4`, and the file dies
    exact (by
      try (first | native_decide | decide)
      all_goals sorry)
      -> `declaration uses sorry`, and the file builds

The two-line form is what the emitter writes now, and the closing read is the
first guard in this file that CAN fire, which is why the two had to be fixed
together.

**3. A `lean` that DIED was reported as a PROOF.** `_run_lean` decided `ok` from
`: error` lines alone, and `lean::memory_exception` ABORTS rather than reports:
on this doc's own 8-argument fixture the process printed
`libc++abi: terminating due to uncaught exception of type lean::memory_exception`
on stdout and exited `-6` with no error line at all, and the report said
`terminates: PROVED`. Every number this doc quotes was therefore a statement
about a file that was never checked on the day the emitter's own fixture was
aborting. The verdict is now driven by what Lean says — `declaration uses sorry`
is the only thing that knows whether a guard's `sorry` is load-bearing — and a
non-zero exit is a failure.

**And the boundary is still there, now measured on both sides.**
The evaluation costs the SIZE OF THE UNFOLDED CHAIN, once per crossing, and at
the length a call with a stack argument produces the file stops elaborating:

| fixture | longest unfold | wall | peak | verdict |
|---|---|---|---|---|
| `const2` | 19 | 3.4 s | 1.4 GB | `rc=0`, read closed |
| 3-argument call | 77 | 127.3 s | 5.2 GB | `rc=0`, a `sorry` still live |
| 8-argument call | 113 | 222.6 s | 6.5 GB | **`rc=-6`**, `lean::memory_exception` |
| 24-argument call | 184 | 258.8 s | 6.0 GB | the same — **and so is the pre-change emitter** |

So `_MAX_UNFOLD = 64` gates the attempt and a longer chain keeps the pre-change
one-equation shape: the 8-argument fixture is CHECKED again at 165.9 s / 6.0 GB
(`rc=0`, against 225.5 s / 6.0 GB before this pass), and the 24-argument one is
no worse than it was — it aborted before this pass too, which the 2026-10-03
table's `127 s, 5.0 GB` no longer reproduces on the current tree and nobody had
looked. 64 is an interpolation between 19 and 77, not a crossover measurement,
and `_MAX_UNFOLD`'s docstring says so and names the bisect.

**What is left, unchanged and now the only thing in this doc.** The per-step
separation invariant: one cheap fact per step, so a read costs O(1) in the
chain's length instead of O(length) per crossing. It needs an emitter-side
stack/frame tracker to make each write's address a literal, which is this doc's
own option 1 and was never the wrong idea — it was the wrong SIZE. The 45-example
sweep is NOT re-measured (it is a heavy run), so
`FORMAL_x86_64_end_to_end_proof.md`'s table stands as of 2026-10-02 and the one
prediction to check first is still `terminates proved with no sorry`.

Everything below this line is earlier and is left as written.

## Status (2026-10-03 — the remaining holes are COUNTED AND NAMED, so the boundary is visible)

The separation itself is unchanged and still open; what landed is the ability to
**see it**. This doc says, twice and in its own words, that "the number the
reader will want is not the number the report gives" — and the reason was that
the verdict line was computed from Lean's `declaration 'terminates' uses 'sorry'`
lines, of which Lean emits **one per declaration**. So a chain with four admitted
`hpop`s and an admitted closing `hrip` read as `proved, 1 sorry`, and the number
of holes that the remaining work consists of was not on the screen anywhere.

`admitted_facts` counts the emitter's own admissions off the generated text, by
the name the emitter gave each one, and reports them **in two classes** because
they are two facts (B21's whole subject):

| | what it is | measured on `wide_recv` |
|---|---|---|
| `admitted` | a fact whose whole proof is `all_goals sorry` — nothing was attempted | **5**: `hpop39`, `hpop67`, `hpop84`, `hpop103`, `hrip` |
| `guarded` | a side condition written `(by try … <;> all_goals sorry)` — the tactic runs FIRST and the `sorry` is reached only if it does not close the goal | **112** |

    wide_recv   terminates: proved, 5 admitted (hpop103, hpop39, hpop67, hpop84,
                hrip), 112 guarded
    bitops      terminates: proved, 1 admitted (hrip), 44 guarded
    const2      terminates: proved, 1 admitted (hrip), 9 guarded

Five is the number the remaining work consists of, and it is the four
returned-tos plus the closing read — exactly the two things the section below
says are left. Before this the same files said `1 sorry`.

**The split is not cosmetic, and both directions were measured.** Counting every
`sorry` in the text gives **118** on `wide_recv`, because each of the 112 guarded
side conditions carries one whether or not it fires; counting only the own-line
ones undercounts. The two numbers answer different questions and the report now
prints both, and `test_formal_sweep_truth.py` asserts the split in both
directions plus the two ways it went wrong while being written:

* a `--` filter but no `/- … -/` filter charged the **theorem's own docstring** as
  an admission — it reads "No `sorry`: the path tree is walked once per branch
  outcome", and that docstring claimed to describe a file with five holes in it.
  That claim is now gone rather than made true (the emitter cannot make it true;
  closing the five is the work below), and both comment forms are stripped.
* a `have <name> … := by` pattern missed the `have hstep7 : … :=` spelling —
  every step lemma is emitted **without** a `by` — so `cur` stayed on the
  previous fact and charged all 112 guarded conditions to `hs`/`hstep` names.

Pinned by four new Lean-free cases in
`test_formal_sweep_truth.py::TestX86EndToEndEmitter` (the file is 92 tests, was
88). Nothing here changes what is proved: same verdicts, same `failing: 0`.

**What is still open is unchanged and is exactly what the sections below name**:
the `hpop` proof, which needs the per-step separation over a chain of writes at
addresses the emitter cannot currently make literal.

**The short version: this is not a prover limit, and none of the three next steps
below can work, because the theorem this program emits is FALSE.** The 24-argument
call builds, runs and answers correctly on both architectures
(`both_arch_twenty_four_arguments_arrive` in `test_formal_run.py`: `241`). The
`terminates` theorem is a different matter, and the timeout is `simp` grinding at
a goal that cannot be closed.

## What I ran

A 24-argument program — the width that forces the callee's stack-argument loads
through a four-byte displacement, and therefore the first program in the corpus
whose path uses `mov_r64_rm64_disp32`:

```
def wide24(a0: int, ..., a23: int) -> int:
    return a23 + a20 * 10 + a6

def main() -> int:
    var x = wide24(1, 2, ..., 24)
    return 0
```

```
$ python3 formal/x86_64_endtoend_test.py .tmp/w24np.mojo
w24np           value:     -  (branches: call_rel32)
  terminates: FAIL error: (deterministic) timeout at `whnf`, maximum number of
```

158 steps, 215 KB of generated Lean, reproduced 2026-10-02 exactly as recorded.

## What is actually wrong, and it is one line of the generated file

The chain's last step is the callee's `ret`:

```lean
have hstep157 : x86_step s157 rc = some
  { s157 with rip := (mem_read_bytes s157.mem (s157.rsp.toNat) 8).toNat,
                rsp := s157.rsp + 8 } := x86_step_ret s157 rc 4294968646 …
have hrip : s158.rip = 0 := by
```

And the `call` at 4294968254 — 78 steps earlier — pushed:

```lean
have hstep77 : x86_step s77 rc = some
  { s77 with rip := (Int.ofNat 4294968254 + 5 + (23)).toNat, rsp := s77.rsp - 8,
            mem := mem_write_bytes s77.mem (s77.rsp - 8).toNat
              (UInt64.ofNat (4294968254 + 5)) 8 } := x86_step_call_rel32 …
```

`4294968254 + 5` is **4294968259**, and that is the word the final `ret` pops.
So `hrip` claims `s158.rip = 0` and the model says `4294968259`. **The goal is
false.** No budget, no decomposition and no index will close it, which is why
tripling `maxHeartbeats` bought nothing (the doc's own measurement, 6m18s → 27m50s
for no result): `simp` was not running slowly, it was failing to find a proof of
something untrue, and `maxHeartbeats` does not meter the `whnf` it stalls in.

The cause is one line of the path tree. `formal/x86_64_endtoend_test.py`'s
`_tree` made **every** `ret` the end of the run. But `call` pushes a return
address and `ret` pops one: after the callee's return the machine is back in the
caller's continuation, and it is the CALLER's `ret` that pops the zero
`X86State.init` puts on the stack — which is what makes address 0 a usable exit
sentinel in the first place.

## The same defect, in the corpus, and it was hiding as a green

`formal/examples/wide_recv.mojo` is the only example in the 45 whose path contains
a `call` (measured: emitted every `terminates` theorem for all 45 and counted
`x86_step_call_rel32`), and it was the only one still carrying a `terminates`
sorry. Its residual goal, taken with `all_goals sorry` → `all_goals trace_state`:

```
⊢ (mem_read_bytes (mem_read_bytes … ) 8) = 0
```

which this doc's companion (`FORMAL_x86_64_end_to_end_proof.md`) read as B18's
"a memory-separation inequality over a symbolic address", and which is in fact
the same false claim: the `call` at 4294967946 pushed **4294967951**.

So a `sorry` was covering for a theorem that was not true, and
`terminates: proved, 1 sorry` was a green resting on it. That is the shape B21
in that doc is about, arrived at from the other end: not three outcomes
conflated as failures, but one failure reported as a proof.

## What is landed (2026-10-02, `work/formal8-14`)

* `_tree` tracks the return address as a LIFO (`rets`), so it can TELL the two
  cases apart, and a `ret` with a frame to return to is declined as its own
  reported outcome — `no tree: the run continues into the caller after the
  callee's ret` — instead of being proved.
* A `call`'s callee is walked with a fresh `seen`: sharing the caller's made a
  second call to the same function look like a cycle, and `wide_recv` calls one
  method body three times (`set_x`, `get_x`, `get_y`). A backward call is a back
  edge and builds no tree at all, which is the `loops` answer and now reaches it
  without recursing in Python to the interpreter limit.
* The outcome is a distinct class (`_NoTree`, carrying a `kind`) rather than a
  message prefix, and it derives from `ValueError` so the existing handler sees
  it. Pinned by six Lean-free cases in `test_formal_sweep_truth.py`.

Measured over the same 45 examples:

| | before | after |
|---|---|---|
| terminates proved with no sorry | 32 | **32** |
| terminates proved with a sorry | 1 | **0** |
| no finite tree | 12 | **13** (10 loop, 2 uncovered form, **1 returns into a caller**) |
| failing | 0 | **0** |

The `sorry` count did not fall because a proof got stronger. `wide_recv` moved
from the proved column to the no-tree column, where it belongs. Both numbers are
worth reading together for that reason.

## Status (2026-10-03 — the return is FOLLOWED; the separation fact is still admitted)

Option 2 of the list below is landed, and with it both programs in this doc emit a
theorem for the first time.

| | 2026-10-02 | 2026-10-03 |
|---|---|---|
| `.tmp/w24np.mojo` (24 arguments, 164 steps) | `no tree: returns into a caller` | **`terminates: proved, 1 sorry`** (127 s, 5.0 GB) |
| `formal/examples/wide_recv.mojo` | `no tree: returns into a caller` | **`terminates: proved, 1 sorry`** (34 s, 2.3 GB) |
| `no finite tree` — the "returns into a caller" column | 1 | **0** (that outcome is no longer reachable for either) |
| `failing` | 0 | **0** |

What landed, in `formal/x86_64_endtoend_test.py`:

* `_tree` gives a `ret` with a frame to return to the successor the matching
  `call` pushed (`rets[-1]`, read off the call's encoding as `m + 5`) and walks
  the caller's continuation with the frame popped. `seen` crosses the return
  UNCHANGED — the callee's addresses have been accumulating since the `call`
  branched off — while the `call` still resets it, so calling one body twice is
  still two calls rather than a cycle. `_NoTree("call")` survives for the one
  decline that is left and now says something true: the continuation after a
  return does not walk.
* The step after a `ret` needs `s_k.rip` and the model says it is read out of
  the frame, so the emitter states it as `hpop{k}` and rewrites the step with
  `rw [← hpop{k}]` — backwards, because the successor already carries the
  literal and the literal has to become `(mem_read_bytes …).toNat` again for
  `x86_step_ret`'s conclusion to match. **The step is still proved by the model.**
* `hpop{k}` is admitted: `simp only [hs{k}]` and the guard takes the rest.
* A chain that crossed a frame is also admitted at its closing `hrip`, because
  the alternative is not affordable (below).

**The report does not show what this costs, and that is worth stating.** Lean
reports "declaration uses `sorry`" once per DECLARATION and
`formal/lean.py::_census_from_output` de-duplicates by name, so four admitted
`hpop`s read as `proved, 1 sorry` exactly like one gap. The option-2 note below
("one `sorry` per post-`ret` step, so `wide_recv` reads worse") is right about
the holes and wrong about the number. They are countable by NAME in the
generated file.

## The second thing this pass found, which was the actual blocker

The return was not what stopped the 24-argument program from being *checked*; a
byte-fact side condition was, and it is fixed. Every hypothesis about the code —
`b0..b3`, the immediates, the displacements — was `simp [read_i32_le, read_i8,
hb]`, and `hb` is `all_bytes`: one conjunct per byte of the function, so each
byte fact became a `simp` set that grows with the size of the program, five
times per instruction. Measured on this program (164 steps, 220 KB of generated
Lean, 579 byte-fact side conditions) that exhausted `maxHeartbeats 4000000` at
`whnf` on **step 19's `h_b1`** and again on **step 105's `h_disp`**, and the file
DIED both times — a heartbeat timeout is not a tactic failure, so the `try`
guard that admits everything else cannot catch it and admit its way out.

`first | native_decide | simp [read_i32_le, read_i8, hb]` settles each one
outright (`rc` is a `def` of an `if` and a list literal, so it is computable at a
literal address) and keeps the simplifier as the fallback, so the change is a
performance change and not a weakening: `bitops` and `const2` report identically
with and without it. After it the same file elaborates in 127 s and reports its
remaining gap as a `sorry`, which is the only shape in which a gap is a number.

This is why the 24-argument program looked like a *chain-length* problem for as
long as it did: the doc's 6m18s → 27m50s heartbeat experiment was raising a
budget for a goal that was both false (B25) and, separately, in a file that could
not finish for an unrelated reason.

## The one real boundary, still open, now measured twice

The two boundaries this doc's table already recorded are still fixed
(`_body`'s lower bound is `entry`; `_tree`'s loop test is a revisited address).
The third is not a boundary at all — it was this bug. What is left is the
separation a followed return needs, and it is a specific statement:

> For the state `s` after a `call` at `m` with the callee's frame pushed below,
> `mem_read_bytes s.mem s.rsp.toNat 8` is the literal `m + 5`.

and — the part option 1 above names and this pass confirms — it needs the READ
ADDRESS to be a literal, because that is what makes each `key` peel's side
condition `a + 8 ≤ b` decidable. Measured again 2026-10-03 on the 24-argument
program, with the read address still symbolic (`s157.rsp.toNat`):

* `simp only [hs1, …, hs157]` followed by `repeat rw [key _ _ _ _ (by first |
  decide | omega)]` did not finish in **1500 s of wall** and was killed by
  `formal/lean.py`'s own bound. That is the doc's 110 s measurement, taken on a
  longer chain and with the cheap `simp only` in place of the full one, so the
  conclusion is stronger than "does not scale": **one such goal is not affordable
  at all** at this size.
* So a per-step separation invariant over a SYMBOLIC address is not the fix; the
  address has to be computed. `X86State.init`'s `rsp` is the literal
  `0xfffffffffffffff0` (`lib/ProofLib.lean`), so an emitter-side stack/frame
  tracker — `push`/`pop`/`call`/`ret`/`sub rsp`/`add rsp`/`leave`, and `mov rbp,
  rsp` — makes every `rsp` and every `rbp`-relative write address along the path
  a compile-time literal, which is what turns each peel into `decide`.
* **A form the tracker does not classify must mean "cannot attempt"**, never
  "unchanged": B22's lesson is that a form with no entry conceals everything
  after it, and here the failure would be a wrong bound rather than a missing
  lemma.

`lib/X86.lean` already has the two round-trip lemmas this needs
(`x86_call_ret_restores_rip`, `x86_call_return_slot_separated`,
`x86_call_ret_balances_stack`, `mem_read_bytes_write_same`,
`mem_read_bytes_write_above`, `lowMask_eight`); what is missing is a way to CARRY
`x86_call_return_slot_separated` across the callee's N steps, which is the
invariant the doc named and still the whole of the remaining work.

## The one real boundary, stated exactly (SUPERSEDED — kept for the measurement)

**Everything below this line is the 2026-10-02 state and is left as written.
Option 2 is LANDED; option 1 is still open and its own sketch is now known to be
wrong, which the Status above says where and why.**

The two boundaries this doc's table already recorded are still fixed
(`_body`'s lower bound is `entry`; `_tree`'s loop test is a revisited address).
The third is not a boundary at all — it was this bug. What is left is the
separation a followed return needs, and it is a specific statement:

> For the state `s` after a `call` at `m` with the callee's frame pushed below,
> `mem_read_bytes s.mem s.rsp.toNat 8` is the literal `m + 5`.

Measured, on the tree that FOLLOWS the return (built and discarded — it is not
landed, and the reason is below):

* `wide_recv` becomes 112 steps with 4 calls and 5 returns, and the step after
  the first `ret` needs `s97.rip = 4294968212` from
  `(mem_read_bytes s96.mem s96.rsp.toNat 8).toNat`.
* Its `rip` side condition is one `simp [hs97]`, and that single `simp` exhausts
  `maxHeartbeats 4000000` in **110 s** and the file dies.
* **And a heartbeat timeout is not catchable by `try`** — B23's fourth point in
  the companion doc — so the `try … <;> all_goals sorry` guard every side
  condition uses cannot admit it. Following the return is therefore not a
  one-line change to the emitter: it needs the per-step separation to be cheap
  enough that the `simp` closes, which is what the `have`-per-step route above
  was reaching for.

**The exact next step, in order:**

1. **Give the emitter a per-step separation invariant** rather than one closing
   `simp`. After each `hs{k+1}`, introduce
   `have hsep{k} : ∀ b, B ≤ b → mem_read_bytes s{k}.mem b 8 = mem_read_bytes i0.mem b 8`
   for a FIXED literal `B` (the outermost frame's exit slot), prove it from
   `hsep{k-1}` plus `A + 8 ≤ B` for that step's write address, and make the
   closing `hrip` `rw [hsep{N}]` against `X86State.init`'s all-zero memory — which
   `lib/X86.lean` already has a lemma for. The blocker is that `A` is
   `s{k}.rsp` for a stack-relative store, and `s{k}.rsp` is a chain of `Nat`
   subtractions; a one-sided bound cannot survive the `add rsp`/`pop` that undo
   it, so the invariant needs either two sides or a generator that evaluates the
   model's `rsp`. **That is the whole of the remaining work and it is worth
   writing down before anyone tries it a third time.**
2. **Or bound the cost first**, so the timeout becomes an admitted `sorry` and
   the case is honestly "proved with N sorries" rather than `FAIL`: emit the
   post-`ret` `rip` condition as `simp only [hs{k}]`, which leaves the goal
   `(mem_read_bytes …) = <literal>` unsolved in O(1) and the guard admits it.
   Measured cost: nothing. What it buys: the theorem is stated over a chain that
   runs to the exit, and each admitted fact is visible. What it costs: one sorry
   per post-`ret` step, so `wide_recv` reads worse while saying more. This is
   why it is second and not first — it makes the number worse on purpose.
3. **Not** the caller's stores, and the doc's own option 3 should be struck: an
   emitter that reserves the outgoing area once would put the call at ~60 steps,
   which does not help, because the goal is false at 60 steps exactly as at 130.

## What is NOT re-measured

`formal/x86_64_model_test.py` (model vs hardware) was not run: nothing here
touches the model. The two boundaries in the table above were not re-measured
either — they were already fixed before this pass and this change does not touch
them. **And neither was the 45-example sweep**: this pass ran the two programs
this doc is about plus `bitops` and `const2` as the no-call control, so the
corpus-wide numbers in `bugs/FORMAL_x86_64_end_to_end_proof.md` are NOT
re-measured and its table stands as of 2026-10-02. The one prediction to check
first is `terminates proved with no sorry`, which must still read 32: the
return-following code is unreachable for an image with no `call`, and that is
pinned Lean-free by `test_formal_sweep_truth.py::TestX86EndToEndEmitter`.
