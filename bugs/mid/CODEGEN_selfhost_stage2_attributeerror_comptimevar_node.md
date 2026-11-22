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

1. **Quick (the pin):**

        python3 tools/memslot.py --gb 8 --label x -- python3 test_codegen_module_alias_function_value.py

   passes. It builds fixture modules through `build_stdlib_dylib.compile_module_to_c` (the per-file
   `do_imports=False` shape), links each with `runtime/fire_runtime.c`, runs it, and compares with
   CPython. It fails on master: a module-alias function VALUE (`f = h.double_it`) lowers to
   `_mojo_dispatch_getattr(NULL, "double_it")`, which raises at run time. The doc's symptom
   (`AttributeError: _as_comptimevar_node` from `_fc._as_comptimevar_node`) has the same shape;
   that link is inferred from the error text, not reproduced end to end.
2. **Full:** `make bootstrap` gets past `bootstrap-stage2-dumps` (stage2 dumps all exit 0), then
   `bootstrap-verify` compares stage1 and stage2 byte for byte. Delete this doc in the same commit
   as the full chain going green. (Quick criterion 1 alone does not close the doc.)

## Status 2026-11-21

- Upstream has DISABLED `bootstrap-stage1-transitive` and `bootstrap-stage2-cc` on master (their docs
  `bugs/gate-bootstrap-stage1-transitive.md` and `bugs/mid/gate-bootstrap-stage2-cc.md` are the switch). So the
  stage2 dump jobs now run against a PARTIAL `stage1/fire.ci` (604 KB, not the ~135 MB closure). The
  `AttributeError` seen in that run is from the partial stage1, not a measured stage2 fact.
- Tried: `mojo/middle/comptime.py` now `from fire_compiler import _as_comptimevar_node` (as `emit_funcs.py`
  does). Lint and a pydiff repro pass. The bootstrap run did not reach a full stage2, so this is unverified.
  It is NOT committed yet.
- Next: re-enable `bootstrap-stage1-transitive` (delete its doc only when green), regenerate the full closure,
  then rerun the stage2 dumps.

## Status 2026-11-22 (root cause fixed; full chain still open)

- **Root cause (landed on `work/bug-codegen-selfhost-stage2-attributeerr`):** a module-alias member
  read as a VALUE (`f = h.double_it`, `f = h.dt`, a parameter default, a function-scoped import) in
  the per-file `do_imports=False` compile fell to `_mojo_dispatch_getattr` on the NULL module marker,
  which is the fatal `AttributeError`. `_fc._as_comptimevar_node` was exactly such a read. The fix
  is in the lowering: `funcs_shared.register_module_member_function` is the one writer for
  "`<alias>.<member>` is a function of the held module", used by both the call path and the value
  path (`calls_shared._callable_value_symbol`), resolving through one hop walk so a renaming
  re-export gets the definer's symbol.
- **Quick test, measured:** `test_codegen_module_alias_function_value.py` FAILS on a `git archive`
  snapshot of master (`AttributeError: double_it`, `AttributeError: dt`, `NotImplementedError:
  helper.dt ...`) and PASSES on the branch (6 shapes print CPython's answer).
- **Measured, covering:** `test_link_mode.py` (see the commit report for the count).
- **Not measured here:** the full chain (`bootstrap-stage1-transitive` and `bootstrap-stage2-cc`
  are still disabled upstream, so `stage1/fire.ci` is partial). Criterion 2 is the integrator's to
  run after those two jobs are re-enabled. Until then the doc stays open.
- Master's `comptime.py` already imports `_as_comptimevar_node` directly (`5128d44f3`), so the exact
  `_fc._as_comptimevar_node` read named above is gone from master; the fix covers the general shape
  that produced it.
- Adjacent open shapes (not needed for this doc's criterion 1): a module-alias CALL `h.f(...)` whose
  name a same-named class or local def also holds, `bugs/CODEGEN_module_alias_call_shadowed_by_same_named_def.md`.
  The value, class-body and class-as-value shapes of the same per-file read are fixed (pinned by
  `test_codegen_module_alias_function_value.py`).
