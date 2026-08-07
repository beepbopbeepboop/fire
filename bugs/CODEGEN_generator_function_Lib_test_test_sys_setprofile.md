# CODEGEN_generator_function: Lib/test/test_sys_setprofile.py

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. The `:50:23:
error: expected identifier before '__func__'` error is GONE (fixed
elsewhere in the meantime) — only 1 error remains, and it's the whole
build's ONLY error anywhere in the entire transitive closure (this
file's own dependency graph is small). Still correctly classified as
**NOT a generator-codegen-cluster failure** — all 3 of this file's own
generator sites still show zero signal of a problem.

```
/Users/mrs/net/Python-3.14.6/Lib/test/test_sys_setprofile.py:415:31: error: assignment to 'MojoList *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
```

Traced one step further this pass (still not fixed — plain-`.ci`
global-assignment lowering, nothing to do with the coroutine `.cpp`
path this task is scoped to): `protect_ident = ident(protect)` (a
module-level global assigned from a call to `ident()`, which correctly
returns `MojoList *`). The generated `.ci` boxes the call result down
to `int64_t` (`_t4 = (void *)_t2; _t5 = (int64_t)_t4;`) before storing
it — `_root_globals.protect_ident = _t5;` — even though
`protect_ident`'s struct field is declared as a REAL `MojoList *` (not
boxed as `int64_t` the way some other globals are). The box-then-store
sequence looks like generic "store into a global" lowering applied
unconditionally regardless of whether the target field is actually
boxed at the C level — a real bug, but in the ordinary GIMPLE global-
assignment path, not the generator/coroutine codegen this cluster
covers. Flagged for a dedicated non-generator pass; not attempted here.

## Status (updated 2026-08-06, superseded above — one of the 2 errors is now fixed, other traced further)

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
