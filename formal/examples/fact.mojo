# SPECIFICATION REFINEMENT.  Every other theorem this build emits compares the
# machine with the generator's OWN model of this source, so all of them are
# self-consistency theorems: code and model are two readings of this file.
# The `@refines` annotation below asks for the stronger claim -- that the
# machine computes the HAND-WRITTEN specification of `n!` — 20 is the widest range a word holds exactly in
# `lib/Specs.lean`, which is defined over Lean's own Nat and has no
# reference to this file, to `mojo`, or to `ProofLib`'s machine model.  It
# produces `main_refines_spec`, and the range is the author's because a word
# reading is `UInt64.ofNat` of a mathematical value and the equation is false
# wherever that value does not fit in a word.
@refines(Specs.factorial64; 20)
@spec(fact_spec; fact_spec 0 = 1; fact_spec (n+1) = (n+1) * fact_spec n)
# THE RANGE IS THE SAME 20 `@refines` CLAIMS, and the precondition has to say so
# rather than the postcondition having to be weakened.  `@ensure(result >= 0)`
# is FALSE over `UInt64` arithmetic -- 21! is 51090942171709440000 and
# 51090942171709440000 - 2**64 = -4249290049419214848 read as a signed 64-bit
# integer -- and a corpus file that promises something false is worse than one
# that promises nothing, because nothing reported it for as long as the
# decorator existed: both emitters ignored `FunctionDef.decorators` entirely, so
# the promise sat in this source unread until `formal/contracts.py` started
# reading it.  Nothing below is a claim this file can check about itself.
#
# `n <= 20` is the widest `n` for which `n!` FITS in a word, which is exactly the
# statement `@refines(Specs.factorial64; 20)` already makes, so the precondition
# and the specification now agree instead of the specification being the only
# one that knows about the boundary.  `n >= 0` stays: it is what makes `n == 0`
# the base case, and dropping it would change the function's own meaning.
#
# The bounded search now reports UNKNOWN rather than REFUTED, which is the
# honest answer and is the same one this corpus's other three contract files
# already give: the ladder does not close `fact`'s goal over `UInt64` arithmetic.
# It is not a pass, and the rows that keep the DETECTOR honest are
# `test_formal_contracts.py`'s `loop_wrong`, `wrong_clampv` and
# `test_the_fact_contract_is_refuted` — each refutes a clause of its own, so
# "a false promise is reported" does not rest on this file.
@require(n >= 0 and n <= 20)
@ensure(result >= 0)
def fact(n):
    if n == 0:
        return 1
    else:
        return n * fact(n - 1)
