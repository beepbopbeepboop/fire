# mojo — shared middle-end + thin GIMPLE backend

## Layout (after restructure waves 1–3)

```
mojo/
  middle/                 # SHARED — no C/GIMPLE emission
    types.py                  ← gimple_ctypes.py
    exprtypes.py              ← gimple_exprtypes.py
    solvers.py                ← gimple_solvers.py
    coro.py                   ← gimple_gen_coro.py (async/generator AST desugar)
    infra_infer.py            ← shared half of gimple_gen_infra.py
    resolve_shared.py         ← shared half of gimple_gen_resolve.py
    funcs_shared.py           ← shared half of gimple_gen_funcs.py
    module_shared.py          ← shared half of gimple_module_gen.py
    stmts_shared.py           ← shared half of gimple_gen_stmts.py
    calls_shared.py           ← shared half of gimple_gen_calls.py
    loops_shared.py           ← shared half of gimple_gen_loops.py
    methods_shared.py         ← shared half of gimple_gen_methods.py

  backend_gimple/          # THIN — C/GIMPLE emission only
    emit_exprs.py             ← gimple_gen_exprs.py
    emit_stmts.py             ← gimple_gen_stmts.py
    emit_calls.py             ← gimple_gen_calls.py
    emit_loops.py             ← gimple_gen_loops.py
    emit_methods.py           ← gimple_gen_methods.py
    emit_infra.py             ← emission half of gimple_gen_infra.py
    emit_funcs.py             ← emission half of gimple_gen_funcs.py
    emit_resolve.py           ← emission half of gimple_gen_resolve.py
    module_gen.py             ← gimple_module_gen.py
    cpp_core.py               ← gimple_cpp_core.py
    cpp_async.py              ← gimple_cpp_async.py
    spec_gen.py               ← gimple_spec_gen.py

gimple_codegen.py              # public entry: GimpleGen + pipeline (stays at repo root)

formal/                        # independent ARM64 backend (unchanged)
```

## Compatibility

Every old path (`gimple_*.py` at repo root) is a re-export shim so existing
`import gimple_*` / `from gimple_* import X` keep working. New code should
import `mojo.middle.*` (analysis) or `mojo.backend_gimple.*` (emission).

## Rules

- `mojo/middle/**` must not call `_emit`, `_cpp_*`, `_new_bb`, or write C text.
- Backends consume the middle-end API (type lattice, solvers, desugar, resolution).
- `gimple_codegen.GimpleGen` remains the supported entry for the C backend.
- `formal/` (ARM64/Mach-O/Lean) is a separate backend and does not depend on
  `mojo/backend_gimple`; it may later consume `mojo/middle` for shared analysis.

## Tooling

- `tools/wave1_move_shared.py` — move pure-shared leaves + shims
- `tools/wave2_extract_shared.py` — extract shared defs from mixed modules
- `tools/wave2b_fix_deps.py` — pull missing module-level deps into shared
- `tools/wave2c_explicit_imports.py` — fix underscore free-vars (star-import gap)
