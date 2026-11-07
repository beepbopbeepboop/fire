# PYTHON3.15: unpacking in comprehensions

## Symptom
Python 3.15 allows unpacking in set/dict comprehensions: `{*a, *b}`, `{**d1, **d2}`.

## Feature
```python
{*a, *b}  # set comprehension unpacking
{**d1, **d2}  # dict comprehension unpacking
```

## Status
Open.
EOF