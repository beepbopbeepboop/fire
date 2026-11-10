# PYTHON3.15_mro_not_supported

## Symptom
`__mro__` attribute access fails at runtime:
```
Unhandled exception: AttributeError: __mro__
```

## Repro
```python
class A:
    pass
class B(A):
    pass
print(B.__mro__)
```

## Source (CPython 3.15.2)
- Objects/typeobject.c (__mro__ descriptor)
- Python 3.15 allows `except <expr>` where `<expr>` can be a ternary

## Status
Open. Need to implement `__mro__` attribute on classes.