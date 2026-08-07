# CODEGEN_generator_function: Lib/test/libregrtest/runtests.py

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) — SAME symptom family as 2026-07-30, now precisely
classified. This file reaches the real coroutine `.cpp` compile stage
(`runtests_gen.cpp`) cleanly:

```
runtests_gen.cpp:142:11: error: 'sys' was not declared in this scope
runtests_gen.cpp:142:59: error: 'JsonFileType' was not declared in this scope; did you mean 'JsonFile'?
runtests_gen.cpp:217:53: error: invalid conversion from 'long long int' to 'MojoList*' [-fpermissive]
runtests_gen.cpp:218:44: error: invalid conversion from 'long long int' to 'MojoList*' [-fpermissive]
```

**Classification: already-known dyld.py-cluster gaps, two concrete
instances:**
1. **Module attribute access not threaded into generator scope**
   (`bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s bullet 4) —
   `inherit_subprocess`'s `if sys.platform == 'win32' and self.file_type
   == JsonFileType.WINDOWS_HANDLE:` references both the `sys` MODULE and
   `JsonFileType` (a locally-defined enum class) — neither is in scope
   inside the generated coroutine body. Slightly broader than the
   original dyld.py finding (module-only): here a top-level CLASS name
   is also unresolved, suggesting the gap is really "only params/self/
   locals are threaded into generator-body scope, not ANY outer-scope
   name (module or class)".
2. **`yield from` over a `MojoList*`-typed field/local doesn't get
   correct list-iteration lowering** (variant of dyld.py's bullet 3,
   "`for x in <MojoList*>:` missing begin()/end()") —
   `iter_tests`'s `yield from self.tests` (a plain field, not a nested
   generator call) hits "invalid conversion from 'long long int' to
   'MojoList*'" at its delegation-loop's element extraction, consistent
   with the same missing-native-C++-iteration-support root cause, here
   triggered by `yield from <container>` instead of a `for` loop.

Not fixed here — both are established, already-documented gaps in the
generator-codegen path; no new fix attempted.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/runtests.py
