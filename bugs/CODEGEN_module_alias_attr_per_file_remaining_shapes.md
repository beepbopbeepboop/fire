# CODEGEN: module-alias attribute reads that still fall through in a per-file compile

Found 2026-11-21 while extending `test_codegen_module_alias_function_value.py`
for the `CODEGEN_selfhost_stage2_attributeerror_comptimevar_node` fix (that
doc is deleted with its fix; this doc is what is LEFT).

The path is the per-file compile — `compile_to_gimple(..., do_imports=False)` /
`build_stdlib_dylib.compile_module_to_c`, the shape every
`bootstrap-stage2-dumps` item uses. The fixed bug was `<alias>.<function>`
read as a VALUE. Three measured shapes are still wrong in this compile shape
and right in an inlined whole-program compile, each for its own reason. None
of them is a regression from that fix; all three predate it.

Reproduced with a two/three-file fixture (CPython is the oracle; the fixtures
are the `H_*`, `L_*` and `J_*` cases in the notes below):

## 1. A same-named class/struct in the importer shadows a module member function

    # helper.py:  def double_it(x: int) -> int: return x * 2
    # main.py:
    import helper as h
    class double_it:
        pass
    f = h.double_it
    print(f(21))

CPython prints `42`. The compile of `main.py` emits

    static void * _funcptr_double_it = (void *)double_it;
    ...
    _t2 = _funcptr_double_it;

i.e. the address of the C function the CLASS typedef occupies, and the linked
program prints a pointer decimal (measured `20058832`, different every run).
On a class-less fixture the same read lowers correctly to
`_funcptr_helper_double_it_9f63a2`.

Why: `_lower_MemberExpr`'s module-alias branch and
`_callable_value_symbol` ask TU-wide, bare-name-keyed tables whether the
member is a function. The class claims the bare name `double_it`
(`imported_symbols['double_it']` / `struct_field_types`), so
`funcs_shared.register_module_member_function` returns early ("already
registered") and `_func_csym('double_it')` answers the unqualified
`double_it` — the class. Guarding on `struct_field_types` only changes which
of the two wrong lowerings happens; the whole-program table is genuinely
occupied by the class.

Next step: give a module-member function value a MODULE-QUALIFIED answer that
does not go through `imported_symbols[bare_name]` — resolve the definer and
its original name (the hop walk already returns both:
`_find_symbol_home_module(..., want_name=True)`), build
`<definer>_<original_name>_<overload_suffix>` and emit the matching extern
directly, so a same-named class in the importer is irrelevant. The value form
and the bare re-dispatch share `calls_shared._callable_value_symbol`, so this
is one place, not two.

## 2. A class value read through the alias

    # helper.py:  class Widget: pass
    # main.py:
    import helper as h
    W = h.Widget
    print(W is not None)

Measured: `Unhandled exception: AttributeError: Widget` (exit 1, 1-2 s).

Why: the existing class-as-value branch in `_lower_MemberExpr`
(`class value <alias>.<member> — UNRESOLVED, class-as-value not modeled`)
is gated on `node.member in gen.struct_field_types`, which only holds classes
of modules this compile INLINED. The per-file compile inlines nothing, so the
read reaches the generic `_mojo_dispatch_getattr(NULL, "Widget")` fallback.

Next step: ask the aliased module itself (`funcs_shared._module_defines_symbol`
with kind `'struct'`, following re-exports through
`_find_struct_home_module`) and route to the SAME "UNRESOLVED, class-as-value
not modeled" stub the inlined path already emits. That turns a hard runtime
AttributeError into the documented gap; real class-as-value support is a
larger feature and is not required to close this.

## 3. A class-body attribute bound to a module-alias function value

    # helper.py:  def double_it(x: int) -> int: return x * 2
    # main.py:
    import helper as h
    class C:
        f = h.double_it
    print(C.f(21))

Measured: `Unhandled exception: AttributeError: f` (exit 1). The generated C
has an EMPTY `_mojo_classattr_init`, registers a classattr reader for
`C.f`, and lowers the read `C.f(21)` to
`_mojo_dispatch_getattr(<class marker>, "f")` + `mojo_maybe_bound_call_1`.

Why: a class-body assignment is only materialized into
`_classattr_<Cls>__<name>` when the value is a literal (see module_gen's class
attribute pass); a non-literal value never gets an initializer and the read
falls through to dynamic dispatch.

Next step: lower a non-literal class-body value into the classattr init
(`_classattr_C__f = <lowered h.double_it>`), which needs shape 1's
module-member value machinery to be addressable; then the existing classattr
reader answers `C.f` with the real function address. Deferred until shape 1
lands.

## Where the fixture cases live

The three fixtures are currently only in a scratch probe; add each to
`test_codegen_module_alias_function_value.py` in the commit that fixes it
(the file already builds every module through `compile_module_to_c`, links
with `runtime/fire_runtime.c` and compares against CPython, which is exactly
what these need).

    python3 tools/memslot.py --gb 8 --label x -- python3 test_codegen_module_alias_function_value.py
