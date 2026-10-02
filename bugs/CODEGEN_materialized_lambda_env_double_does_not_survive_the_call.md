# A materialized lambda whose env carries a captured `double` returns a wrong value, with the store, the field and the read all agreeing in the C

**Found 2026-10-02 on `work/bugs4-3`** while working
`bugs/CODEGEN_lambda_call_boundary_loses_the_return_type.md`, whose `double`
rows turned out to be two different bugs. Measured on this tree and on
`HEAD` (`git archive HEAD` into a scratch copy), which agree on every value
below, so nothing here is a regression from that work.

## What I ran

`gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c`, against CPython on the same text.

```python
def m():
    q = 2.5
    fn = lambda: q + 1
    return fn()          # INLINED: never materialized

def n():
    q = 2.5
    fn = lambda: q + 1
    return fn           # MATERIALIZED: bound method + env struct

def k(p: float):
    fn = lambda: p * 2
    return fn()          # MATERIALIZED, capture is a PARAMETER

print(m())
print(n()())
print(k(2.5))
```

```
CPython  : 3.5 / 3.5 / 5.0
compiled : 3   / 1.0 / 2.0
```

`m()` is the INLINED path and its `3` for `3.5` is the sibling doc's bug. The
other two are this one: a materialized lambda, called through a value, whose
captured `double` arrives as something else.

## The generated C is right, which is the finding

For `n()`:

```c
typedef struct n_lambda_1_env {
  double q;
} n_lambda_1_env;
...
  _t4 = (double)q;
  _t2->q = _t4;                      /* the store: right */
  _t7 = mojo_bound_method_new (_t5, _t6);
  fn = (void *)_t7;
  _t11 = (int64_t)_t10;              /* n() returns the callable BOXED */
  return _t9;
}

double __GIMPLE n_lambda_1 (n_lambda_1_env * _env)
{
  _t1 = _env->q;                     /* the read: right */
  _t2 = (double)1;
  _t3 = _t1 + _t2;
  return _t3;
}
```

Field type, store and read all say `double`. So the value is lost either
side of the box: either `_env` is not the struct that was filled, or
`_env->q` is read from a struct that was never written. `1.0` for `q + 1`
means `q` read as `0.0`; `2.0` for `p * 2` means `p` read as `1.0`; and
`g2` — the same shape as `n` but with `q * 2` — prints `2.0`, i.e. `1.0`.
Those are not one consistent wrong value, so this is not a plain "the field
is zeroed": the two cases read different garbage, which is what an
UNINITIALIZED `malloc`'d env looks like.

**So the env is allocated (`malloc(_mojo_sizeof_n_lambda_1_env ())`), the
stores are emitted into it, and the callee reads a different block.** The
prime suspect is the boxing round trip: `mojo_bound_method_new(fnaddr, env)`
is a heap `MojoBoundMethod *`, `n()` returns it through an `int64_t`, and the
caller re-reads it with `mojo_fnptr_call_d0(fn)`. A `char *` capture behaves
differently (it prints a plausible-looking address rather than a small
number), which is consistent with the pointer surviving and only the
DOUBLE field being read from the wrong place — but that is a hypothesis, not
a measurement.

Note what makes this cheap to miss: the same three programs with an `int`
capture are correct (`fn = lambda: n + 1` prints `8`), and so is a `char *`
capture in most spellings. Only a `double` has no `int64_t` spelling, so only
a `double` cannot survive being homogenized — the same value-model wall as
`bugs/CODEGEN_lambda_call_boundary_loses_the_return_type.md` and
`bugs/CODEGEN_multi_kind_global_read_before_the_reassignment_reads_the_placeholder.md`,
reached through the closure env instead.

## Next step

1. Print the `MojoBoundMethod`'s `self` pointer and the `env` pointer at both
   ends (one `fprintf` in the generated C, or `mojo_bound_method_new`'s own
   body plus `_lower_fnptr_call_value`'s reconstruction) and diff them. That
   one measurement says whether the store or the read is at fault, and the
   whole bug is downstream of it.
2. If the `self` pointer round-trips correctly, the read is the problem: the
   lifted `n_lambda_1`'s parameter is typed `n_lambda_1_env *` by
   `_struct_method_csym`'s composer, and the boxed `int64_t` has to be
   re-narrowed to that pointer type before the call. Check whether it is
   re-narrowed or passed as an integer, and whether `_callable_value_symbol`
   / `mojo_fnptr_call_d0`'s `d`-suffixed (double-returning) variant has a
   matching argument convention — the `_d0..d4` twins exist and are keyed on
   the RETURN type, so the argument path for a `double`-returning callable is
   part of what has to agree here.
3. `k`'s row is the cheapest reduction of the whole thing (no env malloc
   ordering to reason about, one captured parameter, and the env field type
   is right in the C), so it is where to start.

## Evidence

- The two `.mojo` sources are the program above; both outputs are measured,
  not inferred, on this tree and on `HEAD`.
- The C excerpts are quoted from `compile_to_gimple`'s output for `n()`.
- `test_gimple_runner.py` is 301 passed / 10 failed both before and after the
  sibling fix, so this is not collateral from it.