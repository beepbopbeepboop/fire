# CODEGEN: the self-hosted tokenizer is quadratic — `mojo_cstr_region_eq` rescans from byte 0 on every call

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