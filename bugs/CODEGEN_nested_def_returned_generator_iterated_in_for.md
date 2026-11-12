# CODEGEN: a generator returned through nested defs is refused at build

Split out 2026-11-12 from the tuple-slot-zero-prints-None bug (its "Second gap"),
whose first gap was fixed in 1f1ac8bb3; the second gap was not part of that fix.

## Reproducer (today)

```
def walk(xs):
    for i, st in enumerate(list(xs)):
        yield xs, i
def outer(body):
    def inner(fn):
        return walk(fn)
    return inner(body)
def main():
    for p in outer([1, 2]):
        print(p[1])
main()
```

Expected (CPython): `0` and `1`.

Observed (`python3 fire.py build -o <exe> <file>`, exit 1, no executable):

    Unsupported shape(s): walk: yields ['xs'], whose call sites do not all pass
    the same statically-known type (they disagree, or one of them the static
    scan could not type at all) ...

The same refusal comes from `test_gimple_generator_runner._build_generator_program`.

## What the original report saw (not re-run)

The original report's shape (a recursive `walk` that calls `yield from walk(sub)`
on `getattr(st, fld, None)` values) built, and its `for p in outer(...)` loop ran
ZERO times with `mojo_unsupported_iter: 'for' loop over unsupported iterable type
<unknown>: MojoGenerator *`, silently. Today's build refuses instead, so the
silent-zero behaviour may be gone for that shape or may only be hidden by the
refusal; re-run the original shape before relying on either description.

## Exact next step

1. In the static call-site scan that produces the `Unsupported shape(s)` message,
   find why the argument of `walk(fn)` is untyped: `fn` is an untyped parameter of
   the nested `inner`, whose only caller passes `body`, which is `outer`'s
   untyped parameter, called with `[1, 2]`. Expected: the scan follows the nested
   def's argument to its literal (`list[int]`), so `walk`'s `xs` slot is typed.
2. If the scan cannot follow it, the refusal is the correct answer: keep it, and
   make sure no path returns a generator object as an iterable of zero length.
3. Pin with a `test_generator_stdout` case in `test_gimple_generator_runner.py`
   (the reproducer above, expecting `0\n1\n`) once it builds.
