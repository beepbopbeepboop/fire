# PYTHON3.15: stable ABI for free-threaded builds

## Symptom
Python 3.15 provides stable ABI for free-threaded builds (PEP 703). Our compiled extensions must be compatible.

## Source (CPython 3.15.2)
- C API: Include/stable_abi.h, Python/abstract.c
- Free-threaded: Python/ceval.c (GIL handling)

## Status
Open.
