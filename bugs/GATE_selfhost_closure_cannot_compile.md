# GATE: the self-host closure cannot compile

**Job:** `selfhost` (`test_selfhost.py`) and `bootstrap-stage2-cc`
(`make stage2/mojo`). Neither tracks a bug doc — this is one.

## Symptom

`fire.py --dump-full fire.py` produces a `fire.ci` that gcc rejects, and
`test_selfhost.py`'s build half fails, so the produced binary cannot compile a
two-line program. Four independent defects, each fixed on master:

1. **Missing hardcoded AST struct fields** (`5b82f8169`). The core AST layouts
   come from a hardcoded map in `mojo/backend_gimple/module_gen.py`, not from the
   dataclasses. Fields added to a dataclass without a row there make the
   generated C reference a member the struct does not have:
   `Parser._lazy_import_blockers`, `Parser._last_bracket_variadics`,
   `ImportStmt.lazy`, `FromImportStmt.lazy`,
   `FunctionDef.variadic_bracket_params`, `StructDef.where_clause`,
   `StructDef.bracket_types`.
2. **A user struct's own method named like a raw-pointer protocol method was
   hijacked** (`5b82f8169`). `_lower_method_call`'s raw-pointer branch fired on
   any `ot.endswith(' *')` receiver whose method was in `_RAW_PTR_METHODS`, so
   `_LazyImportTarget.load` compiled `self.load()` to `*self` — the call
   dropped, the struct copied by value.
3. **`_resolve_import_module` had an order-dependent return type**
   (`5b82f8169`). `_TypesProxy *` beside `_MojoModuleObject *`; two distinct
   pointers join to the box and a pointer and the box join to the pointer, so
   the inferred type differed between inference passes while the emitted
   prototype kept the first one.
4. **`x[slice(a, b, c)]` was not lowered as a slice** (`29633ff1a`). The index
   arrived as a call to the `slice` builtin; `_lower_subscript` had no arm for
   it, so it cast the slice object to an integer and read ONE element, and the
   bare `slice` symbol was undefined at link time.
5. **`gimple_codegen.compile_to_gimple_parallel_frozen` was not routed to the
   wrapper** (`ad5ee5fa1`). The generic self-host sibling-alias re-dispatch ran
   before the dedicated branch and stripped the qualifier, emitting a bare
   call whose definition is mangled.

## Reproduce

```
python3 fire.py fire.py --dump-full && sed -i '' 's/^int main/int mojo_main/' fire.ci \
  && gcc-mp-15 -Os -g -fgimple -ftrivial-auto-var-init=zero -Iruntime -c -x c fire.ci -o /tmp/fire.o
python3 test_selfhost.py
```

## Next step

`test_selfhost.py` still fails after 1-5: `mojo/middle/comptime.py:470`
(`if isinstance(node, FloatLiteral): return node.value`, added by `13b16397d`)
makes `eval_const`'s inferred return type `char *` while one branch returns a
`double`, so the return cast was `(char *)<double>` — gcc: "cannot convert to
a pointer type". Fixed in `emit_resolve._sce_simple_emit` (`759f02c2e`): a
float→pointer coercion now goes through int64_t, the same two-step every other
scalar→pointer coercion in that file uses. The int→pointer spellings gcc
accepts with a warning; a float→pointer is rejected outright, which is why only
that source kind needed a branch.

Longer term `eval_const` is the wrong shape for this backend: it returns
bool/int/float/str/tuple from one function, so its return slot can never be a
single C type. The float branch is the first one gcc refuses outright, but the
int and bool branches are only accepted by accident.

## Status

2026-11-12: 1-6 landed. Fresh `fire.ci` compiles clean; `make stage2/mojo`
links an 18 MB binary; no bare `compile_to_gimple_parallel_frozen` call
survives. `test_selfhost.py` re-running.
