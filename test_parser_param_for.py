"""Regression test for PARSER_param_for: `param for` loops parse as compile-time for loops."""
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
    # Basic param for
    mod = _parse("def foo():\n    param for i in range(3):\n        pass\n")
    fn = mod[0]
    body = fn.body
    check("param_for_is_comptime_for_stmt", isinstance(body[0], N.ComptimeForStmt), repr(type(body[0])))
    
    # param for with tuple unpacking
    mod = _parse("def foo():\n    param for i, j in zip(a, b):\n        pass\n")
    body = mod[0].body
    check("param_for_tuple_unpack", isinstance(body[0], N.ComptimeForStmt), repr(type(body[0])))
    
    # param for as top level in function
    mod = _parse("def bar():\n    param for x in [1, 2, 3]:\n        print(x)\n")
    body = mod[0].body
    check("param_for_iterable_list", isinstance(body[0], N.ComptimeForStmt))


if __name__ == '__main__':
    run_tests()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    sys.exit(0 if _FAIL == 0 else 1)
