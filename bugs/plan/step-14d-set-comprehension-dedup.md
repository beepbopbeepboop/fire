# plan/step-14d: a set COMPREHENSION is distinct (`{x % 2 for x in range(6)}` has len 2)
**Status: DONE 2026-11-06 (measured).** `_compr_append_elem(distinct=True)` for `kind == "set"` on both backends (scan the result so far, skip the store); container elements refused (`set_comprehension_element_refusal`); computed integer elements accepted. Rows `s_comp_len/sum/filter/unique` and `s_comp_container_r` pass; list/dict rows unchanged.
Class: mid      Size: M      Depends: 14b      Blocks: none
Source: `bugs/FORMAL_set_value_model.md` top Status ("a set COMPREHENSION ... still lower[s] with [its] repeats").

## Current state (measured; verified 2026-11-05)
- `F.Comprehension.kind` is `"list"|"set"|"dict"` (`fire_compiler.py:564`). `_emit_comprehension` (arm64 `:12795`; x86 `:11660`) lowers every kind identically for non-dict: a `[count][...]` blob whose capacity is `_compr_cap(expr)`; the appending happens in `_emit_compr_gen(expr, 0, offset, is_dict, cap, d0)`. No dedup for `kind == "set"`.

## Decisions already made
- For `kind == "set"`, at the point where `_emit_compr_gen` stores the element, insert the SAME `contains` scan as 14b/14c (`_emit_set_contains` over the result blob's current count) and skip the store when found. The element-eligibility rule is 14b's: element kind int, else `set_runtime_element_refusal` (a comprehension's element kind comes from `_expr_str_kind(expr.element)`, evaluated before emission; if it is None, apply 14b's fallback decision).
- Capacity `_compr_cap` is an upper bound on appended elements, so skipping stores is safe.
- Relocated-element comprehension path (`self._compr_reloc`) is for container elements, which are not eligible set elements anyway: leave it, and refuse a set comprehension whose element is a container with the existing sentence plus "a set element must be hashable".

## Work order
1. Read `_emit_compr_gen` on both backends (arm64 `grep -n "def _emit_compr_gen" formal/arm64_codegen.py`; x86 same) and find the one place where the element is stored and the count is incremented. Wrap THAT block: `if expr.kind == "set": scan; skip`.
2. Tests `test_formal_container_methods.py` (find how comprehension rows are spelled there with `grep -n "for x in range" test_formal_container_methods.py | head`; if none, add to SET_CASES): `s_comp_len` (`s = {x % 2 for x in range(6)}`, `len(s)` -> 2), `s_comp_sum` (`{x % 3 for x in range(10)}` walk sum -> 3), `s_comp_filter` (with an `if`), `s_comp_unique` (all distinct -> 6, no change).
3. Doc status lines.

## Do NOT
- Do not change list or dict comprehensions.
- Do not dedup on the per-iteration relocation path.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_container_methods.py
```

## Done when
- [ ] the four `s_comp_*` rows pass on both backends vs CPython
- [ ] list and dict comprehension rows in the same file unchanged-green

## If stuck
Record where the store/increment is emitted on the backend that resisted, land the other backend only if the file's differential rows stay green on both (never one backend alone: invariant 1); otherwise land nothing.
