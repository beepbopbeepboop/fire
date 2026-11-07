# PYTHON3.15: `lazy` soft keyword for lazy imports (PEP 810)

## Symptom
Python 3.15 introduces `lazy import` and `lazy from ... import` for deferred module loading. Our compiler (Mojo superset of Python) must support this syntax.

## Feature
```python
lazy import json
lazy from pathlib import Path
```
- Only at module scope; SyntaxError inside functions/classes/try blocks.
- `lazy from module import *` and `lazy from __future__ import ...` raise SyntaxError.
- `__lazy_modules__` attribute for older-version compat.
- `sys.set_lazy_imports`, `sys.get_lazy_imports`, `sys.set_lazy_imports_filter`.
- `types.LazyImportType`.

## Status
Open. Need to add `lazy` keyword to lexer/parser and implement lazy import semantics.
EOF