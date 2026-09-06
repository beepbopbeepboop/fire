# CODEGEN: `bytes` value type in the compiled path (multi-stage feature)

## Problem

The compiled path (`mojo_compiler.py` parser -> `gimple_gen_*.py` -> C/GIMPLE,
runtime in `runtime/`) has **zero** support for `bytes`. `b'...'` literals,
`bytes(...)`, `bytearray(...)`, `memoryview(...)` all refuse or misbehave.
Grep confirms: only refusal-message strings mention `bytes`, no implementation.

This blocks a large set of `COMPILE_FAIL_*` docs: zipfile, pickle-family, io,
hashlib, subprocess, struct, base64, `Tools/*`, umarshal, gencodec, and more.

## Representation

`MojoBytes` — a heap value mirroring `MojoStr` / `MojoList`:

```c
typedef struct {
    uint8_t *data;   /* NOT NUL-terminated-significant; may contain embedded 0 */
    int64_t  len;
} MojoBytes;
```

Passed as `MojoBytes *` across the C boundary (like `MojoStr *`, `MojoList *`).
`_TYPE_MAP['bytes'] = 'MojoBytes *'`. Runtime ops are `mojo_bytes_*`, declared
in `runtime/mojo_runtime.h`, implemented in `runtime/mojo_runtime.c`, and their
return types registered in BOTH runtime-signature maps
(`gimple_ctypes.py` `_RUNTIME_RET` near line 313 and the parallel copy in
`gimple_codegen.py` near line 190 — these are parallel-maintained today).

### `bytes` vs `str` — must NOT be conflated
- `b[i]` returns an **int** 0-255, never a 1-char str.
- No implicit decode/encode. `bytes` never flows into a `char *` slot and
  `str` never flows into a `MojoBytes *` slot without an explicit
  `bytes(s, enc)` / `b.decode(enc)`.
- Equality is bytewise; `b'a' == 'a'` is `False` (different C types — codegen
  keeps them distinct, so this simply doesn't typecheck to `mojo_str_eq`).
- Truthiness is `len != 0` (same rule as str/list, different helper).

## Staged scope

### Stage 1 (this pass)
- `b'...'` / `b"..."` literals with `\xNN`, `\n`, `\t`, `\r`, `\\`, `\'`, `\"`,
  `\0` escapes -> a `MojoBytes *` value (built at the literal site via
  `mojo_bytes_new_lit(const char *data, int64_t len)`; the data is a
  byte-for-byte octal-escaped C string constant in the string pool, so
  embedded NUL and high bytes are exact and can't run on into following
  hex/octal digits).
- `bytes()` (empty), `bytes(<int n>)` (n zero bytes), `bytes(<list of ints>)`,
  `bytes(<str>, 'utf-8'|'ascii')`.
- `len(b)`, `b[i]` (-> int 0-255, negative index ok), `b == b2`, `b != b2`,
  `bool(b)` / truthiness in `if`/`while`/`and`/`or`/`not`.
- `bytes` through function params annotated `: bytes` and through a return
  type annotated `-> bytes`; unannotated param inferred `bytes` from a
  `b'...'` default value.

### Stage 2 (later)
- `b[a:b]` slice -> `MojoBytes`; `for x in b` (yields int); `bytes(bytearray)`;
  `.decode()`, `.hex()`, `.startswith`/`.endswith`, `.find`, `.split`,
  `.replace`, `.strip`, `+` concat, `b'%d' % x`.
- Unannotated param inferred `bytes` from body usage (indexing feeding an int
  context, passed to a `bytes` param, etc.).

### Stage 3 (later)
- `bytearray` (mutable: `ba[i] = v`, `.append`, `.extend`, slice-assign).
- `memoryview` ({ptr,len,itemsize} non-copying view).

## Study notes — `MojoStr` as the analogue

- runtime struct: `runtime/mojo_runtime.c` ~line 792; header ~line 224.
- literal lowering: `gimple_gen_exprs.py` `_lower_StringLiteral` (~line 149);
  prefix/quote handling `_decode_str_literal_text` in `gimple_gen_resolve.py`
  (~2538); string pool `_intern_string` (`gimple_gen_resolve.py` ~2633),
  emitted `gimple_module_gen.py` ~7663.
- parser strips the `b` prefix today in `_strip_string_prefix_and_quotes`
  (`mojo_compiler.py` ~3726) so byteness is lost. Stage 1 adds an
  `is_bytes: bool` field to `StringLiteral` (mojo_compiler.py ~162) set in
  `_parse_primary` (~3951) / `_merge_string_literals`, and stores the decoded
  bytes as a latin-1 `str` (one char per byte) in `.value`.
- indexing: `gimple_gen_calls.py` ~4337 (`mojo_str_char_at`).
- `str`-typed param handling / `_TYPE_MAP`: `gimple_ctypes.py` ~203.

## Status

**Stage 3: LANDED (2026-09-06).**

- runtime (`runtime/mojo_runtime.{h,c}`):
  - `mojo_bytes_copy` / `mojo_bytearray_copy` — real independent copies
    (`bytes(bytearray)` must not alias the mutable buffer).
  - `mojo_bytearray_{new,setitem,append,extend,pop,delitem,splice}` —
    mutation ops. No capacity field on `MojoBytes`, so size-changing ops
    `realloc` to exactly `len+1` (O(n) append, but keeps the struct
    layout and every codegen struct-field table untouched).
  - `MojoMemoryView` struct `{uint8_t *data; int64_t len; int64_t
    itemsize}` + `mojo_memoryview_{new,from_bytes,len,get,slice,tobytes,
    eq,hex,cast,repr}`. 1-D byte view (itemsize 1); `slice` returns a
    sub-view into the SAME buffer (no copy).
- `_TYPE_MAP`: `bytearray` -> `MojoBytes *` (shared repr), `memoryview`
  -> `MojoMemoryView *`. Return types registered in both signature maps.
- `bytearray(...)` / `memoryview(...)` constructors in
  `gimple_gen_calls.py` (`bytearray()`, `bytearray(int)`,
  `bytearray(bytes)`, `bytearray(list)`, `bytearray(str, enc)`,
  `bytearray(memoryview)`; `memoryview(bytes|bytearray|memoryview)`).
- `bytes(x)` now emits `mojo_bytes_copy` for a `MojoBytes *` arg (so
  `bytes(ba)` is a real copy) and `mojo_memoryview_tobytes` for a view.
- Mutation lowering: `ba[i] = v` (`_gen_stmt_AssignStmt` SubscriptExpr
  `MojoBytes *` branch), `ba[a:b] = <bytes|list>` (SliceExpr branch,
  unstepped), `del ba[i]` (`_gen_stmt_DelStmt`), `.append/.extend/.pop/
  .clear/.copy/.tobytes` in `_lower_bytes_method`. `ba += b'...'` goes
  through the generic `+` path (concat + rebind) — correct for `bytes`,
  and observationally correct for an UNALIASED `bytearray`; a shared
  bytearray alias will not see an in-place `+=` (documented limitation).
- memoryview read path: `mv[i]` -> int, `mv[a:b]` -> sub-view (no copy),
  `len(mv)`, `for x in mv` (`_gen_for_memoryview`), `mv == b'...'`
  (either operand order), `.tobytes()`, `.hex()`, `.cast('B')` (no-op),
  `.release()` / `with memoryview(...) as m:` (context-manager no-op —
  no refcount model), `bytes(mv)`, `str(mv)`/`repr(mv)` -> `<memory at
  0x...>`.
- `isinstance(x, bytearray)` / `isinstance(x, memoryview)` via
  `_SCALAR_TYPE_MATCH`. **bytes vs bytearray cannot be discriminated**
  in the compiled path — both are `MojoBytes *` and there is no type
  tag; `isinstance(x, bytes)` and `isinstance(x, bytearray)` both match
  any `MojoBytes *`. Adding a tag was judged not worth the
  struct-layout churn.
- Tests: `test_gimple.py` (+2 compile checks: `bytearray_construct_and_
  mutate`, `memoryview_ops`), `test_gimple_runner.py` (+2 runnable:
  `gimple_bytearray_mutation`, `gimple_memoryview`).

Deferred / not done in Stage 3:
- **`memoryview(...)` inside a compiled generator/coroutine body** — the
  C++ coroutine-body emitter (`gimple_cpp_core.py` ~line 3582) still
  refuses it as an "unresolved callee". This is the first blocker for
  `bugs/COMPILE_FAIL_zipfile___init__.md` (`_Extra.split`), which also
  has ≥3 further unrelated blockers (pwd=None unannotated param,
  genexp-held-in-local, FileHeader int32 under-widening) — not closed.
  The ordinary GIMPLE path's memoryview support is complete.
- stepped `ba[a:b:k] = ...` slice-assign (rare; falls through).

**Stage 2b: LANDED (2026-09-06).**

- `b'...' % args` -> `MojoBytes *`. `_lower_percent` (gimple_gen_exprs.py)
  gets a bytes branch BEFORE the str-literal branch (a bytes literal is
  also a `StringLiteral`): `_lower_bytes_percent_format` mirrors
  `_lower_percent_format` (compile-time split of the literal template
  into lit/spec parts, one RHS operand per spec, accumulate left-to-
  right) but the accumulator is bytes — literal chunks become
  `mojo_bytes_new_lit` byte-exact constants, `%s`/`%r` of a `MojoBytes`
  operand is spliced RAW (no decode, embedded-NUL safe), every other
  spec is rendered to ASCII via the shared `_format_percent_spec` then
  wrapped with the new `mojo_bytes_from_cstr`. Handles `%d %s %x %X %o
  %c %% %r` + width/precision/flags. A runtime variadic `mojo_bytes_mod`
  was considered and rejected: GIMPLE can't express the mixed
  `MojoBytes*`/`int64_t`/`double` vararg list, and compile-time
  splitting reuses the already-audited str spec parser. The str `%`
  path is untouched (still literal-LHS only, still `char *`).
- Body-usage param inference: an unannotated param used as `x.decode(...)`
  or `x.hex()` anywhere in the body is inferred `bytes`. `BYTES_ONLY_
  METHODS = {'decode', 'hex'}` in `_infer_param_types` — neither name is
  shared with any str/list/dict method the analysis keys on, so this is
  the only signal conservative enough to act on. Indexing / `in` / `+` /
  iteration are deliberately NOT bytes signals (identical to str/list).
  Wins over every other signal. New `is_bytes_method` slot threaded
  through the `analyze_param_usage` result tuple + its memo cache.
- Tests: `test_gimple.py` (+2), `test_gimple_runner.py` (+2).

Deferred from Stage 2b: none (both items done).

---

**Stage 2: LANDED.**

Landed in Stage 2:
- runtime (`runtime/mojo_runtime.{h,c}`): `mojo_bytes_concat`, `_repeat`,
  `_slice` (start/stop/step, negative step, `MOJO_SLICE_STOP_OMITTED`
  sentinel for omitted start), `_contains`, `_find`, `_count`,
  `_startswith`, `_endswith`, `_decode` (-> char*), `_hex` (-> char*),
  `_replace`, `_strip` (do_left/do_right flags + optional chars),
  `_upper`, `_lower`, `_split` (whitespace when sep omitted), `_rsplit`,
  `_splitlines`, `_join`; plus `mojo_repr_list_bytes` for
  `print(list-of-bytes)`.
- `_lower_bytes_method` in `gimple_gen_methods.py` (new, mirrors
  `_lower_str_method`), dispatched from `_lower_method_call` on
  `ot == 'MojoBytes *'` and `_sn == 'MojoBytes'`. `.decode`/`.hex` return
  `char *`; `.split`/`.rsplit`/`.splitlines` return `MojoList *` with
  `_elem_types = 'MojoBytes *'`; everything else returns `MojoBytes *`.
- `+` concat / `*` repeat (both operand orders) in `gimple_gen_exprs.py`
  `_lower_binary`.
- `in` / `not in` for `b'x' in b'xyz'` and `int in b'...'` via
  `mojo_bytes_contains` in `_lower_in_dispatch`.
- `b[a:b]` / `b[a:]` / `b[:b]` / `b[::k]` (incl. `b[::-1]`) in
  `_lower_slice` (`MojoBytes *` branch, reuses `_lower_slice_bounds`).
- `for x in b:` -> x is int 0-255 (`_gen_for_bytes` in
  `gimple_gen_loops.py`, dispatched from `_gen_for_iter`).
- `isinstance(x, bytes)` / `isinstance(x, bytearray)` via the
  `_SCALAR_TYPE_MATCH` table in `_isinstance_one_type`.
- Tests: `test_gimple.py` (+4 compile checks), `test_gimple_runner.py`
  (+5 runnable value-asserting cases).

Deferred to **Stage 2b** (not yet done):
- `b'%d...' % x` / `b'%s' % b'...'` formatting -> bytes. The str `%`
  path (`_lower_percent` / `_lower_percent_format`) is literal-LHS only
  and produces `char *`; a bytes analogue needs a `mojo_bytes_mod`
  runtime primitive (raw-byte %s insertion, embedded NUL safe).
- Unannotated param inferred `bytes` from *body usage* alone
  (`x.decode()` / `x[a:b]` used as bytes / `x + b'...'` / `for _ in x`).
  `_infer_param_types` is heavily bug-tuned (many documented past
  regressions); a bytes signal needs care not to steal `str`/`list`
  inference. Annotation (`: bytes`) and `b'...'` default both already work.
- `bytes(bytearray)` — bytearray is Stage 3; skipped cleanly.

### Stage 3 (still remaining, unchanged)
- `bytearray` (mutable), `memoryview`.

---

**Stage 1: LANDED.**

Landed:
- `runtime/mojo_runtime.{h,c}`: `MojoBytes` struct + `mojo_bytes_new_lit`,
  `_empty`, `_zeros`, `_from_list`, `_from_str`, `_len`, `_get`, `_eq`,
  `_truthy`, `_repr`, `_print`.
- Parser (`mojo_compiler.py`): `StringLiteral.is_bytes` field;
  `_raw_string_is_bytes` / `_decode_bytes_literal` (escape decode ->
  latin-1, one char per byte); wired into `_parse_primary` and
  `_merge_string_literals` (adjacent-literal concat).
- `_TYPE_MAP['bytes'] = 'MojoBytes *'`; `mojo_bytes_*` return types in both
  runtime-signature maps.
- `_lower_StringLiteral`: bytes branch -> fixed 3-digit octal-escaped C
  constant + `mojo_bytes_new_lit(_slit_N, len)`.
- `bytes(...)` constructor in `gimple_gen_calls.py` (0-arg / int / list /
  str+enc / bytes-copy).
- `len(b)` (`_LEN_FNS` + `_CONTAINER_LEN_FN` -> truthiness & `bool(b)`),
  `b[i]` -> `int64_t` via `mojo_bytes_get`, `b == b2` / `!=` via
  `mojo_bytes_eq`, `print(b)` / `str(b)` / `repr(b)` / f-string -> `b'...'`
  repr text (no decode).
- Param typing: annotated `: bytes` / `-> bytes` via `_TYPE_MAP`;
  unannotated param inferred `MojoBytes *` from a `b'...'` default
  (`gimple_gen_funcs.py` default-evidence hook + `_quick_type`).
- Tests: `test_gimple.py` (5 compile checks) + `test_gimple_runner.py`
  (5 runnable value-asserting cases).

Still missing in Stage 1 / deferred to Stage 2:
- Unannotated param inferred `bytes` from *body usage* alone (only
  default-value inference is wired; annotation always works).
- `String(bytes)` / `bytes`-in-`Str(...)` still emit the generic address
  path (Python has no such implicit conversion either — needs explicit
  `.decode()` in Stage 2).
- Everything else already listed under Stage 2 / Stage 3 above.
