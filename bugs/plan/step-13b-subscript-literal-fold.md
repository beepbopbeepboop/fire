# plan/step-13b: `<literal>[<int literal>]` on non-ASCII text folds to the one-character string
**Status: DONE 2026-11-06 (measured).** `"héllo"[1]` prints `é` on both backends.
Class: mid      Size: M      Depends: 10      Blocks: 13c
Source: `bugs/FORMAL_string_value_model.md` Wave 9 ("`s[i]` on non-ASCII text", line ~1070) and "`ord`, `chr` and `hash`..." (line ~1118).

## Current state (measured; verified 2026-11-05)
- `string_element_refusal(base, index, fn, decls, functions)` (`formal/model/values.py:4098`) refuses every string subscript when `non_ascii_strings()` is non-empty, unless the receiver is declared bytes (`receiver_is_declared_bytes`). Called at `formal/arm64_codegen.py:6335` and `formal/x86_64_codegen.py:7691`. In an ALL-ASCII image `s[i]` yields the BYTE (an INT, a deliberate type divergence from CPython; leave it).
- Pinned: `refuse_subscript_into_a_non_ascii_string` (`s = "日本"`, `s[1]` via `%c`, needles `"is refused on a string whose text is not ASCII","s[1]","0x9c","one CHARACTER"`, `test_formal_unicode.py:810`), `refuse_subscript_into_a_non_ascii_literal` (`"日本"[1]`, needles incl. `"the literal","nowhere to put one"`, line ~821), `refuse_subscript_through_a_string_annotated_parameter` (line ~875), and the answered `subscript_into_an_ascii_string_reads_its_byte` (line ~577).
- The draft's claim "needs step 11's buffer" is false for a receiver whose text and index are compile-time known: the answer is itself a literal, interned like any other (the emitters intern on demand: `self._emit_expr(F.StringLiteral(x))`, as `_emit_str_lstrip` does).

## Decisions already made
- Fold ONLY when: `non_ascii_strings()` is non-empty (the image rule that makes the refusal fire); `string_literal_text(base)` is a `str` T (this covers a literal; a NAME bound to a literal is covered only if the backend's `_printf_arg_text`-style text-of-expression helper returns T — use it, same helper 13a uses, so `var s = "日本"; s[1]` folds); `index` is an `F.IntLiteral` (or unary-minus IntLiteral) `k` with `-len(T) <= k < len(T)` (Python rules; out of range is NOT folded — CPython raises IndexError; keep the refusal). Result: `T[k]`.
- Result representation: the one-character STRING (`F.StringLiteral(T[k])`, a `char *`, STR_KIND), not a byte. Consumers must use `%s`/`print`; the old refusal rows used `%c`, which would print a pointer's low byte, so the rewritten rows use `%s`. This is what CPython's `s[i]` is.
- KIND plumbing is part of the step: a `SubscriptExpr` with a string base normally has the INT element kind. Find where (`grep -n "SubscriptExpr" formal/model/cfg.py formal/arm64_codegen.py | head -30`, and each backend's `_expr_str_kind`) and make it return `STR_KIND` exactly when `M.string_element_fold(base, index, text_of)` is not None. In an ASCII image nothing changes (`string_element_fold` returns None when `not non_ascii_strings()`).
- Non-literal index or unknown text stays refused: that is step 13c.

## Work order
1. `formal/model/values.py`: add `string_element_fold(base, index, text_of=None) -> str | None` beside `string_element_refusal`. `text_of(expr)` -> decoded text or None (default: `string_literal_text`).
2. Both emitters (arm64 `:6335`, x86 `:7691`): before calling `M.string_element_refusal`, `ch = M.string_element_fold(e.obj, e.index, <the backend's text-of helper>)`; `if ch is not None: self._emit_expr(F.StringLiteral(ch)); return`.
3. Kind plumbing as above (both backends + model table if the kind is model-side).
4. Rewrite the two pinned refusal rows into ORACLE rows (`s[1]` of `"日本"` printed with `%s` / `print`; CPython `print("c=[" + s[1] + "]")`), plus rows: `"héllo"[0]` (an ASCII char in a non-ASCII image -> still the one-char string "h"), `"héllo"[-1]`, `"héllo"[1]` (`é`), a name bound to the literal, and a REFUSAL row `"日本"[2]` (out of range; needle `is refused`). Keep `refuse_subscript_through_a_string_annotated_parameter` unchanged.
5. Status paragraph in `bugs/FORMAL_string_value_model.md`.

## Do NOT
- Do not change the ASCII-image behaviour (`s[i]` stays a byte there).
- Do not fold negative-out-of-range / non-literal indexes.
- Do not alter `string_element_refusal`'s text for the cases still refused, except the sentence "nowhere to put one" for a KNOWN-literal receiver with a literal index (that case no longer reaches it).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_unicode.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
```
(`test_formal_run.py` is long: run once at the end; a subset can be selected by case name.)

## Done when
- [ ] the rewritten oracle rows pass on both backends
- [ ] ASCII-image subscript rows (`subscript_into_an_ascii_string_reads_its_byte`) unchanged-green
- [ ] the out-of-range row refuses

## If stuck
If the kind of a folded subscript cannot be made STR without regressing other rows, keep the fold OUT, write the row names that regressed into the doc Status, stop.
