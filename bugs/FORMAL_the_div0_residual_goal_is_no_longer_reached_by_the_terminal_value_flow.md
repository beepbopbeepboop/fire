# FORMAL: the div0 residual goal the zero-divisor class pins is no longer REACHED, so three `test_formal_call_proof_gen.py` rows are red on any tree with a built library

**Area:** `test_formal_call_proof_gen.py::TestTheZeroDivisorGuardAgainstLean`
and whatever in `formal/arm64_proof_gen.py` decides which goals the terminal
value flow reaches. **Status: OPEN, measured 2026-10-05 on the tree of this
merge. NOT reproduced on `master`, and the difference is the library, not the
code** — see §1. **Needs a Lean-backed read, so it is filed rather than
guessed at**; this session is a light worker and may not launch lean.

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
