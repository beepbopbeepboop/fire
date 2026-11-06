# plan/step-20: close out the word-valued MLIR ops (the lowering landed; fix the 3 reds and the stale census)
Class: mid      Size: S      Depends: 15a      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §2.2 ("corrected 2026-10-02", lines ~761-800) and its closing census (line ~837).

## Current state (measured 2026-11-05; the draft step was STALE: the lowering exists)
- The operand-type-driven lowering is IMPLEMENTED: `formal/model/layout.py::MLIR_WORD_ARITH_OPS` (:654), `MLIR_CMP_PRED_OPS` (:688), `mlir_cmp_predicate_op` (:767), `mlir_type_kind` (:695), `mlir_operand_declared_type` (:726); `formal/build.py::_dialect_arith_replacement` (~14640) rewrites `index.add/sub/mul/and/divs/shrs`, `index.cmp[pred=...]`, `pop.neg`, `pop.rem` to `BinaryOp`/`UnaryOp` ONLY when every operand is DECLARED a word. Vector/alias operands (`Self._mlir_type`) stay refused. It is a shared AST rewrite, so both backends get it. Pinned by `test_formal_mlir_precedence.py` row `a_dialect_arithmetic_lowers_when_its_operand_declares_a_word` (line ~620, expected `-5 -3 0 -2\n1 0 1\n`).
- `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_mlir_precedence.py` (9 s, 0.1 GB): **PASS=38 FAIL=2** + the census check FAIL:
  1. `the_classification_covers_the_whole_corpus`: "the corpus has 238 `__mlir_op` sites, not the 259 ... ({'typed-result': 91, 'effect': 75, 'vector': 13, 'elementwise': 24, 'unguarded': 35})". Not a table failure: the stdlib checkout moved (259 -> 238). Test line 1183 hard-codes 259.
  2. `a_missing_local_above_the_dialect_construct_does_not_win` and `..._below_...` (lines 108, 124): program `var v = __mlir_op.`pop.inline_asm`[_type=None, assembly="nop", constraints="",]()` is now refused with a text about "a row stride the source never states" (a multi-index-subscript refusal) instead of containing `is a dialect OPERATION`. A refusal pre-empts the dialect classification: a precedence regression.

## Decisions already made
- Case 2: the pre-empting check must not fire for a subscript whose base is an `__mlir_op.`...`` chain. Locate: the message is the last `return` of the multi-index refusal function in `formal/model/layout.py` (~line 2665; `grep -n "row stride" formal/model/layout.py`; its kind is `MULTI_INDEX_DATA`); find where `formal/build.py` decides to call it for a `SubscriptExpr` (`grep -n "MULTI_INDEX_DATA\|multi_index" formal/build.py | head`); add the guard `M.mlir_dialect_op_name(node) is None` (function at `formal/model/layout.py:1052`, takes the callee node) before the subscript refusal. Do NOT reorder unrelated checks.
- Case 1: the census total is data about the stdlib checkout, not a property of the tables. Replace the hard-coded `259` by the measured total ONLY in the failure message path: keep `ok=True` when `fallback == 0` (no site reaches the generic fallback) and print the total; the invariant the test owns is "no site is unclassified". Update the module docstring / comments that say 259 (`test_formal_mlir_precedence.py:196`, `formal/model/layout.py:262,409`) to "259 at the 2026-10-02 measurement; 238 on the 2026-11-05 checkout".
- Do not change any lowering table.

## Work order
1. Fix case 2 (code) then case 1 (test), per above.
2. In `bugs/FORMAL_known_limits.md` §2.2 add a dated Status: "word-valued ops lowered (names the rows); corpus now 238 sites; the vector/mask/alias sites remain refused by class; 9 word-typed sites = what `simd_length.mojo` carries". Do not edit the old paragraphs.
3. Measure which stdlib files this unblocks: `python3 tools/memslot.py --gb 8 --label sl -- python3 fire.py build --formal --no-prove -o .tmp/sl.aout ../modular/mojo/stdlib/std/builtin/simd_length.mojo`; record the terminal message in the Status (an advance to the NEXT construct is the expected, valid result).

## Do NOT
- Do not add a name-keyed table; the operand's declared type decides (`mlir_type_kind == "word"` for EVERY operand).
- Do not touch `mojo/backend_gimple/`.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_mlir_precedence.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_refusal_taxonomy.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] `test_formal_mlir_precedence.py` reports `FAIL=0` and still contains the `index.*` lowering row passing
- [ ] `test_refusal_taxonomy.py` tally unchanged (record before/after)

## If stuck
If the guard changes another case's verdict, write which case and the two messages into §2.2 Status and stop.
