# The self-host closure does not compile: ~40 distinct errors across nine modules, none of them one cause

Found 2026-10-02 by running the job a change to the compiler's own source owes,
`python3 tools/suite.py selfhost`, on `work/bugs4-6-c`. **Pre-existing on this
branch**: the same job fails identically on a pristine `git archive HEAD~3`
extraction of it, with the same first error at the same line, so nothing in this
doc arrived with the dict work that found it. Not mine and not in my claim area —
it spans six backend modules, `myinterpreter.py` and `build_stdlib_dylib.py`.

## What I ran

```
python3 tools/suite.py selfhost                    # this tree:  FAIL, 191s
git archive HEAD~3 | tar -x -C .tmp/base
cd .tmp/base && python3 test_selfhost.py            # the same tree, unmine:  FAIL, 209s
```

Both print the static half green and then

```
self-host closure: 61 modules, every generator/async lowered in place: True
self-host closure: 1422 functions, 1 of them declared in fire_runtime.h under a
  pinned C name; every such declaration matches its definition: True
Results: 1 passed, 1 failed
✗ self-host compile/link regressed (GCC error, ICE, undefined symbol, ...)
```

so the build half is what fails: the closure is emitted and then gcc rejects
it, module by module.

## What is left, as a census

Two errors have already been fixed by the commits that found this and are NOT
in the list below (they are named here only so the next reader does not
re-derive them): `next(<CallExpr>)` refused outright in `module_gen.py`, and 26
distinct `'_mojo_elem_repr_<Struct>' undeclared` link errors. What remains, with
counts from `build/suite.log`:

| count | error | module |
|---|---|---|
| 16 | `passing argument 1 of 'mojo_repr_list_ints' makes pointer from integer without a cast [-Wint-conversion]` | `mojo/backend_gimple/emit_methods.py` |
| 8 | `'struct _mojo_backend_gimple_emit_funcs_toplev' has no member named '_TYPE_MAP'` | `emit_funcs.py` |
| 6 | `'struct ..._emit_infra_toplev' has no member named '_module_loader'` | `emit_infra.py` |
| 4 | `'struct ..._module_gen_toplev' has no member named '_C_RESERVED_FUNCS'` | `module_gen.py` |
| 4 | `'struct ..._emit_funcs_toplev' has no member named '_FIXED_ARRAY_ANN_RE'` | `emit_funcs.py` |
| 3 | `non-trivial conversion in 'component_ref'` / `in 'var_decl'` | `myinterpreter.py` |
| 3 | `too many arguments to function 'myinterpreter_MojoFunction___call__'; expected 3, have 4` | `myinterpreter.py` |
| 3 | `'struct ..._emit_funcs_toplev' has no member named '_SELFHOST_EXTRA_FIELD_CACHE'` | `emit_funcs.py` |
| 3 | `'struct _build_stdlib_dylib_toplev' has no member named 'STDLIB_PATH'` / `'_IN_PROGRESS'` | `build_stdlib_dylib.py` |
| 2 each | the same "no member named" shape for `_BIN_OPS` (`emit_stmts.py`, `emit_exprs.py`), `_LIBM_FN_RETVALS` (`resolve_shared.py`), `_BUILTIN_RET_CTYPES` (`module_shared.py`), `_module_loader` (`funcs_shared.py`), `_FIXED_ARRAY_ANN_RE` (`module_gen.py`) | as named |
| 2 | `passing argument 1 of '_mojo_repr_list' makes pointer from integer` | `methods_shared.py`, `device_glue.py` |
| 2 | `'..._exprtypes_toplev' has no member named '_CPP_CALLABLE_CTYPE'` / `'_FLOAT_TYPES'` | `mojo/middle/exprtypes.py` |
| 2 | `conflicting types for '_compute_exc_descendants'; have 'MojoDict *(MojoList *)'` | `regex_compile.py`, `mojo/middle/types.py` |
| 2 | `has no member named 'self'` on a nested-function C name | `module_gen.py` |
| 1 | `assignment to 'int64_t' from 'MojoList *'` | `resolve_shared.py` |

## The one shape worth starting with

**A module-level imported CONSTANT read as a global that the module's toplev
struct does not have** is 8 + 6 + 4 + 4 + 3 + 2×5 ≈ 30 of the ~40, and it is
one mechanism: `_TYPE_MAP`, `_module_loader`, `_BIN_OPS`, `_C_RESERVED_FUNCS`,
`_FIXED_ARRAY_ANN_RE`, `_SELFHOST_EXTRA_FIELD_CACHE`, `_LIBM_FN_RETVALS`,
`_BUILTIN_RET_CTYPES`, `_CPP_CALLABLE_CTYPE`, `_FLOAT_TYPES` are all names
IMPORTED from another module and read at module scope. `mojo/middle/exprtypes.py`
is the clearest case: `_CPP_CALLABLE_CTYPE` and `_FLOAT_TYPES` come from its
line-13 `from mojo.middle.types import (...)`, and the compiled path declares no
field for either.

So the question to answer first is the one the `globals`-struct passes already
have machinery for: *why is an imported module-level constant not getting a
field in the reading unit's toplev struct, while a locally-assigned global does
(`STDLIB_PATH` in `build_stdlib_dylib.py` is the same shape and is assigned in
the same file)?* Until that is answered, the rest of the list is 30 symptoms of
it, and fixing them one at a time would be the "each error re-measured on its
own" pattern `bugs/` is supposed to stop.

## How to measure a fix

`test_selfhost.py`'s own build, not the suite wrapper, is the fast loop (~200s,
2 GB peak), and the comparison that matters is the ERROR SET, not the exit code:
`grep -oE "error: .*" build/suite.log | sort -u` before and after. The exit code
stays 1 for the whole wall above, so a change that removes three errors and adds
none looks identical to a change that removes none. The invariant to hold is
"no new error message", which is how the two fixes that ARE in this branch were
verified.