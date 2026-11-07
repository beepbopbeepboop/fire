# PYTHON3.15: support new features from Python 3.15

## Symptom
Python 3.15 (released 2026-10-09) introduced several language and stdlib features. Our compiler (Mojo-compatible) should support them. Source: /Users/mrs/net/Python-3.15.2/Doc/whatsnew/3.15.rst.

## New language features to verify
1. `lazy` soft keyword for lazy imports (PEP 810): `lazy import x`, `lazy from x import y`. Only at module scope. `__lazy_modules__` attribute. `sys.set_lazy_imports`, `sys.get_lazy_imports`, `sys.set_lazy_imports_filter`. `types.LazyImportType`.
2. `frozendict` builtin type.
3. `sentinel` builtin (PEP 750? or 3.15 sentinel).
4. UTF-8 as default encoding (PEP 540/686).
5. Unpacking in comprehensions: `{*a, *b}` in set/dict comprehensions.
6. `__lazy_modules__` attribute for module-level lazy imports.
7. TypedDict with typed extra items (PEP 728).
8. TypeForm (PEP 788?).
9. Disjoint bases in type system (PEP 800).
10. PyBytesWriter (PEP 788?).
11. Stable ABI for free-threaded builds (PEP 703/abi3t).
12. Improved error messages.
13. Profiling package (Tachyon).

## Action
- Build a test harness: compile/run small programs exercising each feature with our compiler.
- File individual bug reports for each unsupported feature.
- Check all *.py files in the repo compile.

## Notes
- Our compiler targets Mojo, which is Python-compatible. Python 3.15 features that are pure language syntax need support in fire_compiler.py (parser) and codegen.
- stdlib changes (frozendict, sentinel, profiling) need stdlib updates (but stdlib is read-only upstream; fixes go in compiler).
- Source tree available at /Users/mrs/net/Python-3.15.2.
EOF