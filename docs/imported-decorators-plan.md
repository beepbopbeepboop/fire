# Feature Plan: Imported Decorators (CODEGEN_decorator_application_dropped, imported arm)

## Status
Same-module decorators already compile via the rebinding pass in
`_gmi_decorator_pass` (see `bugs/hard/COMPILE_FAIL_decorator_application_dropped.md`).
The imported-decorator arm is still silently unapplied.

## Root cause
`_gmi_is_rebindable` only returns True when the decorator name is in the
local `scope` dict. An imported decorator (`from deco import twice`) is in
`gen._imported_names` but not in `scope`, so the pass keeps `@twice` on the
def and the decorator is dropped.

## What was tried
1. Recognise imported names in `_gmi_is_rebindable` and collect imported
   names in `gen_module_impl` before the decorator pass.
2. Register the decorator's return type as `int64_t` in `func_return_types`
   so the rebinding assignment `step = twice(step__undecorated)` type-checks.

Step 2 is incomplete: the imported function's return type is resolved through
the imported-function home path (not `func_return_types`), so forcing
`int64_t` there did not take effect. Resulting errors:
  `assignment to 'int64_t' from 'MojoBoundMethod *'` (line: rebinding)
  `assignment to 'MojoBoundMethod *' from 'int64_t'` (line: use site)

## Next sub-tasks
A. Find where an imported function's call return type is determined
   (search `_imported_func_home` / `_own_imported_func_home` and the
   identifier-call branch around `_lower_call`'s `fname_raw` handling).
   Confirm whether it consults a per-function map that can be seeded.
B. Seed that map for any imported name that ends up rebound as a decorator,
   so `twice(...)` lowers to `int64_t` instead of `MojoBoundMethod *`.
C. Alternatively, lower the rebinding assignment with an explicit cast at
   the C level; requires a cast-expression AST node or a new helper
   `gen._cast('int64_t', value)`.

## Repro
`/Users/mrs/.hermes/cache/scratch/imported_deco/` (main.py imports `twice`
from deco.py). Build with:
  `PYTHONPATH=. python3 fire.py build -o main main.py`

## Files
- mojo/backend_gimple/module_gen.py (`_gmi_is_rebindable`,
  `_gmi_decorator_pass`, `gen_module_impl`)
- mojo/backend_gimple/emit_calls.py (`_lower_call`, imported-func home path)
