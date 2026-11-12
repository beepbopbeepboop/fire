# IMPORT_ambiguous_sibling_function

## Summary
fire fails when a program transitively imports two different sibling modules that both define a free function with the same name:
```
'get_pager' is ambiguous — this program transitively imports two different sibling modules that both define a free function named 'get_pager', each from a different lexical scope, and no enclosing `from ... import` resolves the ambiguity
```

## Source (CPython 3.15.2)
- Lib/ (modules with get_pager)

## Status
Open. Need to resolve import ambiguity by lexical scope.