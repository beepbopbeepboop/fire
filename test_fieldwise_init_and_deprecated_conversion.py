#!/usr/bin/env python3
"""Regression: (C) `S[1, c=9]()` of a field-less `@fieldwise_init` struct with an
unbound bracket parameter is `no matching function in initialization`, its
candidates being the two SYNTHESIZED constructors (shown as generated
signatures, with the struct's note), and (D) an integer literal implicitly
converted through `@implicit(deprecated=True)` is a WARNING, with the `T(  )`
fix-it line -- warnings do not stop the program. Expected text captured from
`tools/mojo build -I` (DIAGNOSTICS_formatting_modular part 1, groups C and D)."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')

PACKAGE = '@fieldwise_init\nstruct PosOnlyStruct[a: Int, b: Int, /, c: Int = 9]:\n    pass\n\n\nstruct Dep:\n    @implicit(deprecated=True)\n    def __init__(out self, value: Int):\n        pass\n'

MAIN = 'import pk\n\n\ndef main():\n    _ = pk.PosOnlyStruct[1, c=9]()\n    _ = pk.PosOnlyStruct[1, 2]()\n    _: pk.Dep = 1\n    _: pk.Dep = 123\n    print("ran")\n'

WANT = "M:5:33: error: no matching function in initialization\n    _ = pk.PosOnlyStruct[1, c=9]()\n        ~~~~~~~~~~~~~~~~~~~~~~~~^~\nImported from M:1:\nP:2:1: note: candidate not viable: missing required argument: 'move'\ndef __init__(out self, *, deinit move: Self)    # note - generated function\n^\nImported from M:1:\nP:2:1: note: candidate not viable: failed to infer parameter 'b' of parent struct 'PosOnlyStruct'\ndef __init__(out self)    # note - generated function\n^\nImported from M:1:\nP:2:8: note:  struct declared here\nstruct PosOnlyStruct[a: Int, b: Int, /, c: Int = 9]:\n       ^\nM:7:17: warning: deprecated implicit conversion from 'IntLiteral[1]' to 'Dep'\n    _: pk.Dep = 1\n                ^\nM:7:17: note: call 'Dep(...)' explicitly\n    _: pk.Dep = 1\n                ^\n                Dep( )\nImported from M:1:\nP:8:9: note: implicit constructor for 'Dep' declared here\n    def __init__(out self, value: Int):\n        ^\nM:8:17: warning: deprecated implicit conversion from 'IntLiteral[123]' to 'Dep'\n    _: pk.Dep = 123\n                ^~~\nM:8:17: note: call 'Dep(...)' explicitly\n    _: pk.Dep = 123\n                ^~~\n                Dep( )\nImported from M:1:\nP:8:9: note: implicit constructor for 'Dep' declared here\n    def __init__(out self, value: Int):\n        ^\n"

WARN_ONLY = '''import pk


def main():
    _: pk.Dep = 1
    print("ran")
'''


def run(main_src):
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, 'pk'))
        pk = os.path.join(d, 'pk', '__init__.mojo')
        open(pk, 'w').write(PACKAGE)
        m = os.path.join(d, 'm.mojo')
        open(m, 'w').write(main_src)
        p = subprocess.run([sys.executable, FIRE, 'run', m],
                           capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout, p.stderr.replace(pk, 'P').replace(m, 'M')


def test_synthesized_constructor_candidates_and_deprecated_conversion():
    rc, out, err = run(MAIN)
    assert rc == 1 and out == '' and err == WANT, err


def test_a_warning_alone_does_not_stop_the_program():
    rc, out, err = run(WARN_ONLY)
    assert rc == 0 and out == 'ran\n', (rc, out, err)
    assert 'warning: deprecated implicit conversion from' in err, err
    assert 'error' not in err, err


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all tests passed')
