# Regression for bug CODEGEN_the_gimple_match_lowering_drops_the_capture...
# Rows from the bug doc: case v: (capture), case 1, other: (short-circuit +
# capture), structural refusal (sequence pattern).

def main():
    # Row 1: bare capture must bind subject (not read undeclared v)
    n = 7
    match n:
        case v:
            print('cap', v)
        case _:
            print('rest')
    # Row 2: pattern list must stop at first match; capture binds
    n2 = 5
    match n2:
        case 1, other:
            print('low', other)
        case _:
            print('rest')
    return 0

main()
