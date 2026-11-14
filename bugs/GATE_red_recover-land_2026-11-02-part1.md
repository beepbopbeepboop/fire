# A module-alias call to a sibling module's top-level function resolves when the caller is compiled first (part 1)

Part 1 of 5 of `bugs/hard/GATE_red_recover-land_2026-11-02.md`. Class: easy —
the registration step this needs already exists in the same file, for the other
branch. This is the largest single cause of `bootstrap-stage1-transitive`'s red
(the parent doc's 17 private functions and `_EXPR_DISPATCH`/`_STMT_DISPATCH`/
`_GD_*` table reads: `ginf._open_block_scope`, `ginf._close_block_scope`,
`ggc._boxed_capture_source`, `ggc._build_outer_closure_env`,
`ggc._generator_star_slot`, `ggc._pack_generator_star_args`,
`gex._closure_value`, `_ca._cpp_word_of_kind`, `_ca._cpp_sig_default_word`,
`_ca._fstring_field_names`, …).

## Measured (2026-11-13, this tree)

Three files: `mojo/middle/aa.py` and `mojo/middle/bb.py` import each other and
each calls the *other's* top-level function through its module alias; a root
calls both.

    # mojo/middle/aa.py
    import mojo.middle.bb as bb
    def _apriv(x): return x + 1
    def a_use(x):  return bb._bpriv(x)
    # mojo/middle/bb.py
    import mojo.middle.aa as aa
    def _bpriv(x): return x + 2
    def b_use(x):  return aa._apriv(x)

`compile_to_gimple(root_src, do_imports=True, filename=<root>)` emits **2**
weak stubs. Built with `gcc-mp-15 -O0 -fgimple -x c -Iruntime`, the binary
prints

    3
    b_use: unavailable in compiled mode0

where CPython prints `3\n2\n`, exit 0 — a silent wrong value, not a compile
error, which is exactly the shape that lets `bootstrap-stage1-transitive` link
and then produce a wrong `.ci` (the parent doc's `CLOSURE_INCOMPLETE`).

The defect is **not** the private-name check. Instrumenting `_func_csym` showed
the first half already works: `_note_own_func_home('_apriv', 'mojo.middle.aa')`
runs and `_func_qualifier('_apriv')` answers `mojo_middle_aa`, but
`_func_csym('_apriv')` still returns the bare `_apriv`, because
`imported_symbols` has an entry for the MODULE (`import mojo.middle.aa as aa`)
and none for the MEMBER `_apriv`. A bare name is mangleable only when the
symbol itself was registered.

The identical problem is already solved for the *generic* (non-selfhost)
module-qualified branch: `emit_methods.py:3721-3785` calls
`gen._local_sibling_module_exports(...)` + `gen._resolved_export_entry(...)` +
`gen._register_imported_symbol(..., write_param_types=True)`, and its own
comment records that `_note_own_func_home` alone is "the partial fix that is
NOT enough, recorded so nobody re-lands it". The selfhost sibling branch
(`emit_methods.py:3098`, entered through `_selfhost_sibling_member_kind`) still
performs the `_note_own_func_home`-only version.

## Goal

A module-alias call to a top-level function of another of this compiler's own
modules resolves to that function's real mangled symbol **regardless of module
generation order**, including inside an import cycle (`emit_infra <->
emit_stmts`; `emit_infra -> emit_calls -> emit_exprs -> emit_infra`).

Do it by sharing the one implementation: after `_note_own_func_home`, the
selfhost sibling branch must also register the MEMBER (keyed by the alias /
unqualified name, signature taken from the defining module's parsed
`FunctionDef` through `_resolved_export_entry`), then re-dispatch the bare-name
call exactly as it does today. Do not add a second copy of that registration
logic: extract the generic branch's steps into one helper both branches call
(the parent doc's sibling `ginf.tagged_for_target_name` already resolves, which
is why only the unregistered member form fails).

## Acceptance

- The probe above compiles with **zero** `unavailable in compiled mode` text,
  at both call sites, and the built binary's stdout equals CPython's
  (`3\n2\n`), exit 0.
- Both call sites name the defining module's qualified symbol
  (`mojo_middle_aa__apriv_9f63a2`, `mojo_middle_bb__bpriv_9f63a2`).
- Both directions work: root -> sibling alias (`root calls bb.b_use`) and
  sibling -> sibling inside the cycle (`bb` calls `aa._apriv`).
- A public sibling function keeps its current path (no double registration, no
  `conflicting types`, no second definition).
- One registration implementation, used by both the selfhost and the generic
  module-qualified branch.

## Done when

File: `test_selfhost_cycle_sibling_call.py` (repo root; created by this part).

Command: `python3 test_selfhost_cycle_sibling_call.py`

It writes the two `mojo/middle/*` modules and the root into a directory under
`$TMPDIR`, compiles the root with
`compile_to_gimple(..., do_imports=True, filename=<root>)`, asserts the `.ci`
contains no `unavailable in compiled mode`, builds it with
`build_config.find_gcc()` (`-O0 -fgimple -x c -Iruntime … runtime/fire_runtime.c`)
and asserts stdout equals CPython's for the same three files. Red today: 2
stubs, and the binary prints `3\nb_use: unavailable in compiled mode0` where
CPython prints `3\n2\n`.

## Where to start

- `mojo/backend_gimple/emit_methods.py:3098` — the selfhost sibling branch.
- `mojo/backend_gimple/emit_methods.py:3721-3785` — the generic branch's member
  registration, to reuse.
- `mojo/middle/funcs_shared.py:696,1230` (`_resolved_export_entry`,
  `_local_sibling_module_exports`) and `gimple_codegen.py:5078-5093`
  (`_register_imported_symbol`, `_resolved_export_entry`,
  `_local_sibling_module_exports`).
- `_selfhost_sibling_member_kind` (`emit_methods.py:525`) already returns
  `'other'` for a member not yet registered, so the branch IS entered; what is
  missing is the member registration, not the arm.

## Not this part

- `MojoParser` (a function-body import alias) is part 2.
- `issubclass` is part 4.
- The dict-method names `append`/`update`/`items` did not reproduce standalone
  on today's tree (see the parent doc's 2026-11-13 status); if one survives in
  the closure it is part 5's inventory.
