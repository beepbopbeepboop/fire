# CODEGEN: `print` of a CAPTURING closure value prints its address decimal, where a plain `def` prints `<function name at 0x...>`

Found 2026-10-04 on `work/bugs7-1` while landing the fix for the compiled path
taking a comprehension's `for` target as a plain local of the enclosing
function, shadowing the module global (whose own deletion needed a pinning test,
and whose subject turned out to include a `print` of a module-scope closure
value). The doc for that bug went with its fix, so this one names the symptom
rather than citing a path that is gone.

## What I ran

```console
$ cat .tmp/w/repr.mojo
def outer(a):
    def inner(x):
        return x + a
    return inner

f = outer(3)
print(f)

def named(x):
    return x + 1
print(named)

g = (lambda y: y * 2)
print(g)

$ python3 .tmp/w/g.py .tmp/w/repr.mojo     # compile_to_gimple + gcc -fgimple + run
81647536
<function named at 0x104839280>
4370699400

$ python3 .tmp/w/repr.py                   # the same text on CPython 3.14.7
<function outer.<locals>.inner at 0x1004c3320>
<function named at 0x105569a770>
<function <lambda> at 0x10556a770>
```

**The middle line is the control and it is CORRECT.** A bare `def` printed as a
name and an address. The first and third — a nested `def` returned as a value,
and a capturing lambda — printed a bare decimal.

## Why the two halves differ, and it is not a formatting decision

`test_gimple.py`'s `print_of_a_function_value_is_not_a_decimal_address` fixed
exactly this symptom for a bare function VALUE, and its own docstring names the
mechanism: a function value is materialised as the pre-declared
`void *` static `_funcptr_<csym>` (GIMPLE forbids `&func_name` as an rvalue),
and the fix was to record `gen._func_value_names[t] = name` at the point the
value is minted, so `print`/`repr` can render the SPELLING instead of falling
into `TypeLattice.printf_fmt`'s `%d` default for a pointer.

So there are two separate things and only the first is done:

1. **the `%d`-on-a-pointer bug** — fixed, for the bare-`def` spelling, by
   `_func_value_names` (`emit_exprs._lower_IdentExpr`'s "bare function name
   used as a value" branch).
2. **a capturing closure is not a `void *` at all.** It is a heap
   `MojoBoundMethod *` (a `malloc` + `_reg_bound_method`, see
   `test_gimple_runner.py`'s
   `gimple_capturing_lambda_in_nested_def_env` and the comment at
   `_gen_lifted_closure`), and NOTHING records the name it should print under.
   `_func_value_names` is keyed by the temp a `void *` was minted into; the
   bound-method path mints a different kind of temp through a different
   lowering (`emit_methods.py`'s `_lower_bound_method_value`), so the table
   never sees it.

Which is why the third line is `4370699400` and not a truncated pointer: the
`char *` arm got the pointer bits and formatted them. There is a
`print(f)`-shaped test for the closure case nowhere in `test_gimple_runner.py`
or `test_gimple.py` — `gimple_capturing_lambda_nested_def_ptr_kinds_build`
pins BUILDABILITY of the two capture kinds (`char *` and `MojoList *`) and says
in its own comment that the printed values "are a SEPARATE gap"; that is this
gap.

## What is NOT the cause, so nobody re-derives it

* **Not the closure's environment or the boxed local.** The env is allocated and
  filled correctly; `f(10)` answers 13 on both engines, so the value is a
  working callable, not a broken one. This is purely the `str()` spelling.
* **Not `mojo_bound_method_call_*`.** Those emit and run.
* **Not the module scope.** The same closure printed through a LOCAL
  (`f = outer(3)` inside a function) has the same decimal, so it is the
  closure-value lowering, not the globals-struct field.
* **Not `printf_fmt`.** Given a `char *` it would produce the right shape;
  nobody is offering it one.

## Exact next step

1. Find where a capturing closure's value is minted and what it is called.
   `emit_methods.py`'s `_lower_bound_method_value` (reached from
   `_gen_lifted_closure`) is where the `MojoBoundMethod *` temp is created; the
   question is what *name* is available there. For the
   `outer(3)`-returns-`inner` spelling the natural answer is what CPython
   prints, `outer.<locals>.inner`, which means the lift must carry the
   enclosing `def`'s name and a "was it nested" bit — check whether
   `_bound_method_ret_types` (the sibling table, recorded at the same site for
   the return-type hop) already has a per-value record with anything usable,
   because if it does this is one more column rather than a new mechanism.
2. Record it in the SAME table `print` already consults
   (`_func_value_names`), or in a sibling the `print`/`repr` arm reads for a
   `MojoBoundMethod *`. Do not add a third spelling of the repr: the point of
   (1)'s fix is that there is one table and one rendering.
3. `test_gimple.py`'s `print_of_a_function_value_is_not_a_decimal_address`
   asserts by SHAPE (a regex), because the address differs per build. Use the
   same shape assertion here — plus the `<lambda>` spelling for line 3, whose
   name is `_func_value_names`-style bookkeeping rather than a source name.
4. `test_gimple_runner.py::test_gimple_matches_cpython` cannot be the test:
   CPython's `0x...` is not this compiler's `0x...`. That is the whole reason
   the existing test lives in `test_gimple.py` and asserts a regex.

Cheapest verification once fixed: the three-line program above, `compile_to_gimple`
+ `gcc -fgimple` + run, compared against `test_gimple.py`'s existing
`print_of_a_function_value_is_not_a_decimal_address` harness.