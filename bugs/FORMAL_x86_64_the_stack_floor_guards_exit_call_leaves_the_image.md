# the stack-floor guard's `exit(2)` call target is outside the image, so no end-to-end path tree exists

## Status: OPEN, not fixed — the two missing step lemmas this sat behind are now
## proved and wired (`work/gatefix5`, 2026-10-03), and this is the layer they
## uncovered. It was NOT visible before them: `_plan` refused first, so
## `test_formal_sweep_truth.py`'s six `TestX86EndToEndEmitter` cases reported the
## coverage gap and never reached the tree.

## What I ran

    python3 tools/memslot.py --gb 8 --label fst -- python3 test_formal_sweep_truth.py
    ...
    ValueError: body loops, or branches out of the function
    Ran 97 tests in 20.296s
    FAILED (errors=6)

All six errors are the same one, and it is a different `ValueError` from the one
this layer used to raise: `_plan`'s `no step lemma wired for: alu_ri32:sub_reg,
lea_r64_rip` is gone, and `emit_terminates` now fails one line later, in
`_tree`.

## What it is

`_tree` follows a `call_rel32` to its TARGET (B22's fix — the instruction after a
call is not the one the machine runs). The stack-floor guard's trap arm is a call
to the C library's `exit`, and that target is not in the image, so `by_addr`
misses and the whole tree declines.

Measured on the fixture `TestX86EndToEndEmitter.SOURCE` compiles
(`formal/build.compile_formal(..., arch='x86_64')` then `_plan`), image
4294968274..4294968501, entry 4294968274:

| call at | target | what it is |
|---|---|---|
| 4294968343 | 4294968504 | **outside** — `exit(2)`, function 1's guard |
| 4294968397 | 4294968412 | in the image — the real call to `Point.get_x` |
| 4294968481 | 4294968504 | **outside** — `exit(2)`, function 2's guard |

Exactly two, one per function, both to the same address — the same 2-per-function
shape the two missing step lemmas had, which is the guard and nothing else.
`_has_loop` answers False, so this is the "branches out of the function" half of
that message and not the loop half.

The guard's own sequence says where it comes from
(`formal/x86_64_codegen.py::_emit_stack_floor_guard`):

    LEA R11, [rip+&floor] ; MOV R10, [R11]   the floor word
    TEST R10, R10 ; JNE done                 already stored
    MOV R10, RSP ; SUB R10, BUDGET ; MOV [R11], R10
    done:
    MOV R11, RSP ; CMP R11, R10
    JAE ok                                    SP >= floor: carry clear
    exit(2)                                   SP < floor
    ok:

and `_emit_call_exit(M.STACK_TRAP_STATUS)` at its end is what emits the `call`.

## Why it is not a one-line fix, and what the question is

`_tree` declining is CORRECT for what it was built to do: it walks paths whose
every step is inside the image, and this one leaves it. The question is what the
MODEL says happens at an address with no instruction, because the answer decides
whether `terminates` is even TRUE:

* If `x86_exec` at an unknown address is "the run has left the modelled
  machine" — no step, no successor — then the guard's trap arm makes
  `(x86_exec_exit (X86State.init n entry) rc 0).isSome = true` FALSE for every
  input whose stack is shallower than the budget, and no tree can prove it. The
  theorem as stated is then wrong for every program with a guard, and the fix is
  to the STATEMENT (a disjunct for "or the run traps"), not to the tree.
* If `x86_exec` treats a missing instruction as "the pc is wherever it is" and
  keeps going, the trap arm is a step the model does not take and the guard is
  unsound in the model.

Both readings are defensible and they are not the same theorem, so this is a
decision about the model's semantics rather than a patch. It is the same
`exit`-in-the-prologue fact
`bugs/FORMAL_x86_64_run_tests_are_gone_since_the_stack_floor_guard_emits_exit.md`
records for `formal/x86_64_proof_gen.py`'s externs guard, in a third consumer:
that one loses the RUN TESTS section, this one loses the path tree.

## Next step

1. Read `x86_exec` / `x86_exec_exit` in `lib/X86.lean` and write down what
   happens at an address with no instruction — one sentence, and it decides
   step 2. Do not start from the tree.
2. If the run ends there, `terminates` needs a second disjunct ("…or the run
   leaves the image") and `_tree` needs to emit that arm, which is a real
   change to the emitted theorem and not a tolerance.
3. Whichever it is, pin it Lean-free next to
   `test_the_return_is_a_named_fact_and_the_step_uses_it` so the six cases
   cannot silently go back to reporting a coverage gap they have passed.

## Re-verify with

    python3 tools/memslot.py --gb 8 --label fst -- python3 test_formal_sweep_truth.py

all six `TestX86EndToEndEmitter` cases must stop raising, and
`python3 tools/suite.py formal-x86-endtoend` must stay at 3 passed.
