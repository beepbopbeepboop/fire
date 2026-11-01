# CODEGEN: `str.encode` and `bytes.decode` remaining gaps

**State: NOT FIXED.** Remaining work split from `CODEGEN_str_encode_compiles_to_the_identity_char_ptr.md` after the identity-stub and codec-name fixes landed.

What remains:

- **`errors=` is not forwarded.** `str.encode` and `bytes.decode` run every codec with strict handling. `errors='replace'`/`'ignore'`/`'strict'` now matter for ascii and latin-1 (`"é".encode("ascii", "replace")` must give `b'?'`); the callers would need to pass the error policy through `mojo_bytes_from_str` / `mojo_bytes_decode`, with the signature change in `fire_runtime.h`. Next step: add an `errors` argument to both helpers, thread it from `_lower_str_method` / `_lower_bytes_method` (and the two `bytes(...)`/`bytearray(...)` call sites in `emit_calls.py`, which pass utf-8 today), and pin `replace` and `ignore` with a `test_gimple_matches_cpython` case.
- **utf-8 decode is not validated.** `mojo_bytes_decode` with the utf-8 codec still copies malformed bytes through; CPython raises `UnicodeDecodeError` ("invalid start byte" / "invalid continuation byte" / "unexpected end of data"). Next step: a UTF-8 validator in the decode path that reports those three reasons with CPython's byte/position wording.
