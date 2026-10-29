# An imported function's trailing default argument is dropped at the call, so `mojoc` does not build

## Status

OPEN. Blocks `mojoc` (the self-hosted compiler) on master, and therefore every self-host, bootstrap and stdlib-compiled gate step that depends on it.

## Symptom

`make mojoc` / `python3 tools/suite.py mojoc` on master (`8c19a643f`, 2026-10-28) exits 1:

```
fire_compiler.py:8875:9: error: too few arguments to function 'compile_to_gimple'; expected 4, have 3
```

`fire_compiler.py:8875` is `return compile_to_gimple(src, do_imports=False, filename=filename)`. The callee is defined in `gimple_codegen.py:6410` as `def compile_to_gimple(mojo_src, do_imports=False, filename="", auto_gpu=True) -> str`. The caller passes three arguments; the fourth, `auto_gpu`, has a default of `True` and must be filled in at the call. It is not.

## Why

The importing module's call lowering knows the callee's arity from the defining module's text scan (`module_loader.py`, the `exports[name]` record: `parameters`, `c_parameters`, `signature`). That record has no default values, so `_lower_named_call` has nothing to pad the omitted trailing parameter with, and the C call is emitted with three arguments against a four-parameter prototype.

The same-module case works: the defining module's own `_func_param_defaults` (`module_gen.py`) carries the defaults, and `gimple_exprtypes._trailing_default_at` pads from them. Only the cross-module (imported) case loses them.

## Repro

Two files, no stdlib needed:

`lib.py`:
```python
def f(a, b=7):
    return a + b
```

`main.py`:
```python
from lib import f
print(f(1))
```

Expected output `8`. Verify with `python3 main.py`. Run it through the compiled path (`python3 fire.py build main.py`) and expect the same `too few arguments` error on `main.py`'s call.

## Next step

1. Record each exported function's parameter defaults in the defining module's export record (`module_loader.py`'s `exports[name]`, from the AST's defaults; `module_spec_gen.py` writes the same shape for spec output, so keep both in step).
2. In the call lowering (`mojo/backend_gimple/emit_calls.py`, `_lower_named_call`), pad missing trailing arguments of an imported callee from those defaults, using the same `_trailing_default_at` helper the same-module path uses. One rule, both cases.
3. Regression test in `test_link_mode.py` with the two-file repro above, running the built binary and checking `8` (no text check of the source).
4. Re-run `python3 tools/suite.py mojoc` and check the `compile_to_gimple` error is gone.
