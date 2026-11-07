# PYTHON3.15: `__lazy_modules__` attribute

## Symptom
Module-level `__lazy_modules__` list makes regular imports lazy. Compat for older Python.

## Feature
```python
__lazy_modules__ = ["json", "pathlib"]
import json  # lazy
```

## Status
Open.
EOF