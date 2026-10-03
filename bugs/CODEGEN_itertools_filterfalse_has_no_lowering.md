# CODEGEN: `itertools.filterfalse` has no lowering, so `importlib/resources/_common.py` refuses outright

Found 2026-10-01 while re-measuring
`bugs/COMPILE_FAIL_importlib_resources_readers.md`. That doc's blocker is
gone and a simpler one took its place.

## What I ran

```
python3 tools/memslot.py --gb 8 --label readers -- \
  python3 fire.py build -o .tmp/out/readers/readers \
  /Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py
```

`readers.py` now contributes **zero `error:` lines** and the whole-program
build gets past the five errors the 2026-09-30 entry recorded. It is
refused by a single module-level generator refusal, in
`importlib/resources/_common.py` (a closure member, not readers.py
itself):

```
cannot compile module: `next(...)` on next(IdentExpr) has no lowering in
this codegen — every fall-through here emitted a call to a `next` symbol
that does not exist, which fails at LINK rather than here. ...
```

The site is one line, `Lib/importlib/resources/_common.py:105`:

```python
    stack = inspect.stack()
    not_this_file = itertools.filterfalse(is_this_file, stack)
    callers = itertools.filterfalse(is_wrapper, not_this_file)
    return next(callers).frame
```

## Reduced, and the reduction is the finding

Six lines reproduce it:

```python
import itertools

def pick(xs, f):
    it = itertools.filterfalse(f, xs)
    return next(it)

print(pick([1, 2, 3], lambda v: v < 2))     # CPython: 2
```

**The refusal is CORRECT as a refusal and WRONG as a diagnosis.**
`itertools.filterfalse` has no lowering at all, so `callers` is an
unmodelled handle of unknown type, and `next()` over an unknown type
genuinely has no honest answer — the message names the shape it could not
resolve and the module falls back to source. That part is right.

What is *not* right is that the message implies `next()` is the missing
piece. Two adjacent facts, both measured:

- **Builtin `filter` is modelled** and does NOT trigger it:
  `it = filter(f, xs); return next(it)` compiles, links and prints `2`.
  So the problem is `itertools.filterfalse` specifically, not filtering,
  and not `next` over a list.
- **`iter(...)` is what the real fix needs**, and it already works:
  `return next(iter(it))` over the same `filter` result compiles and
  prints `2`. So `_lower_next_iter_container`'s `next(iter(<list>))` form
  is the correct landing spot once `filterfalse` produces a real list.

## A trap worth recording: the obvious fix is wrong, twice

The shape *looks* like "`next()` over a `MojoList *` local is
unsupported" — and it is, but adding it turns two CPython `TypeError`s
into values. Measured:

| | CPython | a `next(<bare MoJoList *>)` lowering would give |
|---|---|---|
| `next([1, 2])` | `TypeError: 'list' object is not an iterator` | `1` |
| `next({7, 8})` | `TypeError: 'set' object is not an iterator` | a value |

In Python a list and a set are **not** iterators — `hasattr([], '__next__')`
is `False`; only `iter(x)` produces one. So the bare spelling must keep
refusing for both, and only the `iter()`-wrapped spelling may accept
them. Any fix here has to keep that distinction, which is why the next
step is stated in terms of `filterfalse` rather than in terms of
`next()`.

## Next step

Give `itertools.filterfalse` a real lowering. The predicate-filtering
mechanism already exists — `_lower_builtin_filter` in
`mojo/backend_gimple/emit_calls.py` builds the filtered list element by
element and carries the input's element type onto the result — so the
honest implementation is that same builder with `only_truthy=False`, which
is exactly the difference between `filter` and `filterfalse`. That keeps
the representation a real `MojoList *`, after which
`_common.py:105`'s `next(callers)` needs the `iter()` spelling (or an
honest refusal that names the missing wrapper) rather than a
value-returning shortcut.

A regression belongs beside `test_gimple.py`'s
`test_dict_union_right_operand_is_converted_at_runtime` — same family
(modelled-vs-unmodelled builtin reached through a module-local) — and
must assert CPython's stdout on both pipelines, because the wrong fix
above *compiles and runs*, printing a value where CPython raises.