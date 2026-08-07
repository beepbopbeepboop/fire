# CODEGEN_generator_function: Lib/os.py

## Status (updated 2026-08-06)

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
