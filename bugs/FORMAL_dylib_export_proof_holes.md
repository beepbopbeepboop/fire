# FORMAL: three dylib export proofs still admit `sorry` holes

The `formal-dylib` job (`test_formal_dylib.py`) reports `PASS=27 FAIL=3`. All
three failures are the same class -- a GENERATED proof admits `sorry`
declarations where the test requires a proved contract:

| failing check | what it reports |
|---|---|
| `several exports, and one with no derivable spec` | "the 3-export proof admits 2 hole(s); every export with a derived spec should have a PROVED contract" |
| `an export that binds a local still gets a proved contract` | "the proof admits 3 hole(s); both contracts should be proved, not named" |
| `a conditional value is not a branch` | "the proof admits 3 hole(s); the cset-bearing contract should be proved, so the only hole left is the branching export's named `_spec`" |

Each check asserts an exact hole COUNT, so the delta is not "some holes" but a
specific number:

* `a conditional value is not a branch` asserts `n == 1` -- "the cset-bearing
  contract should be proved, so the only hole left is the branching export's
  named `_spec`" -- and gets **3**. Its own docstring says the cset block must
  now get a PROVED contract (`Block` + `BlockCert` + `agrees_of_body`) and that
  a real `b.cond` block still gets the named `_spec`, so the two extra holes are
  the finding.
* `an export that binds a local still gets a proved contract` -- "both
  contracts should be proved, not named", 3 holes.
* `several exports, and one with no derivable spec` -- "every export with a
  derived spec should have a PROVED contract", 2 holes.

Measured 2026-11-16 on the uncapped run (`/usr/bin/time -l`, peak RSS 4.58 GB,
263 s).

## The three declarations, named (wakeup 57)

Ran `lean` directly on the generated proof (the census only counts; `_run_lean`
returns `detail=""` on success, so the names are not captured anywhere). Three
warnings, and the declarations they attach to:

| line | declaration |
|---|---|
| 3652 | `theorem dylib_export_0_csetval_semantics_total : DylibExport.Total dylib_image dylib_export_0_csetval` |
| 6203 | `theorem dylib_export_1_branched_semantics_total : DylibExport.Total dylib_image dylib_export_1_branched` |
| 6222 | `theorem dylib_export_1_branched_spec : Refine.export_result_spec_under ...` |

So exactly ONE of the three is the obligation the test EXPECTS
(`branched_spec` -- "the only hole left is the branching export's named
`_spec`"), and the two extras are the **`DylibExport.Total` termination
theorems** for both exports. The generated comment above them says why:
"the overflow trap is such a path, so termination for every argument is not a
fact of the model" -- i.e. the `Total` predicate cannot be discharged while an
overflow-trapping path has no step.

**Correction to the marker re-point.** The original `expect=` reason -- "the
hole-count checks on the overflow-trapping exports, whose termination
obligations an exit svc keeps named" -- was substantially RIGHT: these ARE the
overflow-trapping exports' termination obligations. What was wrong was only the
pointer (the svc doc does not describe them). Re-pointed to this doc for the
names; the subject matter is the same.

## Why the walk refuses (the generator's own words)

`{ident}_semantics_total` is PROVED "where the export's CFG allows it", by a
constant-fuel CFG walk in halt-only mode, and left as one named obligation
otherwise (`formal/arm64_proof_gen.py:16945`). The emitted comment on the
`csetval` hole says which side of that line it fell on:

    OBLIGATION, not proved: this export's run terminates for every argument.
    The constant-fuel CFG walk does not cover it: its [overflow trap] is such a
    path, so termination for every argument is not a fact of the model.
    The walk's refusal, so the reason is not swallowed:
    universal theorem: CFG decomposition unsupported for this function shape,
    and every instruction in its own code has a step, so the cause is not an
    unmodelled word: the walk returns None for a shape with no `RET`, an empty
    block runs certificate, or a constant-fuel caller whose budget is below the
    instruction count

So the two `Total` holes are the walk returning `None` for these two shapes --
the `cset` makes `csetval`'s CFG a shape the constant-fuel walk does not cover.
The fix is in the WALK's coverage (or in spelling the refusal as a stated
assumption the way `svc_write_assumed` is), not in the two theorems.

### The refusal message does not name the site, though it says it does

`_cfg_decomposition_refusal`'s docstring promises "this names the one site in
THIS export ... so 'no proof because a dynamic svc at 0x...' is distinguishable
from 'no proof because a loop'". Called directly on both exports, it returns
the SAME generic sentence for each:

    universal theorem: CFG decomposition unsupported for this function shape,
    and every instruction in its own code has a step, so the cause is not an
    unmodelled word: the walk returns None for a shape with no `RET`, an empty
    block runs certificate, or a constant-fuel caller whose budget is below the
    instruction count

So neither of its specific branches (an unmodelled word, or a classified `svc`)
fires for these two, and the reader is left with three candidate classes and no
way to pick. Naming the actual `None` return needs the walk itself
instrumented -- which of the three it is for `csetval` (the `cset` suggests the
block partition, not the fuel) is unmeasured.

**Reproduced in isolation, and the instrument's limit.** Rebuilding just the
`csetval` program and running `formal.lean.proof_census` on the generated proof
gives `n_sorries = 3`, `lib_sorries = 0` -- the count is exact and the library
is clean, so all three are in the GENERATED file. What the census does NOT give
is the declaration names: `Census.detail` is the per-module library table, and
the generated file's own warnings are only parsed on an UNCACHED Lean run (on a
cache hit `detail` carries nothing, which `check_proof_cached`'s own docstring
records). Naming the three therefore needs one uncached `lean` invocation on
that proof -- the missing piece for a fix, not a missing measurement of the
count. The `lib/` holes this job's `expect=` used to describe are GONE --
`no module under lib/ admits a sorry or an admit` PASSES, and the remaining
`library: 1 declaration(s) ... admitted a sorry` is `scaffold_canary`, which is
recorded as vacuous. So these three are in the GENERATED proof, not the
library.

## Why the marker mis-pointed

`tools/suite.py`'s `expect=` said "the hole-count checks on the
overflow-trapping exports, whose termination obligations an exit svc keeps
named" and pointed at `bugs/hard/FORMAL_svc_exit_handling_incomplete.md`. The
count (3) is right; the reason is not -- none of these three checks is a
hole-count check on the overflow-trapping exports, and none is described in
that doc. Re-pointed here.

## Done when

`test_formal_dylib.py` reports 0 failures -- each of the three generated
proofs discharges its `sorry` (or the check is rewritten to say why a named
`_spec` is the intended outcome, which is what the third check's own wording
already half-claims).
