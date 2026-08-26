# HARD BUG: recursive `yield from` generator with extra/keyword-only parameters miscompiles in the C++ coroutine codegen

## Status (updated 2026-08-26)

**Re-verified 2026-08-26** (fresh repro, independent of the 2026-08-23 note
below): rebuilt this doc's own minimal `iter_files` repro from scratch via
`python3 mojo.py build` — exit 0, clean build, no trace of either originally-
documented error. Then actually ran the produced binary against
`iter_files(["a.txt", "b.txt"])` (the 2026-08-23 note recorded the wrong-
output symptom but this session re-confirmed it independently): output is
a single garbage integer (`4361461520` this run, value differs run to run —
consistent with the previously-noted uninitialized/miscomputed value,
e.g. `43637542464` on 2026-08-23), not `a.txt`/`b.txt`. So: build-level fix
still holds exactly as documented; the runtime-correctness gap for this
specific shape (string values through a self-recursive `yield from` with
defaulted params) is also still exactly as documented, unfixed, and
untouched this session. Doc kept (not git rm'd) because it is not resolved
end-to-end — the arg-forwarding/type-mismatch fix this doc primarily
tracks is confirmed still good, but the doc's own final paragraph already
flags the runtime bug as a distinct, un-fixed issue worth separate
tracking, so nothing here is stale.

**Re-verified FIXED 2026-08-23**: this doc's own minimal repro
(`iter_files` with keyword-only `get_files`) builds clean via `python3
mojo.py build` (exit 0) — both originally-documented errors ("too few
arguments to function ...", "invalid conversion from 'int64_t' to
'char*'") remain gone. The doc's runtime-verified second shape
(`countdown(n, *, step)`, self-recursive `yield from` with a
keyword-only arg) also still builds AND runs, printing the correct
`5\n3\n1\n`. No regression of anything this fix claimed.

New observation, NOT a claim of this fix and NOT a regression of it:
the iter_files repro now builds but its output is WRONG at runtime
(prints a single garbage integer, e.g. `43637542464`, instead of
iterating `["a.txt", "b.txt"]`). The 2026-08-07 verification only ever
claimed a CLEAN BUILD for this repro (runtime correctness was verified
on countdown only), so the fixed-state bar documented here still holds —
but the wrong-output shape (string values flowing through a recursive
`yield from` with defaulted params) is worth its own hard-bug doc.

**FIXED** (task #138). Real root cause, precisely identified: a
generator's registration into `self._generator_api` (the dict every
`yield from <call>` site consults to recognize "this delegates to a
generator I've already compiled") only happens AFTER `_gen_cpp_
generator_unit` finishes translating the WHOLE function successfully —
so a genuinely SELF-RECURSIVE `yield from <this-same-function>(...)`
can NEVER find itself there while its own body is still mid-compile.
Both of this doc's original two symptoms, and the third ("garbled
emission") symptom found later, all trace to this ONE chicken-and-egg
gap: the recursive call silently fell through to `_cpp_yield_from`'s
"yield from over a plain (non-generator) collection" fallback instead
of the real coroutine-delegation path, which (a) has no keyword-
argument forwarding at all (explaining symptom 1, the "too few
arguments" error) and (b) always contributes `char *` to `_generator_
yield_ctype`'s type-unification walk (explaining symptom 2, the
`int64_t`-vs-`char*` yield-type mismatch — the ORIGINAL doc guessed
these were two independent gaps needing two independent fixes; they
were one gap with two visible symptoms).

**Fix** (`gimple_codegen.py`, three coordinated pieces):
1. `_generator_yield_ctype`: a `YieldFromExpr` whose callee is `fn.name`
   itself (the function currently having its OWN value-type inferred)
   contributes NO type opinion and is skipped — a self-recursive site's
   type is, by definition, whatever the function's OTHER (base-case)
   yield site(s) agree on; letting it fall to the char* default instead
   silently corrupted the whole function's inferred type even when a
   direct `yield <value>` elsewhere unambiguously wanted int64_t/
   double/_Bool.
2. `_gen_cpp_generator_unit` sets scoped self-context (`self._cpp_gen_
   self_name`/`_base`/`_params`, mirroring the existing `self._cpp_gen_
   self_struct` convention exactly — set right before body compile,
   cleared in `finally`) so `_cpp_yield_from` can recognize "this call
   is to the function currently being compiled" using PURELY LOCAL
   information (this function's own already-computed `base`/`param_
   ctypes`), with no dependency on the not-yet-populated shared dict.
3. `_cpp_yield_from` treats a self-recursive call as a known generator
   delegation (builds a `{'base', 'params'}` dict from the tracked
   self-context instead of looking it up in `self._generator_api`),
   getting the SAME real delegation-loop emission (guard/resume/value/
   destroy, keyword-argument forwarding via the existing `call.kwargs`
   handling) every other `yield from <known-generator>(...)` site
   already gets — no new lowering logic, just routing self-recursion
   into the existing one. A NEW wrinkle this surfaced: the delegation
   loop, emitted INSIDE `{base}_impl`'s own body, calls `{base}_start`/
   `_resume`/`_value`/`_destroy` — extern "C" functions that are only
   textually DEFINED further down in the same generated `.cpp` (after
   `{impl}`), so a self-recursive call needs FORWARD DECLARATIONS of
   those four functions emitted just before `{impl}` — added,
   conditioned on whether self-recursion was actually detected during
   this generator's own body-emission pass (a new `self._cpp_gen_self_
   recursed` flag, same set/clear-in-finally convention).

## Verification

Hand-verified via `python3 mojo.py build` on this doc's own minimal
repro (`iter_files`): went from the exact documented two-error failure
(`too few arguments to function 'iter_files_...'`, `invalid conversion
from 'int64_t' to 'char*'`) to a CLEAN build (exit 0). A second,
runtime-executed test (`countdown(n, *, step)`, self-recursive `yield
from` with a keyword-only arg) built AND ran, printing the correct
`5\n3\n1\n` — confirming actual runtime correctness, not just a clean
compile.

`Lib/test/test_exception_group.py`'s `leaf_generator` (this doc's
"Additional real occurrence", the third/most-severe "~150 garbled
declaration errors" symptom): confirmed FIXED specifically — the
`.ci` output now compiles cleanly with `gcc -fgimple -fsyntax-only`
(0 errors, previously ~150). `leaf_generator` still doesn't fully
compile end-to-end (separate, pre-existing, unrelated gaps in the same
body — method calls/attribute access on untyped params, a tuple
`yield` — now surfacing as ordinary localized g++ errors instead of a
cascading corruption; see `bugs/CODEGEN_generator_function_Lib_test_
test_exception_group.md` for detail), but the cascading-corruption
failure MODE itself is gone.

`Tools/c-analyzer/c_common/fsutil.py` (task #140,
`bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`):
**NOT resolved as a side effect**, contrary to this task's original
expectation — `iter_files` no longer hits the arg-forwarding bug, but
the file still fails to compile, now for a DIFFERENT, previously-MASKED
reason: a `lambda *a, **k: ...` expression assigned to a local inside
`iter_files`'s own body (line 285 of the real file), unrelated to
yield-from/recursion and out of this narrow generator-body codegen's
scope on its own merits. Documented honestly in that file's own doc
rather than falsely claiming resolution — see that doc for detail.

## Gate

All five gates in CLAUDE.md's quality-gate section passed: `test_gimple.
py` (247/247), `test_module_cache.py` (76/76), `make check-selfhost`
clean, from-scratch `libmojostdlib.dylib` rebuild (0 `skip <module>:`
lines), `compile_stdlib.py -j8` (664/664, 0 unexpected — unchanged
count). Also ran `test_gimple_generator_runner.py` (not part of the
required gate, but directly relevant): 32/34 passed; the 2 failures
(`generator_passed_as_argument` and one other) are PRE-EXISTING,
confirmed via `git stash` to fail identically on unmodified code before
this fix — not a regression, not investigated further (out of scope
for this task).

## Original diagnosis (unfixed-era notes, kept for history)

Real, reproducing bug in `gimple_codegen.py`'s C++20-coroutine
generator codegen path (`compile_to_gimple_with_cpp` /
`module_may_have_supported_generator`) — not attempted at the time, as
it looked like a substantial addition to an already-complex code path,
not a small patch. (In the event, the real root cause was narrower and
more precisely fixable than this original assessment expected — see
above.)

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
