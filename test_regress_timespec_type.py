"""Regression test for STDLIB std/sys/_libc.mojo 'unknown type name timespec'.

The stdlib `_libc.mojo` declares `struct timespec`, a C system struct. The
codegen must give that name a typedef in the generated C so bare `timespec`
references resolve (`typedef struct timespec timespec;`, emitted by
`_gmp_emit_struct_definitions` in mojo/backend_gimple/module_gen.py for
names in `_system_structs`). Before that typedef was emitted, gcc reported
"unknown type name 'timespec'" for the generated code.

The check is self-contained: it compiles a small module declaring a struct
of that name through the same codegen the stdlib uses, and gcc-checks the
result. It does not depend on which stdlib checkout is installed (the
checkout the stdlib compile defaults to no longer declares `timespec`, so a
whole-stdlib run cannot observe this regression).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_stdlib_dylib import compile_module_to_c  # noqa: E402
from compile_stdlib import _gcc_syntax_cached  # noqa: E402

_SRC = '''\
comptime time_t = Int64


@fieldwise_init
struct timespec(TrivialRegisterPassable, Writable):
    """C `struct timespec`: a time in seconds and nanoseconds."""

    var tv_sec: time_t
    var tv_nsec: Int64


def make_ts(sec: Int64) -> timespec:
    return timespec(sec, 0)


def ts_sec(t: timespec) -> Int64:
    return t.tv_sec
'''


def test_libc_timespec_compiles():
    c_src = compile_module_to_c(_SRC, os.path.join(HERE, 'timespec_probe.mojo'),
                                'timespec_probe')
    assert 'typedef struct timespec timespec;' in c_src, \
        'system struct timespec has no typedef in the generated C'
    _rc, err = _gcc_syntax_cached(c_src)
    assert "unknown type name 'timespec'" not in err, err


if __name__ == "__main__":
    test_libc_timespec_compiles()
    print("OK")
