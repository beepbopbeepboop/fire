# CODEGEN_gimple_tag_ignored_on_pointer_return

## Summary
The backend emits a function's `__GIMPLE` tag AFTER its return type
(`<ret> __GIMPLE <name> (...)`). gcc accepts that spelling for a scalar or
`void` return and parses the body with the strict GIMPLE grammar, but for a
POINTER return type the tag lands in the declarator (it behaves like a type
qualifier on the `*`), is silently ignored, and the body is compiled as
ordinary C with no GIMPLE parsing or checking.

Every `static <T> * __GIMPLE _alloc_<T> (void)` in the generated C
(`module_gen.py` ~17646 and ~3034) is therefore NOT GIMPLE-checked, and
neither is any pointer-returning method or lifted closure.

## Measured (2026-11-11, /opt/local/bin/gcc-mp-15, `-fgimple -fsyntax-only`)
Body marker: `int x; int64_t *p; p = &x;` — `&<variable>` is rejected by the
strict GIMPLE grammar.

| signature | result |
|---|---|
| `int64_t __GIMPLE f (void)` | error: expected expression before '&' token (GIMPLE-parsed) |
| `void __GIMPLE f (void)` | same error (GIMPLE-parsed) |
| `C * __GIMPLE f (void)` | no error (NOT parsed) |
| `int64_t * __GIMPLE f (void)` | no error (NOT parsed) |
| `__GIMPLE static C * f (void)` | GIMPLE-parsed: rejects `&x`, and `(C *) 0` in a `return` |

Second witness, independent of address-of: `t = G + 1;` in a tagged body
ICE's the gimple parser (`internal compiler error: in build2, at tree.cc:5208`)
when the return type is `int64_t`, and does not ICE at all when it is `C *`.

The tree's own `_alloc_C`-style shape is `static C * __GIMPLE _alloc_C (void)`,
so it is in the NOT-parsed class.

## Impact
A class of verification the tree believes it has is absent: `sizeof(T)`,
inline casts, and pointer arithmetic inside `_alloc_*` bodies are exactly the
constructs the GIMPLE grammar rejects, and none of them is checked there.
It also hides bugs from tests that only exercise pointer-returning methods
(observed while pinning `CODEGEN_method_nested_class_capture_address_of_global`:
the same class statement in a method that returns `C *` compiles fine, while
the identical method returning `int64_t` failed with "expected expression
before '(' token").

## Next step
Move the tag to declaration-specifier position for every tagged definition:
`__GIMPLE static <ret> <name> (...)`. `__GIMPLE static C * f (void)` was
measured to be parsed (see table), so this is the spelling that works for both
scalar and pointer returns. Then:
1. `grep -c ' \* __GIMPLE '` on one generated `.ci` to count the functions
   this newly subjects to GIMPLE parsing;
2. fix or split (into an untagged helper, as the setjmp bodies already are)
   each body that the strict grammar rejects;
3. run `gimplerunner` and one whole-closure compile to collect the
   diagnostics — this is a real sweep, not a one-line change.
