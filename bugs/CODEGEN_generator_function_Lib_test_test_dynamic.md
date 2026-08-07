# CODEGEN_generator_function: Lib/test/test_dynamic.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `invalid conversion from 'void*'` .cpp error no longer
reproduces. `test_dynamic.py`'s 4 own generator sites (all `yield
len(x)`, lines 53/54/112/113 — nested closures inside test methods) do
not appear in the current error list and have no "not eligible"
refusal.

**Classification: likely NOT a generator-codegen-cluster failure**, but
not fully traced this pass. Only 2 current errors, both at the same
line/col:
```
/Users/mrs/net/Python-3.14.6/Lib/test/test_dynamic.py:161:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Lib/test/test_dynamic.py:161:1: error: type mismatch in binary expression
```
Line 161 is `def test_after_specialization(self):` (a method containing a
nested `def trace(frame, event, arg):` closure, not itself a generator)
— the error SHAPE matches the `_quick_type`-family gap
(`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md`'s
sibling pattern: forward-declared-vs-actual-body return type mismatch),
but the exact triggering expression wasn't read from source in this
pass. Not investigated further — out of scope for this generator-
codegen cluster either way (the 2 errors don't implicate any of this
file's own generators).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_dynamic.py
