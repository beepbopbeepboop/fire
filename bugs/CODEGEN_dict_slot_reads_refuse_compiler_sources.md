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

## Status (2026-11-12)

- LANDED (2026-11-12, latest): the container refusal was too wide. `_gen_stmt_AssignStmt`
  (`emit_stmts.py`) refused a container store whenever the name was a box-holding local
  (`_mixed_box`), and since eb2a7e330b that includes a container-beside-scalar name
  (`mixed_value_locals`), which is supposed to carry a container as its bare word. The
  refusal now fires only for a name bound to a TAGGED generator word (`_tagged_mixed`), which is
  what its message says. Measured: `ast_rewriter.py`, `module_shared.py` and `coro.py` each
  compile in isolation (`compile_module_to_c`, `linkable=False`) with this change; before it,
  `ast_rewriter.py` (`'fval'`) and `coro.py` (`'k'`) were refused. `test_mixed_kind_name_representation.py`
  goes 11/20 -> 20/20. `test_dict_slot_read_regression.py` gains Test 5 (a dict read rebound to a
  container, then an int), which fails with the old condition and passes with the new one.
- STILL OPEN (heavy, integrator): the fire.ci self-host build is not run. Done-when is not met until
  it is green; the doc stays until then.

- `mojo/middle/coro.py` COMPILES: its last blocker was the nested recursive
  generator `_walk_lists`, whose dynamic `getattr` the C++ companion refuses.
  It is an eager list-returning function now, so the compiler's own module
  compiles through the ordinary path (pinned by
  `test_selfhost.py::coro_module_compiles_to_c`). The remaining open item is
  the CODE SHAPE for arbitrary user code, not this build (the dynamic-`getattr`
  refusal that blocked it is fixed in 37c877f7c).
- FIXED: a float and a str stored into one name (regression test case 2). The
  name is the `int64_t` box (`emit_infra.mixed_scalar_locals`), so the program
  compiles and prints the CPython answer; `test_dict_slot_read_regression.py`
  asserts that answer now. The representation is pinned by
  `test_mixed_kind_name_representation.py`.
- FIXED: the `parameter 'real_params' of '_mark_coro_param_elem_kinds' is
  passed a container at one call site and a str or number at another` refusal
  was a false positive — every call site passes a list; only the pre-pass's
  `int64_t` default for each target of a multi-value UNPACK was read as "a
  number". `module_gen`'s `_is_noncontainer_arg` now exempts exactly those
  unpack targets; `coro.py` gets past that refusal.
- STILL UNVERIFIED (heavy): the fire.ci self-host build was NOT run in this
  round. Every named module now compiles in isolation; the gate that builds
  fire.ci is the integrator's.
- SUPERSEDED status (kept for the history of this hop): `ast_rewriter.py` and `module_shared.py` compile (the refusal
  was the dict-slot tag, fixed in 7fe6798cc).
- SUPERSEDED: the two "REFUSED BY DESIGN" entries below described the same
  design gap. They are fixed as of this entry; the paragraphs are kept only so
  the earlier measurement is not lost.
- OLD: `mojo/middle/coro.py` was refused with `parameter 'real_params' of '_mark_coro_param_elem_kinds' is
  passed a container at one call site and a str or number at another` (`module_gen.py`, `_refuse_mixed_container_params`).
- OLD: a float and a str stored into one name (regression test case 2) refused with the mixed-name reason.
- `test_dict_slot_read_regression.py` now passes with case 2 compiling and printing the CPython answer.
- NOT RUN: the fire.ci self-host build. Its earlier blocker was the nested-generator shape, not the mixed-kind
  representation; `coro.py` compiles in isolation now (2026-11-12), so only the heavy integrated build remains.

Done when the mixed-kind representation exists, `coro.py` compiles, and the fire.ci build is green. The first two hold
(2026-11-12); this doc stays open only for the heavy fire.ci verification, which the integrator runs.

## Process note

The dict-slot branch was merged to master (6b5c68c5b) without compiling the compiler's own sources. Add that compile to
the check for any compiled-path change.
