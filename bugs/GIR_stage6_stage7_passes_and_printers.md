# GIR stages 6 and 7: the loop and pass shapes, and the other printers

Plan source: `doc/GIR.md`, Stage 6 (counted loops, arms of the giant functions, passes of
`gen_module_impl`) and Stage 7 (the other printers, including the C++ coroutine lowering in
`cpp_core.py`).

## Still open

- Stage 6, counted loops: no copy of the `while idx < n; ...; idx += 1` skeleton is left in the
  backend source. `gen._loop_head` / `gen._loop_tail` have 26 call sites (`emit_loops.py` 9,
  `emit_infra.py` 5, `emit_methods.py` 4, `emit_calls.py` 2, `emit_resolve.py` 5,
  `mojo/middle/loops_shared.py` 1). The manual loop heads that remain emit no increment at all
  (dict/set/list/str iterators, regex iteration, the generator-resume loop) or have one that is not
  `+= 1` (`range(start, stop, step)`'s `+= step`); those are cursor loops, deliberately not this
  skeleton, and not a todo.
- Stage 6, passes of `gen_module_impl`: still in progress. 447 lines are still movable
  (`python3 tools/extract_arm.py --list-phases mojo/backend_gimple/module_gen.py gen_module_impl 25`);
  the rest are the tool's own refusals (a pass that binds a name read later, or that calls a nested
  function), which need the pass to return a value or the nested function lifted first.
- Stage 7: `cpp_core.py` is the C++ coroutine printer. Its lowering still spells types and
  statements as strings; the plan moves it onto the same builder as stage 2b. **Blocked**: it starts
  after stages 2b and 3c, and `mojo/ir/build.py` (stage 2b) does not exist in the tree yet.

## Next step

Repeat the 2026-11-21 round: `--list-phases`, pick the largest movable statement, extract it with
the tool (no hand edits), confirm the new parameter annotations against the parent's name
declarations in a fresh `fire.py --dump mojo/backend_gimple/module_gen.py`, and check
`python3 tools/c_oracle.py check --base <the commit before> -j 4` reports identical C for all 285
`tools/pydiff_corpus` programs. Add the extracted rows to `test_gimple_module_passes.py`.

## Status 2026-11-21: 13 more passes of `gen_module_impl` are their own functions

Landed (one commit, `tools/extract_arm.py --phase` only: no moved line was edited by hand):

- 13 statements became top-level functions that return nothing, and `gen_module_impl` calls each
  once: the 478-line AST struct-table pre-seed (`_gmp_preseed_ast_struct_tables`, gated on one
  bool), and 12 passes of 25-37 lines, 856 statement lines in total. `gen_module_impl` is
  15,554 -> 11,841 -> 9,416 -> **9,107** lines (the first three figures are the 2026-11-16 rounds
  recorded in `doc/GIR.md`).
- The new parameter annotations are the C types the parent's locals had in the compiler's own
  output, checked by dumping `module_gen.ci` before and after: `char *` -> `str`, `_Bool` -> `bool`,
  `MojoList *` -> `list` (`list[str]` where the elements are code fragments), `MojoDict *` -> `dict`,
  `int64_t` -> no annotation. The one word-typed local that is passed is `_mg_introspected` (a set
  that the self-host path carries erased), deliberately unannotated.
- `test_gimple_module_passes.py` is the new pinning test: it fails on the pre-change file (13
  missing signatures, `gen_module_impl` 9,950 lines against the 9,107 ratchet) and passes after.
  It also pins that every `_gmp_*` function the parent calls is a top-level function called exactly
  once, so a pass inlined back into the parent is caught.

Verified:

- `python3 tools/c_oracle.py check --base faabc1806 -j 4`: all 285 `tools/pydiff_corpus` programs
  generate identical C (the base was cached with `c_oracle.py base` first).
- `python3 test_gimple_lint.py`: passed, 0 failures, 13 corpus files, 313,331 statements (this
  compiles `module_gen.py` in single-file `--dump` mode, so the moved code still lowers cleanly).
- `python3 test_gimple_module_passes.py`: 13 passes pinned, 9,107/9,107 lines, 0 failures.

NOT done: stage 7 (blocked on stage 2b), and the 447 still-movable lines above. The self-hosted
bootstrap is not verified here (a light-worker round may not run it); the annotations above are the
only way this change can affect it.

## Done when

- `python3 tools/extract_arm.py --list-phases mojo/backend_gimple/module_gen.py gen_module_impl 25`
  prints `0 lines can be moved` (every remaining refusal is the tool's own verdict, as
  `test_gimple_arms_extracted.py` pins for the arm split), and `test_gimple_module_passes.py`
  reports `0 failure(s)` with every extracted pass in its table.
- Stage 7: `cpp_core.py`'s lowering builds `mojo/ir` instructions instead of C++ text, with
  `python3 tools/c_oracle.py check` reporting identical C for `tools/pydiff_corpus`.
- The doc is deleted in that commit (with `python3 tools/dangling_doc_refs.py --ratchet`).
