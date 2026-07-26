# COMPILE_FAIL: Type Errors in Generated C Code

## Status
**Open** - Generated C code has type errors when Mojo compiles Python.

## Test Reference
Full file: `/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/__future__.py`

## Error from mojo.py
```
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/__future__.py:63:25: error: assignment to 'MojoList *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
   63 | __all__ = ["all_feature_names"] + all_feature_names
```

## Root Cause
The generated C code has a type mismatch. The `+` operator on `MojoList` types is not properly handled, resulting in incorrect C type assignments.

## Python Syntax
```python
__all__ = ["all_feature_names"] + all_feature_names
```

This is list concatenation, which should work correctly in Mojo.

## Impact
Affects files using list operations.

## Files Affected
- __future__.py

## Python Spec
List concatenation is standard Python syntax.

## Related Issues
- [ ] Code generation for list operations
- [ ] Type handling in generated C code

