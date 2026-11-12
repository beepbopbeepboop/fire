# CODEGEN: generated C for nested generators / methods puts `#include` lines inside a function body

Filed 2026-11-12 by the module-level recursive generator round
(`CODEGEN_coro_module_level_recursive_generator_untyped_slot`, fixed in its own
commit). Seven cases in `test_gimple_generator_runner.py` fail at HEAD with the
same gcc error before that fix; they fail identically on the unmodified tree,
so they are not regressions from it.

## What is wrong

Generated C for these programs contains `#include` directives inside a function
body (`T_run`, `A_run`, `C_go`, `run_caller`). gcc rejects them:

    prog.c:14:29: error: expected expression before '(' token
       14 | #include <sys/types.h>
    prog.c:27:1: error: invalid argument to gimple call

The header prelude that `module_gen.py` emits at module top (`parts = [...]`,
around `module_gen.py:16010-16030`) is correct; the stray copy is produced by
a different emitter, on the path that lowers a nested generator or a generator
method defined inside a class/function.

## Failing cases (all `test_gimple_generator_runner.py`)

- `nested_generator_method_reads_self` (error at `prog.c:14`, in `T_run`)
- `nested_generator_method_self_write_visible_to_method` (`prog.c:15`)
- `nested_generator_method_self_and_local` (`prog.c:15`)
- `nested_generator_method_self_nonlocal_write_then_close` (`prog.c:17`)
- `nested_generator_method_same_name_two_classes` (`prog.c:13`, in `A_run`)
- `generator_callsite_self_field_kind` (`prog.c:11`, in `C_go`)
- `two_nested_asyncs_shared_capture_through_sibling` (`prog.c:1182`, in `run_caller`)

The `tagged_generator_mixed_type_container_refused` failure in the same file
is a different defect (an expected refusal that compiles); it is tracked by
`bugs/mid/CODEGEN_tagged_generator_mixed_type_step4-part2.md`.

## Reproduce

    python3 tools/memslot.py --gb 8 --label nested -- python3 test_gimple_generator_runner.py

Look for `FAIL  nested_generator_method_` and `FAIL  two_nested_asyncs_`.

## Exact next step

1. Dump the generated C for `nested_generator_method_reads_self` (the test
   source is in the runner) with `gimple_codegen.compile_to_gimple_with_cpp`
   and find the emitter that writes the `#include <sys/types.h>` /
   `#include <setjmp.h>` lines into `T_run`. A grep for the `#include` strings
   in `mojo/backend_gimple/` finds the module-top prelude only, so the stray copy
   is probably built from a joined header string or a per-method `parts` list.
2. Make that emitter write the function's body only, not the module prelude.
   Do not special-case the test names.
3. Verify with the seven cases above; `generator_callsite_self_field_kind` and
   `two_nested_asyncs_shared_capture_through_sibling` are the quickest to
   reproduce singly.
4. Delete this doc in the commit that makes all seven pass, and run
   `python3 tools/dangling_doc_refs.py --ratchet`.
