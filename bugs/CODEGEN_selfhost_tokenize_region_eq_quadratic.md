# CODEGEN: the self-hosted tokenizer is quadratic — `mojo_cstr_region_eq` rescans from byte 0 on every call

## Status (2026-10-01 — PARTIAL: the runtime half is 14x faster and the
## tokenizer's own quote loop is now O(1); the tokenizer is STILL quadratic
## through `s[j]`, for the reason recorded under "Why the scan cannot be made
## start-relative" below)

**Landed in this branch:**

1. **`runtime/fire_runtime.c` — both O(stop) scans are `memchr` now.**
   `mojo_cstr_region_eq` and `mojo_cstr_slice` each computed "how far does `s`
   reach" with a byte-at-a-time `while (len < stop && s[len]) len++;`. That
   value is *by definition* the offset of the first NUL in `s[0..stop)`, or
   `stop` — which is exactly `memchr(s, '\0', stop)`. Same value, vectorised.
   Measured on this doc's own scanning shape (a `src[j:j+3] != quote3` loop
   over N docstrings), 117KB/235KB/471KB: **2.14s -> 0.15s, 7.97s -> 0.54s,
   34.0s -> 2.05s**, i.e. a flat **14x**, with a per-position equality check
   against the old loop confirming the two agree at every offset. Still
   quadratic — see below for why it cannot be otherwise.

2. **`fire_compiler.py::replace_multiline_strings` — the quote loop's
   `src[i:i + 3] == quote3` is now two character compares.** `c` is `src[i]`
   (read a few lines above), so the slice compare was `src[i+1] == c and
   src[i+2] == c` with a short-slice guard, and it is spelled that way now.
   That loop runs **once per quote character in the file**, and each call
   cost O(i), so its total was the sum of every quote's offset: **1.0e9 byte
   reads** self-hosted on this file's own 350KB source. It is now O(1) per
   position, so that term is **zero**. Verified exhaustively equivalent to the
   slice compare over all 1970 `(src, i, c)` cases with `|src| <= 4`, and
   `py_tokenize` is byte-identical (kind, value, line, col) on 16 files of
   the self-host closure including `fire_compiler.py`, `myinterpreter.py`,
   `gimple_codegen.py`, `module_loader.py` and `module_gen.py`.

**What is still open, and it is the larger term.** The same O(stop) scan
backs `mojo_cstr_slice`, and **`s[j]` on a plain `str` lowers to
`mojo_cstr_slice(s, j, j+1)`** (`emit_calls.py::_lower_subscript`'s
`_actual_types == 'char *'` arm). `_scan_string_end` walks a literal body one
character at a time with `c = src[j]`, so the tokenizer's remaining cost is
`sum over j of O(j)` = **6.2e10 byte reads** on `fire_compiler.py`'s 350KB —
60x more than the quote loop that was just removed, and still quadratic after
the 14x. (A `for c in s` loop is fine: `_gen_for_cstr` calls `mojo_strlen`
once and then indexes by pointer arithmetic.)

### Why the scan cannot be made start-relative

The doc's "option 1" proposes scanning from `start` instead
(`while (start + len < stop && s[start + len]) len++;`). **That is not
sound**, and it is worth recording why rather than re-deriving it: the first
byte such a scan reads is `s[start]`, and nothing has established that `start`
is inside the string. `s[start:stop] == needle` has to answer for a `start`
past the end too — where the region is empty and the answer is `needle == ""`
— so the function must be able to ask "is `start` inside this string?" at
all, and for a bare `char *` that question *is* the scan from byte 0. Reading
`s[start]` to find out is exactly the out-of-bounds read the change would
introduce (a `s[1000000:1000003] == "abc"` on a 3-character string reads a
megabyte past the NUL).

The same wall stops the obvious fast path — "when `stop - start == strlen(needle)`
just `memcmp` the needle at `s + start`, which is O(needle_len)" — because
that `memcmp` reads `s[start]` too.

So the fix is not a better scan, it is **a length**. Either the string carries
one, or the slice/compare entry points take one the caller already has.
`emit_calls.py` has no length for a `char *` receiver today, which is why the
whole chain is stuck. `MojoStr` (`runtime/fire_runtime.h`) already has `->len`
and is the shape a fix would move plain `str` toward; a codegen-side
length-aware `mojo_cstr_slice_n(s, slen, start, stop)` /
`mojo_cstr_region_eq_n(s, slen, start, stop, needle)` emitted whenever the
receiver's length is statically known is the concrete next step, and is a
compiler change, not a runtime one.

**Regression test:** `test_gimple_runner.py::gimple_region_eq_scan_finds_terminator`
pins the answers for the cases whose value depends on the scan finding the
terminator (past the end, straddling it, empty needle against an empty
region). It deliberately asserts **answers, not timing** — the per-call cost is
still O(stop), and a ratio test here would be measuring libc's `memchr`, not
this compiler.

## Status (2026-09-29 — OPEN, measured; not fixed here)

Found while bisecting an unrelated blowup (see
`CODEGEN_container_eq_is_pointer_identity.md`) with the same stage2 binary.
It is a separate cause and it is the reason a self-hosted `--dump` of a
compiler source costs minutes instead of seconds.

`mojo_cstr_region_eq(s, start, stop, needle)` computes how far the string
reaches with

```c
    } else {
        len = 0;
        while (len < stop && s[len]) len++;
    }
```

— a scan from index 0, not from `start`. That is deliberate (the function's own
comment says the alternative is a `strlen` over the whole string), and for a
single call it is the cheaper of the two. The problem is the CALLER:
`fire_compiler.py`'s `py_tokenize` -> `replace_multiline_strings` searches for
a closing triple quote with

```python
    j = i + 3
    while j < n and src[j:j + 3] != quote3:
        j += 2 if src[j] == '\\' and j + 1 < n else 1
```

which the codegen special-cases (deliberately — see `mojo_cstr_region_eq`'s
comment) to `mojo_cstr_region_eq(src, j, j + 3, quote3)`. So the scan is called
once per character, and each call rescans everything before `j`: the whole
string- scanning loop is quadratic in the length of the region being scanned,
and the tokenizer runs it over every string literal in the file.

## What was run, and what it showed

Reference, same file, same function:

```
$ python3 -c "import time, fire_compiler as FC; \
    src=open('myinterpreter.py').read(); t0=time.time(); \
    toks=FC.py_tokenize(src); print(time.time()-t0, len(toks))"
0.049 29547            # 260 KB, 29,547 tokens
```

Self-hosted (stage2 binary), same file:

```
$ python3 tools/memslot.py --gb 8 --label stage2-dump -- \
      .tmp/stage2-fire-binary --dump myinterpreter.py
memcap: BREACH  8.5 GB > 8.0 GB ceiling ...
```

with `sample` at 1m23s, 100% of the stack:

```
py_tokenize
  py_tokenize_replace_multiline_strings
    mojo_cstr_region_eq          2538 of 2559 samples
```

and `.tok`/`.ast` written at ~2m30s — i.e. more than half of the run, and
roughly 3000x the reference time for the same function, before a single
statement is compiled.

## Exact next step

Two options, both cheap:

1. **Runtime.** Give the comparison a start-relative length: for non-negative
   `start`/`stop` the caller only needs to know whether the region exists, so
   `len` can stop at `stop` after confirming the bytes — the real requirement is
   "does `s` reach `stop`", which for a scan from `start` is
   `while (start + len < stop && s[start + len]) len++;`. That makes each call
   O(3) instead of O(stop) and the whole loop linear, with no change at the
   call site.
2. **Call site.** Replace the scan with `src.find(quote3, j)`-shaped logic
   (`fire_compiler.py`'s own tokenizer already uses `src.find('\n', i)` a few
   lines above), which is linear and needs no runtime change.

Option 2 is smaller; option 1 fixes every current and future caller of
`mojo_cstr_region_eq` at once, and the same O(stop)-per-call shape is worth
auditing for in the other `mojo_cstr_slice` / `mojo_cstr_region_eq` call sites
the compiler emits.

A regression test: time `py_tokenize` on a synthetic file of N docstrings for
N and 2N and require the ratio to stay near 2. Measured on this file, the
current shape is far worse than quadratic-per-region — worth re-measuring
before fixing so the test's budget is set from data.