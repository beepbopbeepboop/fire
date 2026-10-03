# CODEGEN: `next(<generator>)` in a function's RETURN position is truncated to `int64_t`

A compiled generator's yielded value is correct everywhere it is consumed
**except** when a function `return`s it directly: the enclosing function's
return type is inferred as `int64_t`, so a yielded `char *` comes back as a
raw heap address (printed in decimal) and a yielded `double` comes back
truncated. **Exit 0, no diagnostic.**

## Minimal repro

```python
def mk():
    yield 'q'
def h():
    return next(mk())
print(h())
```

```
CPython   : q
compiled  : 4331039728        <- the char* value, printed as an integer
```

arm64, `gcc -fgimple` + the `fire_coro_gen.c` / `fire_coro.c` /
`fire_async_sched.c` runtime (the same link set `test_gimple_runner.py`
assembles when the generated C contains `__mgco_`). Measured on
`6b9b6b18`.

## Scope: EVERY non-int64_t yield type, and only in return position

Four yields, one call shape each, all through `return next(mk())`:

| yield | CPython | compiled |
|---|---|---|
| `yield 7` | `7` | `7` — **correct** |
| `yield 'q'` | `q` | `4366085104` — the pointer |
| `yield 1.5` | `1.5` | `1` — truncated |
| `yield [1, 2]` | `[1, 2]` | `4380596752` — the pointer |

`int64_t` survives because it happens to be the return type's own
representation. Every other scalar kind is destroyed, and a `float` is
destroyed *silently to a plausible number*, which is the worse of the two:
`1.5` -> `1` is not obviously wrong to a reader.

## And only in RETURN position — three near neighbours are all correct

Same generator, same `next()`, four consumption shapes:

```
for x in mk(): print(x)     -> q          CORRECT
list(mk())                  -> ['q']     CORRECT
r = next(mk()); print(r)    -> q          CORRECT
return next(mk())           -> 4366085104 WRONG
```

So this is **not** a `next()` lowering bug, and not a generator-protocol
bug. `for` and `list()` drive the identical
`__mgco_mk_start` / `_resume` / `_value` triple and read the value slot
correctly. The `for` body's own emitted C for the read is byte-identical to
the `next()` case:

```c
/* both shapes */
_t3 = __mgco_mk_value (_t1);
x = _t3;                     /* for-loop: correct */
...
_t4 = __mgco_mk_value (_t1);  /* next():    also correct */
goto bb_5;
```

The value is read correctly in both. The difference is entirely in what the
enclosing function does with it afterwards, which pins the bug to
**function return-type inference**.

## Root cause

`_lower_generator_next` (`emit_calls.py:141`) returns `(vct, result)` with
`vct` the generator's `api['value_ctype']` — `char *` for a string yield,
`double` for a float yield. That is right, and the emitted temps are typed
correctly (`char * _t4;` holding `__mgco_mk_value(...)`, then
`_t6 = (void *)_t4; _t7 = (int64_t)_t6;`).

The loss is one level up. `h` is emitted as:

```c
int64_t h (void) { ... return _t5; }   /* _t5 is int64_t */
```

so the `char *` is returned through an `int64_t` return slot and the caller
prints the address. `h`'s C return type came from the return-type inference
pass, which types a function whose body is `return <call>` from the
**callee's declared return type** — and `next()` is a builtin with no
declared return type to consult, so it falls to the `int64_t` default.

The corroborating detail: adding an explicit `str()` around the value makes
the program print `q` again.

```python
def h():
    return str(next(mk()))
```

`str` HAS a declared return type (`char *`), the enclosing function is
inferred `char *`, and the value survives. That is the same inference
missing one row for `next`, confirmed from the other side.

## Next step

Teach the return-type inference that a `return next(<generator>)` (and the
`return`-of-a-local-bound-to-one shape, which behaves identically) has the
generator's `value_ctype`, not `int64_t`.

The generator api is already reachable from the inference pass:
`self._generator_api[name]['value_ctype']`, the same lookup
`_lower_generator_next` performs at emission time, and the same
`{'base', 'value_ctype'}` dict `_fn_returns_generator`
(`module_gen.py:6627`, filled at `:6720`) already points at. So the
inference needs a `next(<generator-call>)` row that resolves the generator
behind the call and returns its `value_ctype` — the inference-side twin of
what `_lower_generator_next` already knows.

Two things worth checking while there, because they are the same row:

* `yield from <generator>` and `x, = <generator>` in return position are the
  same shape and are expected to be broken identically; they should be
  covered by whatever row is added, not left as a third variant.
* the 2-argument `next(g, default)` form has a genuinely `int64_t`-or-`char *`
  union result and must NOT be typed as the generator's `value_ctype`; it
  needs the join with `default`'s type.

A regression test belongs next to the generator tests in
`test_gimple_generator_runner.py`, comparing the compiled program's stdout
against CPython's on the same source (a `for`-loop test cannot catch this —
the `for` path is already correct, which is exactly why this survived).
The test must cover a NON-`int64_t` yield; a `yield 7` fixture passes today
and would prove nothing.

## Why it was not found by a build sweep

The build is clean and the program exits 0. A sweep that only checks "built,
exit 0" reports this file as green; only comparing stdout against CPython
catches it — the same distinction
`bugs/COMPILE_FAIL_Tools_cases_generator_parsing.md` records for its own
`globals()` weak-stub case.