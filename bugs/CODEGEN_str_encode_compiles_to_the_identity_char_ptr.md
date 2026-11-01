# CODEGEN: `str.encode(...)` on a `char *` compiled to the identity (a TODO stub), so the result was a str, not bytes

**State: PARTIALLY FIXED 2026-10-31.** The type and value of `str.encode()` for
the default and UTF-8 encodings are now right. What remains is the
non-UTF-8 codec argument (below).

    s = "abc"
    b = s.encode()
    print(b)                # CPython: b'abc'      compiled (before): abc
    print(len(b))           # CPython: 3           compiled (before): 3
    t = "héllo"
    print(len(t.encode()))  # CPython: 6           compiled (before): 5

## Status 2026-10-31 — what landed

- `mojo/backend_gimple/emit_methods.py` (`_lower_str_method`): `encode` on a
  `char *` now returns a real `MojoBytes *` via `mojo_bytes_from_str`, passing
  the encoding (positional or `encoding=` keyword; default `"utf-8"`) through.
  It was an identity stub typed `char *`.
- `mojo/middle/resolve_shared.py` (`_quick_type`): `encode` is `MojoBytes *` in
  both the plain-receiver pre-pass and the chained-receiver branch. Previously it
  was in the `char *` row.
- `mojo/backend_gimple/module_gen.py`: a module-global `X = s.encode()` is
  declared `MojoBytes *` (was `char *`, which made the global print as a str).
- Regression: `gimple_str_encode_is_bytes` in `test_gimple_runner.py`, a
  CPython-oracle comparison covering a local, a module global, a function
  return, a chained `.encode().decode()`, and `str(7).encode() + b'!'`. It
  fails on the pre-fix tree (`abc` / `h\xc3\xa9llo 5`) and passes with the fix.

## Status 2026-10-31 (second round) — codec table landed

- `runtime/fire_runtime.c`: `mojo_codec_lookup` resolves the codec name the way
  CPython's `codecs.lookup` normalises it (lowercase, `-`/space to `_`) against
  CPython's aliases for utf-8, ascii and latin-1; anything else raises
  `LookupError: unknown encoding: <name>`. `mojo_bytes_from_str` encodes ascii
  and latin-1, and an unencodable character raises `UnicodeEncodeError` with
  CPython's message (`'ascii' codec can't encode character '\xe9' in position
  1: ordinal not in range(128)`). `mojo_bytes_decode` refuses ascii bytes
  >= 0x80 with `UnicodeDecodeError`, and maps latin-1 bytes to their code points.
- New typed raisers `mojo_raise_unicode_encode_error`,
  `mojo_raise_unicode_decode_error`, `mojo_raise_lookup_error` (same mechanism
  as `mojo_raise_index_error`); tags are `crc32` of the class name.
- `mojo/middle/types.py` (`_BUILTIN_EXC_PARENT`): `UnicodeError` is a
  `ValueError`, and `UnicodeEncodeError`/`UnicodeDecodeError` are
  `UnicodeError`s, so `except ValueError:` catches an unencodable character.
- `mojo/backend_gimple/emit_methods.py` (`bytes` `decode`): the codec was read
  only from the `encoding=` keyword; a positional `b.decode("ascii")` silently
  used utf-8. Now the positional and keyword forms both reach the runtime, the
  same shape as `str.encode`.
- Regression: `gimple_str_encode_codecs` in `test_gimple_runner.py` (a
  CPython-oracle comparison). It failed before the fix (`c3 a9` for latin-1,
  no refusal for ascii, `ascii` decode returned the raw byte) and passes now.

## What remains

- **`errors=` is not forwarded.** `str.encode` and `bytes.decode` run every
  codec with strict handling. `errors='replace'`/`'ignore'`/`'strict'` now
  matter for ascii and latin-1 (`"é".encode("ascii", "replace")` must give
  `b'?'`); the callers would need to pass the error policy through
  `mojo_bytes_from_str` / `mojo_bytes_decode`, with the signature change in
  `fire_runtime.h`. Next step: add an `errors` argument to both helpers,
  thread it from `_lower_str_method` / `_lower_bytes_method` (and the two
  `bytes(...)`/`bytearray(...)` call sites in `emit_calls.py`, which pass
  utf-8 today), and pin `replace` and `ignore` with a `test_gimple_matches_cpython`
  case.
- **utf-8 decode is not validated.** `mojo_bytes_decode` with the utf-8 codec
  still copies malformed bytes through; CPython raises `UnicodeDecodeError`
  ("invalid start byte" / "invalid continuation byte" / "unexpected end of
  data"). Next step: a UTF-8 validator in the decode path that reports those
  three reasons with CPython's byte/position wording.

## Related, not this bug

`s = 'abc'; s.decode()` is not valid Python 3 (`str` has no `decode`); the
`char *` `decode` stub is left as it was.
