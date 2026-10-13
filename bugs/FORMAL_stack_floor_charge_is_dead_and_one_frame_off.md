# FORMAL_stack_floor_charge_is_dead_and_one_frame_off: the helper the guard's comments name would charge one frame too little if anyone called it

**Area:** FORMAL — `formal/model.py::stack_floor_charge`, its two documented
callers in `formal/arm64_codegen.py::_emit_stack_floor_guard` and
`formal/x86_64_codegen.py::_emit_stack_floor_init`. **Status: NOT FIXED, and
deliberately reported rather than acted on — it is a live landmine in a
function another worker's docs claim, and it moves no measured depth today
because nothing calls it.**

## What is wrong

`model.stack_floor_charge(budget_bytes, frame_bytes)` returns
`budget - frame` (clamped at one frame), and its docstring is the four-limit
table that measured, for the OLD budget, that the guard's floor must be
`SP - (budget - frame)` rather than `SP - budget`.

**That budget no longer exists.** `stack_floor_budget_for_limit` now subtracts
the frame itself (`usable = limit - MARGIN - frame`), so the "budget" both
emitters compute already has the frame inside it. The emitters therefore use
that budget DIRECTLY as the charge — `floor = SP - budget` — which is exactly
the old `budget - frame` in the table's own terms, and both of them say so in a
comment ("The frame term is already inside the BUDGET now … so nothing is
discounted here").

So `stack_floor_charge` is (a) **uncalled** — verified, the only occurrences
tree-wide are its definition and two comments — and (b) **wrong if called**:
`stack_floor_charge(new_budget, frame) = new_budget - frame`, one frame less
than the emitters charge. A smaller charge is a LOWER floor, so the guard would
fire one frame LATER, which is the `budget + frame` column of its own table —
the "too deep" / crash direction. A future reader who follows the comments ("the
charge is `model.stack_floor_charge(budget, _SCRATCH)`") into that function and
routes the emitters through it would reintroduce the SIGSEGV this guard exists
to replace.

## How it was found

While fixing the arm64 guard's reduced-`ulimit -s` SIGSEGV (it took
`getrlimit`'s RETURN STATUS as the limit instead of loading `rlim_cur` back out
of the scratch struct the call wrote; fixed 2026-10-07). The comment at
`arm64_codegen.py:2038` names
`stack_floor_charge` as the arithmetic while the code beside it stores the
budget; `grep` for a call site found none.

## The exact next step

One of:

* **Delete `stack_floor_charge`** and rewrite its two comment mentions to name
  `stack_floor_budget_for_limit`'s frame term and the emitters' direct use of
  the budget. This is the consolidation `CLAUDE.md` asks for (one answer to one
  question) and leaves no wrong arithmetic to find.
* **Or make it authoritative**: change it to return the emitters' charge
  (`budget`, clamped) and have both emitters CALL it, so the docstring's table
  and the emitted bytes cannot drift again. That is the larger change and it
  touches proof-walked instruction sequences, so it wants the `formal` /
  `formal-call-proofgen` gate.

Which one is right is a call for the stack-floor owner; it is filed rather than
taken because the choice changes the emitted prologue and the guard area is held
by other workers this round.
