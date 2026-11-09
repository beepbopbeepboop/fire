# PYTHON3.15: `__lazy_modules__` attribute

## Symptom
Module-level `__lazy_modules__` list makes regular imports lazy. Compat for older Python.

## Feature
```python
__lazy_modules__ = ["json", "pathlib"]
import json  # lazy
```

## Source (CPython 3.15.2)
- Import system: Python/import.c, Python/importlib (Lib/importlib)
- Module attrs: Objects/moduleobject.c

## Status
Open.
