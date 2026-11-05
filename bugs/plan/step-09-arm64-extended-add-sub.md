# plan/step-09: arm64 extended-register `ADD`/`SUB`/`CMP` (SP class)

**Source:** `bugs/FORMAL_arm64_instruction_coverage.md` §"The one class the
census cannot see".
**Master plan:** `doc/finish-formal.md` §"Step 09".

## Goal

Model the encoding class the census cannot see. A64's SP encoding for `Rn` is
the extended-register class (bits 28..24 = `01011`, **bit 21 set**), not the
shifted-register class (`0x8b000000`/`0xcb000000`) where every register-form
`ADD`/`SUB` row of the step table sits. Nothing this backend emits is in the
class, so no image or proof has hit it; the generator already *names* the class
(`ADD extended`/`SUB extended`/`SUBS/CMP extended`).

## What to add

The same four things a `TBZ`/`TBNZ` wiring costs, **scaffold only**:

- a model branch for the class (a mask/value pair) in `lib/ProofLib.lean`;
- a `work_step_*` theorem (may be `sorry`);
- an `hne_` fact in every earlier `work_step_*` theorem;
- the proof-table rows in `formal/arm64_proof_gen.py`.

Do **not** add a lowering: the doc says it is "not worth landing for an image no
emitter produces". Record that decision in the step.

## Structure-only rule

The naming already landed (`_unmodelled_instruction`). This step adds the model
structure with a counted hole; it does not add a lowering.

## Files

`lib/ProofLib.lean`, `formal/arm64_proof_gen.py`, ledger.

## Verification

`test_formal_proof_gaps.py`;
`test_formal_call_proof_gen.py::TestRegister31.test_the_sp_encodings_are_named_rather_than_left_unnamed`.

## Done when

- [ ] class modelled, holes counted
- [ ] naming test still passes
- [ ] step records that no lowering was added and why

## Dependencies

step-01.
