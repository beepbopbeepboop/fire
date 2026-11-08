# plan/step-13d: `%<w>.<p>s` on a non-ASCII image with a run-time operand, via star arguments
**Status: OPEN 2026-11-08 (measured; two worker attempts reviewed and NOT integrated).** Branch `work/plan-13d-r2` holds a worker's WIP (do not merge it): (1) `formal/model/strings.py::printf_runtime_text_widths` detects the shape and then `return None`s unconditionally ("simplified ... for now"), so nothing is rewritten and the refusal is unchanged; (2) `formal/arm64_codegen.py::_emit_utf8_charcount/_emit_utf8_bytes_for_chars/_emit_utf8_char_start` are unwired, `_emit_utf8_char_start` has `pass` placeholders in its loop, and the others clobber X1/X0 with no register contract; (3) the four new oracle rows are malformed (a stray `\\n` after the `printf(...)` in the Mojo source, and a Python twin `def main(n)` that the harness calls with no argument), so the CPython reference itself crashes (4 FAILs; the rest of `test_formal_unicode.py` is 189 pass / 5 fail on that branch against 191 / 0 on master). A new attempt should start from master, write the emitters against a register contract copied from `_emit_str_count` (arm64 :8484), wire them from the printf lowering where `printf_text_width_refusal` fires on a string-kind operand, and add the oracle rows in the shape of `printf_fold_plus_int` (no `n` in the twin). The measurements in the 13c memo (`%*.*s` is accepted by the variadic area; the byte/character mismatch) stand.
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
