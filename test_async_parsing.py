"""Parser-only unit tests for `async def`/`await`/`async for`/`async with` —
Milestone 3a of INTERP_generator_yield_entirely_unimplemented (the
async/await sibling of Milestone 1's `yield`/`yield from` parsing).

These tests construct `Parser(py_tokenize(src)).parse_module()` directly and
inspect the resulting AST (AwaitExpr / FunctionDef.is_async / ForStmt.is_async
/ WithStmt.is_async) — no interpreter/execution involved. Interpreter
execution of async/await (suspension, an event loop) is explicitly out of
scope for this milestone; `myinterpreter.py` is not touched or exercised
here, matching test_yield_parsing.py's own scope statement.
"""
import sys
import fire_compiler as N

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


def run_tests():
    # `async def` at top level.
    mod = _parse("async def f():\n    return 1\n")
    fn = mod[0]
    check("top_level_async_def_is_FunctionDef", isinstance(fn, N.FunctionDef), repr(fn))
    check("top_level_async_def_is_async", fn.is_async is True)
    check("top_level_async_def_not_generator", fn.is_generator is False)

    # `async def` as a method inside a struct.
    mod = _parse("struct S:\n    async def m(self):\n        return 1\n")
    s = mod[0]
    m = s.methods[0]
    check("method_async_def_is_async", m.is_async is True)
    check("method_async_def_name", m.name == "m", m.name)

    # `async def` decorated (the OTHER statement-dispatch path, via the `@`
    # decorator block, distinct from the undecorated top-level path above).
    mod = _parse("@some_decorator\nasync def f():\n    return 1\n")
    fn = mod[0]
    check("decorated_async_def_is_async", fn.is_async is True)
    check("decorated_async_def_has_decorator",
          fn.decorators == ["some_decorator"], repr(fn.decorators))

    # Plain (non-async) `def` is unaffected — is_async defaults False.
    mod = _parse("def f():\n    return 1\n")
    check("plain_def_not_async", mod[0].is_async is False)

    # `await expr` in various positions.
    mod = _parse("def f():\n    x = await g()\n")
    assign = mod[0].body[0]
    check("await_assign_rhs_is_AwaitExpr", isinstance(assign.value, N.AwaitExpr), repr(assign.value))
    check("await_wraps_call", isinstance(assign.value.value, N.CallExpr), repr(assign.value.value))

    mod = _parse("def f():\n    return await g()\n")
    ret = mod[0].body[0]
    check("await_in_return_is_AwaitExpr", isinstance(ret.value, N.AwaitExpr), repr(ret.value))

    mod = _parse("def f():\n    await g()\n")
    stmt = mod[0].body[0]
    check("bare_await_stmt_is_AwaitExpr", isinstance(stmt.value, N.AwaitExpr), repr(stmt.value))

    mod = _parse("def f():\n    print((await g()) + 1)\n")
    call = mod[0].body[0].value
    inner = call.args[0]
    check("await_in_binop_operand", isinstance(inner, N.BinaryOp), repr(inner))
    check("await_in_binop_left_is_AwaitExpr", isinstance(inner.left, N.AwaitExpr), repr(inner.left))

    # `async for x in y: ...`
    mod = _parse("def f():\n    async for x in y:\n        pass\n")
    for_stmt = mod[0].body[0]
    check("async_for_is_ForStmt", isinstance(for_stmt, N.ForStmt), repr(for_stmt))
    check("async_for_is_async_true", for_stmt.is_async is True)
    check("async_for_target", for_stmt.target == "x", for_stmt.target)

    # Plain `for` is unaffected — is_async defaults False.
    mod = _parse("def f():\n    for x in y:\n        pass\n")
    check("plain_for_not_async", mod[0].body[0].is_async is False)

    # `async with x() as y: ...`
    mod = _parse("def f():\n    async with cm() as y:\n        pass\n")
    with_stmt = mod[0].body[0]
    check("async_with_is_WithStmt", isinstance(with_stmt, N.WithStmt), repr(with_stmt))
    check("async_with_is_async_true", with_stmt.is_async is True)
    check("async_with_alias", with_stmt.items[0].alias == "y", with_stmt.items[0].alias)

    # Plain `with` is unaffected — is_async defaults False.
    mod = _parse("def f():\n    with cm() as y:\n        pass\n")
    check("plain_with_not_async", mod[0].body[0].is_async is False)

    # Async generator: `async def f(): yield x` — both is_async AND
    # is_generator must end up True (a real, valid Python construct; the two
    # flags are independent, not mutually exclusive).
    mod = _parse("async def f():\n    yield 1\n")
    fn = mod[0]
    check("async_generator_is_async", fn.is_async is True)
    check("async_generator_is_generator", fn.is_generator is True)
    check("async_generator_yield_bearing_ids_nonempty",
          fn.yield_bearing_node_ids is not None and len(fn.yield_bearing_node_ids) > 0)

    # `async`/`await` keyword-vs-identifier disambiguation: both are soft
    # keywords (not in _KEYWORDS), so a variable literally named `async` or
    # `await` must still parse as an ordinary identifier when not followed
    # by the shape that would make it a real async construct.
    mod = _parse("async = 5\n")
    check("async_as_assign_target", isinstance(mod[0], N.AssignStmt)
          and isinstance(mod[0].target, N.IdentExpr) and mod[0].target.name == "async",
          repr(mod[0]))

    mod = _parse("x = async\n")
    check("async_as_assign_rhs_ident", isinstance(mod[0].value, N.IdentExpr)
          and mod[0].value.name == "async", repr(mod[0].value))

    mod = _parse("await = 5\n")
    check("await_as_assign_target", isinstance(mod[0], N.AssignStmt)
          and isinstance(mod[0].target, N.IdentExpr) and mod[0].target.name == "await",
          repr(mod[0]))

    mod = _parse("x = await\n")
    check("bare_await_as_ident", isinstance(mod[0].value, N.IdentExpr)
          and mod[0].value.name == "await", repr(mod[0].value))

    # `async` immediately followed by something that isn't def/fn/for/with
    # (e.g. a call) must also fall through to plain identifier/expression
    # parsing, not misparse as some async construct.
    mod = _parse("async(x)\n")
    check("async_call_is_ExprStmt", isinstance(mod[0], N.ExprStmt), repr(mod[0]))
    check("async_call_is_CallExpr", isinstance(mod[0].value, N.CallExpr), repr(mod[0].value))
    check("async_call_func_is_async_ident",
          isinstance(mod[0].value.func, N.IdentExpr) and mod[0].value.func.name == "async",
          repr(mod[0].value.func))

    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    ok = run_tests()
    sys.exit(0 if ok else 1)
