# plan/step-19: the optional-runtime-unit registry

**Source:** `bugs/FORMAL_known_limits.md` §3.1 ("What is still open, and it is
[1]'s half").
**Master plan:** `doc/finish-formal.md` §"Step 19".

## Goal

Of 683 runtime entry points, **272** have every type crossing the boundary one
word; they are refused only because the executable path (`build --formal`) has
no runtime library on its link line. The single lever between the 272 and
working code is an optional-runtime-unit registry.

## What to add

- A registry of runtime units the link line can opt into, read from
  `runtime/*.h` (the same authority `formal/model`'s `runtime_abi()` reads,
  kept honest by `test_runtime_header_scan.py`).
- The executable path able to include one unit.
- `mojo_sqlite3_*` (16 of 22) as the first unit; it already has test
  scaffolding (`test_sqlite3_*.mojo`, `build_stdlib_dylib.py`).

## Structure-only rule

A word-shaped call is emitted only when the symbol is on the link line; a box in
an argument or the return is refused regardless (the rule the prefix rule could
not express). Do not regress that. Holes, if any, are counted.

## Files

`formal/model/` (ABI table), `formal/build.py`, `build_stdlib_dylib.py`,
`fire.py`, `test_formal_dylib.py`, `test_runtime_header_scan.py`,
`test_formal_link_accounting.py`.

## Verification

`test_formal_dylib.py`, `test_runtime_header_scan.py`,
`test_formal_link_accounting.py`; a real word-shaped call answering a host value.

## Done when

- [ ] at least one runtime unit links into a formal executable
- [ ] a word-shaped call answers a real host value
- [ ] the header census stays green
- [ ] a box argument is still refused

## Dependencies

step-01 (holes only). Independent.
