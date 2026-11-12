# COMPILE_FAIL: c_analyzer/__main__.py part 4 — end-to-end build and behaviour check

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md` (SPLIT)
Class: mid

Filed under `bugs/mid/` (the class this part argues it needs).

## Scope

After parts 1-3 land, re-run the parent doc's own repro on the current tree.
Copy the reference sources into the worktree scratch area (never edit
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`):

```
mkdir -p .tmp/ca
cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/. .tmp/ca/
python3 tools/memslot.py --gb 8 --label ca-main -- python3 fire.py build -o .tmp/ca/out .tmp/ca/c_analyzer/__main__.py
```

This part is the integration/verification step, not a new compiler feature.
It does four things:

1. Confirms the file's own shapes (`fmt_summary`/`section`,
   `build_section`/`render`, `_render_table`) no longer appear in
   `Unsupported shape(s)`.
2. Confirms the imported-module closure compiles, or names the exact remaining
   blocker. The imported-module floor is owned by sibling docs and must not be
   fixed here:
   - `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`
     (`c_parser/info.py`, `c_parser/parser/_func_body.py`,
     `c_parser/match.py`).
   - `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md`
     (`c_common/scriptutil.py`).
   - `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md`
     (`c_common/tables.py`).
   - `bugs/mid/SUITE_gimplegenerators.md` (the `ggc` shadow
     `UnboundLocalError` in `emit_methods._lower_method_call`, which
     `c_parser/info.py` triggers).
3. If the build still fails, records the verbatim `Unsupported shape(s)` list
   in this doc and files the remaining named blocker as a new
   `bugs/<AREA>_<slug>.md` with the exact command, output, and next step. If
   the remaining blocker is one of parts 1-3 still failing, update that part's
   Status with the measured output instead of filing a duplicate.
4. If the build succeeds, runs the built program's `analyze --format summary`
   (or `check --format summary`) on a small C sample and compares stdout and
   exit code with the CPython reference (`python3 .tmp/ca/c-analyzer.py ...`),
   then records the comparison here.

## Acceptance

- The build command's exit status and the full `Unsupported shape(s)` list
  (or `Built: ...`) are recorded in this doc.
- Either:
  (a) the build exits 0 and the built program's summary output matches the
      CPython reference on the sample, or
  (b) the remaining blocker is a new bug doc with the exact next step, and
      this doc says which sibling doc owns it.
- One build only, wrapped in `tools/memslot.py --gb 8`. No whole-closure gate,
  no self-host build, no `--dump-full`.

## Not in scope

- Fixing the imported-module blockers listed above (sibling docs).
- Deleting the parent doc. The parent stays at its class and carries SPLIT;
  the controller/integrator decides when it is closed.
- Re-doing the compiler work of parts 1-3; this part only measures and closes
  the loop.
