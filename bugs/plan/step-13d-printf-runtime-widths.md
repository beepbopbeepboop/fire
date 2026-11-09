# plan/step-13d: `%<w>.<p>s` on a non-ASCII image with a run-time operand, via star arguments
**Status: DONE 2026-11-08 (measured; arm64 AND x86-64, redone from master).** The two worker attempts (branch `work/plan-13d-r2`: unwired emitters with `pass` placeholders, malformed test rows) were NOT used. Instead of hand-assembled UTF-8 loops, the runtime already exports word-shaped helpers (`mojo_str_codepoint_len`, `mojo_utf8_codepoint_to_byte_offset`, `mojo_strlen`), so the lowering is a SOURCE-level rewrite to the star form: `formal/model/strings.py::printf_runtime_text_widths` turns `%<flags><w>.<p>s` over a run-time String NAME in an image that holds non-ASCII text into `%<flags>*.*s` with the width and precision computed in CHARACTERS (precision <- byte offset of code point P; width <- W + bytes shown - characters shown); both codegens call it right after the fold (`printf_fold_text_widths`), and `formal/build.py::_runtime_word_calls` adds the three helpers to the link prepass when `printf_runtime_width_operands` finds a use. Measured against CPython on both architectures for `%6s %-6s %.3s %8.3s %-8.3s` of `héllo` (all five match; before: `printf("%*.*s", 8, 3, "héllo")` printed `     hé`, CPython `     hél`). `test_formal_unicode.py`: 191/0 -> 209/0 (10 new oracle rows, an ASCII twin for each, and 9 model checks; the old row that asserted the refusal was replaced). Not covered: an operand that is not a plain name (a call, a field) keeps the refusal; so does a precision written `%.s`. `test_formal_runtime_link.py` 225/225; `test_runtime_header_scan.py` 72/72 after refreshing the census (908 entry points; another commit had added 11 declarations).
Class: mid      Size: M      Depends: 13c      Blocks: none
Source: "Run-time code-point walk" in `bugs/FORMAL_string_value_model.md` (step 13c memo): read it first, it has the decision, the formulas and the measurements.

## Work order
1. Arm64 first. In `formal/arm64_codegen.py` next to `_emit_str_count` (:8484) add `_emit_utf8_charcount` and a `_emit_utf8_bytes_for_chars` loop (continuation byte test `(b & 0xC0) == 0x80`; stop at NUL). Keep them small and shared; no per-call allocation.
2. In `formal/model/strings.py` add `printf_runtime_text_widths` (sibling of `printf_fold_text_widths`, :2096) and call it where `printf_text_width_refusal` (:2005) refuses a string-kind operand on a non-ASCII image: rewrite `%W.Ps` to `%*.*s` with the computed arguments (formulas in the memo). An operand that is not a string-kind keeps the refusal.
3. Tests: oracle rows `%6s`, `%-6s`, `%.3s`, `%8.3s` with a `String` PARAMETER holding `héllo`, `日本`, `a😀b` in `test_formal_unicode.py`, built and run on arm64 against CPython. The existing refusal rows for an unsupported operand must still refuse. An ASCII-only image must emit the same code as before.
4. x86-64 only after arm64 passes: same two emitters in `formal/x86_64_codegen.py` next to `_emit_str_count` (:6652).

## Do NOT
- Do not change anything for an ASCII image. Do not add allocation. Do not touch the proof generator: the program stays `prove`-refused with a named reason.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_unicode.py
python3 tools/plan_index.py --check
```
