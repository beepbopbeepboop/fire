# CODEGEN_generator_function: Lib/test/test_sys_setprofile.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `redefinition of 'struct _mojogen_f...'` error (plausibly an
earlier instance of `bugs/hard/CODEGEN_generator_function_symbol_not_
module_qualified.md`'s symbol-collision family, though not confirmed —
no longer reproduces so it can't be re-checked directly) no longer
reproduces. `test_sys_setprofile.py`'s own 3 generator sites (`yield i`,
lines 244/266/283) do not appear in the current error list and have no
"not eligible" refusal — they appear to compile cleanly.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Only 2 current errors, both unrelated:
```
/Users/mrs/net/Python-3.14.6/Lib/test/test_sys_setprofile.py:50:23: error: expected identifier before '__func__'
/Users/mrs/net/Python-3.14.6/Lib/test/test_sys_setprofile.py:415:31: error: assignment to 'MojoList *' from 'int64_t' makes pointer from integer without a cast [-Wint-conversion]
```
Not investigated further — out of scope for this generator-codegen
cluster (neither implicates this file's own generators).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_sys_setprofile.py
