# PYTHON3.15: improved error messages

## Symptom
Python 3.15 has improved error messages. Our compiler's error messages should match or exceed.

## Source (CPython 3.15.2)
- Error reporting: Python/errors.c, Python/ceval.c
- Parser errors: Python/ast.c, Parser/parser.c
- AttributeError suggestions (the 3.15 feature proper): Python/suggestions.c
  (`_Py_CalculateSuggestions`, the UTF-8-byte Levenshtein engine) and
  Lib/traceback.py (`_compute_suggestion_error`, `_check_for_nested_attribute`,
  `_CROSS_LANGUAGE_HINTS`, the print-time `!a` renderings).

## Status
2026-11-07 (branch work/bug-python3-15-improved-error-messages): the
AttributeError half of the 3.15 feature is implemented on the
interpreter/CLI path and differential-fuzzed against CPython 3.15.2.

Shipped:
- RAISE half (`myinterpreter._tag_attribute_error`): every missing-attribute
  AttributeError carries `name` and `obj` (set via `setattr()`, since member
  syntax does not survive self-host lowering) — all seven raise sites
  (MojoInstance/MojoClass `__getattr__`, super `__getattribute__`,
  `_eval_member_of` both branches, module `__getattr__` + `__delattr__`).
  A caught AttributeError stays plain — the same caught-plain /
  uncaught-suggested split CPython 3.15 measures (the suggestion is a
  print-time thing).
- PRINT half (`myinterpreter.attribute_error_suggestion`, called from
  fire.py's top-level error printing on both the REPL and
  `interpret_and_execute` paths; the final traceback line is rewritten so
  the `Error:` line and the final line agree): CPython's priority order —
  static cross-language/wrong-type table, two-pass distance match, then the
  nested-attribute check — with 3.15.2-verbatim renderings, including the
  non-ASCII `!a` (ascii-escape) branch.
- The distance match mirrors CPython's TWO-PASS engine: the C module
  (`_suggestions`) on UTF-8 bytes with best_distance seeded at infinity,
  then Lib/traceback.py's code-point fallback with best_distance seeded at
  len(name) — the two disagree on non-ASCII input ('caf' -> 'café' is only
  found by the second pass; a Unicode case flip costs 2 in the byte pass,
  1 in the fallback), plus CPython's NFKC-normalization early return and its
  caps (C module gives up at 750+ candidates; the fallback at 751+ and at a
  40-code-point name, the latter two aborting before the nested check).
  The nested check mirrors CPython's re-filter to non-underscored outer
  members (20, sorted).
- Regression: `test_attr_error_messages.py` (13 tests, including a
  differential test against the host's own TracebackException for the
  non-ASCII path); differential fuzz 3000 ASCII + 4000 non-ASCII cases,
  0 mismatches against the host 3.15.2 engine with 356 cases exercising
  the non-ASCII rendering; 23-case e2e parity of `fire.py run` vs
  `python3 -c`; self-host lowering of both modified files checked
  (compile_to_gimple + gcc -fsyntax-only, no new errors; the distance
  functions lower to real runtime calls — the first draft rebind a local
  to a re-encoded value, which the lowering cannot express, and was
  rewritten to offset-indexing).

Remaining (none block the interpreter/CLI path):
- SELF-HOST binary: the `!a` conversion is dropped there (f-string `!a`
  lowers to plain stringification) — bugs/CODEGEN_fstring_ascii_conversion.md.
  The non-ASCII branch is also unreachable end-to-end in user programs while
  the parser rejects non-ASCII identifiers (pre-existing parser gap).
- SELF-HOST binary: `frozenset` is stubbed in the cross-language table
  (the frozenset builtin has no compiled-path backing; adjacent to
  bugs/PYTHON3.15_frozendict.md), so the two frozenset hints degrade there.
- CPython's `hide_underscored` refinement (allow underscored candidates when
  the failing access was `self.x`) needs the traceback frame, which the
  print-time half here does not carry — documented in `_attr_close_match`.
- CPython's 3.15 feature also covers ModuleNotFoundError / ImportError /
  NameError suggestions (the other branches of `_compute_suggestion_error`);
  only the AttributeError branch is ported here.
