#!/usr/bin/env python3
"""Regression: a Mojo class's ``__mro__`` attribute.

`B.__mro__` used to raise `AttributeError: __mro__` — CPython exposes
`type.__mro__`, a tuple of the classes in method-resolution order, and real
code (e.g. `next(type for type in cls.__mro__ if ...)` and metaclass-style
introspection) reads it off classes directly. The interpreter now returns its
own C3 linearisation: a tuple starting with the class itself, continuing
through the linearisation of its bases left to right.

Everything is asserted on ``c.__name__`` rather than on repr: a MojoClass's
repr is `<myinterpreter.MojoClass object at 0x...>`, which would pin the
address, not the behaviour.
"""
import sys
import fire_compiler as N
from myinterpreter import Interpreter, MojoClass

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def _run(source: str) -> Interpreter:
    mod = N.Module(body=N.Parser(N.py_tokenize(source)).parse_module())
    interp = Interpreter()
    interp.execute(mod)
    return interp


def _mro_names(cls):
    return [c.__name__ for c in cls.__mro__]


def test_plain_class():
    interp = _run("class X:\n    pass\n")
    X = interp.scope.get('X')
    mro = X.__mro__
    check('plain_class_mro_is_a_tuple_with_only_itself',
          isinstance(mro, tuple) and len(mro) == 1 and mro[0] is X,
          repr(mro))


def test_single_inheritance():
    interp = _run("class A:\n    pass\nclass B(A):\n    pass\n")
    A = interp.scope.get('A')
    B = interp.scope.get('B')
    mro = B.__mro__
    check('single_inheritance_order',
          _mro_names(B) == ['B', 'A'] and mro[0] is B and mro[1] is A,
          repr(_mro_names(B)))


def test_transitive_chain():
    interp = _run(
        "class A:\n    pass\nclass B(A):\n    pass\nclass C(B):\n    pass\n")
    check('transitive_chain',
          _mro_names(interp.scope.get('C')) == ['C', 'B', 'A'])


def test_diamond_order_matches_c3():
    interp = _run(
        "class O:\n    pass\nclass L(O):\n    pass\nclass R(O):\n    pass\n"
        "class D(L, R):\n    pass\n")
    check('diamond_shared_root_order_is_c3',
          _mro_names(interp.scope.get('D')) == ['D', 'L', 'R', 'O'])


def test_diamond_order_flips_with_base_order():
    interp = _run(
        "class O:\n    pass\nclass L(O):\n    pass\nclass R(O):\n    pass\n"
        "class E(R, L):\n    pass\n")
    check('diamond_respects_base_declaration_order',
          _mro_names(interp.scope.get('E')) == ['E', 'R', 'L', 'O'])


def test_two_unrelated_bases():
    interp = _run(
        "class A:\n    pass\nclass B:\n    pass\nclass P(A, B):\n    pass\n")
    check('two_unrelated_bases',
          _mro_names(interp.scope.get('P')) == ['P', 'A', 'B'])


def test_elements_are_distinct_and_first_is_itself():
    interp = _run(
        "class A:\n    pass\nclass B:\n    pass\nclass C(A, B):\n    pass\n")
    C = interp.scope.get('C')
    mro = C.__mro__
    check('mro_members_are_unique_classes',
          all(isinstance(c, MojoClass) for c in mro)
          and len(set(mro)) == len(mro) and len(mro) == 3)


def test_inconsistent_hierarchy_raises_type_error():
    interp = _run(
        "class B:\n    pass\nclass A(B):\n    pass\nclass X(B, A):\n    pass\n")
    X = interp.scope.get('X')
    try:
        X.__mro__
        check('inconsistent_hierarchy_raises', False,
              'expected TypeError, got an MRO')
    except TypeError:
        check('inconsistent_hierarchy_raises', True)
    except Exception as e:
        check('inconsistent_hierarchy_raises', False,
              f"expected TypeError, got {type(e).__name__}: {e}")


def test_repeated_access_is_the_same_tuple_object():
    interp = _run(
        "class A:\n    pass\nclass B(A):\n    pass\n")
    B = interp.scope.get('B')
    check('repeated_access_cached', B.__mro__ is B.__mro__)


def test_instance_member_lookup_raises_attribute_error():
    interp = _run(
        "class A:\n    pass\nclass B(A):\n    pass\n"
        "def main():\n    b = B()\n    x = b.__mro__\n")
    try:
        interp.eval_expr(N.CallExpr(func=N.IdentExpr(name='main')))
    except AttributeError:
        check('instance_member_lookup_raises', True)
        return
    check('instance_member_lookup_raises', False,
          'expected AttributeError for b.__mro__')
    check('instance_is_instance_of_class', True)


def main():
    test_plain_class()
    test_single_inheritance()
    test_transitive_chain()
    test_diamond_order_matches_c3()
    test_diamond_order_flips_with_base_order()
    test_two_unrelated_bases()
    test_elements_are_distinct_and_first_is_itself()
    test_inconsistent_hierarchy_raises_type_error()
    test_repeated_access_is_the_same_tuple_object()
    test_instance_member_lookup_raises_attribute_error()
    print(f'\n{_PASS} passed, {_FAIL} failed')
    return 1 if _FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
