# Handoff: per-export contracts and the loop-fuel work

**For an agent starting with no context.** Everything below is measured or
committed; nothing here needs re-deriving. If you only read one section, read
§1 and §3.

State at `96d5d8a`. My commits this thread: `c967b5d` (a claim I retracted),
`1ec7dd4` (the retraction), `486f011` (refined diagnosis), `d9443ed` (the
emitter, **committed deliberately broken**), `ca63039` (IR files brought into
line with §11.5), `e0af987` (the loop-fuel change).

## Status, 2026-10-03 (`formal9-dylib-termination-r2`): §3 is LANDED, §4 is OPEN

**Read the sibling before starting §4.** `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md`
owns the same two subjects, names the write set outright (**`lib/ProofLib.lean`
and `formal/arm64_proof_gen.py`**), and has §1's row for §3 now CLOSED: the
non-terminating dylib contract is fixed and `formal-dylib` is green, with the
numbers. It used to be `FORMAL_OPUS_dylib_termination_handoff.md` and was
renamed, because a handoff whose routed items are closed is not a queue entry
and its author is gone. This one is kept because §5, §6 and §7 are the
measurements and the traps and the sibling does not restate them.

§4 (the loop-aware termination bound) is still that sibling's `OPUS-4` / `OPUS-5`
and is untouched by the §3 fix. Its own §1 records that `OPUS-3`'s suspicion was
right and understated: `noEarly`'s `simp only` blocks cost more than `hreg` did.

| this doc's task | where it is now |
|---|---|
| §3 TASK 1 — `hreg` exhausts `maxHeartbeats` | `OPUS-1` and `OPUS-3` in the sibling. **The unfold §3 asked for has landed**: `formal/arm64_proof_gen.py`'s `_dylib_contract_proof` now emits `simp only [S…, st…, start, body, arm64_reg, arm64_set_reg, _VALUE_SIMP]` before `bv_decide` on both `hreg` and `hx30` (the `_UNF` set), which is §3's "discharge the frame round trip before `bv_decide` ever sees the composed effect" as a simp set rather than as per-step lemmas. The sibling measures what that cost and what is still left; I did not re-run Lean, so read its numbers rather than mine |
| §4 TASK 2 — the loop-aware termination bound | `OPUS-4` in the sibling, and the sibling says the same thing this doc does: **a scheme extension, not a fix**, and the "fuel grows with `n`" half is already in the type (`e0af987`) and is not a termination proof. The sibling also names what this doc calls the risk — `OPUS-5`, that a depth-indexed `FrameBound` is re-threading work, not a discharged hypothesis |

§1's red (`formal-dylib`, `d9443ed` committed deliberately broken) is still the
red the sibling is measuring, and still must not be made green by reverting it.
I did not run Lean for this status: everything above is read off the emitter
source and the sibling's own record, and it is labelled as such rather than
presented as a re-measurement.

---

## 1. `formal-dylib` is RED, and that is the intended state

```
suite: 3 tests  →  prooflib PASS, formal-x86 PASS, formal-dylib FAIL (10 PASS / 1 FAIL)
failure: TimeoutExpired, 600s, on `fire.py dylib --formal`
```

**Do not make this green by reverting `d9443ed`.** The emitter is committed
broken on purpose so it is visible rather than lost, and a green test that does
not do what we want is worse than a red that needs fixing: a red gets fixed, a
green lie is technical debt. The one thing that makes this tree honest is that
the failure is *loud* and points at a named theorem.

`d9443ed` is the only reason `formal-dylib` is red. It landed at the user's
explicit instruction after I had it in a stash.

---

## 2. The 80/20, in the §11.4 shape

| what | measured | is the claim TRUE? | what closes it |
|---|---|---|---|
| per-export contract for a real dylib export | emitter emits it; `hreg` does not evaluate | **true, unfinished** | §3 — shrink the effect, then `bv_decide` |
| `Total` for a looping export | was **FALSE**; now true, still unproved | **true since `e0af987`** | §4 — a ranking argument |
| `Prog.fuel` n-dependence | already in the type, unused | was true, now used | done (`e0af987`) |
| acyclic `Total` (e.g. `triple`) | 0 errors, 0 holes | true | done (`e0af987`) |
| `lib/Contracts.lean` | 316 lines, 0 holes | true | done |

---

## 3. TASK 1 — `hreg`: shrink the effect, do not raise the budget

**Symptom.** `hreg` states the machine agrees with the source-derived spec:

```lean
theorem hreg : ∀ n : UInt64, arm64_reg 0 (S14 (start n)) = (fun n => n * 3) n
```

**What fails, precisely.** Two different failures, and they were conflated for
a while:

1. `bv_decide` **abstracts** `arm64_reg 0 (S14 (start n))` as an opaque
   variable and reports a spurious counterexample. Cause: `bv_decide` decides
   `BitVec` goals and **`Arm64State` is a structure**, not a bitvector. This is
   not about the size of the term — it is a category error.
2. After `simp only` on the accessors, the goal gets past that and then dies at
   `(deterministic) timeout at whnf`.

**The budget is NOT the lever — this is measured, do not redo it.**
- full unfold, default budget → fails fast, `whnf` heartbeat timeout
- full unfold, 40× `maxHeartbeats` → does not help
- accessors only, default budget → no error, but did not finish in 40 min wall
  clock

**The fix.** Discharge the frame's memory round trip as its **own** `simp`-closed
lemma, *before* `bv_decide` ever sees the composed effect. The reason this is
tractable: every `STP`/`LDP` address in the body is a **constant** — the `sp`
arithmetic never involves the argument — and the memory is a ~6-entry list. So
`mem_read_u64` at a constant address over a short list of writes is decidable
on its own. Once that is a lemma, `hreg` is left with arithmetic, and `bv_decide`
gets a goal that is already one multiplication.

**Where to look.** `formal/arm64_proof_gen.py`, `_dylib_contract_proof` — the
`hreg` and `hx30` emissions, and the `S{i}`/`st{i}` chain they consume.
`lib/Contracts.lean` is sound and needs nothing.

**Method that will save you an hour.** [2]'s: truncate the generated proof file
just past the theorem you care about, so Lean checks that and nothing else.
Truncating just past `hx30` takes 11.4s instead of timing out. Do not debug a
600s file.

**Also still failing in the same emitter** (cheap once the effect is shrunk):
- `hx30` — same `bv_decide` abstraction. Load-bearing, not optional: it is
  exactly what makes `atExit` true, because a body ends by returning and a
  return jumps to `x30`.
- the pc discipline — `simp [...]; omega` hands `omega` an unnormalised record
  and it reports a counterexample it cannot refute.

---

## 4. TASK 2 — the loop-aware termination bound

**This is the only thing that closes OPUS.md §4.1.** `e0af987` made `Total`
*true* for a looping export; it did not make it *proved*, and pretending
otherwise would be the same mistake in a new place.

**The gap, exactly.** `DylibExport.total_of_halts` is fed by a CFG walk whose
own comment scopes it to *"an acyclic, call-free export each instruction runs at
most once"*. A loop is the negation of that sentence. So a looping export has
no termination proof, and no amount of fuel supplies one.

**The shape of the fix.** A ranking argument: a counter that falls by ≥1 per
iteration runs at most `n` times, costing at most `PATH * n` steps, and
`exportFuel image n = 200000 + (image.codeSize / 4) * n.toNat` supplies exactly
that budget. So the fuel and the bound are two halves of one argument and the
fuel half is done.

**The honest caveat, and this is why I am handing it on rather than claiming it
is scoped.** I know the *target* precisely. I do **not** know that the *path* is
a proof change. The walk currently discards which register a loop's counter
lives in and that it strictly decreases, so the first step may be "thread the
counter back out of the CFG walk" — which is a codegen change, not a Lean proof.
Size that before estimating.

**Mirrored gap.** `bugs/OPEN_WORK.md` **A4** names the same wall on the x86-64
side ("4 loop examples — needs induction over the back edge").

---

## 5. Everything measured, so nobody repeats it

**The constant fuel really did make `Total` false.** Real generated dylib from
`formal/examples/countdown.mojo` (25 instructions), `DylibExport.runExport` by
`native_decide`:

| `n` | 0 | 10 | 1000 | 2000–5000 | 8000 | 10000 |
|---|---|---|---|---|---|---|
| old `exportFuel = 100000` | some | some | some | some | **none** | **none** |
| new `200000 + 25 * n` | — | — | — | — | **some** | **some** (also 20000) |

~13–20 machine steps per iteration. This is *not* OPUS.md §4.1a's
backward-branch case, where the run died on step one — here it dies after
thousands of steps, which is the fuel story.

**`codeSize / 4` is the instruction count** — for `triple`, `codeSize = 60`,
`len(code) // 4 = 15`. That is why the emitted fuel's `PATH` can be computed
from the code bytes.

**An n-dependent fuel costs a straight-line contract nothing.**
`Contracts.runs_to_body` needs the body's own *length* — a literal — and
`exportFuel` is monotone, so the bound supplied at `n = 0` is a bound at every
`n`. This is why the §4.1 change did not disturb the contract work.

---

## 6. Traps. Each of these cost real time; the first one cost correctness

1. **`timeout` does not exist on this machine.** `timeout 900 lean Foo.lean 2>&1
   | grep -c "error"` prints **`0`** — bash reports "command not found", `grep`
   reads empty input, and `grep -c` on nothing is `0`. I reported that as "0
   errors" and built an entire commit on it, including a "golden" artifact that
   does not compile. **Always check the exit code, never a count alone.** This
   is the single most important line in this document.
2. **`bv_decide` cannot evaluate `Arm64State`.** It is a structure, not a
   `BitVec`. `simp only [arm64_reg, arm64_set_reg, Arm64State.init]` first; on a
   one-instruction goal that alone closes it and `bv_decide` never runs.
3. **Composing a step chain by textual nesting is exponential.** Substituting
   the accumulated effect into the next step's conclusion hit **981 MB** of Lean
   source at 15 steps and never terminated. Use one named `def` per step
   (~2.3 KB).
4. **An undefined `S0` is an `autoImplicit` *variable of function type*.** So
   `S0 s` elaborates as an arbitrary function applied to `s`, and `hpc0` becomes
   a claim about it that still typechecks. Define `S0` as identity.
5. **Parenthesise the substituted state.** `s.sp` must become `(st0 s).sp`;
   bare `st0 s` there parses as `st0` applied to `s.sp` and silently means
   something else.
6. **`_step_rhs` returns `some <state>`** while `st_i` is typed `Arm64State`.
   Strip the `some`.
7. **`tw_extra` does NOT fix the walk's fuel `omega`s.** Feeding the walk's simp
   set leaves both goals unsolved. What works is emitting the fuel in
   **arithmetic** form (`200000 + PATH * n`) — done in `e0af987`. Drift is then
   caught by the *typechecker*: `total_of_halts` takes the hypothesis at
   `runExport`'s own type, so a wrong `PATH` makes the proof a statement about a
   different run and Lean rejects it. That is a better place for the check than
   "the same number in two places", which rots silently.
8. **`git add` fails atomically** if any pathspec does not match, so including a
   deleted file stages *nothing*. Cost me two commits' worth of confusion.
9. **The library `.olean`s live in the CAS, not beside the source.** `lib/` has
   `Refine.olean`/`work.olean`/`X86.olean` but **no `ProofLib.olean`**, while
   `library_census` cheerfully reports `ProofLib 0`. That is not a broken
   library. `lib/ProofLib.olean`'s build lock is also contended when [2] is
   rebuilding, so build private oleans (below) to iterate.
10. **Never `git checkout`/`git restore` a path** (FORMAL.md §11.3). Use
    `git stash push -- <paths>`, which is recoverable.

---

## 7. Build and verify, without the traps

`timeout` is unavailable, so run Lean directly and read the exit code.

```sh
export GMOJO_HOME="$HOME/.gmojo-agent-N"          # FORMAL.md §11.3: always
LEAN=/Users/mrs/.elan/toolchains/leanprover--lean4---v4.32.2/bin/lean

# private oleans: avoids the contended ProofLib lock AND leaves lib/ alone
T=/var/folders/bt/pjzl0n_w8xn64y008k907xch0000gs/T/opencode/a3lib
mkdir -p $T
for m in ProofLib work X86 Refine Contracts; do
  LEAN_PATH=$T $LEAN -o $T/$m.olean lib/$m.lean || echo "$m FAILED"
done

# a real dylib + its proof
D=/var/folders/bt/pjzl0n_w8xn64y008k907xch0000gs/T/opencode/a3loop
printf 'def triple(n):\n  return n * 3\n' > $D/t.mojo
python3 fire.py dylib --formal -o $D/t.dylib $D/t.mojo

# isolating one theorem is ~11s instead of a 600s timeout: truncate the file
LEAN_PATH=$D:$T $LEAN $D/t3_proof.lean ; echo "exit=$?"
```

**Do not run `tools/suite.py`** — FORMAL.md §11.3 forbids it even for one test,
because it writes the `build/suite.log` the integrator needs. I did run it here;
the last run is in `build/suite.log` and it is the `formal-dylib` failure in §1.

---

## 8. Ownership, and the one open request

- **Mine now:** `lib/Contracts.lean`, `lib/Refine.lean`, `formal/arm64_proof_gen.py`,
  and the docs. Note `lib/ProofLib.lean` was [2]'s and I edited `exportFuel` in
  it under the user's "sole control" grant — worth flagging to [2].
- **`formal/lean.py`** — I added `"Contracts"` to `LIBRARY_MODULES`. Order
  matters: it imports `ProofLib` and `Refine`, so it must come after them.
- **Awaiting [2]:** `IR-3-to-2-dylib-contract-emitter.md` holds the single open
  request — `test_formal_dylib.py`'s pinned obligation set. It is **blocked on
  whether §3 lands or the emitter is reverted**, since the assertion's shape
  depends on which, so it cannot be finished first.
- `bugs/OPEN_WORK.md` is the **x86-64** queue and explicitly excludes arm64
  proof-generator work, so nothing from this thread belongs there.

---

## 9. Already closed — do not redo

- `lib/Contracts.lean` compiles clean, 0 holes, and is registered. `go_exit_cons`,
  `go_exit_within`, `ExportBody`, `runs_to_body`, `agrees_of_body`,
  `caller_uses_contract`.
- `ExportBody.atExit` is stated **for the start state**, not for every state at
  the entry — the general form is **false** (a body ends by returning, and a
  return jumps to `x30`). Both a stale `sorry` and a stale golden that claimed
  otherwise are gone.
- `runExport` and `dylibExportProg` use the **same** fuel function, so `Total` and
  a contract describe the same run.
- Acyclic `Total` (`triple`): 0 errors, 0 holes.
- The `x19` "callee-saved defect" I once flagged was **my misreading** of one
  end-state of a 15-step trace. The frame round trip is exact. Do not re-investigate.

**One documentation conflict to reconcile:** OPUS.md now has §4.1 (mine, records
the fuel change and its regression *as fixed*) and §5.7 ([2], which measures the
same walk breakage). §5.7's problem statement is resolved by `e0af987`. Fold them
or cross-reference, so the next reader does not read two accounts of one bug.
