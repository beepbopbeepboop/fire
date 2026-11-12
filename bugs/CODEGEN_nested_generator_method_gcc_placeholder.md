# CODEGEN: generator methods and two nested async cases emit `<<< error >>>` into gcc input

Observed 2026-11-12 on `work/bug-codegen-tuple-slot-zero-in-collected` while running
`python3 test_gimple_generator_runner.py` (469 passed, 7 failed). All 7 fail the same way:
`gcc -fgimple compile of .c failed`, with the generated C containing a literal
placeholder:

    _t6 = mojo_gen_note (_t3, <<< error >>>);

and gcc then reporting `expected expression before '('` and `invalid argument to gimple call`.

## Failing cases (test_gimple_generator_runner.py)

- `nested_generator_method_reads_self`
- `nested_generator_method_self_write_visible_to_method`
- `nested_generator_method_self_and_local`
- `nested_generator_method_self_nonlocal_write_then_close`
- `nested_generator_method_same_name_two_classes`
- `two_nested_asyncs_shared_capture_through_sibling`
- `generator_callsite_self_field_kind`

Five are `nested_generator_method_*` cases (a generator created inside a struct method
`T.run`, capturing `self`). The other two are `two_nested_asyncs_shared_capture_through_sibling`
and `generator_callsite_self_field_kind`. In the case inspected, the second argument of
`mojo_gen_note` is the generator's start function, and it is the one that comes out as the
placeholder; the others were not dumped.

## Why this is not the tuple repr fix

These failures are in the gcc compile of the codegen's own output. The tuple repr fix
(`runtime/fire_coro_gen.c` `tuple_box`, `runtime/fire_runtime.c` `mojo_list_append_word`)
changes no Python codegen and no header, so the generated C for these cases is unchanged.

## Exact next step

1. Take `nested_generator_method_reads_self`, dump its generated C
   (`gimple_codegen.compile_to_gimple_with_cpp(src)[0]`), and find the `<<< error >>>`
   site in `mojo/backend_gimple/`: the emitter that builds the `mojo_gen_note` call for a
   generator created inside a method.
2. Make it resolve the start function's C name the same way the module-level and
   free-function nested cases do, and check the other six cases.
3. The seven tests are the quick check; run them with
   `python3 -c "import test_gimple_generator_runner as R; ..."` or the whole file.
