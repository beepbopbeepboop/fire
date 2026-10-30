# CODEGEN: a tuple `for` target in a compiled generator emits invalid C++

**State: OPEN. Found 2026-10-29 while working on
`COMPILE_FAIL_Tools_scripts_summarize_stats`. Not fixed.**

## Repro

```python
def iter_tables(base: int):
    for name, den in [(1, 2), (3, 4)]:
        yield Section("sec", name + den + base)
```

(Any generator whose `for` target is a tuple over a literal iterable.)

## Observed

`python3 fire.py build` falls to the C++ compile of the generator with:

```
for (auto name, den : {{1, 2}, {3, 4}}) {
```

g++ rejects it: `declaration of 'auto name' has no initializer` and
`multiple declarations in range-based 'for' loop`. The `den` in the body is then
also undeclared. So the module hard-fails at the C++ stage instead of refusing
honestly, which is worse than a fallback to source.

## Expected

Either the loop lowers (`for (auto _t : ...) { int64_t name = _t[0]; ... }`, or
the index form the emitter already uses for `range`), or the generator refuses
with an unsupported-shape message so the module falls back to source.

## Where

The C++ coroutine loop emitter in `mojo/backend_gimple/cpp_core.py`, which emits
the range-for `for (auto <target>, <target> : <iterable>)`. It needs to handle a
tuple target as it does on the plain GIMPLE path, or refuse it.

## Next step

1. Reproduce with the snippet above through
   `gimple_codegen.compile_to_gimple_with_cpp(src, do_imports=False)` and confirm
   the `for (auto name, den` text in the returned C++.
2. In the loop emitter, bind each slot from the element, or raise
   `_UnsupportedGeneratorShape` for a tuple target. Prefer binding, since the
   refusal leaves the module source-only.
3. Add a regression test beside `test_regress_codegen_generator_frame.py` that
   asserts no `for (auto <a>, <b>` text and that the program's output matches
   CPython.

Related but distinct: `CODEGEN_generator_param_loop_target_kinds_still_unresolved.md`
covers the tuple target on the plain-GIMPLE `_static_env` path, not this C++ emitter.
