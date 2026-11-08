# PYTHON3.15_py_warnings_syntax_error

## Summary
fire fails to parse `_py_warnings.py` at line 392:
```
Error building: /Users/mrs/net/Python-3.15.2/Lib/_py_warnings.py:392:23: Expected COLON got KW('if')
```

## Source (CPython 3.15.2)
- Lib/_py_warnings.py:392

## Status
Open. Investigate parser issue with conditional expression in this context.