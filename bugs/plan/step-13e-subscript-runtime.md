# plan/step-13e: `s[i]` on a non-ASCII image with a run-time receiver or index
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
