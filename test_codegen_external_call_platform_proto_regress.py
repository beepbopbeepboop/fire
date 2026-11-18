#!/usr/bin/env python3
"""Regression: external_call must not emit a prototype that conflicts with a
platform header, and must type args from the known C signature when one exists.

Covers: nanosleep external_call proto/conflicting-decl and pointer arg typing.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_stdlib_dylib as b


def _compile_and_check(src, name):
    c = b.compile_module_to_c(src, name + '.mojo', name, linkable=False)
    # nanosleep is declared by <time.h> in the prelude: no self-emitted proto.
    for line in c.splitlines():
        if line.strip().startswith('extern ') and 'nanosleep' in line:
            raise AssertionError(
                'self-emitted nanosleep prototype conflicts with platform header:\n'
                + line)
    with tempfile.TemporaryDirectory(dir=os.path.join(HERE, '.tmp')) as td:
        path = os.path.join(td, name + '.c')
        with open(path, 'w') as f:
            f.write(c)
        r = subprocess.run(
            ['gcc-mp-15', '-fgimple', '-fsyntax-only',
             '-D__MOJO_STDLIB_MODE__', '-Iruntime', path],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(
                'generated C did not syntax-check:\n' + r.stderr + '\n' + r.stdout)


def test_nanosleep_null_pointer_arg_uses_platform_signature():
    # The second argument is a null/zero value bound to a pointer parameter in
    # the platform signature; it must be passed as a pointer, not an int64_t,
    # and no conflicting prototype may be emitted.
    src = r'''
from sys.ffi import external_call

struct _CTimeSpec:
    var tv_sec: Int
    var tv_nsec: Int

def f():
    var tv = _CTimeSpec(0, 0)
    var req = Pointer(to=tv)
    _ = external_call["nanosleep", Int32](req, Int64(0))
'''
    _compile_and_check(src, 'nano_null')


def test_nanosleep_pointer_args_use_platform_signature():
    src = r'''
from sys.ffi import external_call

struct _CTimeSpec:
    var tv_sec: Int
    var tv_nsec: Int

def f():
    var tv = _CTimeSpec(0, 0)
    var req = Pointer(to=tv)
    var rem = Pointer(to=tv)
    _ = external_call["nanosleep", Int32](req, rem)
'''
    _compile_and_check(src, 'nano_ptr')


if __name__ == '__main__':
    tests = [test_nanosleep_null_pointer_arg_uses_platform_signature,
             test_nanosleep_pointer_args_use_platform_signature]
    for t in tests:
        t()
        print('ok', t.__name__)
