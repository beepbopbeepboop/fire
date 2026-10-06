# `len` over a string literal: the length is a byte count the image stores
# next to the characters, so the call is a load and an add rather than
# arithmetic. (`a + b` on two strings is REFUSED on this path -- `+` would be
# integer arithmetic on two addresses -- so the corpus pins the length read and
# not the concatenation.)
def str_len(n):
    a = "hello"
    return len(a)
