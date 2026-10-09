# the stack-floor guard still dies of SIGSEGV at exactly the budget's frame count under a reduced `ulimit -s`

**Area:** FORMAL / arm64 codegen. Found 2026-10-05 on `work/merge-formal45` while
merging `work/formal33-recursion-stack`, whose `formal/arm64_codegen.py`
docstring for `_emit_stack_floor_guard` claims the opposite.

## What the docstring claims

`work/formal33-recursion-stack` moved the guard to the top of the prologue —
before `STP X29, X30`, before the saved-register pushes, before
`SUB SP, #_SCRATCH` — and the comment says the position is load-bearing, with
this measurement:

> Measured, arm64, `deep(n)`, `ulimit -s 2048`, where the usable stack is exactly
> 14 frames: `n=13` exits 0 and `n=14` dies with SIGSEGV and no output.

The claim is that after the move `n=14` **refuses** (a status and the trap
message) instead of dying, because the prologue no longer touches the stack
below the limit before anything compares SP.

## What was measured on this machine

`tools/formal_recursion_depth.py`'s own `_FEW_MOJO` (`deep` / `main`, one
128 KiB frame on arm64), built per depth with `-n`, run under
`ulimit -s 2048`:

| depth | `work/formal33-recursion-stack`'s own tree | this tree |
|---|---|---|
| 13 | `d=13`, exit 0 | `d=13`, exit 0 |
| 14 | **SIGSEGV, exit 139** | **SIGSEGV, exit 139** |
| 20 | **SIGSEGV, exit 139** | **SIGSEGV, exit 139** |

At the default `ulimit -s 8176` both trees behave identically and correctly:
`k=40` and `k=58` answer, `k=59` refuses with `model.stack_trap_message` and
exit 2, and the budget printed in that message (7 864 320 = 7.5 MiB = 60 frames
of 131 072) is `STACK_FLOOR_BUDGET_BYTES` rather than the limit.

## Why the arithmetic says it cannot work at 2048

`STACK_FLOOR_MARGIN_BYTES` is 262 144 and the budget is
`min(STACK_FLOOR_BUDGET_BYTES, rlim_cur - MARGIN)`, so under
`ulimit -s 2048` the budget is `2 097 152 - 262 144 = 1 835 008`, which is
**exactly 14 frames** of 131 072 bytes. The guard fires when
`SP < SP_at_entry - budget`, so the fourteenth call is the last one whose SP is
still above the floor and the fifteenth is below it — but the fourteenth call's
own `SUB SP, #_SCRATCH` has already put SP 96 bytes below the floor by the time
its guard would run, and the next push is a touch below the real limit.

So the boundary case is off by the prologue's own pushes however early the
guard goes: what is missing is a budget that leaves room for the frame that
crosses the line, not a position for the check.

## The next step

One of:

* **Subtract the prologue's own footprint from the budget**, so the floor is
  `SP_at_entry - (budget - pushes)` rather than `SP_at_entry - budget`.
  `model.stack_floor_charge` is where that arithmetic lives and
  `STACK_FLOOR_MIN_BUDGET_BYTES` is the clamp that would have to grow with it.
* **Or make the margin scale with the frame**, so a small `rlim_cur` keeps a
  whole frame in reserve rather than exactly none — the same shape as
  `STACK_FLOOR_MARGIN_BYTES`'s own argument for being a flat 256 KiB.

Either way the row to add is `tools/formal_recursion_depth.py`'s: a depth at
exactly `budget // frame_bytes` must REFUSE on both architectures, and the
program is `deep` with `-n` at that depth under `ulimit -s 2048`. It is not in
that tool's corpus today, which is why the docstring's claim survived the merge.