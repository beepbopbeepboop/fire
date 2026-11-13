#!/usr/bin/env python3
"""Regression test: float bit reinterpretation (the stdlib-syntax red).

A width-1 float scalar's bit accessors (`x.to_bits()`, `x._to_bits_signed()`)
and the bit-level constructors (`bitcast[Float32, 1](bits)`,
`SIMD[Float32, 1](from_bits=bits)`) answer the IEEE-754 bit pattern, as their
stdlib signatures say. Before this, the accessors fell through to the generic
scalar-method stub, which answers the receiver unchanged, and `bitcast` /
`from_bits` fell to `(int64_t)0`. Both are silent wrong answers, and once the
float SIMD annotation resolved to `float` the accessor result was `float & int`,
which gcc rejected in std/math's frexp and std/utils's isinf/isnan.

The program prints only integers (the bit patterns), so the expected output is
computed with `struct` and compared exactly, with no float formatting in play.
"""

import os
import struct
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from gimple_codegen import compile_to_gimple  # noqa: E402
from monomorphize import find_gcc  # noqa: E402

_RUNTIME = os.path.join(_HERE, 'runtime')

_SRC = '''\
def bits_of(x: SIMD[Float32, 1]) -> Int64:
    return x.to_bits()

def signed_bits_of(x: SIMD[Float32, 1]) -> Int64:
    return x._to_bits_signed()

def dbits_of(x: SIMD[Float64, 1]) -> Int64:
    return x.to_bits()

def float_of(b: Int64) -> SIMD[Float32, 1]:
    return bitcast[Float32, 1](b)

def double_of(b: Int64) -> SIMD[Float64, 1]:
    return bitcast[Float64, 1](b)

def float_from_bits(b: Int64) -> SIMD[Float32, 1]:
    return SIMD[Float32, 1](from_bits=b)

def round_trip(x: SIMD[Float32, 1]) -> SIMD[Float32, 1]:
    return bitcast[Float32, 1](x.to_bits())

def main():
    print(bits_of(1.5))
    print(bits_of(-1.5))
    print(signed_bits_of(-1.5))
    print(dbits_of(1.5))
    print(bits_of(float_of(1069547520)))
    print(dbits_of(double_of(4609434218613702656)))
    print(bits_of(float_from_bits(2139095040)))
    print(bits_of(round_trip(0.1)))
'''


def _expected():
    u32 = lambda f: struct.unpack('<I', struct.pack('<f', f))[0]  # noqa: E731
    neg = u32(-1.5)
    signed = neg - (1 << 32) if neg >= (1 << 31) else neg
    return [
        str(u32(1.5)),
        str(neg),
        str(signed),
        str(struct.unpack('<Q', struct.pack('<d', 1.5))[0]),
        str(u32(1.5)),
        str(struct.unpack('<Q', struct.pack('<d', 1.5))[0]),
        str(u32(float('inf'))),
        str(u32(0.1)),
    ]


def test_float_bit_reinterpretation_runs_and_matches_ieee754():
    c_src = compile_to_gimple(_SRC, do_imports=False, filename='bits.mojo')
    gcc = find_gcc()
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td:
        c_file = os.path.join(td, 'bits.c')
        exe = os.path.join(td, 'bits.exe')
        with open(c_file, 'w') as fh:
            fh.write(c_src)
        cc = subprocess.run(
            [gcc, '-fgimple', '-x', 'c', f'-I{_RUNTIME}', '-o', exe, c_file,
             os.path.join(_RUNTIME, 'fire_runtime.c'), '-lm'],
            capture_output=True, text=True, timeout=600)
        assert cc.returncode == 0, cc.stderr[-2000:]
        run = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    got = run.stdout.split()
    want = _expected()
    assert got == want, f'got {got!r}, want {want!r}'


def test_bitcast_is_not_the_zero_stub():
    c_src = compile_to_gimple(_SRC, do_imports=False, filename='bits.mojo')
    assert 'indirect call via' not in c_src, 'a bitcast/from_bits call was stubbed'
    assert 'float.to_bits() stubbed' not in c_src
    assert 'mojo_float_to_bits' in c_src and 'mojo_float_from_bits' in c_src


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('PASS ', name)
            except AssertionError as e:
                failures += 1
                print('FAIL ', name, e)
    print('FAILURES:', failures)
    sys.exit(1 if failures else 0)
