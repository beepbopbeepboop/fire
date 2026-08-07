# CODEGEN_generator_function: Lib/test/libregrtest/save_env.py

## Status (updated 2026-08-06)

**STILL FAILING**, but the specific error has changed since 2026-07-30
(that `'begin' was not declared` shape — dyld.py's bullet-3 iteration
gap — no longer reproduces for this file). Current failure is a real
SYNTAX error in the generated `.cpp` itself (not just an unresolved
name):

```
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:327:16: error: expected ')' before ',' token
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:339:4: error: 'name' undeclared (first use in this function); did you mean 'rename'?
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:339:15: error: 'restore' undeclared (first use in this function)
```

**Root cause (traced to source, new gap — narrow, single instance,
not yet a hard-bug doc):**
```python
def resource_info(self):
    for name in self.resources:
        method_suffix = name.replace('.', '_')
        get_name = 'get_' + method_suffix
        restore_name = 'restore_' + method_suffix
        yield name, getattr(self, get_name), getattr(self, restore_name)   # line 326
```
`yield name, getattr(self, get_name), getattr(self, restore_name)` — a
3-element tuple yield where two of the three elements are `getattr(self,
<dynamic-name-string>)` calls (each resolving to a BOUND METHOD at
runtime). The emitted C++ for this specific tuple-yield shape has a real
syntax error (`error: expected ')' before ',' token` — not a name-
resolution problem, an actually malformed expression/statement), which
then cascades: `__enter__`'s `for name, get, restore in
self.resource_info():` (line 339) unpacking the (never-compiled)
generator's output reports `name`/`restore` as undeclared, since the
tuple-yield's own emission never got far enough to declare them.

Not folded into a hard-bug doc (single instance so far in this cluster
— the closest prior finding, dyld.py's bullet-1 "untyped params default
wrong", is a different mechanism: this is about a MULTI-ELEMENT TUPLE
yield containing `getattr(...)` call results specifically, producing
outright malformed C++ syntax rather than a type mismatch). Flagged for
whoever next hits a tuple-yield containing `getattr()`/similarly dynamic
sub-expressions to confirm and fold into a dedicated hard-bug doc.

Not fixed here — inside the coroutine `.cpp` tuple-yield emission path,
warranting its own dedicated verification pass per this task's
guidance.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py
