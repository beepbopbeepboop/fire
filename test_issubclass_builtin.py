#!/usr/bin/env python3
"""`issubclass(...)` is lowered, not answered by the weak "unavailable" stub.

The GIMPLE backend had no arm for `issubclass`: the call fell through to the
generic unknown-builtin lowering, which emits a weak C stub printing
`issubclass: unavailable in compiled mode` and returning 0. The three-class
probe below therefore printed that diagnostic three times instead of CPython's
`True\\nFalse\\nTrue` -- a silent wrong value, exit 0.

This file pins the `issubclass(...)` weak-stub bug from the recover-land gate
(part 4 of that gate's split; the fix deleted its doc): it compiles the probe,
requires no stub in the generated `.ci`, builds it with the project's own gcc,
and compares stdout with CPython's on the same source. It also pins the two
edges of the new arm:

* a module-qualified class name (`m.Derived`) answers like the bare name;
* `issubclass(1, object)` is an honest compile-time refusal, never a silent
  `False` and never a stub;
* the compiler's own guard shape `isinstance(value, type) and
  issubclass(value, BaseException)` compiles stub-free.

Run:  python3 test_issubclass_builtin.py
"""
import os
import re
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from gimple_codegen import compile_to_gimple  # noqa: E402
from build_config import find_gcc  # noqa: E402
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S  # noqa: E402

_RUNTIME = os.path.join(_HERE, 'runtime')
_STUB = 'unavailable in compiled mode'

_PROBE = '''\
class Base:
    pass

class Derived(Base):
    pass

def f():
    print(issubclass(Derived, Base))
    print(issubclass(Base, Derived))
    print(issubclass(Derived, object))

f()
'''

# Same classes through a module qualifier: `m.Derived` / `m.Base` / `m.object`.
_QUALIFIED_PROBE = '''\
import issubclass_probe_m as m

def f():
    print(issubclass(m.Derived, m.Base))
    print(issubclass(m.Base, m.Derived))
    print(issubclass(m.Derived, object))

f()
'''

_QUALIFIED_MODULE = '''\
class Base:
    pass

class Derived(Base):
    pass
'''

# The compiler's own use (myinterpreter.py: isinstance(value, type) and
# issubclass(value, BaseException)): a boxed word whose kind is only known at
# run time. It must lower to the class-table query, not the stub.
_GUARD_SHAPE = '''\
class BaseException:
    pass

class ValueError(BaseException):
    pass

def is_exc(value):
    return isinstance(value, type) and issubclass(value, ValueError)

def f():
    print(type(is_exc(ValueError)))

f()
'''

_REFUSAL = '''\
class Base:
    pass

def f():
    print(issubclass(1, object))

f()
'''

_TUPLE_PROBE = '''\
class Base:
    pass

class Derived(Base):
    pass

def f():
    print(issubclass(Derived, (Base, Derived)))
    print(issubclass(Base, (Derived,)))
    print(issubclass(Derived, ()))

f()
'''


def _cpython(src: str, td: str):
    """CPython's stdout for the same program (annotations stripped)."""
    py = '\n'.join(re.sub(r'\bvar\s+', '', ln) for ln in src.splitlines()) + '\n'
    path = os.path.join(td, 'ref.py')
    with open(path, 'w') as fh:
        fh.write(py)
    p = subprocess.run([sys.executable, path], capture_output=True,
                       text=True, timeout=RUN_TIMEOUT_S, cwd=td)
    assert p.returncode == 0, p.stderr[-2000:]
    return p.stdout


def _build_and_run(c_src: str, td: str, name: str):
    c_file = os.path.join(td, name + '.c')
    exe = os.path.join(td, name)
    with open(c_file, 'w') as fh:
        fh.write(c_src)
    cc = subprocess.run(
        [find_gcc(), '-fgimple', '-x', 'c', f'-I{_RUNTIME}', '-o', exe,
         c_file, os.path.join(_RUNTIME, 'fire_runtime.c'), '-lm'],
        capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    assert cc.returncode == 0, cc.stderr[-3000:]
    p = subprocess.run([exe], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S)
    return p.stdout, p.returncode, p.stderr


def test_probe_matches_cpython():
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td:
        c_src = compile_to_gimple(_PROBE, do_imports=False, filename='probe.mojo')
        assert _STUB not in c_src, 'issubclass fell through to the weak stub'
        out, rc, err = _build_and_run(c_src, td, 'probe')
        want = _cpython(_PROBE, td)
    assert rc == 0, err[-2000:]
    assert out == want == 'True\nFalse\nTrue\n', (out, want)


def test_module_qualified_class_names_match_cpython():
    old = os.getcwd()
    try:
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td:
            # The compiler's sibling-import search starts from the importing
            # file's directory, so the fixture and the probe live together in
            # the temp dir. CPython's reference run needs the same module.
            with open(os.path.join(td, 'issubclass_probe_m.mojo'), 'w') as fh:
                fh.write(_QUALIFIED_MODULE)
            with open(os.path.join(td, 'issubclass_probe_m.py'), 'w') as fh:
                fh.write(_QUALIFIED_MODULE)
            os.chdir(td)
            try:
                c_src = compile_to_gimple(
                    _QUALIFIED_PROBE, do_imports=True,
                    filename=os.path.join(td, 'qualified.mojo'))
            finally:
                os.chdir(old)
            assert _STUB not in c_src, 'a module-qualified class hit the weak stub'
            out, rc, err = _build_and_run(c_src, td, 'qualified')
            want = _cpython(_QUALIFIED_PROBE, td)
    finally:
        os.chdir(old)
    assert rc == 0, err[-2000:]
    assert out == want == 'True\nFalse\nTrue\n', (out, want)


def test_guard_shape_is_stub_free():
    c_src = compile_to_gimple(_GUARD_SHAPE, do_imports=False,
                              filename='guard.mojo')
    assert _STUB not in c_src, 'the isinstance(value, type) and issubclass(...) shape hit the stub'
    assert 'mojo_issubclass_rtclass' in c_src


def test_tuple_of_classes_matches_cpython():
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td:
        c_src = compile_to_gimple(_TUPLE_PROBE, do_imports=False,
                                  filename='tuple.mojo')
        assert _STUB not in c_src, 'a tuple of classes hit the weak stub'
        out, rc, err = _build_and_run(c_src, td, 'tuple')
        want = _cpython(_TUPLE_PROBE, td)
    assert rc == 0, err[-2000:]
    assert out == want == 'True\nFalse\nFalse\n', (out, want)


def test_non_class_operand_is_a_compile_time_refusal():
    try:
        compile_to_gimple(_REFUSAL, do_imports=False, filename='refusal.mojo')
    except RuntimeError as e:
        msg = str(e)
        assert 'issubclass' in msg, msg
    else:
        raise AssertionError('issubclass(1, object) compiled without a refusal')
    # A container LITERAL is proven non-class by its AST shape too.
    try:
        compile_to_gimple('def f():\n    return issubclass([], object)\n',
                          do_imports=False, filename='refusal2.mojo')
    except RuntimeError as e:
        assert 'issubclass' in str(e), e
    else:
        raise AssertionError('issubclass([], object) compiled without a refusal')


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
            except AssertionError as e:
                failures += 1
                print('FAIL ', name, e)
            else:
                print('PASS ', name)
    print('FAILURES:', failures)
    sys.exit(1 if failures else 0)
