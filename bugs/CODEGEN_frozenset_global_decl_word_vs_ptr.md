# A frozenset module global is declared `int64_t` in its defining module but `MojoSet *` in an importing one

Class: high. Hard gcc failure in the `bootstrap-stage2-cc` gate (the
self-host bootstrap TU), measured 2026-11-18 on master 2fb10b162 with the
function-scoped-import fix (the gate's other class of errors) already
applied.

## Symptom

    fire_compiler.py:3740: error: assignment to 'int64_t' from 'MojoSet *'
      3740 | _COMPTIME_TYPE_FUNCS = frozenset({'type_of', '__type_of'})
    ownership_check.py:163: error: assignment to 'MojoSet *' from 'int64_t'
      163 | _COMPTIME_TYPE_FUNCS = N._COMPTIME_TYPE_FUNCS
    ownership_check.py:445: error: assignment to 'int64_t' from 'MojoSet *'
      445 |     if (... node.func.name in _COMPTIME_TYPE_FUNCS):

Reproduce: `python3 tools/suite.py bootstrap-stage2-cc` (stage1 passes;
stage2 gcc fails).

## The two declarations of one global (stage1/fire.ci, measured 2026-11-18)

The defining module, `fire_compiler.py`, keeps the global as a boxed
`int64_t` word:

    int64_t _COMPTIME_TYPE_FUNCS;                          /* globals struct */
    ._COMPTIME_TYPE_FUNCS = 0,
    int64_t fire_compiler__mojo_global_get__COMPTIME_TYPE_FUNCS (void)
        { return _fire_compiler_globals._COMPTIME_TYPE_FUNCS; }

The importing module, `ownership_check.py`, keeps its own module-level
`_COMPTIME_TYPE_FUNCS` (assigned from `N._COMPTIME_TYPE_FUNCS`) as a real
pointer:

    MojoSet * _COMPTIME_TYPE_FUNCS;                        /* globals struct */
    MojoSet * ownership_check__mojo_global_get__COMPTIME_TYPE_FUNCS (void)
        { return _ownership_check_globals._COMPTIME_TYPE_FUNCS; }

The three errors are the three seams between the two spellings:

* the definition stores the `frozenset(...)` call's `MojoSet *` result into
  the `int64_t` field (no box);
* the import reads the defining module's `int64_t` field and stores it
  into its own `MojoSet *` field;
* the `in` operator reads the importer's `MojoSet *` field into the
  boxed-word slot its set-membership lowering expects.

## Root cause (as far as traced)

Two declaration paths disagree on the C type of a module-level container
global:

1. The self-host bootstrap pre-pass in `gen_module_impl`
   (`mojo/backend_gimple/module_gen.py`, the `_global_c_decl_types`
   seeder, just above the inline-compile loop): for a module-level
   `X = frozenset({...})` / `set(...)` / `{...}` / list / dict literal it
   records `_global_var_types[X] = 'MojoSet *'` (semantic) but
   `_global_c_decl_types[X] = 'int64_t'` — the boxed-word convention the
   rest of the codegen assumes for container globals (see the
   two-step load through `void *` in `gen_module_impl`'s global
   initializer block).
2. In `ownership_check.py` the module-level statement is
   `X = N._COMPTIME_TYPE_FUNCS` — a MODULE-ATTRIBUTE READ, not a literal —
   so path 1 never fires for it, and the ordinary global-declaration path
   types the field from the read's answer, `MojoSet *` (the defining
   module's SEMANTIC type), instead of its `_global_c_decl_types` word.

The defining module's own accessors/getters were already built by path 1
(`int64_t`), the importer's by path 2 (`MojoSet *`), and the bridge
(`N._COMPTIME_TYPE_FUNCS`, itself lowered at one site to the
`_t106 = 0;  /* class attr ... UNRESOLVED import */` placeholder) plus the
set `in` lowering each side one of the two conventions.

## Fix direction

One C type per logical container global, all paths: the attribute-read
declaration (path 2) must honor the owner's `_global_c_decl_types`
boxed-word spelling when it resolves the owner, exactly as the
`module_qualifier` docstring's "two mutually disagreeing spellings of one
module" warning does for name spelling. Do NOT flip path 1 to `MojoSet *`:
the boxed-word convention is what the global initializer block, the
`_global_c_decl_types` two-step load, and the set `in` lowering all
assume.

## Status

Provenance: the cross-module READ shape (`N._COMPTIME_TYPE_FUNCS` in
ownership_check.py) came with 125a4a4b0 (2026-11-17, "type_of is a
compile-time type builtin") — the day before the gate first ran red
(2026-11-18 07:28); before that each file carried its own copy and the
two declaration paths never met.

Blocks `bootstrap-stage2-cc` (with CODEGEN_set_op_operand_typed_double.md).
NOT fixed by the function-scoped-import fix (that one's errors are gone
from the gate's gcc output; regression:
test_gimple_function_scoped_import_extern.py / suite
`reg-gimple-function-scoped-import-extern`).
