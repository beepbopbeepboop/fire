# [3] round 2: per-export contracts — library landed, per-export proof DOES NOT

**Status: the §11.2 [3] Done-when is NOT met, and my previous turn said it was.
That was wrong, and the error was mine in a way worth recording.**

| | |
|---|---|
| `lib/Contracts.lean` | **landed, verified, 0 admitted holes.** Compiles clean: `lean` exit 0, no `declaration uses 'sorry'`. |
| Registering it in `formal/lean.py` | **landed.** |
| Per-export spec, derived from source | **landed** in a stash, not emitted (see below). |
| A real export carrying a proved non-identity spec | **NOT PROVED.** `bv_decide` cannot do it. |
| A caller discharging against it | **NOT PROVED** — depends on the above. |

## The retraction, first, because it is the load-bearing part

Last turn I reported the Done-when **closed** for a real dylib export, with
"0 errors and 0 `sorry`" and negative controls that "refute" the identity spec.
None of that was verified. Every one of those checks ran as

    timeout 1700 env LEAN_PATH=... lean Foo.lean 2>&1 | grep -c "error"

and **`timeout` does not exist on this machine.** Bash printed
`timeout: command not found`, `grep -c` read empty input, and `grep -c` on
nothing prints `0`. So the pipeline printed `0` and I read that as "no errors".
The artifact I committed as a "golden" reference does not compile:

    error: invalid 'import' command, it must be used in the beginning of the file

Its `import Contracts` was mid-file, which is fatal — elaboration stops there,
so the file's *contents* were never even typechecked. It also contained
independently broken text I had never seen for the same reason: `st1` was
emitted as `arm64_set_reg 29 st0 s (st0 s.sp + 0)`, where `st0 s.sp` parses as
`st0` applied to `s.sp`. Two bugs, both invisible behind the import error.

The checks that did **not** use `timeout` were real, and one of them is why I
should have caught this: the `atExit` type error surfaced immediately in a
`grep`-free run. I had the evidence in hand and still let the `timeout`-based
results stand. `lib/Contracts.lean`'s own verification never used `timeout`,
which is why it is genuinely clean.

The method lesson, which is the part I would keep: **a verification whose
verifier never ran is not a weak result, it is a fabricated one**, and `grep -c`
on a failed command returning `0` is exactly the shape that hides it. A check
that cannot fail should not be reported as a pass.

## Why the contract is not provable the way I claimed

I claimed, and the committed message says, that `bv_decide` discharges the
spec including the frame's memory round trip. It does not. Against the real
generated dylib:

    m_proof.lean:1950: error: The prover found a potentially spurious counterexample:
    - It abstracted the following unsupported expressions as opaque variables:
      [arm64_reg 0 (S14 (start n))]

`bv_decide` decides goals over `BitVec n`. `Arm64State` is a **structure**, so
`arm64_reg 0 (...)` is not a bitvector term, and `bv_decide` abstracts it as an
opaque variable instead of evaluating it. The claim was never plausible and I
should have tested it against the real generator before writing it down — the
measurement I *did* take (concrete values, `native_decide`, `triple 7 = 21`)
said nothing about symbolic evaluation, and I let the concrete result stand in
for the symbolic one.

Two further obstacles, both real and both still open:

* **The pc discipline does not close.** `simp [S_k, …]; omega` leaves a large
  unnormalised record, and `omega` reports a counterexample it cannot refute.
* **`native_decide` cannot help**, because after `intro n` the goal has a free
  `n`. So neither decision procedure covers the gap: the machine model is over
  a structure, and the statement is universally quantified.

## What closing it actually needs

One of these, and I have not built either:

1. **A symbolic evaluator for the machine over `BitVec 64`.** An `Arm64State`
   whose registers are `BitVec 64` and whose memory is a bitvector-indexed
   function would make `hreg` a bitvector goal, which is precisely what
   `bv_decide` is for. This is the principled fix and it is real work.
2. **A normalisation strategy for the composed effect** that `decide` can
   follow: the memory addresses are all constants (the `sp` arithmetic never
   involves the argument), so the list of memory writes is short and closed,
   and kernel reduction *might* normalise the read-back to a closed `UInt64`
   expression in `n`. Whether that is fast enough is a measurement I never
   made, because the `bv_decide` failure stopped the file earlier.

The frame round trip is not the hard part, and I was right about that much:
it is real, and the `x30` round trip is exactly what makes `atExit` true.

## What is landed, and what it is worth

* `lib/Contracts.lean` — 316 lines, compiles clean, 0 holes. `go_exit_cons`,
  `go_exit_within`, `ExportBody`, `runs_to_body`, `agrees_of_body`,
  `caller_uses_contract`, `SpecIsIdentity`. The generic machinery is sound and
  reusable; what is missing is an instance.
* `formal/lean.py` — `Contracts` registered, so it is built and censused rather
  than sitting in `lib/` unbuilt. The four previously registered modules still
  report **0 admitted sorries**; `Contracts` adds none.
* Spec derivation from source, and the parens/`some`-stripping fixes to the
  emitter: **in a stash**, not emitted. Recoverable with
  `git stash list` / `git stash pop`. It is correct as far as it goes —
  `return n * 3` → `(fun n => (n * (3 : UInt64)))`, `return 2` → `(fun n => (2 : UInt64))`,
  `return n % 7` → `(fun n => (n UInt64.mod (7 : UInt64)))`, and it declines
  `mojo_pow_mod(n, 3)` rather than guessing. The generator now correctly
  parenthesises the substituted state, defines `S0` instead of leaving it to
  `autoImplicit` (an undefined `S0` is a free *variable* of function type, so
  every `hpc0` would have been a statement about an arbitrary function), and
  strips the `some` from `_step_rhs`. Those three are real bugs found and fixed
  regardless of whether the contract is ever proved.

The generator deliberately emits the **named `sorry` obligation** for the spec,
unchanged, because the alternative is emitting a contract that does not prove
and turning an honest hole into a build failure.

## Also retracted: the x19 "aside" (this one was right to retract)

Last-but-one turn I flagged that the run returns `x19 = 0` "after a prologue
that spilled `x19 = n`", suggesting a model or codegen defect. That retraction
stands and is *not* affected by the verification failure: it came from walking
the body one instruction at a time with `#eval`, which is direct execution and
not a proof. `x19` is callee-saved, was 0 on entry, and the epilogue correctly
restores 0. The frame round trip is exact. That conclusion is as solid as
anything here.

## Verification state of this turn

* `lib/Contracts.lean`: `lean` exit 0, no `declaration uses 'sorry'`. Real run,
  no `timeout` in the pipeline.
* `fire dylib --formal` on a real `def triple(n): return n * 3`: builds, and the
  proof census reports **1 declaration admitted a `sorry`** — the per-export
  spec, named and counted. That is the honest current state of the dylib proof.
* The emitted contract (from the stash) does **not** typecheck-prove: the errors
  above are from a real `lean` run.
* The golden is removed; it did not compile.
