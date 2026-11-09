# BUILD_symbol_collisions_150_modules

## Summary
fire fails on 121 files with:
```
(150 modules excluded for symbol collisions)
```

## Source (CPython 3.15.2)
- Various modules with transitive imports causing symbol name collisions.

## Status
Open. Need to handle symbol collisions in multi-module builds.