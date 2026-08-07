# CODEGEN_generator_function: Lib/test/libregrtest/runtests.py

## Status (updated 2026-08-07 — bullet 2 (`yield from self.<MojoList* field>`) FIXED)

Re-verified against current master, then fixed bullet 2 from the
2026-08-06 note below (`_cpp_yield_from`, gimple_codegen.py:24122's
"yield from <plain collection expr>" branch, ~line 24203): `coll_expr =
self._cpp_expr(call)` for `yield from self.tests` emits the raw
`self->tests` field access uncast. `_cpp_expr`'s `MemberExpr` case
(gimple_codegen.py:22230) only special-cases `self.<field>` for the 4
known scalar ctypes (int64_t/double/_Bool/char *); any other field type
(here, a `MojoList *`-typed field, boxed as a raw `int64_t` at the C++
struct level per this codegen's own struct-field-boxing convention)
falls to its generic "Unknown field: emit as self->member" case with NO
cast at all. `auto {result_var} = self->tests;` then infers
`result_var` as `long long int` (the struct field's raw boxed type),
not `MojoList *` — hence g++'s "invalid conversion from 'long long int'
to 'MojoList*'" at both the `mojo_list_len`/`mojo_list_get_str` calls
that immediately follow.

**Fixed**: added an explicit `(MojoList *)(...)` cast around `coll_expr`
in that branch's `auto {result_var} = ...;` line. Safe for every shape
this branch reaches (its own preceding comment documents the branch's
contract as "the value IS a plain collection" — i.e. always semantically
a `MojoList *` regardless of whether its current C++ TYPE reflects
that); a cast applied to an expression that's already correctly typed
`MojoList *` is a no-op, so this can't regress any other currently-
working `yield from <expr>` shape.

**Verified fixed**: both isolated (`do_imports=False`) and the full
`python3 mojo.py build .../runtests.py` re-run now show ZERO
`MojoList*`-conversion errors — `runtests_gen.cpp:217`/`:218`'s errors
are gone from both. `runtests.py` still fails to build overall — bullet
1 (module/class-name-not-threaded-into-generator-scope, `sys.platform`/
`JsonFileType` inside `JsonFile.inherit_subprocess`) is UNCHANGED, still
reproduces identically, and was NOT attempted (matches the already-
documented, broader dyld.py-cluster "outer-scope name not threaded into
generator body" gap — not narrow/single-instance, out of scope for this
pass per the same reasoning the 2026-08-06 note already gives).

### Gate verification

See the shared end-of-session gate run covering every fix made in this
session (test_gimple.py/test_module_cache.py/check-selfhost/stdlib
dylib rebuild/compile_stdlib.py -j8, all passing/664-664/0-skip).

## Status (updated 2026-08-06, bullet 2 below now FIXED above; bullet 1 still accurate/unfixed)

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
