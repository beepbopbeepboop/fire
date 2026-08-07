# HARD BUG: recursive `yield from` generator with extra/keyword-only parameters miscompiles in the C++ coroutine codegen

## Status

Unfixed. Real, reproducing bug in `gimple_codegen.py`'s C++20-coroutine
generator codegen path (`compile_to_gimple_with_cpp` /
`module_may_have_supported_generator`) — not attempted, as it's a
substantial addition to an already-complex code path, not a small patch.

## Symptom

Depends on which check the module hits first:

- Some shapes are rejected outright, before any C++ is even generated:
  ```
  Error building: cannot compile module: function(s) iter_files (generator
  function(s), contain a `yield`/`yield from`) — this codegen compiles
  every function into a single straight-line C function and has no
  suspend/resume state-machine transform for generators, ... falling back
  to interpreting this module from source instead
  ```
  (`RuntimeError` from `gen_module`; `mojo.py build` reports this as
  "Error building", RC=1, no object file — despite the message claiming a
  source-level fallback, the CLI path does not actually fall back and the
  build fails.)

- Other, similarly-shaped generators get *past* that pre-check and reach
  the real g++ coroutine compile, which then fails with concrete C++
  errors exposing two distinct real bugs in the generated coroutine code:
  1. **Keyword-only arguments aren't forwarded on the recursive call.** The
     recursive `iter_files(...)` call inside the generator's own body is
     lowered with fewer arguments than the function's real C signature
     declares:
     ```
     main_gen.cpp:115:50: error: too few arguments to function 'void iter_files_7a6366(int64_t, int64_t, int64_t, int64_t)'
     ```
  2. **The yielded value's inferred type doesn't match the coroutine
     promise's `yield_value` signature** (a bare parameter falls back to
     `int64_t`, but the promise was generated expecting `char *`):
     ```
     main_gen.cpp:122:14: error: invalid conversion from 'int64_t' to 'char*' [-fpermissive]
     ```

## Minimal repro

```python
# main.mojo — reproduces the concrete C++ errors (arity + yield-type mismatch)
def iter_files(root, suffix=None, relparent=None, *,
               get_files=None,
               ):
    if not isinstance(root, str):
        roots = root
        for root in roots:
            yield from iter_files(root, suffix, relparent,
                                  get_files=get_files)
        return
    yield root
```

```
$ python3 mojo.py build main.mojo
Generator (.cpp) compilation failed: ...
main_gen.cpp:115:50: error: too few arguments to function 'void iter_files_7a6366(int64_t, int64_t, int64_t, int64_t)'
main_gen.cpp:122:14: error: invalid conversion from 'int64_t' to 'char*' [-fpermissive]
```

(RC=1, no object file. Reproduces identically whether the keyword-only
default is `None` or a real function value, e.g. `get_files=os.walk` —
not specific to function-valued defaults.)

## Real-world file exposing this

`Tools/c-analyzer/c_common/fsutil.py`'s `iter_files` (the real function this
repro is distilled from):

```python
def iter_files(root, suffix=None, relparent=None, *,
               get_files=os.walk,
               _glob=glob_tree,
               _walk=walk_tree,
               ):
    if not isinstance(root, str):
        roots = root
        for root in roots:
            yield from iter_files(root, suffix, relparent,
                                  get_files=get_files,
                                  _glob=_glob, _walk=_walk)
        return
    ...
```

The real file hits the blanket pre-check rejection (first symptom above),
not the concrete C++ errors the minimal repro reaches — some difference in
how the pre-check scans this larger, more heavily-parameterized shape trips
the outright refusal instead of letting it through to the real compile
attempt. Root cause of *that* difference not identified; not required to
demonstrate the two real bugs above, which the minimal repro proves
directly.

Note: this file was originally reported (`bugs/
COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`) for a *different*
symptom — `exc.filename` access in `create_backup` ("request for member
'filename' in something not a structure or union"). That specific error no
longer reproduces: the module-level generator check above now fires first
and blocks compilation earlier, before `create_backup` is ever reached.
Whether the original `.filename` bug is itself still latent (fixed, or
just masked) is unconfirmed — masked either way by this generator gap
today.

## Additional real occurrence (2026-08-06)

Found again while classifying the `CODEGEN_generator_function_Lib_*.md`
cluster (tasks #95-135): `Lib/test/test_exception_group.py`'s own
`leaf_generator(exc, tbs=None)`:
```python
def leaf_generator(exc, tbs=None):
    if tbs is None:
        tbs = []
    tbs.append(exc.__traceback__)
    if isinstance(exc, BaseExceptionGroup):
        for e in exc.exceptions:
            yield from leaf_generator(e, tbs)
    else:
        yield exc, tbs
    tbs.pop()
```
Same shape as this doc's own repro (recursive `yield from` to itself,
with a defaulted extra parameter, `tbs=None`) — but here the failure
mode is DIFFERENT from either of the two symptoms already documented
above: instead of a clean whole-module refusal OR clean, isolated C++
errors, this instance produces ~150 severely garbled/malformed
declaration errors in the PLAIN `.ci` output itself (`error: type
defaults to 'int' in declaration of ...`, `error: expected '=', ',',
';', 'asm' or '__attribute__' before ':' token`, `error: conflicting
types for 'mojo_list_append_int'` and other RUNTIME HELPER functions —
suggesting the emission got badly desynchronized, likely missing a
brace or falling out of a function body mid-emission) at
`test_exception_group.py:574-598` (NOT inside a `_gen.cpp` file — this
is the plain gcc-compiled `.ci`, meaning the malformed emission happens
in whatever caller-side inline-driving-loop code consumes this
generator, not in the coroutine `.cpp` unit itself). See
`bugs/CODEGEN_generator_function_Lib_test_test_exception_group.md` for
the full current error list. A third failure MODE for what's likely the
same underlying "recursive yield-from with an extra parameter" root
cause — worth noting for whoever picks this up that the blast radius
isn't limited to a clean refusal or isolated errors; it can also corrupt
the surrounding plain-C emission badly enough to cascade into completely
unrelated-looking syntax errors against this codegen's own runtime
helper declarations.

## What a real fix needs

At minimum: (1) forward keyword-only arguments on recursive `yield from`
calls inside a generator being lowered to a coroutine, and (2) infer the
coroutine promise's `yield_value` parameter type from the actual yielded
expression's type rather than defaulting to `int64_t` for an unannotated
parameter. Both are incremental fixes to the existing C++ coroutine
codegen, not a new capability — but nontrivial given how much of that path
is already fragile/special-cased (see `A5-BUG.md` and the ICE-avoidance
comments throughout `gimple_codegen.py`'s async/generator lowering).
