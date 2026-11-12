"""Quick probe for CODEGEN_simd_and_array_values_erase_to_int64-part2-part2.

Passes when float SIMD values are not typed/mapped as plain Int64 in lowered
call argument contexts.
"""
import sys
sys.path.insert(0, '.')
import build_stdlib_dylib as b


def main():
    # A float SIMD value passed through should retain float element typing in
    # the emitted C, not be erased to int64_t argument storage.
    src = (
        'def id_simd(x: SIMD[DType.float32, 2]) -> SIMD[DType.float32, 2]:\n'
        '    return x\n'
        '\n'
        'def f():\n'
        '    var v = SIMD[DType.float32, 2](1.0)\n'
        '    var r = id_simd(v)\n'
        '    return r\n'
    )
    c = b.compile_module_to_c(src, 'simd_arg.mojo', 'simd_arg', linkable=False)
    # Erased path today: arguments/values become plain int64_t.
    # Fixed path must preserve float typing for the SIMD float32 values.
    assert 'indirect call via SubscriptExpr' not in c, c
    assert 'float' in c or 'double' in c, c
    # The returned/local SIMD float32 value must not be represented solely as
    # int64_t in this probe.
    assert 'int64_t r;' not in c, c
    print('ok')


if __name__ == '__main__':
    main()
