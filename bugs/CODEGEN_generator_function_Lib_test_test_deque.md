# CODEGEN_generator_function: Lib/test/test_deque.py

## Status (updated 2026-08-07)

`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md` (task
#145, referenced below re: the lines-332/438/834 "non-trivial
conversion"/"type mismatch" pattern) is now fixed. This file's own
mention was only ever a speculative "sibling family" match, not
independently traced to a confirmed bare-`return`-comprehension shape
in this file's source, and this file was already classified as "NOT a
generator-codegen-cluster failure" dominated by unrelated errors — not
re-investigated further here.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'SyntaxError' was not declared` .cpp error no longer
reproduces. `test_deque.py`'s own 2 generator sites (`yield 1` line 16,
`yield next(task)` line 1012) do not appear in the current error list
and have no "not eligible" refusal.

**Classification: NOT a generator-codegen-cluster failure.** The file
has ~80 current errors, almost all `error: unexpected RHS for assignment
before ';' token` at dozens of distinct lines plus `error: implicit
declaration of function 'deque'` — this codegen appears to be failing on
an ordinary top-level construct used pervasively throughout this file
(possibly `self.assertRaises(...)`-style context-manager assignment
idioms, or the `deque(...)` constructor call itself colliding with a
reserved/builtin name similar to `tokenize.py`'s `any`/`perror`
collisions found elsewhere in this session's pass — not confirmed which,
given the volume). Also present: the recurring comprehension/`_quick_
type`-family "non-trivial conversion"/"type mismatch" pattern
(`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md`'s
sibling family) at lines 332/438/834. None of this implicates the file's
own 2 generators. Not investigated further — out of scope for this
generator-codegen cluster; the `deque`-name-collision angle in
particular looks worth a dedicated non-generator report given how many
lines it affects.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_deque.py
