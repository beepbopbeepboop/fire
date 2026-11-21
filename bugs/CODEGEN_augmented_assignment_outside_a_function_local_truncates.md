# CODEGEN: an augmented assignment outside a function local still truncates a float

Found 2026-11-20 while landing the float augmented-assignment truncation fix
(that bug's own repro is a plain function local, and its `## Done when` is
met). The fix teaches the
local-type pre-pass to join the value type an augmented assignment rebinds
(`resolve_shared._infer_local_var_types_core`'s `aug_inferred`), but it
deliberately applies only to names the scan already records as local
bindings. A parameter, a `global`, and a module-level (`_toplevel`) name are
all typed outside that table, so the same `x /= 2` / `x += 0.5` still truncates
through their int64_t slot. Use CPython as the oracle.

## Repros

Each prints `4.5` (or `9.5`) in CPython and `4` (or `9`) in the compiled
binary, on this branch with the local fix applied and on master without it
(measured both ways, so this is pre-existing and not a regression from the
fix):

```python
def f(x):
    x /= 2
    print(x)
f(9)
```

```python
def f(x: Int):
    x /= 2
    print(x)
f(9)
```

```python
x = 9
def f():
    global x
    x /= 2
f()
print(x)
```

```python
x = 9
x /= 2
print(x)
```

`x += 0.5` on any of these is the same bug (`9` instead of `9.5`).

## Root cause

`_infer_local_var_types_core`'s `aug_inferred` table is joined into
`inferred` only for names already in `inferred`; a name whose only binding in
this body is the augmented assignment is left out on purpose, because a local
declaration from that join would shadow the type the parameter signature or
the module globals struct owns. The store then coerces the computed value to
that declared type: `emit_stmts._gen_stmt_AugAssignStmt` picks
`gen._type_of(tname)` for a parameter and `gen._global_dst_ctype(tname)` /
`gen._global_var_types` for a global and a `_top_level` name, and
`_safe_coerce_emit('double', 'int64_t', ...)` truncates 4.5 to 4.

So the value is computed correctly (`mojo_div_double`, a real `double`); only
the destination slot is the wrong C type. The fix is not "also add these names
to `aug_inferred`" — that shadows the parameter/global declaration.

## Next step

Give the parameter/global slot the rebinding type, or box/promote the value
the way a dynamic word is handled, without adding a shadowing local:

- parameter: the signature's C parameter type (`func.params`) has to widen to
  `double` for a name whose bindings include an augmented assignment (and the
  call sites must agree, since they coerce to the prototype);
- `global` / `_toplevel`: the field type is chosen in `module_gen`
  (`_global_var_types`, around the module-global declaration and
  `_pending_global_container_ctype`), so the augmented-assignment join has to
  reach that pass too;
- an annotated `x: Int` parameter is a deliberate static type in Mojo source;
  decide and record whether Python's rebinding rules win for the unannotated
  parameter (they must, since it is a dyn word) and what an annotation means
  here.

Check both the store (`print(x)` inside the function) and the return
(`return x` is a separate int-return-slot truncation, filed in
`CODEGEN_true_division_result_truncated_by_an_int_local.md`).

## Done when

Each repro above is a `test_gimple_matches_cpython` case in
`test_gimple_runner.py` that passes, and the cases print `OK` under
`python3 tools/pydiff.py`. Then delete this doc in the same commit and run
`python3 tools/dangling_doc_refs.py --ratchet`.
