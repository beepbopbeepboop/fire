# Python builtins that iterate a user-defined iterator struct still fail in the interpreter

## Status

PARTIAL. Found 2026-10-30 while fixing `CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered`.

Landed 2026-10-30 (option 2 below, through one choke point): `list`, `tuple`,
`set`, `frozenset`, `sum`, `sorted`, `enumerate`, `any`, `all`, `zip`, and
`min`/`max` with one argument now accept a Mojo struct with `__iter__`. The
hook is `_mojo_builtin_args`, called from `invoke` — the one call path shared
by `eval_CallExpr` and `map[func]`. The builtin objects are not wrapped, so
`isinstance(x, list)` is unchanged. Regression:
`test_interp_oracle.py::user_iterator_struct_next_and_for` (fails on the
unfixed tree with `KeyError: 0`, passes now). Verified: `python3
test_interp_oracle.py` → 24 passed, 0 failed.

Still failing, measured with `python3 fire.py run` on 2026-10-30:

```python
    print(list(map(lambda x: x * 10, Counter(1, 4))))   # KeyError: 0
    print(list(filter(lambda x: x > 1, Counter(1, 4)))) # KeyError: 0
    print(list(reversed(Counter(1, 4))))                # KeyError: 0
```

`map`/`filter` take the iterable as their SECOND argument and the first
positional is the callable, so the first-argument rule in `_mojo_builtin_args`
does not reach it; `reversed` needs a sequence protocol, not `__iter__`, and
Python's `reversed()` would call `__reversed__`, so it is a separate decision.
`dict(c)` (pairs) was not measured. Remaining work: extend the table for
`map`/`filter` (iterable argument index 1) and decide `reversed` explicitly.

Still failing, the original report:

```python
class Counter:              # __init__/__iter__ (returns self)/__next__ as usual
    ...
def main():
    print(list(Counter(1, 4)))   # KeyError: 0   (CPython: [1, 2, 3])
main()
```

Any builtin that calls Python's own `iter()` internally hits the same wall:
`list(c)`, `sum(c)`, `zip(c, ...)`, `enumerate(c)`, `tuple(c)`, `sorted(c)`,
and so on. CPython looks `__iter__` up on the TYPE, and `MojoInstance` forwards
only attribute reads, so a builtin given a user iterator falls through to
`__getitem__` and dies with `KeyError: 0`.

## Next step

Option 2 was taken (2026-10-30) for the builtins listed in Status. What remains
is `map`/`filter`/`reversed`/`dict`, per Status. The original options follow.

Make the protocol visible to Python's own builtins, not one call site at a
time. Two options, pick one:

1. Give `MojoInstance` class-level `__iter__` and `__next__` that forward to
   `self._mojo_class.methods`, raising `TypeError("'X' object is not iterable")`
   / `TypeError("'X' object is not an iterator")` when the Mojo method is absent.
   Cost: `hasattr(value, '__iter__')` and `hasattr(value, '__next__')` become
   True for every `MojoInstance`. Affected sites to re-check first:
   `myinterpreter.py` ~4410 (`list(value)` on hasattr), ~4736/~4764 (the `for`
   guard, which `_mojo_iter` now sits behind), ~5223 (`hasattr(value, 'send')
   and hasattr(value, '__next__')`, the await-driveable check), and ~6138-6151
   (unpack). Each must keep its current message for a struct without the method.
2. Keep the class clean and route the builtins: wrap `list`, `tuple`, `sum`,
   `zip`, `enumerate`, `sorted`, `min`, `max`, `any`, `all` in `setup_builtins`
   the way `iter`/`next` are now wrapped. Smaller blast radius, more places to
   forget.

Either way, the regression belongs in `test_interp_oracle.py`
(`user_iterator_struct_next_and_for` is the case to extend), since the compiled
path is not the one that is wrong here.
