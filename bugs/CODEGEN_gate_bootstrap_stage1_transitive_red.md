# Gate job `bootstrap-stage1-transitive` is red: bootstrap stage1 transitive job red

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

2026-10-29 — PARTIAL FIX landed on `work/bug-codegen-gate-bootstrap-stage1-transi` (root cause of the diagnostic below; the gate job itself is not yet re-run).

- Reproduced the exact diagnostic without the whole-closure compile: a NESTED `def walk(live): live = set(live); live.add(1); return live`, called from an enclosing function, was refused with `cannot coerce MojoSet * to MojoList * ... dest='live'`. The same body at module scope compiled, because the module-level call `walk({3})` gives call-site evidence that overrides the guess; a nested def gets no call-site evidence.
- Root cause: `infra_infer._infer_param_types` reaches its last-resort container guess (`MojoList *`) for `live` because `set(live)` is iteration evidence (`set` is in `_ITERABLE_CONSUMING_BUILTINS`). The body's own rebinding `live = set(live)` was never read as evidence, and `_prebound_local_ctypes` could not see it either, since it only recognised container DISPLAYS (`{...}`, `[...]`), not builtin constructor calls.
- Landed: `_builtin_container_ctor_ctype` (builtin container constructors through `types._BUILTIN_RET_CTYPES`, consulted by `_prebound_local_ctypes`), and `_rebound_param_containers` (a parameter the body rebinds to one container kind takes that kind in the last-resort arm, mirroring `_returned_param_containers`).
- Test: `test_gimple.py::test_nested_def_rebound_param_takes_the_container_it_stores`. FAILS on HEAD's `infra_infer.py` with the diagnostic above; PASSES with the fix. `test_gimple.py` as a whole: 417 pass, 1 fail, and that failure (`scalar_arity_min_max_params_are_not_containers`) is pre-existing on HEAD (same runtime `AttributeError: MIN_READ_SIZE`), tracked by `bugs/CODEGEN_scalar_arity_min_max_link_mode_prints_nothing.md`.

2026-10-30 — the red gate run (`5a071f6b`) predates the fix above: `ea558a912` is NOT an ancestor of `5a071f6b`, it is on master after it. Verified on this branch, narrow only (no closure compile):

- Pre-fix commit (`ea558a912^`, scratch worktree): a nested-def program with the `walk_stmts` shape (`live = set(live)`, `live |= ...`, `live -= ...`, `live.add(...)`, loop, nested helper) is refused with exactly `cannot coerce MojoSet * to MojoList * (incompatible container kinds) ... dest='live'`.
- HEAD: the same program compiles.
- `test_gimple.py::test_nested_def_rebound_param_takes_the_container_it_stores` now also carries that `walk_stmts`-shaped program (it previously covered only the minimal `set(live)` + `add` shape). It passes on HEAD.
- Still NOT verified: the named check `python3 tools/suite.py bootstrap-stage1-transitive` (a whole-closure `fire.py --dump-full`, 4 GB class, ~5 min). It must be run by the integrator on master. The doc is kept until it passes.

REMAINING (why this is not deleted yet): the doc's named check is `tools/suite.py bootstrap-stage1-transitive` run alone on master. That is a whole-closure compile, which the worker run did not perform. The integrator must run it on the merged branch. Only if that job then passes does this doc get deleted (with `dangling_doc_refs.py --ratchet`). If it still reports a `MojoSet`/`MojoList` coercion anywhere in `formal/model.py`, the next step is to find that statement's shape and add it to the nested-def test; the fix only covers the parameter-rebinding shape.

## Gate output (first lines)

```
memcap: bootstrap-stage1-transitive -- ceiling 4.0 GB across the process tree
# ERROR: compiling imported module 'formal.model' from /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: cannot coerce MojoSet * to MojoList * (incompatible container kinds) at /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: value='_t3' dest='live'
# ERROR: compiling imported module 'formal.model' from ../formal/model.py: cannot coerce MojoSet * to MojoList * (incompatible container kinds) at /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: value='_t3' dest='live'
✓ Generated fire.ci (transitive closure)
```

## What to check first

stage1 transitive compile failed (no excerpt captured); rerun alone.

## Next step

1. Run `python3 tools/suite.py bootstrap-stage1-transitive` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
