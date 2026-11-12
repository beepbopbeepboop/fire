"""Quick probe for CODEGEN_simd_and_array_values_erase_to_int64-part2-part1.

Passes when float SIMD constructors are lowered with preserved scalar dtype
instead of the erased `int64_t` placeholder path.
"""
import sys
sys.path.insert(0, '.')
import build_stdlib_dylib as b


def main():
    src = 'def f():\n    var v = SIMD[DType.float32, 2](1.0)\n    return v\n'
    c = b.compile_module_to_c(src, 'simd_ctor.mojo', 'simd_ctor', linkable=False)
    # Today this lowers as: _t1 = (int64_t)0;  /* indirect call via SubscriptExpr */
    assert 'indirect call via SubscriptExpr' not in c, c
    # A float SIMD constructor must carry float-typed representation, not pure
    # int64_t erasure of the constructed value.
    assert 'int64_t v;' not in c or 'float' in c or 'double' in c, c
    print('ok')


if __name__ == '__main__':
    main()
