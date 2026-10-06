# FORMAL_arm64_an_extern_call_makes_the_run_never_reach_the_exit: the `pre_reaches_0` obligation is FALSE for every program whose only opaque call is on the path, and it is emitted anyway

**Area:** FORMAL (the arm64 proof generator's extern-call run test) · **found
by** `formal/examples/mod_by_var.mojo`, one of the 42 examples added on
2026-10-05 · **arm64** (the x86-64 generator answers the same program with its
own placeholder path, so it never emits this obligation) · **filed 2026-10-05,
NOT fixed.**

## What I ran

    python3 tools/memslot.py --gb 8 --label unary -- python3 -c "
    import sys; sys.path.insert(0,'.')
    import tools.formal_proof_census as C
    r = C.measure_example('mod_by_var')
    print(r.status, r.reason)"

from

```python
def mod_by_var(n):
    d = 4
    return n % d
```

## What I saw

`status = lean-rejected`, and the first diagnostic is not a `sorry` and not an
unsolved goal:

    mod_by_var_proof.lean:85:2: error: Tactic `native_decide` evaluated that
    the proposition to be false

Line 85 is:

```lean
theorem mod_by_var_pre_reaches_0 :
  run_pc_reached { (Arm64State.init 10 4294968256) with
                     x30 := UInt64.ofNat 4294968476 }
                 mod_by_var_code 4294968440 200000 = true := by
  native_decide
```

**The obligation is false, and it is false about the machine.** `n % d` with `d`
a *variable* emits a `BL` into `__TEXT,__stubs` — the run-time division helper,
outside the image — and `lib/ProofLib.lean`'s `arm64_step` has no row for a call
to an address it cannot decode, so the modelled run STOPS at the call. It never
reaches pc 0, which is what `pre_reaches_0` asserts. The IMAGE is fine: built and
run, it exits 2, which is `10 % 4` and is what CPython answers.

The program's own answer is not in question; the theorem is about the run
reaching the exit, and the run does not.

## What I expected

A refusal, or no such obligation. `bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`
establishes that every reaction the generator has to an unfollowable call is
closed, and that the remaining honest statement is a precondition ("the run
reaches the call"). What it does not say is that the *pre*-condition emitted for
a single opaque call on the only path is `run_pc_reached … exit = true`, which is
a claim about reaching the exit and is exactly what the model cannot establish.

**Why one call site reaches this and two do not** is the measurement that makes
it a small, separate bug rather than a restatement of that doc:

| program | extern calls | what the generator does |
|---|---|---|
| `floordiv`, `udivmod` (`n // 7 + n % 7`) | two | **refused**: `universal theorem: 2 calls this walk cannot follow (0x… -> 0x… (opaque)), 0x… -> 0x… (opaque)), and ONE halt address cannot discharge them` |
| `mod_by_var` (`n % d`, one variable divisor) | one | **emits a proof**, with `pre_reaches_0` false |

So the walk's own rule ("one halt address can discharge one call") is what lets
this program through, and what it emits on the far side is an obligation the
model has no way to discharge. The refusal and the false theorem are the same
gap seen from two sides, and the corpus now carries a row for each.

## The exact next step

`_gen_extern_test` (`formal/arm64_proof_gen.py`) writes `pre_reaches_0` for the
pc it plants the exit at. Two things have to be decided together, and the first
is the cheap one:

1. **Is pc 0 even reachable for this program?** The generated theorem can
   already tell: the extern call is a `_call_boundary`, and the block that ends
   at it is already recognised. So when the only path to the planted exit goes
   through a call the model cannot step, emit the *documented* precondition —
   "the run reaches the call" — instead of "the run reaches the exit". That is
   `prop := "True"` over the call pc, which is the shape the sibling doc already
   argues for, and it is a change to one address in one f-string.
2. **If it cannot be told**, refuse, as the two-call case does. A theorem that
   is false about the machine is the one outcome the whole design is arranged to
   avoid (`bugs/FORMAL_string_value_model.md`'s "a stated gap costs a program its
   proof, and a fabricated model costs it a proof of something FALSE"), and a
   refused program costs one row of `tools/formal_proof_census.py` while a false
   theorem costs the reader a proof they cannot trust.

Either way the oracle is a Lean run, so this needs the `formal` suite behind it
rather than one example; the cheap half — that the emitted obligation is false,
which `native_decide` has now said in the generated file's own words — is
recorded above.
