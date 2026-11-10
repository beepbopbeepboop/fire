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

2026-11-07 (branch work/bug-python3-15-improved-error-messages-3988, second
entry): the remaining THREE branches of CPython 3.15's
`_compute_suggestion_error` are ported, so the interpreter/CLI path now
matches CPython 3.15 for EVERY exception type the feature covers:

- NAMEERROR: the RAISE half tags every NameError from a Scope lookup —
  `Scope.get`/`Scope.delete` (rewritten iterative: the old recursion
  raised in the ROOT scope, but the frame that failed is the one CPython's
  print-time half reads, so the walk now raises at the lookup's own scope)
  and `eval_NameExpr`'s loc re-raise — with `name`, the frame's candidate
  pool (CPython's f_locals + f_globals + f_builtins: the frame's vars plus
  the module scope's vars, where setup_builtins binds builtins; a
  module-level failure duplicates the root scope exactly as CPython
  duplicates the module dict), and the frame's `self` (the `self.<name>`
  refinement). The PRINT half (`name_error_suggestion`) runs CPython's
  order: NFKC early return, the `self.<name>` refinement, the shared
  distance match, then the forgot-to-import refinement (a misspelling that
  IS a stdlib module name gets `. Did you forget to import 'x'?`, or
  ` Or did you forget to import 'x'?` after a suggestion).
- MODULENOTFOUNDError: print half only (the real exception already carries
  `name`): the candidates are every module spec the sys.meta_path finders'
  `discover` hook reports (in 3.15 only PathFinder has one), relative to
  the missing name's parent package (`importlib.util.find_spec`; a
  non-package parent such as frozen `os` raises inside discover -> no
  candidates, CPython's try/except-returns-None); rendering
  `. Did you mean: '<s>'?` (the MNE branch has no `!a` branch of its own).
- IMPORTERROR (a `from X import Y` miss, the one carrying `name_from`):
  candidates = X's dir() (the shared `_safe_dir`, CPython's
  `_get_safe___dir__`), re-filtered to non-underscored names when
  `name_from` is non-underscored (CPython re-filters here, mirroring the
  attr branch).
- The shared machinery is now ONE implementation used by all four branches
  (`_suggestion_two_passes`, `_suggestion_normalize`, `_suggestion_after_
  pool`, `_safe_dir`) — the attr branch's private copies were refactored
  onto it; fire.py's `_format_error_message` dispatches all four types
  through `myinterpreter.error_suggestion_suffix`.
- Engine fix found in the process: at EXACTLY 750 candidates CPython's C
  module gives up (its own cap) and the pure-Python fallback is the only
  pass left — and it runs for ASCII too — while the old code's ASCII
  early-return skipped it (a 750-candidate pool got no suggestion at all);
  the early return now applies only when pass 1 RAN. Pinned by
  `test_name_error_caps_match_cpython`.

Regression: `test_attr_error_messages.py` grew from 13 to 26 tests — the 13
new: RAISE-half field pins (module frame + function frame), exact 3.15.2
suffix pins (self refinement, forgot-to-import alone + combined, non-ASCII
rendering, caps boundary, underscore pools), a differential test where the
host subprocess runs the same failing reference and hands back its frame's
EXACT candidate pool plus its own printed suffix (same pool in -> suffix
must be byte-identical out), e2e parity of `fire.py run` vs `python3 -c`
for all three types in the same environment (the `Error:` line our
printing computes, plus final-line agreement), caught-plain for MNE, and
the four-way dispatcher with CPython's guards. Self-host lowering of
myinterpreter.py and fire.py: compile_to_gimple + gcc -fgimple
-fsyntax-only shows no NEW error kinds vs the pre-change tree.

Remaining (none block the interpreter/CLI path):
- SELF-HOST binary: the `!a` conversion is dropped there (f-string `!a`
  lowers to plain stringification) — bugs/CODEGEN_fstring_ascii_conversion.md.
  The non-ASCII branch is also unreachable end-to-end in user programs while
  the parser rejects non-ASCII identifiers (pre-existing parser gap).
- SELF-HOST binary: `frozenset` is stubbed in the cross-language table
  (the frozenset builtin has no compiled-path backing; adjacent to the
  frozendict-builtin work fixed in e79028f08), so the two frozenset hints
  degrade there.
- SELF-HOST binary: the environment-dependent refinements read the host's
  import/sys state at print time — `sys.meta_path`'s `discover` for
  ModuleNotFoundError, `sys.stdlib_module_names` for NameError's
  forgot-to-import — and the self-hosted binary's `sys` is a stub, so both
  degrade to no suggestion there (guarded with getattr/try — no crash,
  same class as the frozenset stub).
- CPython's `hide_underscored` refinement (allow underscored candidates when
  the failing access was `self.x`) needs the traceback frame, which the
  print-time half here does not carry — documented in `_attr_close_match`.
- The interpreter's OWN `from X import Y` miss binds an `_AutoStubValue`
  (the documented graceful stand-in for unresolved symbols, which the
  transpiler relies on) instead of raising CPython's ImportError, so the
  ImportError branch only fires for a name_from ImportError that propagates
  from a real module (a module that fails its own from-import); the
  print-time half is ported regardless, and the e2e regression exercises
  exactly that reachability.
- CPython 3.13-era ModuleNotFoundError message REPLACEMENTS (the stdlib-
  special messages for `_tkinter`/`_gdbm`/..., the no-site and
  incompatible-extension-module suffixes) REWRITE the message rather than
  appending a print-time suffix, and predate 3.15 — out of scope for this
  port.
