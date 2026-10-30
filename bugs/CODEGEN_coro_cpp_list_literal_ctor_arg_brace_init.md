# CODEGEN: a list literal passed to a constructor from a compiled generator emits brace-init into a `MojoList *`

**State: OPEN. Found 2026-10-29 while working on
`COMPILE_FAIL_Tools_scripts_summarize_stats`. Not fixed.**

## Repro

```python
class Table:
    def __init__(self, title: str, mode: int):
        self.title = title; self.mode = mode

class Section:
    def __init__(self, name: str, tables: list):
        self.name = name; self.tables = tables

def outer():
    def iter_tables(base: int):
        for i in range(2):
            yield Section("sec", [Table("t", i)])

    for s in iter_tables(5):
        print(s.name)

outer()
```

## Observed

The generator's C++ body passes a brace-init list where the extern signature
wants a container:

```
error: cannot convert '<brace-enclosed initializer list>' to 'MojoList*'
note: initializing argument 3 of 'void Section___init__(Section*, char*, MojoList*)'
```

So the module hard-fails at the C++ stage instead of refusing honestly.

## Expected

Either the list literal lowers to a real `MojoList *` (`mojo_list_new` plus
`mojo_list_append` of each element, the same way other list literals in this
emitter are built), or the generator refuses with an unsupported-shape message
so the module falls back to source.

## Where

The C++ coroutine CallExpr lowering for a struct constructor's arguments in
`mojo/backend_gimple/cpp_core.py`. The ctor call site emits an initializer list
(`{...}`) for a `ListExpr` argument. The tuple-element typing this needs lives
in the same family as `CODEGEN_nested_container_as_dict_key_or_tuple_slot.md`.

## Next step

1. Reproduce with the snippet above through
   `gimple_codegen.compile_to_gimple_with_cpp(src, do_imports=False)`, and confirm
   the `{[&]() -> Table * ...}` brace-init text for the argument.
2. Lower a `ListExpr` ctor argument to a `MojoList *` built by the existing list
   helpers, or raise `_UnsupportedGeneratorShape`. Prefer the lowering.
3. Add a regression test beside `test_regress_codegen_generator_frame.py` that
   checks the emitted text and that the program output matches CPython.
