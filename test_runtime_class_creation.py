"""Stage 3 of bugs/hard/CODEGEN_enum_runtime_class_creation.md: the 3-argument
`type(name, bases, namespace)` makes a class at run time.

Each program is compiled, RUN, and its stdout compared with CPython's on the same text. The
class is a class-table entry (`mojo_type_new`) whose bases are the listed classes and whose
dict starts from the namespace; `Foo.x`, `Foo.x = v`, `getattr / hasattr` on the handle read the
table, found through the bases (depth first, left to right). A shape the compiler cannot
model (a user metaclass) must still be refused by name, not miscompiled.
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
    'computed_namespace_dict_variable': """\
def main():
    ns = {'x': 1, 'f': 2.5, 's': 'hi'}
    ns['y'] = 3
    Foo = type('Foo', (), ns)
    print(Foo.x, Foo.f, Foo.s, Foo.y)
    ns['z'] = 9
    print(hasattr(Foo, 'z'), getattr(Foo, 'y'))
main()
""",
    'computed_bases_list_variable': """\
def main():
    A = type('A', (), {'a': 1, 'k': 10})
    B = type('B', (), {'b': 2, 'k': 20})
    bases = (A, B)
    C = type('C', bases, {'c': 3})
    print(C.a, C.b, C.c, C.k)
main()
""",
    'static_class_in_computed_bases_list': """\
class B:
    y = 5

def main():
    A = type('A', (), {'a': 1})
    bases = (A, B)
    C = type('C', bases, {'c': 3})
    print(C.a, C.c, C.y)
    ls = (B,)
    D = type('D', ls, {})
    print(D.y)
main()
""",
    'static_base_body_attributes_are_inherited': """\
class B:
    y = 5
    s = 'hi'
    f = 2.5

def main():
    F = type('F', (B,), {'z': 1})
    print(F.z, F.y, F.s, F.f)
    print(hasattr(F, 'y'), hasattr(F, 'q'), getattr(F, 'y'))
    F.y = 6
    print(F.y, B.y)
main()
""",
    'static_base_attribute_is_read_live': """\
class B:
    y = 5

def main():
    F = type('F', (B,), {})
    B.y = 8
    print(F.y)
main()
""",
    'instance_of_a_run_time_class': """\
def main():
    Foo = type('Foo', (), {'x': 1})
    o = Foo()
    o.y = 3
    print(o.x, o.y)
    o.x = 5
    print(o.x, Foo.x)
    p = Foo()
    print(p.x, hasattr(p, 'y'), hasattr(o, 'y'))
    Foo.x = 9
    print(p.x, o.x)
main()
""",
    'instance_reads_through_the_class_bases': """\
def main():
    A = type('A', (), {'a': 1, 'k': 10})
    B = type('B', (A,), {'b': 2})
    o = B()
    print(o.a, o.b, o.k)
    A.k = 11
    print(o.k, getattr(o, 'k'), getattr(o, 'nope', 42))
main()
""",
    'methods_in_the_namespace_are_called_on_instances': """\
def init(self, v):
    self.v = v

def get(self):
    return self.v + 1

def add(self, a, b):
    return self.v + a + b

def make(x):
    return x * 2

def main():
    Foo = type('Foo', (), {'__init__': init, 'get': get, 'add': add, 'make': make})
    o = Foo(4)
    print(o.get(), o.add(10, 20))
    o.v = 7
    print(o.get())
    print(Foo.make(21))
    Bar = type('Bar', (Foo,), {'get': lambda self: 100})
    b = Bar(1)
    print(b.get(), b.add(1, 1))
main()
""",
    'isinstance_of_a_run_time_class': """\
def main():
    A = type('A', (), {'a': 1})
    B = type('B', (A,), {'b': 2})
    C = type('C', (), {})
    o = B()
    print(isinstance(o, B), isinstance(o, A), isinstance(o, C))
    print(isinstance(A(), B), isinstance(o, (C, A)), isinstance(5, A))
main()
""",
    'isinstance_of_a_static_base_of_a_run_time_class': """\
class Base:
    pass

def main():
    B = type('B', (Base,), {'b': 2})
    o = B()
    print(isinstance(o, B), isinstance(o, Base))
    print(isinstance(Base(), Base), isinstance(5, Base))
    C = type('C', (), {})
    print(isinstance(C(), Base))
main()
""",
    'type_dunder_new_with_the_type_metaclass': """\
def main():
    Foo = type.__new__(type, 'Foo', (), {'x': 1, 'z': 'hi'})
    print(Foo.x, Foo.z, Foo.__name__)
    B = type.__new__(type, 'B', (Foo,), {'b': 2})
    print(B.x, B.b)
    B.q = 5
    print(B.q, hasattr(B, 'q'), hasattr(Foo, 'q'))
main()
""",
    'call_result_namespace': """\
def ns():
    d = {}
    d['x'] = 1
    d['z'] = 'hi'
    return d

def main():
    Foo = type('Foo', (), ns())
    print(Foo.x, Foo.z)
    B = type('B', (Foo,), dict(b=2))
    print(B.x, B.b)
main()
""",
    'methods_and_constructor_take_up_to_seven_arguments': """\
def init(self, a, b, c, d, e, f, g):
    self.t = a + b + c + d + e + f + g

def many(self, a, b, c, d, e, f, g):
    return self.t * 100 + a + g

def stat(a, b, c, d, e, f, g):
    return a * 1000 + g

def main():
    Foo = type('Foo', (), {'__init__': init, 'many': many, 'stat': stat})
    o = Foo(1, 2, 3, 4, 5, 6, 7)
    print(o.t)
    print(o.many(1, 0, 0, 0, 0, 0, 9))
    print(Foo.stat(3, 0, 0, 0, 0, 0, 4))
    p = Foo(1, 1, 1, 1, 1, 1, 1)
    print(p.many(2, 0, 0, 0, 0, 0, 3))
main()
""",
    'metaclass_made_at_run_time_answers_misses': """\
def ga(cls, name):
    return len(name) * 100

def mname(cls):
    return 42

def main():
    Meta = type('Meta', (type,), {'__getattr__': ga, 'tag': 7, 'mname': mname})
    Foo = type.__new__(Meta, 'Foo', (), {'x': 1})
    print(Foo.x)
    print(Foo.tag)
    print(Foo.abc)
    print(Foo.mname())
    Foo.y = 3
    print(Foo.y)
main()
""",
    'type_of_and_isinstance_with_a_run_time_metaclass': """\
def main():
    Meta = type('Meta', (type,), {'tag': 7})
    Sub = type('Sub', (Meta,), {})
    Foo = type.__new__(Meta, 'Foo', (), {'x': 1})
    Baz = type.__new__(Sub, 'Baz', (), {})
    Bar = type('Bar', (), {})
    o = Foo()
    print(isinstance(Foo, Meta), isinstance(Bar, Meta), isinstance(Baz, Meta), isinstance(Foo, Sub))
    print(isinstance(Foo, type), isinstance(Bar, type), isinstance(o, type), isinstance(5, type))
    print(type(Foo) is Meta, type(Bar) is Meta, type(Baz) is Sub, type(Bar) is type)
    print(type(o) is Foo, type(o) is Bar, isinstance(o, Foo), isinstance(o, Meta))
main()
""",
    'rt_class_flag_reaches_a_later_function': """\
def make():
    Meta = type('Meta', (type,), {})
    return type.__new__(Meta, 'Foo', (), {})

def check(c):
    print(isinstance(c, type))

def main():
    check(make())
    check(5)
main()
""",
    'two_classes_of_one_name_are_two_classes': """\
def main():
    P = type('Same', (), {'v': 1})
    Q = type('Same', (), {'v': 2})
    print(P.v, Q.v, P.__name__ == Q.__name__)
main()
""",
    'init_subclass_invoked': """\
class Base:
    def __init_subclass__(cls):
        print(cls.__name__)

def main():
    Derived = type('Derived', (Base,), {})
    print(Derived.__name__)
main()
""",
}


def main():
    for name, src in CASES.items():
        R.test_gimple_matches_cpython(name, src)
    R.test_gimple_build_refusal(
        'type_dunder_new_with_a_user_metaclass_is_refused_by_name',
        """\
class Meta(type):
    pass

def main():
    Foo = type.__new__(Meta, 'Foo', (), {'x': 1})
    print(Foo.x)
main()
""", 'type.__new__(metacls')
    print(f'\n{R._PASS} passed, {R._FAIL} failed')
    return 1 if (R._FAIL or R._TIMEOUT) else 0


if __name__ == '__main__':
    sys.exit(main())
