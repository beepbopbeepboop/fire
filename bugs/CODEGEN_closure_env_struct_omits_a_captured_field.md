# A closure's env struct omits a captured field, so both its allocator and its body write through a field that does not exist

## Status: OPEN. Found 2026-10-03 while working
## `bugs/hard/CODEGEN_dispatch_globals_list_forces_every_name_to_a_dict.md`;
## reachable only through the rollback that bug removed.

## What I ran

    python3 tools/suite.py selfhost
    # FAIL  selfhost  (110s)  exit 1

and the generated-C error inventory described in that doc's "How it is measured
now" section (`sed 's/^#line .*$//' fire.ci > fire_nl.ci` + `gcc -fsyntax-only
-fgimple`), which reports 2 of the 11 remaining errors as:

    fire_nl.ci:881497:13: error: 'gen_module_impl__is_foreign_main__mk_round_env' has no member named 'self'
    fire_nl.ci:953918:17: error: 'gen_module_impl__is_foreign_main__mk_round_env' has no member named 'self'

## What I saw

The struct, emitted at `fire_nl.ci:863836`:

    typedef struct gen_module_impl__is_foreign_main__mk_round_env {
      MojoList * all_functions;
      MojoList * all_structs_for_methods;
      int64_t stmts;
    } gen_module_impl__is_foreign_main__mk_round_env;

The two writes that do not compile, in
`gen_module_impl__mk_round` and in
`mojo_backend_gimple_module_gen_gen_module_impl_7e9a9f`:

    _t4 = _env->self;
    _env__mk_round->self = _t9645;

## Why

`gen_module_impl` (mojo/backend_gimple/module_gen.py:1472) nests three
functions that all become closures, and their captured-variable sets are
MERGED into one env struct per outer function: `_is_foreign_main` captures
`gen_module_impl`'s parameter `stmts` (module_gen.py:4770), while `_mk_round`
captures the locals `all_functions` and `all_structs_for_methods`
(module_gen.py:5120). `_mk`, nested inside `_mk_round` (module_gen.py:5130),
captures `self`, `_mk_cache` and `callee_kinds`, and its body reads and writes
`self._return_maybe_kinds` / `self._return_value_slot_kinds`
(module_gen.py:5138, 5148).

The env struct's field list is `ClosureInfo.captures`
(module_gen.py:10576-10584, `for vname, vtype in ci.captures`), while the
allocator's and the body's field references come from a different walk. `self`
is in the second and not the first, so the two disagree about what the struct
has — a hard gcc error rather than a silent miscompile, which is the good half.

The neighbouring struct emitted immediately after,
`gen_module_impl__scan_module_level_for_func_attrs_env`, DOES declare
`GimpleGen * self;`, so the capture machinery can do this and the merged /
nested case is what is missing it.

## Exact next step

`ClosureInfo.captures` for a nested-in-a-closure is built by the closure
lifting pass in `emit_funcs.py` / `emit_methods.py` (the `_all_closures`
two-level map `_mojo_backend_gimple_module_gen_gen_module_impl_7e9a9f`'s env is
allocated from). Either

* the merge that combines an outer function's captures with a nested
  function's drops a name that is captured only by the inner one, or
* `_mk`'s own `ClosureInfo` is not the one the allocator reads, so the `self`
  reference resolves through the outer `ci`.

Compare, for `_mk`, the `ci.captures` list against the `_env-><field>` names
the lifted body emits, and make the struct's field list the union. The check
that would have caught it is worth adding next to `ClosureInfo.captures`: every
`_env->X` a lifted body emits must be a declared field of `ci.env_struct`.

Note also that `_env__mk->_mk_cache` and `_env__mk->callee_kinds` are written
at `fire_nl.ci:881458-881464` and gcc does NOT report them — so those two
fields exist somewhere the struct above does not show. Establish which env
struct that is before assuming the `self` case is the same one; it may be two
defects, not one.