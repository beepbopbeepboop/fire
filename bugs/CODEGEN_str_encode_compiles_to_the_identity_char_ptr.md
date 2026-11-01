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

## What remains

- **The encoding argument is ignored by the runtime.** `mojo_bytes_from_str`
  (`runtime/fire_runtime.c`, `(void)encoding;`) produces UTF-8 for every codec
  name, so `"é".encode("latin-1")` gives `c3 a9` where CPython gives `e9`, and
  `"é".encode("ascii")` gives bytes where CPython raises `UnicodeEncodeError`.
  `bytes.decode(enc)` (`mojo_bytes_decode`) has the same gap. Next step: give
  both runtime helpers a real codec table (utf-8/ascii/latin-1 at minimum), with
  an unencodable character raising `UnicodeEncodeError` (the runtime has
  `mojo_raise_value_error`; a dedicated raise is needed for the exact class), and
  pin each codec with a `test_gimple_matches_cpython` case.
- **`errors=` is not forwarded.** A `str` is always valid UTF-8, so for the one
  codec the runtime implements `strict` and `replace` cannot differ. This becomes
  live once the codec table above exists.

## Related, not this bug

`s = 'abc'; s.decode()` is not valid Python 3 (`str` has no `decode`); the
`char *` `decode` stub is left as it was.
