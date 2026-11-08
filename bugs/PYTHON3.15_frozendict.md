# PYTHON3.15: `frozendict` builtin type

## Symptom
Python 3.15 adds `frozendict` as a builtin. Our compiler must support it as a type.

## Feature
Immutable dict variant. Needs type registration, literals, methods.

## Source (CPython 3.15.2)
- Implementation: Objects/dictobject.c (frozendict_new, PyFrozenDict_Type, frozendict_does_not_support)
- Registration: Python/bltinmodule.c
- Header: Include/cpython/dictobject.h, Include/internal/pycore_dict.h

## Status
Open.
