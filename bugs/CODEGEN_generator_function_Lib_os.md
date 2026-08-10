# CODEGEN_generator_function: Lib/os.py

## Status (updated 2026-08-09 — RECLASSIFIED: real tuple-valued-yield refusal, now the blocking error)

Re-verified against current master (`c79a013`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/os.py`. The
build now fails IMMEDIATELY, on `os.py`'s OWN top-level module compile
(`gen_module`, before any transitive-closure/GCC-stage work is even
reached), with a hard Python-level `RuntimeError`:

```
Error building: cannot compile module: function(s) _fwalk, walk
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ...
```

`MOJO_DEBUG=1` confirms the precise refusal reason for both:

```
[gimple_codegen] generator 'walk' not eligible for C++ coroutine path,
  falling back to honest refusal: walk: every `yield` must carry a
  value, and all values must agree on one scalar type
  (int64_t/double/_Bool)
[gimple_codegen] generator '_fwalk' not eligible for C++ coroutine path,
  falling back to honest refusal: _fwalk: every `yield` must carry a
  value, and all values must agree on one scalar type
  (int64_t/double/_Bool)
```

Root cause, confirmed by reading the source: `walk()` (os.py:364-418)
has `yield top` (a scalar, line 364, the `topdown=False` post-order
case) AND `yield top, dirs, nondirs` (a real 3-element **tuple-valued
yield**, line 418, the `topdown=True` case) — two yield statements in
the same generator that don't even agree on arity, let alone type.
`_fwalk()` (os.py:465-551) similarly has `yield value` (line 501,
where `value` is itself a 4-tuple assigned earlier via
`stack.append((_fwalk_yield, (toppath, dirs, nondirs, topfd)))`) and
`yield toppath, dirs, nondirs, topfd` directly (line 551, a real
4-element tuple yield).

This is the well-known, already-tracked structural gap for this
generator-codegen family: the coroutine promise only supports a single
scalar `int64_t`/`double`/`_Bool`/`char *` yield type — see
`_infer_generator_yield_ctype`'s explicit `TupleExpr` handling at
`gimple_codegen.py:2699-2724`, which deliberately returns `None`
(refuse) rather than let a tuple yield sail through to broken C++
emission. **Classification: matches the tracked "tuple-valued yield"
structural generator-codegen gap** — out of scope for a narrow fix per
this task's guidance. Not attempted here.

This refusal happens strictly BEFORE the module-qualification fix
(`_gen_cpp_generator_unit`'s `_func_qualifier`-based symbol naming) and
the `relpath`-ambiguity issue documented below ever get exercised for
this file — `os.py`'s own top-level compile now aborts on its own two
generators before any transitive-closure linking is attempted, so
those two previously-documented issues are currently unreachable/moot
for `os.py` specifically (they may still be real for other files, not
re-verified here). The below status entries are kept for history but
no longer describe the current blocking error.

## Status (updated 2026-08-07)

**Classification bug FIXED** (`bugs/hard/CODEGEN_generator_function_
symbol_not_module_qualified.md`, task #146) — `_gen_cpp_generator_unit`'s
free-function base-name computation now module-qualifies via
`_func_qualifier` (the same SB-1 machinery ordinary free functions use).
Confirmed: `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/os.py`
no longer produces ANY `conflicting types for '_mojogen_walk_start'`
error — the specific collision this doc documents is gone.

**File STILL FAILS to build overall**, for a completely different,
unrelated reason: `RuntimeError: cannot compile module: 'relpath' is
ambiguous — this program transitively imports two different sibling
modules that both define a free function named 'relpath' ...` — an
ORDINARY (non-generator) function ambiguity, hit via `_func_qualifier`'s
own pre-existing `_AMBIGUOUS_FUNC_HOME` honest-refusal path (unrelated
machinery, not touched by the generator-symbol fix). Not investigated
further here — out of scope for the generator/coroutine codegen cluster
this file was originally classified under.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, but re-diagnosed from scratch against current master
(`2b0c4c5`) — the 2026-07-31 `_DeprecatedGenericAlias`/`_CallableType`/
`_PlaceholderType` errors no longer reproduce (fixed by unrelated later
work). `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/os.py`'s
whole-program transitive-closure compile now fails with hundreds of
errors from many different files; the ones that actually implicate
`os.py`'s OWN generator (`os.walk`) are:

```
/Users/mrs/net/Python-3.14.6/Lib/os.py:1553:23: error: conflicting types for '_mojogen_walk_start'; have 'MojoGenerator *(int64_t,  int64_t,  int64_t,  int64_t)' {aka 'MojoGenerator *(long long int,  long long int,  long long int,  long long int)'}
/Users/mrs/net/Python-3.14.6/Lib/threading.py:2160:23: note: previous declaration of '_mojogen_walk_start' with type 'MojoGenerator *(int64_t)' {aka 'MojoGenerator *(long long int)'}
```

(also hit, identically, via `Lib/subprocess.py`, `Lib/genericpath.py`,
`Lib/ntpath.py` — every module in the transitive closure that reaches
BOTH `os.py`'s own `walk` generator and an unrelated, differently-shaped
`walk` generator reachable through `Lib/threading.py`.)

**Classification: this is `bugs/hard/CODEGEN_generator_function_symbol_
not_module_qualified.md`** — `os.py`'s `walk(top, topdown=True,
onerror=None, followlinks=False)` (4 params) is a perfectly ordinary,
independently-compilable generator; it collides purely on the emitted C++
coroutine API's SYMBOL NAME (`_mojogen_walk_start`/`_resume`/`_value`/
`_destroy`) with a completely unrelated generator, also bare-named
`walk`, that some other stdlib module transitively pulls in from
`threading.py`. `_gen_cpp_generator_unit`'s free-function base-name
computation (`f"_mojogen_{_safe_name(fn.name)}"`) never got the SB-1-
style module-qualification treatment ordinary free functions received in
`bf96f55`/`13e6a5c` — see the hard-bug doc for the full root cause,
why the two same-named `walk`s are otherwise unrelated (different
arities, different bodies), and why a fix needs the same care as the
original SB-1 project (two rounds of real regressions there).

Older, likely stale note (session before this re-diagnosis; not
independently re-verified here): the `mkdir`/`rmdir`/`execv`/`execve`/
`fork` "implicit declaration" warnings-turned-errors visible deep in the
current transitive-closure build output appear to be UNRELATED libc-
declaration issues in `os.py`'s own non-generator code, not part of this
generator-codegen cluster; not investigated further as part of this
pass (out of scope — this task is specifically about the generator/
coroutine codegen gaps).

## Build error

```
error: '_DeprecatedGenericAlias' does not name a type
error: '_CallableType' does not name a type
error: '_PlaceholderType' does not name a type
```

## Fixed errors (this session)
- `fork` implicit-decl → fixed (`_NEEDS_SELF_EXTERN` + `_LIBC_SIGS`)
- `execv` incompatible-args → fixed (`_KNOWN_SIGS` arg-padding)
- `waitpid` arg-count → fixed (`_KNOWN_SIGS` arg-padding)
- `execve` conflicting-types → fixed (`_KNOWN_SIGS`)
- `sys` not declared → fixed (package import scan)

Source file: `/Users/mrs/net/Python-3.14.6/Lib/os.py`
