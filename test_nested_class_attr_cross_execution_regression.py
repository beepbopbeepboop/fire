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

if __name__ == '__main__':
    test_nested_class_attr_cross_execution_regression()
    test_nested_class_container_attr_cross_execution_regression()
    print("PASS")
