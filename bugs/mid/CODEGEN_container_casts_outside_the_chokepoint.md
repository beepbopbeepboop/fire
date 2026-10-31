# CODEGEN: container-kind casts outside the chokepoint are 41 against a baseline of 27

## Status (2026-10-31, OPEN, not started)

`make check` is red on `no-new-casts` (`test_no_new_container_casts.py`):

```
✗ 41 container-kind casts outside emit_resolve.py (baseline 27, +14 new)
```

The baseline of 27 was set at `37e8c2a2` (2026-10-27). Since then 14 more
`(MojoList *)` / `(MojoDict *)` / `(MojoSet *)` / `(MojoBytes *)` casts were
written outside the coercion chokepoint, mostly in the generator and iterator
work (`fce6f6ce`, `0f5630fe`, `902e17b0`, `363225c2`, `1c671724`, `97f2256e`).
They are casts in emitted C template strings, so they run in the generated
program.

Do not bump `BASELINE_COUNT`. The test's own ledger says a baseline bump to
record a new cast is a lie, and the right fix is to route each new cast
through `gen._coerce_to_type` (the R3 chokepoint). That is a codegen change,
so it owes the full gate and a byte-identical C check on a large succeeding
case.

## The sites (current tree, `test_no_new_container_casts.py`'s own scan)

Run `python3 test_no_new_container_casts.py` for the count. The list below is
from the same scan (`strip_prose`, the same `CAST_RE`); the 14 that are new
since `37e8c2a2` are the ones to route first.

```
mojo/backend_gimple/cpp_core.py:1269  return 'int64_t'
mojo/backend_gimple/cpp_core.py:1270  if _dct == 'MojoList *':
mojo/backend_gimple/cpp_core.py:1271  _leet = getattr(gen, '_cpp_list_local_elem_types', {}).get(e.obj.name)
mojo/backend_gimple/cpp_core.py:2596  gen._async_api,
mojo/backend_gimple/cpp_core.py:3482  and e.func.member in ('split', 'rsplit', 'splitlines')
mojo/backend_gimple/cpp_core.py:4391  # doesn't have. Conservatively stub `true`: real call
mojo/backend_gimple/cpp_core.py:4394  # callable(x): raise ...`), where a false positive here
mojo/backend_gimple/cpp_core.py:4812  # its documented source-interpretation path instead of
mojo/backend_gimple/emit_calls.py:974  """Reconstruct a dependent-return iterator factory call from the record
mojo/backend_gimple/emit_calls.py:3355  # unknown-kind LOCAL is recognised by its name (`_dyn_word_locals`).
mojo/backend_gimple/emit_calls.py:9038  # single-character string) is normalized to a real 1-char string via
mojo/backend_gimple/emit_exprs.py:3321  # mojo_cstr_slice (malloc + memcpy) just to immediately strcmp it
mojo/backend_gimple/emit_exprs.py:3341  lt, lv = ginf._unbox_float_param_operand(gen, node.left, lt, lv)
mojo/backend_gimple/emit_exprs.py:5014  return 'char *', t
mojo/backend_gimple/emit_loops.py:3798  <base>_value() deliberately mirror _gen_for_struct_iter's existing
mojo/backend_gimple/emit_methods.py:1212  return _RT['pack'], gen._call_expr(_RT['pack'], 'mojo_struct_pack_list',
mojo/backend_gimple/emit_methods.py:1268  zero = gen._new_val('int64_t', '(int64_t)0')
mojo/backend_gimple/emit_methods.py:4509  # pointer receiver is the IDENTITY — the pointer payload itself.
mojo/backend_gimple/emit_methods.py:5342  return 'char *', raw
mojo/backend_gimple/emit_methods.py:5990  # struct (struct constructors return `StructName *`, see
mojo/backend_gimple/module_gen.py:949  kinds_out = (_list_literal_slot_kinds(gen, v, _pk)
mojo/backend_gimple/module_gen.py:950  or kinds_out)
mojo/backend_gimple/module_gen.py:952  found = True
mojo/backend_gimple/module_gen.py:953  elif (isinstance(v, gimple_ctypes.IdentExpr)
mojo/backend_gimple/module_gen.py:1665  param_ctypes = ['MojoList *' if c == '...' else c
mojo/backend_gimple/module_gen.py:1666  for c in param_ctypes]
mojo/backend_gimple/module_gen.py:1667  ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
mojo/backend_gimple/module_gen.py:1668  parts.append(f"{ret} {mangled_name} ({ptypes});")
mojo/backend_gimple/module_gen.py:1699  def _emit_reflection_dispatch(self, parts):
mojo/backend_gimple/module_gen.py:1701  dataclasses.fields/asdict). Extracted from gen_module_impl so its
mojo/backend_gimple/module_gen.py:1703  gen_module_impl's ~6000-line body `sn` was cross-unified to int64_t
mojo/backend_gimple/module_gen.py:1797  # below) — self-hosted codegen has no mechanism that carries a
mojo/backend_gimple/module_gen.py:1798  # list's ELEMENT type across a plain function-call parameter
mojo/backend_gimple/module_gen.py:1799  # boundary (confirmed repeatedly this session: `.append()`'s own
mojo/backend_gimple/module_gen.py:14453  for _pth in self._ptr_helpers_needed:
mojo/backend_gimple/module_gen.py:15377  # need `_classattr_GimpleGen__X` globals + `_mojo_classattr_init` body
mojo/backend_gimple/module_gen.py:15378  # entries in whichever TU emits them, else `_alloc_GimpleGen`'s seed reads
mojo/backend_gimple/module_gen.py:15379  # a NULL global. `_class_attrs['GimpleGen']` was populated beside the
mojo/middle/coro.py:6073  
mojo/middle/types.py:1767  _mut = ci.mut_names
mojo/middle/types.py:1768  for _cap in ci.captures:
```

## Next step

1. For each new site since `37e8c2a2` (`git log -p 37e8c2a2..HEAD -- mojo/ gimple_codegen.py`
   and grep the added lines), route the cast through `gen._coerce_to_type`, or,
   where the cast is inside an emitted template, through the template's existing
   coercion helper.
2. Gate: `make gate` once at the end, plus a byte-identical C comparison of a
   large succeeding case before and after.
3. `python3 test_no_new_container_casts.py` must report `41 -> 27` or below
   with no new site.

## Related

- `tools/dangling_refs_baseline.py`, `test_no_new_container_casts.py`: the
  ratchet and its ledger.
