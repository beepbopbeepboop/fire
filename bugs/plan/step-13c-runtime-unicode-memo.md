# plan/step-13c: DECISION MEMO — `%<w>s` / `%.<p>s` and `s[i]` on non-ASCII text the build CANNOT see
Class: hard      Size: M      Depends: 11a, 13a, 13b      Blocks: none
Source: `bugs/FORMAL_string_value_model.md` Wave 9; `formal/model/strings.py:1949 printf_text_width_refusal`, `formal/model/values.py:4098 string_element_refusal`.

## Current state
After 11a/13a/13b: a non-ASCII image still refuses (i) a width/precision on a `%s` whose operand text is unknown and (ii) a subscript whose receiver text or index is not a compile-time constant. Both need a RUN-TIME code-point walk: UTF-8 continuation bytes are `0x80..0xBF`; a code point starts at every other byte.

## Output of this step (design only, committed into `bugs/FORMAL_string_value_model.md` Status)
A guide a mid worker can execute without re-investigation, containing:
1. The measurement: the four refusals that remain (row names in `test_formal_unicode.py`).
2. The decision, recommended and with the alternative laid out: (A) width/precision via `printf`'s own star forms: for a spec `%<flags>W.Ps` with a runtime operand `p`, emit `%<flags>*.*s` with TWO extra int args computed at run time by a shared loop: `bytes_for_chars(p, P)` (first P code points -> byte length) and `W' = W + (strlen(p) - charcount(p))` for the pad (the loop counts non-continuation bytes); (B) copy into a `strdup`'d buffer (11a) and pad there (rejected: needs a sized buffer, more allocation). For `s[i]`: `start = byte offset of code point i` (loop), `len = 1 + continuation bytes that follow`, result = `strndup(p + start, len)` (the 11a buffer; NUL-free by construction); i out of range -> refuse at run time is NOT available (no exception path), so a run-time index is accepted only when the program also guards it? Lay out the two options (refuse run-time indices entirely vs. bounds-check returning the empty string) and recommend refusing.
3. Exact files/functions: shared loop emitters `_emit_utf8_charcount` / `_emit_utf8_char_start` in both codegens next to `_emit_str_count` (arm64 `:8391`, x86 `:6610`), the model rewrite in `printf_fold_text_widths`' sibling `printf_runtime_text_widths`, kind plumbing from 13b.
4. The tests: oracle rows with a parameter-typed operand in a non-ASCII image, built and run on both backends vs CPython.
5. Whether the star forms (`%*.*s`) are accepted by the variadic-area code (`_emit_variadic_area`, `arm64_codegen.py:9014`): measure with a 3-line program and record the result.

## Do NOT
- No code in this step.

## Verification
`python3 tools/dangling_doc_refs.py --ratchet` unchanged versus before.

## Done when
- [ ] the guide exists with all five parts
- [ ] follow-up files `step-13d-*.md` (printf runtime) and `step-13e-*.md` (subscript runtime), Class mid, are written from it

## If stuck
Write the one missing measurement and its command, stop.
