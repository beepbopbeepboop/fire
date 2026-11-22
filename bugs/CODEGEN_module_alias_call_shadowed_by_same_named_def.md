# CODEGEN: a module-alias CALL `h.f(...)` answers a same-named class or local def of the importer

Found 2026-11-22 while fixing the module-alias VALUE form
(`test_codegen_module_alias_function_value.py`). The value form `f = h.f` is now
keyed by the module-qualified C symbol (`funcs_shared.register_module_member_value`)
and is correct in both shadowing cases below. The CALL spelling `h.f(21)` is not:
`emit_methods._lower_method_call`'s module-qualified branch registers the member
through `funcs_shared.register_module_member_function` (bare-name keyed) and then
RE-DISPATCHES the call on the bare name through `_lower_call`
(`_register_sibling_module_member`'s docstring records this design), so the
importer's own same-named entity wins.

## Repro (per-file compile, `compile_module_to_c`, linked with `runtime/fire_runtime.c`)

    # helper.py:  def double_it(x: int) -> int: return x * 2
    # main.py A:
    import helper as h
    class double_it:
        pass
    print(h.double_it(21))          # CPython: 42 — measured: a pointer decimal (51811056 / 17191664 / ...)

    # main.py B:
    import helper as h
    def double_it(x: int) -> int:
        return 0
    print(h.double_it(21))          # CPython: 42 — measured: 0
    print(double_it(5))             # CPython: 0  — measured: 0 (the local call is correct)

Both read `h.double_it` as the importer's own entity. The value form
(`f = h.double_it; f(21)`) in the same two files prints 42 after the fix.

## Why

For B the C has `extern int64_t helper_double_it_9f63a2` and
`int64_t main_double_it_9f63a2`, and the call `h.double_it(21)` is lowered as
`main_double_it_9f63a2 (...)`: the bare re-dispatch resolved through
`_func_csym('double_it')`, which answers the importer's local def.

For A the re-dispatched bare call `double_it(21)` reaches
`emit_calls._lower_call`'s struct-constructor arm (`_fname_ctor in
struct_field_types`), so it builds the class instead of calling the function.

## Next step

Route the module-qualified CALL through the same resolver the value form uses:
in `_lower_method_call`'s generic module-qualified branch, when
`funcs_shared.module_member_function_csym(gen, alias, member)` is not None, lower the call
against that C symbol (register the entry with `register_module_member_value`, whose
extern and `func_param_types` are already keyed by the symbol) instead of
`_register_sibling_module_member` + bare re-dispatch. Keep the factory-value accessor
and the self-host sibling branch as they are unless the new path covers them. The
overload case (`module_member_function_csym` returns None for a name the definer
defines twice) must keep its current answer.

Quick test: add A and B to `test_codegen_module_alias_function_value.py`'s `CASES`
(the CALL spelling, `value_read=False`), and confirm they fail before the change.

## Measured in the same session

- `test_codegen_module_alias_function_value.py` passes (11 shapes) with the value form fixed.
- The call form was NOT changed; the failing outputs above are from the unchanged tree.
