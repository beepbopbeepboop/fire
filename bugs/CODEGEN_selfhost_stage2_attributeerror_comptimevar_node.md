# CODEGEN: the stage2 binary raises `AttributeError: _as_comptimevar_node` on every dump

Found 2026-11-21 while running `make bootstrap` on master plus the stage 5b WordFacts work.
Stage1 (`stage1/fire.ci`) now links and stage2 (`stage2/mojo`) links and starts, but
every `bootstrap-stage2-dumps` job exits 1 with:

    Unhandled exception: AttributeError: _as_comptimevar_node

## Where

- `mojo/middle/comptime.py:85`: `_as_comptimevar_node = _fc._as_comptimevar_node`, where `_fc`
  is the `fire_compiler` module. The comment above it says a field read off a boxed handle
  does not carry the struct, so the module attribute is used instead.
- `fire_compiler.py:4815` defines `_as_comptimevar_node`.
- `mojo/backend_gimple/emit_funcs.py:32` also imports it by name.
- Introduced by `010f47e2b` (comptime: fold an APPLICATION of a generic comptime alias, 2026-11-17)
  and the `_as_comptimevar_node` helper in `e8a7135b8`.

## Measured

- `bootstrap-stage2-dumps:v.mojo`, `abfulltest_leaf.mojo`, `bootstrap-validate.mojo` and others fail
  at 1-2 s with the message above.
- Not yet checked: whether this fails on master before the WordFacts work. Run
  `make bootstrap` on a worktree at `010f47e2b^` to decide that.

## Done when

`make bootstrap` gets past `bootstrap-stage2-dumps` (stage2 dumps all exit 0), then
`bootstrap-verify` compares stage1 and stage2 byte for byte. Delete this doc in the same commit.

## Status 2026-11-21

- Upstream has DISABLED `bootstrap-stage1-transitive` and `bootstrap-stage2-cc` on master (their docs
  `bugs/gate-bootstrap-stage1-transitive.md` and `bugs/gate-bootstrap-stage2-cc.md` are the switch). So the
  stage2 dump jobs now run against a PARTIAL `stage1/fire.ci` (604 KB, not the ~135 MB closure). The
  `AttributeError` seen in that run is from the partial stage1, not a measured stage2 fact.
- Tried: `mojo/middle/comptime.py` now `from fire_compiler import _as_comptimevar_node` (as `emit_funcs.py`
  does). Lint and a pydiff repro pass. The bootstrap run did not reach a full stage2, so this is unverified.
  It is NOT committed yet.
- Next: re-enable `bootstrap-stage1-transitive` (delete its doc only when green), regenerate the full closure,
  then rerun the stage2 dumps.
