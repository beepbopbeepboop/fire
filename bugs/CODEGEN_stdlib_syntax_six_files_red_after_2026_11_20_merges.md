# CODEGEN: stdlib-syntax is red on six files (found 2026-11-20)

`python3 tools/suite.py stdlib-syntax` reports `FAILED: 6 (0 expected, 6 unexpected)`,
`PASSED: 604`. The six files compile on the tree before the 2026-11-20 upstream merges
(605 commits). It is NOT caused by the 2026-11-20 int-or-None return rule: with
`infra_infer._return_arms_are_int_or_none` forced to return False, `std/math/math.mojo`
and `test/builtin/test_sort.mojo` fail identically.

## The six files and the first error

    std/math/math.mojo           codegen: gcc -c failed for the monomorphized
                                 _ldexp_impl_5_dtype_7_Float32_5_width_1_1 (exit 1, 3 attempts)
    test/math/test_exp.mojo      the same, with ..._Float64_5_width_1_1
    test/math/test_ldexp.mojo    (same family; read its message)
    test/math/test_math.mojo     (same family; read its message)
    test/builtin/test_sort.mojo  gcc: test_sort.mojo:73:8: error: assignment to 'char *' from ...
    test/math/test_tanh.mojo     gcc: test_tanh.mojo:200:8: error: assignment to 'char *' from ...

Two families: a monomorphized `_ldexp_impl[dtype, width]` that gcc rejects, and an assignment
into a `char *` of a value of another type (look at the line named in the message).

## How to reproduce one file in about 20 s

    cat > /tmp/one.py <<'PY'
    import sys
    sys.path.insert(0, '.')
    from pathlib import Path
    import compile_stdlib as C
    base = Path(C.get_stdlib_path())
    for rel in sys.argv[1:]:
        r = C.transpile_file(base / rel)
        print(rel, r[0], str(r[1])[:300])
    PY
    GMOJO_HOME=$(mktemp -d) python3 /tmp/one.py test/builtin/test_sort.mojo

(`GMOJO_HOME` set to an empty directory matters: the codegen cache can hide a regression.)

## Bisect result (2026-11-20)

`git bisect` between `965c87598` (good) and the tree of that day: the first bad commit for
`test/builtin/test_sort.mojo` is `d17488051` "codegen: project List elements so Span helper
calls elaborate" (`mojo/backend_gimple/emit_resolve.py`, +305/-76; it also changed
`elaborate.py` and `gimple_codegen.py`). Not bisected: whether the `_ldexp_impl`
monomorphization failures (`std/math/math.mojo`, `test_exp`, `test_ldexp`, `test_math`) come from
the same commit; check them with the repro above at `d17488051^` and `d17488051`.

## Next step

Read that commit's change to `emit_resolve.py` for the code that assigns a projected List
element into a `char *` (line 73 of `test_sort.mojo`), fix it so the assigned value is cast or
typed as the destination, rerun the six files, and delete this doc in the same commit.
