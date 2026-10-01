# CODEGEN: `next(it)` inside `for x in it:` returns the element the loop already yielded

`it = iter(<list>)` lowers to a shared list + int64_t cursor
(`_try_bind_list_iter`, `mojo/backend_gimple/emit_stmts.py`). Both the
`for x in it:` lowering and the `next(it)` lowering read
`mojo_list_get_<suffix>(lst, cur)` and then advance `cur`. That is
individually correct for a single-pass iterator, but the two together are
an OFF BY ONE: the `for` loop's advance happens in its post block, AFTER
the body, so while the body runs the cursor still points AT the element
the loop just handed to `tkn` — and `next(it)` reads exactly that one
again.

Real Python's `list_iterator.__next__` advances before returning, so by
the time the loop body runs the iterator is already one past the yielded
element, and a `next(it)` in the body reads the FOLLOWING one.

## What I ran

```python
def walk(items):
    it = iter(items)
    out = []
    for x in it:
        out.append(x)
        nxt = next(it)
        out.append(nxt)
    return out

def main():
    print(walk([1, 2, 3, 4]))

main()
```

`python3 fire.py build -o .tmp/out/t_next .tmp/py/t_next.py` — builds,
exit 0. Run both:

```
$ python3 .tmp/py/t_next.py
[1, 2, 3, 4]
$ .tmp/out/t_next
[1, 1, 3, 3]
```

Two elements are consumed and each is reported twice instead of four
distinct elements being reported once each. The `for` loop also loses
half its iterations as a consequence.

This is exactly the shape CPython's
`Tools/cases_generator/analyzer.py::check_escaping_calls` uses:

```python
tkn_iter = iter(stmt.contents)
for tkn in tkn_iter:
    ...
        next(tkn_iter)
```

The C++ coroutine backend has the same two-sided structure and therefore
the same defect: `mojo/backend_gimple/cpp_core.py`'s `_cpp_for_stmt`
emits `{target} = mojo_list_get_int({list}, {cur});` as the loop BODY with
`{cur}++` as the for-increment (i.e. the same "advance after the body"
ordering), while `_cpp_list_iter_cursor`'s `next(it)` read happens before
the increment. Both backends need the same correction.

## What I expected

`[1, 2, 3, 4]` — CPython's answer, printed identically by the compiled
binary.

## Next step

Move the advance so the cursor means "index of the next unconsumed
element" everywhere, i.e. the Python invariant:

- `mojo/backend_gimple/emit_loops.py::_gen_for_list_iter_cursor` — emit
  `var = mojo_list_get_<suffix>(lst, cur)` **and** `cur = cur + 1` at the
  TOP of `bb_body`, and drop the advance from `bb_post`. `bb_post` stays
  in the `loop_stack` so a `continue` still lands somewhere correct, but
  it becomes just the jump back to `bb_cond`.
- `mojo/backend_gimple/cpp_core.py::_cpp_for_stmt`'s
  `_cpp_list_iter_cursor` branch — advance in the loop body rather than in
  the C++ for-increment.
- `_lower_next_list_iter` / the cpp equivalent need NO change: with the
  invariant restored, "read at `cur`, then advance" is exactly right.

Regression test: the `t_next.py` program above, run on BOTH pipelines with
CPython on the same text as the expectation (the `test_gimple.py`
`cursor_advance_has_no_cast_operand_in_gimple` test is the shape to copy —
it lives next door and already covers the compile half of this same
lowering). The existing test must keep passing: it only does `next(it)` in
a `range()` loop, never inside `for x in it:`, which is why the off-by-one
survived the `+ 1` cast fix that landed alongside it.

## Why this was not fixed in the same commit

Commit `6a7c69fd` fixed the `(int64_t)1` cast operand in these exact five
advance sites, which is what made this lowering compile at all, and it is
visible in the same code. Changing the cursor INVARIANT is a different
change with a different blast radius (every `for x in <bound cursor>` in
the tree, both backends), and it is the silent-wrong-value class that
`construct:compiled-silent-wrong-values` is already tracking. It should not
ride along on a fix whose stated job is "this shape is not valid GIMPLE".
