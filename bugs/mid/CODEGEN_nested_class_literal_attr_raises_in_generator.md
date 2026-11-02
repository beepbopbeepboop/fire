# CODEGEN: a literal class attribute on a class nested in a generator raises AttributeError at run time

Found 2026-10-29 while running `test_gimple_generator_runner.py` for the
enumerate loop-target fix. Pre-existing on master (reproduced with that fix
reverted, `coro.py` at HEAD).

## Repro

```mojo
def g():
    class Tag():
        __version__ = 7
    t = Tag()
    yield t.__version__

def main():
    for v in g():
        print(v)
main()
```

    expected (CPython / the test's oracle):  7
    compiled:  exit 1, stdout empty
               stderr: Unhandled exception: AttributeError: __version__

## Failing tests (test_gimple_generator_runner.py, all red on HEAD)

- `nested_class_literal_attr_compiles`
- `nested_class_noinit_ctor_in_generator_compiles`
- `nested_class_literal_attr_contextmanager_compiles`

The third and second were not separately root-caused; they share the
nested-class-in-generator shape and may or may not share the cause.

## Next step

Find where a class defined inside a generator body gets its layout
(`module_gen._gmi_hoist_nested_structs`, per the 2026-07 hoist commits) and
check whether a class-level literal assignment (`__version__ = 7`) is carried
into that layout as a readable attribute. The read `t.__version__` must lower
to the constant; today it reaches the attribute-miss path at run time instead.
