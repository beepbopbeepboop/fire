# CODEGEN_arithmetic_on_a_received_none_gives_one: `x + 1` on a None received by `x = yield` prints 1

## Status (2026-11-01, carried forward from e0ad5183f's commit message; not fixed)

`x = yield` now binds the None box on the default path (e0ad5183f), so
`print(x)` prints `None`. Arithmetic on that name still unwraps the box to its
bits (0), so `x + 1` prints `1`. CPython raises `TypeError`. This is a silent
wrong value on a valid program, and it is the remaining symptom of the
None-received family whose print case is fixed.

### Repro (measured 2026-11-01)

```python
def g():
    x = yield
    try:
        print(x + 1)
    except TypeError:
        print("TypeError")
    yield 1

def main():
    it = g()
    next(it)
    next(it)
main()
```

- CPython: `TypeError`
- compiled path (`test_generator_matches_cpython` helper): `1`
  (`CPython 'TypeError\n', compiled '1\n'`)

The interpreter (`fire.py run`) raises the TypeError correctly; only the
compiled path is wrong.

### Cause

`tagged_recv_name` (emit_infra.py) keeps the box at the bind, so `print(x)` and
`x == None` see None. Arithmetic on a tagged name goes through
`_tagged_arith_select` (emit_infra / emit_exprs), which picks the operand's
int64 payload and never raises for a None box. The None box has no numeric
kind, so the arithmetic lowering needs a None check that raises the TypeError
(or a None-aware refusal) rather than unwrapping.

### Next step

1. In `_tagged_arith_select` (`mojo/backend_gimple/emit_infra.py`), when an
   operand is a tagged name whose box kind may be None, emit a runtime check on
   the box kind and raise TypeError on None, instead of unwrapping to 0. Or, if a
   runtime raise is not expressible there, refuse the program at compile time
   with an explicit error, never a value.
2. Pin with a case in `run_none_yield_tests` (`test_gimple_generator_runner.py`)
   using the repro above (the `try`/`except` form, so the CPython reference runs
   to completion); it must PASS on both default and cpp paths.
