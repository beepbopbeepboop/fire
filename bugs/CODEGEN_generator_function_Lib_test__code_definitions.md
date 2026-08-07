# CODEGEN_generator_function: Lib/test/_code_definitions.py

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) with a more specific reason than the 2026-07-30 note.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py
[gimple_codegen] async generator 'asyncgen_spam' not eligible for C++ coroutine path, falling back to honest refusal: asyncgen_spam: *args/**kwargs parameters not supported for compiled async generators
Error building: cannot compile module: function(s) asyncgen_spam (async generator function(s), ...) — falling back to interpreting this module from source instead
```

**Root cause:**
```python
async def asyncgen_spam(*args):
    for arg in args:
        yield arg
```
`asyncgen_spam` is an ASYNC generator (`async def` + `yield`) whose only
parameter is `*args`. The async-generator codegen step
(`_gen_cpp_async_generator_unit`) explicitly refuses `*args`/`**kwargs`
parameters outright (same deliberate scope boundary already documented
for plain generators and plain async functions in
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md` — that doc's
title says "struct-typed" but the underlying mechanism/scope-limit family
is the same: `_gen_cpp_generator_unit`/`_gen_cpp_async_unit`/
`_gen_cpp_async_generator_unit` all independently refuse any parameter
shape outside a fixed scalar/container allow-list, and `*args`/`**kwargs`
are refused unconditionally regardless of what's actually inside them).
As with the other member of this family, refusing a module-level
generator escalates to a fatal whole-module `RuntimeError`.

Not folded into the existing hard-bug doc's title/scope in this pass
(that doc is scoped to the struct-typed-parameter case specifically) —
flagged here as a confirmed second trigger of the same underlying
"coroutine codegen's parameter-shape allow-list is narrower than the
scalar/container types themselves" family; worth either broadening that
hard-bug doc's scope or spinning off a sibling doc
(`CODEGEN_generator_varargs_param_refused.md`) if a third instance
turns up.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py
