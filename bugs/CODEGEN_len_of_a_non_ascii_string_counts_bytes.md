# CODEGEN: `len(s)` on a non-ASCII string counts BYTES, where the other engines count CODE POINTS

**Area:** CODEGEN (`mojo/backend_gimple` + `runtime/fire_runtime.c`). **Status:
OPEN, measured 2026-10-07, PRE-EXISTING on `master`.** Found while fixing the
front-end escape decoder (the `\uXXXX`/`\UXXXXXXXX`/`\N{…}`/octal class, whose
own doc is deleted with its fix). With that decoder fixed, all four escapes now
DECODE on the compiled path; what is left is the length this engine reports for
the resulting text.

## What I ran

```
$ printf 'def main():\n    print(len("\\u00e9"))\n    print(len("\\U0001F600"))\n    print(len("\\N{LATIN SMALL LETTER E WITH ACUTE}"))\n    print(len("é"))\n' > .tmp/lenc.mojo
$ python3 fire.py --jit .tmp/lenc.mojo
2
4
2
2
$ python3 fire.py run .tmp/lenc.mojo      # interpreter
1
1
1
1
```

CPython makes each of them 1. The interpreter is a Python `str` and folds to
code points; the two formal backends fold a literal's `len()` from its decoded
text (`formal/model.py`'s TEXT ENCODING block). The compiled path's `len` is
`strlen` over a `char *`, so it answers the UTF-8 BYTE count: 2, 4, 2, 2.

## Why it is a separate defect from the escape decoder

Before the decoder fix the same four rows answered 6, 10, 35, 2 — the escape
was never decoded, so the count was of the SOURCE TEXT. That is fixed; the
`len("é")` row (spelled as the character, no escape) answered 2 both before and
after, which is what makes this a string-MODEL question rather than an escape
one: a `char *` has no code-point count to report.

## The exact next step

This belongs with the compiled path's string model. Two candidate shapes, and
the choice is the model's owner's:

* keep `char *` and give `len` an encoding-aware path (walk the bytes counting
  UTF-8 lead bytes) — cheap for `len`, but `s[i]`, `find`, slicing and `printf`
  width all have the same question and would each need the same layer; or
* give the compiled path a real string value type (the direction the formal
  backends took), which is the larger change and the one that answers all of
  them at once.

`bugs/FORMAL_string_value_model.md` is where the representation is argued; the
compiled path's row belongs beside it. The cheapest measurement is the four-line
probe above through `fire.py --jit` vs `python3`.
