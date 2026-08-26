# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-25 — down to ONE blocker: `next()` on a cross-module generator handle)

Re-ran fresh against `fix/rest-remainder9`. Real progress since 2026-08-23:
`parse_table` and `_fix_write_default` no longer appear in the refusal at
all — both now compile past the generator-eligibility pre-pass cleanly.
Only ONE ineligible generator remains:

```
Error building: cannot compile module: function(s) read_table (generator
function(s), contain a `yield`/`yield from`) ...
Unsupported shape(s): read_table: a call to unresolved callee 'next(...)'
is not supported in a compiled generator/coroutine body (...).
```

Root-caused: `read_table`'s `lines = strutil._iter_significant_lines(infile)`
binds a generator object obtained from a FOREIGN module (`c_common/
strutil.py`, imported), then later does `actualheader = next(lines).strip()`.
The coroutine-body emitter's `next(x)` support (gimple_cpp_core.py, ~line
1736) only handles the case where `x` is a same-module STRUCT implementing
`__next__` (real object-based iterator protocol) — it has no notion of a
generator-typed local holding a coroutine handle at all, whether from this
module or another. The nearby `yield from <call>` delegation machinery
(`gen._generator_api`/`{base}_start/_resume/_value/_destroy`) is the
closest existing analogue, but it only tracks SAME-MODULE generators the
current compile has itself already translated via the C++20-coroutine
path — `strutil._iter_significant_lines` is both foreign-module (no
cross-module coroutine-handle linking exists yet) and manually driven via
bare `next()` rather than a `for`/`yield from` consumption shape this
emitter already understands. Making `next()` work on an arbitrary
generator-typed local would need a new `_generator_var_api`-style
tracking mechanism (mirroring `_async_var_api`/`_taskgroup_var_api`'s
existing "value -> api" side-tables) PLUS cross-module coroutine-handle
resolution for the `strutil` case specifically — a materially new codegen
capability, not a local fix. Left untouched, per this round's guidance
against large speculative feature work. Doc kept open; every one of the
smaller, narrower gaps this doc previously tracked (tuple-yield, keyword-
parameter escaping, `?:` type coercion, bare-module-reference lowering,
bound-method-as-value) has now either been fixed or become moot as
`parse_table`/`_fix_write_default` cleared the eligibility gate — `next()`
on a foreign generator is now the sole, and genuinely structural, blocker.

## Status (updated 2026-08-23 — real progress: coroutine units now EMIT C++ and reach g++; 13 new, precisely-diagnosed C++ errors remain)

Re-ran against current master tip (`626f3f0`). For the first time this
file's generators get past the eligibility pre-pass entirely —
`parse_table`, `read_table`, and `_fix_write_default` all emit real
coroutine `.cpp` units (confirming the tuple-yield support AND the
2026-08-13 keyword-parameter escaping fix below both hold: no
"expected ',' or '...' before 'default'" anywhere) — and the build now
fails at the g++ stage with 13 errors that are ALL new, unrelated to
either old blocker:

```
tables_gen.cpp: In function '_mojogen__fix_write_default_Task
_mojogen__fix_write_default_impl(MojoList*, int64_t)':
179:32: error: operands to '?:' have different types 'int64_t' and 'char*'
tables_gen.cpp: In function '_mojogen_read_table_Task ...':
258:13: error: 'strutil' was not declared in this scope; did you mean 'strtol'?
265:24: error: 'next' was not declared in this scope
273:28: error: invalid conversion from 'const char*' to 'int64_t'
282:41: error: invalid conversion from 'MojoBoundMethod*' to 'int64_t'
283:32: error: '_get_reader' cannot be used as a function
284:31: error: 'fix_row' cannot be used as a function
tables_gen.cpp: In function '_mojogen_parse_table_Task ...':
359:10: error: declaration of 'auto line' has no initializer
359:19: error: multiple declarations in range-based 'for' loop
359:32: error: 'strutil' was not declared in this scope
361/382: error: 'filename' was not declared in this scope
```

Mechanisms (all in the separately-maintained coroutine-body emitter,
`_cpp_expr`/`_cpp_for_stmt` in gimple_cpp_core.py):
1. `for line, filename in _get_reader(...)` inside `parse_table` — a
   TUPLE-target for-loop over a non-`enumerate` iterable emits malformed
   `for (auto line, filename : ...)` C++ ("multiple declarations in
   range-based 'for' loop", cascading "'filename' was not declared").
   The coroutine drive-loop's tuple-unpack exists but only for an
   already-translated GENERATOR callee; `_get_reader` isn't one here.
   Same gap family `c_parser/datafiles.py`'s doc lists.
2. Bare module references in the body (`strutil.split(...)` etc.) have
   no lowering → `'strutil' was not declared`; same for the `next()`
   builtin (used against a generator-object local).
3. `_get_reader(...)`/`fix_row(...)` as nested-function calls resolve to
   undeclared symbols; a bound method stored/passed as a value converts
   `MojoBoundMethod*`→`int64_t`.
4. `_fix_write_default`'s ternary over a param default mixes
   int64_t and char* (`default=None` vs string defaults).

Notably, the 2026-08-09 note's latent `ColumnSpec._parse` `cls(*values)`
spread-call finding is no longer observable either way — the ordinary
path now handles spread call arguments (the parser wraps them in a
UnaryOp node; see this repo's CLAUDE.md), and `_parse` compiles past
that line. Doc kept open; every remaining mechanism above is
feature-sized work on shared coroutine-codegen machinery. Not attempted.

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
