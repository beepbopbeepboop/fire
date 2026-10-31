# A method receiver whose type could not be resolved returns the receiver's own pointer bits

## Status 2026-10-29 — planning round (the guide; no code landed here)

Measured on the tree after the list-copy and class-attribute fixes: this is
the one red case left in `test_gimple_runner.py` (the gate's `gimplerunner`
job). It prints `4374860544` / `4374860208` where CPython prints `2` / `2`.
The generated C for `L.numel` is still `_t1 = self->w; _t2 = _t1;
/* int64_t.numel() stubbed */`.

Decision (recommended, no further input needed): dispatch by a GENERATED
switch on `__mojo_type_id`, not by a runtime table in `fire_runtime.c`. The
type ids are compile-time constants already (`_struct_type_id(sn)`), and
`_emit_reflection_dispatch` (`mojo/backend_gimple/module_gen.py`, starts at
line 1693) already emits exactly that comparison for `_mojo_dispatch_getattr`
and its siblings. A runtime registry would add state that ASLR and the
allocator can disturb, for no gain.

Plan, in the order it has to land:

1. `mojo/backend_gimple/module_gen.py`, the constructor observation pass
   (around lines 10789-10945). `_ctor_scalar_obs` keeps only the FIRST type seen
   for `<Struct>::<param>`, and a second, different one only sets
   `_ctor_scalar_conflict[_skey] = True`, discarding the candidate. Keep the set
   instead: add every observed `<Struct> *` to `_ctor_struct_cands[_skey]` in
   both observation loops (the `__init__`-call loop and the caller-body loop).
   A scalar conflict keeps its current `True` behaviour.
2. Same file, where a slot is left at `int64_t` because of a struct-pointer
   conflict (the `_ctor_lit_param_types` writer, around line 10940): record
   `self._poly_slot_cands[_skey] = sorted(cands)`. The field `w` of `L` has the
   same key (`L::w`), because the param is stored under its own name.
3. Same file, beside `_emit_reflection_dispatch`: for each method name `m` that
   ≥2 candidates define, emit `static int64_t _mojo_poly_<m>(void *o, ...)` that
   switches on `_struct_type_id(S)` and calls `S_<m>((S *)o, ...)` for each
   candidate, with a forward declaration next to the struct prototypes. REFUSE
   with a named compile error when the candidates disagree on the method's
   return type or arity. A silent wrong answer is the failure this removes.
4. `mojo/backend_gimple/emit_methods.py`, `_lower_struct_method_call` (line
   ~6894). When `ot` is `int64_t` and the receiver is `self.<f>` or an
   IdentExpr whose slot is in `_poly_slot_cands`, and every candidate has
   `{S}_{m}` in `func_return_types`, lower to `_mojo_poly_<m>(recv, args...)`.
   Before editing, confirm which of the two stub emitters fires for this
   shape: `emit_calls.py:4419` (`{fname}() stubbed`) or `emit_methods.py:2564`
   (`int64_t.<m>() stubbed`). The C above says the second.
5. Runtime: nothing. A tag that matches no candidate must raise through
   `mojo_raise_attribute_error(m)`, the same real AttributeError a missing
   dynamic attribute raises, so `except AttributeError:` still catches it.

Tests, in `test_gimple_runner.py` beside
`gimple_ctor_param_polymorphic_slot_stays_unresolved`:

- `gimple_ctor_param_polymorphic_slot_reads_receiver` (already there, `2`/`2`)
  must pass.
- A three-candidate variant whose method takes an argument (`return self.n * k`),
  checked against CPython.
- A refusal: two candidates whose `numel` return types differ must fail with
  the named compile error, not compile.
- A unanimous slot still resolves statically: the generated C for it must not
  contain `_mojo_poly_`.

Risk: `module_gen.py` and `emit_methods.py` are on the compiled path, so this
owes the full `make gate` (the integrator runs it) and not only the runner file.
Nothing known blocks it.

**State: OPEN. Found 2026-10-01 while fixing
the constructor direction of the method-receiver struct-pointer fix
(commit ddf415104, doc deleted in the same commit). Not caused by that fix — a genuinely
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
the method-receiver struct-pointer fix (commits ddf415104, 6379400b1) and the
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
  the method-receiver struct-pointer fix (ddf415104), and is worth an
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