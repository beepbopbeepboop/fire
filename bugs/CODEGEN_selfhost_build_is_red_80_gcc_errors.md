# The self-host build is red: 80 distinct gcc errors in the compiled closure

**State: OPEN, measured, not fixed.** Found 2026-10-02 while verifying
`work/bugs4-4-c` with the `selfhost` job that a change to the compiler's own
source owes. Not that branch's work and not caused by it — see "Not a
regression", which is measured, not asserted.

## What I ran

```sh
python3 tools/memslot.py --gb 8 --label selfhost-head -- python3 test_selfhost.py
```

which is `python3 tools/suite.py selfhost` (`tools/suite.py:1229`) without
the runner. Peak 2.0-2.2 GB, ~260 s.

## What I see

```
  self-host closure: 61 modules, every generator/async lowered in place: True
  self-host closure: 1423 functions, 1 of them declared in fire_runtime.h under a pinned C name; every such declaration matches its definition: True
Results: 1 passed, 1 failed
✗ self-host compile/link regressed (GCC error, ICE, undefined symbol, or the produced binary cannot compile)
```

Both STATIC halves are green; the build half is not. `build()` in
`test_selfhost.py` returns `""` and prints nothing of its own, so the verdict
line is the only symptom — the 80 errors are in the gcc output above it, and
they fall into three shapes:

1. **`'_mojo_elem_repr_<Class>' undeclared (first use in this function)`** —
   30 of the 80. The element-repr shim is referenced but never emitted, in
   `fire_compiler.py`, `ast_rewriter.py`, `myinterpreter.py`,
   `mojo/backend_gimple/{cpp_core,emit_calls,emit_loops}.py`,
   `mojo/middle/{coro,funcs_shared,infra_infer,lambdareduce,solvers,offload}.py`,
   `regex_compile.py`. The declaration is emitted only for a struct this
   compile REFLECTS (one with at least one field — see
   `mojo/backend_gimple/module_gen.py`'s `reflect_structs` and
   `emit_exprs.py`'s `_struct_elem_repr_shim`, which returns '' for a
   field-less one), so the reference and the emission disagree about which
   classes qualify.
2. **`'struct _mojo_<module>_toplev' has no member named '_X'`** — 15 of the
   80, where `_X` is a module-level constant or an imported module alias
   (`_C_RESERVED_FUNCS`, `_TYPE_MAP`, `_BIN_OPS`, `_SELFHOST_EXTRA_FIELD_CACHE`,
   `_FIXED_ARRAY_ANN_RE`, `_CPP_KEYWORD_FIELDS`, `_PSEUDO_DUNDER_ATTRS`,
   `_UNKNOWN_FIELD_CTYPE`, `_BUILTIN_RET_CTYPES`, `_LIST_RETURNING_METHODS`,
   `_STR_RETURNING_METHODS`, `_SCALAR_FLOAT_TYPES`, `_LIBM_FN_RETVALS`,
   `STDLIB_PATH`, `_IN_PROGRESS`, `TEST_PATH`, `_module_loader`, and
   `_mojo_middle_exprtypes_toplev` missing `_CPP_CALLABLE_CTYPE`). These read
   a module global that the toplevel struct does not carry, so the global was
   never recorded as one.
3. **Type mismatches** — the rest: `assignment to 'int64_t' from 'MojoList *'`
   / `'MojoDict *'` (`-Wint-conversion`), `assignment to 'MojoSet *' from
   incompatible pointer type 'char *'`, `passing argument 1 of '_mojo_repr_list'
   makes pointer from integer without a cast`, `conflicting types for
   '_compute_exc_descendants'`, `too many arguments to function
   'myinterpreter_MojoFunction___call__'; expected 3, have 4`, and
   `invalid use of undefined type 'struct _mojo_middle_solvers_toplev'`.

Shapes 1 and 2 look like the same class of thing — a thing that is supposed
to be emitted for a module and is not — and both smell like fallout from the
recent "one implementation per fix" consolidation, but nothing here measures
which change introduced them and this file does not claim to.

## Not a regression from this branch's work

`work/bugs4-4-c` changes `runtime/fire_runtime.c`,
`runtime/fire_runtime.h`, `gimple_codegen.py`,
`mojo/backend_gimple/emit_exprs.py` and `mojo/backend_gimple/module_gen.py`.
Reverting exactly those five to the branch's HEAD and re-running gives:

```
$ diff .tmp/err_head.txt .tmp/err_mine2.txt && echo IDENTICAL
IDENTICAL
```

80 distinct `error:` lines on each side, byte-identical after normalising the
`file:line:col` away. So the reds are this branch's inherited state, not
something the work that found them introduced, and the integrator should read
this as a pre-existing gate failure.

## Why it matters more than a normal red

`selfhost` is in `check` and in `gate` and carries NO `expect=` marker, so
this is an **undeclared** red — `CLAUDE.md`'s "there is no undeclared red" is
a statement about the registry, and this is a counterexample to it right now.
Everything downstream of the self-host build is therefore unmeasured too:
`mojoc`, `native-dumpfull` (`expect=`ed, but for a different reason),
`bootstrap-stage1-*` and `bootstrap-stage2-cc`. In particular
`bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md` — 226 KB of history
about the native-vs-reference comparison — cannot be advanced at all while
the compiler does not compile itself.

## Next step

1. Shape 1 first: it is 30 of the 80, it is a single missing emission, and
   every one of the 30 is the same question. Find where `_mojo_elem_repr_X` is
   DECLARED (`module_gen.reflect_structs`) and where the DEFINITION is
   emitted, and make the two agree on which classes qualify. The reference
   side is `emit_exprs.py`'s `_struct_elem_repr_shim`, which already returns
   '' for a field-less struct — so the bug is that something still asks for
   the shim of a class it has decided not to reflect.
2. Then shape 2, which is the same question asked of module-level constants:
   which pass is supposed to put `_C_RESERVED_FUNCS` and its 16 siblings into
   the module's `_toplev` struct, and why does the reader assume it ran.
3. The type mismatches are third; several of them are the same boxed-pointer
   fact as shape 2 (`-Wint-conversion` from a container) and may go with it.

Cheapest bisect: `git log -S "_mojo_elem_repr" --oneline -- mojo/backend_gimple/module_gen.py`
and the same for the `_toplev` struct's member list, and check whether the
emitting side moved without the reading side.
