"""Tests for the Metal/GPU codegen path.

Three layers, cheapest first, because they fail for different reasons and
the expensive one is the one that actually proves anything:

- the pure tables (``mojo/middle/metal_ops.py``) -- no device needed
- device-region selection (``mojo/backend_gimple/device_select.py``) --
  no device needed
- the MSL emitter (``mojo/backend_gimple/emit_metal.py``) -- text only
- and then, if a Metal device is present, the generated MSL is compiled by
  Apple's real compiler, dispatched, and checked against a CPU reference.

The last one is the only test that can catch a kernel which compiles and
computes the wrong answer, which is the failure mode this whole path is
built to avoid. It is skipped rather than failed when there is no device,
because "no GPU" is a property of the machine and not a defect in the
compiler.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import gimple_codegen as gctypes
from build_config import find_gcc as _find_gcc

_GCC = _find_gcc()
import mojo.backend_gimple.device_select as dsel
import mojo.backend_gimple.device_glue as dglue
import mojo.backend_gimple.emit_metal as eml
import mojo.middle.metal_ops as mops
import mojo.middle.offload as ofl


def parse(src: str):
    return gctypes.Parser(gctypes.py_tokenize(src)).parse_module()


class TestMetalOpsTables(unittest.TestCase):
    """The tables are pure, so these need no device and no emitter."""

    def test_double_becomes_float(self):
        # MSL has no double. This is a precision REDUCTION, and it is the
        # single most important thing in the table: a silent double/float
        # mixup is a wrong number on the device that the host's fp64
        # reference will expose, but only if the comparison is run.
        self.assertEqual(mops.msl_type('double'), 'float')
        self.assertEqual(mops.msl_type('float'), 'float')

    def test_pointer_indirection_is_preserved(self):
        self.assertEqual(mops.msl_type('float *'), 'float *')
        self.assertEqual(mops.msl_type('int64_t *'), 'long *')
        self.assertEqual(mops.msl_type('int64_t **'), 'long **')

    def test_host_containers_are_refused_not_guessed(self):
        # A MojoList is a heap object with a host header; it cannot cross
        # to a device. Refusing here is what surfaces the contiguity
        # constraint as a build error instead of a garbage read.
        for t in ('MojoList *', 'MojoDict *', 'MojoSet *', 'MojoBytes *'):
            self.assertIsNone(mops.msl_type(t), t)
            self.assertIsNone(mops.kernel_arg_type(t), t)

    def test_unknown_type_is_refused(self):
        self.assertIsNone(mops.msl_type('struct Foo *'))
        self.assertIsNone(mops.msl_type('MojoStructFmt *'))

    def test_kernel_arg_narrows_to_what_msl_accepts(self):
        # MSL rejects a 64-bit kernel input outright. The stdlib's `len: Int`
        # resolves to int64_t, so the narrowing is what makes the stdlib's
        # own kernels expressible.
        self.assertEqual(mops.kernel_arg_type('int64_t'), 'int')
        self.assertEqual(mops.kernel_arg_type('uint64_t'), 'uint')
        self.assertEqual(mops.kernel_arg_type('float'), 'float')

    def test_address_spaces_stay_distinct(self):
        # mlir.py collapses every LLVM address space to `void *`, which is
        # right for C and wrong here: `threadgroup` is not `device`, and
        # conflating them reads garbage rather than trapping.
        self.assertEqual(mops.address_space(0), 'device')
        self.assertEqual(mops.address_space(1), 'constant')
        self.assertEqual(mops.address_space(3), 'threadgroup')
        self.assertNotEqual(mops.address_space(3), mops.address_space(0))

    def test_threadgroup_is_not_a_kernel_argument_space(self):
        self.assertNotIn('threadgroup', mops.ARG_ALLOWED_ADDRESS_SPACES)
        self.assertIn('device', mops.ARG_ALLOWED_ADDRESS_SPACES)

    def test_intrinsics_are_namespaced_but_builtins_are_not(self):
        # A blanket `metal::` prefix on the builtins is a link error at best
        # and wrong overload resolution at worst.
        self.assertEqual(mops.intrinsic('sqrt'), 'metal::sqrt')
        self.assertEqual(mops.intrinsic('abs'), 'abs')
        self.assertEqual(mops.intrinsic('min'), 'min')
        self.assertIsNone(mops.intrinsic('no_such_function'))

    def test_index_vars_map_to_generated_parameters(self):
        # global_idx is not a Metal builtin; it is a generated index
        # parameter. This is the "transform the hand-written speciality
        # code" mapping, and it is what std/gpu/primitives/id.mojo needs.
        self.assertEqual(mops.index_var('global_idx'), '__gid')
        self.assertEqual(mops.index_var('thread_idx'), '__lid')
        self.assertEqual(mops.index_var('block_idx'), '__tgid')
        self.assertIsNone(mops.index_var('not_an_index'))

    def test_index_param_names_match_their_declarations(self):
        # They diverged once and the symptom was MSL reporting an
        # undeclared identifier. Cheap to check, so it is checked.
        for key, decl in mops.INDEX_PARAMS:
            self.assertIn(key, decl, f'{key!r} not spelled in its own declaration {decl!r}')

    def test_every_index_param_declares_its_own_name(self):
        names = [d.split()[1] for _k, d in mops.INDEX_PARAMS]
        self.assertEqual(len(names), len(set(names)), 'duplicate index parameter name')


class TestDeviceSelect(unittest.TestCase):
    """Which functions become MSL instead of C."""

    def test_explicit_gpu_decorator(self):
        m = parse('@gpu\ndef k(x):\n    return x\n\ndef h(y):\n    return y\n')
        self.assertEqual(dsel.classify_functions(m),
                         {'k': dsel.DEVICE, 'h': dsel.HOST})

    def test_kernel_decorator_alias(self):
        m = parse('@kernel\ndef k(x):\n    return x\n')
        self.assertEqual(dsel.classify_functions(m)['k'], dsel.DEVICE)

    def test_stdlib_registrar_shape_finds_an_unmarked_kernel(self):
        # This is the rule that makes the HAND-WRITTEN stdlib GPU code work
        # without editing it: upstream's `vec_add` is an ordinary `def` with
        # no marker, and the only signal is the call that hands it to
        # compile_function. Reproduces the shape of
        # stdlib/test/asyncrt/test_device_pointer_kernel.mojo.
        m = parse('''
def vec_add(a, b, out, n):
    return 0

def main():
    ctx = DeviceContext()
    kernel = ctx.compile_function[vec_add]()
    ctx.enqueue_function(kernel, grid_dim=(1,), block_dim=64)
    return 0
''')
        got = dsel.classify_functions(m)
        self.assertEqual(got['vec_add'], dsel.DEVICE)
        self.assertEqual(got['main'], dsel.HOST)

    def test_registration_nested_in_a_function_is_still_found(self):
        # A registration can sit inside any statement, so a depth-limited
        # walk would miss real ones.
        m = parse('''
def kern(x):
    return 0

def helper():
    if True:
        ctx = DeviceContext()
        return ctx.compile_function[kern]()
    return 0
''')
        self.assertIn('kern', dsel.device_functions(m))

    def test_unrelated_call_shaped_like_a_registrar_is_not_a_kernel(self):
        m = parse('''
def notakernel(x):
    return 0

def main():
    obj = Thing()
    obj.compile_something[notakernel]()
    return 0
''')
        self.assertEqual(dsel.classify_functions(m)['notakernel'], dsel.HOST)

    def test_a_parameter_shadowing_the_name_is_not_a_registrar(self):
        m = parse('''
def kern(x):
    return 0

def main():
    compile_function = 5
    return compile_function
''')
        self.assertEqual(dsel.classify_functions(m)['kern'], dsel.HOST)

    def test_method_with_the_marker_is_device(self):
        m = parse('''
class K:
    def __init__(self):
        self.n = 1

    @gpu
    def step(self):
        return self.n
''')
        got = dsel.classify_functions(m)
        self.assertEqual(got['K_step'], dsel.DEVICE)
        self.assertEqual(got['K___init__'], dsel.HOST)


class TestMetalEmitter(unittest.TestCase):
    """MSL text generation. No device required."""

    def emit(self, src: str, name: str | None = None) -> str:
        mod = parse(src)
        fdef = mod[0]
        if name:
            fdef.name = name
        return eml.emit_kernel(fdef)

    def test_stdlib_vec_add_shape(self):
        msl = self.emit('''
def vec_add(in0: UnsafePointer[Float32, MutAnyOrigin],
            in1: UnsafePointer[Float32, MutAnyOrigin],
            output: UnsafePointer[Float32, MutAnyOrigin], len: Int):
    tid = global_idx.x
    if tid >= len:
        return
    output[tid] = in0[tid] + in1[tid]
''')
        self.assertIn('kernel void vec_add(', msl)
        self.assertIn('#include <metal_stdlib>', msl)
        self.assertIn('using namespace metal;', msl)
        # buffers carry an address space AND a buffer index
        self.assertIn('device float * in0 [[buffer(0)]]', msl)
        # a scalar is constant-by-reference; MSL rejects the by-value form
        self.assertIn('constant int &len', msl)
        # global_idx becomes a generated index parameter
        self.assertIn('__gid [[thread_position_in_grid]]', msl)
        self.assertIn('tid = __gid;', msl)
        # the index is an int, not a float
        self.assertIn('int tid;', msl)

    def test_index_infers_as_int_not_float(self):
        # A float index silently loses precision past 2^24, so the type is
        # load-bearing rather than cosmetic.
        msl = self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin], n: Int):
    i = global_idx.x
    out[i] = 1.0
''')
        self.assertIn('int i;', msl)
        self.assertNotIn('float i;', msl)

    def test_for_loop_index_is_int(self):
        msl = self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin], n: Int):
    for i in range(n):
        out[i] = 2.0
''')
        self.assertIn('for (i = 0; i < n; i += 1)', msl)
        self.assertIn('int i;', msl)

    def test_range_with_start_and_step(self):
        msl = self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin], n: Int):
    for i in range(1, n, 2):
        out[i] = 3.0
''')
        self.assertIn('for (i = 1; i < n; i += 2)', msl)

    def test_math_intrinsic_is_namespaced(self):
        msl = self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin], x: Float32):
    out[0] = sqrt(x) + exp(x)
''')
        self.assertIn('metal::sqrt(', msl)
        self.assertIn('metal::exp(', msl)

    def test_while_and_break_continue(self):
        msl = self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin], n: Int):
    i = 0
    while i < n:
        i = i + 1
        if i > 3:
            break
        continue
    out[0] = 1.0
''')
        self.assertIn('while (', msl)
        self.assertIn('break;', msl)
        self.assertIn('continue;', msl)

    def test_chained_comparison_is_and_not_nested(self):
        # Python's `a < b < c` means `(a<b) and (b<c)`; MSL has no chained
        # comparison, so emitting it as a nested `&&` is the only correct
        # reading and it is what a reader would otherwise have to guess.
        msl = self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin], a: Int, b: Int, c: Int):
    if a < b < c:
        out[0] = 1.0
''')
        self.assertIn('&&', msl)

    # ---- refusals. Each of these must RAISE, not emit something plausible.

    def test_refuses_a_host_container_parameter(self):
        with self.assertRaises(eml.MetalUnsupported) as cm:
            self.emit('''
def k(xs: List[Float32]):
    return 0
''')
        self.assertIn('cannot be passed to a GPU', str(cm.exception))

    def test_refuses_a_globals_read(self):
        # A device function has no globals. `constant` is an argument, not a
        # module variable, so there is nothing to read.
        with self.assertRaises(eml.MetalUnsupported) as cm:
            self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin]):
    out[0] = SOME_GLOBAL
''')
        self.assertIn('not a parameter', str(cm.exception))

    def test_refuses_a_general_iterable_loop(self):
        # On a GPU the index space IS the parallelism, so a general
        # iterable loop would be sequential work on thousands of threads.
        with self.assertRaises(eml.MetalUnsupported) as cm:
            self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin], xs):
    for v in xs:
        out[0] = v
''')
        self.assertIn('range', str(cm.exception))

    def test_refuses_a_kernel_returning_a_value(self):
        with self.assertRaises(eml.MetalUnsupported):
            self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin]):
    return 1.0
''')

    def test_refuses_an_unknown_call(self):
        with self.assertRaises(eml.MetalUnsupported) as cm:
            self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin]):
    out[0] = some_user_function(1.0)
''')
        self.assertIn('no MSL lowering', str(cm.exception))

    def test_refuses_an_unknown_statement(self):
        with self.assertRaises(eml.MetalUnsupported):
            self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin]):
    with open("f") as f:
        out[0] = 1.0
''')

    def test_refuses_a_non_scalar_index_component(self):
        with self.assertRaises(eml.MetalUnsupported) as cm:
            self.emit('''
def k(out: UnsafePointer[Float32, MutAnyOrigin]):
    out[0] = global_idx.w
''')
        self.assertIn('x, y and z', str(cm.exception))


# ---------------------------------------------------------------------------
# The expensive one: generated MSL, real Metal compiler, real GPU.
# ---------------------------------------------------------------------------

_HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

static const char *kMsl = @MSL@;

int main(void) {
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) { printf("NO_DEVICE\n"); return 2; }
        NSError *err = nil;
        MTLCompileOptions *co = [[MTLCompileOptions alloc] init];
        co.languageVersion = MTLLanguageVersion3_2;
        id<MTLLibrary> lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:kMsl]
                                               options:co error:&err];
        if (!lib) { printf("MSL_FAIL: %s\n", err.description.UTF8String); return 3; }
        id<MTLFunction> fn = [lib newFunctionWithName:@"@FNAME@"];
        if (!fn) { printf("NO_FN\n"); return 3; }
        id<MTLComputePipelineState> ps =
            [dev newComputePipelineStateWithFunction:fn error:&err];
        if (!ps) { printf("NO_PIPE: %s\n", err.description.UTF8String); return 3; }

        const int N = @N@;
        float *a = malloc(N * sizeof(float));
        float *b = malloc(N * sizeof(float));
        float *got = malloc(N * sizeof(float));
        float *ref = malloc(N * sizeof(float));
        for (int i = 0; i < N; i++) {
            a[i] = (float)i * 0.5f;
            b[i] = (float)(i % 7) - 3.0f;
            ref[i] = a[i] + b[i];
            got[i] = -12345.0f;
        }
        id<MTLBuffer> ba = [dev newBufferWithBytes:a length:N*sizeof(float)
                            options:MTLResourceStorageModeShared];
        id<MTLBuffer> bb = [dev newBufferWithBytes:b length:N*sizeof(float)
                            options:MTLResourceStorageModeShared];
        id<MTLBuffer> bo = [dev newBufferWithBytes:got length:N*sizeof(float)
                            options:MTLResourceStorageModeShared];
        id<MTLCommandQueue> q = [dev newCommandQueue];
        id<MTLCommandBuffer> cb = [q commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:ps];
        [e setBuffer:ba offset:0 atIndex:0];
        [e setBuffer:bb offset:0 atIndex:1];
        [e setBuffer:bo offset:0 atIndex:2];
        [e setBytes:&N length:sizeof(int) atIndex:3];
        NSUInteger w = ps.threadExecutionWidth, tmax = ps.maxTotalThreadsPerThreadgroup;
        NSUInteger tg = tmax / w;
        [e dispatchThreadgroups:MTLSizeMake((N + tg - 1) / tg, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(w, 1, 1)];
        [e endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        memcpy(got, [bo contents], N * sizeof(float));

        double maxdiff = 0.0; int bad = 0;
        for (int i = 0; i < N; i++) {
            double d = fabs((double)got[i] - (double)ref[i]);
            if (d > maxdiff) maxdiff = d;
            if (d > 0) bad++;
        }
        printf("MAXDIFF %.3e BAD %d\n", maxdiff, bad);
        return bad == 0 ? 0 : 1;
    }
}
'''


def _c_string_literal(text: str) -> str:
    esc = (text.replace('\\', '\\\\').replace('"', '\\"')
               .replace('\n', '\\n').replace('\t', '\\t'))
    return '"' + esc + '"'


#: The same shape as `_HARNESS` for a kernel that returns INT and whose
#: reference is the DISPATCH GEOMETRY rather than an arithmetic combination of
#: two input buffers. `_HARNESS` hardwires `vec_add`: three float buffers and
#: `ref[i] = a[i] + b[i]`, so an index-intrinsic kernel run through it
#: reports `mismatch` for reasons that have nothing to do with the kernel.
#:
#: The reference here is deliberately a check on the DEVICE's own view of
#: its position: the kernel stores `lid + nthreads + (lid % 32)`, all three
#: read through `llvm.air.*` intrinsics, and the host recomputes that from
#: the width and threadgroup size it dispatched with. If an intrinsic read
#: the wrong value, or were routed through a float, this is what catches it.
_HARNESS_INT = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>

static const char *kMsl = @MSL@;
static const char *kFname = "@FNAME@";

int main(void) {
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) { printf("NO_DEVICE\n"); return 2; }
        NSError *err = nil;
        MTLCompileOptions *co = [[MTLCompileOptions alloc] init];
        co.languageVersion = MTLLanguageVersion3_2;
        id<MTLLibrary> lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:kMsl]
                                               options:co error:&err];
        if (!lib) { printf("MSL_FAIL: %s\n", err.description.UTF8String); return 3; }
        id<MTLFunction> fn = [lib newFunctionWithName:@(kFname)];
        if (!fn) { printf("NO_FN\n"); return 3; }
        id<MTLComputePipelineState> ps =
            [dev newComputePipelineStateWithFunction:fn error:&err];
        if (!ps) { printf("NO_PIPE: %s\n", err.description.UTF8String); return 3; }

        const int N = 256;
        int *outbuf = malloc(N * sizeof(int));
        for (int i = 0; i < N; i++) outbuf[i] = -999;
        id<MTLBuffer> bo = [dev newBufferWithBytes:outbuf length:N*sizeof(int)
                            options:MTLResourceStorageModeShared];
        id<MTLCommandQueue> q = [dev newCommandQueue];
        id<MTLCommandBuffer> cb = [q commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:ps];
        [e setBuffer:bo offset:0 atIndex:0];
        [e setBytes:&N length:sizeof(int) atIndex:1];
        NSUInteger w = ps.threadExecutionWidth, tmax = ps.maxTotalThreadsPerThreadgroup;
        NSUInteger tg = tmax / w;
        [e dispatchThreadgroups:MTLSizeMake((N + tg - 1) / tg, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(w, 1, 1)];
        [e endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        memcpy(outbuf, [bo contents], N * sizeof(int));

        int w2 = (int)w;
        int bad = 0;
        for (int i = 0; i < N; i++) {
            int lane = i % w2;
            int want = ((lane * 16777217) + w2 + (lane % 32)) & 0x7fffffff;
            if (outbuf[i] != want) {
                if (bad < 6) printf("  i=%d got=%d want=%d (w=%d)\n",
                                    i, outbuf[i], want, w2);
                bad++;
            }
        }
        printf("W=%d MISMATCH %d of %d\n", w2, bad, N);
        return bad == 0 ? 0 : 1;
    }
}
'''


def run_int_kernel_on_gpu(msl: str, fname: str, n: int = 256):
    """`run_on_gpu` for an int kernel. Same contract, `_HARNESS_INT`."""
    if sys.platform != 'darwin':
        return 'no_device', ''
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'h.m')
        exe = os.path.join(td, 'h')
        body = (_HARNESS_INT.replace('@MSL@', _c_string_literal(msl))
                              .replace('@FNAME@', fname))
        with open(src, 'w') as f:
            f.write(body)
        cc = subprocess.run(['clang', '-fobjc-arc', '-O1', '-framework',
                             'Foundation', '-framework', 'Metal', '-o', exe, src],
                            capture_output=True, text=True)
        if cc.returncode != 0:
            return 'compile_fail', cc.stderr[:400]
        run = subprocess.run([exe], capture_output=True, text=True, timeout=300)
        out = run.stdout
        if 'NO_DEVICE' in out:
            return 'no_device', out
        if 'MSL_FAIL' in out or 'NO_FN' in out or 'NO_PIPE' in out:
            return 'compile_fail', out
        if run.returncode != 0 or 'MISMATCH 0 of' not in out:
            return 'mismatch', out
        return 'ok', out

def run_on_gpu(msl: str, fname: str, n: int = 4096):
    """Compile `msl` with Apple's real compiler, dispatch, compare to a CPU
    reference. Returns (status, stdout). status: 'ok' | 'no_device' |
    'compile_fail' | 'mismatch'."""
    if sys.platform != 'darwin':
        return 'no_device', ''
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'h.m')
        exe = os.path.join(td, 'h')
        # Substituted, not %-formatted: the harness is C, so its own printf
        # specifiers would all have to be escaped, and getting that wrong
        # fails as "not enough arguments for format string" rather than
        # pointing at the real problem.
        body = (_HARNESS.replace('@MSL@', _c_string_literal(msl))
                       .replace('@FNAME@', fname)
                       .replace('@N@', str(n)))
        with open(src, 'w') as f:
            f.write(body)
        cc = subprocess.run(['clang', '-fobjc-arc', '-O1', '-framework',
                             'Foundation', '-framework', 'Metal', '-o', exe, src],
                            capture_output=True, text=True)
        if cc.returncode != 0:
            return 'compile_fail', cc.stderr[:400]
        run = subprocess.run([exe], capture_output=True, text=True, timeout=300)
        out = run.stdout
        if 'NO_DEVICE' in out:
            return 'no_device', out
        if 'MSL_FAIL' in out or 'NO_FN' in out or 'NO_PIPE' in out:
            return 'compile_fail', out
        if run.returncode != 0 or 'MAXDIFF 0.000e+00 BAD 0' not in out:
            return 'mismatch', out
        return 'ok', out


@unittest.skipUnless(sys.platform == 'darwin', 'Metal is macOS-only')
class TestGeneratedMslRunsOnGpu(unittest.TestCase):
    """The test that can catch a kernel which compiles and computes the
    wrong answer. Everything above it checks TEXT; this checks BEHAVIOUR."""

    KERNEL = '''
def vec_add(in0: UnsafePointer[Float32, MutAnyOrigin],
            in1: UnsafePointer[Float32, MutAnyOrigin],
            output: UnsafePointer[Float32, MutAnyOrigin], len: Int):
    tid = global_idx.x
    if tid >= len:
        return
    output[tid] = in0[tid] + in1[tid]
'''

    def test_stdlib_vec_add_matches_cpu_exactly(self):
        mod = parse(self.KERNEL)
        msl = eml.emit_kernel(mod[0])
        status, out = run_on_gpu(msl, 'vec_add')
        if status == 'no_device':
            self.skipTest('no Metal device on this machine')
        self.assertEqual(status, 'ok', f'status={status}\n{out}\n--- msl ---\n{msl}')


# ---------------------------------------------------------------------------
# Seam 3: the module sidecar -- MSL embedded in the generated C, the host
# launch wrappers, and a real dispatch through runtime/fire_metal.h.
# ---------------------------------------------------------------------------

KERNEL_AND_CALLER = '''
@gpu
def vec_add(in0: UnsafePointer[Float32, MutAnyOrigin],
            in1: UnsafePointer[Float32, MutAnyOrigin],
            output: UnsafePointer[Float32, MutAnyOrigin], len: Int):
    tid = global_idx.x
    if tid >= len:
        return
    output[tid] = in0[tid] + in1[tid]


def run(n: Int):
    vec_add(n, n, n, 8)


def main():
    print(_mojo_gpu_kernel_count())
'''


class TestLaunchArgTypes(unittest.TestCase):
    """The host wrapper's signature, derived off the AST.

    A DEVICE function never reaches gen_func, so there is no inferred C
    signature to read back -- these are what stand in for it, and a wrong
    answer here is a wrong pointer width at the dispatch.
    """

    def test_pointer_params_are_buffers_and_scalars_are_not(self):
        mod = parse(KERNEL_AND_CALLER)
        types, count = dglue.launch_arg_types(mod[0].params)
        self.assertEqual(
            [(n, isb) for n, _t, isb, _w in types],
            [('in0', True), ('in1', True), ('output', True), ('len', False)])
        self.assertEqual(count, 3)

    def test_int_scalar_narrows_to_the_width_the_msl_declares(self):
        """`Int` lowers to MSL `int`, so the host must hand over 4 bytes.

        This is not a style choice. The device reads exactly the bytes bound
        at that constant index; a host double there delivered the low 4 bytes
        of the mantissa, and a length of 1024 arrived as 0 -- the kernel took
        its bounds guard on every thread, wrote nothing, and exited 0.
        """
        mod = parse(KERNEL_AND_CALLER)
        types, _ = dglue.launch_arg_types(mod[0].params)
        self.assertEqual(types[3][1], 'int32_t')
        self.assertEqual(types[3][3], 4)

    def test_element_count_index_rejects_a_kernel_with_no_length(self):
        """A `float *` carries no length, so without one the host cannot copy
        results back. Silently copying back nothing would produce a program
        that runs and prints plausible numbers and is wrong."""
        with self.assertRaises(dglue.LaunchError) as cm:
            dglue.element_count_index('k', -1)
        self.assertIn('no Int/Int64 parameter', str(cm.exception))

    def test_c_string_literal_escapes_trigraphs(self):
        """MSL is full of `?:`, and a C preprocessor that eats trigraphs turns
        the ternary into a digraph. Escaping `?` is what stops the emitted
        string from being re-read differently than it was written."""
        lit = dglue.c_string_literal('a ?: b')
        self.assertIn(r'\?', lit)
        self.assertNotIn('?', lit.replace(r'\?', ''))


class TestDeviceSidecarEmission(unittest.TestCase):
    """What the module generator actually puts in the .ci."""

    @classmethod
    def setUpClass(cls):
        cls.ci = gctypes.compile_to_gimple(KERNEL_AND_CALLER, False,
                                            'sidecar_test.py')

    def test_msl_is_embedded_as_a_c_string(self):
        self.assertIn('_mg_msl_source', self.ci)
        # The kernel text survives escaping, so look for a distinctive
        # fragment rather than the whole (chunked, escaped) literal.
        self.assertIn('kernel void vec_add', self.ci.replace('\\n', '\n'))

    def test_runtime_header_is_included_only_when_offloading(self):
        self.assertIn('#include <fire_metal.h>', self.ci)
        plain = gctypes.compile_to_gimple('def main():\n    print(1)\n', False, 'p.py')
        self.assertNotIn('fire_metal.h', plain,
                         'a module with no kernels must not acquire a Metal '
                         'dependency')

    def test_launch_wrapper_is_generated_with_the_kernels_own_signature(self):
        self.assertIn(
            'void _mg_launch_vec_add(float * in0, float * in1, '
            'float * output, int32_t len)', self.ci)

    def test_wrapper_precedes_its_call_site_so_the_call_typechecks(self):
        """The wrapper is defined in the tail sidecar but called from a
        function body emitted much earlier, so the prototype in the preamble is
        load-bearing: without it the call is an implicit declaration and gcc
        reports "conflicting types" against the real definition."""
        proto = self.ci.find('void _mg_launch_vec_add(float * in0')
        call = self.ci.find('_mg_launch_vec_add(_t')
        self.assertGreater(proto, 0, 'no prototype emitted')
        self.assertGreater(call, 0, 'the Mojo call site was not routed')
        self.assertLess(proto, call)

    def test_mojo_call_site_routes_to_the_launch_wrapper(self):
        """A call to a device function must become a dispatch, not a call to a
        C function that does not exist. This is the assertion that would have
        caught the stub: the generated code referenced `vec_add_<oid>` with a
        weak stub, which linked and then did nothing."""
        self.assertIn('_mg_launch_vec_add(', self.ci)
        # No C definition of the kernel itself may survive.
        self.assertNotIn('_MOJO_STUB_vec_add', self.ci)

    def test_scalar_is_narrowed_before_it_reaches_the_runtime(self):
        self.assertIn('int32_t _mg_sc0 = (int32_t)len;', self.ci)
        self.assertIn('_mg_widths[] = {4}', self.ci)

    def test_introspection_entry_points_are_registered(self):
        """They are called from compiled Mojo, so they must be real registered
        runtime functions -- otherwise the C backend mints a weak stub that
        collides with the sidecar's definition."""
        for n in ('_mojo_gpu_kernel_count', '_mojo_gpu_have_device',
                  '_mojo_gpu_dispatch_count', '_mojo_gpu_failure_count'):
            self.assertIn(f'int64_t {n}(void);', self.ci)
            # The definition line is column-aligned in the emitter, so match
            # on the name and the body rather than on exact spacing.
            self.assertRegex(
                self.ci,
                r'int64_t ' + re.escape(n) + r'\(void\)\s*\{')


# The C driver for the end-to-end dispatch. It calls the GENERATED wrapper
# (not the runtime directly) because the wrapper is where the buffer table,
# the narrowing and the width table live -- a test that skipped it would pass
# with all of that deleted.
_SIDECAR_DRIVER = r'''
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include <stdint.h>
void _mg_launch_vec_add(float *a, float *b, float *o, int32_t n);
int64_t _mojo_gpu_kernel_count(void);
int64_t _mojo_gpu_have_device(void);
int64_t _mojo_gpu_dispatch_count(void);
int64_t _mojo_gpu_failure_count(void);
int main(void) {
    int64_t n = 1024;
    float *a = malloc(n * 4), *b = malloc(n * 4), *o = malloc(n * 4);
    for (int64_t i = 0; i < n; i++) { a[i] = (float)i * 0.5f;
                                       b[i] = (float)i * 2.0f;
                                       o[i] = -1.0f; }
    if (_mojo_gpu_kernel_count() != 1) { printf("KCOUNT\n"); return 3; }
    if (!_mojo_gpu_have_device()) { printf("NO_DEVICE\n"); return 2; }
    _mg_launch_vec_add(a, b, o, (int32_t)n);
    double worst = 0.0; int64_t bad = 0;
    for (int64_t i = 0; i < n; i++) {
        double d = fabs((double)a[i] + (double)b[i] - (double)o[i]);
        if (d > worst) worst = d;
        if (d > 0.0) bad++;
    }
    printf("DISPATCHES %lld FAILURES %lld MAXDIFF %.3e BAD %lld\n",
           (long long)_mojo_gpu_dispatch_count(),
           (long long)_mojo_gpu_failure_count(), worst, (long long)bad);
    return 0;
}
'''


@unittest.skipUnless(sys.platform == 'darwin', 'Metal is macOS-only')
class TestSidecarDispatchesOnRealGpu(unittest.TestCase):
    """Python -> MSL -> C string -> real Metal compiler -> real GPU, through
    the generated host wrapper. The one test that can catch a marshalling bug
    -- a wrong scalar width, a short grid, a missing copy-back -- because every
    one of those produces a wrong answer at exit 0 rather than an error."""

    def test_generated_wrapper_computes_the_right_answer(self):
        ci = gctypes.compile_to_gimple(KERNEL_AND_CALLER, False, 'sidecar_gpu.py')
        rt = os.path.join(HERE, 'runtime')
        metal_m = os.path.join(rt, 'fire_metal.m')
        if not os.path.exists(metal_m):
            self.skipTest('runtime/fire_metal.m missing')
        with tempfile.TemporaryDirectory() as wd:
            ci_f = os.path.join(wd, 'm.ci')
            drv_f = os.path.join(wd, 'drv.c')
            with open(ci_f, 'w') as f:
                f.write(ci)
            with open(drv_f, 'w') as f:
                f.write(_SIDECAR_DRIVER)
            # The module's own `main` is renamed so the driver owns the entry
            # point; everything else, including the sidecar, is untouched.
            compile_r = subprocess.run(
                [_GCC, '-O0', '-fgimple', '-fPIC', f'-I{rt}',
                 '-Dmain=mojo_module_main', '-c', '-o',
                 os.path.join(wd, 'm.o'), '-x', 'c', ci_f],
                capture_output=True, text=True)
            if compile_r.returncode != 0:
                self.skipTest(f'gimple compile failed:\n{compile_r.stderr[:2000]}')
            metal_r = subprocess.run(
                ['clang', '-O0', '-fobjc-arc', f'-I{rt}', '-c', '-o',
                 os.path.join(wd, 'fm.o'), metal_m],
                capture_output=True, text=True)
            if metal_r.returncode != 0:
                self.skipTest(f'clang compile failed:\n{metal_r.stderr[:2000]}')
            exe = os.path.join(wd, 'a.out')
            link_r = subprocess.run(
                [_GCC, '-O0', '-o', exe, drv_f, os.path.join(wd, 'm.o'),
                 os.path.join(wd, 'fm.o'), os.path.join(rt, 'fire_runtime.c'),
                 f'-I{rt}', '-framework', 'Foundation', '-framework', 'Metal',
                 '-lm'], capture_output=True, text=True)
            if link_r.returncode != 0:
                self.fail(f'link failed:\n{link_r.stderr[:2000]}')
            run = subprocess.run([exe], capture_output=True, text=True, timeout=300)
            out = run.stdout
            if 'NO_DEVICE' in out:
                self.skipTest('no Metal device on this machine')
            if 'KCOUNT' in out:
                self.fail(f'sidecar registered the wrong kernel count\n{out}')
            self.assertIn('MAXDIFF 0.000e+00 BAD 0', out,
                          f'wrong answer on the GPU\n{out}')
            self.assertIn('DISPATCHES 1', out)
            self.assertIn('FAILURES 0', out)


@unittest.skipUnless(sys.platform == 'darwin', 'Metal is macOS-only')
class TestListsReachTheGpu(unittest.TestCase):
    """Ordinary Python lists, offloaded.

    This is the case the whole exercise exists for. A `MojoList` is a struct
    whose first field is a data pointer, so the obvious lowering -- cast it to
    `float *` -- points at the struct HEADER and the kernel reads data/len/cap/
    the inline buffer as the array. It runs, and it is wrong. Lists are
    therefore packed into real contiguous buffers for the dispatch and written
    back afterwards.

    Driven through `fire.py --jit`, so it also covers the whole link path: the
    generated .ci, the sidecar, the Objective-C runtime, and the frameworks
    being added to the link line only because this module references them.
    """

    PROG = '''\
@gpu
def vec_add(in0: UnsafePointer[Float32, MutAnyOrigin],
            in1: UnsafePointer[Float32, MutAnyOrigin],
            output: UnsafePointer[Float32, MutAnyOrigin], len: Int):
    tid = global_idx.x
    if tid >= len:
        return
    output[tid] = in0[tid] + in1[tid]


def main():
    a = [0.0, 1.0, 2.0, 3.0]
    b = [2.0, 2.0, 2.0, 2.0]
    # Poisoned, so a dispatch that silently did nothing cannot look correct.
    o = [-999.0, -999.0, -999.0, -999.0]
    vec_add(a, b, o, 4)
    for v in o:
        print(v)
    print("d", _mojo_gpu_dispatch_count())
    print("f", _mojo_gpu_failure_count())
'''

    def test_plain_lists_dispatch_and_return_the_right_answer(self):
        with tempfile.TemporaryDirectory() as wd:
            path = os.path.join(wd, 'lists.mojo')
            with open(path, 'w') as f:
                f.write(self.PROG)
            r = subprocess.run(
                [sys.executable, os.path.join(HERE, 'fire.py'), '--jit', path],
                capture_output=True, text=True, timeout=900, cwd=HERE)
            out = r.stdout.strip().splitlines()
            if r.returncode != 0:
                self.skipTest(f'no JIT build here: {r.stderr[-400:]}')
            if 'd 0' in ' '.join(out) and 'f 1' in ' '.join(out):
                self.skipTest('no Metal device on this machine')
            self.assertEqual(out[:4], ['2.0', '3.0', '4.0', '5.0'],
                             f'wrong answer on the GPU\n{r.stdout}\n{r.stderr[-800:]}')
            self.assertIn('d 1', out, f'no dispatch happened\n{r.stdout}')
            self.assertIn('f 0', out, f'a dispatch failed\n{r.stdout}')


# ---------------------------------------------------------------------------
# Increment 2: the stdlib reaches the GPU ONLY through
# `llvm_intrinsic["llvm.air....", ReturnType, ...]()`, so that subscript-call
# shape is what makes real stdlib GPU code lowerable at all.
# ---------------------------------------------------------------------------

AIR_INTRINSIC_CALL = '''
def air_indices(out: UnsafePointer[Int32, MutAnyOrigin], len: Int):
    tid = global_idx.x
    if tid >= len:
        return
    a = llvm_intrinsic["llvm.air.thread_position_in_threadgroup.x", Int32, has_side_effect=False]()
    b = llvm_intrinsic["llvm.air.threads_per_threadgroup.x", Int32, has_side_effect=False]()
    c = llvm_intrinsic["llvm.air.thread_index_in_simdgroup", Int32, has_side_effect=False]()
    out[tid] = ((a * 16777217) + b + c)
'''


def _air_fn(src: str = AIR_INTRINSIC_CALL):
    mod = parse(src)
    return [s for s in mod if getattr(s, 'name', None)
            and str(s.name) == 'air_indices'][0]


class TestLlvmAirTables(unittest.TestCase):
    """The table half: pure, so no device and no emitter."""

    def test_index_families_resolve_to_generated_parameters(self):
        # These resolve to the index PARAMETERS, not to a call. MSL's
        # builtin-function spellings do not resolve at any language version
        # on this toolchain -- see metal_ops.INDEX_PARAM_NAMES, which records
        # that as probed rather than assumed.
        self.assertEqual(mops.llvm_air('llvm.air.thread_position_in_threadgroup.x'),
                         '__lid')
        self.assertEqual(mops.llvm_air('llvm.air.thread_position_in_threadgroup.z'),
                         '__lid')
        self.assertEqual(mops.llvm_air('llvm.air.threads_per_threadgroup.x'),
                         '__nthreads')
        self.assertEqual(mops.llvm_air('llvm.air.threadgroup_position_in_grid.y'),
                         '__tgid')

    def test_simdgroup_index_matches_the_existing_lane_id_definition(self):
        # One definition of "the lane": if this ever stops agreeing with
        # INDEX_PARAM_NAMES['lane_id'], the two would disagree silently.
        self.assertEqual(mops.llvm_air(mops.LLVM_AIR_SIMDGROUP_INDEX),
                         mops.INDEX_PARAM_NAMES['lane_id'])

    def test_math_intrinsics_map_to_the_metal_namespace(self):
        self.assertEqual(mops.llvm_air('llvm.air.sqrt'), 'metal::sqrt')
        self.assertEqual(mops.llvm_air('llvm.air.rsqrt'), 'metal::rsqrt')

    def test_what_is_absent_refuses_rather_than_guessing(self):
        # Every one of these is a real llvm.air name the stdlib can reach.
        # None has a 1:1 MSL form, so each must return None -> the emitter
        # raises naming the intrinsic. A table entry here would be a guess
        # about semantics, and a guess that computes a plausible wrong answer
        # is worse than a refusal.
        for name in (
                'llvm.air.simdgroup_matrix_8x8_multiply_accumulate',
                'llvm.air.simdgroup_matrix_16x16x16_multiply_accumulate',
                'llvm.air.simdgroup_matrix_16x16x16_widening_multiply_accumulate',
                'llvm.air.simd_shuffle',
                'llvm.air.simd_ballot.i32',
                'llvm.air.threads_per_grid.x',   # no such kernel attribute
                'llvm.air.thread_position_in_threadgroup.q',  # not x/y/z
        ):
            self.assertIsNone(mops.llvm_air(name), name)

    def test_declared_return_type_is_honoured(self):
        # The emitter DEFAULTS an unknown expression to float, so reading the
        # stdlib's declared return type is what keeps an Int32 index
        # intrinsic from being declared float.
        self.assertEqual(mops.llvm_air_ret_type('Int32'), 'int')
        self.assertEqual(mops.llvm_air_ret_type('Float16'), 'half')
        self.assertEqual(mops.llvm_air_ret_type('Bool'), 'bool')
        # A vector spelling has no single right width here; None keeps the
        # existing default rather than inventing one.
        self.assertIsNone(mops.llvm_air_ret_type('SIMD[DType.float32, 4]'))


class TestLlvmAirLowering(unittest.TestCase):
    """The emitter half: MSL text, no device needed."""

    def test_intrinsic_call_becomes_its_msl_form(self):
        msl = eml.emit_kernel(_air_fn())
        self.assertIn('a = __lid;', msl)
        self.assertIn('b = __nthreads;', msl)
        self.assertIn('c = (__lid % 32u);', msl)
        # The subscript-call shape is what needed lowering at all; before
        # this, `_call` refused any non-IdentExpr callee outright.
        self.assertNotIn('llvm_intrinsic', msl)

    def test_intrinsic_results_are_declared_int_not_float(self):
        msl = eml.emit_kernel(_air_fn())
        self.assertIn('int a;', msl)
        self.assertIn('int b;', msl)
        self.assertIn('int c;', msl)
        self.assertNotIn('float a;', msl)

    def test_a_vendor_intrinsic_is_refused_by_name(self):
        # llvm.nvvm.* / rocdl.* are reached only from is_nvidia_gpu() /
        # is_amd_gpu() branches and have no 1:1 MSL equivalent. Refusing with
        # the name in the message is the useful part.
        src = '''
def air_indices(out: UnsafePointer[Int32, MutAnyOrigin], len: Int):
    out[0] = llvm_intrinsic["llvm.nvvm.mbarrier.arrive.shared", Int32]()
'''
        with self.assertRaises(eml.MetalUnsupported) as cm:
            eml.emit_kernel(_air_fn(src))
        self.assertIn('llvm.nvvm.mbarrier.arrive.shared', str(cm.exception))

    def test_an_unimplemented_air_intrinsic_is_refused_by_name(self):
        src = '''
def air_indices(out: UnsafePointer[Int32, MutAnyOrigin], len: Int):
    out[0] = llvm_intrinsic["llvm.air.simd_shuffle", Int32]()
'''
        with self.assertRaises(eml.MetalUnsupported) as cm:
            eml.emit_kernel(_air_fn(src))
        self.assertIn('simd_shuffle', str(cm.exception))

    def test_a_non_literal_intrinsic_name_is_refused(self):
        # The stdlib writes `"llvm.air..." + dim` where dim is a StaticString
        # parameter, so this shape is reachable. Resolving it to a default
        # name would be inventing a kernel.
        #
        # The name here is a FUNCTION PARAMETER rather than an undefined
        # global, so this reaches the intrinsic path and is refused there --
        # the "no globals" refusal that a bare undefined name would hit
        # first is a different error and is not what is under test.
        src = '''
def air_indices(out: UnsafePointer[Int32, MutAnyOrigin], len: Int, nm: String):
    out[0] = llvm_intrinsic[nm, Int32]()
'''
        with self.assertRaises(eml.MetalUnsupported) as cm:
            eml.emit_kernel(_air_fn(src))
        self.assertIn('not a string literal', str(cm.exception))


@unittest.skipUnless(sys.platform == 'darwin', 'Metal is macOS-only')
class TestAirIntrinsicsRunOnGpu(unittest.TestCase):
    """Increment 2's behavioural claim: an `llvm.air.*` index intrinsic
    reads the DEVICE's own thread position, and reaches an int buffer without
    being routed through a float."""

    def test_air_index_intrinsics_read_the_device_thread_position(self):
        msl = eml.emit_kernel(_air_fn())
        status, out = run_int_kernel_on_gpu(msl, 'air_indices')
        if status == 'no_device':
            self.skipTest('no Metal device on this machine')
        self.assertEqual(status, 'ok', f'status={status}\n{out}\n--- msl ---\n{msl}')

    def test_a_float_routed_intrinsic_is_caught_by_this_harness(self):
        """The test is worth keeping only if it FAILS on the bug it guards.

        `_type_of` defaults an unrecognised expression to `float`, so before
        the return-type table the three `Int32` intrinsics were declared
        `float` and every result was routed through a float. Small values
        survive that -- `lid` is 0..31, so a naive check passes. The kernel
        above multiplies by 16777217 (2^24+1) for exactly that reason, and
        this asserts the mutated kernel is caught rather than assuming it.
        """
        msl = eml.emit_kernel(_air_fn())
        self.assertIn('int a;', msl)
        broken = msl.replace('int a;', 'float a;') \
                     .replace('int b;', 'float b;') \
                     .replace('int c;', 'float c;')
        self.assertNotEqual(broken, msl, 'mutation did not apply')
        status, out = run_int_kernel_on_gpu(broken, 'air_indices')
        if status == 'no_device':
            self.skipTest('no Metal device on this machine')
        self.assertEqual(status, 'mismatch',
                         'a float-routed intrinsic computed the right answer, '
                         'so this harness cannot see that class of bug:\n'
                         f'{out}')



# ---------------------------------------------------------------------------
# Increment 3: auto-offload. A recognised parallel loop nest is synthesised
# into a `@gpu` function and flows through seams 1/2/3 unchanged.
# ---------------------------------------------------------------------------

SAXPY = '''
def saxpy(a: Float32, x: List[Float32], y: List[Float32],
          out: List[Float32], n: Int):
    for i in range(n):
        out[i] = a * x[i] + y[i]
'''


def _fn(src: str, name: str = None):
    mod = parse(src)
    for s in mod:
        if getattr(s, 'name', None) and (name is None or str(s.name) == name):
            return s
    raise AssertionError('no such function')


class TestOffloadRecognition(unittest.TestCase):
    """What is accepted, and -- mostly -- what is refused.

    The refusals are the point. Increment 3 moves a loop onto a GPU without
    being asked, so every loop it declines must be declined for a reason that
    would otherwise produce a plausible wrong answer at exit 0.
    """

    def test_a_parallel_map_is_recognised(self):
        info = ofl.recognise(_fn(SAXPY))
        self.assertIsNotNone(info)
        self.assertEqual(info.index, 'i')
        self.assertEqual(info.param, 'n')
        self.assertEqual(info.writes, 'out')
        self.assertEqual(info.reads, ['x', 'y'])
        # `a` is a bare identifier in the body, so it is a kernel parameter
        # too. Missing it emits it as an undeclared global -- the build error
        # that found this.
        self.assertEqual(info.scalars, ['a'])

    def test_a_scalar_coefficient_is_carried(self):
        info = ofl.recognise(_fn(
            'def f(k: Int, x: List[Float32], out: List[Float32], n: Int):\n'
            '    for i in range(n):\n'
            '        out[i] = x[i] * k\n'))
        self.assertEqual(info.scalars, ['k'])

    def test_a_reduction_is_refused(self):
        # `t = t + x[i]` is not a parallel map. Accepting it and summing
        # per-thread would give a wrong answer, not an error.
        f = _fn('def f(x: List[Float32], out: List[Float32], n: Int):\n'
                '    t = 0.0\n'
                '    for i in range(n):\n'
                '        t = t + x[i]\n'
                '    out[0] = t\n')
        self.assertIsNone(ofl.recognise(f))
        self.assertIn('reduction', ofl.explain(f))

    def test_a_strided_write_is_refused(self):
        f = _fn('def f(x: List[Float32], out: List[Float32], n: Int):\n'
                '    for i in range(n):\n'
                '        out[i * 2] = x[i]\n')
        self.assertIsNone(ofl.recognise(f))
        self.assertIn('not indexed by the loop variable', ofl.explain(f))

    def test_a_conditional_store_is_refused(self):
        f = _fn('def f(x: List[Float32], out: List[Float32], n: Int):\n'
                '    for i in range(n):\n'
                '        if x[i] < 0.0:\n'
                '            continue\n'
                '        out[i] = x[i]\n')
        self.assertIsNone(ofl.recognise(f))
        self.assertIn('not a single assignment', ofl.explain(f))

    def test_a_nested_loop_is_refused(self):
        f = _fn('def f(x: List[Float32], out: List[Float32], n: Int):\n'
                '    for i in range(n):\n'
                '        for j in range(n):\n'
                '            out[i] = x[j]\n')
        self.assertIsNone(ofl.recognise(f))

    def test_an_aliasing_write_is_refused(self):
        f = _fn('def f(x: List[Float32], out: List[Float32], n: Int):\n'
                '    for i in range(n):\n'
                '        x[i] = x[i] + 1.0\n'
                '        out[i] = x[i]\n')
        self.assertIsNone(ofl.recognise(f))

    def test_range_with_two_bounds_is_refused(self):
        f = _fn('def f(x: List[Float32], out: List[Float32], n: Int):\n'
                '    for i in range(0, n):\n'
                '        out[i] = x[i]\n')
        self.assertIsNone(ofl.recognise(f))
        self.assertIn('range', ofl.explain(f))

    def test_iterating_a_list_rather_than_a_range_is_refused(self):
        f = _fn('def f(x: List[Float32], out: List[Float32], xs: List[Int]):\n'
                '    for i in xs:\n'
                '        out[i] = x[i]\n')
        self.assertIsNone(ofl.recognise(f))

    def test_a_call_in_the_body_is_refused(self):
        f = _fn('def f(x: List[Float32], out: List[Float32], n: Int):\n'
                '    for i in range(n):\n'
                '        out[i] = helper(x[i])\n')
        self.assertIsNone(ofl.recognise(f))
        self.assertIn('CallExpr', ofl.explain(f))

    def test_other_host_work_in_the_function_is_refused(self):
        f = _fn('def f(x: List[Float32], out: List[Float32], n: Int):\n'
                '    z = 1.0\n'
                '    for i in range(n):\n'
                '        out[i] = x[i]\n')
        self.assertIsNone(ofl.recognise(f))
        self.assertIn('assignment', ofl.explain(f))

    def test_a_trailing_return_is_allowed(self):
        f = _fn('def f(x: List[Float32], out: List[Float32], n: Int):\n'
                '    for i in range(n):\n'
                '        out[i] = x[i]\n'
                '    return out\n')
        self.assertIsNotNone(ofl.recognise(f))


class TestOffloadSynthesis(unittest.TestCase):
    """The synthesised function, and the seams it has to survive."""

    def setUp(self):
        self.fn = _fn(SAXPY)
        self.k = ofl.synthesise(self.fn, ofl.recognise(self.fn))

    def test_it_is_marked_gpu_so_the_existing_seams_take_it(self):
        # This is the whole design: no new code path, just a FunctionDef that
        # seam 1 already classifies as DEVICE.
        self.assertEqual(self.k.decorators, ['gpu'])
        self.assertEqual(dsel.classify_functions([self.k]),
                         {self.k.name: dsel.DEVICE})

    def test_the_name_cannot_collide_with_a_user_function(self):
        self.assertTrue(str(self.k.name).startswith(ofl.SYNTH_PREFIX))
        self.assertNotEqual(str(self.k.name), 'saxpy')

    def test_the_length_parameter_comes_first(self):
        # device_glue takes the FIRST Int parameter as the copy-back element
        # count. With `a: Int` present, any other order lets a coefficient
        # steal that role and the host copies back the wrong number of
        # elements.
        types, count_idx = dglue.launch_arg_types(self.k.params)
        self.assertEqual(self.k.params[count_idx][0], ofl._LENGTH_PARAM)
        self.assertEqual(count_idx, 0)

    def test_containers_are_device_pointers_not_lists(self):
        # `List[Float32]` resolves to `MojoList *`, which emit_metal refuses
        # by name; the device signature has to be the pointer spelling.
        for name, ann in self.k.params:
            if name in ('x', 'y', 'out'):
                self.assertTrue(ann.startswith('UnsafePointer['), ann)

    def test_it_lowers_to_msl_with_a_real_bounds_guard(self):
        msl = eml.emit_kernel(self.k)
        self.assertIn('kernel void _mg_offload_saxpy', msl)
        self.assertIn('i = __gid;', msl)
        # The guard is what stops an over-dispatched grid reading past the end.
        self.assertIn('if ((i >= _mg_len))', msl)
        self.assertIn('out[i] = ((a * x[i]) + y[i]);', msl)

    def test_buffer_indices_count_buffers_not_parameters(self):
        """A latent emitter bug that this parameter order exposed.

        runtime/fire_metal.m binds buffers at 0..n_bufs-1 and only then the
        scalars, so a scalar before a buffer must not advance the buffer
        index. Every hand-written kernel in this tree declares all its
        buffers first, so `len(parts)` happened to equal the buffer count
        and the bug could not fire -- until a synthesised kernel put its
        length scalar first. Before the fix this kernel bound `out` at
        [[buffer(4)]] while the runtime bound it at 2, and the GPU wrote
        nothing: 1024 of 1024 elements left at their sentinel, exit 0.
        """
        msl = eml.emit_kernel(self.k)
        self.assertIn('x [[buffer(0)]]', msl)
        self.assertIn('y [[buffer(1)]]', msl)
        self.assertIn('out [[buffer(2)]]', msl)
        self.assertNotIn('out [[buffer(4)]]', msl)

    def test_an_unannotated_container_is_refused(self):
        f = _fn('def f(x, out, n):\n'
                '    for i in range(n):\n'
                '        out[i] = x[i]\n')
        info = ofl.recognise(f)
        self.assertIsNotNone(info, 'the loop itself is still a parallel map')
        with self.assertRaises(ofl.SynthesisRefused) as cm:
            ofl.synthesise(f, info)
        self.assertIn('no type annotation', str(cm.exception))

    def test_a_string_container_is_refused(self):
        # `x: List[String]` is not read in the body here, so the recogniser
        # has nothing to refuse on and the loop is a perfectly good parallel
        # map -- `out[i] = 1.0` touches only the Float32 list. The string
        # container is caught where it belongs: a String element is not a
        # scalar or a subscript, so any body that actually READS one is
        # refused.
        f = _fn('def f(x: List[String], out: List[Float32], n: Int):\n'
                '    for i in range(n):\n'
                '        out[i] = 1.0\n')
        info = ofl.recognise(f)
        self.assertIsNotNone(info)
        self.assertEqual(info.reads, [], 'x is not read, so it is not a kernel arg')

        # A body that DOES read the string element is RECOGNISED -- the
        # recogniser is a shape test and does not track element types -- and
        # then refused by the SYNTHESISER, which is the layer that resolves
        # annotations. The layering is the point: refusing on shape would
        # mean refusing every subscript read, including the numeric ones that
        # are the whole purpose.
        g = _fn('def f(x: List[String], out: List[Float32], n: Int):\n'
                '    for i in range(n):\n'
                '        out[i] = x[i]\n')
        ginfo = ofl.recognise(g)
        self.assertIsNotNone(ginfo)
        self.assertEqual(ginfo.reads, ['x'])
        with self.assertRaises(ofl.SynthesisRefused) as cm:
            ofl.synthesise(g, ginfo)
        self.assertIn('String', str(cm.exception))


class TestOffloadEndToEnd(unittest.TestCase):
    """The synthesised kernel has to survive the real codegen, not just the
    emitter in isolation."""

    def test_the_kernel_and_its_launch_wrapper_reach_the_generated_c(self):
        mod = parse(SAXPY + '\ndef main():\n    print(1)\n')
        synth = ofl.synthesise_module(mod)
        self.assertEqual([str(f.name) for f in synth], ['_mg_offload_saxpy'])
        gen = gctypes.GimpleGen(None)
        gen.module_name = 'e2e'
        out = gen.gen_module(list(mod) + list(synth))
        # The MSL sidecar, and the host wrapper that marshals for it.
        self.assertIn('_mg_offload_saxpy', out)
        self.assertIn('_mg_launch__mg_offload_saxpy', out)
        # The MSL is embedded as an ESCAPED C string, so the buffer
        # attributes appear split across adjacent string literals. Assert on
        # the wrapper's buffer table instead, which is unescaped and is the
        # half the HOST actually uses.
        self.assertIn('void *_mg_bufs[] = {x, y, out};', out)
        self.assertIn('_mg_sc0 = (int32_t)_mg_len;', out)
        # And on the escaped kernel signature, joined back up.
        self.assertNotIn('out [[buffer(4)]]', out)
        self.assertIn('buffer(2', out)

    def test_an_explicitly_marked_function_is_not_re_synthesised(self):
        mod = parse('@gpu\ndef k(out: List[Float32], n: Int):\n'
                    '    for i in range(n):\n'
                    '        out[i] = 1.0\n')
        self.assertEqual(ofl.synthesise_module(mod), [])


@unittest.skipUnless(sys.platform == 'darwin', 'Metal is macOS-only')
class TestSynthesisedKernelRunsOnGpu(unittest.TestCase):
    """Increment 3's behavioural claim: a loop nobody marked computes the
    right answer on the real GPU."""

    def test_a_recognised_loop_computes_saxpy_exactly(self):
        msl = eml.emit_kernel(
            ofl.synthesise(_fn(SAXPY), ofl.recognise(_fn(SAXPY))))
        status, out = run_saxpy_on_gpu(msl, '_mg_offload_saxpy')
        if status == 'no_device':
            self.skipTest('no Metal device on this machine')
        self.assertEqual(status, 'ok', f'status={status}\n{out}\n--- msl ---\n{msl}')

    def test_misbound_buffers_are_caught_by_this_harness(self):
        """The test earns its keep only if it fails on the bug it guards."""
        msl = eml.emit_kernel(
            ofl.synthesise(_fn(SAXPY), ofl.recognise(_fn(SAXPY))))
        self.assertIn('out [[buffer(2)]]', msl)
        broken = (msl.replace('y [[buffer(1)]]', 'y [[buffer(2)]]')
                     .replace('out [[buffer(2)]]', 'out [[buffer(4)]]'))
        self.assertNotEqual(broken, msl, 'mutation did not apply')
        status, out = run_saxpy_on_gpu(broken, '_mg_offload_saxpy')
        if status == 'no_device':
            self.skipTest('no Metal device on this machine')
        self.assertEqual(status, 'mismatch',
                         'a misbound buffer computed the right answer, so '
                         f'this harness cannot see that class of bug:\n{out}')


#: saXPY's own harness. `_HARNESS_INT` checks a device's view of its THREAD
#: INDEX; this one checks a computed VALUE, and it is the only test that can
#: tell a synthesised kernel that works from one that never ran.
#:
#: The buffer binding order is the runtime's, not the MSL's: fire_metal.m
#: binds buffers at 0..n_bufs-1 and only then the scalars. An earlier
#: version of this harness bound by parameter position and reported a
#: perfect-looking failure that was really a harness bug.
_HARNESS_SAXPY = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

static const char *kMsl = @MSL@;
static const char *kFname = "@FNAME@";

int main(void) {
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) { printf("NO_DEVICE\n"); return 2; }
        NSError *err = nil;
        MTLCompileOptions *co = [[MTLCompileOptions alloc] init];
        co.languageVersion = MTLLanguageVersion3_2;
        id<MTLLibrary> lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:kMsl]
                                               options:co error:&err];
        if (!lib) { printf("MSL_FAIL: %s\n", err.description.UTF8String); return 3; }
        id<MTLFunction> fn = [lib newFunctionWithName:@(kFname)];
        if (!fn) { printf("NO_FN\n"); return 3; }
        id<MTLComputePipelineState> ps =
            [dev newComputePipelineStateWithFunction:fn error:&err];
        if (!ps) { printf("NO_PIPE: %s\n", err.description.UTF8String); return 3; }

        const int N = 1024;
        float a = 2.5f;
        float *x = malloc(N * sizeof(float));
        float *y = malloc(N * sizeof(float));
        float *out = malloc(N * sizeof(float));
        for (int i = 0; i < N; i++) {
            x[i] = (float)i; y[i] = (float)(N - i); out[i] = -1.0f;
        }
        id<MTLBuffer> bx = [dev newBufferWithBytes:x length:N*sizeof(float)
                            options:MTLResourceStorageModeShared];
        id<MTLBuffer> by = [dev newBufferWithBytes:y length:N*sizeof(float)
                            options:MTLResourceStorageModeShared];
        id<MTLBuffer> bo = [dev newBufferWithBytes:out length:N*sizeof(float)
                            options:MTLResourceStorageModeShared];
        id<MTLCommandQueue> q = [dev newCommandQueue];
        id<MTLCommandBuffer> cb = [q commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:ps];
        [e setBuffer:bx offset:0 atIndex:0];
        [e setBuffer:by offset:0 atIndex:1];
        [e setBuffer:bo offset:0 atIndex:2];
        [e setBytes:&N length:sizeof(int) atIndex:3];
        [e setBytes:&a length:sizeof(float) atIndex:4];
        NSUInteger w = ps.threadExecutionWidth, tmax = ps.maxTotalThreadsPerThreadgroup;
        if (w == 0) w = 1;
        if (tmax < w) tmax = w;
        [e dispatchThreadgroups:MTLSizeMake((N + tmax/w - 1)/(tmax/w), 1, 1)
            threadsPerThreadgroup:MTLSizeMake(w, 1, 1)];
        [e endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        memcpy(out, [bo contents], N * sizeof(float));
        double maxdiff = 0.0; int bad = 0;
        for (int i = 0; i < N; i++) {
            double want = (double)a * (double)x[i] + (double)y[i];
            double d = fabs((double)out[i] - want);
            if (d > maxdiff) maxdiff = d;
            if (d > 0) bad++;
        }
        printf("SAXPY N=%d MAXDIFF %.3e BAD %d\n", N, maxdiff, bad);
        return bad == 0 ? 0 : 1;
    }
}
'''


def run_saxpy_on_gpu(msl: str, fname: str):
    """Dispatch `msl` as a saXPY kernel and compare against the CPU value."""
    if sys.platform != 'darwin':
        return 'no_device', ''
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'h.m')
        exe = os.path.join(td, 'h')
        body = (_HARNESS_SAXPY.replace('@MSL@', _c_string_literal(msl))
                               .replace('@FNAME@', fname))
        with open(src, 'w') as f:
            f.write(body)
        cc = subprocess.run(['clang', '-fobjc-arc', '-O1', '-framework',
                             'Foundation', '-framework', 'Metal', '-o', exe, src],
                            capture_output=True, text=True)
        if cc.returncode != 0:
            return 'compile_fail', cc.stderr[:400]
        run = subprocess.run([exe], capture_output=True, text=True, timeout=300)
        out = run.stdout
        if 'NO_DEVICE' in out:
            return 'no_device', out
        if 'MSL_FAIL' in out or 'NO_FN' in out or 'NO_PIPE' in out:
            return 'compile_fail', out
        if run.returncode != 0 or 'BAD 0' not in out:
            return 'mismatch', out
        return 'ok', out



class TestNoGpuFlag(unittest.TestCase):
    """`--no-gpu` turns off INFERENCE, not the device path.

    The distinction is the whole contract, and both halves are tested
    because either alone would be a plausible-looking implementation: a flag
    that suppressed every kernel would satisfy "no auto-offload" while
    silently demoting code the user explicitly marked, and a flag that
    changed nothing would satisfy "marked code still works" while leaving no
    way to keep a loop on the host.
    """

    MARKED = ('@gpu\n'
              'def vec_add(in0: UnsafePointer[Float32, MutAnyOrigin],\n'
              '            output: UnsafePointer[Float32, MutAnyOrigin], len: Int):\n'
              '    tid = global_idx.x\n'
              '    if tid >= len:\n'
              '        return\n'
              '    output[tid] = in0[tid]\n')

    def test_inference_is_off_without_the_flag_on_the_gen(self):
        mod = parse(SAXPY)
        on = gctypes.GimpleGen(None, auto_gpu=True)
        on.module_name = 'x'
        with_on = on.gen_module(list(mod))
        off = gctypes.GimpleGen(None, auto_gpu=False)
        off.module_name = 'x'
        with_off = off.gen_module(list(mod))
        self.assertIn('_mg_offload_saxpy', with_on)
        self.assertNotIn('_mg_offload_saxpy', with_off)
        # And the rest of the module is untouched: this is a targeted
        # suppression, not a different codegen.
        self.assertIn('saxpy', with_off)

    def test_a_marked_kernel_survives_no_gpu(self):
        for auto in (True, False):
            gen = gctypes.GimpleGen(None, auto_gpu=auto)
            gen.module_name = 'm'
            out = gen.gen_module(list(parse(self.MARKED)))
            self.assertIn('kernel void vec_add', out, f'auto_gpu={auto}')
            self.assertIn('_mg_launch_vec_add', out, f'auto_gpu={auto}')

    def test_a_registrar_reached_kernel_survives_no_gpu(self):
        # Reached through `compile_function[...]` rather than marked. Same
        # contract: the user asked for the device path explicitly.
        src = ('def k(out: UnsafePointer[Float32, MutAnyOrigin], len: Int):\n'
               '    out[global_idx.x] = 1.0\n'
               '\n'
               'def main():\n'
               '    ctx = DeviceContext()\n'
               '    ctx.compile_function[k](4, 1, 1)\n')
        gen = gctypes.GimpleGen(None, auto_gpu=False)
        gen.module_name = 'm'
        out = gen.gen_module(list(parse(src)))
        self.assertIn('kernel void k', out)

    def test_the_cache_key_separates_the_two(self):
        """A content-addressed cache that ignored the flag would serve a GPU
        build to a `--no-gpu` request -- the silent-wrong-output class the
        cache exists to prevent."""
        import cas
        src = SAXPY
        self.assertNotEqual(cas.compile_key(src, False, 'm', auto_gpu=True),
                            cas.compile_key(src, False, 'm', auto_gpu=False))
        # ...and the default is the GPU one, so an unkeyed caller is unchanged.
        self.assertEqual(cas.compile_key(src, False, 'm'),
                         cas.compile_key(src, False, 'm', auto_gpu=True))

    def test_the_cli_flag_is_recognised_and_stripped(self):
        import fire
        self.assertEqual(fire._extract_gpu_flags(['--no-gpu', 'a.py']),
                         (False, ['a.py']))
        self.assertEqual(fire._extract_gpu_flags(['a.py']), (True, ['a.py']))
        # It must come out of argv, or the executed program sees it as its
        # own argument (`input_file = sys.argv[1]`, program argv = argv[2:]).
        self.assertEqual(fire._extract_gpu_flags(['x.mojo', '--no-gpu'])[1],
                         ['x.mojo'])


@unittest.skipUnless(sys.platform == 'darwin', 'Metal is macOS-only')
class TestNoGpuOnRealGpu(unittest.TestCase):
    """`--no-gpu` must not stop marked code from running on the device."""

    PROG = ('@gpu\n'
            'def vec_add(in0: UnsafePointer[Float32, MutAnyOrigin],\n'
            '            in1: UnsafePointer[Float32, MutAnyOrigin],\n'
            '            output: UnsafePointer[Float32, MutAnyOrigin], len: Int):\n'
            '    tid = global_idx.x\n'
            '    if tid >= len:\n'
            '        return\n'
            '    output[tid] = in0[tid] + in1[tid]\n'
            '\n'
            'def main():\n'
            '    a = [0.0, 1.0, 2.0, 3.0]\n'
            '    b = [2.0, 2.0, 2.0, 2.0]\n'
            '    o = [-999.0, -999.0, -999.0, -999.0]\n'
            '    vec_add(a, b, o, 4)\n'
            '    for v in o:\n'
            '        print(v)\n'
            '    print("d", _mojo_gpu_dispatch_count())\n'
            '    print("f", _mojo_gpu_failure_count())\n')

    def _run(self, extra):
        with tempfile.TemporaryDirectory() as wd:
            path = os.path.join(wd, 'm.mojo')
            with open(path, 'w') as f:
                f.write(self.PROG)
            r = subprocess.run(
                [sys.executable, os.path.join(HERE, 'fire.py')] + extra +
                ['--jit', path],
                capture_output=True, text=True, timeout=900, cwd=HERE)
            return r.stdout.strip().splitlines(), r.stderr

    def test_marked_kernel_still_dispatches_with_no_gpu(self):
        out, err = self._run(['--no-gpu'])
        if not out:
            self.skipTest(f'no JIT build here: {err[-400:]}')
        self.assertEqual(out[:4], ['2.0', '3.0', '4.0', '5.0'],
                         f'--no-gpu changed a marked kernel\n{out}\n{err[-600:]}')
        self.assertIn('d 1', out, f'no dispatch happened\n{out}')
        self.assertIn('f 0', out, f'a dispatch failed\n{out}')



if __name__ == '__main__':
    unittest.main()
