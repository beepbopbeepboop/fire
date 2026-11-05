# plan/step-16: bare calls to templates with inferrable type arguments

**Source:** `bugs/FORMAL_known_limits.md` §1.2 (re-measured 2026-10-04; 123 bare
calls).
**Master plan:** `doc/finish-formal.md` §"Step 16".

## Goal

The export gate became per-edge and the family fell from 163 to 3 files; what is
behind it is **123 bare calls** to a template whose type arguments are inferrable
from the call's arguments:

| call | count | site |
|---|---|---|
| `FormatStruct(writer, "Allocation")` | 68 | `std/memory/alloc.mojo:450` |
| `dealloc(allocation^)` | 29 | `:99` |
| `is_negative(value)` | 13 | |
| `PhiloxRandom(seed)` | 6 | |
| `align_up(x)` | 3 | |

The current refusal ("spell it as `Name[<a type>](…)`") would send a reader to
edit working stdlib, because Mojo lets an inferrable type argument be omitted.

## What to add

Infer the type arguments at the call site from the argument shapes, feed the
existing monomorphizer, and publish the demanded instantiation as a real
boundary symbol. A bare call whose arguments do **not** determine the type
arguments is still refused by name.

## Structure-only rule

The demanded instantiation is part of the artifact's identity (the CAS key); do
not cache an inferred instantiation under the bare name. Scaffold any proof
obligation with `sorry`.

## Files

`formal/monomorph.py`, `formal/model/calls.py`, `formal/imports.py`,
`test_formal_monomorph.py`, `test_formal_imports.py`.

## Verification

`test_formal_monomorph.py`, `test_formal_imports.py` (the two surviving pins:
"a generic template is not exported under its base name" and "a bare call to a
template is refused by the export rule" must be reconciled with the new rule);
a sweep delta on the 123.

## Done when

- [ ] the five named families instantiate
- [ ] the export-gate family count moves off them
- [ ] an uninferrable bare call is still refused by name
- [ ] the two export pins updated deliberately

## Dependencies

step-15 (shares the monomorphizer).
