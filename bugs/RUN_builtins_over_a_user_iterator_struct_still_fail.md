# Python builtins that iterate a user-defined iterator struct still fail in the interpreter

## Status

OPEN. Found 2026-10-30 while fixing `CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered`.

Landed alongside that doc's interpreter half (`_mojo_iter` / `_mojo_next` in
`myinterpreter.py`): `next(c)`, `iter(c)`, `for x in c` and list comprehensions
over a struct with `__iter__`/`__next__` now drive the Mojo protocol.

Still failing, measured with `python3 fire.py run`:

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
