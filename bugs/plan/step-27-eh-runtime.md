# plan/step-27: EH runtime / `try`-handler arms (scaffold)

**Source:** `bugs/FORMAL_no_exceptions.md` item 2;
`FORMAL_a_try_handler_arm_is_still_never_emitted.md` (no longer in `bugs/`, the
sizing).
**Master plan:** `doc/finish-formal.md` §"Step 27".

## Goal

A `raise` is a termination; there is no unwinder, the exception object is never
constructed, and a `try`/`except` whose arm has a body is refused by name. The
doc's arithmetic: an exception object is more than one 64-bit word, so a real EH
runtime is "a real programme, not an afternoon". The sizing doc is blunt: the
hand-dispatchable slice moves **0 files**, because every arm whose body could be
dispatched wraps a CALL, and a call's raise is the callee's to decide.

**This is a scaffold step, not an unwinder.**

## What to add (scaffold only)

- The *structure* of an EH runtime: the landing-pad table, the personality-
  routine shape per catch type, and a place for the exception object to live.
- A semantic-model translation for `TryStmt` in `formal/arm64_proof_gen.py` —
  today the model has **none**, so every program with a `try` is refused by
  `--formal` regardless.
- The model arms and their theorems stated with `sorry` (ledger).
- The two questions with no answer in the code — superclass matching, and what
  `except A as e` binds — recorded as open, not guessed.

## Structure-only rule

Do not attempt a full unwinder. The deliverable is the shape plus counted holes,
so a later step can fill them. The existing uncaught-`raise` behaviour
(`test_formal_exceptions.py`, 331 checks) must not change.

## Files

`formal/arm64_codegen.py`, `formal/x86_64_codegen.py`, `formal/model/`,
`formal/arm64_proof_gen.py`, `lib/ProofLib.lean`, `test_formal_exceptions.py`,
ledger.

## Verification

`test_formal_exceptions.py` (all rows still pass);
`test_formal_proof_gaps.py`; a `try` program now generates (rather than refusing
to generate) a proof statement, with a hole.

## Done when

- [ ] `TryStmt` has a model translation (holes counted)
- [ ] landing-pad/personality structure exists
- [ ] the two open questions are recorded
- [ ] `test_formal_exceptions.py` stays green

## Dependencies

step-01, step-11/step-25 (the exception object's storage is the same value-model
question).
