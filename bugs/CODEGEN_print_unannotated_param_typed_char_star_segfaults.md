# CODEGEN: `print(<unannotated param>)` types the parameter `char *` and segfaults on an int argument

**State: OPEN, reproduced 2026-09-29, mechanism located, not fixed.**

Found while working `bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md`'s
"test hole" section, whose claim about this shape was **wrong** and is corrected
below.

## Symptom

```mojo
def g(x):
    print(x)

def main():
    g(1)
```

    CPython:   1
    compiled:   <no output>   SIGSEGV, exit 139

The generated C declares the parameter `char *` and the call site passes the
integer as a pointer:

    void g_d719e0 (char * x) { mojo_print (x); ... }
    ...
    _t1 = (void *)_t3;          /* _t3 = (int64_t)1 */
    _t2 = (char *) _t1;
    g_d719e0 (_t2);

so `mojo_print` `strlen`s address 1.

Measured variants (all CPython-verified, compiled with the gimple backend and
run; harness = compile -> `gcc -fgimple` -> link `fire_runtime.c` + the A3
coroutine objects -> run, compared against `exec`-ing the same text as Python):

| program | CPython | compiled |
|---|---|---|
| `print(x)` , `g(1)` | `1` | **SIGSEGV (139)** |
| `print(x)` , `g(1.5)` | `1.5` | **compile error** (`gcc -fgimple`) |
| `print(x)` , `g("s")` | `s` | `s` (correct) |
| `print(x, x)` , `g(1)` | `1 1` | **SIGSEGV (139)** |
| `print("v=", x)` , `g(1)` | `v= 1` | `v= 1` (correct) |
| `print(str(x))` , `g(1)` | `1` | `1` (correct) |
| `print(x + 1)` , `g(1)` | `2` | `2` (correct) |
| `return x` then `print(g(1))` , `g(1)` | `1` | `1` (correct) |

So the trigger is narrow: the parameter's ONLY use is as a **bare argument to
`print`**. Every other spelling tested is already right.

## Mechanism

`mojo/middle/infra_infer.py`, `_infer_param_types`'s `BUILTIN_PARAM_TYPES`:

```python
BUILTIN_PARAM_TYPES = {
    'open': 'char *',
    'mojo_open_file': 'char *',
    'print': 'char *',
    'str': 'int',
}
```

A parameter passed to `print` is inferred to be a `char *` and the
inference wins over the `int64_t` default, so the emitted signature is
`void g(char * x)`.

`'len'` was **already removed from this same table** for exactly this class of
bug, and its removal note is the specification of what is wrong with `'print'`:

> `len` deliberately excluded: passing a param to `len()` means it's a SIZED
> CONTAINER (str/list/dict/set/tuple — no single correct C type to default
> to), not that the param's own type IS `int` — that's len()'s RETURN type,
> not its argument's type. This entry used to wrongly infer 'int' for any
> unannotated parameter whose ONLY usage signal was `len(param)` ... producing
> a compiled function whose parameter was declared `int` while every real
> caller passed a genuine pointer (str/list) argument — "passing argument 1 of
> '<fn>' makes integer from pointer without a cast".

`print` has the identical defect with the roles swapped: `print` accepts a
value of ANY type in Python, so `print(x)` says nothing at all about `x`'s
type, and inferring `char *` from it is the same unsound inference that was
removed for `len`.

## Correction to the doc that pointed here

`bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md` said of the
`print(x)` half of its test hole:

> That `print(x)` half is the cross-cutting one-C-type-per-slot limitation the
> doc's Correction 1 already names (**an ordinary `def g(x): return x` does the
> same**)

Both halves of that are wrong on the current tree, re-measured 2026-09-29:

- It is **not** the one-C-type-per-slot limitation. That applies when two
  call sites DISAGREE. `def g(x): return x` with `print(g(1))` is correct
  (row 8 of the table), and `def g(x): print(x)` segfaults with a **single**
  call site passing an int. There is no disagreement here at all — the
  inference is simply wrong from one observation.
- An ordinary `def g(x): return x` does **not** do the same.

The generator spelling of the same body is a *different* mechanism and is not
covered by the `BUILTIN_PARAM_TYPES` fix:

```mojo
def g(x, y):
    print(x)
    yield y

def main():
    for v in g(1, 3.5):
        print(v)
    for v in g("s", 1.5):
        print(v)
```

    CPython:   1 / 3.5 / s / 1.5
    compiled:  1 / 3.5 / 4367506888 / 1.5      (exit 0)

Here `x` IS correctly typed `int64_t` in the A3 body
(`_t1 = __mojo_gen_arg (__c, _t2); x = _t1;` then `sprintf (_t5, "%ld", x)`),
so the defect is that `print` of an `int64_t` holding a `char *` renders the
pointer as a decimal instead of the string. That is a missing runtime type
test in `print`'s lowering, not a parameter-typing error.

## Done when

- `def g(x): print(x)` called with an int, a float and a string each prints
  what CPython prints (the int and float cases at minimum; they are the two
  that crash today).
- `'print'` is either removed from `BUILTIN_PARAM_TYPES` the way `'len'` was,
  or the entry is qualified so it only applies where the body ALSO has
  string-only evidence for the param (`STRING_ONLY_METHODS`,
  `param.find(...)`, subscripting a `str` result, ...). Removing it is the
  smaller change and is the direction the `len` note already establishes.
- A regression test in `test_gimple_runner.py` next to
  `gimple_untyped_param_string_passthrough`, which is the existing coverage for
  the sibling case that must keep working.

## Note on scope

`infra_infer.py` is shared with the self-hosted compiled path and with the
coroutine body emitter, so this needs a full `make gate` — it is not a
single-suite change.
