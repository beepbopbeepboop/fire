# The arm64 exit cannot flush without a call, and a call on any proof-walked path breaks proof generation — the precondition for `FORMAL_arm64_exit_trap_does_not_flush_so_a_program_that_prints_then_exits_1_prints_nothing`

**Area:** FORMAL, both backends. **Status: OPEN, and it is the PRECONDITION for the
doc named above, measured on this tree 2026-10-04 (`work/formal23-2`). RE-MEASURED
2026-10-05 on `work/formal27-2` and still open, with two things landed and the
next step now stated in terms of the Lean signature it has to change — see
"What changed on 2026-10-05" at the end. NOT fixed: the fix is a
`lib/ProofLib.lean` change whose soundness cannot be established without the
Lean gate, which a light worker may not run.** That
doc's §"Exact next step" step 1 — one `_emit_exit` helper that emits
`fflush(NULL)` before the three-instruction trap, at all 21 sites — **is
measured NOT to land as written**: it makes `formal/examples/udivmod.mojo` stop
generating a proof at all. This is the blocker, and it is a different defect
from the exit-flush one, so the flush doc stays where it is and this names the
thing in front of it.

## What I ran, and what I saw

The two-instruction experiment, applied to ONE trap site
(`_emit_div_shift_pow`'s divide-by-zero arm), which is the smallest site that
reaches the arm64 proof generator's CFG walk:

```python
            self.asm.label(div0_label)
            self.asm.emit(encode_movz_xd_imm(0, 0))
            self._emit_extern_call("fflush", 1)     # ← the whole change
            self.asm.emit(encode_movz_xd_imm(0, 1))
            self.asm.emit(encode_movz_xd_imm(16, 1))
            self.asm.emit(encode_svc(0x80))
```

    $ python3 -c "import sys,os; sys.path.insert(0,'.'); import formal.build as fb; \
        fb.compile_formal('formal/examples/udivmod.mojo', arch='arm64', \
                          output='.tmp/udivmod.aout', prove=True, check=False)"
    NotImplementedError: universal theorem: 2 calls this walk cannot follow
    (0x100000448 -> 0x1000004b4 (opaque), 0x100000488 -> 0x1000004b4 (opaque)),
    and ONE halt address cannot discharge them.  The run reaches 0x100000448 only
    on the paths that pass it, so a second call has paths of its own -- the honest
    statement would be a disjunction over the call addresses, which is one exit
    address more than this framework has.  The semantic model is emitted and
    correct for all of them; what is missing is the machine half.

Before the change the same program generates `udivmod_compiles_correctly_universal`
— a real theorem about `s.x0 = mojo n` for every `n`, not an admission.
`udivmod.mojo` is not in `test_formal.py`'s `EXPECTED_FAILURES`, so this would be
a new red in a gated Lean test.

## Why: there is no way to flush without an unfollowable call

`fflush` is in the C library, so flushing is a `BL` to an address outside the
image. Every way the arm64 generator can react to that is closed:

* **`_call_boundary` / `_opaque`** (`formal/arm64_proof_gen.py`) halts the walk at
  the FIRST such call and restates the theorem as "the run reaches the call",
  with `prop := "True"`. For a flush inside a conditional arm that statement is
  **false** — the run reaches the flush only on the paths that take the branch —
  so this is not a weaker theorem, it is a broken one. One flush site is already
  enough: `udivmod` has TWO (`/` and `%`), and the error above is about the
  second.
* **A `b` to a thunk outside the function** does not help either: `_cfg_blocks`
  only builds blocks inside `[func_entry, func_end)`, so the target has no block
  and `emit_block` raises `unsupported edge to <addr> (loop back-edge /
  continuation; no loop contract matches)`.
* **A thunk INSIDE the window** is worse: the walk follows it and hits the
  `bl fflush` inside it, which is the same wall one level down.
* **`BLR` through a register** is an unmodelled word (`_step_branch_index`
  returns `None`), so the block's run certificate cannot be built at all.

So the honest statement of the precondition: **the arm64 CFG walk must be able to
discharge a block whose last instruction is a call it cannot follow** — the run
leaves the image, and the terminal proposition for THAT block is
`arm64_go_exit … = none` rather than the function's uniform `x0 = mojo n`. That
is a change to the theorem's shape (a disjunction, or a per-block terminal
predicate), not a tactic, and `_unfollowable_calls`' own docstring says so: *"the
honest statement would be a disjunction over the call addresses, which is one
exit address more than this framework has."*

## Why it is not the same as the x86-64 side, which already has this problem

x86-64's exit IS a call — `_emit_call_exit` → `_emit_extern_call("exit")` — so
x86-64 has been paying this cost for the whole corpus and has machinery for it:
`info["compiler_traps"]` records the trap's address and
`x86_64_proof_gen._program_externs` subtracts it, which is what puts the run
tests back. arm64 has no `compiler_traps` and no such subtraction: the raw trap
is in every prologue (`stack_floor_guarded_names` widened it to every function),
so an arm64 version of that mechanism would have to start by naming the stack
floor's trap address as a compiler trap — and the flush doc's step 2 already
excludes that one site for a different reason (the proof generator decodes it).

## The exact next step

1. Give `emit_block`/`emit_runs` a per-block terminal: a block whose last
   instruction is an unfollowable `BL` gets `arm64_go_exit … = none` as its
   terminal proposition, and the walk's final step becomes a disjunction
   ("the run returned `none`, or it returned `some s` with `s.x0 = mojo n`").
   `walk-terminal` is where the uniform proposition is assembled today, so that
   is the one line to change, and `CFG_LEAF_SITES`' `walk-terminal` is where a
   new leaf name goes if the disjunction cannot be closed automatically.
2. Then the stack-floor guard's trap, and only then, every other site.
3. Measure with the sweep's own arm64/x86-64 parity, which is what found the
   divergence, and with `formal/examples/udivmod.mojo` as the anti-rot: a
   generator change that makes it stop generating is a regression whatever it
   fixes.

## Reproduce

The experiment is two lines in `formal/arm64_codegen.py` and is reverted by
deleting them; `formal/examples/udivmod.mojo` is the whole case. No Lean is
involved — generation alone raises, which is why this is cheap to check and why
it was not noticed while the exit-flush bug was still described as an emitter
decision.

## What changed on 2026-10-05 (`work/formal27-2`)

**The reproduction no longer needs an emitter change, and the addresses in the
section above are stale.** The two-instruction experiment is still the right
experiment — applied to `_emit_div_shift_pow`'s divide-by-zero arm on this tree,
`formal/examples/udivmod.mojo` stops generating with

```
NotImplementedError: universal theorem: 2 calls this walk cannot follow
(0x100000448 -> 0x1000004d4 (opaque), 0x1000004a8 -> 0x1000004d4 (opaque)), and
ONE halt address cannot discharge them.
```

— the same shape, at addresses that have moved (`…4b4` above is `…4d4` now, and
the second call is at `…4a8`, not `…488`) — but a TWO-LINE program reaches the
identical refusal with no patch at all:

```python
def main(n):
    if n > 0:
        printf("pos\n")
    else:
        printf("neg\n")
    return 0
```

Two `printf`s on opposite arms is the smallest program with the shape, so the
next worker does not have to edit `formal/arm64_codegen.py` to find out whether
the precondition moved. That program is now the fixture behind
`test_formal_call_proof_gen.py`'s
`TestCallProofs::test_two_calls_out_of_the_image_are_refused_by_name`, which
pins the state of the gap in the three ways a reader needs: refused rather than
emitted (an emitted theorem here would be FALSE — `arm64_step` answers `none` at
both addresses, so the `none` branch of `x0 = mojo n` is `False`), both
addresses named, and the word "disjunction" present so the work can be sized.
`formal/examples/udivmod.mojo` still generates its proof on this tree, which is
the anti-rot for the other half: a change that made it stop generating would be a
regression whatever it fixed.

**The next step is in `lib/ProofLib.lean`, not in `walk-terminal`, and that is
the correction worth having.** The doc's step 1 says the terminal proposition is
assembled at `walk-terminal` and that this is "the one line to change". It is
not: the halt address is a single `Nat` compared against `st.pc` in the model's
own loop, and it is threaded through EVERY run lemma the walk's induction is
built from:

```lean
def arm64_go_exit (st : Arm64State) (code : Nat → UInt8) (exit : Nat) (fuel : Nat) : Option Arm64State :=
  if fuel = 0 then none
  else if st.pc = exit then some st
  …
```

`arm64_exec_go_exit` is that call, `arm64_go_exit_call` is the same test again,
`lib/Refine.lean`'s `Prog` carries `p.exit`, and `formal/arm64_proof_gen.py`'s
`emit_runs` passes `exit_pc` to `runs_avoid_append` on each of its three paths
(the prologue segment, the call, and the segment itself) through one
`append_avoid` closure. So a block that ends at a SECOND opaque call has no
lemma to invoke, and per-block terminals need either

1. a set-valued exit — `arm64_go_exit` over a list of addresses plus a gluing
   family beside `go_exit_step`/`go_exit_b`, which is the whole of `runProg`'s
   exit discipline re-proved once per shape; or
2. two independent induction chains, one per halt address, which cannot work
   because a path reaching the other call executes a `BL` the model cannot step
   (so each chain's run lemma fails on the other's block) — this is why "run it
   twice and disjoin the theorems" is not the cheap version of the fix.

Option 1 is the work. It is a `ProofLib` project with an emitter change beside
it, and **it cannot be landed without the Lean gate**: a per-block terminal that
does not close produces a theorem with a `sorry` in it, which the census reads as
clean, and one that closes by accident produces a false theorem. That is the
whole of why this is still open.
