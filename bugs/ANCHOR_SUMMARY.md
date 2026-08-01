## Commits (this session)
1. `da1a05d` — Hoist `.cpp` coroutine locals to function scope (mimetypes `ctype` fix)
2. `daedf1f` — Fix `__init__.mojo` package imports: scan sibling files for exported functions
3. `872a113` — Skip C stdlib names in `load_module`; add `fork`/`waitpid` to `_NEEDS_SELF_EXTERN`
4. `6076f23` — Add `execv`/`waitpid` to `_KNOWN_SIGS` for arg-padding; `execv` to `_NEEDS_SELF_EXTERN`
5. `d0b2e7a` — Add `execve` to `_KNOWN_SIGS` to prevent auto-stub type conflict
6. `f1fe593` — Catch `_mojo_type_to_c` errors in `load_module` scan (`tokenize` import broken)

## Bugs removed
- `CODEGEN_generator_function_Lib_mimetypes.md` — mimetypes `.cpp` now compiles clean (rc=0)

## Bugs updated
- `CODEGEN_generator_function_Lib_os.md` — `fork`/`execv`/`waitpid`/`execve`/`sys` fixed; remaining: `_DeprecatedGenericAlias`/`_CallableType`/`_PlaceholderType` (opaque-class globals struct)
- `CODEGEN_generator_function_Lib_typing.md` — `Unpack` fixed; remaining: same `_DeprecatedGenericAlias` etc.

## Key Details
- `load_module` had silent failure: `_mojo_type_to_c` throws `cannot import name 'tokenize'` (broken import), caught by outer `try/except` → entire scan returns `{}`. Fixed with `try/except` fallback to `'int64_t'`.
- `_C_STDLIB_SKIP` prevents `nan`/`trunc`/etc. conflicts with prelude headers.
- `_KNOWN_SIGS` padding: `waitpid` 2→3 args, `execv`/`execve` correct `char *` types.

## Gates
- `test_selfhost.py`: PASS
- `test_gimple.py`: 247/0
- dylib: 1 skip = baseline (`memory/alloc` pre-existing naming collision)
