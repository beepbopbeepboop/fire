# CODEGEN: compiling the compiler's own sources is refused: dict-slot reads are tagged words

Found 2026-11-10. Since the dict-slot read work reached master (7ae229803, merged in 6b5c68c5b, then 3213b5e88), the
compiler refuses to compile some of its own modules (the fire.ci self-host build). Errors seen:

    ERROR: compiling imported module 'ast_rewriter' from .../fire/ast_rewriter.py: 'node': a name bound to a tagged
    generator word (a yield of more than one kind) cannot also hold a value of another C type (str or float): the box
    cannot carry it; refused
    ERROR: compiling imported module 'mojo.middle.coro' ...: '_callee': a name bound to a tagged generator word ... refused
    ERROR: compiling imported module 'mojo.middle.module_shared' ...: '_fd': a name bound to a tagged generator word ... refused

## When it worked

Measured by compiling the module alone with `build_stdlib_dylib.compile_module_to_c(src, path, name, linkable=False)`
at each commit (the probe is described below):

| commit | ast_rewriter.py | module_shared.py |
|---|---|---|
| d049ce259 (formal: ABI census opt-in exclusion; the last commit before the session's codegen work) | OK | OK |
| 35576ecc9 codegen: recover dict slot kind for string-keyed subscript reads | OK | - |
| f36706357, 1e2cd3d11, 7654f53c9 (the dict-slot series, earlier steps) | OK | - |
| 7ae229803 codegen: make dict slot reads always carry value kind | REFUSED | - |
| 3213b5e88, 08fd01352, abbde2442, 0d8bb4429, master (7fb6cb5bf) | REFUSED | REFUSED |

`coro.py` fails in isolation on d049ce259 too, with a different message (`parameter 'real_params' ... passed a container
at one call site and a str or number`), so it is not evidence for this bug on its own. Its `_callee` refusal was
reported in the fire.ci build and I have not reproduced it in isolation.

## What broke it

7ae229803 changes the dict subscript arm in `mojo/backend_gimple/emit_calls.py`: `mojo_dict_get_int` becomes
`mojo_dict_slot_boxed` (and the bytes/None variants), and each result temp is added to `gen._tagged_word_vals`. So a
value read from a dict is now a tagged word, the same as a generator word.

The refusal that fires (`MIXED_NAME_NON_INT64_REFUSAL`, `mojo/backend_gimple/emit_infra.py`, from efef2b08a) is for a
name bound to a tagged generator word and later stored with a str or float value. A dict read is not a generator word,
so the refusal should not apply to it. For `ast_rewriter.py`, the candidate is `node = node.edges[key]` (line 603,
a dict read) with another assignment of a different C type to `node` in the same function. That is not confirmed.

## Reproduce

    cd <repo at master>
    python3 - <<'PY'
    import os
    from build_stdlib_dylib import compile_module_to_c
    src = open("ast_rewriter.py").read()
    compile_module_to_c(src, os.path.join(".tmp", "probe.py"), "ast_rewriter", linkable=False)
    PY

Expected: returns the C text. Actual on master: RuntimeError with the message above. Same for `module_shared.py`.
Bisect with `git worktree add --detach <dir> <commit>` and run the same probe in each.

## Next step

Make the refusal fire only for a tagged generator word, so a dict read tagged by 7ae229803 is not refused, or stop
tagging a dict read whose name is later rebound with another C type. The fix is done when `ast_rewriter.py`,
`module_shared.py` and `coro.py` compile in the fire.ci build, and `test_dict_slot_read_regression.py` still passes.
Check it against the fire.ci build, not only this probe.

## Status (2026-11-11)

- FIXED: `ast_rewriter.py` and `module_shared.py` compile (the refusal was the dict-slot tag, fixed in 7fe6798cc).
- REFUSED BY DESIGN: `mojo/middle/coro.py` is refused with `parameter 'real_params' of '_mark_coro_param_elem_kinds' is
  passed a container at one call site and a str or number at another`. The compiled path has no representation that
  holds both kinds (`module_gen.py`, `_refuse_mixed_container_params`). Expected until that representation exists:
  see `CODEGEN_mixed_kind_names_need_a_representation.md`.
- REFUSED BY DESIGN: a float and a str stored into one name (regression test case 2) now refuse with the mixed-name
  reason, instead of emitting a double-to-pointer cast gcc rejects. The same design gap.
- `test_dict_slot_read_regression.py` passes with case 2 expecting that refusal.
- NOT RUN: the fire.ci self-host build. Its check needs `coro.py` to compile, which is blocked on the design gap.

Done when the mixed-kind representation exists, `coro.py` compiles, and the fire.ci build is green. Until then this doc
stays open with the status above.

## Process note

The dict-slot branch was merged to master (6b5c68c5b) without compiling the compiler's own sources. Add that compile to
the check for any compiled-path change.
