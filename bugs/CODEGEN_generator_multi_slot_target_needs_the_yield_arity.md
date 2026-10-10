# CODEGEN: a multi-slot `for` target over a generator whose yield arity was never recorded emits invalid C

**Area:** CODEGEN (`mojo/backend_gimple/emit_loops.py`,
`_gen_for_generator_iter`). Found 2026-10-04 while fixing the generator-side
half of the loop-target problem, which is
`bugs/CODEGEN_loop_target_rebind_outside_the_zip_enumerate_families.md`'s
sibling and was found in `Tools/c-analyzer/c_parser/preprocessor/__init__.py`.

## What I ran

```python
def g():
    yield 1

def main():
    for a, b in g():      # two slots, generator yields ONE value
        print(a, b)
main()
```

    CPython   TypeError: cannot unpack non-iterable int object
    compiled  gcc -fgimple: error: expected ')' before ',' token

The same program with a TUPLE-yielding generator (`yield 1, 2`) now compiles
and prints `1 2` — that half was the same defect and is fixed (the per-slot
names come from `_emit_generator_tuple_unpack`, so declaring the raw target
string as well was never anything but invalid C). What is left is the case
where the generator's yield arity is UNKNOWN, so `tuple_slot_ctypes` is None and
the multi-slot target falls through to the single-name declare with the target
string `(a, b)` intact.

## Mechanism

```python
is_tuple_target = (gimple_ctypes.for_target_is_tuple(var)
                   and tuple_slot_ctypes is not None)
if is_tuple_target:
    var_names = gen._split_top_level_comma(var[1:-1])
else:
    var_names = None
    _one = _single_loop_target_name(var)      # None for a MULTI-slot target
    if _one is not None:
        var = _one
    gen._declare_var(var, vct)                 # var is still '(a, b)'
```

`_single_loop_target_name` returns None here by design — a two-slot target over
a one-value generator is not a spelling, it is a real mismatch — and the code
then declares `(a, b)` as a variable name, which is not C.

## Why it is left as it is

The comment above this branch used to call it "a pre-existing, unrelated
mismatch this fix doesn't attempt to handle", and that is still the right
answer: there are two possible sources and nothing here can tell them apart.

* The generator yields a TUPLE and `_generator_tuple_yield_slot_ctypes` failed
  to record it (a registration gap), in which case the right answer is the
  per-slot unpack with the types the generator actually has.
* The generator yields one value and the source unpacks it, which CPython
  accepts only when the value is iterable — an iterator protocol this scalar
  model does not have.

Emitting either is a guess, and both guesses are wrong for the other case.
Rolling back to the generic path is not an option either: `_gen_for_iter`'s
unsupported-iterable fallback is `mojo_unsupported_iter`, a ZERO-ITERATION
stub, so trading a compile error for it would turn a loud failure into a silent
wrong program.

## Exact next step

Make the two cases distinguishable, in this order:

1. `_generator_tuple_yield_slot_ctypes` should record the arity for EVERY
   compiled generator whose yields are tuple literals, so `tuple_slot_ctypes` is
   None only for a generator that genuinely yields one value per resume. That
   single change moves this case into the fixed branch for the common shape.
2. Then refuse what is left, by name: a multi-slot target over a
   one-value-per-resume generator is a real shape the model cannot answer, and
   `gen_module`'s per-function eligibility pre-check (the same one the cpp
   generator path uses for `_UnsupportedGeneratorShape`) is where a refusal
   belongs, because it can name the construct instead of leaving gcc to name a
   `(`. The rollback trap above is why it must be a REFUSAL at eligibility time
   and not a fallback after emission.

## Coverage

`test_gimple_generator_runner.py`'s new `gen_one_slot_tuple_target_binds_one_
name` and `gen_one_slot_tuple_target_comprehension` pin the half that is fixed.
The case here needs a case that ASSERTS THE REFUSAL once step 2 exists —
`test_generator_c_compiles` is the right shape for it, since a refusal has to
be visible as something other than a gcc error about a line of generated C.