# CODEGEN_sync_generator_struct_param_cpp_shadow: a sync generator with a struct-typed parameter emits invalid C++

Found 2026-10-29 while adding the method-nested self-capture (see
`CODEGEN_generator_function_Lib_test_test_frame.md`).

## Repro

    struct T:
        var k: Int
        def __init__(out self, k: Int):
            self.k = k

    def gen(t: T):
        yield t.k
        yield t.k + 1

    def main():
        var t = T(7)
        for v in gen(t):
            print(v)

    main()

Run through `test_gimple_generator_runner._build_generator_program` (or
`compile_to_gimple_with_cpp` then g++ on the `.cpp`):

    prog_gen.cpp: In function 'MojoGenerator* _mojogen_gen_start(T*)':
    error: declaration of '_mojogen_gen_Task t' shadows a parameter
        _mojogen_gen_Task t = _mojogen_gen_impl (t);
    error: cannot convert '_mojogen_gen_Task' to 'T*'

## What is happening

- The default stack-switch path (`mojo/middle/coro.py`) does NOT lower `gen`:
  `_eligible` requires every generator parameter to be scalar
  (`pann not in _SCALARISH` -> refuse). So `gen` falls through to the C++
  companion (`mojo/backend_gimple/cpp_async.py`), and `compile_to_gimple`
  reports no generator module at all (`C has __mgco_gen: False`).
- The C++ companion emits the start function with the struct parameter named
  `t`, and then names the generator task local `t` too, so the parameter is
  shadowed and the `_impl(t)` call receives a `Task` where a `T*` is expected.
  The C++ path's own param/local naming collides for any struct-typed param.

## Expected

Either a real lowering (a struct-typed generator parameter crossing the
`__mojo_gen_arg` ABI as a `T *`, the BUG-2026-030 erasure `_async_method_setup`
already uses), or an honest refusal naming the parameter. Not a g++ error on
generated code.

## Next step

1. In `cpp_async.py`, find where the start function's task local is named
   (`_mojogen_gen_Task t = _mojogen_gen_impl (...)`) and rename it so it cannot
   collide with a user parameter (e.g. a `__task` prefix), which turns the
   g++ error into a correct build for the struct-param case.
2. Then decide whether the stack-switch path should accept a struct param
   (the `_async_method_setup` route), so the default path lowers it. The
   method-nested self capture already re-types its hidden `self` that way
   (`_capture_self_into_generator`), which is the model to copy.
3. Pin with a `test_gimple_generator_runner.py` run case (expected `7\n8\n`).
