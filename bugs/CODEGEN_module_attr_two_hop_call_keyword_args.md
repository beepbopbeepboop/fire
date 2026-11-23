# CODEGEN: a two-hop module-attribute CALL with a keyword argument falls to a dynamic getattr

## Symptom

Per-file (`do_imports=False`) compile. `helper.py` does `import impl as sub`;
`main.py` does `import helper as h` and calls a keyword-only parameter through
the two-hop receiver:

    # impl.py
    def pick(p: int, *, a: int = 0, b: int = 0) -> int:
        return a * 10 + b
    # helper.py
    import impl as sub
    # main.py
    import helper as h
    print(h.sub.pick(1, b=2))
    print(h.sub.pick(1, a=3))

CPython prints `2` and `30`. The compiled program exits 1 at run time:

    Unhandled exception: AttributeError: sub

Reproduced on a clean HEAD checkout (`2f5516b60`) and on the branch with the
module-attribute VALUE fix applied (same output both). The positional CALL
`h.sub.double_it(21)` and the one-level keyword call `h.pick(1, b=2)` (the
`call_module_function_keyword_only` case in `test_codegen_module_alias_function_value.py`)
both work; only the two-hop receiver with a keyword fails.

## Cause (read, not yet changed)

`emit_methods._lower_method_call` gates the two-hop arm on the call having no
keywords:

    if (isinstance(func.obj, gimple_ctypes.MemberExpr)
            and isinstance(func.obj.obj, gimple_ctypes.IdentExpr)
            and not getattr(node, 'kwargs', None)):
        _arm_r = _lmc_two_hop_module_call(gen, node, func)

so a keyword call never reaches `_lmc_two_hop_module_call`, and the receiver
lowers to a dynamic getattr on the module marker. The helper itself also builds
its rewritten `CallExpr` with `kwargs=[]`, so even with the gate removed the
keywords would be dropped silently — both must change together.

## Next step

1. In `_lmc_two_hop_module_call` (`mojo/backend_gimple/emit_methods.py`), pass
   the call's keywords through: `kwargs=list(getattr(node, 'kwargs', None) or [])`
   in the rewritten `CallExpr`, as `_lmc_hub_module_ref`'s sibling arms already do.
2. Drop the `and not getattr(node, 'kwargs', None)` gate in
   `_lower_method_call`, so keyword calls take the same resolved-module path as
   positional ones.
3. Add the fixture above to `test_codegen_module_attr_module_value.py` as a
   `call_two_hop_keyword_only` case (expected `2\n30\n`, value=False), beside the
   existing `call_two_hop_alias`. Confirm it fails on HEAD first, then passes.

## Done when

`python3 tools/memslot.py --gb 8 --label x -- python3 test_codegen_module_attr_module_value.py`
passes with the keyword case included, and `test_codegen_module_alias_function_value.py`
(`call_module_function_keyword_only`) still passes.
