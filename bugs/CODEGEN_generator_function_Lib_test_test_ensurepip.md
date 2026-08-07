# CODEGEN_generator_function: Lib/test/test_ensurepip.py

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) with a precisely identified, new gap.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/test/test_ensurepip.py
[gimple_codegen] generator 'fake_pip' not eligible for C++ coroutine path, falling back to honest refusal: unsupported statement in generator body: StructDef
Error building: cannot compile module: function(s) fake_pip (generator function(s), ...) — falling back to interpreting this module from source instead
```

**Root cause (new gap — narrow, single instance, not yet a hard-bug
doc):**
```python
def fake_pip(version=ensurepip.version()):
    if version is None:
        pip = None
    else:
        class FakePip():          # <-- nested class def inside a generator body
            __version__ = version
        pip = FakePip()
    ...
    yield pip
```
`fake_pip` defines a NESTED CLASS (`class FakePip(): ...`) inside its
own generator body. The coroutine codegen's statement lowering
(`_cpp_stmt`) has no case for a `StructDef` node at all — nested class
definitions inside a generator are refused wholesale, distinct from
every other gap found in this cluster's pass (those are all about
parameter types, assignment targets, `raise` targets, or expression
shapes — this is about a whole nested TYPE DEFINITION).

Single instance so far in this cluster; not folded into a hard-bug doc.
If confirmed recurring elsewhere, write
`bugs/hard/CODEGEN_generator_nested_class_def_unsupported.md`.

Not fixed here — a nested class inside a generator is a genuinely
unusual shape and support would need real design work (where does the
class's own methods/layout get compiled relative to the enclosing
coroutine's translation unit?), well beyond a narrow fix.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_ensurepip.py
