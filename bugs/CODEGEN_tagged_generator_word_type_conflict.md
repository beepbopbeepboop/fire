# CODEGEN_tagged_generator_word_type_conflict

## Summary
fire refuses to compile when a name bound to a tagged generator word (a yield of more than one kind) also holds a value of another C type:
```
'prevname': a name bound to a tagged generator word (a yield of more than one kind) cannot also hold a value of another C type (str or float): the box cannot carry it; refused
```

## Source (CPython 3.15.2)
- Lib/ (generator-heavy modules)

## Status
Open. Need to allow tagged generator words to coexist with other types.