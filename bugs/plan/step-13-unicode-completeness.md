# plan/step-13: Unicode `s[i]` and `%<w>s` once the buffer exists

**Source:** `bugs/FORMAL_string_value_model.md` wave 9.
**Master plan:** `doc/finish-formal.md` §"Step 13".

## Goal

Wave 9 landed bytes-vs-characters for `len`, `find`, `%<width>s` and the
ASCII/refusal rules. Two items are conditional on step-11's buffer:
`s[i]` on non-ASCII text (needs a one-character object) and `%.3s`
(a character-count precision).

## What to add

- Once step-11's buffer exists: lower `s[i]` to the one-character object and
  `%.3s` to a character-count precision.
- Until then: keep the refusals and pin them (they are already correct and
  name the non-ASCII case).
- Add the differential rows (both backends, CPython as oracle) that
  `test_formal_unicode.py` already structures, including the 17 byte-operation
  rows that must stay right.

## Structure-only rule

`ord` folds and `chr` refuses for a reason about where the answer would live;
keep that distinction. `hash` stays refused (CPython randomises it).

## Files

`formal/model/strings.py`, both codegens, `test_formal_unicode.py`.

## Verification

`python3 test_formal_unicode.py`; the 17-row differential.

## Done when

- [ ] refusal rows become answer rows, or stay refusals naming the buffer
- [ ] the 17-row differential stays green
- [ ] `chr`/`hash` reasons unchanged

## Dependencies

step-11.
