# The row that says the declaration POISONED the model rather than mis-answering
# one read: this function's answer does not depend on `a` at all, and it still
# failed before -- with TWELVE errors rather than six, because `_stmts_go` is a
# fold and the 0 the declaration was read as became what the rest of the
# function was evaluated from.
def vardecl_unused(n):
    var a = 1
    return 2
