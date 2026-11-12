# COMPILE_FAIL: scriptutil.py part 1 — nested generator capture of plain-assignment enclosing locals

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md` (SPLIT)

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/scriptutil.py`

## Scope

Unblock the capture side of `traceback_cm` (scriptutil.py:218), a nested generator
inside `main()` decorated as `@contextlib.contextmanager` that reads the enclosing
local `showtb`. `showtb` is first bound by a plain assignment
(`showtb = ns.pop('traceback')`, scriptutil.py:215), not a `var`, so
`_enclosing_scope_with_locals` does not currently resolve it for the nested-generator
capture path.

This part covers **only** extending nested-generator (and, if needed for soundness,
the shared nested-closure capture discovery) to recognize first-bound plain-assignment
locals as capturable when it is safe, so the enclosing read becomes a frame/capture
field instead of being refused.

Out of scope: representing/lowering `@contextlib.contextmanager` itself, the decorator
call/usage shape of `traceback_cm`, and the unrelated `_iter_filenames` blockers.

## Implementation notes

- Widen `_enclosing_scope_with_locals` (and any sibling discovery used by
  `mojo/backend_gimple/cpp_async.py` nested-generator capture) to include plain
  assignments that are the single/first binding in the enclosing def, with a check that
  the lowered C type matches the outer body's declaration (per parent doc 2026-10-29
  next step). Preserve the existing soundness rule: do not claim generators whose
  captured name is rebound in ways the by-value snapshot would miscompile.
- Keep changes consistent with the existing direct-call nested-generator capture path
  landed in `cpp_async._compile_nested_generator_closures` / emit paths.

## Acceptance check

- A compiled reproducer where a nested generator defined as a direct statement of an
  enclosing function reads an enclosing local first bound by plain assignment (not
  `var`) compiles and its behavior matches CPython (stdout/values). Include the
  `showtb`-like boolean/control-flow read shape.
- Existing nested-generator capture regressions still pass (at minimum the tests named
  in the parent 2026-10-29 status in `test_gimple_generator_runner.py`).
- Narrow verification only (the specific covering test file/command), wrapped in
  `python3 tools/memslot.py --gb 8 --label <what> -- <cmd>` if it compiles.

## Not in this part

- `@contextlib.contextmanager` lowering/representation (part 2).
- `process(...)` callable-parameter discovery in `_iter_filenames` (part 3).
- Making `scriptutil.py` fully compile (part 4 / depends on prior parts).
