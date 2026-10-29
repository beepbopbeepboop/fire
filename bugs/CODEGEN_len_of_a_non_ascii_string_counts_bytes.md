# CODEGEN: `len(s)` on a non-ASCII string counts BYTES, where the other engines count CODE POINTS

## Status (2026-10-28): len(s) now counts code points for char* and MojoStr* via mojo_str_codepoint_len. The four-line JIT probe now matches CPython. Indexing/slicing/find still read char* as BYTES per original doc, so a `while i < len(s): s[i]` loop over non-ASCII text still stops short. Full fix requires either an encoding-aware indexing layer or the "real string value type" representation (see bugs/FORMAL_string_value_model.md).

## Status (2026-10-21): the len-only fix (f79e8b2f) was REVERTED, and why

f79e8b2f routed every compiled `len()` of a string through `mojo_str_codepoint_len` while `s[i]`, slicing, `find` and every other index still read the `char *` as BYTES — the commit said so itself ("the s[i]/find/ slicing half ... is left to the larger representation change"). That half-model is not a smaller version of the right answer, it is a new and worse bug class: **every `while i < len(s): ... s[i]` / `s[a:len(s)]` / `range(len(s))` loop over non-ASCII text now stops short**, because the bound is in code points and the index is in bytes. Before the fix such a loop visited every byte (a wrong count for `print(len(s))`, but the string was processed whole); after it, the tail of the text is silently dropped.

Measured on the self-hosted compiler, which is exactly that kind of program (its tokenizer is `n = len(src)` + `src[pos]`, and its own sources contain em-dashes): with f79e8b2f merged, the stage2 binary's `--dump` diverged from the Python reference on 13 artifacts (`.tok` of `fire.py`, `fire_compiler.py`, `myinterpreter.py`, `module_loader.py`, `bootstrap-validate.mojo` …), e.g. `f"  [{n} declaration(s) ADMITTED a sorry — the file typechecks, "` tokenized as `f [ { n } declaration ( s ) ...` and `generated_dispatch.py` failing with `unterminated string literal`. Reverted, the same comparison is back to the pre-merge state. So the doc is reopened, with the measured constraint added:

**len and indexing must change TOGETHER.** A fix has to make `s[i]`, slices, `find`/`index`, `enumerate`/`for c in s` and `len` agree on one unit. Code-point indexing over a bare UTF-8 `char *` is O(i) per access, so a naive version turns every tokenizer-shaped loop quadratic (the self-hosted compiler scans 2+ MB sources); the real fix needs either a string value that carries its length and ASCII-ness (the "real string value type" option above), or an ASCII fast path whose answer is cached soundly. Whichever lands, `make bootstrap` (stage1 vs stage2 `.tok` on the compiler's own non-ASCII sources) is the regression test for the loop half, and the four-line probe above is the test for the `len` half.

**Area:** CODEGEN (`mojo/backend_gimple` + `runtime/fire_runtime.c`). **Status: OPEN, measured 2026-10-07, PRE-EXISTING on `master`.** Found while fixing the front-end escape decoder (the `\uXXXX`/`\UXXXXXXXX`/`\N{…}`/octal class, whose own doc is deleted with its fix). With that decoder fixed, all four escapes now DECODE on the compiled path; what is left is the length this engine reports for the resulting text.

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

CPython makes each of them 1. The interpreter is a Python `str` and folds to code points; the two formal backends fold a literal's `len()` from its decoded text (`formal/model.py`'s TEXT ENCODING block). The compiled path's `len` is `strlen` over a `char *`, so it answers the UTF-8 BYTE count: 2, 4, 2, 2.

## Why it is a separate defect from the escape decoder

Before the decoder fix the same four rows answered 6, 10, 35, 3 — the escape was never decoded, so the count was of the SOURCE TEXT. That is fixed; the `len("é")` row (spelled as the character, no escape) answered 2 both before and after, which is what makes this a string-MODEL question rather than an escape one: a `char *` has no code-point count to report.

## The exact next step

This belongs with the compiled path's string model. Two candidate shapes, and the choice is the model's owner's:

* keep `char *` and give `len` an encoding-aware path (walk the bytes counting UTF-8 lead bytes) — cheap for `len`, but `s[i]`, `find`, slicing and `printf` width all have the same question and would each need the same layer; or
* give the compiled path a real string value type (the direction the formal backends took), which is the larger change and the one that answers all of them at once.

`bugs/FORMAL_string_value_model.md` is where the representation is argued; the compiled path's row belongs beside it. The cheapest measurement is the four-line probe above through `fire.py --jit` vs `python3`.