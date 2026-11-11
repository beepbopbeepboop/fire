# DIAGNOSTICS_missing_validation_modular part 4: fold `_get_kgen_string` in diagnostic messages

Part 4 of the split of `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`.
The umbrella's Status names "reflection-driven messages like
`StaticString(_get_kgen_string[...])`" as an open shape.

## Why this part

`comptime assert`/`constrained` messages are folded by
`mojo.middle.comptime.eval_const` so a diagnostic reads
`expected positive number, got -2` instead of a compiler temp name. The
`String(...)` / `StaticString(...)` / `StringSlice(...)` wrappers are already
transparent to that fold. The standard library's reflection spelling is not:

```mojo
from std.collections.string.string_span import _get_kgen_string

fn f():
    comptime assert False, StaticString(_get_kgen_string["hello"]())
```

The AST is a `CallExpr` whose function is a `SubscriptExpr` over
`IdentExpr('_get_kgen_string')` with a string-literal index, wrapped in
`StaticString`. `eval_const` has no case for it, so the message does not fold.

Measured 2026-11-10 with a local stand-in for the stdlib declaration:

```mojo
def _get_kgen_string[s: String]() -> String:
    return s

fn f():
    comptime assert False, StaticString(_get_kgen_string["hello"]())
```

The compiler raises `comptime assertion failed: _t2`; the expected message is
`hello`. (`StaticString("hello")` alone already folds to `hello`.)

## Scope

`mojo/middle/comptime.py::eval_const` only:

- recognise `CallExpr(func=SubscriptExpr(obj=IdentExpr('_get_kgen_string'),
  index=<foldable string>), args=[], kwargs=[])` and return the folded index
  string. `_get_kgen_string` is a compiler builtin name in the same sense as
  `String`/`StaticString`: the fold is by name, not by importing the stdlib
  module, so it also works for the reduced test above.
- Fold the index with `eval_const` first (a literal, a comptime alias, or
  `String` concatenation), so `_get_kgen_string[name]` works when `name` is a
  comptime string.
- Leave an unknown index, a non-empty argument list, or any other
  `_get_kgen_string` shape unfolded (return `None`), exactly as today.
- Do not add a second copy of the string-wrapping rule; the existing
  `StaticString`/`String`/`StringSlice`/`StringSpan` case already turns the
  result into a message. If `eval_const_int`/`eval_const_bool` have a separate
  `_get_kgen_string` path later, call this one helper rather than duplicating
  it.

## Acceptance

Add to `test_comptime_assert_diagnostic.py`:

```python
def test_comptime_assert_message_get_kgen_string():
    src = ('def _get_kgen_string[s: String]() -> String:\n'
           '    return s\n'
           'fn f():\n'
           '    comptime assert False, StaticString(_get_kgen_string["hello"]())\n')
    try:
        # _compile_full: do_imports=True + a real temp file, the path that
        # elaborates the generic `_get_kgen_string[s]` call.  The plain
        # do_imports=False helper folds the message to the literal text
        # `comptime assertion failed`, which is a different (and also wrong)
        # path.
        _compile_full(src)
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed: hello' in s, s
        assert '_t' not in s.split('comptime assertion failed:')[-1], s
        return
    raise AssertionError('provably-false comptime assert compiled')
```

Also cover an unknown index (the message must remain unfolded and must not
crash) and the `constrained` form in `test_constrained_diagnostic.py`.

Run only:

    python3 test_comptime_assert_diagnostic.py
    python3 test_constrained_diagnostic.py

No suite registration and no whole-closure compile. The real
`std.collections.string.string_span` import pulls the whole stdlib and is not
required for this acceptance; the local declaration produces the same AST.

## Status
- **Open.**
