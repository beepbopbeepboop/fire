# plan/step-15: monomorphization residuals

**Source:** `bugs/FORMAL_known_limits.md` §1.2 (the 2026-10-03 re-measurement).
**Master plan:** `doc/finish-formal.md` §"Step 15".

## Goal

Stage 5 monomorphization landed for the formal dylib path (`formal/monomorph.py`,
`doc/ABI.md` §Generics amended). Four remainders are listed with the reason each
is not a third line of the same commit: a type argument in an **annotation
position**, a **dotted application** `mod.G[T]()`, a **comptime specialization
of an imported template**, and the **trait-bound check**. Their single home is
`FORMAL_generic_monomorph_scope.md`, which is no longer in `bugs/`; this step
re-creates its inventory or carries the four rows here.

## What to add

One row per remainder: the construct, the mangling it needs, the CAS keying, and
the export entry. Each remainder is either instantiated (with a differential row)
or refused by name with a reason true of the construct.

## Structure-only rule

`widen[Int](5)` and `Pair[Int]()` already build and are pinned by
`test_formal_monomorph.py` (11 cases). Do not regress them. A remainder that
cannot be instantiated yet gets a refusal, not a guessed instantiation.

## Files

`formal/monomorph.py`, `formal/imports.py`, `formal/model/calls.py`,
`test_formal_monomorph.py`, `test_formal_imports.py`, `doc/ABI.md`.

## Verification

`test_formal_monomorph.py`; a sweep delta on the affected family.

## Done when

- [ ] each of the four remainders instantiated or refused by name
- [ ] the 11 existing monomorph cases stay green
- [ ] `doc/ABI.md` §Generics states the final contract

## Dependencies

step-01 (holes only). Independent of the others.
