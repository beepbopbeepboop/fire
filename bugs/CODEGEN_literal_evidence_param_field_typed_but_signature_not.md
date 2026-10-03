# Literal evidence types an unannotated `__init__` param's FIELD, but not the emitted signature, so a float argument is truncated at the call

Found 2026-10-01 while fixing
`bugs/CODEGEN_unannotated_init_param_field_type_int64_residue.md` (deleted with
that fix). That fix moved the cross-module constructor evidence from the FIELD
it used to reach (by name) to the PARAM, which is what makes every field typed
from that param correct. **The float half was already broken before it, in one
module**, and is the same evidence mechanism reaching only half as far.

## What I ran

`gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c`, against CPython on the same text. ONE module, no
imports — so this is not the cross-module case the sibling doc was about.

```mojo
class B:
    def __init__(self, f):     # NOT annotated
        self.f = f
        self.g = f

def main():
    b = B(2.5)
    print(b.f)
    print(b.g)
```

```
CPython  : 2.5 2.5
compiled : 2.0 2.0        exit 0
```

## The generated C is the whole story

```c
  _t3 = (int64_t)2.5;          /* the CALL SITE coerces the literal to int64_t */
  B___init__ (_t2, _t3);
  ...
  _t4 = b->f;                  /* the field is declared double */
  _t5 = mojo_repr_float (_t4);
  mojo_print (_t5);
```

The field is `double` and the READ is right; the value arrived as the integer 2
and widened to 2.0. So the store and the declaration disagree, and only because
the evidence reached one of them.

## Mechanism

`module_gen.gen_module_impl`'s field pass types the PARAM into a local `pm` map
and hands it to `_gmi_collect_self_assigns`, which is what types every field
assigned from that param (`self.f` and `self.g` above). That `pm` map is local
to the loop: it never reaches the C SIGNATURE of `__init__`, which
`emit_calls.py`'s constructor path reads from `gen.func_param_types[init_fname]`
to coerce each argument (the `_init_full` loop, "Coerce each argument to its
declared `__init__` param C type"). An unannotated param has no annotation for
that table to read, so it is `int64_t` there and the literal is truncated at the
call.

Why the `str` shape of this does not show: a `char *` literal's address
round-trips through an `int64_t` param unchanged, so the field declared `char *`
still reads back as the same pointer and prints correctly. That is luck, not
correctness — and it is why the sibling doc's `str` reproducer looked "half
fixed" (`b.s` right, `b.n` a heap address) when in fact `b.s` was right for the
wrong reason.

## Next step

1. **Give the signature builder the same evidence.** `func_param_types` for a
   method is built where the method's params are lowered; the cross-module and
   same-module literal tables (`_ctor_lit_param_types`,
   `_xf_own_ctor_params`) are keyed `<struct>::<param>` and are complete by then.
   Seeding the unannotated `__init__` param's entry from them — and only where
   it is currently the `int64_t` default, so an explicit annotation still wins —
   is the one-line-shaped version, and it makes the argument coercion and the
   field declaration agree by construction rather than by luck.
2. **Assert the agreement instead of inferring it.** The failure mode is
   "declared type, store type, and read type are three different answers", and
   nothing in the suite compares them. A cheap check over
   `struct_field_types[s.name][f]` against the emitted `__init__` body — for each
   `self.f = <param>`, the param's ctype in `func_param_types` must equal the
   field's — would have caught this and would catch the next one. That is a
   suite-level invariant rather than a fix, which is why it is listed second.
3. The float case also needs the *value* half: `b.f = 2.5` assigned to an
   annotated `f: Float64` param works today, so only the unannotated inference
   is affected. Nothing else in the family is known to be broken.

There is no regression test for this yet (the dict suite in
`test_gimple_runner.py` covers homogeneous cases only). The case above is the
one to add when it is fixed, anchored on CPython's `2.5 2.5`.
