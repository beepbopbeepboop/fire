# plan/step-26: one discoverable host-module failure convention

**Source:** `bugs/FORMAL_no_exceptions.md` ("The rule, stated once"; item 1).
**Master plan:** `doc/finish-formal.md` §"Step 26".

## Goal

On the formal path "did this fail?" is a RETURN value and cannot be an
exception. Today `os`, `json` and `hashlib` each invent a convention, because
there is no shared one. The fix is not a code change but **a single exported
pair of names every host module uses**, so the next module decides nothing.

## What to add

- The exported pair in one place (a success/failure sentinel and/or a status
  type).
- Migrate the three modules to it:
  - `os` — `0` on success, `-1` on failure; `makedirs` is `exist_ok=True` only.
  - `json` — `valid`/`top_kind`/`member_kind` (names CPython's `json` lacks).
  - `hashlib` — each digest one function returning a string; a disagreement is a
    status.
- A citation of the convention at each definition.

## The rule that must survive

Do **not** invent a status where CPython has no failure to report: a status the
caller cannot distinguish from a real failure is worse than being permissive
(`os.makedirs`'s reason). State the convention once, in one document/module,
that every host module cites.

## Files

`formal/hostmods/`, `test_formal_hostmods_*.py`.

## Verification

The hostmods suites; the three modules' behaviours unchanged except for the
shared spelling.

## Done when

- [ ] one pair is defined and cited by every host module's definitions
- [ ] `os`/`json`/`hashlib` behaviours unchanged except for the shared spelling
- [ ] `FORMAL_no_exceptions.md` item 1 is closed and the doc says so

## Dependencies

None.
