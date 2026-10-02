# CODEGEN: a method of a class defined inside a function cannot read that function's locals

**State: OPEN, unfixed.** Found 2026-10-02 while landing the fix for "a
`class` defined inside a function has no methods at all" (that doc is deleted
with its fix). This is the residue that fix leaves, it is a different shape,
and it is the reason the ordinary `cmp_to_key` factory idiom still answers
wrongly.

## What I ran and what I saw

```python
def mk(n: int):
    class C:
        def __init__(self, k: int):
            self.v = n + k
        def get(self):
            return self.v
    return C(1).get()

print(mk(10))
```

| | CPython | compiled |
|---|---|---|
| `mk(10)` | `11` | **`1`**, exit 0, no diagnostic |

`n` reads as `0` inside the hoisted `__init__`, and `self.v` is then `0 + 1`.
There is no message on stdout and no non-zero exit: the name is simply not in
scope in the emitted C, so it falls through
`mojo/backend_gimple/emit_exprs.py`'s unknown-identifier arm to
`_new_temp('int64_t')` + `(int64_t)0; /* ct param or undeclared: n */`.

The real stdlib instance is `Lib/functools.py`'s `cmp_to_key`:

```python
def cmp_to_key(mycmp):
    class K(object):
        def __lt__(self, other):
            return mycmp(self.obj, other.obj) < 0
    ...
    return K
```

Every one of `K`'s comparison dunders closes over the `mycmp` parameter.
`sort(key=...)` with `cmp_to_key` therefore compares with `mycmp` stubbed to 0
— which is `a < b` answering `0 < 0`.

## Why the fix that landed does not cover it

`mojo/backend_gimple/module_gen.py::_gmi_hoist_nested_structs` gives a nested
class a layout and emits its methods by APPENDING the class's `StructDef` to
the module-level statement list — because every consumer of the module's
struct set (the `struct_field_types` seed, `_merge_struct_inheritance`, the
`_alloc_X` helper, the `typedef struct X`, the method-body emission loop) reads
that list and nothing else. That is what makes the methods exist at all.

The emitted method is then an ordinary module-level C function
(`int64_t C___init__ (C *self, int64_t k)`), and `mk`'s frame is not reachable
from it: `mk`'s locals live in `mk`'s own C locals, and there is no
environment struct threaded through. So every free name in a nested class's
body that is not a module-level name is a hard 0.

## What it would take

A class environment, i.e. the closure machinery pointed at a class instead of
at a function. The pieces, and why each is not a one-liner:

1. **An env field per instance.** The hoisted class needs a hidden
   `_env` field of a per-class env-struct type, allocated by
   `_alloc_<Class>` and filled at the construction site from `mk`'s live
   locals. The env struct's name has to be derived from the (possibly
   renamed) hoisted class name, so it must be minted after
   `_gmi_hoist_nested_structs` has settled names — the closure env structs
   (`<lifted>_env`) are minted in `closures.discover_closures`, which runs
   BEFORE `gen_module_impl` and therefore before the hoist.
2. **A capture list per nested class**, i.e. the free names of each method
   body minus `self` and the module-level names, resolved against the
   ENCLOSING function's scope. `closures.discover_closures` already computes
   exactly this for a nested `def` (`_scan_for_closures(ctx, outer_name,
   outer_scope, body)` with `outer_scope` built from the enclosing function's
   params and body); a nested class needs the same walk over `sd.methods`
   instead of `inner.body`, with `outer_name` keyed `(enclosing, class)`.
3. **Every method takes the env**, as a leading `env *` after `self`, and
   every method CALL SITE passes `recv->_env`. The call sites go through
   `_lower_MemberExpr` / `_lower_bound_method_call_value` /
   `mojo_fnptr_call_N` (a bound method of the class), so the parameter is a
   per-class property: the emitted prototype, the definition, and the call all
   have to agree or gcc rejects the TU.
4. **The ownership half.** `ownership_destruct.lambda_value_owned`'s rule —
   "after the binding, the only acceptable mention of the name is as the
   CALLEE of a call" — has no answer for an env reachable from every instance
   of a class, and `bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md`'s
   OPEN 1/OPEN 2 are the same question one level down for functions. Freeing
   wrongly here is a use-after-free on every instance, not one closure.

An honest interim is a REFUSAL rather than a silent 0: a nested class with a
method that reads a name that is neither module-level, nor a parameter of that
method, nor `self`, nor a field of the class is a compile error. That is a much
smaller change than the feature (it is a check over `sd.methods`' free names
against the enclosing function's locals, which
`_gmi_local_binding_names` already collects) and it converts a plausible wrong
number into a build failure — but it will refuse real code, including
`functools`, so it wants `compile_stdlib.py`'s `U` count measured first, per
CLAUDE.md's rule about type-resolution refusals.

## Regression test (when it lands)

`test_gimple_runner.py`, `test_gimple_matches_cpython` or
`test_gimple_stdout`, next to `gimple_nested_class_methods` /
`gimple_nested_class_in_every_body` — the fixture above plus the
`cmp_to_key` shape (a nested class whose method reads the enclosing
PARAMETER), asserted against CPython's exact text. A compile-only assertion
is worthless here: this compiles, links and exits 0.
