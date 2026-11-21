# COMPTIME: a module-level `if` on a non-numeric constant folds to the else arm

Found 2026-11-20 while fixing the float augmented-assignment truncation:
the doc's `if 0.0001:` was checked inside `main()`, and the function-scope
condition needed an `_ensure_bool_cond` fix. Checking the same statement at
module scope exposed this second, independent path: the compile-time folder
decides the branch before any condition is emitted.

## Repro

`if "x":`, `if [1]:`, `if {1: 2}:` each print `no` in the compiled binary and
`yes` in CPython. `if "":` is correct (`no`) because the wrong answer happens
to be the right one for an empty value. A nonzero float literal was the same
bug and was fixed on 2026-11-20 by accepting `float` in `eval_const_bool`
(`if 0.5:` and `if 0.0001:` now print `yes`); the non-numeric kinds are still
wrong.

    def main():
        pass

    if "x":
        print("yes")
    else:
        print("no")

## Root cause

`mojo/middle/comptime.eval_const_bool` converts only a folded `bool`/`int`
(and now `float`) to a truth value. `eval_const` DOES fold a non-empty
`StringLiteral` to its `str`, a `ListExpr`/`TupleExpr` to a list/tuple and a
`DictExpr` to a dict, so it returns a value, but `eval_const_bool` rejects it
and returns None. `eval_const_bool_state` then does

    if eval_const_bool(...): return CONST_TRUE
    return CONST_FALSE

and a foldable shape whose fold produced a truthy non-bool value therefore
reports CONST_FALSE. `module_gen._flatten_resolved_conditionals` (and the
comptime-if emitter that uses the same state) reads CONST_FALSE and resolves
the statement to its else arm, so the then-arm is deleted before emission.

## Next step

Answer Python truthiness for every value `eval_const` can fold: extend
`eval_const_bool`'s accepted folded types (str, list, tuple, dict) or make
`eval_const_bool_state` distinguish "folded to a value" from "fold failed"
instead of collapsing both to CONST_FALSE. Add a `test_gimple_matches_cpython`
case with module-level `if "x":`, `if [1]:` and `if {1: 2}:` (and an empty
control), then delete this doc in the same commit and run
`python3 tools/dangling_doc_refs.py --ratchet`.
