# CODEGEN: a module attribute that is itself a module, read as a VALUE, is a dynamic getattr (replan part 3 of 4)

## Goal

In the per-file (`do_imports=False`) compile, a function reached through a module attribute that
is ITSELF a module must be a real function value when it is read as a value:

    import helper as h        # helper.py: import impl as sub
    f = h.sub.double_it
    f(21)                     # must print 42

and the same for an unaliased dotted import:

    import pkg.impl
    f = pkg.impl.double_it
    f(21)                     # must print 42

The CALL spellings of both already work; only the VALUE spelling falls to
`_mojo_dispatch_getattr` and dies on the module marker.

## Where and what was measured (2026-11-23)

Fixtures built through `build_stdlib_dylib.compile_module_to_c` (the per-file path), linked with
`runtime/fire_runtime.c`, run, stdout compared with CPython.

| shape | result on HEAD |
|---|---|
| `import helper as h` (helper: `import impl as sub`), `f = h.sub.double_it` | exit 1, `AttributeError: sub`; C has `_mojo_dispatch_getattr(_t2, "sub")` then a second getattr for `"double_it"` |
| `import pkg.impl`, `f = pkg.impl.double_it` | exit 1, `AttributeError: impl`; C has `_mojo_dispatch_getattr(_t2, "impl")` |
| `print(h.sub.double_it(21))` (CALL) | PASS, prints 42 |
| `print(pkg.impl.double_it(21))` (CALL) | PASS, prints 42 |
| `import pkg.impl as i`, `f = i.double_it` | PASS, prints 42 (the alias binds the module directly) |

`_module_attr_module` (`mojo/middle/funcs_shared.py:1678`) already answers "which module does
this module's namespace bind this attribute to", for both `import M [as N]` and
`from ... import submodule`. The CALL path consumes it (`mojo/backend_gimple/emit_methods.py`,
`_lmc_resolve_module_attr` / the module-attribute re-dispatch landed as `c749d2faf`);
`_lower_MemberExpr` (`mojo/backend_gimple/emit_exprs.py`) has no branch for "the receiver is a
member read whose value is a module", so the value read never asks.

## Next step

In `_lower_MemberExpr`, when the receiver is itself a `MemberExpr` (or a dotted module path)
that `_module_attr_module` resolves to a module, answer the OUTER member against that module
through the same module-qualified value machinery the alias branch already uses
(`_callable_value_symbol` / `register_module_member_value`), instead of lowering the receiver
to a dynamic getattr first. Keep the generic fallback for a receiver that is not a module
binding.

## Acceptance

- Both VALUE spellings print `42`, and their emitted C contains no
  `_mojo_dispatch_getattr` whose attribute string is `"sub"`, `"impl"` or `"double_it"`.
- The CALL spellings (`h.sub.double_it(21)`, `pkg.impl.double_it(21)`), the direct alias
  (`import pkg.impl as i; f = i.double_it`) and a plain same-module function value stay green
  in the same test file.
- A receiver that is NOT a module binding (e.g. a class instance's attribute) keeps its
  existing lowering.

## Done when

File: `test_codegen_module_attr_module_value.py` (new).

Command:

    python3 tools/memslot.py --gb 8 --label module-attr-module-value -- python3 test_codegen_module_attr_module_value.py

It builds each fixture through `compile_module_to_c`, links with `runtime/fire_runtime.c`, runs
it and compares stdout with CPython. RED on HEAD at the two VALUE spellings, GREEN after this
part. `test_module_attr_module_call.py` (registered as `reg-module-attr-module-call`) is the
sibling pin for the CALL spelling and must stay green.
