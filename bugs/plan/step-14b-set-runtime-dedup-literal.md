# plan/step-14b: run-time distinctness for a set literal with non-canonical elements (`{x, x, 2}`), both backends
Class: mid      Size: L      Depends: 14a      Blocks: 14c, 14d
Source: `bugs/FORMAL_set_value_model.md` top Status ("What is NOT fixed, and it needs a set RUNTIME").

## Current state (measured; verified 2026-11-05)
- A set literal lowers through `_emit_list` (arm64 `formal/arm64_codegen.py:9184`; x86-64 `formal/x86_64_codegen.py:4583`): a stack blob `[count][e0]...` with `count = len(literal)` and one store per element. After 14a only word-canonical literals are deduplicated (compile time).
- `_emit_set_contains(self, base_reg, count_reg, elem_reg, out_reg)` exists on arm64 only (`arm64_codegen.py:14856`; clobbers X10/X11/X12 and `out_reg`; compares whole 8-byte words). x86-64 has `_emit_set_filter_pass` (`x86_64_codegen.py:8201`, "the same per-element scan") but no `_emit_set_contains`.
- Element-kind query: each backend has `self._expr_str_kind(expr)` returning `"str"`, `"int"` or None (arm64 `arm64_codegen.py:6800+`, x86 same name).
- A computed string (after step 11a) is NOT interned, so two equal computed strings are different words: word equality is wrong for them.

## Decisions already made (the design)
- **Representation is unchanged:** the list blob `[count:i64][word...]`. A "set runtime" here is DISTINCTNESS ESTABLISHED AT RUN TIME BY A LINEAR SCAN over the words already stored (O(n^2), same cost class as the existing `&`,`|`,`-`,`^` emitters, `_emit_set_op`). Reason: capacity is a compile-time bound on this path (frame blobs; `LENGTH_DEPENDENT_METHODS["split"]` says so), a hash table would need either a heap or a bounded bucket array with a probe/resize protocol, none of which the executable has; and the scan matches what the operators already do.
- **Element words eligible for the scan:** an element whose `_expr_str_kind` is `"int"` (integers, bools). `IntLiteral`/`BoolLiteral`/`StringLiteral` elements need no scan against each other (14a handles them), but they still participate as scan targets. A non-literal element whose kind is `"str"` or None, or a float, is REFUSED with a new model sentence `set_runtime_element_refusal(spelled_elem, kind)`: "{x} is a set element whose equality is not a word comparison: a string that is not a literal may be a computed (non-interned) string, and a float's `==` is not bit equality (-0.0, nan)". Reason: refuse rather than answer wrongly (invariants 2 and 3).
- **Fallback decision for kind None (unclassifiable word, e.g. an unannotated parameter):** refuse as above FIRST. Then run the three verification commands; if existing rows in `test_formal_container_methods.py` or `test_formal_run.py` go red SOLELY because of a kind-None element, switch to: kind None is eligible (word compare) provided no OTHER element of the same literal has kind `"str"`; record the switch and the rows that forced it in the doc Status. (Unannotated integer parameters are the corpus's common case; a None-kind word that is really a computed string is the residual, stated in the refusal docstring.)
- **Order:** first-occurrence insertion order, exactly as 14a (documented and pinned: see 14e). No change to `for x in s`.
- **Emission shape (both backends):** a new method `_emit_set_literal(self, expr)` that is `_emit_list`'s FIXED path (not the `_compr_reloc` path: if `self._compr_reloc` is non-empty, raise `CodegenError(M.set_runtime_element_refusal_in_comprehension(...))` or simply fall back to `_emit_list` when every element is canonical) with count starting at 0:
  `reserve blob of size 8*(1+cap) with cap = max(n, self._list_caps.get(id(expr), n))`; `count := 0`; for each element `i`: `eval el -> X0`; `reload base`; `load count`; `_emit_set_contains(base, count, elem, found)`; `if found skip`; `store el at base+8+8*count`; `count := count + 1` (write the count word each time). Result X0 = base.
  The element value must survive the scan: keep it in a callee-saved/scratch register that `_emit_set_contains` documents untouched (arm64: X0-X9 untouched, so hold elem in X0, base in X9, count in X2). x86-64: write `_emit_set_contains(self, base: Reg, count: Reg, elem: Reg, out: Reg)` as the twin with the identical contract ("clobbers only R10/R11 and `out`"), modelled on `_emit_set_filter_pass`'s inner loop.
- Dispatch: in both emitters the `F.SetExpr` arm becomes: `kept, dropped = M.set_literal_distinct_elements(...)` (14a) first; if `kept is not None` (all canonical): the 14a path; else `self._emit_set_literal(expr)`.
- **`print(set)` stays refused**, with the reason updated in the model (find: `grep -n "will not guess a set" formal/model/*.py`): "a set prints in CPython's hash order, which is not this path's insertion order" (this is the true reason; the old text blamed "missing storage").

## Work order
1. `formal/model/layout.py` (next to the 14a functions): `set_runtime_element_refusal(spelled_elem, kind)`.
2. x86-64 `_emit_set_contains` (new), check with a throwaway direct test via the set operators: the existing `s_union`/`s_inter` rows must still pass.
3. `_emit_set_literal` on both backends + dispatch.
4. `_scan_list_caps` (arm64 `:5303`; find x86's twin with `grep -n "_scan_list_caps" formal/x86_64_codegen.py`): no change needed for literals (cap = n), verify with a row that has 5 elements and 2 distinct values.
5. Tests, `test_formal_container_methods.py` SET_CASES: `s_len_name_dups` (`["x = 7", "s = {x, x, 2}"]`, `len(s)`, CPython 2); `s_walk_name_dups` (sum 9 vs repeats 16); `s_len_mixed_dups` (`["x = 2", "s = {2, x, 3, x}"]`, 3 — mixes a literal and names); `s_in_after_runtime_dedup`; a refusal row for a float element (`s = {1.5, x}`; find how this file spells refusal rows: `grep -n "REFUS\|refuse" test_formal_container_methods.py | head`) and one for a computed-string element (`s = {name_param, "a"}` with a `String` parameter). Update the `print(set)` refusal needle if a test pins the old text (`grep -rn "guess" test_formal_*.py`).
6. Doc status lines.

## Do NOT
- Do not hash. Do not change the blob layout. Do not touch the relocated-comprehension path.
- Do not compare strings with `strcmp` here (that is a different, later capability; refuse instead).
- Do not delete `KNOWN_DIVERGENCES['set_order']` (order did not change; 14e decides it).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_container_methods.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py set_union_names
```
(the second only if such case names exist; otherwise run `test_formal_run.py` once for the `SET_UNION_CASES` group via its case-name filter after `grep -n "SET_UNION_CASES" test_formal_run.py`.)

## Done when
- [ ] `{x, x, 2}` has len 2 and a walk sums 9 (x=7), on both backends, vs CPython
- [ ] the float and computed-string refusal rows pass
- [ ] existing `s_union*`/`s_inter*` rows still pass on both backends

## If stuck
If the register discipline in `_emit_set_literal` cannot be made to hold on one backend, land the model half (refusal text, `_emit_set_contains` x86 twin with a test through `|`), keep the literal path refusing non-canonical elements with `set_runtime_element_refusal`, and write the failing register conflict into the doc Status. Stop.
