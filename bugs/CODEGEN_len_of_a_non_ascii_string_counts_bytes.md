# CODEGEN: `len(s)` on a non-ASCII string counts BYTES, where the other engines count CODE POINTS

## Status (2026-10-29): planning round — measured state and the implementation guide for the index half

Re-measured on `work/bug-codegen-len-of-a-non-ascii-string-co-5901` (HEAD includes c99c057fb):

- The four-line probe, `python3 fire.py --jit`: `1 1 1 1` (matches CPython). `test_nonascii_len_regression.py` PASSES (`PASS nonascii_len_matches_cpython`), run via `tools/memslot.py --gb 8`. That is the `len` half, and it is done.
- The index half is still open. Probe `.tmp/idx.mojo` (`s = "aéb"`):

  ```
  print(len(s))            # CPython 3 | run 3 | --jit 3
  (a counting loop, `while i < len(s): i += 1`, also gives 3 on all three; it does not exercise `s[i]`)
  print(len(s[1:]))        # CPython 2 | run 2 | --jit 3   <- JIT slice counts bytes-after-1 as code points
  print(s.find("b"))       # CPython 2 | run 2 | --jit 3   <- JIT returns the BYTE offset
  ```

  The interpreter is correct on every row; the compiled path is the only one wrong, on `find` and on slices.

- Where the byte semantics live (compiled path), so the next round starts here:
  - `len`: `mojo/backend_gimple/emit_calls.py:3706,3744`, `mojo/backend_gimple/emit_methods.py:5704,5964-5988` (already codepoint, via `mojo_str_codepoint_len`).
  - `find`/`index`/`rfind`/`count`: `mojo/backend_gimple/emit_methods.py:5824-5860` (`mojo_str_find`, `mojo_str_find_from`) and the second arm at `:6268-6297`. Both return a byte offset; `runtime/fire_runtime.c` (`mojo_str_find`, `mojo_str_find_from`) is where the offset is computed.
  - subscript and slice: `mojo/backend_gimple/emit_calls.py:9305` (`_lower_subscript`), `runtime/fire_runtime.h:865-867` (`mojo_str_slice`, `mojo_cstr_slice`, `mojo_cstr_slice_n`), and the `(char *, start, stop)` ABI in `gimple_codegen.py:3345-3355`.

- **Decision needed (the representation question, not a code question):** a code-point index over a bare UTF-8 `char *` is O(i) per access, and the self-hosted tokenizer scans multi-MB sources with `src[pos]` (see the 2026-10-21 entry). Two options that answer all of `len`/`s[i]`/slice/`find` at once:
  - **(A) ASCII-aware string value.** Lower compiled strings to a value carrying `(data, byte_len, codepoint_len, is_ascii)`. For `is_ascii` the code-point index is the byte index (O(1), no behaviour change on ASCII, which is almost all of the tree). Non-ASCII takes an O(n) walk with the count cached on the value. This is the "real string value type" the formal backends already use (`bugs/FORMAL_string_value_model.md`), and it is what I recommend: it makes the fast path the common path and gives the slow path a single owner.
  - **(B) Keep `char *`, codepoint everywhere, O(i) indexing.** Simplest type-wise, but it turns tokenizer-shaped loops quadratic on the compiler's own sources. Rejected for the self-host path unless (A) is ruled out.
- **Implementation plan once (A) is chosen (ordering):** (1) add the value type and its ops to `runtime/fire_runtime.{h,c}` with a unit probe in the runtime test (`test_runtime_header_scan.py` census moves, use its `--fix`); (2) route `len` through it (the `emit_calls.py:3706/3744` and `emit_methods.py:5704/5964` sites already converge on one helper); (3) `find`/`index`/`count` and `_lower_subscript` on the value, with the ASCII fast path first; (4) slices through `mojo_str_slice*`; (5) move `char *`-only call sites to the value in the order the probe exposes them.
- **Tests that will prove it:** extend `test_nonascii_len_regression.py` (or a sibling `test_nonascii_index_regression.py`) with the four rows above (`len(s[1:])`, `find`, a `while i < len(s): s[i]` walk over `"aéb"` and `"é"*3`) asserting CPython's output on interpreter AND `--jit`. Each must fail on this tree today (the JIT rows above) and pass after. Regression for the ASCII fast path: a byte-identical generated C check on an all-ASCII program before vs after (`cmp`), so the common path is provably unchanged. The compiled-path blast radius is the integrator's to gate (`make gate`, with `stdlib-dylib` skip count and `stdlib-syntax` U count checked).

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