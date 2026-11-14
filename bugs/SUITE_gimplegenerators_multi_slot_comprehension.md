# SUITE: `gimplegenerators` has 1 failing case — `gen_multi_slot_comprehension_target_over_one_value_generator_refused` refuses with the wrong reason

## Status 2026-11-14 — fixed at the root cause on work/bug-suite-gimplegenerators-multi-slot-co

Root cause: `unknown_decl_check.check_module` runs at `_run_pipeline` step 3,
before ANY codegen, so for a comprehension whose element reads an undeclared
name (`print([x for a, b in g()])`) that pass answered its own, less specific
question first and the arity refusal in `_compr_generator_loop` (commit
48623688f) was never reached. Fix: a new pipeline pre-pass
(`mojo/middle/coro.py::refuse_multi_slot_comprehension_over_nontuple_generator`)
runs beside `_check_ownership`, BEFORE the unknown-declaration pass, and raises
the same refusal through the same message builder
(`multi_slot_comprehension_refusal`) that `_compr_generator_loop` now uses. The
pre-pass only fires on shapes it can prove (multi-slot tuple target; iterable is
a bare-name call of a module-level generator of the same module whose every
yield is provably non-tuple — no tuple literal, no `yield from`); everything
ambiguous defers to codegen's own refusal, so it cannot refuse anything codegen
would have accepted.

Verified (each wrapped in `python3 tools/memslot.py --gb 8 --label x --`):
`test_gimple_generator_runner.py` 510 passed, 0 failed, including the named
case below and the new set-comprehension spelling; `test_unknown_decl_check.py`
ok; tuple-yield / 1-tuple-target / multi-slot-over-list shapes unchanged.

The `for`-statement sibling of the same ordering collision is filed, not fixed:
`bugs/SUITE_gimplegenerators_multi_slot_for_unknown_body.md`.

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

## Done when

`test_gimple_generator_runner.py` is green with BOTH of these refused with
`multi-slot comprehension target over a generator whose yield arity is not a
tuple` (never `use of unknown declaration 'x'`):

- `gen_multi_slot_comprehension_target_over_one_value_generator_refused`
  (the doc's own case), and
- `gen_multi_slot_set_comprehension_target_over_one_value_generator_refused`
  (the set spelling, added with the fix).

Both pass as of bef7368fd; the file reports `510 passed, 0 failed`.

## Exact next step

(Superseded by the fix Status above: the arm was never reached because
`unknown_decl_check.check_module` killed the compile first; the pre-pass added
in bef7368fd makes the refusal happen before the body is compiled, as asked.)

Run the single snippet with `MOJO_DEBUG=1` and see whether
`_compr_generator_loop`'s new multi-slot arm is reached at all: the expected
raise is gated on `_one is None and for_target_is_tuple(_target_str)`, so
either the comprehension takes a different branch before it (the
comprehension's own target handling, `_compr_bind_target`) or `g()` is an A3
generator whose consumer lowerings never reach that function. Then make the
refusal happen before the target's body is compiled, as the test requires.
