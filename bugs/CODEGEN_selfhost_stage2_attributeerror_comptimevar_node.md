# CODEGEN: the stage2 binary raises `AttributeError: _as_comptimevar_node` on every dump

Found 2026-11-21 while running `make bootstrap` on master plus the stage 5b WordFacts work.
Stage1 (`stage1/fire.ci`) now links and stage2 (`stage2/mojo`) links and starts, but
every `bootstrap-stage2-dumps` job exits 1 with:

    Unhandled exception: AttributeError: _as_comptimevar_node

## Where

- `mojo/middle/comptime.py:85` used `_as_comptimevar_node = _fc._as_comptimevar_node`, where
  `_fc` is the `fire_compiler` module — a function read as a VALUE through a bare
  `import fire_compiler as _fc` alias.
- `fire_compiler.py:4815` defines `_as_comptimevar_node`.
- `mojo/backend_gimple/emit_funcs.py:32` imports it by name.
- Introduced by `010f47e2b` (comptime: fold an APPLICATION of a generic comptime alias, 2026-11-17)
  and the `_as_comptimevar_node` helper in `e8a7135b8`.

## Measured

- `bootstrap-stage2-dumps:v.mojo`, `abfulltest_leaf.mojo`, `bootstrap-validate.mojo` and others fail
  at 1-2 s with the message above.
- Compiling `mojo/middle/comptime.py` through `compile_to_gimple(..., do_imports=False)` (the
  per-file path) with its old `_as_comptimevar_node = _fc._as_comptimevar_node` line put back
  emitted `_mojo_dispatch_getattr ((void *)0, "_as_comptimevar_node")` for that read. It is
  not specific to `010f47e2b`: any per-file compile of `f = <module alias>.<function>` lowered
  the same way — the quick test below reproduces it with two plain modules and no comptime
  involvement at all. That commit only added the first such read (of an imported function as
  a VALUE) inside the closure.

## Done when

`make bootstrap` gets past `bootstrap-stage2-dumps` (stage2 dumps all exit 0), then
`bootstrap-verify` compares stage1 and stage2 byte for byte. Delete this doc in the same commit.

Quick pin (added 2026-11-21, and the one that landed the root-cause fix):

    python3 tools/memslot.py --gb 8 --label x -- python3 test_codegen_module_alias_function_value.py

It builds a two-module fixture through `build_stdlib_dylib.compile_module_to_c` — the
per-file `do_imports=False` path `fire.py --dump` uses — links it with the runtime and
requires the program's stdout to equal CPython's. It FAILS on the pre-fix compiler with
`Unhandled exception: AttributeError: double_it` and passes now.

## Root cause (fixed 2026-11-21)

Not the module marker, and not `comptime.py`'s spelling: `_lower_MemberExpr`'s
"a free function reached through a module alias, used as a VALUE" branch was gated on
`node.member in gen.func_return_types`, and that table only carries the defs of modules the
compile INLINED. `compile_to_gimple(..., do_imports=False)` — the shape `fire.py --dump` and
therefore every `bootstrap-stage2-dumps` item uses — inlines nothing, so any
`f = _fc._as_comptimevar_node` fell through to the generic dynamic-dispatch fallback:

    _t102 = (void *)_root_globals._fc;      /* module marker: 0 */
    _t103 = _mojo_dispatch_getattr (_t102, "_as_comptimevar_node");

a NULL receiver, i.e. a fatal uncaught `AttributeError: _as_comptimevar_node` when the
module's top-level runs. Every later file the binary tried to compile died there.

**Landed:**

- `funcs_shared.register_module_member_function` — one writer for "`<alias>.<member>` names a
  function of the module the alias holds" (re-export hop, `_note_own_func_home`, then
  `_register_imported_symbol` from the definer's own parsed signature). It is the body of
  `emit_methods._register_sibling_module_member`, which the module-qualified CALL path already
  used, moved to the middle tier so the VALUE spelling can reach the same one implementation.
- `calls_shared._callable_value_symbol` (the tree's one answer to "the function `f` as a bare C
  value", reached by `_lower_MemberExpr` and the default-parameter path) registers an
  unregistered module member through it and then answers it like any other import.
- `_lower_MemberExpr`'s branch delegates its emission to `_callable_value_symbol` instead of
  keeping a second copy of the `_funcptr_` emission.

Measured on `mojo/middle/comptime.py` compiled with `do_imports=False`, with its OLD
`_as_comptimevar_node = _fc._as_comptimevar_node` line put back: the read now lowers to

    extern ComptimeVarStmt * fire_compiler__as_comptimevar_node_9f63a2 (int64_t e);
    static void * _funcptr_fire_compiler__as_comptimevar_node_9f63a2 = ...;
    _t102 = _funcptr_fire_compiler__as_comptimevar_node_9f63a2;

so the spelling that failed now works too; the by-name `from fire_compiler import
_as_comptimevar_node` that 5128d44f3 landed (matching `emit_funcs.py`) stays as the clearer
spelling and is no longer load-bearing. The member path also types the extern from the
definer's parsed `FunctionDef` (`ComptimeVarStmt *`), where the by-name scan answers `int64_t`.

## Status 2026-11-21 (after the fix)

- Root cause fixed and pinned by the quick test above (fails before, passes after); `linkmode`
  (56/56) and `gimple` re-run green on the touched code.
- **Still not verified end to end**, because the bootstrap chain is blocked UPSTREAM of this
  bug, not by it: `bootstrap-stage1-transitive` and `bootstrap-stage2-cc` are both `disabled=`
  on master (their docs `bugs/gate-bootstrap-stage1-transitive.md` and
  `bugs/gate-bootstrap-stage2-cc.md` are the switches), so stage1/fire.ci is a 604 KB
  single-module dump rather than the closure, and stage2/mojo has no compiler in it. The
  `AttributeError` seen in that state is a partial-closure artifact on top of this defect.
- Next (for the integrator/owner): re-enable `bootstrap-stage1-transitive` and
  `bootstrap-stage2-cc` (each deletes its doc when green), then run
  `python3 tools/suite.py bootstrap-stage2-dumps bootstrap-verify`. Delete this doc in the
  commit that shows them green.
