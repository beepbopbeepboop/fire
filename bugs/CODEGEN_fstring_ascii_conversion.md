# CODEGEN: f-string `!a` (ascii) conversion dropped on the compiled path

## Symptom
On the self-host (gimple_codegen) path, the f-string conversion `!a` renders
the plain value instead of `ascii(value)`. CPython semantics: `!a` =
`ascii()` — single-quoted, every non-ASCII character escaped as `\xNN` /
`\uXXXX` — while `!s` and the no-conversion default are both `str()`. So
`f"({s!a})"` with `s = 'héllo'` prints `('h\xe9llo')` in CPython but
`(héllo)` in compiled output: no quotes, unescaped.

## Evidence
- `mojo/backend_gimple/emit_exprs.py`, `_lower_StringLiteral` f-string branch
  (~line 403): the conversion is parsed and carried (`_parse_fstring_parts`
  returns `('expr', text, spec, conv)` with `conv == 'a'`), but the emitter
  special-cases only `!r` — `if _conv == 'r': _repr_value(...) else:
  _stringify_value(...)`. `!a` falls into the stringify arm.
- Measured in the generated C for `myinterpreter.attribute_error_suggestion`
  (the CPython 3.15.2 verbatim non-ASCII rendering
  `f". Did you mean '.{suggestion}' ({suggestion!a}) ..."`): the interpolated
  `!a` parts lower to plain stringification, no `ascii()` step.
- The `ascii()` builtin has no compiled-path runtime backing (see
  myinterpreter.py's `_eval_fstring_field` comment: "undefined _ascii/_format
  symbols at link time"), so the fix needs a runtime ascii-escape helper plus
  an `!a` arm — a compiled-path change, not a caller-side one.
- The formal path REFUSES f-strings with conversions outright
  (`test_formal_format_conformance.py` rows `fstring_repr_refused` /
  `fstring_str_refused` / `fstring_ascii_refused`), so each path needs its own
  decision; this doc covers only the gimple/self-host path.

## Impact
Any compiled (self-host) code that uses `!a` in an f-string diverges from
CPython. Concrete instance: `myinterpreter.attribute_error_suggestion`'s
non-ASCII branch under the self-host binary (the interpreter/host path is
unaffected and matches CPython 3.15.2 byte-for-byte — differential fuzzed;
see bugs/PYTHON3.15_improved_error_messages.md). The branch is additionally
unreachable end-to-end in user programs while the parser rejects non-ASCII
identifiers (a separate pre-existing parser gap), so today the blast radius
is compiled user code that writes `!a` itself.

## Suggested shape of the fix
Add an `!a` arm to `_lower_StringLiteral` that calls a new runtime
ascii-escape function (single quotes + `\xNN`/`\uXXXX` escapes, i.e. what
CPython's `ascii()` does to a str), mirroring the existing `!r` arm.

## Status
Open. Filed 2026-11-07 from the PYTHON3.15 improved-error-messages work
(branch work/bug-python3-15-improved-error-messages).
