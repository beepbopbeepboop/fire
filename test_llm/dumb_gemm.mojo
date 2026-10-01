# The "dumb" GEMM: a naive triple loop, written the way anyone would.
#
# This is the input to the auto-metalisation. It is deliberately the most
# obvious possible implementation of C = A @ B, because the point is not that
# this code is good -- it is that this is the code a person actually writes,
# and that the compiler should be able to recognise IT rather than requiring
# the author to hand-write a @gpu kernel and learn simdgroup_matrix.
#
# The tensor-core replacement lives in test_llm/gemm_tensorcore.m and reaches
# 0.96 TFLOPS, about 20x the scalar path. So the target for auto-metalisation
# is a 20x speedup on THIS function, with no change to how it is written.
#
# Notes on shape, all of which the recogniser has to cope with:
#   * a triple nest, which the current recogniser refuses outright
#   * the trip counts are parameters (m, k, n), not attributes
#   * A is indexed [i*k + p] -- an AFFINE index, which is also refused today
#   * C accumulates: c[i*n + j] = c[i*n + j] + a[i*k + p] * b[p*n + j], so the
#     output is read-modify-write, the aliasing case the recogniser refuses
#
# Every one of those refusals was a deliberate, measured decision. This file is
# the case that overturns them, so each has to be re-earned rather than
# assumed -- and the correctness check below is what re-earns them.


def gemm_dumb(
    A: List[Float32],
    B: List[Float32],
    C: List[Float32],
    m: Int,
    k: Int,
    n: Int,
):
    # C = A @ B, the textbook triple loop.
    for i in range(m):
        for j in range(n):
            acc: Float32 = 0.0
            for p in range(k):
                acc = acc + A[i * k + p] * B[p * n + j]
            C[i * n + j] = acc


def main():
    # Small enough to check element by element, large enough that the triple
    # loop is genuinely O(m*n*k) and worth replacing.
    m = 64
    k = 64
    n = 64

    A = [0.0] * (m * k)
    B = [0.0] * (k * n)
    C = [0.0] * (m * n)
    # Values are exact multiples of 1/16 in [-0.5, 0.5]. Products are multiples
    # of 1/256 and a 64-term sum stays under 4, so every partial sum is exactly
    # representable in f32. That makes the whole GEMM order-independent in f32:
    # the tensor-core kernel reduces in a different ORDER than this loop, and
    # the two must agree BIT-EXACTLY rather than to within a tolerance. A
    # tolerance check would hide a transposition, which is the most likely way
    # for a GEMM rewrite to be wrong while still looking plausible.
    for i in range(m * k):
        A[i] = Float32((i * 37) % 17) * 0.0625 - 0.5
    for i in range(k * n):
        B[i] = Float32((i * 53) % 13) * 0.0625 - 0.25

    gemm_dumb(A, B, C, m, k, n)

    # A checksum AND the elements the C harness also prints, so the two can be
    # compared value by value rather than in aggregate. An aggregate can hide a
    # transposition, which is the single most likely way for a GEMM rewrite to
    # be wrong while still producing a plausible number.
    var total: Float64 = 0.0
    for i in range(m * n):
        total = total + Float64(C[i])
    print("checksum", total)
    print("elems", C[0], C[1], C[63], C[64], C[4095])
    print("kernels", _mojo_gpu_kernel_count())
    print("d", _mojo_gpu_dispatch_count())
    print("f", _mojo_gpu_failure_count())
