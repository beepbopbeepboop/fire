# CODEGEN: the in-process single-unit path compiles a bracketed generic call to 0

**Area:** `gimple_codegen.py` / the `do_imports=False` single-unit path (the
inline pipeline), exercised by `test_comptime_assert_diagnostic.py`.

## Measured (clean HEAD, before the alias fix)

```
python3 -m pytest -q test_comptime_assert_diagnostic.py -k bracketed_call
```

fails with

```
AssertionError: a bracketed generic call compiled in-process (it would print 0)
```

The program under test:

```
def f[x: Int]() -> Int:
    return x + 1

def main():
    print(f[1]())
```

## Expected

`compile_to_gimple(src, do_imports=False)` refuses with a `RuntimeError`
whose message contains `needs the generic instantiated` and `link mode`, because
the single-unit path does not instantiate a generic. The test's comment says
the stub this path used to emit printed 0 where the real build prints 2.

## Actual

No exception. The compile succeeds, so the program would print 0. The refusal
the test pins is not produced, so the silent miscompile the refusal exists to
prevent is back.

## Exact next step

1. Run the snippet above through `compile_to_gimple(..., do_imports=False)`
   and find where the bracketed call `f[1]()` is lowered: confirm that no
   `RuntimeError` is raised and see what symbol/stub is emitted.
2. Find the guard that was meant to raise `needs the generic instantiated`
   (`grep -rn "needs the generic" --include=*.py`) and why it no longer fires
   for a bracketed call to a plain `def` generic.
3. Restore the refusal (not a special case for this input), then re-run
   `python3 -m pytest -q test_comptime_assert_diagnostic.py`.

Found while verifying the module/local `alias` run fix; the alias change does
not touch this path.
