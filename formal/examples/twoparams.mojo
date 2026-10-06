# A TWO-PARAMETER ENTRY POINT. The formal entry convention used to be "one
# argument, in x0": `mojo` was declared `UInt64 -> UInt64`, `eval_eq_mojo` and
# every run test quantified over one `n`, and the startup stub materialized one
# word -- so `def main(n: Int, m: Int)` was a legal PROGRAM (it builds, it runs)
# with no PROOF, refused by `formal/arm64_proof_gen.py::_go_apply` with a
# message naming a one-input apparatus that no longer exists.
#
# This is the smallest program that reaches the widened convention: it calls
# nothing, so the one remaining AST-bridge limit (`MojoExpr.call` carries a
# single argument -- `bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md`)
# is not in its way, and every parameter past the first is exercised: the model
# binds both, `eval_eq_mojo` hands the bridge both, the universal theorem sets
# `x1`, and the run test starts from the same `x1` the startup stub put there.
#
# The second argument is 0 for every built run, because `-n` supplies one value
# per parameter and the default supplies one.  `-n 7,5` builds a binary that
# returns 12; `python3 -c "..."` in the doc of
# `formal/model.py::entry_arg_values` has the command.
def main(n: Int, m: Int) -> Int:
    return n + m