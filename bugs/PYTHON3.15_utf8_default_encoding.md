# PYTHON3.15: UTF-8 as default encoding

## Symptom
Python 3.15 makes UTF-8 the default encoding (PEP 686). Our compiler's default file encoding must be UTF-8.

## Source (CPython 3.15.2)
- Init config: Python/initconfig.c (default encoding)
- Codecs: Python/codecs.c
- Spec: PEP 686 (Make UTF-8 mode default)

## Status
Open.
