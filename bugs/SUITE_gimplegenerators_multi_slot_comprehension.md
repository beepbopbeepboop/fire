# SUITE: `gimplegenerators` has 1 failing case — `gen_multi_slot_comprehension_target_over_one_value_generator_refused` refuses with the wrong reason

## Status 2026-11-14 — measured on master, not caused by the branch that filed this

### What was run

```sh
python3 tools/memslot.py --gb 8 --label x-genrunner -- \
  python3 test_gimple_generator_runner.py
```

### What was seen

```
FAIL  gen_multi_slot_comprehension_target_over_one_value_generator_refused:
      refused with the wrong reason: <source>:5:12: error: use of unknown
      declaration 'x'
500 passed, 1 failed
```

The case (`test_gimple_generator_runner.py` ~line 9621) compiles

```python
def g():
    yield 1

def main():
    print([x for a, b in g()])
main()
```

and expects the refusal message
`multi-slot comprehension target over a generator whose yield arity is not a
tuple`, added by commit `48623688f` in `emit_infra._compr_generator_loop`. It
gets a downstream C-compile error instead: the comprehension's bind of `x`
never happens, so the generated body reads an undeclared `x`.

Verified independent of this branch: the same snippet returns the same error
with the branch's code changes reverse-applied
(`git apply -R` of the code hunks, then compile the snippet directly).

### What was expected

`500 passed, 0 failed` (or the named refusal, per the test's own contract).
`tools/suite.py`'s `gimplegenerators` registration carries no `expect=`, so
this is an undeclared red on master, not a known failure.

### Exact next step

Run the single snippet with `MOJO_DEBUG=1` and see whether
`_compr_generator_loop`'s new multi-slot arm is reached at all: the expected
raise is gated on `_one is None and for_target_is_tuple(_target_str)`, so
either the comprehension takes a different branch before it (the
comprehension's own target handling, `_compr_bind_target`) or `g()` is an A3
generator whose consumer lowerings never reach that function. Then make the
refusal happen before the target's body is compiled, as the test requires.
