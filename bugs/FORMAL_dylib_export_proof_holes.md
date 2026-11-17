# FORMAL: three dylib export proofs still admit `sorry` holes

The `formal-dylib` job (`test_formal_dylib.py`) reports `PASS=27 FAIL=3`. All
three failures are the same class -- a GENERATED proof admits `sorry`
declarations where the test requires a proved contract:

| failing check | what it reports |
|---|---|
| `several exports, and one with no derivable spec` | "the 3-export proof admits 2 hole(s); every export with a derived spec should have a PROVED contract" |
| `an export that binds a local still gets a proved contract` | "the proof admits 3 hole(s); both contracts should be proved, not named" |
| `a conditional value is not a branch` | "the proof admits 3 hole(s); the cset-bearing contract should be proved, so the only hole left is the branching export's named `_spec`" |

Measured 2026-11-16 on the uncapped run (`/usr/bin/time -l`, peak RSS 4.58 GB,
263 s). The `lib/` holes this job's `expect=` used to describe are GONE --
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
