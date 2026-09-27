# HARD BUG: a `bool` that round-trips through a generator's value slot comes back as an integer — `1`, not `True`

**State: OPEN.** New 2026-09-26. Silent wrong value, exit 0. Found while fixing
the generator-consumption `value_ctype` bug (now fixed and its doc deleted); it
is a *distinct* defect that survived that fix, in the same value slot.

## Minimal repro

```python
def y():
    yield True

for b in y():
    print(b)
```

CPython prints `True`. The compiled program prints `1`.

## Evidence that the loss is at the generator slot, not at `print`

`print` handles bools correctly everywhere else in the compiled path, which
locates the defect precisely:

| program | CPython | compiled |
|---|---|---|
| `t = True; print(t)` | `True` | `True` |
| `print(not True)` | `False` | `False` |
| `print(True + 0)` | `1` | `1` |
| `for b in y_bool(): print(b)` | `True` | **`1`** |
| `for i in y_int(): print(i)` | `1` | `1` |
| `for a, c, d in tup_bool(): print(a, c, d)` | `x True False` | **`x 1 0`** |

Reproduce with `/tmp`-resident `.mojo` files and
`python3 fire.py build -o b bools.mojo && ./b`. Every row above was measured;
the three correct rows are the control that rules out `print`.

## Mechanism

`mojo/middle/coro.py` types a generator's single value slot with a four-valued
KIND, and `_KIND_CTYPE` maps it to a C type:

```python
_KIND_CTYPE = {'i': 'int64_t', 'p': 'char *', 'd': 'double', 'tuple': 'MojoList *'}
```

`_generator_value_kind` gives a `BoolLiteral` yield the kind `'i'`
(`_yield_kind`: `isinstance(expr, (N.IntLiteral, N.BoolLiteral)) -> 'i'`), so
the slot is `int64_t` and `<base>_value` returns `int64_t`. The stored value is
a correct 0/1 — the *bool-ness* is what is lost, not the value. There is no
`'b'` kind and no `_Bool` in `_KIND_CTYPE`, so nothing downstream can recover
it.

Tuple yields are affected identically and for the same reason: a `True` in a
tuple slot comes back as `1` (`x True False` → `x 1 0`). That path goes through
`_generator_tuple_slots` / `_KIND_TO_SLOT_CTYPE`, which likewise has no bool
entry — so this is one missing kind in the shared kind lattice, not two bugs.

## Why it is silent and not a refusal

The value is a *correct* 0/1 in a correctly-typed `int64_t` slot, so every
consistency check in the pipeline passes: the consumer's declared type, the
`_value` accessor's return type, and the callee's yield kind all agree. Nothing
downstream has any way to know a bool was involved. The only symptom is the
rendered text, and only where the value is printed — an int64_t 1 renders as
`1`. `print` is the sole observable, which is why this survived: every
structural test of the value slot is green.

## Not the same bug as the one just fixed

The generator-consumption `value_ctype` bug (doc now deleted) put the WRONG
ctype in the slot — `int64_t` where the callee yielded `char *` — so the value
was a pointer read as an integer. Here the ctype and the value are consistent
with each other and simply less precise than Python's: the fix for that bug
does not touch this one, and its regression tests stay green.

## Fix direction (not written)

Add a `'b'` kind to the lattice — `_KIND_CTYPE['b'] = '_Bool'`, a `_Bool`
literal case in `_yield_kind`, `_KIND_TO_SLOT_CTYPE['b'] = '_Bool'`, and the
matching `__mgco_*_value` accessor return type in `register`/`emit_c`. The
awkward part is the arg ABI, not the slot: a `_Bool` must cross
`__mojo_coro_yield_i` (an `int64_t` yield shim) as an `int64_t` 0/1 and be
re-narrowed on the `_value` side, the same round-trip the `'d'` kind already
does with `__mojo_coro_yield_d` / `__mojo_gen_arg_d`. So this is a new entry
in an existing four-way mechanism, not a new mechanism — but it touches
`register`/`emit_c`, which is why it is not a drive-by.

Two things to decide before writing it, both beyond a mechanical edit:

- **Mixed bool/int yields.** A generator yielding `True` on one path and `1`
  on another has no single right answer for one slot. `_generator_value_kind`
  already refuses mixed int/string and mixed float/int
  (`'mixed int / string yields (v0)'`); mixed bool/int wants the same
  treatment rather than a silent widening to `'i'`.
- **Unannotated call-site params.** A caller passing a bool into an
  unannotated parameter is currently recorded as kind `'i'` by
  `_scan_callsite_param_kinds`; if `'b'` exists, that scan has to be able to
  produce it or the two will disagree.

No real-corpus occurrence was hunted for. The shape is common enough in Python
(`yield`ing a flag is ordinary), but nothing was measured, so the blast radius
below is a guess and should not be relied on.
