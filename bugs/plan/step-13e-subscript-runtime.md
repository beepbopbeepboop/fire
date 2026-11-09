# plan/step-13e: `s[i]` on a non-ASCII image with a run-time receiver or index
**Status: DONE (printf `%c` case) 2026-11-08 (measured; arm64 AND x86-64); the general element read is NOT done.** Same technique as 13d, no hand-written loops: `formal/model/strings.py::printf_runtime_text_elements` rewrites `printf("%c", name[i])` (receiver and index plain names or integer literals, receiver a string, image holding non-ASCII text, receiver text NOT visible to the build) to `%s` of `mojo_char_at_str_cp(name, i)`, the runtime helper that walks code points and takes negative indices from the end; both codegens call the chained entry `printf_runtime_rewrites` (widths from 13d, then elements) and `formal/build.py::_runtime_word_calls` links the helper. `héllo`, `日本語` and `a😀b` at indices 1, 0, -1 and a variable index match CPython on both architectures; `test_formal_unicode.py` 209/0 -> 224/0 (10 oracle rows, 5 model checks). The existing refusal row for a receiver whose text the build can see and an out-of-range literal index (`s = "日本"; s[2]`) is unchanged. STILL REFUSED, by design: an element read in any other position (assignment `c = s[i]`, comparison, `ord(s[i])`, `print(s[i])`), because the byte-load lowering gives the element an INTEGER kind and a character needs a string kind there; that is kind plumbing, not a rewrite. Out of range at run time the helper returns an empty string where CPython raises IndexError (the ASCII lowering also does not trap).
Class: mid      Size: M      Depends: 13d      Blocks: none
Source: "Run-time code-point walk" in `bugs/FORMAL_string_value_model.md` (step 13c memo).

## Work order
1. Reuse 13d's `_emit_utf8_charcount` and add `_emit_utf8_char_start(ptr, index)` (byte offset of code point `index`; negative index = `charcount + index`). Result: the 11a buffer holding `1 + trailing continuation bytes` bytes from that offset, NUL-terminated. Out-of-range keeps the existing path.
2. In `formal/model/values.py` change `string_element_refusal` (:4142) so a string-kind receiver on a non-ASCII image is lowered instead of refused; every other operand kind keeps its refusal.
3. Oracle rows in `test_formal_unicode.py`: `s[1]`, `s[i]`, `s[-1]` with a `String` parameter holding `héllo`, `日本`, `a😀b`, arm64 against CPython; then x86-64.

## Do NOT
- No change for ASCII images; do not touch the proof generator.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_unicode.py
python3 tools/plan_index.py --check
```
