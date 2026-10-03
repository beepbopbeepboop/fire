# FORMAL_x86_64_endtoend_call_rel32_has_no_tree: `formal/x86_64_endtoend_test.py` treats a `call rel32` as a fall-through, so 7 x86-64 examples read "no tree"

**Area:** the x86-64 end-to-end proof driver. Found 2026-10-03 while closing
`bugs/FORMAL_lean_model_call_semantics.md`, which named this as its one
outstanding item and pointed here. That document is retired in the same commit;
this is the item that outlives it.

**Status: root cause located to one missing arm in `build()`. Not fixed here —
the verification this needs is a Lean run, and this worker's brief bounds Lean
and disables the eight Lean-checking suites, so it could not be landed honestly
as "verified".**

## What is already in place, so the remaining work is small

`bugs/OPEN_WORK.md` A1's substance, re-read on this tree 2026-10-03. Everything
the tree-building needs exists; what is missing is the tree.

  * `lib/X86.lean:2040` `x86_call_post`, `:2055` `x86_at_target`, `:2059`
    `x86_ret_post` — what a call does to the machine.
  * `x86_step_call_rel32` — the step lemma, PROVED, and named in `_FORMS` at
    `formal/x86_64_endtoend_test.py:322` with its two hypothesis arguments.
  * The two successors and the separation fact the arm needs:
    `x86_call_ret_balances_stack` and `x86_call_ret_round_trip`
    (`lib/X86.lean:2096`), and the `rip` half behind them
    (`mem_read_bytes_write_same` and the pointwise byte lemmas).
  * The argument plumbing: `_FORMS["call_rel32"]`, its `extra_args` and its
    `extra_succ` arm (`:825`) are all written, with the reason they are written
    that way recorded in place — including the note that `$tgt`/`$ret` are
    deliberately NOT substituted as literals because the successor quotes the
    model's own `(Int.ofNat m + 5 + off).toNat`.

So A1's old framing — "the proof generator is rewritten to a per-instruction
certificate loop that covers `call_rel32` already" — is still true, and the
document it came from (`bugs/OPEN_WORK.md`, not this repo's) should be read as
stale about where the remaining work is.

## The cause: `build()` has no `call_rel32` arm

`formal/x86_64_endtoend_test.py::_tree`'s `build()` handles three shapes and then
falls through to the linear one:

    if form == "ret":            return _Node(..., "ret",  state, None)
    if form == "jmp_rel32":      node = _Node(..., "jmp", state, addr + 5 + off)
                                  node.kids = [build(addr + 5 + off, …)]
    node = _Node(insn, form, raw, addr, "seq", state, addr + insn.length)
    node.kids = [build(addr + insn.length, …)]

A `call rel32` is none of the three, so it becomes a `seq` node whose single
successor is `addr + 5` — the FALL-THROUGH. That is a wrong model of the
instruction, not a missing one: a call has two successors, the target it
branches to and the return address it PUSHES, and the tree never asks what is at
the target. The `ret` node is then built with a stack that never had the return
address pushed, so the round trip the library already proves about
`x86_call_ret_round_trip` is never asked about here.

The consequence is one of the driver's own counters. `_tree`'s `build()` raises
`ValueError` for a form it cannot model, and the reporting block
(`formal/x86_64_endtoend_test.py:1709-1717`) splits that two ways: `_has_loop(t)`
gives `loops (no finite path tree)` and anything else gives
`no tree: <the exception>`. The second is this bug, and it lands in `noform`,
whose label the summary prints as **"uncovered form"** — so the cost of the
missing arm is already visible in the driver's own tally and nobody counted it,
because `7 call_rel32` in the header table (`:61`) is the count of `call_rel32`
SITES in the corpus, not the count of examples this arm decides.

**I did not measure how many examples that is**, and the doc that pointed here
(`bugs/FORMAL_lean_model_call_semantics.md`, now retired) said "7 of the x86-64
examples have no tree" — which is the site count read as an example count. Every
way to settle it runs Lean, which this worker's brief bounds; the number to
report is whatever `noform` drops to.

## Exact next step

1. Add a `call_rel32` arm to `build()`, beside the `jmp_rel32` one and for the
   same reason with one difference: TWO successors, not one.

       elif form == "call_rel32":
           off = int.from_bytes(raw[1:5], "little", signed=True)
           node = _Node(insn, form, raw, addr, "call", state, addr + 5)
           node.kids = [build(addr + 5 + off, None, depth + 1, seen),   # target
                        build(addr + 5,        None, depth + 1, seen)]  # returns to

   The `state` on the node is where the PUSH belongs: the successor equations
   are the ones `x86_call_post_rip`/`x86_call_post_rsp` state, so the two
   hypotheses the tree emits have to be about that state and not the pre-call
   one. Read `x86_call_ret_round_trip`'s own statement for the order the two
   sides are consumed in — it is the fact the arm is checking.
2. Read the new number off the driver's OWN tally. `noform` (printed as "N
   uncovered form") is where this arm's sites have been landing, and the summary
   already separates them from `notree` ("N loop") — so the measurement step is
   "run it and read two numbers", not new instrumentation. What is worth adding
   is the FORM in the message: `no tree: <exception>` truncates to 38 characters
   and a reader cannot tell `call_rel32` from any other unmodelled form.
3. Verify with the ONE Lean run this needs — `formal/x86_64_endtoend_test.py`'s
   own entry point, under `formal/lean.py::run_lean`'s bound, never a bare
   `lean`. A worker with the budget should expect the `call_rel32` examples to go
   from `no tree` to a tree with one step proved, and the previously reported
   `imul`-masked `rsp + disp8` gap (recorded at `:650`) to surface as a
   genuinely unproved step rather than as `no tree`.

## What this is not

Not the `Total` obligation, which was this family's other open item and is
**closed**: `FORMAL_contract_work_handoff.md` records that `e0af987` made `Total`
true for the generated programs and that acyclic `Total` (`triple`) is 0 errors,
0 holes. `bugs/FORMAL_lean_model_call_semantics.md` said the same thing with an
older tree under it, which is why it is retired rather than updated.