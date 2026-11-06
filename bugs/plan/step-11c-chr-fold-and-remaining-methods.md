# plan/step-11c: `chr(<constant>)` folds; `replace`/`join`/the case-variants refuse naming the buffer correctly
**Status: DONE 2026-11-06 (measured).** `chr(65)` prints `A` on arm64 and x86-64; the refusal rows are unchanged and green in `test_formal_str_methods.py`.
Class: mid      Size: S      Depends: 11a      Blocks: 13
Source: `bugs/FORMAL_string_value_model.md` § "`ord`, `chr` and `hash` were not an encoding question at all" (line ~1118).

## Current state (measured; verified 2026-11-05)
- `chr(n)` is refused for every argument by `text_builtin_refusal` (`formal/model/strings.py:~496`: "its answer is a NEW one-character String ... nowhere to put one ... the same missing buffer `upper()`/`join()`/`replace()` are refused for"). Emitted from `_emit_text_builtin` (`arm64_codegen.py:6748`, `x86_64_codegen.py:4853`), which folds only `ord` via `M.ord_fold` (`strings.py:433`).
- Pinned by `test_formal_unicode.py` REFUSAL_CASES: `refuse_chr_names_the_missing_buffer` (`chr(233)`, needles `"chr(233) is refused", "NEW one-character", "nowhere to put one", "LENGTH_DEPENDENT_METHODS"`, line ~893) and `refuse_chr_of_an_ascii_code_point_is_still_refused` (`chr(65)`, line ~901), and `refuse_hash_*` (do not touch).
- `replace`, `join`, `swapcase`, `capitalize`, `title`, `casefold`, `center`/`ljust`/`rjust`/`zfill`, `format`, `removeprefix/suffix`, `reverse` are still in `LENGTH_DEPENDENT_METHODS` with reasons that say "no heap" / "the only buffer available ... is the receiver's own bytes", which became false when 11a defined the buffer.

## Decisions already made
- **`chr(k)` with `k` a compile-time INTEGER LITERAL in 1..127 folds to the interned one-character literal** (`self._emit_expr(F.StringLiteral(chr(k)))`; no buffer needed; a literal is its own text). Reasons: it keeps the image-level ASCII invariant (an ASCII literal adds no non-ASCII text); NUL (`chr(0)`) is refused by the NUL obligation (`STRING_BUFFER_NUL_OBLIGATION`, step 11a). `chr(128..)` stays refused with the existing text (it would introduce a non-ASCII string after `publish_non_ascii_strings` already ran for the image). `chr(<non-literal>)` stays refused: the result could be >= 128 or 0, which would break the invariant "the image's literals are exactly its string contents", and a run-time check has no refusal path.
- Refusal text for the remaining `chr` cases is rewritten to be TRUE after 11a: say "a run-time or non-ASCII code point has no representation: the result would break the rule that an all-ASCII image holds only ASCII strings (and chr(0) the NUL rule)", keep the substrings `"chr(233) is refused"` and `"NEW one-character"` ONLY if the new sentence still contains them naturally; otherwise update the needles in the test row in the same commit (that is a test edit the step authorises).
- `replace`, `join`: stay REFUSED. New reasons (shared constants in `cfg.py`): `replace` "needs a two-pass walk (count occurrences, then build) over a buffer sized from the count; the runtime buffer exists (`strdup`) but the sizing loop is not lowered"; `join` "needs the elements of a sequence of strings walked at run time and this path cannot iterate a string blob (see string_iteration_refusal)". The case-variants (`swapcase`, `capitalize`, `title`, `casefold`): "same buffer as upper(), different per-position rule; not lowered yet". `center/ljust/rjust/zfill/format/removeprefix/removesuffix/reverse` keep their wording except that every sentence claiming "no heap"/"no buffer" is replaced by the accurate one.
- `swapcase`/`capitalize`/`title` could be lowered with the 11a loop but are NOT in this plan (out of the doc's list).

## Work order
1. `formal/model/strings.py`: add `chr_fold(args) -> str | None` next to `ord_fold`: returns `chr(k)` iff `len(args)==1`, the argument is an `F.IntLiteral` (also accept a negative? no: negative -> None) with `1 <= k <= 127`; else None. Rewrite the `chr` branch of `text_builtin_refusal` per the Decision.
2. Both `_emit_text_builtin`: `if name == "chr": s = M.chr_fold(args); if s is not None: self._emit_expr(F.StringLiteral(s)); return` before the final refusal.
3. KIND of the result: `m = chr(65)` must bind `m` as a string. Find where `ord`'s INT result kind is established: `grep -n '"ord"' formal/model/*.py formal/arm64_codegen.py formal/x86_64_codegen.py`; add `chr` -> `STR_KIND` there ONLY when `chr_fold(call.args)` is not None. If no such place exists (kind of a builtin call comes from a table), add the entry to that table with the same guard. Measure with the test below: `var m = chr(65); printf("[%s]", m)` must print `[A]`, not a number.
4. `formal/model/cfg.py`: reword the `LENGTH_DEPENDENT_METHODS` entries per the Decision.
5. `test_formal_unicode.py`: move `refuse_chr_of_an_ascii_code_point_is_still_refused` out of `REFUSAL_CASES` into `ORACLE_CASES` (rename `chr_of_an_ascii_literal_folds`; shape `(name, mojo_source, cpython_source)`, line ~113; `print` for the CPython column); add refusal rows `chr_zero_is_refused` (needle `"NUL"`) and `chr_of_a_name_is_refused`; keep `refuse_chr_names_the_missing_buffer` (`chr(233)`) and both `refuse_hash_*` rows byte-for-byte unless the needles in the Decision force an edit.
6. `test_formal_str_methods.py`: any row asserting the old `replace`/`join` sentence is updated to the new reason (grep `"no heap"`, `"nowhere"`).
7. Status paragraph in `bugs/FORMAL_string_value_model.md`.

## Do NOT
- Do not fold `chr(k)` for `k >= 128` (would silently make the image non-ASCII after the table is published).
- Do not touch the `hash` reason.
- Do not lower `replace`/`join` here.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_unicode.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_str_methods.py
```

## Done when
- [ ] `chr(65)` prints `A` on both backends vs CPython (oracle row)
- [ ] `chr(0)`, `chr(233)`, `chr(n)` refused, `hash` rows unchanged and green
- [ ] no remaining refusal sentence says "no heap" about strings: `grep -n "no heap\|there is no heap" formal/model/cfg.py` empty for string methods

## If stuck
If the result kind cannot be threaded (item 3), keep `chr` fully refused (revert items 1-2), do items 4 and 6 only, record the kind-table location you found in the doc Status, stop.
