# CODEGEN: a generator's yield slot takes the FIRST kind a rebound name had, and a mixed-kind lambda yield falls back to a wrong-value path

**State: PARTIAL (2026-10-29). No silent wrong value remains for either shape:
both now REFUSE at compile time, in both backends. Compiled output that
matches CPython is still missing, and needs the feature described under
"Remaining" below.**

## Status

- **Shape 1 (rebound local), landed.** `mojo/middle/coro.py`'s `_static_env`
  records EVERY kind a name is bound to. Two kinds that share a slot layout
  (`bool` and `int`) widen to `'i'`, as the mixed bool/int decision already
  does. Any other disagreement is a `('conflict', kinds)` marker, and a yield
  of that name is refused by `_generator_value_kind`. Before this, a dropped
  name read as a None hole, and a lone hole is int64_t: `2` / `0`, silently.
- **Shape 2 (mixed-kind lambda), landed as a refusal.** The cpp fallback
  types a lambda call as `std::function<int64_t()>`, so a float or bool result
  reached its yield as int64_t. `coro.cpp_value_slot_refusal` runs in
  `cpp_async._gen_cpp_generator_unit` and refuses any yield whose kind is `d`
  (needs `double`) or `b` (needs `_Bool`) that the cpp typer put in a
  different slot, and any yield of a conflicting name.
- **Tests:** `test_gimple_generator_runner.py`'s `generator_rebound_local_
  yield_kind_shape1_refused` and `generator_mixed_lambda_yield_shape2_refused`
  pin the refusals. Their old pins (`2\n0\n`, `1\n1\n`) were wrong against
  CPython and are gone.

## Remaining

1. **Compiled output that matches CPython for these programs.** Shape 1 needs
   a value slot that holds BOTH a bool and a float (a tagged or boxed slot).
   The stack-switch slot is one scalar, so this is a feature, not a fix to
   `_static_env`. Shape 2 needs a lambda callable whose return kind is not
   always int64 in the cpp path (`_CPP_CALLABLE_CTYPE` is int64-only).
2. **Methods in the cpp check.** `cpp_value_slot_refusal` calls
   `_static_env(fn, None)`, so a generator METHOD's `self.<field>` yields
   are not typed there. Those yields are not refused by the cpp check even
   when a field is float. Fix: thread the enclosing `StructDef` into the cpp
   unit (it has only the struct NAME today).
3. **Stdlib gate impact, for the integrator.** A generator that yields a
   rebound name, or a float/bool lambda result on the cpp path, is now a
   refusal. Check `compile_stdlib.py`'s `U` count and `stdlib-dylib`'s
   `skip` count against the pre-change run. A new refusal there is the
   correct answer, but it must be seen.

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

Remaining item 1 above is the feature (a slot that holds bool and float, and a
lambda callable with a non-int return in the cpp path). Item 2 is the one
small, self-contained follow-up: thread the enclosing `StructDef` into
`_gen_cpp_generator_unit` and pass it to `cpp_value_slot_refusal`.
