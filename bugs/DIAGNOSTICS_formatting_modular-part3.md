# DIAGNOSTICS: formatting comparison with modular (part 3)

## SPLIT: DIAGNOSTICS_formatting_modular-part1, DIAGNOSTICS_formatting_modular-part2, DIAGNOSTICS_formatting_modular-part3, DIAGNOSTICS_formatting_modular-part4, DIAGNOSTICS_formatting_modular-part5

## Symptom
Our diagnostic formatting for modular test cases does not match the expected format from the modular compiler. We need to compare our output with the modular reference and fix any discrepancies.

## Affected file
- `diagnostic_format.mojo`

## Acceptance
- The diagnostic output for `diagnostic_format.mojo` matches the modular reference format exactly.
- The status section of the bug doc reflects the fix.
- No other files are affected by this change.

## Notes
- This is part 3 of 5 parts for the `DIAGNOSTICS_formatting_modular` bug.
- The full list of affected files includes: `diagnostics_in_missing_locs.mojo`, `diagnostics_in_missing_locs_imports.mojo`, `diagnostic_format.mojo`, `kgen_lsp_check_parse_error.mojo`, and `invalid_downcast_error.mojo` (diagnostic part).
- This part focuses on `diagnostic_format.mojo`.

## Reference

- Modular test, the one this doc means: `test/mojo-parser/diagnostic_format.mojo`
  in the modular checkout (`/Users/mrs/net/chatgpt/claude/modular/mojo`). Its
  RUN lines use `%parse-mojo-isolated`. Other files with this name exist
  (`test/mojo-tool/build/diagnostic_format.mojo`, `test/mojo-parser/docs/`); the
  doc's "affected file" is read as the mojo-parser one.
- Ground truth: `tools/mojo build <abs path>` (text) and
  `tools/mojo build --diagnostic-format json <abs path>` (json). Use absolute
  paths, because the wrapper `cd`s into the modular checkout.

## Status

### 2026-11-14 — partial fix (unknown-declaration diagnostic)

Landed, for the file's unknown-identifier error:

- `fire.py run <file>` no longer prints `Error: ... is not defined` plus a
  Python traceback for an unknown name in Mojo source. It prints the modular
  block: `file:line:col: error: use of unknown declaration 'X'`, the source
  line, and the `^~~~` caret line. A suggestion appends
  `; did you mean 'Y'?` to the head and puts `Y` under the caret.
- `--diagnostic-format json` (global flag, `fire.py`
  `_extract_diagnostic_format`) emits the modular JSON records for the same
  error: the diagnostic object (sorted keys, 0-based `location`/`ranges`,
  1-based `fixIts` for the suggestion) and the driver's closing
  `failed to parse` record.
- `myinterpreter.py`: `mojo_diagnostic(exc, filename, source, fmt)` renders one
  record in both forms. `name_error_candidate` is factored out of
  `name_error_suggestion`, so the CPython-rendered suffix and the Mojo
  rendering pick the same candidate. The unknown-name raise in `eval_IdentExpr`
  attaches `mojo_loc` (line, col, width). Python-facing messages are unchanged,
  so the caught-in-code `NameError` text is unchanged.
- `test_attr_error_messages.py`: the two end-to-end uncaught-NameError tests
  now assert the modular block (their old `Error:` plus CPython-suggestion
  assertions pinned the replaced output). New test
  `test_mojo_unknown_declaration_block_matches_modular` pins the text block and
  the JSON stream.

Verified byte-identical to `tools/mojo build` (same absolute path) for the
JSON stream of this file and of a suggestion case, and for the text block
apart from the launcher line below.

Still missing (the file's RUN lines and their modular output):

1. The launcher's text trailer,
   `<mojo launcher>: error: failed to parse the provided Mojo source module`,
   is not printed in text mode. It names the launcher path, so it is not
   reproducible in our CLI. JSON mode includes it.
2. `--use-mlir-diagnostics=true` with `--diagnostic-format json` should be an
   error record `{"kind":"error","message":"--diagnostic-format=json is
   incompatible with --use-mlir-diagnostics=true"}`. Not implemented; the flag
   is not recognised.
3. The unknown-name error is raised at run time by the interpreter, when the
   statement executes. The modular compiler reports it statically, before
   anything runs, and reports every such error. A static name-resolution pass
   is the real next step; it also gives the other diagnostics in this file's
   sibling tests a place to live.
4. Other error shapes in the same RUN lines are not done: `cannot open '<path>'`
   (json, missing input) and `expression must be mutable in assignment` (a
   parse error, `4 = "hello"`) with its `failed to parse` record.
5. Multiple candidates (the modular listing of several suggestions) and the
   CPython forgot-to-import hint are not rendered in modular form.
