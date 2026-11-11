# CODEGEN_class_rebind_late_binding

## Summary
fire refuses to compile a class whose method reads a parameter that the enclosing function rebinds:
```
method `finish_request` of class `DualStackServerMixin` reads `args`, a parameter or local of `_main`, which declares the class, and reads `args`, which the enclosing function rebinds, so a snapshot taken at the class statement could differ from Python's late binding
```

## Source (CPython 3.15.2)
- Lib/socketserver.py (DualStackServerMixin)

## Status
Open. Need to handle late binding correctly.