#!/usr/bin/env python3
"""Regression: a struct naming a trait of its own module as a base but not
implementing a function the trait requires is rejected before anything runs,
in the modular compiler's shape (one error per trait with a missing
requirement, a note per missing function, then the trait note), and every such
error is reported in source order. Expected text captured from
`tools/mojo build` (DIAGNOSTICS_formatting_modular part 1, group J)."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')


def run(src):
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 't.mojo')
        open(f, 'w').write(src)
        p = subprocess.run([sys.executable, FIRE, 'run', f],
                           capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout, p.stderr.replace(f, 'F')


def test_inherited_requirement_missing():
    rc, out, err = run('''trait NoDefaultFunc:
    def doSomething(self):
        ...


trait StillNoDefaultFunc(NoDefaultFunc):
    def doEverything(self):
        ...


struct StructViolation(StillNoDefaultFunc):
    def doEverything(self):
        pass


struct Direct(NoDefaultFunc):
    pass


def main():
    print("ran")
''')
    want = """F:11:8: error: 'StructViolation' does not implement all requirements for 'NoDefaultFunc'
struct StructViolation(StillNoDefaultFunc):
       ^
F:2:9: note: required function 'doSomething' is not implemented
    def doSomething(self):
        ^
F:1:7: note: trait 'NoDefaultFunc' declared here
trait NoDefaultFunc:
      ^
F:16:8: error: 'Direct' does not implement all requirements for 'NoDefaultFunc'
struct Direct(NoDefaultFunc):
       ^
F:2:9: note: required function 'doSomething' is not implemented
    def doSomething(self):
        ^
F:1:7: note: trait 'NoDefaultFunc' declared here
trait NoDefaultFunc:
      ^
"""
    assert rc == 1 and out == '' and err == want, (rc, out, err)


def test_one_error_per_trait_all_missing_functions():
    rc, out, err = run('''trait A:
    def one(self):
        ...

    def two(self):
        ...


trait B(A):
    def three(self):
        ...

    def dflt(self):
        pass


struct S(B):
    def two(self):
        pass


struct R(Copyable, A):
    pass


def main():
    pass
''')
    want = """F:17:8: error: 'S' does not implement all requirements for 'A'
struct S(B):
       ^
F:2:9: note: required function 'one' is not implemented
    def one(self):
        ^
F:1:7: note: trait 'A' declared here
trait A:
      ^
F:17:8: error: 'S' does not implement all requirements for 'B'
struct S(B):
       ^
F:10:9: note: required function 'three' is not implemented
    def three(self):
        ^
F:9:7: note: trait 'B' declared here
trait B(A):
      ^
F:22:8: error: 'R' does not implement all requirements for 'A'
struct R(Copyable, A):
       ^
F:2:9: note: required function 'one' is not implemented
    def one(self):
        ^
F:5:9: note: required function 'two' is not implemented
    def two(self):
        ^
F:1:7: note: trait 'A' declared here
trait A:
      ^
"""
    assert rc == 1 and err == want, err


def test_conforming_struct_runs():
    rc, out, err = run('''trait T:
    def go(self):
        ...

    def extra(self):
        print("default")


struct S(T):
    def go(self):
        print("go")


def main():
    S().go()
''')
    # (a trait's default method is not inherited by the interpreter; that is
    # a separate gap -- this case only checks the static pass accepts it.)
    assert rc == 0 and out == 'go\n', (rc, out, err)


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all tests passed')
