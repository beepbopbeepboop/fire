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
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import gimple_codegen as gctypes
import mojo.backend_gimple.device_select as dsel
import mojo.backend_gimple.emit_metal as eml
import mojo.middle.metal_ops as mops


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


if __name__ == '__main__':
    unittest.main()
