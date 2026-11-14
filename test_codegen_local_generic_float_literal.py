#!/usr/bin/env python3
"""Regression test for bug:CODEGEN_local_generic_float_literal_arg_erases_to_int64.

A module-local generic called with a float literal (`absorb(1.0)`) must
instantiate at the literal's own type (`Float64`, C `double`). Before the fix,
the harness compiled the module from an in-memory source string whose path did
not exist on disk, and the text-only generic discovery in `module_gen`
(`_gsrc`) read nothing. `absorb` was then lowered as an ordinary function with
`T` erased to `int64_t`, and the float literal was truncated at the call site.

The source is passed in memory and the path is deliberately NOT created, which
is exactly the shape `compile_module_to_c` callers use. The real driver stashes
`gen._source_text`; the harness must do the same.

Run:  python3 test_codegen_local_generic_float_literal.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_stdlib_dylib as b

ABSORB_SRC = (
    'def absorb[T](x: T) -> T where T.is_floating_point():\n'
    '    return x\n'
    '\n'
    'def f():\n'
    '    var r = absorb(1.0)\n'
    '    return r\n'
)

# A path that does not exist on disk: the in-memory source is the only copy.
MISSING_PATH = os.path.join(HERE, 'no_such_dir_local_generic_float', 'absorb_mem.mojo')


def _compile_in_memory(src):
    assert not os.path.exists(MISSING_PATH), MISSING_PATH
    return b.compile_module_to_c(src, MISSING_PATH, 'absorb_mem', linkable=False)


def test_float_literal_instantiates_at_float64():
    c = _compile_in_memory(ABSORB_SRC)
    # The literal's C type is `double`, so the instance is the Float64 one.
    assert re.search(r'\babsorb_\w*_Float64\s*\(\s*double\b', c), (
        'no Float64 instantiation of absorb taking a double:\n' + c)
    # And the caller passes the literal through unconverted.
    assert re.search(r'\(\s*1\.0\s*\)', c), c


def test_float_literal_never_emits_int64_instance():
    c = _compile_in_memory(ABSORB_SRC)
    # The erased instance this bug emitted: a definition of `absorb_*` whose
    # parameter is int64_t.
    bad = re.findall(r'\bint64_t\s+absorb\w*\s*\(\s*int64_t\b', c)
    assert not bad, 'int64_t instance of absorb emitted:\n' + c


if __name__ == '__main__':
    names = sorted(n for n, f in list(globals().items())
                   if n.startswith('test_') and callable(f))
    for name in names:
        globals()[name]()
        print('ok', name)
    print('all tests passed')
