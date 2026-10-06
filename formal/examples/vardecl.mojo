# `var a = 1` is a `VarDecl`, and the semantic model used to read one as a
# statement whose value is 0 -- so the whole function was modelled as 0 and
# every proved program with a local failed.  The bare-assignment spelling
# (`threevar.mojo`) covered the same arithmetic and passed, which is why this
# one-token difference went unseen.  Three declarations, the second ANNOTATED,
# and the third reading the first: a model that binds the name to zero fails
# each of those independently.
def vardecl(n):
    var a = 1
    var b: Int = a + n
    var c = b + a
    return c
