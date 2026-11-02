# CODEGEN: a tuple dict key holding int `1` and str `"1"` is one key on the compiled path

## Status — 2026-11-01: found while converting test_dict_tuple_key.py's budgets; not fixed

**Symptom.** `test_dict_tuple_key.py` case `distinct-tuples` fails on HEAD
(16 passed, 1 failed of 17): the compiled program counts one fewer distinct
key than CPython from the fourth `put` on.

**Reproduce.** `python3 tools/memslot.py --gb 8 --label dict-tuple -- python3 test_dict_tuple_key.py`
→ `FAIL distinct-tuples compiled answer differs from CPython's`,
`line 4: cpython 4, compiled 3`, `line 5: cpython 5, compiled 4`, …

**Cause (observed, not yet traced).** The case's `put` calls are, in order:
`(a,b,c)`, `(c,b,a)`, `(1,2,3)`, `("1","2","3")`. CPython gives 4 distinct keys
after the fourth; the compiled binary gives 3. So the tuple `(1,2,3)` and the
tuple `("1","2","3")` are the same key on the compiled path. The case's own
comment says `(1,) != ("1",)` and that a repr-based key would be wrong; the
compiled key appears to compare or hash element text without the element's kind.

**Expected.** Element kind is part of key identity: `(1,2,3)` and
`("1","2","3")` are two keys, as CPython has them.

**Not the same as** `CODEGEN_dict_slot_read_loses_its_value_kind.md` (a dict READ
losing the slot's kind for printing) — this is key identity, not rendering. It
may share a helper with the content-key aliasing that doc names; check before
assuming.

**Next step.** Compile a minimal program with `d[(1, 2, 3)] = 1; d[("1", "2", "3")] = 2; print(len(d))`
through `fire.py run` and `fire.py build`, confirm the compiled count is 1 and the
interpreter's is 2, then read the tuple-key hash/equality in `runtime/fire_runtime.c`
(the `mojo_dict_*` key path) to see which element kinds it ignores. The pinning
test is the existing `test_dict_tuple_key.py::distinct-tuples` row; it is not
registered in `tools/suite.py`, so the fix does not need a registration.
