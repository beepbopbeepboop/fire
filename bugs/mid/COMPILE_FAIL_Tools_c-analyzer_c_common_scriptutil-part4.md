# COMPILE_FAIL: scriptutil.py part 4 — remaining _iter_filenames/scriptutil generator shapes and module closure

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md` (SPLIT)

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/scriptutil.py`

## Scope

After parts 1-3 remove the two named module-level refusals (`traceback_cm` and the
`process(...)` call in `_iter_filenames`), `scriptutil.py` is still expected to hit
downstream unsupported shapes recorded in the parent doc (2026-10-29 / 2026-10-02),
notably within `_iter_filenames` and its closure:

- `iterutil.peek_and_iter` usage and `next(...)` on a rebound list-iterator local (the
  `peek_and_iter` / iterator-cursor shape referenced by the parent).
- `iterutil.iter_many`.
- `yield from fsutil.process_filenames(...)` (yield-from a module/imported generator
  call result as needed here).
- A lambda inside a tuple yield (and related small expression forms used in this path).
- `yield from items` on a non-generator/local iterator value as it appears in this
  function.
- Any residual scriptutil-local generator shape that still prevents module compilation
  once the above are addressed.

This part is the integration/closure work to make the module-level refusal list empty.

## Dependencies

- Depends on part 1 and part 2 (clear `traceback_cm`).
- Depends on part 3 (resolve `process(...)` in `_iter_filenames`).
- Some iterator behaviors may overlap with separate bugs (e.g. `iterutil`/`next` on
  bound list iterator). Implement the minimal support needed for scriptutil's shapes,
  or record/align with existing bug docs if a blocker is truly external; do not
  duplicate fixes.

## Acceptance check

- `MOJO_DEBUG=1 python3 fire.py build -o <tmp>/scriptutil <copy>/c_common/scriptutil.py`
  (sources copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`, with required
  sibling modules available per closure) completes without the module-level generator
  refusal list, producing a `.cpp`/artifact as applicable for a successful build on the
  current tree. Run wrapped in `python3 tools/memslot.py --gb 8 --label scriptutil-build -- <cmd>`.
- If a specific residual shape is isolated first, add/verify a narrow compiled-vs-CPython
  regression for it in the appropriate test file, but the end-state acceptance for this
  part is the scriptutil module build succeeding.

## Notes

- Do not run whole-closure compiles, self-host builds, or the quality gate (per worker
  rules). If verification truly requires a heavier closure run beyond the single module
  build above, finish with `CONTROL-STATUS: PARTIAL` and list the exact needed suite jobs
  under `NOT DONE`.
