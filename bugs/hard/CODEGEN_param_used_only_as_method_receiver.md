# A parameter used only as a method receiver is not resolved to a user struct

## Status (2026-10-02 — this doc's own repro is FIXED and was already; the FORWARDING chain this doc's fix sketch describes did not exist and now does)

### What was already fixed, and is pinned

The doc's exact repro is a passing test in `test_gimple_runner.py`:
`gimple_ctor_param_used_only_as_field_then_receiver`, which is this program
verbatim and asserts `"15\n"`. Re-measured 2026-10-02 with the whole 25-shape
matrix from the 2026-09-26 entry: the doc's repro, the free-function variant
(`def mk(t): return L(t, 'hi')`), a plain function whose parameter is only
ever a receiver (`def f(w): return w.numel()`), and the one-hop
`def f(w): return L(w).numel()` all compile, link, run and agree with CPython.

So the doc's "the missing piece is one more observation set" was already true
of this tree: `_struct_obs` in `mojo/backend_gimple/module_gen.py` collects
`(callee, param) -> {struct names}` from `_arg_struct_ptr_type` over the call
sites, and Pass 1.3d-struct applies it to a parameter the callee's body uses
as a method receiver or passes to a constructor. The parameter's own C
signature is still `int64_t` in the doc's repro — the field it feeds is `T *`
and the body casts through it — so the FIELD is what the fix delivers, and
that is what the answer depends on.

### What this pass fixed: the forwarding chain

The doc's fix sketch ends: *"collect `(callee, param_index) -> {struct names}`
from `_arg_struct_ptr_type` over the call sites, and in the decision step type a
param as `<Struct> *` when the set is unanimous"*. That existed. What did not
exist is the hop **across free functions**, and without it a dataclass
travelling through two thin wrappers stopped dead:

```python
def a(w): return L(w)
def b(w): return a(w).numel()
b(T(9))            # CPython 9; compiled 4377466752 — a T *'s own bits
```

`w` is in `b`'s body only as `a(w)`'s argument, and **nothing calls `a`
directly**, so `a`'s parameter has no call-site evidence at all. Two changes
in `mojo/backend_gimple/module_gen.py`:

* Pass 1.3d-struct's admission arm is widened from "used as a method receiver
  or passed to a constructor" to "**or forwarded as a bare-identifier argument
  to any call in this body**". That is the same one-hop shape the constructor
  arm already had, one level of indirection out.
* a bounded propagation fixpoint (four rounds, the same bound and the same
  reasoning as the constructor fixpoint below it) copies a resolved
  `<Struct> *` across a bare-identifier forward: `b.w = T *` ⇒ `a.w = T *`.
  Every gate the constructor twin uses is reused unchanged — an explicit
  annotation wins, a defaulted parameter keeps its default-derived type, only
  a no-evidence type is replaced — plus the one this hop needs and the twins
  do not: **contrary call-site evidence vetoes it**. That veto is what keeps
  the chain honest, and it is the reason the property has no assertable
  observable: see `bugs/CODEGEN_polymorphic_struct_param_degrades_to_a_pointer.md`.

Two regression tests, `gimple_struct_ptr_param_forwarded_through_two_free_
functions` and `..._through_three_free_functions`, so the fixpoint's BOUND is
asserted rather than assumed.

### Measured, 2026-10-02

| shape | CPython | before | after |
|---|---|---|---|
| the doc's repro | `15` | `15` | `15` |
| `b(w) -> a(w) -> L(w)` | `9` | an address | **`9`** |
| `c(w) -> b(w) -> a(w) -> L(w)` | `11` | an address | **`11`** |

`test_gimple.py` 368 passed / 0 failed, `test_gimple_generator_runner.py`
398/0, and `test_gimple_runner.py` 292 passed / 10 failed with the **identical
ten failures** as this branch's base commit (verified by running the base
tree's own copy from `git archive HEAD`): `_emit_dict_int_value_store` missing
on `GimpleGen` (4), a bool-annotated struct field printing as `1`/`0` (2),
`sorted(key=)` over runtime-built strings, a tuple dict key, and a peak-RSS
ceiling. None of the ten is in this change's blast radius, and none moved.

### What remains, and where it went

The doc's blast-radius claim ("the general 'pass a dataclass to a
constructor' shape, which is common in real code") is now true for the
STRUCT-POINTER axis and false for the CONTAINER axis, which is a different
defect with a different mechanism and has its own doc:

* the CONTAINER axis was a separate defect and is now FIXED, as its own doc:
  a parameter handed a function's RETURN VALUE got no element type at all
  (`total(build(10))` printed an address where CPython prints `21`), because
  `_static_arg_elems` had arms for a caller-scanned local and for a container
  literal and none for a `CallExpr`. Its "container-direction twin" sentence
  above is about this, and the twin existed from the moment this doc was
  written until `_static_arg_elems` grew a `CallExpr` arm resolving the
  callee's RETURN element type. Pinned by `test_gimple_runner.py`'s
  `gimple_param_receiving_a_call_result_has_an_element_type` (the dict-value
  shape) and `gimple_param_elem_from_a_call_result` (the element-type one),
  which are two assertions of the same arm on the two things it has to get
  right. The twin's own doc was deleted with its fix, so there is no path to
  repair here.
* `bugs/CODEGEN_polymorphic_struct_param_degrades_to_a_pointer.md` — a
  parameter called with two DIFFERENT structs has no representation, and the
  correct unanimity refusal leaves it at `int64_t`, so both calls print a
  pointer. Pre-existing, measured before and after this change.

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
