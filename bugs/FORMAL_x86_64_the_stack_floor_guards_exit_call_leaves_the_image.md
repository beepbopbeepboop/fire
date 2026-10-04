# the stack-floor guard's `exit(2)` call target is outside the image: the path tree now ends there, and the theorem is a disjunction over halt addresses

**Status: the path tree is FIXED (2026-10-04, `work/gatefix6`); what the guard
still costs is written down below and is not fixed.** The defect this doc filed
— "no end-to-end path tree exists", every example reporting `body loops, or
branches out of the function` — no longer happens, and the theorem that is
emitted instead is one the model can support.

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

## Reproducing

    python3 tools/memslot.py --gb 8 --label fst -- python3 test_formal_sweep_truth.py
    python3 test_formal_x86_64_call_tree.py            # the `_tree` arm, no image, no Lean
    python3 formal/x86_64_endtoend_test.py formal/examples/ret42.mojo formal/examples/wide_recv.mojo

The first was `FAILED (errors=6)` on `work/gatefix6`'s base commit — six
`ValueError: body loops, or branches out of the function` from
`TestX86EndToEndEmitter`, which is what the gate reported as
`formal-sweep-truth`. It is 101 tests, all passing.