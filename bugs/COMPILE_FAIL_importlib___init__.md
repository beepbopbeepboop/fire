# COMPILE_FAIL: Lib/importlib/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py`

## Status (RESOLVED, re-verified 2026-08-07)

**Builds successfully now** (`python3 mojo.py build .../importlib/
__init__.py` exits 0, 0 `error:` lines). The dynamic-attribute hard bug
this doc was blocked on
(`bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md`, task #136)
had its Steps 1-4 implemented and verified earlier the same day (real
per-object dynamic-attribute storage) — this file's `module.__spec__`
read/write on a generically-typed `reload()` parameter now resolves
through that machinery. Not independently re-diagnosed beyond
confirming the build now succeeds; see that hard-bug doc for the actual
fix.

## Status (updated 2026-08-06, historical — now resolved, see above)

Root-caused; not fixed — instance of the tracked dynamic-attribute hard
bug (bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md, task
#136). Not attempted independently here.

```
error: request for member '__spec__' in something not a structure or union
```
at (`reload()`):
```python
def reload(module):
    try:
        name = module.__spec__.name
    except AttributeError:
        ...
    ...
    spec = module.__spec__ = _bootstrap._find_spec(name, pkgpath, target)
```

## Root cause

`module` is `reload()`'s parameter — genuinely "any module object" at
the Python level (`types.ModuleType`, or any object with module-like
attributes), which this compiler can't resolve to a known struct layout.
`.__spec__` is read AND written (`module.__spec__ = ...`) on this
generically-typed parameter — the same class of gap as the hard bug's
own `cls.__slot_names__`/`self.__hardroot` examples (an opaque,
unresolvable object needing real attribute get/set), just triggered by
a bare, unannotated function parameter this time rather than a `cls`/
`self` receiver.

Added as a confirmed real-world instance in
bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md. Not
independently fixable without that hard bug's planned generic
dynamic-attribute-storage runtime work — no further action here.
