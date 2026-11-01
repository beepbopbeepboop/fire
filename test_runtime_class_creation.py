"""Stage 3 of bugs/CODEGEN_enum_runtime_class_creation.md: the 3-argument
`type(name, bases, namespace)` makes a class at run time.

Each program is compiled, RUN, and its stdout compared with CPython's on the same text. The
class is a class-table entry (`mojo_type_new`) whose bases are the listed classes and whose
dict starts from the namespace; `Foo.x`, `Foo.x = v`, `getattr / hasattr` on the handle read the
table, found through the bases (depth first, left to right). A shape the compiler cannot
model (a computed namespace) must still be refused by name, not miscompiled.
"""
import sys

import test_gimple_runner as R

CASES = {
    'namespace_attrs_name_and_int_str': """\
def main():
    Foo = type('Foo', (), {'x': 1, 'z': 'hi'})
    print(Foo.x)
    print(Foo.z)
    print(Foo.__name__)
main()
""",
    'attribute_set_after_creation': """\
def main():
    Foo = type('Foo', (), {'x': 1})
    Foo.y = 7
    setattr(Foo, 'w', 9)
    Foo.x = 2
    print(Foo.x, Foo.y, Foo.w)
main()
""",
    'bases_are_searched_depth_first_left_to_right': """\
class Base:
    pass

def main():
    setattr(Base, 'k', 5)
    A = type('A', (Base,), {'a': 1})
    B = type('B', (), {'k': 6, 'b': 2})
    C = type('C', (A, B), {'c': 3})
    print(C.a, C.b, C.c, C.k)
    D = type('D', (B, A), {})
    print(D.k)
main()
""",
    'two_classes_of_one_name_are_two_classes': """\
def main():
    P = type('Same', (), {'v': 1})
    Q = type('Same', (), {'v': 2})
    print(P.v, Q.v, P.__name__ == Q.__name__)
main()
""",
}


def main():
    for name, src in CASES.items():
        R.test_gimple_matches_cpython(name, src)
    R.test_gimple_build_refusal(
        'computed_namespace_is_refused_by_name',
        """\
def main():
    ns = {'x': 1}
    Foo = type('Foo', (), ns)
    print(Foo.x)
main()
""", 'creates a class at run time')
    print(f'\n{R._PASS} passed, {R._FAIL} failed')
    return 1 if (R._FAIL or R._TIMEOUT) else 0


if __name__ == '__main__':
    sys.exit(main())
