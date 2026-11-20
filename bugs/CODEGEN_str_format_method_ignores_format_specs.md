# CODEGEN: `"{:.2f}".format(x)` ignores the format spec

f-string specs are implemented (`{x:.2f}`, `{x:^6}`, `{x:04d}`, `{x:#x}`, `{x:,}`, nested `{x:>{w}}`, `{x=}`):
the lowering calls the runtime's `mojo_fmt_int` / `mojo_fmt_float` / `mojo_fmt_str` (a complete
implementation of Python's format-spec mini-language, `runtime/fire_runtime.c`). `str.format` does
not use them: it goes to `mojo_str_format_words` (`_lower_str_format_call` in
`mojo/backend_gimple/emit_methods.py`) which drops precision, zero padding and grouping.

## Repro (`tools/pydiff_corpus/min/fs_str_format.py`)

```python
print("{} {}".format(1, "a"))
print("{0} {1} {0}".format("x", "y"))
print("{name} {age}".format(name="bob", age=3))
print("{:>5} {:<5}|".format("a", "b"))
print("{:.2f}".format(3.14159))
print("{:04d}".format(7))
print("{:,}".format(1234567))
print("{!r}".format("s"))
```

Differences (CPython vs compiled): `{:.2f}` prints `3.14159`; `{:04d}` prints `   7`; `{:,}` prints `1234567`.

## Next step

Make `mojo_str_format_words` call the same spec engine for each field that has a spec: it already
has the field's word, so dispatch on the kind it knows (int, float, str) to `mojo_fmt_int` /
`mojo_fmt_float` / `mojo_fmt_str`. Then `python3 tools/pydiff.py` on the repro prints `OK`; add it
to `tools/pydiff_ok.txt` and delete this doc.
