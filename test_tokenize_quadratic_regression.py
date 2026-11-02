#!/usr/bin/env python3
"""Quick regression test for CODEGEN_selfhost_tokenize_region_eq_quadratic.

The tokenizer should be roughly linear in input size (O(n)), not quadratic.
We test by timing py_tokenize on synthetic inputs of size N and 2N.
"""
import time
import fire_compiler


def make_docstring_src(n):
    # Generate n triple-quoted docstrings separated by simple code
    parts = []
    for i in range(n):
        parts.append(f'"""docstring number {i} with some content {i}"""')
        parts.append(f'x{i} = {i}\n')
    return '\n'.join(parts)


def test_tokenize_linear():
    # Warm up
    src_small = make_docstring_src(5)
    fire_compiler.py_tokenize(src_small)
    
    # Time for N and 2N
    n = 50
    src_n = make_docstring_src(n)
    src_2n = make_docstring_src(2*n)
    
    t0 = time.time()
    toks_n = fire_compiler.py_tokenize(src_n)
    t1 = time.time()
    toks_2n = fire_compiler.py_tokenize(src_2n)
    t2 = time.time()
    
    time_n = t1 - t0
    time_2n = t2 - t1
    
    # Should be roughly linear (ratio ~2). With quadratic, ratio would be ~4.
    # Allow some slack for overhead, but require ratio < 3.0
    ratio = time_2n / time_n if time_n > 0 else float('inf')
    print(f"time_n={time_n:.4f}s, time_2n={time_2n:.4f}s, ratio={ratio:.2f}")
    assert ratio < 3.0, f"Tokenization appears quadratic: ratio={ratio:.2f} >= 3.0"
    assert len(toks_n) > 0 and len(toks_2n) > 0


if __name__ == '__main__':
    test_tokenize_linear()
    print("ok")
