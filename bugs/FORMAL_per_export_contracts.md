# [3] round 2: per-export contracts — library landed, per-export proof DOES NOT

**Status, rewritten 2026-10-02: the §11.2 [3] Done-when is STILL not met, and
the three claims this doc's own body ends on are now MEASURED rather than
argued — two of them are wrong.** The §11.2 answer below is unchanged (it was
never met); what changed is that the blocker is no longer "a HEARTBEAT limit
that might lift". It is a CPU limit, it is inside `simp only` rather than
`bv_decide`, and there is a **second** expensive declaration the doc does not
mention. Everything the body says about the retraction, the stash and the
`timeout`-that-does-not-exist is left in place as the record it is.

## The five measurements, and the three claims they refute

Subject: a three-line `def triple(n): return n * 3` built through
`fire dylib --formal`. The generated file is 2,786 lines and the body's composed
effect is a 15-step chain (`st0`…`st14`, `S1`…`S15`).

    $ python3 tools/memslot.py --gb 8 --label pe -- \
          python3 fire.py dylib --formal -o .tmp/pe/triple.dylib .tmp/pe/triple.mojo
    [proof census: triple_proof.lean — hole census not measured, 0 vacuous …]
    formal dylib: proof check failed: lean exceeded 1500s CPU (limit 1500s,
      enforced by RLIMIT_CPU inside lean) — killed, and this is NOT a verdict
      on the proof

Every variant below is that file with one or two proofs replaced, run through
`formal.lean.run_lean` with `LEAN_PATH=lib`, wall 1500 s and CPU 1500 s — the
bounds `formal/lean.py` already enforces, so nothing here launched `lean`
directly.

| variant | what was replaced | result |
|---|---|---|
| **vC** | `hreg` → `True`, `noEarly` → `sorry` | **6.2 s**, 1.59 GB peak. **The rest of the file is cheap.** |
| **vB** | `hreg` → `True` only | **> 1500 s CPU** (SIGKILL), 1.44 GB |
| **vA** | `noEarly` → `sorry` only | **> 1500 s CPU** (SIGXCPU), 1.46 GB |
| **vD** | `noEarly` → `sorry`, `hreg`'s `bv_decide` → `sorry` | **> 1500 s CPU** (SIGXCPU), 1.59 GB |
| **vF** | vA plus `Arm64State.init` in the unfold set | **> 1500 s CPU** (SIGXCPU), 1.47 GB |

Read across the rows:

1. **`maxHeartbeats` is the wrong lever, which is the measurement the last
   section of this doc asked for and the answer is NO.** The generated file sets
   `maxHeartbeats 20000000` itself (line 7). The run is killed by
   `RLIMIT_CPU`, not by a heartbeat timeout, so no heartbeat budget can extend
   it: the process spends its whole life inside arithmetic and never approaches
   the budget. Raising it would make the same arithmetic run 2x as long and die
   of the same signal.
2. **`bv_decide` is not where the time goes.** vD removes it entirely, leaving
   `simp only [_UNF]` in place, and the file still does not check. So the
   bit-blasting of the 64-bit multiply — which the doc names as the thing
   "left to `bv_decide` after the memory round trip is discharged as its own
   lemma" — is not the cost, and discharging the memory round trip first would
   not have helped.
3. **`noEarly` is a second, independent hog, and it is one of exactly two.**
   vB neutralises `hreg` and still blows the bound; vC neutralises both and
   finishes in 6.2 s. So the 100-odd decode lemmas, the 15 `runsTo` chains, the
   15 `S*_pc` `omega` lemmas, `atExit`, the frame round trip and the `Total`
   proof are all cheap — the file has a 1500x gap between its cheap 99% and its
   expensive declarations, which is why the earlier "6 errors" and "12 errors"
   readings could not see it.

**One premise in the body is stale and changes the next step:** the memory model
is NOT "a 6-entry memory list". `Arm64State.mem` is a function,
`mem : Nat → UInt8`, and `Arm64State.init` sets it to `fun _ => 0`
(`lib/ProofLib.lean:1244`). The frame addresses are constants too —
`sp := 0xfffffffffffffff0` — so the round trip through `mem_read_u64` /
`mem_write_u64` is at constant addresses and is NOT the obstruction the doc's
option 2 assumes.

## What the next step is, sharpened by the above

The target is one call: `simp only [_UNF]`, where `_UNF` is thirty step
definitions plus `body` plus `arm64_reg` / `arm64_set_reg` plus `_VALUE_SIMP`
(`arm64_proof_gen.py`'s `_dylib_contract_proof`). Two shapes, neither tried
here, both of which replace the whole-chain unfolding with a chain of
one-step-at-a-time lemmas:

* **a per-step value chain for `hreg`** — `hval0 : ∀ n, arm64_reg 0 (S0 (start
  n)) = n` and `hval{i+1} : ∀ n, arm64_reg 0 (S{i+1} (start n)) = <a closed
  term in n>`, each proved from the previous with ONE `st_i` in the simp set
  rather than thirty. `hreg` is then `hval14`. The point is not elegance: it is
  that a simp set of thirty rewrites over a fifteen-deep chain of
  thirty-five-field records is what `simp` is being asked to normalise, and
  fifteen lemmas each normalising one step is fifteen small obligations.
* **a per-step exit lemma for `noEarly`** — the generator ALREADY has the
  per-step pc lemmas (`S{k}_pc`) and ALREADY calls them, and the 15 branches
  still each re-run the thirty-lemma `simp only [_UNF]`. A
  `noExit{k} : ∀ (s : Arm64State), s.pc = entry → (S{k} s).pc ≠ exit` proved once
  per `k` with `simp [S{k}]; omega`, and `noEarly` by `rw`, turns fifteen
  unfoldings into none.

What was NOT tried, and why: `Arm64State.init` added to the unfold set (vF,
measured, no help), and removing `bv_decide` (vD, measured, no help). The first
is the one-line change the doc's own one-instruction recipe suggests and it does
not move the number, which is worth knowing before anyone tries it again.


## Three statements in the body below that are now stale, named so nobody
## re-derives them

1. **"Stashed: `formal/arm64_proof_gen.py` + `formal/build.py` — the emitter,
   the source-derived spec, and the three emitter bugs."** The emitter is
   LANDED: `_dylib_spec_lean` and `_dylib_contract_proof` are in
   `formal/arm64_proof_gen.py`, `formal/build.py:12652` calls the first and
   passes its answer to the second, and the generated file for `triple`
   contains `theorem spec : Refine.export_result_spec … (fun n => n * 3)` and
   `theorem caller …`. The three emitter bugs are in too — `S0` is defined,
   `st_i` is parenthesised, and `_dylib_spec_lean` returns `(fun n => …)`. So
   the "not emitted" table row above is history, and this paragraph is the
   only place the stash is still mentioned.
2. **"Refined diagnosis: it is a HEARTBEAT limit, not just the abstraction"** —
   superseded by measurement 1 above: the run is killed by `RLIMIT_CPU`, and the
   file's own budget is 20 M heartbeats, so the heartbeat is not the binding
   constraint and raising it cannot help.
3. **"the memory addresses are all constants … so the list of memory writes is
   short and closed"** — the addresses part is right and the list part is not:
   `Arm64State.mem` is a FUNCTION (`mem : Nat → UInt8`, initialised to
   `fun _ => 0`), not a list. The consequence is the same as far as this doc's
   argument goes — nothing has to be invented about the memory — but it is why
   the next step above is about the unfolding and not about the round trip.

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

## Refined diagnosis: it is a HEARTBEAT limit, not just the abstraction

[2] pointed out that this file already solves the "hand `bv_decide` an opaque
model term" trap at `formal/arm64_proof_gen.py:3885` ("unfolded before
bv_decide ... otherwise bv_decide reports spurious counterexamples"). I tested
whether that lead transfers, and it does — but only part of the way, and the
part it fixes changes what the blocker *is*.

**It transfers, and it is not a `BitVec` model that is needed.** On a
one-instruction goal:

    -- fails: abstracts arm64_reg 0 (arm64_set_reg 0 (init n 0) n) as opaque
    bv_decide

    -- closes the goal outright, `bv_decide` never runs
    simp only [arm64_reg, arm64_set_reg, Arm64State.init]

So the structure accessors are the *only* thing `bv_decide` chokes on, and
`simp only` on them is enough for a small goal. That kills my earlier framing:
this is not "you need a symbolic `BitVec 64` machine model" (a much larger
project), it is a normalisation problem.

**On the real 15-step composed effect, unfolding gets further and then dies on
heartbeats.** With the accessors *and* the whole `S`/`st` chain unfolded by
`simp only`, the `hreg` goal no longer reports a spurious counterexample — it
reaches

    error: (deterministic) timeout at `whnf`, maximum number of heartbeats
    (20000000) has been reached

So the honest statement of the blocker is: **the 15-step composed effect does
not reduce to a bitvector normal form within the heartbeat budget.** Two things
follow, and the first is a cheap experiment nobody should skip:

1. **Measure whether raising `maxHeartbeats` closes it.** The chain is 15 steps
   over a 6-entry memory list with constant addresses, so it is finite and in
   principle reducible; whether it is *tractable* is an empirical question I did
   not get to. This is the first thing to try, and it costs one number.
2. If it is not tractable, the fix is to make the effect *smaller* before
   evaluating it — discharge the memory round trip as its own `simp`-closed
   lemma (the write and the read-back, at constant addresses) and leave `bv_decide`
   a goal that is already one multiplication. That is a restructure of the
   emitter, not a new decision procedure.

The two remaining failures stand as recorded: `hx30` (same `bv_decide`
abstraction) and the pc discipline (`omega` on an unnormalised record).

Stashed: `formal/arm64_proof_gen.py` + `formal/build.py` — the emitter, the
source-derived spec, and the three emitter bugs. Not landable, because emitting
the contract makes the dylib `--formal` build fail. `git stash list` has it.

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
