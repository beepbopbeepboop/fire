# plan/step-10: the `String` frame-vs-`char *` representation collision

**Source:** `bugs/FORMAL_string_value_model.md` (the 16 "a String receiver"
refusals; wave 8's closing section).
**Master plan:** `doc/finish-formal.md` §"Step 10".

## Goal

Resolve the representation collision. A `String` local must be *either* a
three-slot frame *or* a `char *`, and both readings are in force at once. The
returned half is lowered (wave 8); what remains is the constructor collision —
currently a SIGBUS turned into a refusal — plus the frame/field derivation and
the argument-position analysis the doc calls **D2's and D4's**.

## What to add

- **The frame/field derivation**: decide, per `String`-shaped local, which
  reading is in force, from a shared `formal/model/` table (not per backend).
  The string half is already stated by `model.string_has_static_storage()`.
- **The argument-position analysis**: which argument positions a callee can be
  trusted with. The load-bearing fact, per the doc: *a `char *` to
  `__TEXT,__text` has static storage duration, so the frame-escape rule is sound
  for a struct whose fields live in a frame and unsound as applied to it.*
- Replace the crash/refusal with the lowering for the shapes the derivation
  admits, and a refusal naming the collision for the rest.
- Diff against CPython on both backends for: the `String()`/`a._len_or_data = 5`
  / `a.size()` reproducer, the `lstrip`-returns-`char *` control, and a
  `String`-returned-from-a-function case.

## Structure-only rule

The Lean half is step-01's `Semantics`/`InImage` hole; do not attempt the
contract here. Deliverable is the Python model table plus the differential rows.

## Files

`formal/model/` (`frames`, `layout`, `strings`, `init`), `formal/build.py`,
`formal/arm64_codegen.py`, `formal/x86_64_codegen.py`, `test_formal_run.py`,
the string value-model tests.

## Verification

`test_formal_run.py`; the doc's reproducer on both backends; a counter that the
16-family count moved. `tools/formal_sweep.py` for the family delta.

## Done when

- [ ] reproducer answers CPython's value on both backends
- [ ] the 16-family count moves
- [ ] ONE shared table decides the reading
- [ ] remaining refusals name the collision

## Dependencies

step-01 (for the Lean contract hole only).
