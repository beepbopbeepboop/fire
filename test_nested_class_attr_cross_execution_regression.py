"""Regression for bugs/CODEGEN_nested_class_attr_reads_enclosing_local_silently_zero.md.
A function-scoped class's non-constant class attribute is per EXECUTION of its
`class` statement: an instance built in one call keeps that call's value when
it is read after a later call of the same function. Before the per-execution
cell storage this printed `7 7 9 9` where CPython prints `5 7 9 5`.
"""
from test_gimple_runner import test_gimple_stdout

def test_nested_class_attr_cross_execution_regression():
    test_gimple_stdout("gimple_nested_class_attr_cross_exec", """\
def make(version: int):
    class Tag():
        __version__ = version
    return Tag()

def main():
    a = make(5)
    b = make(7)
    print(a.__version__)
    print(b.__version__)
    print(make(9).__version__)
    print(a.__version__)
""", "5\n7\n9\n5\n")

def test_nested_class_container_attr_cross_execution_regression():
    # A container-valued attribute is per execution too: the instance keeps its
    # own list, not the list the latest call built. Before this fix `2 2`.
    test_gimple_stdout("gimple_nested_class_container_attr_cross_exec", """\
def h(v: int):
    class C():
        items = [v]
    return C()

def main():
    c = h(1)
    d = h(2)
    print(c.items[0])
    print(d.items[0])
""", "1\n2\n")

def test_nested_class_attr_recursive_execution_regression():
    # A recursive call runs the same `class` statement, repointing the shared
    # cell global. The caller's class-name read after the call must still see
    # ITS OWN cell. Before the save/restore this printed `6 6 6 6`.
    test_gimple_stdout("gimple_nested_class_attr_recursive", """\
def f(v: int, d: int):
    class T():
        __version__ = v
    if d > 0:
        f(v + 1, d - 1)
        print(T.__version__)
        return
    print(T.__version__)

def main():
    f(5, 1)
    f(7, 0)
""", "6\n5\n7\n")

def test_nested_class_attr_recursive_value_return_regression():
    # The same restore must run before a `return <value>`, and the value must
    # be the caller's own cell, not the callee's. Expected `5`, and a second
    # call from a fresh frame reads its own `9`.
    test_gimple_stdout("gimple_nested_class_attr_recursive_return", """\
def g(v: int, d: int) -> int:
    class T():
        __version__ = v
    if d > 0:
        g(v + 1, d - 1)
        return T.__version__
    return T.__version__

def main():
    print(g(5, 1))
    print(g(9, 0))
""", "5\n9\n")

def test_nested_class_attr_exception_unwind_regression():
    # An exception raised in a nested execution of the same function unwinds
    # past that execution without reaching its own restore. The catching
    # execution's handler must put its OWN cell back, or its class-name read
    # reaches the nested execution's cell. Before this fix this printed `6`
    # where CPython prints `5`.
    test_gimple_stdout("gimple_nested_class_attr_exception_unwind", """\
def f(v: int, d: int):
    class T():
        __version__ = v
    if d > 0:
        try:
            f(v + 1, d - 1)
        except ValueError:
            print("caught")
        print(T.__version__)
    if d == 0:
        raise ValueError("x")

def main():
    f(5, 1)
""", "caught\n5\n")

def test_nested_class_attr_unwind_other_function_regression():
    # The exception is raised in a nested execution of `x`, and it is caught
    # by a DIFFERENT function (`h`), which defines no class of its own. `x`'s
    # own restore never runs on that path, so the cell it reads must be put
    # back during unwinding. Before the unwind-time restore this printed `6`
    # where CPython prints `5`.
    test_gimple_stdout("gimple_nested_class_attr_unwind_other_function", """\
def x(v: int, d: int):
    class T():
        __version__ = v
    if d > 0:
        h(v + 1, d - 1)
    if d == 0:
        raise ValueError("x")
    print(T.__version__)

def h(v: int, d: int):
    try:
        x(v, d)
    except ValueError:
        print("caught")

def main():
    x(5, 1)
""", "caught\n5\n")

def test_class_attr_instance_read_falls_back_to_class_regression():
    # An instance read of a class attribute that no instance write has shadowed
    # reads the class attribute. Before the fallback every such read raised
    # AttributeError, because an instance read consulted only dynamic storage.
    # A write on the instance still shadows the class attribute, and the
    # class-name read is unchanged. CPython prints 9, 4, 9.
    test_gimple_stdout("gimple_class_attr_instance_read_fallback", """\
class A():
    x = 9

def main():
    a = A()
    print(a.x)
    a.x = 4
    print(a.x)
    print(A.x)
""", "9\n4\n9\n")

if __name__ == '__main__':
    test_nested_class_attr_cross_execution_regression()
    test_nested_class_container_attr_cross_execution_regression()
    test_nested_class_attr_recursive_execution_regression()
    test_nested_class_attr_recursive_value_return_regression()
    test_nested_class_attr_exception_unwind_regression()
    test_nested_class_attr_unwind_other_function_regression()
    test_class_attr_instance_read_falls_back_to_class_regression()
    print("PASS")

def test_same_named_function_scoped_classes_attr_regression():
    # Two function-scoped classes with the same bare name: the second is hoisted
    # under a renamed struct (`T__g`), so its class-name read must resolve
    # through the same enclosing-function rename the constructor uses. Before
    # that, `T.x` inside `g` read the first class's `x`: `1 1` where CPython
    # prints `1 2`.
    test_gimple_stdout("gimple_same_named_scoped_class_attr", """\
def f():
    class T():
        x = 1
    return T.x

def g():
    class T():
        x = 2
    return T.x

def main():
    print(f())
    print(g())
""", "1\n2\n")
