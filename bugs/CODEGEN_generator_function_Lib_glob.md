# CODEGEN_generator_function: Lib/glob.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'os' was not declared` .cpp error no longer reproduces
(dyld.py's documented "module attribute access not threaded into
generator scope" gap — see `bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`
— appears fixed for glob.py's shape at least). `MOJO_DEBUG=1` shows NO
"not eligible" refusal for any of glob.py's own generators (`_iglob`,
`_glob1`/`_glob0`, `_glob2`, `_iterdir`, `_rlistdir`) — all pass the
eligibility pre-filter and reach real `.cpp` generation.

Current failure, still inside the generator-codegen cluster but a
DIFFERENT, narrower bug than the old one:

```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:175:7: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
```

**Root cause (read from `_glob2`'s source):**
```python
def _glob2(dirname, pattern, dir_fd, dironly, include_hidden=False):
    assert _isrecursive(pattern)
    if not dirname or _isdir(dirname, dir_fd):
        yield pattern[:0]                                    # char* (empty string slice)
    yield from _rlistdir(dirname, dir_fd, dironly,            # forward reference!
                         include_hidden=include_hidden)
```
`_glob2` has TWO yield sites of apparently different shapes: a direct
`yield pattern[:0]` (a string slice, `char *`) and a `yield from
_rlistdir(...)` — but `_rlistdir` is DEFINED LATER in the file (line
218, vs. `_glob2` at line 170). This is the same forward-reference
caveat already surfaced in this session's `MOJO_DEBUG` output for a
different function in this same file (`tokenize`-style note: *"the
delegated-to generator must be defined earlier"*) — when the overall
generator's yielded-VALUE type is computed (`_generator_yield_ctype`),
the `yield from` to a not-yet-registered generator apparently doesn't
contribute its real element type to the join, so the combined value type
collapses to the `int64_t` default instead of joining to `char *` (the
correct common type, since `_rlistdir` itself ultimately yields strings
too). The result: the coroutine promise's `yield_value` is generated
expecting `int64_t`, but the `yield pattern[:0]` call site still
produces a real `char *` — hence "assignment to int64_t from char*".

This is a variant of the already-documented "generator yielded-value
type inference" gap (`bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s
bullet 1, and the untyped-generator-param cousin in
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`'s sibling
docs) — specifically the FORWARD-REFERENCE angle of it: a generator with
a `yield from` to a same-file sibling generator defined LATER, combined
with an earlier plain `yield` of a different concrete type, produces a
wrong combined promise type. Not folded into a new hard-bug doc here
(only one clean instance traced end-to-end so far) — flagged for whoever
next hits this shape to fold into a broader "generator yield-value type
inference" hard doc once 2-3 more instances are confirmed.

The two other current errors (`translate_584a43` arity mismatch,
`struct _subprocess_toplev` undefined) were not investigated — they look
unrelated to the generator-codegen cluster (arity/import-resolution
issues in non-generator code) and are left for a separate pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/glob.py
