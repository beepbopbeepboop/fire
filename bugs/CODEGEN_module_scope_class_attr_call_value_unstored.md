# CODEGEN_module_scope_class_attr_call_value_unstored

## Summary

A MODULE-scope class attribute whose value is a call, or reads a name that is
not a module global, is still never stored: `C().name` reads `0` / `None`.
Literals and expressions over module globals (this module's own or
`from m import`ed `var` globals) are stored; calls and builtins are not. This
is the remaining case of the module-scope class-attribute store, whose
global-reference cases (this module's own and `from m import`ed `var` globals)
were fixed on 2026-11-12 (module_gen.py's `_module_class_attr_global_stores`,
commit 68802e723 and the cross-module follow-up).

## Repro (measured 2026-11-12, this tree)

    S = "x"

    def f() -> String:
        return "q"

    class C():
        var name = f()
        var n = len(S)

    def main():
        print(C().name)
        print(C().n)

    main()

Compiled with `compile_to_gimple(src, filename=<entry>)` and `gcc -fgimple`:
prints `0` and `0`. Expected (CPython): `q` and `1`.

## Where it is

`mojo/backend_gimple/module_gen.py` `_module_class_attr_global_ctype` returns
None for any value with a free name that is not a global of this module or a
`from m import` global (`f`, `len`), so `_module_class_attr_global_stores`
emits no store. The `_classattr_` global is then never seeded (the literal
seeder in `gen_module` skips non-literals).

## Next step

1. Decide the storage rule for a call value: it is evaluated at the class
   statement's position in the top-level body, like the global-reference store.
   Check that `AssignStmt(C.name, f())` lowers correctly at module top level
   (the call's result type from `f`'s declared return).
2. Widen the gate for a call whose result type is known (a module function with
   a declared scalar/`String` return, or a builtin with a known result type like
   `len`) — type from the callee's signature, not `_quick_type`'s guess.
3. Regression beside `test_module_class_attr_from_imported_global` in
   `test_gimple_runner.py`: the repro above, expecting `q\n1\n`.

## Done when

The repro prints `q` and `1`, checked by a regression next to the
`gimple_module_class_attr_*` cluster.
