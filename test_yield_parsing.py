"""Parser-only unit tests for `yield`/`yield from` — Milestone 1 of
bugs/INTERP_generator_yield_entirely_unimplemented.md.

These tests construct `Parser(py_tokenize(src)).parse_module()` directly and
inspect the resulting AST (YieldExpr / YieldFromExpr / FunctionDef.is_generator
/ FunctionDef.yield_bearing_node_ids) — no interpreter/execution involved.
Interpreter execution of generators is explicitly out of scope for this
milestone; `myinterpreter.py` is not touched or exercised here.
"""
import sys
import mojo_compiler as N

_PASS = 0
_FAIL = 0


def _parse(src: str):
    return N.Parser(N.py_tokenize(src)).parse_module()


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def check_raises(name: str, src: str, exc_type=SyntaxError):
    global _PASS, _FAIL
    try:
        _parse(src)
    except exc_type:
        print(f"PASS  {name}")
        _PASS += 1
        return
    except Exception as e:
        print(f"FAIL  {name}  wrong exception type: {type(e).__name__}: {e}")
        _FAIL += 1
        return
    print(f"FAIL  {name}  expected {exc_type.__name__}, parse succeeded")
    _FAIL += 1


def run_tests():
    # Bare `yield`.
    mod = _parse("def f():\n    yield\n")
    fn = mod[0]
    y = fn.body[0].value
    check("bare_yield_is_YieldExpr", isinstance(y, N.YieldExpr), repr(y))
    check("bare_yield_value_none", y.value is None, repr(y.value))
    check("bare_yield_marks_generator", fn.is_generator)

    # `yield expr`.
    mod = _parse("def f():\n    yield 5\n")
    fn = mod[0]
    y = fn.body[0].value
    check("yield_expr_is_YieldExpr", isinstance(y, N.YieldExpr), repr(y))
    check("yield_expr_value", isinstance(y.value, N.IntLiteral) and y.value.value == 5, repr(y.value))
    check("yield_expr_marks_generator", fn.is_generator)

    # `yield a, b` — implicit tuple, same convention as `return a, b`.
    mod = _parse("def f():\n    yield 1, 2\n")
    fn = mod[0]
    y = fn.body[0].value
    check("yield_tuple_is_YieldExpr", isinstance(y, N.YieldExpr), repr(y))
    check("yield_tuple_value_is_tuple", isinstance(y.value, N.TupleExpr), repr(y.value))
    check("yield_tuple_elements", len(y.value.elements) == 2, repr(y.value.elements))

    # `yield from expr`.
    mod = _parse("def f():\n    yield from range(5)\n")
    fn = mod[0]
    y = fn.body[0].value
    check("yield_from_is_YieldFromExpr", isinstance(y, N.YieldFromExpr), repr(y))
    check("yield_from_value_is_call", isinstance(y.value, N.CallExpr), repr(y.value))
    check("yield_from_marks_generator", fn.is_generator)

    # `x = yield y` — yield as the whole RHS of a simple assignment.
    mod = _parse("def f():\n    x = yield 7\n")
    fn = mod[0]
    assign = fn.body[0]
    check("assign_rhs_is_AssignStmt", isinstance(assign, N.AssignStmt), repr(assign))
    check("assign_rhs_is_YieldExpr", isinstance(assign.value, N.YieldExpr), repr(assign.value))
    check("assign_rhs_marks_generator", fn.is_generator)

    # `(yield x)` as a sub-expression (parenthesized) — e.g. a call argument.
    mod = _parse("def f():\n    results = []\n    results.append((yield 1))\n")
    fn = mod[0]
    call = fn.body[1].value
    check("paren_yield_call_expr", isinstance(call, N.CallExpr), repr(call))
    check("paren_yield_is_arg", len(call.args) == 1 and isinstance(call.args[0], N.YieldExpr),
          repr(call.args))

    # `x += yield y` — real Python allows bare yield as an augmented-assign RHS.
    mod = _parse("def f():\n    x = 0\n    x += yield 1\n")
    fn = mod[0]
    aug = fn.body[1]
    check("augassign_rhs_is_AugAssignStmt", isinstance(aug, N.AugAssignStmt), repr(aug))
    check("augassign_rhs_is_YieldExpr", isinstance(aug.value, N.YieldExpr), repr(aug.value))

    # `x: int = yield y` — real Python allows bare yield as an annotated-assign RHS.
    mod = _parse("def f():\n    x: int = yield 1\n")
    fn = mod[0]
    ann = fn.body[0]
    check("annassign_rhs_is_AssignStmt", isinstance(ann, N.AssignStmt), repr(ann))
    check("annassign_rhs_is_YieldExpr", isinstance(ann.value, N.YieldExpr), repr(ann.value))

    # `yield` inside if/while/for/try bodies.
    mod = _parse(
        "def f():\n"
        "    if True:\n"
        "        yield 1\n"
        "    while True:\n"
        "        yield 2\n"
        "    for i in range(3):\n"
        "        yield i\n"
        "    try:\n"
        "        yield 4\n"
        "    except Exception:\n"
        "        pass\n"
    )
    fn = mod[0]
    check("yield_in_if_body", isinstance(fn.body[0].then_body[0].value, N.YieldExpr))
    check("yield_in_while_body", isinstance(fn.body[1].body[0].value, N.YieldExpr))
    check("yield_in_for_body", isinstance(fn.body[2].body[0].value, N.YieldExpr))
    check("yield_in_try_body", isinstance(fn.body[3].body[0].value, N.YieldExpr))
    check("yield_in_compound_bodies_marks_generator", fn.is_generator)

    # Generator detection: a `yield` only inside a NESTED `def` must mark
    # the INNER function as a generator, and must NOT mark the outer one
    # (real Python scoping — a nested function's `yield` belongs to it, not
    # its enclosing function).
    mod = _parse("def outer():\n    def inner():\n        yield 1\n    return inner\n")
    outer = mod[0]
    inner = outer.body[0]
    check("nested_yield_does_not_mark_outer", outer.is_generator is False)
    check("nested_yield_marks_inner", inner.is_generator is True)
    check("outer_yield_bearing_ids_none", outer.yield_bearing_node_ids is None)
    check("inner_yield_bearing_ids_nonempty",
          inner.yield_bearing_node_ids is not None and len(inner.yield_bearing_node_ids) > 0)

    # A function with no yield at all is not a generator.
    mod = _parse("def plain():\n    return 1\n")
    check("plain_function_not_generator", mod[0].is_generator is False)
    check("plain_function_no_yield_ids", mod[0].yield_bearing_node_ids is None)

    # yield_bearing_node_ids: the YieldExpr node itself, and every ancestor
    # statement/expression up to (but not including) the FunctionDef, must
    # be recorded.
    mod = _parse("def f():\n    if True:\n        yield 1\n")
    fn = mod[0]
    if_stmt = fn.body[0]
    yield_expr = if_stmt.then_body[0].value
    ids = fn.yield_bearing_node_ids
    check("yield_node_in_ids", id(yield_expr) in ids)
    check("if_stmt_in_ids", id(if_stmt) in ids)
    check("expr_stmt_in_ids", id(if_stmt.then_body[0]) in ids)

    # Using `yield` as a bare sub-expression WITHOUT parens (e.g. directly
    # inside an `if` condition) is not a supported grammar shape — real
    # Python requires parens there too. Not asserting a specific failure
    # mode (this codegen's call-argument comma-handling is independently
    # lenient — a pre-existing, unrelated parser quirk), just documenting
    # that unparenthesized `yield` is only recognized at the specific
    # positions real Python allows it bare (RHS of simple/chained/
    # annotated/augmented assignment, bare expression statement).

    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    ok = run_tests()
    sys.exit(0 if ok else 1)
