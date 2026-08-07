# CODEGEN_generator_function: Lib/test/test_doctest/test_doctest.py

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) — same symptom family as 2026-07-30, still reaching the
real coroutine `.cpp` compile stage:

```
test_doctest_gen.cpp:106:12: error: 'TestHook' was not declared in this scope
test_doctest_gen.cpp:109:18: error: request for member 'remove' in 'hook', which is of non-class type 'int64_t' {aka 'long long int'}
```

**Root cause:**
```python
@contextlib.contextmanager
def test_hook(pathdir):
    hook = TestHook(pathdir)
    try:
        yield hook
    finally:
        hook.remove()
```
`hook = TestHook(pathdir)` — `TestHook` is a module-level class defined
elsewhere in the file. **Classification: two already-documented
dyld.py-cluster gaps hitting together:**
1. `TestHook` (the class NAME itself) isn't threaded into the generator
   body's C++ scope — the same "outer-scope name not in scope inside
   generator" gap already generalized in `bugs/CODEGEN_generator_
   function_Lib_test_libregrtest_runtests.md`'s re-diagnosis (there for
   a module name AND an enum class; here for an ordinary class name).
2. `hook`'s inferred type falls back to `int64_t` (the untyped-local
   variant of dyld.py's bullet 1 "untyped params default wrong" —
   `hook` is a plain local assigned from a constructor call, not a
   function parameter, but the same missing usage-based-inference root
   cause applies), so `hook.remove()` fails with "request for member
   'remove' in ... non-class type 'int64_t'".

Not fixed here — both are established, already-documented gaps in the
generator-codegen path.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_doctest/test_doctest.py
