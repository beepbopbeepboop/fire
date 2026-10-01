# CODEGEN_boxed_method_name_list_set_ambiguity: `.remove()`/`.clear()` on a boxed handle guesses list-vs-set by priority order alone

## Status (2026-09-13 — FIXED same day)

`_lower_method_call` (gimple_gen_methods.py, ~line 2469) now special-cases
`remove`/`clear` BEFORE the static method-name routing: it unboxes the
`int64_t` handle once, then runtime-dispatches via
`mojo_is_registered_dict`/`mojo_is_registered_set` (falling back to list)
before calling the matching `mojo_dict_clear`/`mojo_set_clear`/
`mojo_list_clear`, or `mojo_set_discard`/`mojo_list_remove_str`/
`mojo_list_remove_int` for `remove`. Verified with an isolated compile
(`x.remove(1)` / `y.clear()` / `z.remove("a")` on unannotated params) and
against `std/builtin/simd.mojo`; `test_no_new_container_casts.py` count
unchanged (no new ad-hoc casts introduced — the new casts all route
through `gen._coerce_to_type`).

## Status (2026-09-13 — found during DESIGN.html R1/R5 follow-up, NOT fixed)

`gimple_gen_methods.py`'s "Opaque int → coerce to appropriate container
type FIRST" block (`_lower_method_call`, ~line 2471) unboxes a genuinely
ambiguous `int64_t`-boxed receiver by METHOD NAME alone:

```python
if method in ('keys', 'values', 'items', 'get', 'update'):
    ...  # -> MojoDict *
elif method in ('append', 'extend', 'sort', 'reverse', 'clear'):
    ...  # -> MojoList *
elif method in ('add', 'discard', 'remove'):
    ...  # -> MojoSet *
```

This is a real, structural gap, not a contrived one: `.remove(x)` is a
real method on BOTH `list` and `set` in Python (`list.remove` removes by
value; `set.remove` removes an element) — this dispatcher always
resolves it to `MojoSet *`, so `some_boxed_list.remove(x)` on a value
whose real kind is `list` (not `set`) reinterprets the list header as a
`MojoSet *` and calls `mojo_set_discard`-family runtime functions on it.
`.clear()` is real on `list`, `dict`, AND `set` simultaneously — this
dispatcher always resolves it to `MojoList *`, so a boxed dict/set with
`.clear()` called gets the wrong runtime function too.

This differs from the OTHER bugs fixed this session (`all()`/`any()`/
`sum()`/etc., see `bugs/CODEGEN_all_any_dict_set_miscompile.md`): those
had a `_materialize_as_list`-shaped fix (produce a `MojoList *` view
regardless of source kind). This one is a METHOD-CALL dispatch ambiguity
— there is no single "give me a list view" operation that resolves it;
the runtime function to call genuinely differs by the receiver's real
kind (`mojo_list_remove_*` vs `mojo_set_discard`, `mojo_list_clear` vs
`mojo_dict_clear` vs `mojo_set_clear`), so fixing it needs a
`mojo_is_registered_list`/`_dict`/`_set` runtime guard at the CALL site
choosing which runtime function to invoke — a 3-way branch per affected
method name, not a single shared helper like `_materialize_as_list`.

**Not fixed in this pass**: no concrete failing repro was constructed
(unlike the other 8 fixes this session, each verified via an isolated
compile) — this needs a real reproduction of a boxed (not statically-
typed) list/dict/set value reaching this exact dispatcher with an
ambiguous method name, then the 3-way runtime-guard rewrite, verified
against `compile_stdlib.py` before/after.

## Suggested fix

For each ambiguous method name (`remove`, `clear`, and any other
list/dict/set method-name collision), emit a `mojo_is_registered_list`/
`_dict`/`_set` runtime check before dispatch, choosing the matching
runtime function per branch — mirroring the existing dict-vs-list
runtime dispatch already used in `_gen_for_iter` (`gimple_gen_loops.py`)
and `DelStmt` subscript handling (`gimple_gen_stmts.py`).
