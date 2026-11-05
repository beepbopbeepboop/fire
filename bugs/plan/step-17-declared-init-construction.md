# plan/step-17: declared `__init__` / field-filling construction

**Source:** `bugs/FORMAL_known_limits.md` §6.3 (lever #3, 20 files) and §6.1
(`std/builtin/builtin_slice.mojo`, `Slice` with 3 arguments).
**Master plan:** `doc/finish-formal.md` §"Step 17".

## Goal

The cheapest capability in the known-limits residue. A constructor with a
declared `__init__` — `Slice(...)` with 3 arguments — is refused because the
path cannot run a user-defined `__init__`, and the doc calls this "the best
worded refusal in the residue". Cost: days, self-contained, nothing about it
needs a new value model.

## What to add

- Field-filling construction for the shapes that admit it: a declared `__init__`
  whose body assigns fields. Either run that body or fill the fields directly.
- An exact refusal for the shapes that genuinely need to execute arbitrary code.
- The constructor machinery already exists in `formal/model/init.py`
  (`struct_fields_written_outside_init`, `_init_type_position_names`,
  `construction_keyword_refusal`, `struct_construction_plan`) — reuse it.

## Structure-only rule

No new value model. A struct whose `__init__` does something the path cannot do
is refused, not approximated. Scaffold proof obligations with `sorry`.

## Files

`formal/model/init.py`, `formal/model/structs.py`, both codegens,
`test_struct_formal.py`.

## Verification

`test_struct_formal.py`; a differential row for a `Slice`-shaped construction on
both backends.

## Done when

- [ ] `Slice.__init__`-shaped construction builds and answers CPython on both
      backends
- [ ] remaining refusals name the construct
- [ ] no regression in the existing constructor tests

## Dependencies

step-01 (holes only). Independent.
