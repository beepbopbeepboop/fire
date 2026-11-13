# CODEGEN: a float arm beside an ANNOTATED pointer return is truncated, not widened

Status: OPEN (design decision). Filed 2026-11-12, carried over from the
deleted `CODEGEN_mixed_return_tagged_word_untouched_container_ops.md`: its
container-operation part is fixed, and this was the "also still open" part
that fix deliberately did not touch. Two adjacent bugs were fixed earlier by
carrying a mixed return as a tagged word (`2026-11-12` commits around
`test_float_return_beside_tuple_return.py`); an INFERRED float+pointer join
now widens, an ANNOTATED one does not.

## What happens (measured on this tree)

```python
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return 2.5
```

The `-> String` annotation fixes the C return type at `char *`, so
`_infer_return_type_core` does not widen this body and `_gen_stmt_ReturnStmt`
keeps the old `(int64_t)<double>` -> pointer coercion for the float arm. It
compiles, but truncates: the caller receives pointer `1` and `print(pick(0))`
prints `1` where CPython prints `1.5` (and one debug read of the "string"
would be a wild pointer). This is pinned as the currently-compilable spelling
by `test_float_into_pointer_return_regression.py`.

The inferred (unannotated) shape is the one the tagged-word fix covers:

```python
def pick(x: Int):
    if x == 1:
        return "one"
    return 2.5
```

## The decision this needs

Real Mojo's annotation decides the type, so a `-> String` body that returns a
float is arguably a type error, not something to widen. But silently
truncating to a pointer is not a defensible third option. The two coherent
answers:

1. **The annotation wins.** A float (or any non-pointer) arm in a body whose
   annotation fixes a pointer type is a compile-time diagnostic naming the
   function and the arm. This matches a static type system and keeps
   `_infer_return_type_core`'s annotation precedence untouched. Cost: source
   that compiles today (the pinned test) starts failing, so this needs the
   diagnostic to be precise, and the pinned test becomes an
   `assertRaises`-style check of the message.
2. **The tagged-word widening overrides a contradicted pointer annotation.**
   When the observed arms prove the annotation wrong (a float beside the
   declared pointer), treat the body like the inferred mixed case: return the
   tagged word, box every arm by kind, and let callers dispatch (which is now
   complete for print/repr, arithmetic, `in`, subscript, `len`, list methods,
   `is None`, `isinstance`). Cost: an annotation stops being authoritative
   exactly when it is contradicted, which can surprise a reader; and the
   annotation would have to be dropped from the C signature (the erased
   `int64_t` return is what the whole tagged-word model uses).

This is a semantics call, not a mechanical change, so it needs an explicit
decision before code moves.

## Exact next step

Pick option 1 or 2 above, then:

1. `infra_infer._infer_return_type_core` / `_gen_stmt_ReturnStmt`: for
   option 1, raise the diagnostic where an annotated pointer return meets a
   non-pointer arm (reuse the reflection helpers that already classify a
   `double`/`float` arm); for option 2, let the float-beside-pointer join win
   over a contradicted pointer annotation and record the body in
   `gen._float_mixed_return_bodies` exactly as the inferred case does.
2. Update `test_float_into_pointer_return_regression.py` to pin the chosen
   answer (the diagnostic text, or a CPython-stdout comparison for `1.5`).
3. Add the case to `test_float_return_beside_tuple_return.py` if option 2, so
   it is compared against CPython like its siblings.
