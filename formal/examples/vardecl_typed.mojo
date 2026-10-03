# The TYPED twin of `vardecl.mojo`, and the reason it is a separate example:
# a function is "typed" when a variable or the return type is not the default
# `Int64`, and a typed function is modelled by `_stmts_go_t` — a different
# dispatcher, which had the same `VarDecl` omission in the same place and would
# have kept it after the untyped one was fixed.  The annotation is `Int8`, so
# the declaration's value is carried at the DECLARED type's 64-bit
# representation rather than as a bare word.
def vardecl_typed(n: Int8) -> Int8:
    var a: Int8 = 3
    var b = a + n
    return b
