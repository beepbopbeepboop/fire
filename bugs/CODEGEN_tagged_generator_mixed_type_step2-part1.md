# CODEGEN_tagged_generator_mixed_type_step2-part1: pin the tagged box's kind tag

Class: **easy** (this doc lives in `bugs/`, the easy class).

## Parent

`bugs/hard/CODEGEN_tagged_generator_mixed_type_step2.md`, which is step 2 of
`docs/tagged_generator_mixed_type-plan.md`. That doc is being split; this is
its first part.

## Why this part exists

The parent doc says step 2 is "extend the tagged word box to carry a type
discriminator so a str/float value can be stored alongside the int", and names
`mojo/backend_gimple/emit_infra.py` and `gimple_codegen.py` as the files.

That runtime half is already done, and has been for a while. `MojoBox` in
`runtime/fire_runtime.c` already carries a `char kind` byte, and every kind
step 2 needs already has a producer and a consumer:

| kind | producer | reads it back |
|---|---|---|
| `'i'` | `mojo_id` token (an int that is pointer-shaped) | `mojo_box_int` |
| `'d'` | `mojo_box_from_double` | `mojo_box_double`, `mojo_repr_boxed` |
| `'p'` | `mojo_box_from_str` | `mojo_box_word`, `mojo_cstr_or_int_str`, `mojo_word_cstr_value` |
| `'s'` | a boxed bytes slot | `mojo_box_word` (the pointer), `mojo_repr_boxed` |
| `'b'` | `mojo_box_from_bool` | `mojo_box_int` (0/1), `mojo_repr_boxed` |
| `'n'` | `mojo_box_none` | `mojo_word_is_none`, `mojo_box_word` (the NULL word) |
| `'l'` | a boxed nested-list slot | `mojo_repr_boxed` |

So there is no box-format change to make here, and a worker must not invent a
second tag scheme next to this one. What is missing is a **test of the
contract**: nothing in the tree asserts that each constructor/accessor pair
round-trips, so a later change to `MojoBox` (or to one arm of the switch) is
free to break the very representation the other two parts of this split rely
on. This part adds that test and nothing else.

## Scope

Add one group to the existing C harness in `test_ptr_registry.py` (it already
`#include`s `runtime/fire_runtime.c`, so it can call the box functions
directly; build flags, the assert tripwire, `-O0`/`-O2`/ASan variants and the
group dispatch already exist there):

1. A `static void test_box_kinds(void)` in the `HARNESS` string, asserting each
   row of the table above:
   - `mojo_box_from_double(1.5)`: `mojo_is_boxed`, `mojo_box_double == 1.5`,
     `mojo_box_word` returns the box unchanged (a double has no int64_t
     spelling), `mojo_repr_boxed` is `"1.5"`.
   - `mojo_box_from_str("boxed")`: `mojo_is_boxed`, `mojo_box_word` is the
     original pointer, `mojo_cstr_or_int_str` is `"boxed"`.
   - `mojo_box_from_bool(1)`: `mojo_repr_boxed` is `"True"`,
     `mojo_box_int` is `1`.
   - `mojo_box_none()`: `mojo_word_is_none`, `mojo_box_word` is `0`,
     `mojo_repr_boxed` is `"None"`.
   - A bare (unboxed) string pointer: `mojo_is_boxed` is false and
     `mojo_box_word` returns it unchanged, so a consumer cannot mistake a
     non-box for one.
   Every returned `char *` above is owned by the caller (`mojo_repr_boxed`
   and `mojo_cstr_or_int_str` both hand back a fresh block for a box); `free`
   it so the ASan variant stays green.
2. `GROUP("boxkinds", test_box_kinds)` next to the other `GROUP` lines in the
   harness's `main`, and `"boxkinds"` added to `GREEN_GROUPS` so the ordinary
   `ptrreg` suite job runs it. Update the "`ptrreg` … covers the nine
   always-green groups" comment when the count changes.

No runtime change, no codegen change, and **no `tools/suite.py` change**:
`ptrreg` already owns `test_ptr_registry.py`, and `test_suite.py` checks that
a stated test status matches the registry.

## Files

- `test_ptr_registry.py` (the only file this part changes).

## Test

The new group is the test. It runs in the existing harness, so it gets the
assert-liveness tripwire, both `-O0` and `-O2`, and the clang ASan variant for
free.

## Acceptance

```
python3 test_ptr_registry.py --group boxkinds
python3 test_ptr_registry.py
```

Both must print `PASS` for `boxkinds` at every variant the machine can build
and end with `Results: N passed, 0 failed`. A failure here means the runtime
box does not carry the kind step 2's codegen parts assume, and those parts
must not be started until it is understood.

## Status

Not started. This part has no dependency on part 2 or part 3.
