# `-x` on a VARIABLE, which is the one spelling that makes the emitter write a
# `NEG Xd, Xn` — `formal/arm64_codegen.py`'s unary-minus arm emits
# `encode_neg_xd_xn(0, 0)`, and `NEG Xd, Xn` is `SUB Xd, XZR, Xn`, so the word
# carries `Rn = 31`.  Nothing else in this directory had one: every other
# `-` here has a LITERAL operand, and the emitter folds `-7` into the constant,
# so the arm never ran and the arm64 machine model's reading of `Rn = 31` in the
# SUB-register branch was never contradicted by a proof in the corpus.
#
# That reading is the defect `bugs/FORMAL_arm64_neg_is_shadowed_by_the_sub_
# register_arm.md` names: the branch read `arm64_reg_or_sp 31 s`, so the model
# computed `sp - x` for an instruction whose result is `-x`.  The generator's own
# `_step_rhs` always said `arm64_reg 31 s`, so the step-result lemma for this
# word could not be closed by `exact`-ing the library's — the two disagreed about
# the same word.  The example exists so that word is in the PROVING corpus: an
# instruction nothing proves is an instruction nothing catches.
def neg(n):
    return -n