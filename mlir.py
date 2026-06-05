"""mlir.py — strip-mined MLIR semantics for the Mojo reference backend.

Mojo's builtin scalar types are *newtypes over MLIR builtin types*, and their
methods are thin wrappers over MLIR ops.  For example the real stdlib `Int` is::

    struct Int:
        var _mlir_value: __mlir_type.index

        fn __add__(self, rhs) -> Int:
            return __mlir_op.`index.add`(self._mlir_value, rhs._mlir_value)

So to compile the *real* library we go all the way down to MLIR and replay the
semantics we depend on as plain C / GIMPLE primitives — then later build back up.
`__mlir_type.index` is just a machine word (`int64_t`); `index.add` is just `+`.

This module is deliberately **table-driven**.  We harvested the *entire* MLIR
surface used across the stdlib (``grep -rhoE '__mlir_op\\.`[^`]+`'`` etc. — ~130
distinct opcodes over the `index`, `pop`, `kgen`, `lit`, `co`, `nvvm`, `rocdl`,
`llvm`, `builtin` dialects) and classified all of it here at once:

  * what lowers to plain C now      → the op/type/attr tables below
  * what is value-preserving glue   → NOOP_OPS (identity / drop)
  * what we cannot honestly do on    → DEFERRED_OPS, with a reason.  These are
    the CPU yet (GPU, coroutines,      GPU kernels (Metal/CUDA — see METAL.md),
    atomics, vector SIMD, compiler     coroutine lowering, atomics, true vector
    intrinsics)                        SIMD, and compiler-internal kgen ops.

`gimple_codegen` calls the three entry points (`type_to_c`, `parse_attr`,
`lower_op`); adding a newly-met op is one row here, not new backend control flow.
"""
from __future__ import annotations


# ── small helpers ─────────────────────────────────────────────────────────

def unwrap(member: str) -> str:
    """Strip the backtick quoting MLIR identifiers carry, e.g. ``\\`index.add\\``."""
    m = member.strip()
    if len(m) >= 2 and m[0] == '`' and m[-1] == '`':
        m = m[1:-1]
    return m.strip()


# ── __mlir_type.<member> → C type ─────────────────────────────────────────
#
# The MLIR builtin types the stdlib's scalar newtypes are built on.  `index` is
# a native machine word; integer/float widths mirror our normal lattice; every
# pointer/address-space flavour collapses to a plain C pointer.

MLIR_TYPES: dict[str, str] = {
    # native machine word
    'index': 'int64_t',
    '!kgen.scalar<index>': 'int64_t',
    # fixed-width integers (signless / signed / unsigned spellings)
    'i1':  '_Bool', 'i8': 'int8_t', 'i16': 'int16_t', 'i32': 'int32_t', 'i64': 'int64_t',
    'si8':  'int8_t',   'si16': 'int16_t',  'si32': 'int32_t',  'si64': 'int64_t',
    'ui8':  'uint8_t',  'ui16': 'uint16_t', 'ui32': 'uint32_t', 'ui64': 'uint64_t',
    '!kgen.scalar<bool>': '_Bool',
    '!kgen.scalar<si8>':  'int8_t',
    '!kgen.scalar<ui8>':  'uint8_t',
    # floats
    'f16': '__fp16', 'f32': 'float', 'f64': 'double', 'bf16': 'float',
    # literals (comptime numerics that have materialized to a value)
    '!pop.int_literal': 'int64_t', '!pop.float_literal': 'double',
    # strings / pointers — all address spaces collapse to a C pointer
    '!kgen.string': 'char *',
    '!kgen.pointer<none>': 'void *',
    '!kgen.pointer<scalar<ui8>>': 'uint8_t *',
    '!llvm.ptr': 'void *', '!llvm.ptr<1>': 'void *', '!llvm.ptr<3>': 'void *',
    '!llvm.ptr<7>': 'void *', '!llvm.ptr<8>': 'void *',
    # nothing / never
    '!kgen.none': 'void', '!kgen.never': 'void',
}


def type_to_c(member: str) -> str | None:
    """Map a ``__mlir_type.<member>`` to its C type, or None if unknown.

    Compiler-internal / comptime-only types (``!kgen.type``, ``!kgen.dtype``,
    ``!kgen.deferred``, ``!co.routine``, ``!lit.origin.set`` …) have no runtime C
    representation and intentionally return None so the caller can fall back.
    """
    return MLIR_TYPES.get(unwrap(member))


# ── __mlir_op.<op> → C operator ───────────────────────────────────────────
#
# Binary ops keyed by full "dialect.op" name → C operator.  Signed/unsigned and
# index/arith/pop spellings share the operator; the operand C type carries
# signedness.

BINARY_OPS: dict[str, str] = {
    # index dialect (native machine-word arithmetic)
    'index.add': '+',  'index.sub': '-',  'index.mul': '*',
    'index.divs': '/', 'index.divu': '/', 'index.rems': '%', 'index.remu': '%',
    'index.and': '&',  'index.or': '|',   'index.xor': '^',
    'index.shl': '<<', 'index.shrs': '>>', 'index.shru': '>>',
    # pop dialect (scalar arithmetic on the builtin scalars)
    'pop.add': '+', 'pop.sub': '-', 'pop.mul': '*', 'pop.div': '/',
    'pop.rem': '%', 'pop.floordiv': '/', 'pop.shl': '<<', 'pop.shr': '>>',
    'pop.simd.and': '&', 'pop.simd.or': '|', 'pop.simd.xor': '^',
    # arith dialect (wider integer/float newtypes)
    'arith.addi': '+', 'arith.subi': '-', 'arith.muli': '*',
    'arith.divsi': '/', 'arith.divui': '/', 'arith.remsi': '%', 'arith.remui': '%',
    'arith.andi': '&', 'arith.ori': '|', 'arith.xori': '^',
    'arith.shli': '<<', 'arith.shrsi': '>>', 'arith.shrui': '>>',
    'arith.addf': '+', 'arith.subf': '-', 'arith.mulf': '*', 'arith.divf': '/',
}

# min/max have no C operator → emitted as a ternary.
MINMAX_OPS: dict[str, bool] = {
    'index.mins': True, 'index.maxs': False,   # True == min
    'pop.min': True, 'pop.max': False,
}

# Unary scalar ops → C operator or libm call ("{}" is the operand slot).
UNARY_OPS: dict[str, str] = {
    'pop.neg': '-{}', 'pop.abs': '__builtin_llabs({})',
    'pop.floor': '__builtin_floor({})', 'pop.ceil': '__builtin_ceil({})',
    'pop.round': '__builtin_round({})', 'pop.trunc': '({})',
}

# Ternary scalar ops → C expression over three operands ({0},{1},{2}).
TERNARY_OPS: dict[str, str] = {
    'pop.fma': '({0} * {1} + {2})',       # fused multiply-add
    'pop.select': '({0} ? {1} : {2})',    # select(cond, a, b)
}

# Comparisons: the C operator comes from the predicate attribute, not the op.
CMP_OPS: set[str] = {'index.cmp', 'pop.cmp', 'arith.cmpi', 'arith.cmpf'}

CMP_PRED: dict[str, str] = {
    'eq': '==', 'ne': '!=',
    'slt': '<', 'sle': '<=', 'sgt': '>', 'sge': '>=',
    'ult': '<', 'ule': '<=', 'ugt': '>', 'uge': '>=',
    'olt': '<', 'ole': '<=', 'ogt': '>', 'oge': '>=', 'oeq': '==', 'one': '!=',
    'lt': '<', 'le': '<=', 'gt': '>', 'ge': '>=',   # kgen cmp_pred short spellings
}

# Casts / bitcasts / reinterpretations between an MLIR builtin and our C scalar
# or pointer.  Value-preserving for the widths we model → a C cast.
CAST_OPS: set[str] = {
    'pop.cast_to_builtin', 'pop.cast_from_builtin', 'pop.cast', 'pop.bitcast',
    'pop.trunc', 'pop.pointer.bitcast', 'pop.pointer_to_index',
    'pop.noalias_pointer_cast', 'pop.union.bitcast', 'pop.variant.bitcast',
    'index.casts', 'index.castu',
    'arith.index_cast', 'arith.extsi', 'arith.extui', 'arith.trunci',
    'builtin.unrealized_conversion_cast',
}

# Memory / lvalue ops.  These need lvalue-aware, typed emission (a deref, a
# store statement, or pointer-offset via a helper), so mlir.py only *classifies*
# them; gimple_codegen emits them with operand C types and helper machinery.
#   load   (addr)        -> *addr
#   store  (val, addr)   -> *addr = val          [statement, no value]
#   offset (ptr, idx)    -> ptr + idx   (GIMPLE-legal via _mojo_at_ helper)
MEM_OPS: dict[str, str] = {
    'pop.load': 'load',
    'pop.store': 'store',
    'pop.offset': 'offset',
    'pop.array.gep': 'offset',   # element-address computation == pointer offset
}


def mem_op_kind(op: str) -> str | None:
    """Classify a memory/lvalue op (load/store/offset), or None."""
    return MEM_OPS.get(unwrap(op))


# Struct / aggregate GEP ops.  These take a struct value or pointer and a field
# index (an `index=` op param) and read the N-th field.  Like the memory ops,
# mlir.py only classifies; gimple_codegen resolves the struct layout and emits
# the field access (`v->fieldN` / `v.fieldN` / element N).
#   extract (struct_val)  [index=N]        -> struct_val.fieldN          (value)
#   gep     (struct_ptr)  [index=N,_type]  -> &struct_ptr->fieldN        (pointer)
#   aget    (array_val)   [index=N,_type]  -> array_val[N]               (element)
STRUCT_OPS: dict[str, str] = {
    'kgen.struct.extract': 'extract',
    'kgen.struct.gep': 'gep',
    'pop.array.get': 'aget',
}


def struct_op_kind(op: str) -> str | None:
    """Classify a struct/aggregate GEP op (extract/gep/aget), or None."""
    return STRUCT_OPS.get(unwrap(op))


# Value-preserving glue that produces its single operand unchanged: ownership
# markers (purely for the borrow checker) and ref/pointer identities.
NOOP_OPS: set[str] = {
    'lit.ownership.mark_initialized', 'lit.ownership.mark_destroyed',
    'lit.ref.to_pointer', 'lit.ref.from_pointer', 'lit.materialize_into',
    'kgen.rebind',
}

# ── Deferred: opcodes we are NOT yet honest about lowering to CPU C ─────────
# Kept explicit (with a reason) so we acknowledge the whole surface instead of
# rediscovering it one op at a time.  lower_op() returns None for these and
# deferral_reason() explains why, so the backend can emit a clear stub.

_DEFERRED_PREFIXES: dict[str, str] = {
    'nvvm.':  'GPU (NVIDIA) — see METAL.md / CUDA path',
    'rocdl.': 'GPU (AMD) — see METAL.md / ROCm path',
    'co.':    'coroutine lowering not modeled',
}

_DEFERRED_OPS: dict[str, str] = {
    # true vector SIMD (we only model width-1 / scalar lanes today)
    'pop.simd.splat': 'vector SIMD', 'pop.simd.shuffle': 'vector SIMD',
    'pop.simd.select': 'vector SIMD', 'pop.simd.reduce_or': 'vector SIMD',
    'pop.simd.reduce_and': 'vector SIMD', 'pop.simd.insertelement': 'vector SIMD',
    'pop.simd.extractelement': 'vector SIMD',
    # atomics / fences / inline asm / llvm intrinsics
    'pop.atomic.rmw': 'atomics', 'pop.atomic.cmpxchg': 'atomics',
    'pop.fence': 'memory fence', 'pop.inline_asm': 'inline asm',
    'pop.call_llvm_intrinsic': 'llvm intrinsic',
    'llvm.intr.trap': 'llvm intrinsic', 'llvm.intr.debugtrap': 'llvm intrinsic',
    'llvm.mlir.undef': 'undef value',
    # allocation / globals / symbols (need a memory model pass)
    'pop.stack_allocation': 'allocation', 'pop.global_alloc': 'allocation',
    'pop.global_constant': 'allocation', 'pop.aligned_alloc': 'allocation',
    'pop.aligned_free': 'allocation', 'pop.extern_ptr_symbol': 'symbol',
    # compiler-internal kgen / lit / variant machinery
    'kgen.compile_offload': 'compiler-internal', 'kgen.codegen.reachable': 'compiler-internal',
    'kgen.param.assert': 'compiler-internal', 'kgen.source_loc': 'compiler-internal',
    'kgen.variant.create': 'variant', 'kgen.variant.get': 'variant',
    'kgen.variant.is': 'variant', 'kgen.struct.load_indirect': 'struct indirection',
    'pop.variant.discr_gep': 'variant', 'pop.string.size': 'pop string',
    'pop.string.address': 'pop string', 'pop.dtype.to_ui8': 'dtype',
    'pop.dtype.from_ui8': 'dtype', 'lit.mojo.version.major': 'version constant',
    'lit.mojo.version.minor': 'version constant', 'lit.mojo.version.patch': 'version constant',
    'pop.external_call': 'route via external_call lowering instead',
    # struct/array GEP & memory access — need lvalue-aware emission (next pass)
    'kgen.struct.extract': 'struct field access (lvalue pass)',
    'kgen.struct.gep': 'struct field access (lvalue pass)',
    'kgen.struct.replace': 'struct field set (immutable struct update)',
    'pop.array.replace': 'array set (lvalue pass)', 'pop.array.repeat': 'array (lvalue pass)',
    'lit.ref.pack.extract': 'parameter pack ref (compiler-internal)',
    'lit.ref.struct.ger': 'struct field ref (lvalue pass)',
}


def deferral_reason(op: str) -> str | None:
    """Why we don't lower this op to CPU C yet, or None if we actually do."""
    name = unwrap(op)
    if name in _DEFERRED_OPS:
        return _DEFERRED_OPS[name]
    for pref, reason in _DEFERRED_PREFIXES.items():
        if name.startswith(pref):
            return reason
    return None


def parse_attr(member: str):
    """Interpret a ``__mlir_attr.<member>`` literal.

    Returns one of:
      * ``('int', value)``  typed integer attribute ``\\`0 : index\\```
      * ``('pred', name)``  comparison predicate, either MLIR
        ``\\`#index<cmp_predicate slt>\\``` or kgen ``\\`#kgen<cmp_pred ne>\\```
      * ``('simd', value)`` scalar simd constant ``\\`#kgen.simd<7> : ...\\```
      * ``('raw', text)``   anything we don't model yet
    """
    text = unwrap(member)

    # Comparison predicate (MLIR `cmp_predicate` / arith `cmpi_predicate` / kgen `cmp_pred`)
    if 'cmp_predicate' in text or 'cmpi_predicate' in text \
            or 'cmpf_predicate' in text or 'cmp_pred' in text:
        tok = text.rstrip('>').split()[-1]
        return ('pred', tok)

    # Scalar SIMD constant: `#kgen.simd<7> : !kgen.scalar<ui8>`
    if text.startswith('#kgen.simd<'):
        inner = text[len('#kgen.simd<'):].split('>', 1)[0]
        try:
            return ('simd', int(inner, 0))
        except ValueError:
            return ('raw', inner)

    # Typed integer attribute: `0 : index`, `42 : i32`, ...
    head = text.split(':', 1)[0].strip()
    try:
        return ('int', int(head, 0))
    except ValueError:
        pass

    return ('raw', text)


def lower_op(op: str, args: list[str], attrs: list[str],
             result_hint: str | None = None):
    """Lower a ``__mlir_op.<op>(args)`` call to a C expression.

    Args:
      op:          the op member, e.g. ``\\`index.add\\`` (backticks tolerated).
      args:        already-lowered operand C value strings.
      attrs:       unwrapped attribute strings from the op's ``[...]`` params
                   (e.g. the ``pred=`` of a compare).
      result_hint: a C type the caller expects, if known.

    Returns ``(result_ctype, c_expr)`` or ``None`` if the op isn't lowered
    (either deferred — see ``deferral_reason`` — or simply unmet).
    """
    name = unwrap(op)

    if name in BINARY_OPS and len(args) == 2:
        return ('int64_t', f"{args[0]} {BINARY_OPS[name]} {args[1]}")

    if name in MINMAX_OPS and len(args) == 2:
        a, b = args
        cmp = '<' if MINMAX_OPS[name] else '>'
        return ('int64_t', f"({a} {cmp} {b} ? {a} : {b})")

    if name in UNARY_OPS and len(args) == 1:
        return ('int64_t', UNARY_OPS[name].format(args[0]))

    if name in TERNARY_OPS and len(args) == 3:
        return ('int64_t', TERNARY_OPS[name].format(*args))

    if name in CMP_OPS and len(args) == 2:
        pred = None
        for a in attrs:
            kind, val = parse_attr(a)
            if kind == 'pred':
                pred = val
                break
        if pred is None or pred not in CMP_PRED:
            return None  # predicate not recoverable
        return ('_Bool', f"{args[0]} {CMP_PRED[pred]} {args[1]}")

    if name in CAST_OPS and len(args) == 1:
        target = result_hint or 'int64_t'
        return (target, f"({target}) {args[0]}")

    if name in NOOP_OPS and len(args) == 1:
        return (result_hint or 'int64_t', args[0])

    return None
