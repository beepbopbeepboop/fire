# CODEGEN: a generator's yield slot takes the FIRST kind a rebound name had, and a mixed-kind lambda yield falls back to a wrong-value path

**State: OPEN, reproduced 2026-10-29 against CPython. Found while fixing
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`'s yield residue
(`coro._static_env` now types a lambda-bound local's return kind). Not fixed.**

Two shapes, one family: the value slot of a generator is decided from a
single kind, and the kind is read off the first binding of a name (or off a
partial answer) when the name is really bound to values of different kinds.

## Shape 1 — a rebound local keeps its FIRST kind (literals, no lambdas)

```python
def gen(n):
    r = False
    if n > 0:
        r = 2.5
    yield r

def main():
    for v in gen(1):
        print(v)
    for v in gen(0):
        print(v)
main()
```

CPython: `2.5` then `False`. Compiled: `True` then `False` (exit 0).

Mechanism: `mojo/middle/coro.py`'s `_static_env` records a local's kind with
`env.setdefault(tgt, k)`, so the first assignment (`r = False`, `'b'`) wins
and the later `r = 2.5` (`'d'`) is never seen. `_generator_value_kind` then
sees one `'b'` yield and emits a `_Bool` slot. The rebind is a second,
conflicting kind in the same function, which the mixed-kind rule in
`_generator_value_kind` would refuse if it were recorded.

Pre-existing: reproduced with the 2026-10-29 fix to `_callee_return_kind`
reverted (same output).

## Shape 2 — mixed-kind lambda yields: A3 refuses, the fallback prints the wrong value

```python
def gen(n):
    f = lambda: n > 2
    yield f()
    g = lambda: 1.5
    r = g()
    yield r

def main():
    for v in gen(5):
        print(v)
main()
```

CPython: `True` then `1.5`. Compiled: `1` then `1` (exit 0).

Mechanism: the A3 path correctly refuses this with
`_generator_value_kind(gen) = (None, 'mixed float / non-float yields (v0)')`
(bool `'b'` and float `'d'`). The refusal hands the generator to the legacy
C++ coroutine fallback (`mojo/backend_gimple/cpp_async.py`), whose yield typing
(`gimple_exprtypes._generator_yield_ctype` with `declared`) does not know a
lambda-bound callee's return kind and types both yields `int64_t`. So the
fallback prints both as ints. Before the 2026-10-29 change the A3 path
accepted the same program as `int64_t` and printed the same `1`/`1`, so the
wrong answer predates it; the change only moved it onto the fallback.

## Why these are one doc

Both come from a generator's single value slot being decided from one
partial view of the values it yields. Shape 1 is the first-binding rule in
`_static_env`; shape 2 is a refusal that is not carried through to the
fallback. Fixing shape 1 by recording every binding and refusing on a
disagreement would also refuse shape 2 on the A3 path, but the fallback would
still compile it, so shape 2 needs the fallback to refuse too (or to type the
lambda-bound callee the way `_static_env` now does).

## Next step

1. In `_static_env` (`mojo/middle/coro.py`), replace `env.setdefault(tgt, k)`
   with a per-name set of every kind bound to the name. If the set has more
   than one scalar kind, record the name as conflicting (no entry), so
   `_generator_value_kind` sees a `None` hole and refuses beside a non-int
   kind, or types it `int64_t` beside an int. Check the `None`-hole rule
   against `test_gimple_generator_runner.py`'s existing shapes before landing.
2. For shape 2, make the cpp fallback's `_generator_yield_ctype` call receive
   the lambda-call return table (the same `known`-map gap the bug's
   parent doc describes), or refuse a mixed-kind yield set there the way the
   A3 path does.
3. Tests: both programs above, CPython-compared, in
   `test_gimple_generator_runner.py` next to the lambda-yield tests
   (`generator_lambda_*`).
