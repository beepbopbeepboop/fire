# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-09)

Re-ran against current master (`python3 mojo.py build .../c_common/
tables.py`). The previously-documented `ColumnSpec._parse`
`cls(*values)` spread-call-against-opaque-callee GCC error ("type
mismatch in binary expression" at line 289) no longer surfaces — but
NOT because that bug was fixed. `gen_module`'s generator-eligibility
pre-pass (which now honestly refuses `parse_table`, see below) runs,
and raises, entirely in Python BEFORE any C is ever handed to GCC —
that raise necessarily happens earlier in the pipeline than a GCC-
level type-mismatch ever could. The only way the old doc's GCC error
could have been reached at all is if, at capture time, the generator-
eligibility check didn't yet reject `parse_table`'s tuple-valued yield
(i.e. an earlier, more permissive version of the coroutine-lowering
pre-pass let it through, presumably emitting silently-wrong C, which
then went on to hit the unrelated `cls(*values)` bug during GCC
compilation). The eligibility check has since been hardened to
honestly refuse tuple-valued yields up front instead of silently
mis-lowering them. So: the `cls(*values)` opaque-callee spread-call
bug is UNVERIFIED here, not confirmed fixed — it's simply unreachable
now, masked by an earlier (and more correct) refusal. Left as a
separate, latent finding; not re-investigated since it can't be
reached from this file's current top-level compile.

Current failure is the same already-tracked "coroutine codegen has
much weaker yield/type coverage than the ordinary function path" gap
independently confirmed this session for `c_analyzer/__init__.py`,
`c_analyzer/__main__.py`, `c_analyzer/info.py`, and
`c_common/scriptutil.py`:

```
Error building: cannot compile module: function(s) parse_table
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ...
```

With `MOJO_DEBUG=1`:

```
generator 'parse_table' not eligible for C++ coroutine path, falling
back to honest refusal: parse_table: every `yield` must carry a value,
and all values must agree on one scalar type (int64_t/double/_Bool)
```

`parse_table` (line 153) does `yield row, filename` (line 183) — a
2-tuple-valued yield. The coroutine promise machinery only supports a
single scalar (`int64_t`/`double`/`_Bool`) yield-value type, exactly
the documented "tuple-valued yields aren't representable at all" gap.
Not attempted here — deliberately deferred, already-tracked compiled-
generator/async-codegen project scope, not a narrow fix.

(The old GCC-warning-log excerpt previously shown here was from the
stale pre-hardening repro described above and has been removed —
current repro fails before GCC is ever invoked.)
