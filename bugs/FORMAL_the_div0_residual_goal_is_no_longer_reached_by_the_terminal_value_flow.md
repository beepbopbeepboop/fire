# FORMAL: the div0 residual goal the zero-divisor class pins is no longer REACHED, so three `test_formal_call_proof_gen.py` rows are red on any tree with a built library

**Area:** `test_formal_call_proof_gen.py::TestTheZeroDivisorGuardAgainstLean`
and whatever in `formal/arm64_proof_gen.py` decides which goals the terminal
value flow reaches. **Status: OPEN and now BLOCKED, re-measured 2026-10-08 on
this tree (library built, all seven `.olean` current).** The class no longer
reaches the three red rows at all: `setUpClass` calls `_symbolic_divisor_proof`,
whose `compile_formal(..., prove=True)` now RAISES

```
universal theorem: 2 calls this walk cannot follow
  (0x100000424 -> 0x10000088c (opaque), 0x100000514 -> 0x100000880 (opaque)),
every one of them OUT OF THE IMAGE, and ONE halt address cannot discharge them.
```

so there is no generated `q_compiles_correctly_universal` body to read. That is
`bugs/FORMAL_arm64_the_compiler_trap_recording_is_lost_and_the_stack_guards_
getrlimit_is_a_program_call.md`'s subject on the merged tree (the branch's
branch named the same subject `FORMAL_the_stack_guards_getrlimit_is_counted_as_
a_program_call.md`, which master deleted as fixed in `23350e6e`); the guard's
`getrlimit` in every arm64 prologue is counted as a program
CALL by `_calls`/`_opaque`, and it must be fixed before this document's step 1
can run at all — **this doc's Lean read is downstream of that one.** §1.1 has
the measurement and the one check that shows it is not this document's own
cause. (Previously: OPEN, measured 2026-10-05, three `FAIL`s on a tree with a
built library; `master` is green only because `setUpClass` skips without one.)

**Status 2026-10-09 (this worktree): the route is now doubly gone, and the
class has been taught to say so by name.** Re-measured on this tree with
`lib/*.olean` materialised from the cas (0.0 GB / seconds, not a build):
`_symbolic_divisor_proof` **refuses at GENERATION** — `FormalBuildError /
NotImplementedError: universal theorem: 2 calls this walk cannot follow
(0x100000424 -> 0x100000890 (opaque), 0x100000518 -> 0x100000884 (opaque))`.
The two opaque calls are the compiler's own: the stack-floor guard's
`getrlimit` (the `every_function` image rule puts it in `q`'s prologue,
`model.stack_floor_guarded_names`) and the div0 arm's `fflush`. So §3's
"warnings and no goals" hypothesis is superseded on this tree before Lean even
runs — there is no proof file to read. Master is in the same state (identical
_refusal, `formal-call-proofgen` recorded as 9/175 red in `tools/suite.py`).

The measurement-class repair landed here as a port of master `e06800ff`:
`setUpClass` records per-spelling why the mechanism did not fire (`cls.blind`)
and `test_the_measurement_class_can_still_see_what_it_measures` fails on it by
name, so the three rows now report the refusal rather than "the residual
moved"; see `bugs/FORMAL_the_div0_guard_measurement_class_traces_nothing_
any_more.md`'s 2026-10-07 Status. The fix itself is unchanged and still not
this lane's: the emitter regression (compiler calls read as program calls
because arm64 `compiler_traps` is published and empty) and the conditional-halt
walk gap (`bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_
path.md`) both have to land before `a // b` again reaches a terminal value
flow, and neither is a `test_formal_*` change.

**merged 2026-10-13 (merging `work/formal199-docs`): re-measured on the merged
tree, the generation refusal of both dated records above is gone, and the shape
the class meets is new.** The probe `setUpClass` performs — `compile_formal(
symdiv.mojo, arch="arm64", prove=True, check=False)` on `def q(a, b): return
a // b` — SUCCEEDS here (generation-only, no Lean): the "2 calls this walk
cannot follow" rejection of the 2026-10-08 and 2026-10-09 records is no longer
raised, because the guard's `getrlimit` is no longer a prologue `BL` the walk
counts (`70b76755`'s startup stub, in HEAD — `bugs/FORMAL_arm64_the_
universal_theorem_cannot_follow_a_call_into_the_same_image.md`'s merged
2026-10-13 note re-measures the same subtraction). What moved is the shape: the
file the probe writes contains NO `q_compiles_correctly_universal`. In its
place the generator emits `q_reaches_call_at_0x100000504` — the reachability
theorem — with a comment that names the boundary: "the function calls out of
the image at 0x100000504, so the model cannot execute the call and
`arm64_exec_go` stops there … A caller asked for `q_compiles_correctly_
universal`, whose proposition is about what the function RETURNS, and that
theorem is NOT emitted", and "Two out-of-image calls are REFUSED by name
(`_cfg_decomposition_refusal`) rather than substituted, because the walk halts
on one address only". So on a tree with a built library the class neither
ERRORS in `setUpClass` (the 2026-10-08 state) nor reaches the div0 residual
(the 2026-10-05 state): it partitions a file that has no value theorem to read
and reports the mechanism blind by name, as the 2026-10-09 repair taught it. In
THIS environment the class skips (no `lib/ProofLib.olean`), which is the honest
report of a six-case class whose subject needs a 52 MB library. The branch
lands no code on the merged tree.

## 0. Re-measured 2026-10-08: the failure MOVED, and it is now EARLIER than §3 describes

The class no longer reaches the residual at all. `_symbolic_divisor_proof`
(`test_formal_call_proof_gen.py:5267`) calls
`fb.compile_formal(symdiv.mojo, prove=True)`, and on this tree that now RAISES
before any Lean file is written:

```console
$ python3 tools/memslot.py --gb 8 --label div0 -- \
    python3 test_formal_call_proof_gen.py TestTheZeroDivisorGuardAgainstLean -v
setUpClass ... ERROR
formal.build.FormalBuildError: no proof was generated: …
  NotImplementedError: universal theorem: 2 calls this walk cannot follow
    (0x100000424 -> 0x10000088c (opaque), 0x100000514 -> 0x100000880 (opaque)),
    every one of them OUT OF THE IMAGE, and ONE halt address cannot discharge
    them …
```

So the class is an ERROR in `setUpClass`, not the three residual failures §1/§3
record — the generator refuses `def q(a, b): return a // b`'s universal theorem
before the div0 arm is emitted at all. **The question §5 poses ("does the div0
arm still contribute a goal?") is therefore not yet askable on this tree**, and
the answer is upstream: the walk now cannot follow two out-of-image calls in the
program, which is the subject of
`bugs/FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image.md`
and its siblings (`formal/arm64_proof_gen.py`, another claim's write set). Until
that walk can follow the calls, this class cannot measure the residual, and the
honest status of the doc's own subject is BLOCKED behind it rather than red on
its own terms. The library is not the variable here — the refusal is at
generation, before Lean — so a rebuild does not change this.

## 1. What I ran, and why `master` is green

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py
Ran 114 tests in 95.975s
FAILED (failures=3)
  FAIL: test_the_false_goal_survives_the_documented_next_step (spelling='as_emitted')
  FAIL: test_the_false_goal_survives_the_documented_next_step (spelling='doc_next_step')
  FAIL: test_the_residual_is_the_same_with_and_without_the_branch_fact

$ (in a `git archive master` tree) python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_call_proof_gen.py
Ran 107 tests in 19.294s
OK (skipped=6)
```

`master` is green because the whole class **skips** there: `setUpClass` raises
`SkipTest` unless `lib/ProofLib.olean` exists, and a `git archive` of a commit
carries no build artifact. This worktree has one, built during this session's
own verification runs:

```console
$ ls -la lib/*.olean
-rw-r--r--  1 mrs  staff  52008720 Oct  5 05:04 lib/ProofLib.olean
-rw-r--r--  1 mrs  staff   8729400 Oct  5 05:04 lib/X86.olean
…   (all six, 05:04-05:05)
```

So the honest statement is: **this red appears on any tree where the library has
been built**, and it is invisible everywhere else. That is itself a fact about
the class worth recording — a six-case class whose entire subject is
unobservable without a 52 MB artifact, and which therefore reports green in
every context that does not build one.

## 1.1 Re-measured 2026-10-08: the class now ERRORS in `setUpClass`, and it is not this doc's cause

```console
$ ls lib/*.olean          # all seven present and current (built this tree)
$ python3 tools/memslot.py --gb 8 --label div0 -- \
    python3 test_formal_call_proof_gen.py TestTheZeroDivisorGuardAgainstLean
setUpClass ... ERROR
NotImplementedError: universal theorem: 2 calls this walk cannot follow
  (0x100000424 -> 0x10000088c (opaque), 0x100000514 -> 0x100000880 (opaque)),
  every one of them OUT OF THE IMAGE, and ONE halt address cannot discharge them.
Ran 0 tests ...
```

The addresses move when the emitter changes, so the two calls are the guard's
`getrlimit` (emitted in every arm64 prologue, `_emit_stack_floor_guard`) and the
program's own call; on the merged tree that subject lives in
`bugs/FORMAL_arm64_the_compiler_trap_recording_is_lost_and_the_stack_guards_
getrlimit_is_a_program_call.md` (the branch's name for it,
`FORMAL_the_stack_guards_getrlimit_is_counted_as_a_program_call.md`, was deleted
as fixed on master in `23350e6e`), and it has the reproduction of this exact
refusal and the two candidate fixes. **The check that it is not caused by this
document's subject:** the same
error appears when the only recent arm64 change (the guard's `LDR X13, [scratch]`
read, `work/formal199-docs`) is reverse-applied with `git apply -R` — the
addresses shift (`…0x88c` → `…0x894`) and the error class is identical, so the
walk's opaque-call rule, not the guard arithmetic and not the div0 residual, is
what stops the read.

**So the next step for THIS doc changes:** it is downstream of
`FORMAL_arm64_the_compiler_trap_recording_is_lost_and_the_stack_guards_
getrlimit_is_a_program_call.md` (the branch's own name for that subject,
`FORMAL_the_stack_guards_getrlimit_is_counted_as_a_program_call.md`, was deleted
as fixed on master in `23350e6e`). Until that
one teaches the walk to step a returning extern call (its option 1) and subtracts
the compiler's calls from `_calls`/`_opaque`, `_symbolic_divisor_proof` cannot
produce the theorem this document exists to read, and the "goal CLOSED vs walk
no longer REACHES it" question stays unanswerable.

## 2. The library is CURRENT, so the change is real

Checked through the module's own currency predicate, not by mtime:

```console
$ python3 -   # formal.lean._library_is_current(src, olean, olean + '.srcsha256',
                #                          _effective_digest(stem, lib_dir))
  IEEE754: current=True  effective_digest=65556aa073490686
  ProofLib: current=True  effective_digest=58f18209a7fe3001
  X86:      current=True  effective_digest=9db31c468b73bf37
  work:     current=True  effective_digest=6ca6a086469b1ef
  Refine:   current=True  effective_digest=c7adf0121b95f098
  Contracts:current=True  effective_digest=f3b350683ca18d07
```

All six, including the EFFECTIVE digest (a module's own bytes and every library
module it imports, transitively). So the `.olean` was built from exactly this
`lib/`, and the residual the class reads is what this tree produces.

## 3. What it sees

```console
AssertionError: '⊢ 1 =' not found in 'div0_as_emitted.lean:29:8: warning:
declaration uses `sorry`
div0_as_emitted.lean:34:8: warning: declaration uses `sorry'
…
div0_as_emitted.lean:95:8: warning: declaration uses `sorry'
: as_emitted: the div0 path's residual is no longer the `1 = …` goal — fdiv64's
div0 arm or the div0 path's exit status may have been corrected, which is the
fix this doc wants
```

**The output is warnings and no goals at all.** That is the specific thing worth
reading, and the class's own message is a guess between two causes that this
output does not distinguish:

* **the goal CLOSED** — the fix landed; or
* **the walk no longer REACHES it** — `trace_state` never fires because the
  terminal value flow admits fewer goals.

`fdiv64` is byte-identical to `master`, so the cause is not the one the message
names first:

```console
$ diff <(git show master:lib/ProofLib.lean | sed -n '/theorem fdiv64/,/^$/p') \
       <(sed -n '/theorem fdiv64/,/^$/p' lib/ProofLib.lean)
IDENTICAL
```

`fdiv64`'s div0 arm is still `if b = 0 then 0 else …`, so the **false** theorem
this class exists to expose is still false. What moved is the walk.

## 4. The most likely cause, and it is a merge artifact

`lib/ProofLib.lean` gained **1442 lines** in this merge, all from
`work/formal28-2` (arm64's twelve narrower/unscaled memory forms and its two
flag-setting compares). `git diff --stat master..HEAD -- lib/` is the whole
story:

```
lib/ProofLib.lean | 1477 +++++++++++++++++++++++++++++++-
```

The class's whole mechanism is reading the terminal value flow's residual
(`all_goals (first | done | (trace_state; sorry))`) and asserting the div0 path
contributes a `1 = …` goal. **833 new `bv_decide` sites came in with those 1442
lines** (recorded in `test_formal_admitted.py`'s `LIBRARY_TRUST` and in
`FORMAL.md` §7 row 10 by this merge's earlier commit), and the closure census's
`ProofLib` row moved 297/46 → 311/60. So the module this class leans on changed
substantially, and the div0 walk's admissions are the most likely thing to have
moved with it.

That is a **hypothesis, not a measurement** — which is why this is filed rather
than fixed.

## 5. Exact next step

Needs Lean, so it is the integrator's (`make bootstrap` and the `prooflib` dep
rebuild the library from the current tree; a light worker may not do it).

1. Rebuild the library from the current tree, then re-run the class and read the
   div0 theorem's own body rather than its warnings:

   ```console
   $ python3 tools/suite.py prooflib
   $ python3 tools/memslot.py --gb 8 --label div0 -- python3 test_formal_call_proof_gen.py \
       TestTheZeroDivisorGuardAgainstLean -v
   ```

2. Write the generated `div0_as_emitted.lean` to a scratch path and read
   `theorem q_compiles_correctly_universal`'s terminal `simp`/`trace_state`
   block. The question is one line: **does the div0 arm still contribute a
   goal at all, and if not, which admission now consumes it?**
3. If the goal is merely *unreached*, the fix belongs in
   `formal/arm64_proof_gen.py`'s terminal value flow, and the class is RIGHT —
   it is doing the job its docstring describes ("if `fdiv64`'s div0 arm is ever
   corrected, **or the walk starts to model the div0 arm as the divergence it
   is**, this pin fails and says so"). In that case this doc becomes
   `bugs/FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open.md`'s
   next step, re-measured, and that doc's §"Status" is what moves.
4. If the goal CLOSED, then the false theorem is no longer being stated and
   `formal/model.py`'s div0 handling changed somewhere; find that, because a
   `bv_decide` site set that grew by 833 is a plausible place for a
   `decide`/`rfl` to start discharging something it should not.

Whatever the answer, the class should stop SKIPPING silently when the library is
absent and say so on the way out — a six-case class that is unobservable in
every context that does not build 52 MB is a coverage hole shaped exactly like
the "declared but never called" ones `test_suite.py` now has checks for.

## 6. Why it is not fixed here

Three reasons, in order of weight:

* it needs `lean` on a 52 MB library, and this session is a light worker whose
  rules forbid launching lean;
* `formal/arm64_proof_gen.py` and the div0 doc are another lane's
  (`formal28-2` / `formal28-6-r2` hold the arm64 proof-gap claims, and
  `bugs/FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open.md` is
  the `formal19-3-r2` area);
* and the one fact I would need to distinguish "closed" from "unreached" is the
  generated theorem's body, which is a Lean read.
