"""The device sidecar: MSL into a C string, plus the host dispatch shims.

Seam 3 of ``doc/GPU_OFFLOAD_PLAN.html``. The device emitter
(``emit_metal.py``) produces MSL; this turns that MSL into something the
already-generated C can call, and it does so **inside the same .ci file**.

That single fact is the whole design. The alternative -- emit a second
artifact and run ``xcrun metal`` / ``xcrun metallib`` over it, which is
what ``doc/METAL.html`` proposes -- buys a precompiled binary and pays for
it with build wiring, a second file to ship, and a cache key that has to
be invalidated per GPU family. The Metal runtime compiles the same text at
load time, for whatever GPU is actually present, for the cost of one
``newLibraryWithSource:``. ``test_llm/kernels.metal.inc`` is the existing
proof of that trick working in this tree; this generalises it from a
hand-maintained file to compiler output.

**Everything emitted here is pure C, and that is a hard constraint rather
than a preference.** The generated ``.ci`` is compiled with
``gcc -fgimple -x c`` (``jit/arm64.py``), and gimple is a C front end:
Objective-C constructs -- ``@autoreleasepool``, ``id<MTLLibrary>``,
``MTLCreateSystemDefaultDevice`` -- do not survive it. So the Metal calls
go through a small C API implemented in the runtime
(``runtime/fire_metal.h`` / ``fire_metal.m``), exactly as every other
runtime capability in this tree already does, and this module emits only
calls into it.
"""

from __future__ import annotations

from typing import NamedTuple

#: C-escape a Python string into C string literal bodies. `?` is escaped for
#: trigraph safety: `??` followed by one of `=/()'<!>-` is eaten by a
#: conforming preprocessor as a digraph, and MSL is full of `?:`.
_C_ESCAPES = {
    '\\': '\\\\', '"': '\\"', '\n': '\\n', '\r': '\\r', '\t': '\\t',
    '?': '\\?',
}


def c_string_literal(text: str, indent: str = '', width: int = 72) -> str:
    """`text` as a sequence of adjacent C string literals.

    Adjacent literals concatenate, so the result is one runtime string with
    no copying at compile time. Chunked because the MSL for a real kernel is
    a few KB and one enormous source line makes the generated C unreadable
    in a diff or an editor.
    """
    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for ch in text:
        piece = _C_ESCAPES.get(ch, ch)
        if cur_len + len(piece) > width:
            out.append(indent + '"' + ''.join(cur) + '"')
            cur, cur_len = [], 0
        cur.append(piece)
        cur_len += len(piece)
    if cur:
        out.append(indent + '"' + ''.join(cur) + '"')
    return '\n'.join(out) if out else (indent + '""')


#: Kernel parameter annotation -> the C type the host wrapper takes it as.
#: Anything spelled as a pointer is a device buffer (it becomes an
#: `[[buffer(n)]]` argument); everything else is a scalar.
_POINTER_ANNOTATIONS = ('UnsafePointer[', 'Pointer[', 'DTypePointer[')

#: Element type inside a pointer annotation -> the C type of the array.
_ELEM_CTYPE = {
    'Float32': 'float', 'Float16': 'uint16_t', 'BFloat16': 'uint16_t',
    'Int32': 'int32_t', 'Int64': 'int64_t', 'Int': 'int64_t',
    'UInt32': 'uint32_t', 'Bool': 'int8_t',
}

#: Scalar parameter type -> (C storage type, BYTES the MSL declares for it).
#:
#: The byte count is the load-bearing half. emit_metal.py lowers a Mojo `Int`
#: to MSL `int`, so a `constant int &len` parameter reads 4 bytes; the host
#: has to hand over exactly 4. MSL has no `double`, and the device reads the
#: low bytes of whatever is bound, so passing a host double for an `int`
#: parameter delivers the wrong number rather than a compile error --
#: 1024.0 arrives as 0. These widths are the contract between the emitter
#: (which chose the MSL type) and the wrapper (which narrows the value).
_SCALAR_WIDTH = {
    'Int': ('int32_t', 4), 'Int32': ('int32_t', 4), 'UInt32': ('uint32_t', 4),
    'Int64': ('int64_t', 8), 'UInt64': ('uint64_t', 8),
    'Float32': ('float', 4), 'Float16': ('uint16_t', 2),
    'BFloat16': ('uint16_t', 2), 'Bool': ('int8_t', 1),
}


#: Origins that mean the kernel PROMISES not to write through the pointer.
#: An annotation with no origin, or a mutable one, is writable -- the
#: conservative direction, because an unnecessary write-back is wasted work
#: while a skipped one is a wrong answer.
_IMMUTABLE_ORIGINS = ('immut', 'imm')


def buffer_is_writable(annotation: str) -> bool:
    """Whether a kernel buffer parameter is declared WRITABLE.

    `UnsafePointer[Float32, ImmutAnyOrigin]` -> False (read-only).
    `UnsafePointer[Float32, MutAnyOrigin]`   -> True.
    `UnsafePointer[Float32]`                  -> True (no promise made).

    The origin is the ONLY place mutability is recorded: `_mojo_type` maps
    both spellings to the same `float *`, so the C type cannot answer this.
    """
    ann = (annotation or '').strip()
    if not ann.startswith(_POINTER_ANNOTATIONS):
        return True
    ann = ann.lower()
    for origin in _IMMUTABLE_ORIGINS:
        if origin in ann:
            return False
    return True


class LaunchArg(NamedTuple):
    """One kernel parameter, as the host marshalling sees it.

    A NamedTuple rather than a bare tuple because this grew a fifth field
    (writable) and every positional unpack of it broke at once. The accessors
    keep working when the next field arrives, and `writable` is the reason it
    exists: `_mojo_type` maps `UnsafePointer[Float32, MutAnyOrigin]` and
    `UnsafePointer[Float32, ImmutAnyOrigin]` to the SAME `float *`, so the C
    type cannot tell the host which buffers the kernel promised to write.
    """

    name: str
    ctype: str
    is_buffer: bool
    width: int
    writable: bool = True
    #: C expression giving THIS buffer's element count, for the pack and the
    #: copy-back. None means "the kernel's first Int/Int64 parameter", which is
    #: the historical single-length contract and still the right default.
    #:
    #: It exists because a GEMM has three buffers of three DIFFERENT lengths --
    #: A is M*K, B is K*N, C is M*N -- and one count cannot express that.
    #: Measured, that is not hypothetical: with every buffer cut to a single
    #: count, A is truncated to the first parameter's value and the kernel
    #: reads past it. Which is the same class of silent wrong answer as the
    #: offset-index refusal in 9798ee7b, one level up: there the length was
    #: right and the OFFSET was dropped; here the offset idea is fine and the
    #: LENGTH is wrong.
    #:
    #: Defaulting to None keeps every existing kernel and every existing test
    #: byte-identical; only kernels that ask for it get per-buffer lengths.
    length: str | None = None


class LaunchError(Exception):
    """A kernel whose host side cannot be marshalled honestly."""


def launch_arg_types(params) -> tuple[list[tuple[str, str, bool, int]], int]:
    """Per-parameter (name, c_type, is_buffer, scalar_width) for a kernel.

    `params` is the AST's `[(name, annotation_string), ...]`, straight off the
    FunctionDef -- usable without having run the C type inference, which is
    the point: a DEVICE function never reaches gen_func, so there is no
    inferred signature to read back.

    `scalar_width` is in bytes and is 0 for buffers. See `_SCALAR_WIDTH` for
    why it is not simply `sizeof(int64_t)`.

    The second return value is the index of the parameter used as the element
    count for the device->host copy-back, or -1. See `element_count_index`.
    """
    out: list[tuple[str, str, bool, int]] = []
    count_idx = -1
    for _i, (_pn, _ann) in enumerate(params):
        _ann = (_ann or '').strip()
        if _ann.startswith(_POINTER_ANNOTATIONS) or _ann.endswith('*'):
            _inner = (_ann[_ann.find('[') + 1:].split(',')[0].strip()
                      if '[' in _ann else 'Float32')
            out.append(LaunchArg(
                _pn, _ELEM_CTYPE.get(_inner, 'float') + ' *', True, 0,
                buffer_is_writable(_ann)))
        else:
            if count_idx < 0 and _ann in ('Int', 'Int64'):
                count_idx = _i
            _ct, _w = _SCALAR_WIDTH.get(_ann, ('int64_t', 8))
            out.append(LaunchArg(_pn, _ct, False, _w, True))
    return out, count_idx


def element_count_index(kernel: str, count_idx: int) -> int:
    """Which parameter gives the element count for the copy-back.

    A `float *` in C carries no length, so the host has to learn it from
    somewhere to copy results back. The contract is the kernel's first
    `Int`/`Int64` parameter -- which is the `len: Int` every hand-written
    kernel in this tree already has (see std/gpu/primitives/id.mojo and
    test_llm/metal.m).

    It is a CONTRACT, checked here, rather than a heuristic: a kernel with no
    length parameter cannot be marshalled, and silently copying back nothing
    would produce a program that runs, prints plausible numbers, and is
    wrong. The real fix is length-carrying buffers, which is already on the
    critical path for auto-offloading ordinary Python (no contiguous
    MojoList storage yet) -- so this raises instead of guessing.
    """
    if count_idx < 0:
        raise LaunchError(
            f'GPU kernel {kernel!r} has no Int/Int64 parameter, so the host '
            f'wrapper has no way to know how many elements to copy back from '
            f'the device. Add a `len: Int` parameter (the convention every '
            f'hand-written kernel here already uses), or use a length-carrying '
            f'buffer.')
    return count_idx


#: Per-kernel grid override, {kernel_name: (nthreads, ngroups)} as C
#: expressions. Empty unless the synthesiser populates it, so every existing
#: kernel keeps the inferred 0,0 grid and its generated C is unchanged.
_GRID: dict = {}


def emit_launch_wrappers(kernels: dict, grids: dict | None = None) -> str:
    """The per-kernel host wrapper each host call site targets.

    `kernels` maps kernel name -> (params, count index) as produced by
    `launch_arg_types` + `element_count_index`.

    The wrappers exist so the call site in emit_calls.py reads like an
    ordinary function call (`_mg_launch_vec_add(a, b, out, n)`) while the
    marshalling -- buffer table, length table, scalar narrowing to the width
    the MSL declares -- happens exactly once, here.
    """
    lines: list[str] = []
    for _kn, (params, count_idx) in kernels.items():
        count_idx = element_count_index(_kn, count_idx)
        _bufs = [(a.name, a.ctype) for a in params if a.is_buffer]
        _scals = [(a.name, a.ctype, a.width) for a in params
                 if not a.is_buffer]
        _sig = ', '.join(f'{a.ctype} {a.name}' for a in params) or 'void'
        lines.append('/* host wrapper for kernel %r */' % _kn)
        lines.append('void _mg_launch_%s(%s) {' % (_kn, _sig))
        if _bufs:
            lines.append('    void *_mg_bufs[] = {%s};'
                         % ', '.join(n for n, _ in _bufs))
            # A buffer's element count is its OWN `length` expression when the
            # kernel gave it one, and the kernel's single Int parameter
            # otherwise. The single-count rule is not abandoned: it is the
            # default, and it is what protects the common case where writing
            # past an output buffer because its own length was longer would be
            # heap corruption. What it could not express is a kernel whose
            # buffers genuinely differ -- a GEMM's A is M*K, B is K*N, C is
            # M*N -- and truncating A to the first parameter is the same class
            # of silent wrong answer as the dropped offset in 9798ee7b.
            lines.append('    int64_t _mg_sizes[] = {%s};'
                         % ', '.join((a.length or params[count_idx][0])
                                     for a in params if a.is_buffer))
        else:
            lines.append('    void *_mg_bufs[1]; int64_t _mg_sizes[1];')
        if _scals:
            for _j, (_n, _t, _w) in enumerate(_scals):
                lines.append('    %s _mg_sc%d = (%s)%s;' % (_t, _j, _t, _n))
            lines.append('    void *_mg_scalars[] = {%s};'
                         % ', '.join('&_mg_sc%d' % j
                                     for j in range(len(_scals))))
            lines.append('    static const uint8_t _mg_widths[] = {%s};'
                         % ', '.join(str(w) for _n, _t, w in _scals))
        else:
            lines.append('    void *_mg_scalars[1];')
            lines.append('    static const uint8_t _mg_widths[] = {8};')
        # Grid shape. The default 0,0 means "the runtime infers it": the
        # threadgroup count from the largest buffer's element count and the
        # width from the device max (fire_metal.m: `tg = ngroups > 0 ? ... :
        # ceil(max(sizes)/tptg)`, `use = nthreads > 0 ? ... : tptg`). That is
        # right for a kernel with ONE THREAD PER OUTPUT ELEMENT, which is every
        # kernel this tree had until now.
        #
        # It is wrong for a tensor-core GEMM, where 32 lanes cooperate on one
        # 8x8 output tile, so a grid of m*n threads would be ~32x too many and
        # 31 of every 32 would exit immediately. Both values are overridable in
        # the runtime already, so this needs no ABI change -- only for a kernel
        # to ask.
        _grid = _GRID.get(_kn)
        _nthr, _ngrp = _grid if _grid else (0, 0)
        lines.append('    _mg_run("%s", %d, _mg_bufs, _mg_sizes, %d, _mg_scalars,'
                     ' _mg_widths, %s, %s);'
                     % (_kn, len(_bufs), len(_scals), _nthr, _ngrp))
        lines.append('}')
        lines.append('')
    return '\n'.join(lines)


def _c_helper_name(elem_ctype: str) -> str:
    """A C identifier for a pack/unpack helper of `elem_ctype`.

    Same shape as the `_mojo_at_<T>` naming in module_gen, and for the same
    reason: the helper name has to be a stable function of the element type
    so it can be emitted once, deduplicated, and referenced from every call
    site that needs it.
    """
    return '_mg_pack_' + ''.join(
        ch if (ch.isalnum() or ch == '_') else '_' for ch in elem_ctype)


def _c_unpack_name(elem_ctype: str) -> str:
    return '_mg_unpack_' + _c_helper_name(elem_ctype)[len('_mg_pack_'):]


#: The C template for one element type's pack helper. `%s` is the element
#: type.
#:
#: The list length is NOT carried back from the packer to the unpacker, which
#: was the first design and was wrong twice over. A `int64_t *` out-parameter
#: means every call site needs an extra pointer VARIABLE, and a `_new_temp`
#: pointer is an uninitialised local -- passing it without initialising stores
#: through stack junk, and initialising it to NULL defeats the very write it
#: exists to receive. Neither is reachable from a wrong answer here; one
#: segfaults inside the helper.
#:
#: Recomputing `min(n, mojo_list_len(l))` on the unpack side gives the
#: identical count, because the callee is handed a `%(t)s *` and has no way
#: to reach the list -- so the length cannot have changed between the two
#: calls. Both helpers clamp to the list's real length, so a caller that
#: over-reports gets a short read rather than a read past the end.
_PACK_TEMPLATE = """static %(t)s *%(cn)s(MojoList *l, int64_t n) {
    int64_t len = l ? mojo_list_len(l) : 0;
    if (n < 0 || n > len) n = len;
    %(t)s *b = (%(t)s *)calloc(n < 1 ? 1 : n, sizeof(%(t)s));
    if (!b) return 0;
    for (int64_t i = 0; i < n; i++) b[i] = (%(t)s)mojo_list_get_double(l, i);
    return b;
}"""

_UNPACK_TEMPLATE = """static void %(un)s(MojoList *l, %(t)s *b, int64_t n) {
    if (!l || !b) return;
    int64_t len = mojo_list_len(l);
    if (n > len) n = len;
    for (int64_t i = 0; i < n; i++) mojo_list_set_double(l, i, (double)b[i]);
}"""


def list_marshalling_prototypes(elem_ctypes) -> str:
    """Forward declarations for the pack/unpack pair of each element type."""
    lines = ['/* list <-> contiguous buffer. A boxed list is NOT a buffer: each',
             '   element is one int64_t slot holding a bit-cast double. Casting a',
             '   MojoList* to T* instead points at the struct HEADER (data / len /',
             '   cap / inline array), so the callee reads the box as data --',
             '   measured: summing [1.0, 2.0, 3.0] that way printed 2.45e+26, at',
             '   exit 0. These two functions are the only place it happens. */']
    for _et in elem_ctypes:
        lines.append('static %s *%s(MojoList *l, int64_t n);'
                     % (_et, _c_helper_name(_et)))
        lines.append('static void %s(MojoList *l, %s *b, int64_t n);'
                     % (_c_unpack_name(_et), _et))
    return '\n'.join(lines)


def list_marshalling_definitions(elem_ctypes) -> str:
    """The pack/unpack pair for each element type."""
    lines = []
    for _et in elem_ctypes:
        _subs = {'t': _et, 'cn': _c_helper_name(_et), 'un': _c_unpack_name(_et)}
        lines.append(_PACK_TEMPLATE % _subs)
        lines.append(_UNPACK_TEMPLATE % _subs)
        lines.append('')
    return '\n'.join(lines)


def msl_module(parts: list[str]) -> str:
    """The accumulated MSL as one compilable translation unit.

    The device emitter is called per function, so what arrives is a list of
    complete `kernel void ... { ... }` definitions. They are concatenated
    and the runtime compiles them as ONE library: compiling a library is
    the expensive part, and every kernel carries the same two-line preamble.
    """
    return '\n\n'.join(parts)


def emit_launch_prototypes(kernels: dict) -> str:
    """Forward declarations for the launch wrappers.

    Emitted in the PREAMBLE, not next to the definitions: a host function
    can call a kernel that is declared later in the file, and without a
    prototype the call is an implicit declaration -- which then collides
    with the real `int64_t`/`float *` definition later as a
    "conflicting types" error pointing at the wrong line entirely.
    """
    lines: list[str] = []
    for _kn, (params, _ci) in kernels.items():
        _sig = ', '.join(f'{a.ctype} {a.name}' for a in params) or 'void'
        lines.append(f'void _mg_launch_{_kn}({_sig});')
    # The introspection entry points, unconditionally: they are REAL runtime
    # functions (registered in _RUNTIME_FUNCS, so a call from compiled Mojo
    # resolves to the sidecar's definition instead of colliding with a weak
    # auto-stub), and Mojo code can call them to check that the device path
    # was actually taken rather than trusting a plausible result.
    for _n in ('_mojo_gpu_kernel_count', '_mojo_gpu_have_device',
               '_mojo_gpu_dispatch_count', '_mojo_gpu_failure_count'):
        lines.append('int64_t %s(void);' % _n)
    if lines:
        lines.insert(0, '/* host entry points for this module\'s GPU kernels */')
    return '\n'.join(lines)


def c_suffix(module_name: str) -> str:
    """A C-identifier suffix distinguishing one module's device state from
    another's in a SINGLE translation unit.

    The MSL string, its init flag and its device flag are per MODULE and
    cannot be shared the way the pack/unpack helpers are: each module carries
    its own MSL, so one shared `_mg_msl_source` would compile the wrong
    kernels. And `static` does not rescue them -- `static` is internal
    linkage, so two `static int64_t _mg_init_state` in one FILE are still a
    redefinition. Measured, from a two-module program: six of them
    (`_mg_pack_float`, `_mg_msl_source`, `_mg_init_state`, ...).
    """
    out = ''.join(ch if (ch.isalnum() or ch == '_') else '_'
                  for ch in module_name)
    if not out:
        return ''
    return ('_' + out) if not out[0].isdigit() else ('_m' + out)


def emit_device_sidecar(parts: list[str], kernel_names: list[str],
                        kernels: dict | None = None,
                        module_name: str = '',
                        grids: dict | None = None) -> str:
    """The whole device sidecar as C text, ready to append to the module.

    `parts` and `kernel_names` are in the SAME order -- `module_gen` builds
    both in one pass over the functions -- so they pair positionally rather
    than by re-parsing the MSL to recover which kernel is which.
    """
    sfx = c_suffix(module_name)
    lines: list[str] = []
    lines.append('/* ── GPU device code ──')
    lines.append('   The MSL below is the compiler\'s output for this module\'s')
    lines.append('   @gpu/registered kernels, embedded as a string. mojo_metal_*')
    lines.append('   compiles it at load time for the GPU actually present, so')
    lines.append('   this file stays self-contained: no .metallib, no second')
    lines.append('   artifact, and nothing to wire into the build. */')
    lines.append('static const char *_mg_msl_source{sfx} =')
    lines.append(c_string_literal(msl_module(parts), indent='    '))
    lines.append(';')
    lines.append('')
    lines.append('/* Lazily initialised on FIRST DISPATCH, not at load. A module with a')
    lines.append('   kernel that is never called must not compile any MSL, and a')
    lines.append('   machine with no GPU must still load and run. */')
    lines.append('static int64_t _mg_init_state{sfx} = 0;   /* 0 uninit, 1 done */')
    lines.append('static int64_t _mg_have_device{sfx} = 0;')
    # The DISPATCH and FAILURE counters are NOT here. They were `static int64_t`
    # per-unit, so a program that dispatched in one module and asked in
    # another read the asker's zero. They are process-wide in the runtime now.
    lines.append('')
    lines.append('')
    lines.append('static void _mg_init{sfx}(void) {')
    lines.append('    if (_mg_init_state{sfx}) return;')
    lines.append('    _mg_init_state{sfx} = 1;')
    lines.append('    _mg_have_device{sfx} = (int64_t) mojo_metal_init(_mg_msl_source{sfx});')
    lines.append('}')
    lines.append('')
    lines.append('static int64_t _mg_run{sfx}(const char *name, int64_t n_bufs,')
    lines.append('                          void *const *bufs, const int64_t *sizes,')
    lines.append('                          int64_t n_scalars, void *const *scalars,')
    lines.append('                          const uint8_t *widths,')
    lines.append('                          int64_t nthreads, int64_t ngroups) {')
    lines.append('    _mg_init{sfx}();')
    lines.append('    if (!_mg_have_device{sfx}) {')
    # No counter bump here: mojo_metal_dispatch counts BOTH outcomes, and this
    # branch never reaches it -- it is the "no device at all" case, which
    # _mojo_gpu_have_device already reports. See the note in fire_metal.m.
    # Each C string literal is on ONE source line. An earlier version
    # wrapped these as Python implicit concatenation across several physical
    # lines, which emitted a C string split across source lines -- an
    # unterminated literal, and gcc reported it against whatever #line the
    # module last set, which was nowhere near the real cause.
    lines.append('        fprintf(stderr,')
    lines.append('            "mojo_gpu: kernel \'%s\' needs a Metal device and this "')
    lines.append('            "machine has none; the result is left untouched. "')
    lines.append('            "Move the work off the device path, or run on a "')
    lines.append('            "machine with a GPU.\\n", name);')
    lines.append('        return 0;')
    lines.append('    }')
    lines.append('    return (int64_t) mojo_metal_dispatch(name, n_bufs, bufs, sizes,')
    lines.append('                                    n_scalars, scalars, widths,')
    lines.append('                                    nthreads, ngroups);')
    lines.append('}')
    lines.append('')
    if kernels:
        # Populated by the synthesiser for a tensor-core GEMM; empty
        # otherwise, so every existing kernel keeps the inferred 0,0 grid.
        _GRID.update(grids or {})
        # The pack/unpack helpers are NOT emitted here: they live in the
        # preamble, next to the `_mojo_at_<T>` pointer helpers, because a call
        # site in an ordinary function body needs them and those bodies are
        # emitted before this tail.
        lines.append(emit_launch_wrappers(kernels, grids))
    lines.append('/* The device kernels this module contains. Lets a host program, or a')
    lines.append('   test, ask what was offloaded instead of guessing. */')
    lines.append('static const char *_mg_kernels[] = {')
    for name in kernel_names:
        lines.append(f'    "{name}",')
    lines.append('    0')
    lines.append('};')
    lines.append('')
    # These four are REAL runtime functions, and they are also CALLED from
    # compiled Mojo, so they must be in _RUNTIME_FUNCS with their true
    # signatures -- otherwise the C backend sees an unknown name, mints a
    # weak `int64_t f();` stub, and this definition collides with it
    # ("conflicting types"). That is the same reason `mojo_list_new` is
    # registered rather than declared ad hoc.
    #
    # There is deliberately no `_mojo_gpu_kernel_name`: returning a name
    # would mean handing back a pointer into static storage as an int64_t,
    # and a caller would have no way to read it.
    lines.append('__attribute__((weak)) int64_t _mojo_gpu_kernel_count(void)'
                 '   { return %d; }' % len(kernel_names))
    lines.append('__attribute__((weak)) int64_t _mojo_gpu_have_device(void)'
                 '  { _mg_init{sfx}(); return _mg_have_device{sfx}; }')
    lines.append('__attribute__((weak)) int64_t _mojo_gpu_dispatch_count(void)'
                 ' { return mojo_metal_dispatch_count(); }')
    lines.append('__attribute__((weak)) int64_t _mojo_gpu_failure_count(void)'
                 '  { return mojo_metal_failure_count(); }')
    return '\n'.join(lines).replace('{sfx}', sfx)


#: The introspection entry points, for a module with NO device code at all.
#:
#: `emit_device_sidecar` is skipped when a module offloads nothing, and it is
#: the only definition of these four. So a program that merely ASKS whether the
#: device path was taken could not be linked -- "implicit declaration of
#: function '_mojo_gpu_kernel_count'" -- which is precisely the question
#: `--no-gpu` makes interesting: with the flag, "did anything go to the GPU?"
#: should answer 0, not fail to build.
#:
#: Deliberately no `#include <fire_metal.h>`, no MSL, and no device
#: initialisation: a module with no kernels must not acquire a dependency on
#: the Metal runtime (see module_gen's preamble comment), and must stay
#: loadable on a machine with no GPU. `have_device` therefore reports 0 --
#: truthfully, nothing here can use a device.
EMPTY_SIDECAR = """\
/* No device code in this module, so there is nothing to offload. The
   introspection entry points still exist so a program can ASK whether the
   device path was taken -- which is the question --no-gpu makes worth asking
   -- and get an honest 0. See device_glue.EMPTY_SIDECAR. */
__attribute__((weak)) int64_t _mojo_gpu_kernel_count(void)    { return 0; }
__attribute__((weak)) int64_t _mojo_gpu_have_device(void)     { return 0; }
__attribute__((weak)) int64_t _mojo_gpu_dispatch_count(void)  { return 0; }
__attribute__((weak)) int64_t _mojo_gpu_failure_count(void)   { return 0; }
"""


def emit_introspection_prototypes() -> str:
    """Prototypes for the four introspection entry points, unconditionally.

    They are REAL runtime functions registered in _RUNTIME_FUNCS, so a call
    from compiled Mojo must resolve to a sidecar definition rather than
    colliding with a weak auto-stub. Emitted for every module, kernel or not.
    """
    return ('/* GPU introspection entry points; present in every module so a\n'
            '   program can ask whether the device path was taken. */\n'
            + '\n'.join(
                f'int64_t {_n}(void);' for _n in
                ('_mojo_gpu_kernel_count', '_mojo_gpu_have_device',
                 '_mojo_gpu_dispatch_count', '_mojo_gpu_failure_count')))
