"""Regression for bugs/CODEGEN_nested_class_attr_reads_enclosing_local_silently_zero.md.
The basic single-call case (store at class statement execution) is fixed,
but per-execution instance storage is not: a class object built in one call
and read after a later call of the same function reads the later call's
value instead of the construction-time value.
Expected once fully fixed: 5\n7\n9\n5\n. Currently: 7 7 9 9.
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

if __name__ == '__main__':
    test_nested_class_attr_cross_execution_regression()
    print("PASS")
