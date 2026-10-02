# FORMAL_x86_64_tuple_target_subscript_element_refused: one program, two answers, and the doc that recorded it was deleted with its fix

**Status: OPEN, one row, measured on the merged tree 2026-10-02. arm64 answers
`a[0], b = 1, 2` correctly; x86-64 refuses it by node type.** This file exists
because `bugs/FORMAL_tuple_store_target_shapes.md` — which held the only record
of it — was deleted on `master` by `830955f5` with the fix for the OTHER item in
it, and the deletion was correct for the half that was fixed and lossy for the
half that was not.

## What I ran

`fire.py build --formal --no-prove` on one program, on both backends, then run
the image. (The probe is `.tmp/probe_tuple_subscript.py` in the worktree that
ran it; nothing in `bugs/` or a test file names this shape.)

    def main(n: Int) -> Int:
        var a = [0]
        var b = 0
        a[0], b = 1, 2
        printf("a0=%d b=%d", a[0], b)
        return 0

## What I saw

| backend | answer |
|---|---|
| arm64 | **built**, rc 0, `a0=1 b=2` — CPython's answer for the same text |
| x86-64 | **refused**: `build: tuple assignment targets must be plain names or fields on the formal x86-64 path (got SubscriptExpr)` |

The control — the same subscript store WITHOUT the tuple, `a[0] = 1` — builds
and answers `a0=1` on both. So this is not "a subscript store is unsupported":
it is the SUBSCRIPT as a tuple-store TARGET specifically, and only on x86-64.

## What this doc replaces, and why the old one had to go

`bugs/FORMAL_tuple_store_target_shapes.md` recorded the `MemberExpr` half of
the same table, which `work/formal3-8-r2` fixed with
`formal/x86_64_codegen.py::_tuple_target_key` (one table, three shapes: a name,
a frame-slot key, a nested list of either). `830955f5` on `master` then closed
the other half it recorded — the `_STORE_TUPLE` band-aid in
`model.struct_field_assigned_type`, which existed only because
`init_body_stores` could not inline an `__init__` whose body is a tuple store —
and CLAUDE.md says a doc for a fully fixed bug is deleted rather than left with
a Status history. So the deletion stands and this file takes over the one item
that was still open in it.

## Where the remaining gap is, exactly

`formal/x86_64_codegen.py::_tuple_target_key` ends with:

    raise CodegenError(
        "tuple assignment targets must be plain names or fields on the "
        f"formal x86-64 path (got {type(el).__name__})")

arm64's `_tup_slot` / `_store_tup_slot` has no such clause — its third answer
covers the shape. So the x86-64 answer is a bare `raise` with no model behind
it, which is the shape of a gap rather than the shape of a decision.

**One thing the old doc said about this is now FALSE, and it is worth recording
why.** It read "a subscript element target (`a[0], b = 1, 2`) is still refused
on x86-64, and it SIGSEGVs on arm64". The SIGSEGV half is gone: arm64 builds
and answers correctly, measured above. Anyone who went looking for a crash on
arm64 will not find one, and reading that sentence as current would send them
past the bug that is there.

## Exact next step

Give `_tuple_target_key` a SUBSCRIPT answer on x86-64 — a base-plus-offset key
the existing `_store_var` can store into, or, if the list blob's frame home
cannot be named for an arbitrary base, the same `model.field_access_refusal`
route the `MemberExpr` arm already uses so the two architectures' sentences
match. Then add the case to `test_formal_value_model.py`'s `TUPLE_STORE_CASES`
(as a `FIXED_CASES` row, since it prints and answers on both backends) rather
than to `test_formal_x86_64_parity.py`'s `X86_ONLY_REFUSALS`: that group pins
per-platform limits that are CORRECT for their platform, and this one is not —
arm64 already answers the program, so a row there would pin a wrong answer as
though it were the agreed one. Nothing in the suite currently exercises a
subscript as a tuple target, which is why the divergence survived every merge
that touched either half of the table.

## What was NOT re-measured

Only the two programs above, on this tree, at merge time (`5842c47c` plus this
merge). Nothing here re-checks the `MemberExpr`, nested-group, or
construction-inline shapes; those are the closed half and their tests are
`test_formal_value_model.py`'s `TUPLE_STORE_CASES` and
`test_formal_x86_64_parity.py`'s `a_tuple_target_in_a_constructor_body_is_refused_identically`.
