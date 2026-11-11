# CODEGEN: an enum member comparison prints 1 where CPython prints True

Found 2026-11-10 by the estate audit: `test_enum_desugar.py` fails on master.

## Measured
The test's `methods_aliases_functions_and_errors` case. Its last printed line:

    compiled : Color.GREEN Color.GREEN 1
    CPython  : Color.GREEN Color.GREEN True

The comparison's result is printed as an integer word, so the compiled path loses the `bool` type of the
comparison result.

## Next step
Find the enum-member comparison lowering (`_lower_compare` for enum members) and give its result the `_Bool`
type. Add a regression case to `test_enum_desugar.py` that prints the comparison alone. Delete this doc in the
commit that fixes it.
