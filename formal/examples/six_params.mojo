# A SIX-PARAMETER entry. Past the register argument file, so the last two
# arguments arrive on the stack, and the frame layout has to agree with the
# model's binding of all six. `model.entry_arg_values` pads the startup stub's
# one supplied value with five ZEROS -- the `0` both architectures' `init`
# constructors leave in the argument registers past the first -- so the run
# test crosses the whole six-argument frame rather than a call site inside it.
def six(a, b, c, d, e, f):
    return a + b + c + d + e + f
