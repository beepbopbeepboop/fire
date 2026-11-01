"""Regression: `hasattr` / `getattr(..., default)` on a field the compiler minted
(assigned outside `__init__`) must be False on an instance that never received it.

A field the COMPILER mints onto a struct (assigned outside `__init__`, or only
read) exists in every instance's storage, but only the instances that were
actually assigned it may answer `hasattr(obj, name)` True. Each program is
compiled, run, and its stdout compared with CPython's on the same text.
"""
import sys

import test_gimple_runner as R

CASES = {
    'inferred_field_assigned_outside_init_is_absent_on_other_instances': """\
class P:
    def __init__(self):
        self.a = 1

def main():
    p = P()
    p.b = 5
    q = P()
    print(hasattr(q, 'b'))
    print(getattr(q, 'b', 99))
    print(hasattr(p, 'b'), getattr(p, 'b', 99))
main()
""",
    'method_assigned_field_absent_on_instance_that_never_called_it': """\
class Box:
    def __init__(self):
        self.a = 1

    def set(self):
        self.c = 7

def main():
    b = Box()
    b.set()
    other = Box()
    print(hasattr(b, 'c'), getattr(b, 'c', -1))
    print(hasattr(other, 'c'), getattr(other, 'c', -1))
main()
""",
    'setattr_marks_the_field_present': """\
class P:
    def __init__(self):
        self.a = 1

def main():
    p = P()
    q = P()
    setattr(p, 'b', 5)
    print(hasattr(p, 'b'), getattr(p, 'b', 0))
    print(hasattr(q, 'b'), getattr(q, 'b', 0))
main()
""",
    'field_read_only_in_one_body_is_absent_until_stored': """\
class P:
    def __init__(self):
        self.a = 1

def reader(x):
    return getattr(x, 'r', 42)

def main():
    p = P()
    print(hasattr(p, 'r'), reader(p))
    p.r = 3
    print(hasattr(p, 'r'), reader(p))
main()
""",
    'copy_by_value_keeps_presence': """\
class P:
    def __init__(self):
        self.a = 1

def main():
    p = P()
    p.b = 5
    c = P()
    c.a = p.a
    c.b = p.b
    print(hasattr(c, 'b'), getattr(c, 'b', 0))
    d = P()
    print(hasattr(d, 'b'))
main()
""",
    'more_than_64_minted_fields_use_several_presence_words': (
        "class P:\n"
        "    def __init__(self):\n"
        "        self.a = 1\n\n"
        "def main():\n"
        "    p = P()\n"
        + "".join(f"    p.f{i} = {i}\n" for i in range(70))
        + "    q = P()\n"
        "    print(hasattr(q, 'f0'), hasattr(q, 'f63'), hasattr(q, 'f69'))\n"
        "    print(hasattr(p, 'f0'), hasattr(p, 'f63'), hasattr(p, 'f69'))\n"
        "    print(getattr(p, 'f69', -1), getattr(q, 'f69', -1))\n"
        "main()\n"
    ),
}


def main():
    for name, src in CASES.items():
        R.test_gimple_matches_cpython(name, src)
    print(f'\n{R._PASS} passed, {R._FAIL} failed')
    return 1 if (R._FAIL or R._TIMEOUT) else 0


if __name__ == '__main__':
    sys.exit(main())
