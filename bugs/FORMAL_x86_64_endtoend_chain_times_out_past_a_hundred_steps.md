# the x86-64 end-to-end chain cannot close past about a hundred steps, so the first program with a stack argument is unprovable

**Area:** FORMAL (the x86-64 end-to-end prover). **Status: the premise is wrong
and the premise was the bug. What is left is one real boundary, named exactly,
with the measurement that says so.** Found 2026-10-02 while finishing the SysV
stack-argument convention's proof half
(`bugs/FORMAL_x86_64_stack_argument_past_the_twentieth_needs_a_disp32_lemma.md`,
deleted with its fix — the lemmas it asked for are in `lib/X86.lean` and wired in
`formal/x86_64_endtoend_test.py`). Re-opened and rewritten 2026-10-02 on
`work/formal8-14`.

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

## The one real boundary, stated exactly

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
them.
