# PYTHON3.15: `sentinel` builtin

## Symptom
Python 3.15 adds `sentinel` builtin for creating unique sentinel values.

## Feature
`sentinel("name")` creates a unique sentinel. Used for default argument markers.

## Source (CPython 3.15.2)
- Registration: Python/bltinmodule.c (sentinel builtin)
- Objects: Objects/sentinelobject.c (if exists) or Objects/object.c
- Spec: PEP 661 (sentinel values)

## Status
Open.
