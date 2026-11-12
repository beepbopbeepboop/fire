# INTERP_python_str_dunder_ignored

## Summary

`fire.py run` (the interpreter) ignores a Python-source class's own `__str__`
and `__repr__` methods. `str(obj)` and `print(obj)` return
`<Item instance>` where CPython and the compiled path both call the user
method and return its text.

## Evidence

Run on 2026-11-11 at HEAD `d210765a2`.

```python
class Item:
    def __init__(self, n: int):
        self.n = n
    def __str__(self) -> str:
        return "I" + str(self.n)

print(str(Item(1)))
print(Item(1))
```

* `python3` (CPython 3.15): `I1` / `I1`.
* `python3 fire.py run`: `<Item instance>` / `<Item instance>`.
* `python3 fire.py build` + run the binary: `I1` / `I1` — the compiled path is
  right (its `_stringify_value` looks up `__str__`/`__repr__`).

Found while replanning `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md`:
the analyzer's `dump` methods print `str(c)` on `CacheEntry`/`StackItem`
objects, so an interpreter run of `analyzer.py` cannot be used as the oracle
for the compiled binary's output.

## Root cause

`myinterpreter.py` binds the builtin `str` straight to Python's `str`
(`self.scope.define('str', str)` at line 4812), and a user class instance is a
`MojoInstance` (`myinterpreter.py:2253`). `MojoInstance.__str__`
(line 2292) and `__repr__` (line 2298) only consult Mojo's
`write_to`/`write_repr_to` methods; neither looks in
`self._mojo_class.methods` for the Python dunder `__str__`/`__repr__`. The
compiled path's shared `user_dunder_repr_call`
(`mojo/middle/calls_shared.py::user_dunder_repr_call`) does look them up —
that is the two-front-end divergence.

## Next step

In `myinterpreter.py`:

1. `MojoInstance.__str__`: if `'__str__'` is in `self._mojo_class.methods`,
   call it as `method(interp, self)` and return its result; otherwise fall
   through to the existing `write_to` / `repr(self)` path (CPython's `str`
   prefers `__str__`, then `__repr__`).
2. `MojoInstance.__repr__`: if `'__repr__'` is in `methods`, call it; otherwise
   keep the existing `write_repr_to` / `write_to` / `<Cls instance>` fallback.
3. Add a regression test next to `test_runtime_diff.py` or
   `test_interp_oracle.py` (`test_interp_oracle.py` is the front-end oracle for
   exactly this class of bug) that runs the two-line repro through
   `python3 fire.py run` and CPython and requires identical stdout.

`Done when`: `python3 test_interp_oracle.py` (or the added case's own quick
command) passes with the fixture above and the compiled/interpreter outputs
agree.
