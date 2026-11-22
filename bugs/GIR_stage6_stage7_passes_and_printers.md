# GIR stages 6 and 7: stage 6 (passes of `gen_module_impl`) is finished; stage 7 is open

Plan source: `doc/GIR.md`, Stage 6 (counted loops, arms of the giant functions, passes of
`gen_module_impl`) and Stage 7 (the other printers, including the C++ coroutine lowering in
`cpp_core.py`).

## Still open

- Stage 7: `cpp_core.py` is the C++ coroutine printer. Its lowering still spells types and
  statements as strings; the plan moves it onto the same builder as stage 2b. **Blocked**: it starts
  after stages 2b and 3c, and `mojo/ir/build.py` (stage 2b) does not exist in the tree yet.

## Next step

Stage 7: once `mojo/ir/build.py` (stage 2b) is in the tree, move one `cpp_core.py` emission at a
time onto the builder, with `python3 tools/c_oracle.py check --base <the commit before> -j 4`
reporting identical C for all 285 `tools/pydiff_corpus` programs after each move (the corpus
includes the C++ companion output, so a coroutine-lowering change is hashed).

## Status 2026-11-21 (second round): stage 6 is finished — 0 movable passes remain

Landed (one commit, `tools/extract_arm.py --phase` only: no moved line was edited by hand):
the remaining 14 movable statements of `gen_module_impl` are now top-level functions that return
nothing, each called once. 447 statement lines -> 14 call sites, so `gen_module_impl` is
9,107 -> **8,674** lines, and
`python3 tools/extract_arm.py --list-phases mojo/backend_gimple/module_gen.py gen_module_impl 25`
prints `0 lines can be moved`. Everything the tool still lists is its own refusal, which is the
accepted end state: a pass that returns a value, that binds a name read later, or that calls a
nested function (29 nested functions here capture a local, and lifting one needs a typed parameter
per captured local).

The new parameter annotations are the C types the parent's locals had in the compiler's own
output (`python3 fire.py --dump mojo/backend_gimple/module_gen.py`): `char *` -> `str`,
`_Bool` -> `bool`, `MojoList *` -> `list`, `MojoSet *` -> `set[str]` (the two are sets of names),
`MojoDict *` -> `dict`, `int64_t` -> no annotation. The one erased-word local passed is `_gg_stmts`
(`int64_t` in the parent, deliberately unannotated), so the self-hosted compiler types it the same
way the parent did; the CPython dump infers `MojoClass *` for it from the body's one field use and
casts at the call site.

Verified:

- `python3 test_gimple_module_passes.py`: 27 passes pinned (13 + 14), `gen_module_impl`
  8,674/8,674 lines, 0 failures. The test also runs `--list-phases` and requires the
  `0 lines can be moved` end state; on the pre-change file it reports 30 failures (14 missing
  signatures, the 9,107-line parent, and 447 movable lines).
- `python3 tools/c_oracle.py check --base 25ce47f3c -j 4`: all 285 `tools/pydiff_corpus`
  programs generate identical C.
- `python3 test_gimple_lint.py`: passed, 0 failures, 13 corpus files, 313,334 statements (it
  compiles `module_gen.py` in single-file `--dump` mode, so the moved code still lowers cleanly).

NOT done: stage 7 (blocked on stage 2b). The self-hosted bootstrap is not verified here (a
light-worker round may not run it); the annotations above are the only way this change can affect it.

## Done when

- Stage 7: `cpp_core.py`'s lowering builds `mojo/ir` instructions instead of C++ text, with
  `python3 tools/c_oracle.py check` reporting identical C for `tools/pydiff_corpus`.
- The doc is deleted in that commit (with `python3 tools/dangling_doc_refs.py --ratchet`).
