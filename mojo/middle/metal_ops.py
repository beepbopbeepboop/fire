"""MSL (Metal Shading Language) emission tables.

The Metal counterpart of ``mlir.py``, and deliberately built the same way:
**pure data, no gen object, no emission.** Every entry answers "given this
operation and these already-lowered operand strings, what MSL text do I
write?" — so the tables here can be read, and tested, without constructing
a GimpleGen or running an emitter.

Why a table at all, when MSL is C-like and most of an expression lowers to
itself? Because the parts that are *not* C-like are exactly the parts that
must not be guessed at:

- **``double`` does not exist in MSL**, at any language version. Every
  float is ``float`` (fp32). A silent ``float``/``double`` mixup here is a
  precision bug on the device that the host's fp64 reference will happily
  expose — but only if the comparison is run, which is why
  ``test_llm/bench.c`` prints ``max |diff|`` rather than trusting agreement.
- **Address spaces are load-bearing and are NOT pointers.** ``device``,
  ``threadgroup`` and ``constant`` are distinct, and conflating them is a
  silent miscompile: a ``threadgroup`` array read from ``device`` code
  returns garbage rather than trapping. This is precisely the collapse
  ``mlir.py`` performs for the host (every ``!llvm.ptr<N>`` becomes
  ``void *``, ``mlir.py:71-77``), which is correct for C and wrong here.
  So the host's ``void *`` representation must be *undone* on the way to a
  device, not inherited.
- **There is no libc.** ``sqrt``/``exp`` are ``metal::sqrt``; there is no
  ``printf``, no ``malloc``, no ``mojo_list_get_double``. A kernel operates
  on typed memory and nothing else.

Each of those is a place where "emit it like C" is not merely inelegant
but wrong, which is the whole reason this is a table and not a comment.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

#: C type -> MSL type. MSL has no ``double``; a Python/C ``double`` becomes
#: ``float`` (fp32). This is a precision *reduction* and callers that care
#: must compare against an fp64 host reference -- see ``test_llm/bench.c``,
#: which prints ``max |diff|`` per size rather than assuming agreement.
C_TO_MSL_TYPE: dict[str, str] = {
    'void': 'void',
    '_Bool': 'bool',
    'bool': 'bool',
    'char': 'char',
    'int8_t': 'char',
    'uint8_t': 'uchar',
    'int16_t': 'short',
    'uint16_t': 'ushort',
    'int32_t': 'int',
    'uint32_t': 'uint',
    'int64_t': 'long',
    'uint64_t': 'ulong',
    'size_t': 'ulong',
    'float': 'float',
    'double': 'float',      # the whole point: MSL has no double
    '__fp16': 'half',
}

#: MSL has no 64-bit float, and silently reading a ``long`` as one is the
#: kind of mistake that shows up as a plausible number. Anything mapped
#: through here is checked against this set before it is emitted.
_MSL_FLOAT_TYPES = frozenset({'float', 'half'})

#: The MSL builtin FUNCTION spellings of the thread indices. NOT used for
#: emission -- see :data:`INDEX_PARAM_NAMES` for why -- but kept because
#: they are the names an existing hand-written kernel body may already use,
#: and dropping them would turn a body that used to work into a build
#: error for no reason.
THREAD_INDEX_FNS: dict[str, str] = {
    'thread_index_in_threadgroup': 'thread_index_in_threadgroup',
    'threads_per_threadgroup': 'threads_per_threadgroup',
    'threadgroup_index_in_threadgroup': 'threadgroup_index_in_threadgroup',
    'threadgroups_per_threadgroup': 'threadgroups_per_threadgroup',
}

#: The stdlib's index VARIABLES (``std/gpu/primitives/id.mojo``) rewritten
#: onto MSL. This is the concrete form of "transform the hand-written
#: speciality code": upstream writes ``global_idx.x`` and this table says
#: what that means on a Metal device.
#:
#: They lower to GENERATED KERNEL PARAMETERS carrying the index attributes
#: (``uint g [[thread_position_in_grid]]``), not to the bare
#: ``thread_index_in_threadgroup``-style builtin FUNCTIONS. That is not a
#: preference: on this toolchain the builtin-function spellings do not
#: resolve at any language version (2.4 through 4.0 all report "use of
#: undeclared identifier 'thread_index_in_threadgroup'"), while the
#: attribute form is what the working hand-written kernels in
#: ``test_llm/kernels.metal`` use and what does compile. Probed, not
#: assumed.
#:
#: The names are an internal ABI between the emitter and these tables; the
#: leading underscores keep them out of the kernel's own namespace.
INDEX_PARAM_NAMES: dict[str, str] = {
    'thread_idx': '__lid',
    'block_idx': '__tgid',
    'grid_dim': '__nthreads',
    'block_dim': '__nthreads',
    'global_idx': '__gid',
    'lane_id': '(__lid % 32u)',
}

#: The index parameters every generated kernel carries, in signature order.
#: Emitting all of them unconditionally (rather than only the ones a body
#: mentions) keeps the signature a function of the KERNEL, not of the
#: body's current text -- so editing a body cannot silently change the ABI
#: the host side marshals against.
#: (internal name, MSL declaration). The two halves MUST agree: the
#: declaration's identifier is what the emitted signature spells, and the
#: internal name is what a body's ``global_idx`` rewrites to. They diverged
#: once during development and the symptom was MSL reporting "use of
#: undeclared identifier '__gid'" -- which is at least an honest error, but
#: only because the attribute parameter had to exist at all.
INDEX_PARAMS: list[tuple[str, str]] = [
    ('__gid', 'uint __gid [[thread_position_in_grid]]'),
    ('__tgid', 'uint __tgid [[threadgroup_position_in_grid]]'),
    ('__lid', 'uint __lid [[thread_position_in_threadgroup]]'),
    ('__nthreads', 'uint __nthreads [[threads_per_threadgroup]]'),
    # NOTE: there is deliberately no `threadgroups_per_threadgroup`
    # parameter. MSL has no such kernel ATTRIBUTE on this toolchain
    # ("unknown attribute 'threadgroups_per_threadgroup' ignored", and the
    # parameter is then rejected as an input declaration), and the value is
    # available to the host anyway -- it is part of the dispatch geometry,
    # not something the kernel has to be told.
]


#: Address space for a pointer, keyed by the host-side marker that produced
#: it. ``mlir.py:71-77`` maps ``!llvm.ptr<1>``/``<3>``/``<7>`` all to
#: ``void *``; this is the table that keeps them apart on the way back out.
#:
#: The LLVM address-space numbers are the stdlib's own (see
#: ``std/gpu/memory/memory.mojo``'s ``AddressSpace`` enum), so a pointer
#: that arrived tagged keeps its tag instead of being flattened.
ADDRESS_SPACE: dict[int, str] = {
    0: 'device',
    1: 'constant',
    3: 'threadgroup',
    7: 'threadgroup_cluster',
}

#: Address spaces a kernel ARGUMENT may have. ``threadgroup`` is not one of
#: them: a threadgroup array is declared and shared inside the kernel, not
#: passed in from the host, and a kernel signature naming one is a bug the
#: emitter should refuse rather than silently reinterpret as ``device``.
ARG_ALLOWED_ADDRESS_SPACES = frozenset({'device', 'constant'})

#: Memory-order flags for ``threadgroup_barrier``. The stdlib writes these
#: as ``mem_flags::mem_threadgroup`` (``std/gpu/sync/sync.mojo``), so the
#: table is keyed by the token AFTER the ``mem_flags::`` qualifier.
MEM_FLAGS: dict[str, str] = {
    'mem_none': 'mem_flags::mem_none',
    'mem_device': 'mem_flags::mem_device',
    'mem_threadgroup': 'mem_flags::mem_threadgroup',
    'mem_threadgroup_imageblock': 'mem_flags::mem_threadgroup_imageblock',
}

#: Types a Metal kernel ARGUMENT may have. MSL requires kernel inputs to be
#: 32-bit scalars (``int``/``uint``/``float``/``half``) or pointers --
#: ``long`` is rejected outright ("invalid type 'long' for input declaration
#: in a kernel function"), and so are 64-bit vectors. So the stdlib's
#: ``len: Int``, which resolves to ``int64_t``, is narrowed here.
#:
#: That narrowing is forced by the target rather than chosen: every GPU
#: kernel indexes with 32-bit arithmetic and MSL gives no alternative. It
#: is a table rather than an inline conditional so the constraint is
#: visible where it bites, and so a future 64-bit-argument target differs
#: from this one in exactly one place.
_KERNEL_ARG_NARROW: dict[str, str] = {
    'long': 'int', 'ulong': 'uint',
    'int64_t': 'int', 'uint64_t': 'uint',
}


def kernel_arg_type(c_ctype: str) -> str | None:
    """MSL type for a kernel ARGUMENT, narrowed to what MSL accepts.

    Refuses what it cannot honestly represent -- a struct, a 64-bit
    vector, a host container -- by returning None rather than guessing.
    """
    msl = msl_type(c_ctype)
    if msl is None:
        return None
    if msl.endswith('*'):
        # A pointer keeps its base, narrowed the same way a scalar is.
        return msl
    return _KERNEL_ARG_NARROW.get(msl, msl)


def msl_type(c_ctype: str) -> str | None:
    """MSL type for a host C type, or None if MSL has no equivalent.

    Pointers are handled by stripping the indirection and mapping the base,
    so ``float *`` gives ``float *`` and ``int64_t **`` gives ``long **``.
    The ADDRESS SPACE is deliberately not applied here: which space a
    pointer lives in is a property of the use, not of the C type (the host
    collapses every space to a bare pointer, see :func:`address_space`),
    so the caller adds it. Returning a bare ``float *`` from here is not a
    valid MSL type on its own and is not meant to be used as one.

    None is a refusal, not a default. A type this table does not know is
    a type that needs a decision (a struct layout? a pointer to what
    address space? a ``MojoList``, which cannot cross to a device at all?)
    and defaulting it to something plausible is how a kernel ends up
    silently wrong.
    """
    if c_ctype in C_TO_MSL_TYPE:
        return C_TO_MSL_TYPE[c_ctype]
    stripped = c_ctype.rstrip()
    while stripped.endswith('*'):
        stripped = stripped[:-1].rstrip()
    base = C_TO_MSL_TYPE.get(stripped)
    if base is None:
        return None
    # One `*` per level stripped, so the indirection is preserved exactly.
    return base + ' ' + '*' * (c_ctype.count('*'))


#: math function -> MSL namespaced call. No libc on the device; these live
#: in the ``metal`` namespace (which the emitted preamble pulls in with
#: ``using namespace metal``). Kept as an explicit table rather than
#: ``f"metal::{name}"`` because the set that ISN'T namespaced is larger
#: than it looks -- ``abs``/``min``/``max``/``clamp``/``sign`` are builtins,
#: not ``metal::`` functions, and a blanket prefix turns them into link
#: errors at best and wrong overload resolution at worst.
_MATH_FNS: dict[str, str] = {
    'sqrt': 'metal::sqrt', 'rsqrt': 'metal::rsqrt',
    'exp': 'metal::exp', 'exp2': 'metal::exp2', 'expm1': 'metal::expm1',
    'log': 'metal::log', 'log2': 'metal::log2', 'log10': 'metal::log10',
    'pow': 'metal::pow',
    'sin': 'metal::sin', 'cos': 'metal::cos', 'tan': 'metal::tan',
    'asin': 'metal::asin', 'acos': 'metal::acos', 'atan': 'metal::atan',
    'atan2': 'metal::atan2',
    'sinh': 'metal::sinh', 'cosh': 'metal::cosh', 'tanh': 'metal::tanh',
    'fabs': 'metal::fabs', 'fmod': 'metal::fmod',
    'floor': 'metal::floor', 'ceil': 'metal::ceil', 'trunc': 'metal::trunc',
    'rcp': 'metal::rcp',
}

#: Builtin (NOT namespaced) device functions. Separate from ``_MATH_FNS``
#: precisely because they are builtins -- see that table's comment.
_BUILTIN_FNS: dict[str, str] = {
    'abs': 'abs', 'fabs': 'fabs', 'min': 'min', 'max': 'max',
    'clamp': 'clamp', 'sign': 'sign', 'fma': 'fma', 'mix': 'mix',
    'saturate': 'saturate', 'isnan': 'isnan', 'isinf': 'isinf',
}

def is_float_type(msl: str) -> bool:
    return msl in _MSL_FLOAT_TYPES


def address_space(llvm_as: int | None) -> str:
    """MSL address-space keyword for an LLVM address-space number.

    Unknown numbers fall back to ``device``, which is the runtime's own
    default (``mlir.py:71-77`` maps every pointer there). Callers that care
    -- kernel signatures, in particular -- should check
    :data:`ARG_ALLOWED_ADDRESS_SPACES` rather than rely on this.
    """
    return ADDRESS_SPACE.get(llvm_as, 'device')


def intrinsic(name: str) -> str | None:
    """MSL spelling of a math/builtin function, or None if unrecognised."""
    return _MATH_FNS.get(name) or _BUILTIN_FNS.get(name)


def thread_index_fn(name: str) -> str | None:
    return THREAD_INDEX_FNS.get(name)


def index_var(name: str) -> str | None:
    """MSL expression for one of the stdlib's index VARIABLES, or None.

    Separate from :func:`thread_index_fn` on purpose: those are the MSL
    builtins under their own names, while these are the stdlib's names
    rewritten onto the generated index parameters.
    """
    return INDEX_PARAM_NAMES.get(name)


def mem_flag(name: str) -> str | None:
    return MEM_FLAGS.get(name)


# ---------------------------------------------------------------------------
# Statements the device supports
# ---------------------------------------------------------------------------

#: Ops MSL spells differently from C, or supports at all. Kept as a table
#: because the *absence* of an op is as informative as its presence: what is
#: not listed here is not something to guess at on a device.
DEVICE_BINOPS: dict[str, str] = {
    '+': '+', '-': '-', '*': '*', '/': '/', '%': '%',
    '&': '&', '|': '|', '^': '^', '<<': '<<', '>>': '>>',
}

#: Comparison operators, unchanged from C -- listed so a caller can CHECK
#: membership rather than assume, and so the set is in one place when MSL
#: diverges (it currently does not).
DEVICE_CMPOPS: dict[str, str] = {
    '<': '<', '>': '>', '<=': '<=', '>=': '>=',
    '==': '==', '!=': '!=',
}
