# plan/step-14a: RESTORE the compile-time set-literal dedup that the `formal/model/` package split lost
Class: easy      Size: S      Depends: none      Blocks: 14b, 14c, 14d
Source: `bugs/FORMAL_set_value_model.md` top Status (2026-10-12): "word-canonical half is fixed" — which is FALSE on this tree.

## Current state (measured 2026-11-05)
- `def main(n: Int) -> Int:\n    var s = {1, 1, 2, 3, 3}\n    return len(s)` builds (arm64) and exits **5**; CPython: 3.
- `grep -rn "set_literal_distinct_elements\|set_literal_word_key" formal` finds NOTHING; `grep -n "s_len_dups\|s_walk_dups" test_*.py` finds NOTHING. The fix was commit `1d40572ed` (an ancestor of HEAD) against the old single file `formal/model.py`; the later split into `formal/model/*.py` dropped it. `CANONICAL_ELEM_TYPES = (F.IntLiteral, F.BoolLiteral, F.StringLiteral)` is still at `formal/model/__init__.py:46`.
- Current emission: arm64 `formal/arm64_codegen.py:4440-4444` (`if isinstance(expr, F.SetExpr): ... self._emit_list(expr); return`); x86-64 a `(F.ListExpr, F.TupleExpr, F.SetExpr)` arm (find: `grep -n "F.SetExpr" formal/x86_64_codegen.py`).
- Stale claims in the doc / old plan: "x86-64 has no set emitter (`set_union_refusal`)" — `set_union_refusal` is gone; `_emit_set_union`, `_emit_set_op`, `_emit_set_filter_pass` exist on x86-64 (`x86_64_codegen.py:8201-8441`).

## Decisions already made
- Re-land the old patch verbatim in the new layout. `git show 1d40572ed -- formal/model.py formal/arm64_codegen.py formal/x86_64_codegen.py test_formal_container_methods.py` is the authority; the model functions are `set_literal_word_key(e)` (IntLiteral -> `("int", int(e.value))`, BoolLiteral -> `("bool", bool(e.value))`, StringLiteral -> `("str", e.value)`, else None) and `set_literal_distinct_elements(elements) -> (kept, dropped)` returning `(None, 0)` when any element's word is unknown. Put both in `formal/model/layout.py` immediately after `key_compare_is_structural` (line ~137; it already uses `CANONICAL_ELEM_TYPES`). (A string's word is its interned address, so two equal literals compare equal; compare by decoded text, `F.decoded_literal(e)` rather than `e.value` IF `e.value` is the raw escaped body — check with `"a\x41"` vs `"aA"` and use whichever makes those two equal.)
- Careful with the old `(None, 0)` convention: in the emitters `kept, dropped = ...; if dropped: expr = F.ListExpr(elements=kept, line=expr.line, col=expr.col)` — `dropped == 0` for the `None` case so nothing happens. Keep that.
- x86-64: split the combined arm so `F.SetExpr` has its own arm exactly as in the old diff (the old diff shows the shape).
- Order is untouched (insertion order of first occurrence).

## Work order
1. Model functions in `formal/model/layout.py`.
2. arm64 `:4440` and x86-64 arm.
3. Tests: `test_formal_container_methods.py` `SET_CASES` (line 614; rows are `(name, setup_lines, expr_or_(fmt,args), why)`): add the three rows from the old diff verbatim: `s_len_dups` (`["s = {1, 1, 2, 3, 3}"]`, `"len(s)"`), `s_walk_dups` (walk summing; CPython 6), `s_len_dups_str` (`['s = {"a", "a", "b"}']`, `"len(s)"`), with their `why` text.
4. `bugs/FORMAL_set_value_model.md`: add a dated Status line: the fix was lost in the package split and is re-landed by this commit.

## Do NOT
- Do not dedup when any element is non-canonical (the whole literal keeps its repeats until 14b).
- Do not reorder the kept elements.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_container_methods.py
```

## Done when
- [ ] `s_len_dups`, `s_walk_dups`, `s_len_dups_str` pass on both backends (CPython oracle)
- [ ] `grep -rn set_literal_distinct_elements formal | wc -l` >= 3 (def + two emitters)

## If stuck
If the x86-64 arm cannot be split cleanly, apply the dedup in the shared arm with an `isinstance(expr, F.SetExpr)` guard; record that in the doc Status. Never leave the arm64 half without the x86-64 half.
