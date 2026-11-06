# plan/step-13a: `%<w>s`, `%-<w>s`, `%.<p>s` on a non-ASCII text the build can SEE are folded to the CPython answer
**Status: DONE 2026-11-06 (measured).** `printf("[%5s][%-5s][%.1s]", "日本", "日本", "日本")` prints `[   日本][日本   ][日]` on both backends, equal to CPython; `printf_fold_text_widths` is in `formal/model/strings.py`; `test_formal_unicode.py` 191/0.
Class: mid      Size: M      Depends: 10      Blocks: 13c
Source: `bugs/FORMAL_string_value_model.md` Wave 9 ("A `%<width>s` on non-ASCII text ... `%.3s` is refused for the same reason", line ~1085).

## Current state (measured; verified 2026-11-05)
- Refusal: `printf_text_width_refusal` (`formal/model/strings.py:1949`), called from `printf_text_conversion_refusal`'s chain via `printf_format_refusal` (`strings.py:2976`), reached from `_check_printf_format`-style hook `arm64_codegen.py:~7117` (`reason = M.printf_format_refusal(name, F.decoded_literal(fmt) ..., args[idx+1:], self._printf_arg_is_text, self._printf_arg_text, ...)`) and x86 `x86_64_codegen.py:~5266`. `text_of_arg` (`self._printf_arg_text`) returns the DECODED text of an argument when the build can see it (a literal, or a name bound to one), else None.
- Specs: `_printf_specs(fmt_text)` returns dicts with keys `stars`, `conv`, `quant` (the text between `%` and the conversion character, flags included, e.g. `-6`, `.3`, `10.3`) — see `printf_text_widths` (`strings.py:1582`) and its tests at `test_formal_unicode.py:1542-1650`.
- Pinned refusal rows (REFUSAL_CASES, `test_formal_unicode.py`): `refuse_printf_width_on_non_ascii_text` (`"[%6s]\n", "héllo"`, line ~832), `refuse_printf_left_width_on_non_ascii_text` (`%-6s`), `refuse_printf_precision_on_non_ascii_text` (`%.3s`, line ~848), `refuse_printf_width_on_an_unseen_operand_in_a_non_ascii_image` (line ~859), plus an ORACLE row `printf_width_beside_a_non_ascii_literal_still_prints` (line ~562) and `printf_width_on_ascii_text_agrees_with_cpython` (line ~555).
- C `printf("%6s","héllo")` pads to BYTES; CPython `"%6s" % "héllo"` pads to characters. The statement "needs the buffer" in the draft is wrong for a text the build can see: the answer is a compile-time constant string.

## Decisions already made
- **Fold, not buffer.** For each spec with `conv == "s"`, `stars == 0`, a non-empty `quant`, whose operand's text `T` is known (`text_of_arg(arg)` returns a `str`) AND `T` is non-ASCII: compute `R = ("%" + quant + "s") % T` with PYTHON's `%` operator (this is CPython's semantics by construction: flags, width, precision in characters), then rewrite the spec to a plain `%s` and the operand to `F.StringLiteral(R)`. `R` contains no format semantics because it travels as an ARGUMENT, not in the format string.
- Only non-ASCII known text is rewritten. ASCII text keeps the existing byte path (already right, and 200+ rows pass on it). Operands whose text is unknown stay under the existing refusal (that is step 13c). `*` widths/precisions (`stars > 0`) stay refused.
- The rewrite is ONE shared function in `formal/model/strings.py`: `printf_fold_text_widths(callee, fmt_text, args, text_of_arg) -> (new_fmt, new_args) | None` (None = nothing to fold). `args` here is the vararg list after the format. It runs BEFORE `printf_format_refusal` in both emitters; when it returns a pair the emitter proceeds with `F.CallExpr(func=e.func, args=[F.StringLiteral(new_fmt), *new_args], kwargs=e.kwargs, line=e.line, col=e.col)` in place of `e` (copy the node constructor call shape from `model.set`-style helpers: look at how `lstrip` builds `F.StringLiteral`; the CallExpr field names are in `fire_compiler.py` `class CallExpr`).
- `new_fmt` is built from the DECODED format text by splicing the original text between specs unchanged; the `%` of `%%` is untouched (`_printf_specs` already skips it; assert that with a row).

## Work order
1. `formal/model/strings.py`: implement `printf_fold_text_widths`. Walk the specs exactly as `printf_text_width_refusal` does (operand index = running `arg + s["stars"]`). To splice, you need each spec's start/end offsets in `fmt_text`: if `_printf_specs` does not return them, extend it to add `start` and `end` keys (read its body first; it is the single scanner, extend it, do not write a second regex) and run `test_formal_unicode.py` model_checks (lines 1542-1650) to prove the old keys are unchanged.
2. `formal/arm64_codegen.py` and `formal/x86_64_codegen.py`: at the printf emission entry (the function containing `M.printf_format_refusal`, arm64 ~7117, x86 ~5266 — the same function is also called for `print`? read callers with `grep -n "_check_printf" formal/*_codegen.py`), apply the fold first, and make BOTH the refusal check and the emission see the rewritten call. Two lines in each emitter; the decision stays in the model.
3. Tests `test_formal_unicode.py`: move the first three refusal rows (`%6s`, `%-6s`, `%.3s` on literal `"héllo"`) from REFUSAL_CASES to ORACLE_CASES with CPython `print("[%6s]" % "héllo")` style columns (the Python column must print the same text; the Mojo column `printf("[%6s]\n", "héllo")` and Python `print("[%6s]" % "héllo")`); add rows: `%10.3s` of `"日本語テキスト"`, `%-5s|` of `"日本"`, a NAME bound to the literal (`var s = "héllo"` then `printf("[%7s]\n", s)`), `%%` beside a folded spec, and one spec folded + one `%d`. Keep `refuse_printf_width_on_an_unseen_operand_in_a_non_ascii_image` as is (still refused; 13c).
4. Status paragraph in `bugs/FORMAL_string_value_model.md`.

## Do NOT
- Do not fold ASCII operands (no churn in the 200+ passing rows).
- Do not use C-style width arithmetic; use Python's `%` operator on the decoded text — the oracle is CPython and this makes the fold agree by construction.
- Do not touch the unknown-operand refusal.
- Do not edit `ord`/`chr`/`hash` handling.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_unicode.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_str_methods.py
```

## Done when
- [ ] the three moved rows and the five new rows pass as ORACLE rows on both backends
- [ ] `refuse_printf_width_on_an_unseen_operand_in_a_non_ascii_image` still passes as a refusal
- [ ] the model_checks (`strings.py` scanner) lines of `test_formal_unicode.py` pass unchanged

## If stuck
If the rewritten `CallExpr` is not accepted by the emitter (e.g. a flow-sensitive `_printf_arg_text` cache keyed on node identity), record the failing row in the doc Status and keep the refusals; land nothing.
