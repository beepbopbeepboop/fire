# A narrow ANNOTATED local in arithmetic with an unannotated one: the add has
# to widen one operand, and the model has to agree with the image about which
# width the result has.
def mixed_width(n):
    a: Int32 = 3
    b = a * n
    return b & 255
