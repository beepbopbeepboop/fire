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

## Status (2026-11-12) — partial fix landed

**Landed:** the two `_alloc_<Struct>` / closure-env allocator definitions
now put the tag in declaration-specifier position:
`mojo/backend_gimple/module_gen.py` — the struct helper
(`__GIMPLE static <S> * _alloc_<S> (void)`, was `static <S> * __GIMPLE _alloc_<S>`)
and the closure env helper (`__GIMPLE <E> * _alloc_<E> (void)`).
Measured with `gcc-mp-15 -fgimple -fsyntax-only`: the tag-first spelling
makes gcc GIMPLE-parse the body (a `&local` / cast-heavy body is now checked),
and the emitter's own `_alloc_` body shape parses clean under it. Prototypes
are plain C and match either spelling, so they are unchanged.

**Pinned by:** `test_gimple.py`, `alloc_helper_tag_in_declaration_specifier_position`
(header spelling; fails on the old spelling) and
`alloc_helper_body_compiles_as_gimple` (`-x c` strict compile). `test_gimple.py`
442 passed, 0 failed.

**Still open (the rest of the sweep):** every OTHER pointer-returning tagged
function is still tagged after the type:
- `mojo/backend_gimple/emit_funcs.py` ~4961 (`_sig_kw`, struct methods returning
  a pointer) and `mojo/backend_gimple/emit_loops.py` ~3776 (lifted closures) —
  both emit `f"{ret_type} {_sig_kw}{name} (...)"`. For a pointer `ret_type`
  these must become `__GIMPLE {ret_type} {name}`-style, i.e. the tag must be
  moved in front of the return type, not just before the name. Test
  expectations that search for `__GIMPLE Holder_get (` / `__GIMPLE Sub___eq__ (`
  (test_gimple.py ~7141, ~7707; test_dispatch_phase_c.py ~109;
  test_generic_struct_local_linked_list.py ~184) must be updated with the move.
- Each newly-GIMPLE-checked pointer-returning body may then be rejected by the
  strict grammar (`sizeof`, inline casts, `&local`, `t = G + 1` on pointer
  paths). Those need fixing or splitting into an untagged helper, as the setjmp
  bodies already are. This is the sweep: it needs the stdlib compile
  (`compile_stdlib.py`) and a whole-closure compile to enumerate, and was not
  run here (light-worker budget).

## Done when

`python3 tools/memslot.py --gb 8 --label x -- python3 test_gimple.py` passes
with the `emit_funcs.py` / `emit_loops.py` method and closure tags also moved
in front of the return type, the stdlib compile (`compile_stdlib.py`) shows no
new `U` failures and no new `skip` modules, and `gimplerunner` shows no new
GIMPLE rejections. Then delete this doc (`git rm`) and run
`python3 tools/dangling_doc_refs.py --ratchet` in the same commit.
