# plan/step-20: lowering the word-valued elementwise MLIR dialect operations

**Source:** `bugs/FORMAL_known_limits.md` §2.2 correction (26 of the 38
elementwise sites have a vector operand, 9 have a word operand, 3 are pointer
arithmetic).
**Master plan:** `doc/finish-formal.md` §"Step 20".

## Goal

Of the 259 `__mlir_op` sites, 9 have a word-typed operand and are elementwise
arithmetic. **The operation NAME does not decide whether the result is a word —
the operand's type does.** A lowering keyed on the name is right for the 9
word-typed sites and wrong for the 26 vector-typed ones (it would compute a
scalar add of two vector-typed words — a plausible number rather than a
refusal). `std/builtin/simd_length.mojo`'s six `index.*` operations are among
the only 9 word-typed sites and are the natural first target.

## What to add

- An operand-type-driven lowering for the word-typed elementwise operations
  (`pop.add`/`sub`/`mul`/`and`/`divs`/`shrs` on word operands).
- The vector/mask cases still refused by class.
- Keep the classification table arch-free in `formal/model/`.
- Extend `test_formal_mlir_precedence.py`'s `CLASSIFIED` rows so each class's
  words are asserted and another class's are absent.

## Structure-only rule

Do not add a name-keyed table; the whole correction is that the operand's type
decides. The effect class stays as it is (a trap used as a statement already
lowers; `return __mlir_op...trap()` is still refused).

## Files

`formal/model/` (dialect tables), `formal/build.py`, both codegens,
`test_formal_mlir_precedence.py`.

## Verification

`test_formal_mlir_precedence.py` (including
`the_classification_covers_the_whole_corpus`); a differential row for a
word-typed site on both backends.

## Done when

- [ ] the 9 word-typed sites lower or refuse with the missing fact named
- [ ] the vector sites still refuse
- [ ] the classification covers the corpus

## Dependencies

step-01 (holes only). Independent.
