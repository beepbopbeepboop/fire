# A method receiver whose type could not be resolved returns the receiver's own pointer bits

**State: OPEN. Found 2026-10-01 while fixing
`bugs/hard/CODEGEN_param_used_only_as_method_receiver.md`'s constructor
direction (doc deleted, same commit). Not caused by that fix — a genuinely
polymorphic slot was never resolvable and still is not; what changed is only
that the UNanimous case now resolves, which makes the unresolvable case
visible as what it is.**

## What I ran

`.tmp/b1/poly.py`, compiled and run through `test_gimple_runner.py`'s own
`compile_mojo_to_gimple_exe` (single-TU `compile_to_gimple`, no imports):

```python
class T:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

class U:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

class L:
    def __init__(self, w):
        self.w = w
    def numel(self):
        return self.w.numel()

def main():
    print(L(T(2)).numel())
    print(L(U(2)).numel())

main()
```

## What I saw

```
CPython:   2
           2
compiled:  4333885904
           4333885936        (both rows, both runs, different each run — ASLR)
exit 0, no diagnostic
```

The two numbers are the two different heap addresses the `T *` / `U *` had.
`L.__init__`'s `w` is passed a struct pointer at both call sites, and the
observation is NOT unanimous (`T *` at one, `U *` at the other), so the
documented rule leaves the slot at the `int64_t` default —
`bugs/hard/CODEGEN_param_used_only_as_method_receiver.md`'s fix and the
`Pass 1.3d-struct` loop above it both refuse on disagreement. That part is
correct.

The bug is what happens next. `self.w` is an `int64_t`, and
`_lower_struct_method_call` sees an `int64_t` receiver, finds no matching user
method, and emits the generic no-op stub:

```c
int64_t __GIMPLE L_numel (L * self)
{
  int64_t _t1;
  int64_t _t2;
  ...
  _t1 = self->w;
  _t2 = _t1;  /* int64_t.numel() stubbed */
  return _t2;
}
```

whose result is whatever was in the temp — i.e. the receiver's own bits.
CPython raises `AttributeError: 'int' object has no attribute 'numel'` only
because the "int" is this codegen's own fiction; in real Python `w` is always
a `T` or a `U` and both have `numel`, so the honest answer is `2` twice.

## Why the stub exists at all, and why it is the wrong default here

The no-op stub is a deliberate fallback: it is what makes an unresolvable
receiver compile instead of failing the build, and it was the right trade when
every unresolvable receiver really was opaque. It is now the wrong default for
the POLYMORPHIC receiver case specifically, because the two shapes are
distinguishable at compile time:

- a receiver whose slot has NO struct observation anywhere is genuinely opaque,
  and the stub is a reasonable "I cannot represent this" answer;
- a receiver whose slot has a **conflicting pair** of struct observations is a
  *polymorphic dispatch site* — the program is correct, and the only thing
  missing is a runtime choice among the observed structs' own mangled methods.

The runtime already has a dispatch helper for the second shape:
`_mojo_dispatch_getattr(void *, char *)` takes the receiver and the attribute
name, and every dynamic-attribute read goes through it. A method call has the
same ingredients. What is missing is the *selection* — knowing which candidate
structs to try — and the codegen has that list already: the conflict is
recorded in `_ctor_scalar_conflict` / `_struct_obs`' per-param sets, both of
which hold every observed `<Struct> *` for the slot.

## Exact next step

In `_lower_struct_method_call` (`mojo/backend_gimple/`), for a receiver whose
C type is the unresolved `int64_t` default, consult the slot's recorded
observation set:

- empty set → keep today's stub (genuinely opaque);
- a single `<Struct> *` → this can no longer happen after
  `CODEGEN_param_used_only_as_method_receiver`'s fix, and is worth an
  assertion rather than code;
- two or more `<Struct> *`s → emit a polymorphic receiver: pass the boxed
  receiver and the method name to a runtime helper that reads
  `__mojo_type_id`, matches it against a static table of the candidate structs
  (their `__mojo_type_id` value is already assigned by `_alloc_X`, so the table
  is a compile-time constant array), and tail-calls that struct's own mangled
  method. No such table exists yet; it is a small addition to
  `runtime/fire_runtime.c` beside the `_PtrReg` registries, and the same
  mechanism would serve a polymorphic free-function parameter.

Two things this needs before it can be attempted honestly:

1. **The observation sets must be readable at method-call lowering time.** They
   live on `gen` during `gen_module_impl`'s inference passes; `_ctor_lit_param_
   types` already survives into codegen (`_ctor_lit_param_types` is read by
   the field-write pass), but the *conflict* cases are discarded there, so a
   name for the candidate set has to be carried alongside it.
2. **A regression test that can tell the two outcomes apart**, which is why
   this bug doc exists rather than a test in `test_gimple_runner.py`:
   `gimple_ctor_param_polymorphic_slot_stays_unresolved` deliberately uses a
   method that does NOT read the field, because a resolved slot and an
   unresolved one both print `0` there. The receiver-reading variant belongs
   next to this doc's fix, asserting CPython's `2` / `2`.

## Blast radius

Every dynamically-typed method call whose receiver is a struct-typed parameter
or field reaches this, and the failure is the silent kind: no diagnostic, exit
0, a pointer-sized decimal in the output. It is the same failure
`CODEGEN_cross_function_container_element_type.md` reports from the container
direction and `CODEGEN_method_call_on_struct_param_mistyped.md` reported from
the free-function direction — this is the last remaining shape of that family,
the one case where the type genuinely cannot be decided statically and so has
to be decided at runtime instead.