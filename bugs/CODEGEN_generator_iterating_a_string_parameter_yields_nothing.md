# CODEGEN: a generator that iterates a STRING PARAMETER and yields its characters produces nothing

**State: OPEN, unfixed.** Found 2026-10-02 while fixing
`CODEGEN_callable_param_called_in_ordinary_generator_returns_garbage.md`'s
generator half; that doc's own repro only masked it.

## What I ran and what I saw

```python
def apply_to(items):
    for it in items:
        yield it

def go():
    for v in apply_to('ab'):
        print(v)

go()
```

| | CPython | compiled |
|---|---|---|
| `go()` | `a` then `b` | **nothing at all**, exit 0 |

```python
def go():
    s = 'ab'.upper()
    for it in s:
        print(it)
go()
```

prints `A` then `B` on both, so this is not "a generator cannot yield a
character" and not "a string cannot be iterated in a generator": it is the
two together, with the string arriving through the generator's own
untyped-`int64_t` parameter slots.

**Pre-existing, and independent of the change that uncovered it.** Measured
on this tree at `bc17a62b` (the merged bug-batch state this session started
from) with every edit of this session reverted: the same empty output.

## Why it is not the callable-parameter bug

The doc above is about a callable-valued parameter whose CALL returns the
homogenized `int64_t` box. That fix is about the value a call THROUGH a
parameter produces, and it is complete: `len(_f(items))` inside a generator
body now answers CPython's `2`. This bug has no callable in it — the string
comes in through the parameter slot, `__mojo_gen_arg`, which is untyped.

## Mechanism, as far as it is traced

`coro._mark_coro_param_elem_kinds` is the existing precedent and, read in
this light, its own docstring names the gap: a generator's parameters cross
the stack-switch ABI as untyped `int64_t` slots, so `for <t> in <param>:`
in the body reaches the ORDINARY loop lowering as a boxed handle with no
container type **and no element type**. That helper attaches
`_mojo_coro_param_elem_kinds` (`{param: element C type}`) built from
`_static_env`, which answers `('list', k)` for a LIST parameter from the
unanimous cross-call-site contract — and has nothing to say for a `str`
parameter, whose element type is `char` (a 1-character string) rather than
one of the `'i'/'b'/'p'/'d'` container kinds `_KIND_CTYPE` maps.

So the loop target `it` is declared with the wrong type, the `yield` slot is
fed from it, and the consumer sees nothing. Two candidate fixes, in the
order they should be tried:

1. **`_static_env` should answer `('str', 'c')` for a parameter whose
   resolved type is a string**, and `_mark_coro_param_elem_kinds` should
   attach a 1-character-string element type for it. That is the same
   evidence the list arm already uses and needs no new analysis — the
   question is whether `_static_env`'s cross-call-site contract records a
   `char *` parameter at all, and whether the loop lowering accepts a
   `char`-element kind.
2. **A refusal.** `for <t> in <param>: yield <t>` inside a generator whose
   parameter type is a string could be refused the way an unresolvable
   iteration is (`mojo_unsupported_iter`), which converts a silent
   zero-iteration into a diagnostic. Smaller, and the honest interim if (1)
   turns out to be larger than it looks.

## Regression test

`test_gimple_generator_runner.py`, next to
`generator_callable_param_result_keeps_its_type`, asserted against CPython's
exact text. The control that keeps it honest is the `s = 'ab'.upper()`
program above: it passes today, so a fix that made the parameter path pass by
broadening something else would show up as that one going red.
