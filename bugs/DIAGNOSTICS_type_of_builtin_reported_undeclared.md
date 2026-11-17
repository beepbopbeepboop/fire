# DIAGNOSTICS: `type_of(x)` is reported as "use of unknown declaration"

**Status (2026-11-17): open. Pre-existing on master; found while landing
`bugs/CODEGEN_nested_bracket_generic_call_stubs_to_zero.md` (the fix there does
not touch the unknown-declaration check, and the failure happens before
elaboration, so it is not caused by that change).**

## What I ran

    python3 test_elaboration_recursion_diagnostic.py

The file's `test_intrinsic_name_bracket_arg_builds` builds

    def taker[T: AnyType](x: Int) -> Int:
        return 0

    def helper[w: Int](x: Int) -> Int:
        return taker[type_of(x)](x)

## What I saw

The build is refused before codegen:

    error: use of unknown declaration 'type_of'
        return a + taker[type_of(x)](x)
                         ^~~~~~~

raised by `unknown_decl_check.check_module` (called from
`gimple_codegen._run_pipeline`). The same test is registered in `check` as
`reg-elaboration-recursion-diagnostic` with no `expect=` marker, so `check` is
red on master for this reason alone.

## Expected

`type_of(...)` is a compiler-provided builtin, not an undeclared name:
`mojo/backend_gimple/module_gen.py:19563` declares `int64_t type_of(...)` in the
generated runtime header (the lowering's `mojo_type_of` entry has a signature in
`mojo/middle/rt_sigs.py:961` and `GimpleGen._KNOWN_SIGS`), and
`ownership_check.py:159` already lists it in `_COMPTIME_TYPE_FUNCS`. The program
must build and run.

Measured on 2026-11-17:

    python3 -c "import gimple_codegen; from mojo.middle.rt_sigs import RT_SIGS; \
      print('type_of' in gimple_codegen._RUNTIME_FUNCS, \
            'type_of' in gimple_codegen.GimpleGen._KNOWN_SIGS, 'type_of' in RT_SIGS)"
    -> False False False

`unknown_decl_check._compiler_runtime_names()` unions exactly those three
tables (plus `_COMPILE_TIME_INTRINSICS` for names the compiler lowers by name),
so `type_of` is in none of the sets it accepts.

## Exact next step

Add `type_of` to the table that names the functions "a call resolves against" —
`gimple_codegen._RUNTIME_FUNCS` (its module docstring already says that table
holds functions the compiler itself provides, and `module_gen` emits the
declaration), or `GimpleGen._KNOWN_SIGS` — not to `_COMPILE_TIME_INTRINSICS`
unless the intent is to say it is lowered purely by name. Then rerun
`python3 test_elaboration_recursion_diagnostic.py`: all nine cases should pass
(the other eight did on 2026-11-17), and add `type_of` to
`test_unknown_decl_check.py`'s accepted-builtins cases if that file has them.
If the header-table route is preferred (comments in `unknown_decl_check.py` call
the headers the single source of truth), the same test proves it.
