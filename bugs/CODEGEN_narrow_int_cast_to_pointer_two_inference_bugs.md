# Two wrong inferred types in the self-compiled interpreter (a `_Bool` and an `int` cast to a pointer)

Class: medium. Two separate defects in type INFERENCE, both found by
gimple-lint's `cast-narrow-int-to-ptr` rule. Fix one per round.

## Measured 2026-11-16

`python3 test_gimple_lint.py ratchet` reports 2 findings of
`cast-narrow-int-to-ptr`; `BASELINE['cast-narrow-int-to-ptr']` in
`test_gimple_lint.py` is 2. (It was 13. The other 11 were the falsy
short-circuit edge of `flag and ptr`, which now stores the null constant.)

Reproduce, from an empty directory outside the tree:

    python3 /path/to/tree/fire.py --dump /path/to/tree/myinterpreter.py
    python3 /path/to/tree/tools/gimple_lint.py -v --code cast-narrow-int-to-ptr myinterpreter.ci

## Defect 1: a function's return type is taken from one `return` and the others are cast to it

    myinterpreter.ci: _Bool cast to MojoString *
        in Interpreter__apply_binary_op:  _t156 = (MojoString *)_t155;

`Interpreter._apply_binary_op` (`myinterpreter.py`, near line 9440) has many
`return` statements of different types: `return MojoString(left)`,
`return left % right`, `return self._apply_compare_op(op, left, right)`
(a `_Bool`), `return self._wrap_int(...)`. Its emitted signature is

    MojoString * Interpreter__apply_binary_op (Interpreter *, int64_t, char *, int64_t, int64_t);

so every non-`MojoString` result is CAST to `MojoString *`. A `True` from
`_apply_compare_op` becomes the pointer 1.

Expected: a function with no return annotation whose `return` statements
have different C types returns a boxed word (`int64_t`), and each `return`
boxes its value the way a mixed `if`/`else` expression does. Find where the
return type of an unannotated function is inferred (`func_return_types` is
the table; search `mojo/middle/infra_infer.py` and
`mojo/backend_gimple/module_gen.py` for where it is filled) and make
differing return types join to the boxed word, never to the first pointer
type seen.

Test to add to `test_gimple.py`: a function with `if a: return "s"` /
`return a == b`, called both ways, printed, compared with CPython.

## Defect 2: an unannotated parameter is given the wrong struct type

    myinterpreter.ci: int cast to char *
        in Interpreter__eval_member_of:  _t113 = (char *)_t111;     /* _t111 = expr->member; */

`Interpreter._eval_member_of(self, expr, obj)` (`myinterpreter.py`, near
line 9647) is called once, from `eval_MemberExpr`, with a `MemberExpr`.
Its emitted signature is

    int64_t Interpreter__eval_member_of (Interpreter *, _LazyImportTarget *, int64_t);

`_LazyImportTarget` (`myinterpreter.py`, near line 2449) is an unrelated
class with no `member` field. The body then reads `expr->member` through
the wrong struct layout and gets an `int`.

Expected: `expr` is `MemberExpr *` (the only caller passes one) or an
untyped word. Find why parameter inference chose `_LazyImportTarget`:
`_infer_param_types` in `mojo/middle/infra_infer.py`, and the call-site
scan in `mojo/backend_gimple/module_gen.py`. Print the candidates it
considered for `_eval_member_of`'s `expr` and fix the rule that picked a
class no caller passes.

## How to verify (each defect)

1. The ratchet count drops; lower `BASELINE['cast-narrow-int-to-ptr']` in
   the same commit.
2. `python3 test_gimple.py` keeps its pass count with 0 failed.
3. `python3 tools/suite.py stdlib-syntax stdlib-dylib gimple-lint` passes.

## Done when

The baseline entry is 0 and removed from `BASELINE`, and this file is
deleted in the same commit (then
`python3 tools/dangling_doc_refs.py --ratchet`).
