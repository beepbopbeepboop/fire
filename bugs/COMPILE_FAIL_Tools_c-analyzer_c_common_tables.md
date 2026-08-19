# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; a NEW, precisely-diagnosed, unrelated blocker found)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). Confirmed via an isolated compile: `parse_table`'s `yield
row, filename` (line 183) is no longer refused.

**This file still does not build**, blocked by a DIFFERENT, precisely-
diagnosed, pre-existing gap — not in the tuple-yield boxing itself
(confirmed clean), but in the coroutine's own C++ FUNCTION SIGNATURE:
`parse_table(entries, sep='\t', header=None, rawsep=False,
default=None, strict=True)` has a parameter literally named `default`
— a C++ reserved keyword. The coroutine-body codegen's parameter-list
emission (`cpp_sig`, `_gen_cpp_generator_unit`) doesn't escape C++-
keyword parameter names the way struct FIELD names already are
(`_CPP_KEYWORD_FIELDS`) — g++ then fails to parse the function
signature at all ("expected ',' or '...' before 'default'"), which
cascades into "not declared in this scope" errors for every OTHER name
in the function body (including this session's own correctly-generated
tuple-boxing code, which is innocent — it's simply unreachable once the
enclosing function's signature itself fails to parse). Confirmed by line
number: the very first error is at the `_mojogen_parse_table_impl`
function-signature line itself, and every subsequent error in that
function is a direct syntactic consequence of that one parse failure.

A real fix would extend the SAME keyword-escaping mechanism
`_CPP_KEYWORD_FIELDS`/`_cpp_expr`'s IdentExpr case already applies to
struct field names, to coroutine PARAMETER names too — not attempted
here (a distinct, well-scoped `_gen_cpp_generator_unit` gap, unrelated
to the promise/ABI value-representation work this session's fix
targets). Doc kept open (not deleted) — tuple-yield is no longer this
file's blocker, but the file genuinely still doesn't build.

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

## Status (updated 2026-08-13 — coroutine keyword-parameter-name blocker FIXED)

Fixed: `gimple_codegen.py`'s coroutine (.cpp) parameter emission
(`_gen_cpp_generator_unit`/`_gen_cpp_async_unit`) now escapes a
parameter name that's a reserved C/C++ keyword (e.g. `default`) to
`_kw_<name>`, consistently across the emitted signature, the
`_start`-to-`impl` call-forwarding text, and every body reference
(`_cpp_expr`'s IdentExpr fallback, `_cpp_stmt`'s AssignStmt target) —
mirrors the escaping already applied to struct FIELD names
(`_CPP_KEYWORD_FIELDS`) and to the ordinary (non-coroutine) GIMPLE
path's own parameter names (`_C_KEYWORDS`/`_declare_var`), just ported
to this separate coroutine emitter. Threaded through a new scoped-state
map, `self._cpp_kw_param_renames` (mirrors `_cpp_mut_capture_names`'s
identical reset-per-unit convention).

Confirmed fixed: `parse_table`'s g++ signature-parse failure
("expected ',' or '...' before 'default'") is gone — re-running
`python3 mojo.py build .../c_common/tables.py` no longer produces that
error or any of its cascaded "not declared in this scope" follow-on
errors.

**This file still does not build** — as anticipated by the
2026-08-09 status below, the build now reaches (and reproduces) the
separate, already-documented `ColumnSpec._parse`'s `cls(*values)`
opaque-callee spread-call gap ("type mismatch in binary expression" at
line 289), previously only a latent, unverified finding masked by the
earlier (now-fixed) coroutine-signature failure. Not attempted here —
out of scope for this narrow keyword-escaping fix.
