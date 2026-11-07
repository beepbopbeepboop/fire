# PYTHON3.15: unpacking in comprehensions

## Symptom
Python 3.15 allows unpacking in set/dict comprehensions: `{*a, *b}`, `{**d1, **d2}`.

## Feature
```python
{*a, *b}  # set comprehension unpacking
{**d1, **d2}  # dict comprehension unpacking
```

## Source (CPython 3.15.2)
- Parser: Python/ast.c, Python/compile.c (comprehension unpacking)
- Grammar: Grammar/python.gram

## Status
Open.
