# A parameter used only as a method receiver is not resolved to a user struct

## Summary

An unannotated parameter that appears in a function body **only as the
receiver of a method call** is inferred as `int64_t`, not as a pointer to
the user struct. A field assigned from it inherits that, and every later
`self.<field>.<method>()` degrades to the generic no-op stub — which
returns whatever was in the temp, i.e. a pointer-sized garbage number,
with exit 0 and no diagnostic.

## Repro

```python
class T:
    def __init__(self, n):
        self.n = n

    def numel(self):
        return self.n


class L:
    def __init__(self, w):        # `w` is unannotated
        self.w = w                # field typed int64_t

    def numel(self):
        return self.w.numel()     # int64_t.numel() stubbed


def main():
    print(L(T(15)).numel())       # CPython 15; compiled 4312793248
```

## Why

`_infer_param_types`'s decision step has a branch that types a parameter
as `<Struct> *` — but it is gated on `len(fields_accessed) > 0`, i.e. on
the body actually reading a field THROUGH the param (`w.n`, `w.rows`).

A method receiver contributes no field accesses, so that branch never
runs. Nothing else in the decision step recognises a user struct either,
so the parameter falls through to the `int64_t` default.

The existing code already documents the failure mode, at
`mojo/middle/infra_infer.py`'s `@classmethod` note: *"a parameter used as
a method receiver — which contributes no field accesses, so the
struct-inference branch requiring `len(fields_accessed) > 0` never even
runs — was decided purely by the method's NAME"*. What is missing is the
resolution step, not the observation.

## Fix sketch

The receiver's type is determined by the **call sites**: `L(T(15))` passes
a `T *` in that position. The machinery for this already exists and is
already used for the container case:

- `_arg_struct_ptr_type(caller_name, a, caller_struct)` in
  `mojo/backend_gimple/module_gen.py` — the observed struct-pointer type
  of one call argument.
- `_collect_method_scalar_obs` / `_scalar_obs` — the same idea for scalars,
  with the "unanimous over all call sites, and only replaces a
  no-evidence type" policy already written out.
- The container-direction twin of this signal was added for
  `analyze_param_usage` (a param passed to a callee whose own param was
  inferred as a container is a container).

So the missing piece is one more observation set: collect
`(callee, param_index) -> {struct names}` from `_arg_struct_ptr_type`
over the call sites, and in the decision step type a param as
`<Struct> *` when the set is unanimous and the current type is the
`int64_t` default. The container rule added alongside it is the exact
mirror image, and the two belong in the same place.

Note the *element* type of a container-valued field already has this
linkage (`_struct_field_owners` + `_field_elem_types`); what is missing
is only the struct-POINTER-valued field case.

## Real impact

`test_llm/test_llm.py` is built on this shape throughout: `Linear.w`,
`Linear.b`, `Block.norm1/attn/norm2/mlp`, `Model.emb/blocks/norm_f` are
all user structs assigned from a local or a param. The compiled build
prints `parameters 25904820592` where CPython prints `993792`.

This is also the general "pass a dataclass to a constructor" shape, which
is common in real code, so the blast radius is wider than this one file.
