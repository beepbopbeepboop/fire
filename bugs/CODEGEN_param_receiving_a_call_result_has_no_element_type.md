# A parameter that receives a CALL RESULT has no element type, so a list of
# structs iterates as integers

## Status

OPEN, and NEW — measured 2026-10-02 while closing the struct-POINTER side of
`bugs/hard/CODEGEN_param_used_only_as_method_receiver.md` (that side is fixed;
see its doc). This is the CONTAINER axis of the same question, and it is a
different defect with a different mechanism, so it is its own doc rather than a
row in that one.

## What I ran, and what I saw

Single program, compiled + linked + run, CPython alongside:

```python
class T:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

def total(xs):
    s = 0
    for t in xs:
        s = s + t.numel()
    return s

def build(n):
    return [T(n), T(n + 1)]

def main():
    print(total(build(10)))

main()
```

```
CPython   21
compiled  8619471248        <- a heap address
```

`for t in xs:` walked the list and `t.numel()` degraded to the generic no-op
stub, so `s` accumulated a `T *`'s own bits. **Exit 0, no diagnostic** — the
same failure mode as the struct-pointer case, one level of indirection out.

Both one-hop neighbours of this shape are already correct, which is what makes
it a gap rather than a known limit:

| shape | CPython | compiled |
|---|---|---|
| `total(xs)` called `total([T(1), T(2)])` (a container LITERAL) | right | right |
| `total(xs)` called `total(build(10))` (a call result) | `21` | **an address** |
| `total(xs)` called `total(mylist)` where `mylist` is a local holding a list literal | right | right |

## What is believed

The element-type contract is collected from call sites in
`mojo/backend_gimple/module_gen.py`'s Pass 1.3d, and its argument observer is
`_static_arg_elems`:

```python
def _static_arg_elems(a, elem, nested):
    if isinstance(a, gimple_ctypes.IdentExpr):
        ...                       # a caller-scanned local
    if isinstance(a, gimple_ctypes.ListExpr):
        ...                       # a container LITERAL, provable on the spot
    return None, None
```

There is no `CallExpr` arm. So a parameter whose every call site is handed a
function's return value gets **no element evidence at all**, falls to
`int64_t`, and the `for t in xs:` loop reads the elements with
`mojo_list_get_int`. That is exactly what `_static_arg_elems`' own comment
claims was fixed — "a container LITERAL is provable on the spot, which is what
the IdentExpr-only walk above could not see either" — with the third arm of the
same idea never added.

The information needed to add it already exists: the same file's
`_callable_return_elem_type` / `_infer_return_elem_type` machinery resolves what
a function returns for a given argument list, and `_infer_param_types`' caller
arm (the "callee whose own parameter is a container is a container" rule) is
the one-hop version of the same link. So this is the `CallExpr` twin of a rule
that is already written down twice.

## The exact next step

1. Add a `CallExpr` arm to `_static_arg_elems` that resolves the callee's
   RETURN ELEMENT type rather than the callee's own parameter type, and feeds
   it through the existing `_record_param_elem(callee, pname, e, ne)`. Note the
   two are not interchangeable: `build`'s element type comes from its
   `return [T(n), T(n+1)]` list literal, not from any of its parameters.
2. Do it AFTER the ctor fixpoint if the answer needs `_ctor_lit_param_types`,
   or accept that a chain through a constructor takes the extra round the
   constructor fixpoint already takes — the ordering question is real and
   should be settled by measurement, not by whichever pass happens to run
   first.
3. Admission discipline unchanged and must stay: unanimity over all call sites,
   `int64_t` is never positive evidence (the existing comment is right about
   why — it is both the honest answer for a list of ints and this codegen's
   "cannot tell" default), and a conflict erases the real answer rather than
   merging it.
4. Regression tests belong in `test_gimple_runner.py` beside
   `gimple_ctor_param_used_only_as_field_then_receiver` and
   `gimple_ctor_param_struct_and_scalar_slots_are_independent`, which are the
   struct-pointer half of the same family.

## Related

- `bugs/hard/CODEGEN_param_used_only_as_method_receiver.md` — the
  struct-pointer half, whose own repro is fixed and pinned by
  `gimple_ctor_param_used_only_as_field_then_receiver`. Its
  "container-direction twin" sentence is about this, and the twin did not
  exist then and does not exist now.
- `bugs/UNTESTED.md` §3.3, on why a test that reports through its own stdout is
  a test that cannot fail: this failure is silent, and so is every test in the
  estate that would have caught it.