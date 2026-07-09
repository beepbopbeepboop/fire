"""
AST Interpreter for Mojo - executes parsed AST nodes from our parser.

This allows us to run Mojo code by:
1. Parsing .mojo files to AST
2. Executing AST via this interpreter
3. Comparing output to verify correctness

Eventually will be transpiled to .mojo for full bootstrap.
"""

import sys
import os
import re
import importlib
import types
import platform
import operator
import math
import collections
from dataclasses import dataclass
import ast_nodes as N
try:
    import mojo_compiler
except ImportError:
    mojo_compiler = None


class ReturnValue(Exception):
    """Exception used to implement return statements."""
    def __init__(self, value=None):
        self.value = value


class BreakException(Exception):
    """Exception used to implement break statements."""
    pass


class ContinueException(Exception):
    """Exception used to implement continue statements."""
    pass


class MojoError(Exception):
    """Real Mojo's builtin `Error` type — `raise Error("message")`. A real
    Python Exception subclass (not MojoRaisedException-wrapped) so a plain
    `except Exception:`/`except:` catches it via ordinary isinstance(),
    same as any other real exception here. Calls `Exception.__init__`
    directly rather than via `super()` — this file self-hosts, and the
    self-hosting compiler doesn't know what to do with `super()` at all
    (tries to call it as a plain undefined function named `_super`)."""
    def __init__(self, *args):
        Exception.__init__(self, ' '.join(str(a) for a in args))


class MojoRaisedException(Exception):
    """Marker exception for whatever value a Mojo `raise value` statement
    raised (a bare string, or an instance of a user-defined exception
    struct — see execute_RaiseStmt) that isn't already a real Python
    exception. Deliberately carries no fields/payload of its own — the
    self-hosting compiler (this file compiles itself) types an
    `except X as e:` binding as either a known struct pointer or a plain
    `char *` message string, never a generic boxed value, so an attribute
    like `e.mojo_value` can't work once self-hosted. The actual raised
    value instead goes through Interpreter._raised_mojo_value (an
    ordinary, already-well-typed field on a well-known struct) — see
    execute_RaiseStmt/_matches_exc_type."""
    pass


class Scope:
    """Manages variable and function scopes."""
    def __init__(self, parent=None):
        self.parent = parent
        self.vars = {}

    def define(self, name: str, value):
        self.vars[name] = value

    def get(self, name: str):
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"name '{name}' is not defined")

    def set(self, name: str, value):
        if name in self.vars:
            self.vars[name] = value
        elif self.parent:
            self.parent.set(name, value)
        else:
            self.vars[name] = value


class MojoFunction:
    """Represents a function defined in Mojo code."""
    def __init__(self, name, params, body, closure_scope, comptime_params=None):
        self.name = name
        self.params = params
        self.body = body
        self.closure_scope = closure_scope
        # Names from `def f[dtype: DType, ...](...)`'s bracketed generic
        # parameter list (see mojo_compiler.py's _parse_generic_params_capture)
        # — bound by `__getitem__` when the call site subscripts the
        # function (`f[Int32](...)`), not passed as regular arguments.
        self.comptime_params = comptime_params or []

    def __call__(self, interpreter, *args, **kwargs):
        return self._invoke(interpreter, {}, args, kwargs)

    def __getitem__(self, item):
        values = item if isinstance(item, tuple) else (item,)
        bindings = dict(zip(self.comptime_params, values))
        return _MojoBoundComptimeFunction(self, bindings)

    def _invoke(self, interpreter, comptime_bindings, args, kwargs):
        # Create new scope for function execution
        func_scope = Scope(parent=self.closure_scope)

        for name, value in comptime_bindings.items():
            func_scope.define(name, value)

        # Bind parameters to arguments
        for i, param in enumerate(self.params):
            if i < len(args):
                func_scope.define(param, args[i])
            elif param in kwargs:
                func_scope.define(param, kwargs[param])
            else:
                func_scope.define(param, None)


        # Execute function body
        old_scope = interpreter.scope
        interpreter.scope = func_scope
        try:
            for stmt in self.body:
                interpreter.execute(stmt)
            result = None
        except ReturnValue as ret:
            result = ret.value
        finally:
            interpreter.scope = old_scope

        return result


class _MojoBoundComptimeFunction:
    """Result of subscripting a generic function at a call site
    (`run_func[DType.float64](8, 0.125, ctx)`) — the comptime parameter
    names are pre-bound; calling it runs the function body with both those
    and the regular call-time arguments in scope."""
    def __init__(self, func, comptime_bindings):
        self.func = func
        self.comptime_bindings = comptime_bindings

    def __call__(self, interpreter, *args, **kwargs):
        return self.func._invoke(interpreter, self.comptime_bindings, args, kwargs)


class _NoOverloadMatch(TypeError):
    """Raised by MojoOverloadSet.__call__ when no candidate's arity/keywords
    match the call. A dedicated subclass (rather than a bare TypeError) so
    eval_CallExpr can attach the call site's location without also catching
    unrelated TypeErrors raised deeper inside whichever overload runs."""


class MojoOverloadSet:
    """Multiple `def name(...)` definitions sharing a name are Mojo overloads,
    not redefinitions of the same function — real Mojo picks the candidate
    whose signature matches the call site. We can only realistically dispatch
    on argument count and keyword names (the interpreter is untyped, so
    parameter *types* can't disambiguate); no match is a hard error rather
    than a silent first-pick, matching this project's own compiled-path
    overload-resolution philosophy (see gimple_codegen's "no-match overload
    returns None" test)."""
    def __init__(self, name):
        self.name = name
        self.candidates = []  # list of (MojoFunction, required, optional, kwonly, has_var_kwargs)

    def add(self, func, required, optional, kwonly, has_var_kwargs):
        self.candidates.append((func, required, optional, kwonly, has_var_kwargs))

    @staticmethod
    def _matches(spec, args, kwargs):
        required, optional, kwonly, has_var_kwargs = spec[1], spec[2], spec[3], spec[4]
        n = len(args)
        if n < len(required) or n > len(required) + len(optional):
            return False
        covered = (required + optional)[:n]
        for key in kwargs:
            if key in covered:
                return False  # supplied both positionally and by keyword
            if key not in required and key not in optional and key not in kwonly and not has_var_kwargs:
                return False
        for name in required[n:]:
            if name not in kwargs:
                return False
        return True

    def __call__(self, interpreter, *args, **kwargs):
        for spec in self.candidates:
            if self._matches(spec, args, kwargs):
                func = spec[0]
                return func(interpreter, *args, **kwargs)
        raise _NoOverloadMatch(
            f"no overload of '{self.name}' matches {len(args)} positional "
            f"arg(s) and keyword(s) {sorted(kwargs.keys())}"
        )


class _MojoWriter:
    """Minimal stand-in for real Mojo's `Writer` trait — `write_to`/
    `write_repr_to` methods call `writer.write(*args)` one or more times with
    a mix of strings/values to concatenate; this just accumulates them."""
    def __init__(self):
        self._parts = []

    def write(self, *args):
        for a in args:
            self._parts.append(str(a))

    def getvalue(self):
        return ''.join(self._parts)


class MojoInstance:
    """An instance of a Mojo-defined struct/class."""
    def __init__(self, mojo_class):
        self._mojo_class = mojo_class

    def _write_via(self, method_name):
        """Call a user-defined `write_to`/`write_repr_to(self, mut writer)`
        method, if the struct defines one, and return the accumulated text —
        or None if it doesn't (no reflection-based default synthesis here,
        unlike real Mojo's compiler-derived Writable for plain structs)."""
        method = self._mojo_class.methods.get(method_name)
        if method is None:
            return None
        writer = _MojoWriter()
        method(self._mojo_class.interpreter, self, writer)
        return writer.getvalue()

    def __str__(self):
        result = self._write_via('write_to')
        if result is not None:
            return result
        return repr(self)

    def __repr__(self):
        result = self._write_via('write_repr_to')
        if result is not None:
            return result
        result = self._write_via('write_to')
        if result is not None:
            return result
        return f"<{self._mojo_class.name} instance>"


class BoundMethod:
    """A struct/class method bound to a specific instance (`self` already filled in)."""
    def __init__(self, bound_func, instance, interpreter):
        self.bound_func = bound_func
        self.instance = instance
        self.interpreter = interpreter

    def __call__(self, *args, **kwargs):
        f = self.bound_func
        return f(self.interpreter, self.instance, *args, **kwargs)


class MojoClass:
    """Represents a class/struct defined in Mojo code."""
    def __init__(self, name, fields, methods, interpreter, bases=None,
                 comptime_aliases=None, static_methods=None):
        self.name = name
        self.fields = fields  # list of VarDecl/AssignStmt (field declarations)
        self.methods = methods  # dict: name -> MojoFunction
        self.interpreter = interpreter
        self.bases = bases or []  # base MojoClass objects, e.g. `struct Child(Base):`
        # `comptime EOF_TOKEN: Int = 69` inside the struct body — evaluated
        # once at struct-definition time and exposed as a class-level
        # attribute (`TokenType.EOF_TOKEN`), same as a Python class constant.
        self.comptime_aliases = comptime_aliases or {}
        # Names of `@staticmethod` methods — looked up here so __getattr__
        # can hand back the raw MojoFunction (no instance to bind) instead
        # of wrapping it in a BoundMethod.
        self.static_methods = static_methods or set()

    def __getattr__(self, name):
        # Only called when normal attribute lookup (real fields set in
        # __init__) fails, so plain `self.comptime_aliases`/`self.methods`
        # access here can't recurse — both are always set before this could
        # ever fire. (Deliberately not `self.__dict__.get(...)`: the
        # self-hosted compiled path has no Python-style __dict__.)
        if name in self.comptime_aliases:
            return self.comptime_aliases[name]
        if name in self.methods:
            # A method looked up on the class itself (StructType.method),
            # not an instance — return the raw MojoFunction unbound.
            # `@staticmethod`s are meant to be called this way; a regular
            # method returned this way just requires the caller to pass
            # `self` explicitly, matching Python's own unbound-method rule.
            return self.methods[name]
        raise AttributeError(f"'{self.name}' object has no attribute '{name}'")

    def __call__(self, *args, **kwargs):
        instance = MojoInstance(self)
        for f in self.fields:
            if self.interpreter._is_instance(f, 'VarDecl'):
                value = self.interpreter.eval_expr(f.value) if f.value is not None else None
                value = self.interpreter._coerce_to_declared_type(value, getattr(f, 'type_ann', None))
                setattr(instance, f.name, value)
            elif self.interpreter._is_instance(f, 'AssignStmt'):
                value = self.interpreter.eval_expr(f.value) if f.value is not None else None
                for target in f.targets:
                    if self.interpreter._is_instance(target, 'IdentExpr'):
                        setattr(instance, target.name, value)
        init = self.methods.get('__init__')
        if init is not None:
            init(self.interpreter, instance, *args, **kwargs)
        return instance

    def __getitem__(self, item):
        # A user-defined generic struct instantiated with explicit type/value
        # params, e.g. `Layout[Int]`. No monomorphization here — same
        # simplification as _MojoGenericCtor's `List[Int]`.
        return self


class _MojoGenericCtor:
    """Mojo's `List[Int]()`/`Dict[String, Int]()` subscript the type with its
    element type(s) before calling it. The interpreter has no generic-type
    system, so the subscript is a no-op — `List[Int]` and `List[String]` both
    just resolve back to this same constructor, and `[...]` is ignored."""
    def __init__(self, ctor):
        self._ctor = ctor

    def __call__(self, *args, **kwargs):
        ctor = self._ctor
        # Mojo's `List(1, 2, 3)`/`Set(1, 2, 3)` pass elements variadically;
        # Python's own list()/set()/deque() take a single iterable argument.
        if len(args) > 1 and not kwargs:
            return ctor(list(args))
        return ctor(*args, **kwargs)

    def __getitem__(self, item):
        return self


class _MojoBitcastToken:
    """`ptr.bitcast[NewType]()` — subscript with the target type (ignored, no
    real memory typing here), call with no arguments to get the same pointer
    back reinterpreted (a no-op, since `_MojoPointer` isn't typed)."""
    def __init__(self, pointer):
        self.pointer = pointer

    def __getitem__(self, type_arg):
        return self

    def __call__(self, *args, **kwargs):
        return self.pointer


class _MojoPointer:
    """Stand-in for real Mojo's `UnsafePointer[T]`. There's no real memory
    model here — it's a Python list (`buffer`) playing the role of the
    pointee's backing storage, plus an `offset` into it, so pointer
    arithmetic (`ptr + n`) and dereference (`ptr[]`, which the parser lowers
    to `ptr[0]` — see mojo_compiler.py's subscript parsing) both fall out of
    plain list indexing. `UnsafePointer(to=x)` boxes `x` into a fresh
    single-element buffer: reads/writes through the returned pointer work,
    but (unlike real Mojo) don't alias back to the original variable `x` —
    the interpreter has no way to take "the address of" a Python local."""
    def __init__(self, buffer, offset=0):
        self.buffer = buffer
        self.offset = offset

    def __getitem__(self, i):
        return self.buffer[self.offset + i]

    def __setitem__(self, i, value):
        self.buffer[self.offset + i] = value

    def load(self, i=0):
        return self.buffer[self.offset + i]

    def store(self, *args):
        # `ptr.store(value)` or `ptr.store(i, value)`.
        if len(args) == 1:
            i, value = 0, args[0]
        else:
            i, value = args[0], args[1]
        self.buffer[self.offset + i] = value

    def __add__(self, n):
        return _MojoPointer(self.buffer, self.offset + n)

    def __sub__(self, n):
        if isinstance(n, _MojoPointer):
            return self.offset - n.offset
        return _MojoPointer(self.buffer, self.offset - n)

    def __eq__(self, other):
        if not isinstance(other, _MojoPointer):
            return NotImplemented
        return self.buffer is other.buffer and self.offset == other.offset

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self):
        return id(self.buffer) ^ self.offset

    def __bool__(self):
        return True

    def __int__(self):
        # A real (if fake) nonzero "address" — enough for `assert_not_equal(0, Int(ptr))`.
        return id(self.buffer) + self.offset

    def __repr__(self):
        return f"UnsafePointer(0x{self.__int__():x})"

    def free(self):
        pass  # no real memory to release; Python GC owns `buffer`

    def as_immutable(self):
        return self

    def as_unsafe_any_origin(self):
        return self

    def address_space_cast(self, *args, **kwargs):
        return self

    @property
    def bitcast(self):
        # Real Mojo calls this as `ptr.bitcast[NewType]()` — subscript with
        # the target type, then call. A plain method can't be subscripted
        # (`ptr.bitcast[T]` would try to subscript a bound method object), so
        # this is a property returning a subscript-then-call token instead.
        return _MojoBitcastToken(self)

    def address_of(self):
        return self

    def map_to_host(self):
        # Real Mojo's `with dev_buf.map_to_host() as host_buf:` copies device
        # memory to host-visible memory for the duration of the `with` block.
        # There's no real device/host split in this simulation — buffers
        # allocated by `DeviceContext.enqueue_create_buffer` are already
        # plain host lists — so this just hands back the same pointer.
        return _MojoMapToHostCtx(self)

    def enqueue_copy_to(self, other):
        # `ctx.enqueue_copy(dst, src)` / `src.enqueue_copy_to(dst)`.
        for i in range(len(self.buffer) - self.offset):
            other[i] = self[i]


class _MojoMapToHostCtx:
    def __init__(self, ptr):
        self.ptr = ptr

    def __enter__(self):
        return self.ptr

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _MojoUnsafePointerType:
    """`UnsafePointer[Int]` (subscript ignored, no generic-type system),
    `UnsafePointer(to=x)` (address-of, see _MojoPointer), and
    `UnsafePointer.alloc(n)` (fresh n-element backing buffer)."""
    def __getitem__(self, item):
        return self

    def __call__(self, to=None, **kwargs):
        return _MojoPointer([to])

    def alloc(self, count, *args, **kwargs):
        return _MojoPointer([None] * count)

    def copy(self, ptr):
        return _MojoPointer(list(ptr.buffer), ptr.offset)


class _MojoDim3:
    """Mutable (x, y, z) thread/block coordinate — backs the `thread_idx`/
    `block_idx`/`block_dim`/`grid_dim` globals a GPU kernel body reads.
    Mutable and shared (one instance per interpreter, updated in place by
    `_MojoEnqueueFunctionCall` before each simulated thread's invocation)
    rather than rebound per thread, since a kernel reads these as bare
    module-level names, not as parameters it's passed."""
    def __init__(self, x=0, y=0, z=0):
        self.x = x
        self.y = y
        self.z = z

    def __repr__(self):
        return f"({self.x}, {self.y}, {self.z})"


def _mojo_as_dim3(d):
    """Normalize a `grid_dim=`/`block_dim=` argument (a bare int for 1-D, or
    an (x, y, z)-ish tuple/list) to an (x, y, z) tuple."""
    if isinstance(d, int):
        return (d, 1, 1)
    if isinstance(d, (tuple, list)):
        vals = list(d) + [1, 1, 1]
        return (vals[0], vals[1], vals[2])
    return (getattr(d, 'x', 1), getattr(d, 'y', 1), getattr(d, 'z', 1))


class _MojoEnqueueFunctionCall:
    """`ctx.enqueue_function[kernel](*args, grid_dim=.., block_dim=..)` —
    there's no real GPU to dispatch to, so this "launches" the kernel by
    just calling it once per simulated thread, serially, on the CPU, with
    `thread_idx`/`block_idx`/`block_dim`/`grid_dim` updated before each call.
    Fine for correctness testing of small kernels; a launch with a large
    grid (real GPU workloads routinely use thousands+ of threads) will be
    slow, since this is genuinely serial — there's no parallelism here at
    all, simulated or otherwise."""
    def __init__(self, kernel, interpreter):
        self.kernel = kernel
        self.interpreter = interpreter

    def __call__(self, *args, grid_dim=1, block_dim=1, **kwargs):
        interpreter = self.interpreter
        kernel = self.kernel
        grid = _mojo_as_dim3(grid_dim)
        block = _mojo_as_dim3(block_dim)
        thread_idx = interpreter.scope.get('thread_idx')
        block_idx = interpreter.scope.get('block_idx')
        block_dim_g = interpreter.scope.get('block_dim')
        grid_dim_g = interpreter.scope.get('grid_dim')
        global_idx = interpreter.scope.get('global_idx')
        block_dim_g.x, block_dim_g.y, block_dim_g.z = block
        grid_dim_g.x, grid_dim_g.y, grid_dim_g.z = grid
        for bz in range(grid[2]):
            for by in range(grid[1]):
                for bx in range(grid[0]):
                    block_idx.x, block_idx.y, block_idx.z = bx, by, bz
                    for tz in range(block[2]):
                        for ty in range(block[1]):
                            for tx in range(block[0]):
                                thread_idx.x, thread_idx.y, thread_idx.z = tx, ty, tz
                                global_idx.x = bx * block[0] + tx
                                global_idx.y = by * block[1] + ty
                                global_idx.z = bz * block[2] + tz
                                interpreter.invoke(kernel, *args)


class _MojoEnqueueFunctionAccessor:
    def __init__(self, interpreter):
        self.interpreter = interpreter

    def __getitem__(self, item):
        # `ctx.enqueue_function[kernel]` or `[kernel, extra_type_param, ...]`
        # — the kernel function is always the first element when subscripted
        # with more than one.
        kernel = item[0] if isinstance(item, tuple) else item
        return _MojoEnqueueFunctionCall(kernel, self.interpreter)


class _MojoCreateBufferCall:
    def __init__(self, dtype):
        self.dtype = dtype

    def __call__(self, size, *args, **kwargs):
        fill = 0.0 if getattr(self.dtype, '_is_float', False) else 0
        return _MojoPointer([fill] * size)


class _MojoCreateBufferAccessor:
    def __getitem__(self, dtype):
        return _MojoCreateBufferCall(dtype)


class _MojoDeviceContext:
    """Stand-in for real Mojo's `std.gpu.host.DeviceContext`. This
    interpreter has no GPU backend of any kind (simulated or otherwise) —
    kernels launched via `enqueue_function` just run serially on the CPU,
    see `_MojoEnqueueFunctionCall`. Good enough to exercise a kernel's
    *logic* (the actual point of most stdlib correctness tests, which
    typically launch a `grid_dim=1, block_dim=1` single-thread kernel), not
    to test anything about real device dispatch, memory transfer cost, or
    concurrency."""
    def __init__(self, device_id=0, api=None, interpreter=None):
        self.device_id = device_id
        self.api = api or 'cpu'
        self.interpreter = interpreter

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def name(self):
        return "CPU (simulated — no GPU backend in this interpreter)"

    def synchronize(self):
        pass

    def __eq__(self, other):
        return isinstance(other, _MojoDeviceContext) and self.device_id == other.device_id

    def __hash__(self):
        return id(self)

    @property
    def enqueue_function(self):
        return _MojoEnqueueFunctionAccessor(self.interpreter)

    @property
    def enqueue_create_buffer(self):
        return _MojoCreateBufferAccessor()

    def enqueue_copy(self, dst, src):
        if isinstance(src, _MojoPointer):
            src.enqueue_copy_to(dst)
        else:
            for i, v in enumerate(src):
                dst[i] = v

    def enqueue_memset(self, dst, value):
        for i in range(len(dst.buffer) - dst.offset):
            dst[i] = value


class _MojoGPUInfo:
    """Stand-in for `std.gpu.host.info.GPUInfo` — real per-architecture GPU
    capability lookup. `from_name[arch]()` always returns this same generic
    placeholder, since there's no real accelerator here to describe."""
    api = "cpu"

    def __repr__(self):
        return "GPUInfo(cpu, simulated)"


class _MojoGPUInfoType:
    def __getitem__(self, item):
        return self

    def __call__(self, *args, **kwargs):
        return _MojoGPUInfo()

    @property
    def from_name(self):
        return self


class _MojoAddressSpaceValue:
    def __init__(self, name, value):
        self._name = name
        self.value = value

    def __repr__(self):
        return f"AddressSpace.{self._name}"

    def __eq__(self, other):
        if isinstance(other, _MojoAddressSpaceValue):
            return self.value == other.value
        return NotImplemented

    def __hash__(self):
        return self.value


class _MojoAddressSpaceNS:
    """Stand-in for `std.memory.pointer.AddressSpace` — an enum-like
    namespace of GPU memory-space markers. Meaningless without a real GPU
    backend; kept only so code that names/prints/compares them doesn't
    crash."""
    GENERIC = _MojoAddressSpaceValue('GENERIC', 0)
    GLOBAL = _MojoAddressSpaceValue('GLOBAL', 1)
    SHARED = _MojoAddressSpaceValue('SHARED', 2)
    CONSTANT = _MojoAddressSpaceValue('CONSTANT', 3)
    LOCAL = _MojoAddressSpaceValue('LOCAL', 4)


class _MojoTrace:
    """Stand-in for `std.runtime.tracing.Trace` — a profiling-span context
    manager. No-op here; there's no real runtime to trace."""
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _MojoInvokeWrapper:
    """A plain-callable adapter around Interpreter.invoke, so real Python
    builtins (map/filter) that call their function argument directly
    (`func(item)`) can invoke a MojoFunction (which needs the interpreter
    threaded through as its first argument) transparently."""
    def __init__(self, func, interpreter):
        self._func = func
        self._interpreter = interpreter

    def __call__(self, *args, **kwargs):
        func = self._func
        interpreter = self._interpreter
        return interpreter.invoke(func, *args, **kwargs)


class _MojoBoundArgCall:
    """Result of `map[func]`/`filter[func]` — the wrapped builtin partially
    applied with `func` as its first (call-time) argument."""
    def __init__(self, fn, wrapped_func):
        self._fn = fn
        self._wrapped_func = wrapped_func

    def __call__(self, *args, **kwargs):
        fn = self._fn
        wrapped_func = self._wrapped_func
        return fn(wrapped_func, *args, **kwargs)


class _MojoParametricFn:
    """Wraps a builtin like `map` that real Mojo calls as `map[func](iterable)`
    — the function argument goes in the subscript, not the call parens (the
    subscript is Mojo's compile-time-parameter syntax, here just borrowed for
    an ordinary runtime argument). `[func]` curries it in; the returned
    callable then takes the normal call-time arguments."""
    def __init__(self, fn, interpreter):
        self._fn = fn
        self._interpreter = interpreter

    def __getitem__(self, bound_arg):
        wrapped_func = _MojoInvokeWrapper(bound_arg, self._interpreter)
        return _MojoBoundArgCall(self._fn, wrapped_func)

    def __call__(self, *args, **kwargs):
        fn = self._fn
        return fn(*args, **kwargs)


class _MojoScalarType:
    """A sized Mojo scalar type (Int8/UInt32/Float32/...). Plain Python
    int/float already behave like the value side of these types; this only
    carries the `.size_bytes` metadata that `size_of[T]()`/`align_of[T]()`/
    `bit_width_of[T]()` read off the type itself."""
    def __init__(self, name, size_bytes, is_float=False):
        self.name = name
        self.size_bytes = size_bytes
        self._is_float = is_float

    def __call__(self, x=0):
        return float(x) if self._is_float else int(x)

    def __repr__(self):
        return self.name

    def is_floating_point(self):
        return self._is_float

    def is_integral(self):
        return not self._is_float

    def is_signed(self):
        return not self.name.startswith('UInt')

    def is_unsigned(self):
        return self.name.startswith('UInt')

    def is_half_float(self):
        return self.name in ('Float16', 'BFloat16')

    def is_single_float(self):
        return self.name == 'Float32'

    def is_double_float(self):
        return self.name == 'Float64'


class _MojoTypeInfoCall:
    def __init__(self, fn, type_arg):
        self._fn = fn
        self._type_arg = type_arg

    def __call__(self):
        fn = self._fn
        type_arg = self._type_arg
        return fn(type_arg)


class _MojoTypeInfoFn:
    """`size_of[T]()`/`align_of[T]()`/`simd_width_of[T]()`/`bit_width_of[T]()`
    — subscript with a type (or DType.xxx value), call with no arguments."""
    def __init__(self, fn):
        self._fn = fn

    def __getitem__(self, type_arg):
        fn = self._fn
        return _MojoTypeInfoCall(fn, type_arg)


class _MojoConstCall:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class _MojoGetDefinedFn:
    """`get_defined_bool["NAME", default]()`/`get_defined_int[...]` — reads a
    compile-time `-D` define, subscripted as `[name, default]`. This
    interpreter has no build-time define mechanism, so it always falls back
    to whatever default the call site supplied."""
    def __getitem__(self, args):
        default = args[1] if isinstance(args, tuple) and len(args) >= 2 else None
        return _MojoConstCall(default)


class _MojoIsDefinedFn:
    """`is_defined["MODULAR_SOME_FLAG"]()` — no build-time `-D` define
    mechanism here, so always False."""
    def __getitem__(self, name):
        return _MojoConstCall(False)


def _mojo_size_of(t):
    return getattr(t, 'size_bytes', 8)


def _mojo_bit_width_of(t):
    return getattr(t, 'size_bytes', 8) * 8


def _mojo_simd_width_of(t):
    # Not hardware-accurate (real Mojo picks this per-target); 1 is at least
    # a self-consistent value (a "vector" of width 1 is just the scalar).
    return 1


class _MojoCompilationTarget:
    """Stand-in for real Mojo's `sys.info.CompilationTarget` platform-predicate
    namespace. Answers for *this* interpreter host (macOS/arm64), not
    whatever `mojo build` would actually target — fine for the predicates
    stdlib tests branch on, since we're not cross-compiling."""
    def is_macos(self):
        return sys.platform == 'darwin'

    def is_linux(self):
        return sys.platform.startswith('linux')

    def is_apple_silicon(self):
        return sys.platform == 'darwin' and platform.machine() == 'arm64'

    def is_apple_m1(self): return False
    def is_apple_m2(self): return False
    def is_apple_m3(self): return False
    def is_apple_m4(self): return False
    def is_apple_m5(self): return False
    def has_neon(self):
        return platform.machine() == 'arm64'
    def has_neon_int8_dotprod(self): return False
    def has_neon_int8_matmul(self): return False
    def has_avx(self): return False
    def has_avx2(self): return False
    def has_avx512f(self): return False
    def has_sse4(self): return False
    def has_fma(self): return False
    def has_vnni(self): return False
    def has_intel_amx(self): return False


def _mojo_simd_elementwise(a, b, fn):
    """Combine two SIMD-or-scalar operands lane-by-lane with `fn` (used for
    arithmetic operators and for the elementwise `min`/`max` builtins Mojo
    overloads for SIMD — unlike Python's own min/max, which just pick one of
    their two whole arguments)."""
    if isinstance(a, _MojoSIMD) and isinstance(b, _MojoSIMD):
        return _MojoSIMD(a.dtype, a.width, [fn(x, y) for x, y in zip(a.values, b.values)])
    if isinstance(a, _MojoSIMD):
        return _MojoSIMD(a.dtype, a.width, [fn(x, b) for x in a.values])
    if isinstance(b, _MojoSIMD):
        return _MojoSIMD(b.dtype, b.width, [fn(a, y) for y in b.values])
    return fn(a, b)


def _scalar_max2(a, b):
    if a > b:
        return a
    return b


def _scalar_min2(a, b):
    if a < b:
        return a
    return b


def _mojo_max(*args, **kwargs):
    """Mojo overloads `max` for SIMD to mean elementwise max, not "pick one
    of these two whole values" like Python's own builtin. Deliberately
    avoids ever calling the bare name `max(...)`/`min(...)`: this file is
    self-hosted-compiled together with gimple_codegen.py, which has an
    existing single-positional-plus-`key=`-kwarg call site
    (`max(survivors, key=_score)`) that fixes the self-host compiler's
    static arity inference for the global `max` symbol at 1 argument —
    calling it here with 2 positional args breaks that compile
    ("too many arguments to function 'mojo_max'")."""
    if len(args) == 2 and not kwargs:
        a, b = args
        if isinstance(a, _MojoSIMD) or isinstance(b, _MojoSIMD):
            return _mojo_simd_elementwise(a, b, _scalar_max2)
        return _scalar_max2(a, b)
    items = args[0] if len(args) == 1 else args
    result = None
    have_result = False
    for x in items:
        if not have_result:
            result = x
            have_result = True
        elif x > result:
            result = x
    return result


def _mojo_min(*args, **kwargs):
    if len(args) == 2 and not kwargs:
        a, b = args
        if isinstance(a, _MojoSIMD) or isinstance(b, _MojoSIMD):
            return _mojo_simd_elementwise(a, b, _scalar_min2)
        return _scalar_min2(a, b)
    items = args[0] if len(args) == 1 else args
    result = None
    have_result = False
    for x in items:
        if not have_result:
            result = x
            have_result = True
        elif x < result:
            result = x
    return result


class _MojoSIMD:
    """Stand-in for real Mojo's `SIMD[dtype, width]` vector type. No real
    vectorization/hardware backend here — just a fixed-width list of scalars
    with elementwise arithmetic. `==`/`!=` compare whole vectors (True only
    if every lane matches, returning a plain bool) rather than real Mojo's
    per-lane vector result, since that's what `assert_equal(simd_a, simd_b)`
    needs; ordering comparisons (`<`, `>`, ...) return a real elementwise
    `_MojoSIMD` of bools, closer to actual Mojo semantics."""
    def __init__(self, dtype, width, values):
        values = list(values)
        if len(values) == 1 and width > 1:
            values = values * width
        self.dtype = dtype
        self.width = width
        self.values = values

    def _binary(self, other, fn):
        return _mojo_simd_elementwise(self, other, fn)

    def __add__(self, other): return self._binary(other, operator.add)
    def __radd__(self, other): return _mojo_simd_elementwise(other, self, operator.add)
    def __sub__(self, other): return self._binary(other, operator.sub)
    def __rsub__(self, other): return _mojo_simd_elementwise(other, self, operator.sub)
    def __mul__(self, other): return self._binary(other, operator.mul)
    def __rmul__(self, other): return _mojo_simd_elementwise(other, self, operator.mul)
    def __truediv__(self, other): return self._binary(other, operator.truediv)
    def __rtruediv__(self, other): return _mojo_simd_elementwise(other, self, operator.truediv)
    def __floordiv__(self, other): return self._binary(other, operator.floordiv)
    def __mod__(self, other): return self._binary(other, operator.mod)
    def __pow__(self, other): return self._binary(other, operator.pow)
    def __and__(self, other): return self._binary(other, operator.and_)
    def __or__(self, other): return self._binary(other, operator.or_)
    def __xor__(self, other): return self._binary(other, operator.xor)
    def __neg__(self): return _MojoSIMD(self.dtype, self.width, [-v for v in self.values])
    def __abs__(self): return _MojoSIMD(self.dtype, self.width, [abs(v) for v in self.values])

    def __eq__(self, other):
        if isinstance(other, _MojoSIMD):
            return self.values == other.values
        return all(v == other for v in self.values)

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = None

    def __lt__(self, other): return self._binary(other, operator.lt)
    def __gt__(self, other): return self._binary(other, operator.gt)
    def __le__(self, other): return self._binary(other, operator.le)
    def __ge__(self, other): return self._binary(other, operator.ge)

    def __getitem__(self, i): return self.values[i]
    def __setitem__(self, i, v): self.values[i] = v
    def __len__(self): return len(self.values)
    def __iter__(self): return iter(self.values)
    def __bool__(self): return all(bool(v) for v in self.values)

    def __repr__(self):
        vals = ', '.join(str(v) for v in self.values)
        return f"SIMD[{self.width}]({vals})"


class _MojoSIMDCtor:
    def __init__(self, dtype, width):
        self.dtype = dtype
        self.width = width

    def __call__(self, *values):
        return _MojoSIMD(self.dtype, self.width, values)


class _MojoSIMDType:
    """`SIMD[DType.float32, 4](0.0, 1.5, -42.5, -12.7)` — subscript with
    (dtype, width), call with `width` scalar values (or a single value,
    broadcast to fill every lane)."""
    def __getitem__(self, item):
        dtype, width = item
        return _MojoSIMDCtor(dtype, width)


class MojoString(str):
    """`str` subclass carrying the extra methods real Mojo's String/
    StringSlice/StaticString expose that plain Python str doesn't
    (`byte_length`, `ascii_*`, `is_ascii_*`, `__float__`) — subclassing
    (rather than wrapping) means it still behaves exactly like a normal
    string everywhere else: comparisons, isinstance checks, concatenation,
    dict keys, etc. Operations not overridden here (slicing, `+`, `.upper()`)
    fall back to plain `str` and lose these extra methods on their result —
    a known gap, not attempted, since re-deriving MojoString from every
    str method would be a much bigger change for marginal benefit."""
    def byte_length(self):
        return len(str.encode(self, 'utf-8'))

    def is_ascii_digit(self):
        return str.isascii(self) and str.isdigit(self)

    def is_ascii_printable(self):
        return str.isascii(self) and all(32 <= ord(c) <= 126 for c in self)

    def ascii_rjust(self, width, fillchar=' '):
        return MojoString(str.rjust(self, width, fillchar))

    def ascii_ljust(self, width, fillchar=' '):
        return MojoString(str.ljust(self, width, fillchar))

    def ascii_center(self, width, fillchar=' '):
        return MojoString(str.center(self, width, fillchar))

    def __float__(self):
        return float(str(self))

    def codepoints(self):
        return list(self)

    def codepoint_slices(self):
        return list(self)


class _MojoBoolType:
    MIN = False
    MAX = True
    def __call__(self, x=False):
        return bool(x)


class _MojoIntType:
    MIN = -(2 ** 63)
    MAX = 2 ** 63 - 1
    def __call__(self, x=0):
        return int(x)


class _MojoUIntType:
    MIN = 0
    MAX = 2 ** 64 - 1
    def __call__(self, x=0):
        return int(x)


def _mojo_resolve_ambiguous_empty_braces(a, b):
    """See Interpreter._resolve_ambiguous_empty_braces — same `{}`-as-empty-
    dict-vs-empty-set ambiguity, needed here too since `assert_equal(x, {})`
    compares a real set against a literal dict `{}` the parser can't have
    known should have been a set."""
    if isinstance(a, set) and isinstance(b, dict) and not b:
        b = set()
    elif isinstance(b, set) and isinstance(a, dict) and not a:
        a = set()
    return a, b


def _mojo_assert_equal(a, b, msg=None):
    a, b = _mojo_resolve_ambiguous_empty_braces(a, b)
    if a != b:
        raise AssertionError(msg or f"AssertionError: {a!r} is not equal to {b!r}")


def _mojo_assert_not_equal(a, b, msg=None):
    if a == b:
        raise AssertionError(msg or f"AssertionError: {a!r} is equal to {b!r}")


def _mojo_assert_true(cond, msg=None):
    if not cond:
        raise AssertionError(msg or "AssertionError: condition was unexpectedly False")


def _mojo_assert_false(cond, msg=None):
    if cond:
        raise AssertionError(msg or "AssertionError: condition was unexpectedly True")


def _mojo_assert_almost_equal(a, b, msg=None, atol=1e-8, rtol=1e-5):
    if abs(a - b) > atol + rtol * abs(b):
        raise AssertionError(msg or f"AssertionError: {a!r} is not close to {b!r}")


class _MojoAssertRaises:
    """`with assert_raises(): ...` / `with assert_raises(contains="x"): ...`
    — asserts the block raises (optionally with a matching message)."""
    def __init__(self, contains=None, location=None):
        self.contains = contains

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError("AssertionError: Didn't raise")
        contains = self.contains
        if contains is not None and contains not in str(exc_val):
            return False
        return True


class _MojoTestSuiteRunner:
    """Backs `TestSuite.discover_tests[__functions_in_module()]().run()`, the
    boilerplate every stdlib test file ends with. Mirrors real Mojo's own
    `PASS/FAIL ... Summary ...` console output (see `stdlib/std/testing/suite.mojo`)
    closely enough to be a drop-in for the interpreter, though real Mojo also
    times each test — we don't bother, since nothing downstream reads timings."""
    def __init__(self, funcs, interpreter):
        self.funcs = funcs
        self.interpreter = interpreter
        self.skipped_names = set()

    @property
    def skip(self):
        runner = self
        return _MojoTestSuiteRunnerSkipAccessor(runner)

    def run(self, quiet=False, skip_all=False):
        filename = self.interpreter.filename or '<input>'
        if not quiet:
            print(f"Running {len(self.funcs)} tests for {filename} ")
        passed, failed, skipped = 0, 0, 0
        for name, func in self.funcs:
            if skip_all or name in self.skipped_names:
                if not quiet:
                    print(f"    SKIP [ 0.001 ] {name}")
                skipped += 1
                continue
            try:
                func(self.interpreter)
                if not quiet:
                    print(f"    PASS [ 0.001 ] {name}")
                passed += 1
            except Exception as e:
                if not quiet:
                    print(f"    FAIL [ 0.001 ] {name}: {e}")
                failed += 1
        if not quiet:
            print("--------")
            total = passed + failed + skipped
            print(f"Summary [ 0.001 ] {total} tests run: {passed} passed , {failed} failed , {skipped} skipped ")
        if failed:
            raise AssertionError(f"{failed} test(s) failed")


class _MojoTestSuiteRunnerSkipToken:
    def __init__(self, runner, func):
        self.runner = runner
        self.func = func

    def __call__(self):
        runner = self.runner
        func = self.func
        name = None
        for n, f in runner.funcs:
            if f is func:
                name = n
                break
        if name is None:
            fn_name = getattr(func, 'name', str(func))
            raise Exception(
                f"trying to skip a test that is not registered in the suite: {fn_name}"
            )
        runner.skipped_names.add(name)


class _MojoTestSuiteRunnerSkipAccessor:
    def __init__(self, runner):
        self.runner = runner

    def __getitem__(self, func):
        runner = self.runner
        return _MojoTestSuiteRunnerSkipToken(runner, func)


class _MojoTestSuiteDiscoverToken:
    def __init__(self, funcs, interpreter):
        self.funcs = funcs
        self.interpreter = interpreter

    def __call__(self, *args, **kwargs):
        # Real Mojo's TestSuite() call site sometimes passes `cli_args=...`
        # (for suites with their own argv handling) — irrelevant here.
        return _MojoTestSuiteRunner(self.funcs, self.interpreter)


class _MojoTestSuiteDiscover:
    def __init__(self, interpreter):
        self.interpreter = interpreter

    def __getitem__(self, funcs):
        test_funcs = [(n, f) for n, f in funcs if n.startswith('test_')]
        interpreter = self.interpreter
        return _MojoTestSuiteDiscoverToken(test_funcs, interpreter)


class _MojoTestSuite:
    """Stand-in for real Mojo's `testing.TestSuite`. `discover_tests` is
    subscripted (`discover_tests[funcs]`), not called directly, mirroring the
    real API's `discover_tests[__functions_in_module()]()` call shape."""
    def __init__(self, interpreter):
        self.interpreter = interpreter

    def __call__(self):
        return self

    @property
    def discover_tests(self):
        interpreter = self.interpreter
        return _MojoTestSuiteDiscover(interpreter)

    @property
    def test(self):
        interpreter = self.interpreter
        return _MojoTestSuiteFnAccessor(interpreter, run=True)

    @property
    def skip(self):
        interpreter = self.interpreter
        return _MojoTestSuiteFnAccessor(interpreter, run=False)


class _MojoTestSuiteFnCall:
    def __init__(self, func, interpreter, run):
        self.func = func
        self.interpreter = interpreter
        self.run = run

    def __call__(self):
        if not self.run:
            return None
        interpreter = self.interpreter
        func = self.func
        return interpreter.invoke(func)


class _MojoTestSuiteFnAccessor:
    """Backs `suite.test[fn]()` (run `fn` immediately) and `suite.skip[fn]()`
    (don't) — subscript with the test function, call with no arguments."""
    def __init__(self, interpreter, run):
        self.interpreter = interpreter
        self.run = run

    def __getitem__(self, func):
        interpreter = self.interpreter
        run = self.run
        return _MojoTestSuiteFnCall(func, interpreter, run)


def _mojo_unary_math(fn):
    """Wrap a scalar math function so it also applies elementwise to a
    `_MojoSIMD` operand — matching how real Mojo's `std.math` functions are
    overloaded for both `Scalar[dtype]` and `SIMD[dtype, width]`."""
    def wrapper(x, *args, **kwargs):
        if isinstance(x, _MojoSIMD):
            return _MojoSIMD(x.dtype, x.width, [fn(v, *args, **kwargs) for v in x.values])
        return fn(x, *args, **kwargs)
    return wrapper


def _mojo_iota(buf, *args):
    """`iota(buf)` / `iota(buf, offset)` / `iota(buf, length, offset)` — fill
    (part of) a buffer in place with sequential values."""
    if len(args) >= 2:
        length, offset = args[0], args[1]
    elif len(args) == 1:
        offset = args[0]
        length = len(buf)
    else:
        offset = 0
        length = len(buf)
    for i in range(length):
        buf[i] = offset + i


def _mojo_ceildiv(a, b):
    return -(-a // b)


def _build_math_shims():
    """`from std.math import ...` — the real `std/math/math.mojo` is
    parametric/generic-heavy like `std/testing`; hardcode plain Python `math`
    equivalents for the handful of names stdlib test files actually import,
    each also elementwise-applicable to a `_MojoSIMD` (see
    _mojo_unary_math)."""
    return {
        'exp': _mojo_unary_math(math.exp),
        'exp2': _mojo_unary_math(lambda x: 2.0 ** x),
        'log': _mojo_unary_math(math.log),
        'log2': _mojo_unary_math(math.log2),
        'log10': _mojo_unary_math(math.log10),
        'sqrt': _mojo_unary_math(math.sqrt),
        'rsqrt': _mojo_unary_math(lambda x: 1.0 / math.sqrt(x)),
        'recip': _mojo_unary_math(lambda x: 1.0 / x),
        'sin': _mojo_unary_math(math.sin),
        'cos': _mojo_unary_math(math.cos),
        'tan': _mojo_unary_math(math.tan),
        'sinh': _mojo_unary_math(math.sinh),
        'cosh': _mojo_unary_math(math.cosh),
        'tanh': _mojo_unary_math(math.tanh),
        'asin': _mojo_unary_math(math.asin),
        'acos': _mojo_unary_math(math.acos),
        'atan': _mojo_unary_math(math.atan),
        'atan2': math.atan2,
        'erf': _mojo_unary_math(math.erf),
        'floor': _mojo_unary_math(math.floor),
        'ceil': _mojo_unary_math(math.ceil),
        'trunc': _mojo_unary_math(math.trunc),
        'isnan': _mojo_unary_math(math.isnan),
        'isinf': _mojo_unary_math(math.isinf),
        'isfinite': _mojo_unary_math(math.isfinite),
        'gcd': math.gcd,
        'lcm': math.lcm,
        'ceildiv': _mojo_ceildiv,
        'modf': math.modf,
        'ldexp': math.ldexp,
        'frexp': math.frexp,
        'inf': math.inf,
        'iota': _mojo_iota,
    }


def _build_testing_shims(interpreter):
    """`from std.testing import ...` (or `testing`/`std.testing.testing`) can't
    realistically run through the real stdlib source — it's full of generic
    `fn foo[...]` parametrics our simple parser/interpreter doesn't support.
    Hardcode the handful of names stdlib test files actually use instead, the
    same way module_loader.py already hardcodes `_TESTING_EXPORTS` for the
    compiled path."""
    shims = {
        'assert_equal': _mojo_assert_equal,
        'assert_equal_pyobj': _mojo_assert_equal,
        'assert_not_equal': _mojo_assert_not_equal,
        'assert_true': _mojo_assert_true,
        'assert_false': _mojo_assert_false,
        'assert_almost_equal': _mojo_assert_almost_equal,
        'assert_raises': _MojoAssertRaises,
        'TestSuite': _MojoTestSuite(interpreter),
    }
    # `from std.testing import testing, TestSuite` imports the submodule
    # itself as a namespace (`testing.assert_equal(...)`) — self-reference,
    # one level deep (nothing in the corpus goes further than `testing.X`).
    shims['testing'] = types.SimpleNamespace(**shims)
    return shims


class _MojoSuper:
    """Proxy returned by `super` inside a struct method. `super.__init__(tag)`
    resolves to the parent struct's `__init__` method bound to `self`, so the
    call passes `self` as the first argument automatically.

    Uses `__getattribute__` (not `__getattr__`) because `__init__` is a special
    method name — Python finds it as a class attribute (the constructor) before
    consulting `__getattr__`, so `super.__init__` would return the bound
    constructor instead of the parent struct's `__init__`."""
    def __init__(self, base_class, self_instance, interpreter):
        object.__setattr__(self, '_base_class', base_class)
        object.__setattr__(self, '_self', self_instance)
        object.__setattr__(self, '_interpreter', interpreter)

    def __getattribute__(self, name):
        base_cls = object.__getattribute__(self, '_base_class')
        if name in base_cls.methods:
            return BoundMethod(
                base_cls.methods[name],
                object.__getattribute__(self, '_self'),
                object.__getattribute__(self, '_interpreter'))
        if name in ('_base_class', '_self', '_interpreter'):
            return object.__getattribute__(self, name)
        if name in base_cls.comptime_aliases:
            return base_cls.comptime_aliases[name]
        raise AttributeError(f"super object has no attribute '{name}'")


class _SysProxy:
    """Presents the executed program's own argv (`[filename] + program_args`)
    while forwarding everything else to the real `sys` module. Without this,
    interpreted code that reads `sys.argv` sees the *host* process's live
    argv instead of its own — harmless for most scripts, but fatal for
    self-referential ones: `mojo run mojo.py help` would otherwise have the
    nested interpretation of mojo.py re-read the unchanged host argv, take
    the same branch, and re-interpret itself forever."""
    def __init__(self, argv):
        self.argv = argv

    def __getattr__(self, name):
        return getattr(sys, name)


class Interpreter:
    """Executes Mojo AST nodes."""

    def __init__(self, filename: str = None, argv: list = None):
        # Increase recursion limit for meta-programming (interpreter on itself)
        import sys
        old_limit = sys.getrecursionlimit()
        if old_limit < 50000:
            sys.setrecursionlimit(50000)

        self.scope = Scope()
        self.filename = filename
        self.argv = argv if argv is not None else [filename or '<input>']
        self._mojo_module_cache = {}
        self._func_specs = {}
        self._raised_mojo_value = None
        self._setup_builtins()

    def _load_mojo_sibling_module(self, module_name):
        """Resolve `import`/`from import` of a sibling .mojo source file (as
        opposed to a real importable Python module) by parsing and running it
        in its own scope, then exposing its top-level bindings for attribute
        access — the interpreter has no separate module-object representation,
        so a lightweight namespace stands in for one."""
        cache = self._mojo_module_cache

        if module_name in ('testing', 'std.testing', 'std.testing.testing'):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(**_build_testing_shims(self))
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.math', 'std.math.math'):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(**_build_math_shims())
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.sys.defines',):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(
                is_defined=_MojoIsDefinedFn(),
                get_defined_string=_MojoGetDefinedFn(),
                get_defined_bool=_MojoGetDefinedFn(),
                get_defined_int=_MojoGetDefinedFn(),
                MOJO_VERSION="0.0.0-interpreter",
            )
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.sys', 'std.sys.arg', 'std.sys.info'):
            if module_name in cache:
                return cache[module_name]
            argv = self.argv
            namespace = types.SimpleNamespace(
                argv=lambda: argv,
                size_of=self.scope.get('size_of'),
                align_of=self.scope.get('align_of'),
                bit_width_of=self.scope.get('bit_width_of'),
                simd_width_of=self.scope.get('simd_width_of'),
                CompilationTarget=self.scope.get('CompilationTarget'),
                is_64bit=lambda: True,
                DType=self.scope.get('DType'),
                exit=sys.exit,
                get_defined_bool=_MojoGetDefinedFn(),
                get_defined_int=_MojoGetDefinedFn(),
                # This interpreter has no accelerator/GPU backend at all.
                is_gpu=lambda: False,
                is_apple_gpu=lambda: False,
                is_amd_gpu=lambda: False,
                is_nvidia_gpu=lambda: False,
                has_apple_gpu_accelerator=lambda: False,
                has_amd_gpu_accelerator=lambda: False,
                has_nvidia_gpu_accelerator=lambda: False,
                _accelerator_arch=lambda: "cpu",
                num_physical_cores=lambda: os.cpu_count() or 1,
                num_logical_cores=lambda: os.cpu_count() or 1,
            )
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.gpu', 'std.gpu.host', 'std.gpu.host.info', 'std.gpu.id'):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(
                DeviceContext=self.scope.get('DeviceContext'),
                DeviceBuffer=self.scope.get('DeviceBuffer'),
                HostBuffer=self.scope.get('DeviceBuffer'),
                GPUInfo=self.scope.get('GPUInfo'),
                AddressSpace=self.scope.get('AddressSpace'),
                thread_idx=self.scope.get('thread_idx'),
                block_idx=self.scope.get('block_idx'),
                block_dim=self.scope.get('block_dim'),
                grid_dim=self.scope.get('grid_dim'),
                global_idx=self.scope.get('global_idx'),
                lane_id=self.scope.get('lane_id'),
                get_gpu_target=self.scope.get('get_gpu_target'),
            )
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.os', 'std.os.os'):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(
                abort=self.scope.get('abort'),
            )
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.runtime.tracing',):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(
                Trace=_MojoTrace,
                TraceLevel=self.scope.get('TraceLevel'),
            )
            cache[module_name] = namespace
            return namespace

        if module_name == 'std' or module_name.startswith('std.'):
            # Real `std.*` submodules beyond the hardcoded shims above are
            # full of generics/MLIR our simple parser can't handle — walking
            # up from the importing file's directory (needed below for
            # test-only sibling packages like `test_utils`) would eventually
            # reach the real stdlib root and start attempting to parse them,
            # trading a graceful missing-import no-op for a hard crash deep
            # in real stdlib internals. Keep the old graceful-degradation
            # behavior for anything under `std.` that isn't shimmed.
            return None

        rel_path = module_name.replace('.', os.sep) + '.mojo'
        rel_pkg_path = os.path.join(module_name.replace('.', os.sep), '__init__.mojo')
        search_dirs = []
        if self.filename:
            # Walk upward too, not just the importing file's own directory —
            # e.g. stdlib/test/memory/test_alloc.mojo imports the sibling
            # package stdlib/test/test_utils/, which lives a level up from
            # test_alloc.mojo's own directory, not next to it.
            d = os.path.dirname(os.path.abspath(self.filename))
            for _ in range(6):
                search_dirs.append(d)
                parent = os.path.dirname(d)
                if parent == d:
                    break
                d = parent
        search_dirs.append(os.getcwd())
        found = None
        for d in search_dirs:
            flat_candidate = os.path.join(d, rel_path)
            pkg_candidate = os.path.join(d, rel_pkg_path)
            if os.path.isfile(flat_candidate):
                found = flat_candidate
                break
            if os.path.isfile(pkg_candidate):
                found = pkg_candidate
                break
        if found is None:
            return None

        # Cache (and cycle-guard) by resolved absolute path, not `module_name`
        # — a package's __init__.mojo commonly imports a same-named submodule
        # from itself (e.g. test_utils/__init__.mojo importing from
        # test_utils/test_utils.mojo, both reached via the string
        # "test_utils"), and those are different files that must not collide
        # on one cache key. Guard against circular sibling-module imports the
        # same way: without marking the slot before recursing, each nested
        # import would spin up a brand-new Interpreter with its own fresh,
        # unshared cache and recurse forever instead of hitting a cache entry.
        if found in cache:
            return cache[found]
        cache[found] = types.SimpleNamespace()

        with open(found) as f:
            src = f.read()
        from mojo_compiler import py_tokenize, Parser
        tokens = py_tokenize(src)
        mod_stmts = Parser(tokens).parse_module()
        mod_interp = Interpreter(filename=found, argv=self.argv)
        mod_interp._mojo_module_cache = cache  # shared, so cycles hit the guard above
        for stmt in mod_stmts:
            mod_interp.execute(stmt)
        namespace = types.SimpleNamespace(**mod_interp.scope.vars)
        cache[found] = namespace
        return namespace

    def _bind_dotted_import(self, module_name, mod):
        """`import std.sys` (no `as` alias) must bind the top-level name
        `std` and make `std.sys` resolve via chained attribute access — same
        as Python's own dotted-import binding rule. A flat bind of `std`
        straight to the `std.sys` shim namespace (the previous behavior)
        broke `std.sys.whatever`, since there was no intermediate `.sys`."""
        parts = module_name.split('.')
        top = parts[0]
        if len(parts) == 1:
            self.scope.define(top, mod)
            return
        try:
            root = self.scope.get(top)
        except NameError:
            root = None
        if not isinstance(root, types.SimpleNamespace):
            root = types.SimpleNamespace()
            self.scope.define(top, root)
        obj = root
        for p in parts[1:-1]:
            nxt = getattr(obj, p, None)
            if not isinstance(nxt, types.SimpleNamespace):
                nxt = types.SimpleNamespace()
                setattr(obj, p, nxt)
            obj = nxt
        setattr(obj, parts[-1], mod)

    def _is_instance(self, obj, class_name):
        """Check if obj is an instance of class_name from either ast_nodes or mojo_compiler."""
        if isinstance(obj, getattr(N, class_name, type(None))):
            return True
        if mojo_compiler and hasattr(mojo_compiler, class_name):
            if isinstance(obj, getattr(mojo_compiler, class_name)):
                return True
        return False

    def _setup_builtins(self):
        """Setup built-in functions and constants."""
        self.scope.define('None', None)
        self.scope.define('True', True)
        self.scope.define('False', False)
        self.scope.define('__name__', '__main__')
        self.scope.define('__file__', self.filename or '<input>')

        # Built-in functions
        self.scope.define('len', len)
        self.scope.define('print', print)
        self.scope.define('range', range)
        self.scope.define('str', str)
        self.scope.define('int', int)
        self.scope.define('float', float)
        self.scope.define('bool', bool)
        self.scope.define('list', list)
        self.scope.define('dict', dict)
        self.scope.define('set', set)
        self.scope.define('tuple', tuple)
        self.scope.define('open', open)
        self.scope.define('input', input)
        self.scope.define('isinstance', isinstance)
        self.scope.define('hasattr', hasattr)
        self.scope.define('getattr', getattr)
        self.scope.define('setattr', setattr)
        self.scope.define('type', type)
        self.scope.define('enumerate', enumerate)
        self.scope.define('zip', zip)
        self.scope.define('max', _mojo_max)
        self.scope.define('min', _mojo_min)
        self.scope.define('SIMD', _MojoSIMDType())
        self.scope.define('sum', sum)
        self.scope.define('sorted', sorted)
        self.scope.define('reversed', reversed)
        self.scope.define('map', _MojoParametricFn(map, self))
        self.scope.define('filter', _MojoParametricFn(filter, self))
        self.scope.define('repr', repr)
        self.scope.define('all', all)
        self.scope.define('any', any)
        self.scope.define('abs', abs)
        self.scope.define('round', round)
        self.scope.define('hash', hash)
        self.scope.define('id', id)
        self.scope.define('chr', chr)
        self.scope.define('ord', ord)
        self.scope.define('divmod', divmod)
        self.scope.define('next', next)
        self.scope.define('index', operator.index)
        self.scope.define('isnan', math.isnan)
        self.scope.define('isinf', math.isinf)
        self.scope.define('isfinite', math.isfinite)
        # Mojo's StaticString/StringSlice are borrowed-string-view types;
        # plain Python str already behaves like their value side.
        self.scope.define('StaticString', MojoString)
        self.scope.define('StringSlice', MojoString)
        self.scope.define('InlineArray', _MojoGenericCtor(list))
        def _mojo_deque_ctor(*args, **kwargs):
            # Mojo's Deque(capacity=N) is a pre-allocation size *hint*, not a
            # maxlen cap like collections.deque's own `maxlen=` — drop it.
            iterable = args[0] if args else ()
            return collections.deque(iterable)
        self.scope.define('Deque', _MojoGenericCtor(_mojo_deque_ctor))
        self.scope.define('BinaryHeap', _MojoGenericCtor(list))

        def _debug_assert(cond, *args):
            if not cond:
                raise AssertionError("debug_assert failed" + (": " + str(args[0]) if args else ""))
        self.scope.define('debug_assert', _debug_assert)
        self.scope.define('Exception', Exception)
        self.scope.define('BaseException', BaseException)
        self.scope.define('KeyboardInterrupt', KeyboardInterrupt)
        self.scope.define('EOFError', EOFError)
        self.scope.define('ValueError', ValueError)
        self.scope.define('TypeError', TypeError)
        self.scope.define('RuntimeError', RuntimeError)
        self.scope.define('StopIteration', StopIteration)
        self.scope.define('Error', MojoError)

        # Mojo scalar-type constructors — plain Python bool/int/float/str
        # already behave like Mojo's Bool/Int/Float64/String for arithmetic
        # and dunder methods; these wrappers only add the `.MIN`/`.MAX` class
        # attributes stdlib test files read directly off the type name.
        self.scope.define('Bool', _MojoBoolType())
        self.scope.define('Int', _MojoIntType())
        self.scope.define('UInt', _MojoUIntType())
        def _mojo_string_ctor(*args, **kwargs):
            if 'unsafe_from_utf8' in kwargs:
                # Avoid the `bytes()`/`bytearray()` builtins here — this
                # project's self-hosting compiler (gimple_codegen.py, which
                # must also compile myinterpreter.py itself) doesn't
                # recognize them as callable. This is an approximation (one
                # Python char per input byte, not a real UTF-8 multi-byte
                # decode) — good enough for ASCII-range byte lists, wrong for
                # genuine multi-byte UTF-8 sequences.
                data = kwargs['unsafe_from_utf8']
                return MojoString(''.join(chr(b) for b in data))
            if len(args) > 1:
                # Real Mojo's `String(a, b, c, ...)` concatenates the
                # stringified arguments (print-style), unlike Python's own
                # `str(object, encoding, errors)` 2-3 positional-arg
                # constructor, which would otherwise swallow the 2nd
                # argument as an `encoding` name.
                return MojoString(''.join(str(a) for a in args))
            return MojoString(*args)
        self.scope.define('String', _mojo_string_ctor)
        self.scope.define('List', _MojoGenericCtor(list))
        self.scope.define('Dict', _MojoGenericCtor(dict))
        self.scope.define('Set', _MojoGenericCtor(set))
        self.scope.define('Tuple', _MojoGenericCtor(tuple))

        int8, int16, int32, int64 = (
            _MojoScalarType('Int8', 1), _MojoScalarType('Int16', 2),
            _MojoScalarType('Int32', 4), _MojoScalarType('Int64', 8),
        )
        uint8, uint16, uint32, uint64 = (
            _MojoScalarType('UInt8', 1), _MojoScalarType('UInt16', 2),
            _MojoScalarType('UInt32', 4), _MojoScalarType('UInt64', 8),
        )
        float16 = _MojoScalarType('Float16', 2, is_float=True)
        float32 = _MojoScalarType('Float32', 4, is_float=True)
        float64 = _MojoScalarType('Float64', 8, is_float=True)
        bfloat16 = _MojoScalarType('BFloat16', 2, is_float=True)
        self.scope.define('Int8', int8)
        self.scope.define('Int16', int16)
        self.scope.define('Int32', int32)
        self.scope.define('Int64', int64)
        self.scope.define('UInt8', uint8)
        self.scope.define('UInt16', uint16)
        self.scope.define('UInt32', uint32)
        self.scope.define('UInt64', uint64)
        self.scope.define('Float16', float16)
        self.scope.define('Float32', float32)
        self.scope.define('Float64', float64)
        self.scope.define('BFloat16', bfloat16)
        self.scope.define('DType', types.SimpleNamespace(
            int8=int8, int16=int16, int32=int32, int64=int64, index=int64, int=int64,
            uint8=uint8, uint16=uint16, uint32=uint32, uint64=uint64,
            float16=float16, float32=float32, float64=float64, bfloat16=bfloat16,
            bool=_MojoScalarType('Bool', 1),
        ))
        self.scope.define('size_of', _MojoTypeInfoFn(_mojo_size_of))
        self.scope.define('align_of', _MojoTypeInfoFn(_mojo_size_of))
        self.scope.define('bit_width_of', _MojoTypeInfoFn(_mojo_bit_width_of))
        self.scope.define('simd_width_of', _MojoTypeInfoFn(_mojo_simd_width_of))
        self.scope.define('CompilationTarget', _MojoCompilationTarget())
        unsafe_pointer_type = _MojoUnsafePointerType()
        self.scope.define('UnsafePointer', unsafe_pointer_type)
        self.scope.define('MutUnsafePointer', unsafe_pointer_type)
        self.scope.define('ImmutUnsafePointer', unsafe_pointer_type)
        self.scope.define('DeviceBuffer', unsafe_pointer_type)

        # GPU/DeviceContext basics — no real GPU backend, kernels launched
        # via enqueue_function just run serially on the CPU (see
        # _MojoEnqueueFunctionCall). Good enough for exercising kernel logic
        # and the launch/buffer/thread-index syntax and semantics; not a
        # step towards real device dispatch.
        def _device_context_ctor(device_id=0, api=None):
            return _MojoDeviceContext(device_id, api, self)
        self.scope.define('DeviceContext', _device_context_ctor)
        self.scope.define('thread_idx', _MojoDim3())
        self.scope.define('block_idx', _MojoDim3())
        self.scope.define('block_dim', _MojoDim3(1, 1, 1))
        self.scope.define('grid_dim', _MojoDim3(1, 1, 1))
        self.scope.define('global_idx', _MojoDim3())
        self.scope.define('GPUInfo', _MojoGPUInfoType())
        self.scope.define('AddressSpace', _MojoAddressSpaceNS())
        def _mojo_get_gpu_target(*args, **kwargs):
            return "cpu"
        self.scope.define('get_gpu_target', _mojo_get_gpu_target)

        def _mojo_lane_id():
            return 0
        self.scope.define('lane_id', _mojo_lane_id)
        self.scope.define('MutUntrackedOrigin', None)

        def _origin_of(x, *args, **kwargs):
            return x
        self.scope.define('origin_of', _origin_of)

        def _mojo_abort(*args):
            msg = str(args[0]) if args else "abort() called"
            raise RuntimeError(msg)
        self.scope.define('abort', _mojo_abort)
        self.scope.define('TraceLevel', types.SimpleNamespace(
            DISABLED=0, DEFAULT=1, VERBOSE=2, RUNTIME=3,
        ))

        # `__functions_in_module()` backs the `TestSuite.discover_tests[...]`
        # boilerplate at the end of most stdlib test files — see
        # _build_testing_shims. Captures this interpreter's own top-level
        # scope (module scope), since that's what real Mojo's builtin reflects.
        module_scope = self.scope
        def _functions_in_module():
            return [(n, v) for n, v in module_scope.vars.items() if isinstance(v, MojoFunction)]
        self.scope.define('__functions_in_module', _functions_in_module)

        # Standard library modules
        import os
        import sys
        import subprocess
        import shutil
        import sysconfig
        import platform
        import tempfile
        import traceback
        self.scope.define('os', os)
        self.scope.define('sys', _SysProxy(self.argv))
        self.scope.define('subprocess', subprocess)
        self.scope.define('shutil', shutil)
        self.scope.define('sysconfig', sysconfig)
        self.scope.define('platform', platform)
        self.scope.define('tempfile', tempfile)
        self.scope.define('traceback', traceback)

        # Interpreter itself for bootstrapping
        self.scope.define('Interpreter', Interpreter)

        # Parser and compiler functions
        try:
            from mojo_compiler import py_tokenize, Parser as MojoParser
            self.scope.define('py_tokenize', py_tokenize)
            self.scope.define('Parser', MojoParser)
        except ImportError:
            pass

        # GIMPLE codegen
        try:
            from gimple_codegen import compile_to_gimple
            self.scope.define('compile_to_gimple', compile_to_gimple)
        except ImportError:
            pass

    def _loc(self, node: object = None) -> str:
        """Format a gcc-style `file:line:col: ` prefix for a runtime diagnostic.
        Omits the filename segment when the interpreter wasn't given one
        (e.g. the REPL), matching mojo_compiler.Parser's `_loc`."""
        line = getattr(node, 'line', 0) if node is not None else 0
        col = getattr(node, 'col', 0) if node is not None else 0
        if self.filename:
            return f"{self.filename}:{line}:{col}: "
        return f"{line}:{col}: "

    def execute(self, node: object) -> object:
        """Execute an AST node."""
        if node is None:
            return None

        method_name = f'execute_{type(node).__name__}'
        method = getattr(self, method_name, None)

        if method is None:
            raise NotImplementedError(f"{self._loc(node)}No handler for {type(node).__name__}")

        return method(node)

    def execute_Module(self, node: N.Module):
        """Execute module (top-level statements)."""
        result = None
        for stmt in node.body:
            result = self.execute(stmt)
        return result

    @staticmethod
    def _extract_param_names(node):
        """Extract parameter names from a FunctionDef's various param formats.
        Mojo's `*name`/`**name` prefixes (keyword-only marker / kwargs
        catch-all — see mojo_compiler.py's param parsing) are stripped since
        MojoFunction binds everything positional-or-keyword by plain name."""
        params = []
        if hasattr(node, 'params') and node.params:
            for p in node.params:
                if isinstance(p, str):
                    params.append(p)
                elif isinstance(p, tuple):
                    # Handle (name, type_annotation) tuples
                    params.append(p[0])
                elif hasattr(p, 'name'):
                    params.append(p.name)
                elif isinstance(p, dict) and 'name' in p:
                    params.append(p['name'])
                else:
                    # Fallback: try to extract name from string representation
                    p_str = str(p)
                    if '(' in p_str:
                        # Parse string like "('n', None)" to get 'n'
                        try:
                            import ast
                            parsed = ast.literal_eval(p_str)
                            if isinstance(parsed, tuple):
                                params.append(parsed[0])
                            else:
                                params.append(parsed)
                        except:
                            params.append(p_str)
                    else:
                        params.append(p_str)
        return [p.lstrip('*') for p in params]

    @staticmethod
    def _classify_params(node):
        """Classify a FunctionDef's parameters for overload-signature
        matching: (required positional names, optional/defaulted positional
        names, keyword-only names, has-**kwargs-catch-all).

        Keyword-only names come from two places in mojo_compiler.py's parsed
        params: a `*name` prefix (the `*args`-style variadic form), or plain
        (unprefixed) names listed in `node.kwonly` — the far more common
        `def f(x, *, y):` bare-`*,`-separator form leaves `y` looking
        identical to a normal positional param in `node.params`, since the
        parser only records "a bare `*` was seen" via that separate list,
        not as a per-param marker."""
        required, optional, kwonly = [], [], []
        has_var_kwargs = False
        has_default = getattr(node, 'param_has_default', None) or {}
        explicit_kwonly = set(getattr(node, 'kwonly', None) or [])
        for p in (getattr(node, 'params', None) or []):
            if isinstance(p, tuple):
                raw_name = p[0]
            elif hasattr(p, 'name'):
                raw_name = p.name
            elif isinstance(p, dict) and 'name' in p:
                raw_name = p['name']
            else:
                raw_name = str(p)
            if raw_name.startswith('**'):
                has_var_kwargs = True
                continue
            is_kwonly = raw_name.startswith('*')
            name = raw_name.lstrip('*')
            if is_kwonly or name in explicit_kwonly:
                kwonly.append(name)
            elif has_default.get(name):
                optional.append(name)
            else:
                required.append(name)
        return required, optional, kwonly, has_var_kwargs

    def _register_function(self, container, name, func, spec):
        """Bind `func` under `name` in `container` (a plain dict: Scope.vars
        or a struct's methods dict), merging into a MojoOverloadSet if `name`
        already names a function in this same container — repeat `def name`
        in Mojo is an overload set, not a redefinition."""
        self._func_specs[id(func)] = spec
        existing = container.get(name)
        if isinstance(existing, MojoOverloadSet):
            existing.add(func, *spec)
            return existing
        if isinstance(existing, MojoFunction):
            prev_spec = self._func_specs.get(id(existing), ([], [], [], False))
            overload_set = MojoOverloadSet(name)
            overload_set.add(existing, *prev_spec)
            overload_set.add(func, *spec)
            container[name] = overload_set
            return overload_set
        container[name] = func
        return func

    def execute_FunctionDef(self, node: N.FunctionDef):
        """Execute function definition."""
        params = self._extract_param_names(node)
        comptime_params = getattr(node, 'comptime_params', None)
        func = MojoFunction(node.name, params, node.body, self.scope, comptime_params)
        spec = self._classify_params(node)
        return self._register_function(self.scope.vars, node.name, func, spec)

    def execute_StructDef(self, node: N.StructDef):
        """Execute struct/class definition.

        `struct Child(Base1, Base2):` — Python-style class inheritance:
        fields and methods from each named base are merged in first, in
        declaration order (later bases override earlier ones, matching
        Python's own left-to-right MRO for non-diamond hierarchies), then
        Child's own fields/methods are layered on top, overriding same-named
        base methods exactly like a Python subclass overriding a method."""
        methods = {}
        base_names = getattr(node, 'bases', None) or []
        base_classes = []
        merged_fields = []
        comptime_aliases = {}
        static_methods = set()
        from_base = set()
        for base_name in base_names:
            try:
                base_cls = self.scope.get(base_name)
            except NameError:
                base_cls = None
            if isinstance(base_cls, MojoClass):
                base_classes.append(base_cls)
                merged_fields.extend(base_cls.fields)
                methods.update(base_cls.methods)
                comptime_aliases.update(base_cls.comptime_aliases)
                static_methods.update(base_cls.static_methods)
                from_base.update(base_cls.methods.keys())
        for m in getattr(node, 'methods', None) or []:
            params = self._extract_param_names(m)
            comptime_params = getattr(m, 'comptime_params', None)
            method_func = MojoFunction(m.name, params, m.body, self.scope, comptime_params)
            spec = self._classify_params(m)
            if m.name in from_base:
                from_base.discard(m.name)
                methods[m.name] = method_func
            else:
                self._register_function(methods, m.name, method_func, spec)
            if 'staticmethod' in (getattr(m, 'decorators', None) or []):
                static_methods.add(m.name)
        # `comptime NAME: Type = value` struct members — evaluated once,
        # here, at struct-definition time, not lazily per access.
        for alias_name, alias_expr in (getattr(node, 'comptime_aliases', None) or {}).items():
            comptime_aliases[alias_name] = self.eval_expr(alias_expr)
        fields = merged_fields + (getattr(node, 'fields', None) or [])
        cls = MojoClass(node.name, fields, methods, self, bases=base_classes,
                         comptime_aliases=comptime_aliases, static_methods=static_methods)
        self.scope.define(node.name, cls)
        return cls

    def execute_ImportStmt(self, node: N.ImportStmt):
        """Execute `import mod` / `import mod as alias`.

        The interpreter runs the AST as Python, so we resolve through Python's
        real import machinery and bind the resulting module object into scope.
        Failing loudly (rather than the old silent skip) is the point: a skipped
        import surfaces later as a baffling "name '...' is not defined".
        """
        # `import sys` is special: the program must see its own argv (see
        # _SysProxy), not the real process argv reinstated by a fresh
        # importlib.import_module('sys'). Re-binding the real module here is
        # what turned `mojo run mojo.py help` into unbounded recursion — the
        # nested interpretation of mojo.py would re-read the host's live
        # argv instead of the isolated one and take the same branch forever.
        if node.module == 'sys' or node.module.split('.')[0] == 'sys':
            self.scope.define(node.alias or 'sys', self.scope.get('sys'))
            return None
        # Prefer a sibling .mojo file/package over a same-named *real*
        # Python module — otherwise a coincidentally-named .py file
        # anywhere on sys.path (including this very project's own helper
        # scripts, e.g. mojo-reference/lexer.py shadowing some other Mojo
        # project's own lexer.mojo) silently wins over the file the Mojo
        # source obviously meant, with a confusing "no attribute X" error
        # instead of a clean import. A .mojo file sitting right next to the
        # importing source is a much stronger signal of intent than a
        # name collision with an installed/local Python module.
        mod = self._load_mojo_sibling_module(node.module)
        if mod is not None:
            if node.alias:
                self.scope.define(node.alias, mod)
            else:
                self._bind_dotted_import(node.module, mod)
            return None
        try:
            mod = importlib.import_module(node.module)
        except ModuleNotFoundError:
            return None
        if node.alias:
            self.scope.define(node.alias, mod)
        else:
            # `import a.b` binds the top-level package name `a`.
            top = node.module.split('.')[0]
            self.scope.define(top, importlib.import_module(top))
        return None

    def execute_FromImportStmt(self, node: N.FromImportStmt):
        """Execute `from mod import a, b as c` / `from mod import *`."""
        # See execute_ImportStmt: keep the isolated-argv sys proxy, don't
        # pull attributes off the real sys module.
        if node.module == 'sys':
            mod = self.scope.get('sys')
        elif node.module.startswith('.'):
            # Relative import (`from .compare_helpers import X`, inside a
            # package's __init__.mojo) — real Python's importlib requires
            # package context we don't have, and would never resolve a
            # sibling .mojo file anyway. Resolve directly as a sibling module.
            mod = self._load_mojo_sibling_module(node.module.lstrip('.'))
            if mod is None:
                return None
        else:
            # Prefer a sibling .mojo file/package over a same-named *real*
            # Python module — see execute_ImportStmt for why (a coincidental
            # same-named .py file on sys.path, e.g. this project's own
            # lexer.py, would otherwise silently shadow the .mojo file the
            # source obviously meant).
            mod = self._load_mojo_sibling_module(node.module)
            if mod is None:
                try:
                    mod = importlib.import_module(node.module)
                except ModuleNotFoundError:
                    return None
        if node.wildcard:
            names = getattr(mod, '__all__', None)
            if names is None:
                names = [n for n in dir(mod) if not n.startswith('_')]
            for name in names:
                self.scope.define(name, getattr(mod, name))
            return None
        for name, alias in node.names:
            try:
                value = getattr(mod, name)
            except AttributeError:
                raise NameError(f"{self._loc(node)}cannot import name '{name}' from '{node.module}'")
            self.scope.define(alias or name, value)
        return None

    def execute_AssignStmt(self, node: N.AssignStmt):
        """Execute assignment statement."""
        value = self.eval_expr(node.value)
        # Handle both 'targets' (list) and 'target' (single) for compatibility
        if hasattr(node, 'targets'):
            targets = node.targets
        else:
            targets = [node.target]
        for target in targets:
            self._assign_target(target, value)
        return value

    _INT_TYPE_NAMES = {
        'Int', 'Int8', 'Int16', 'Int32', 'Int64', 'Int128', 'Int256',
        'UInt', 'UInt8', 'UInt16', 'UInt32', 'UInt64', 'UInt128', 'UInt256',
    }
    _FLOAT_TYPE_NAMES = {'Float16', 'Float32', 'Float64', 'BFloat16'}

    def _coerce_to_declared_type(self, value, type_ann):
        """Coerce a var's initializer to its declared scalar type, mirroring
        real Mojo's implicit-constructor conversion (e.g. `var x: Int = 84 / 2`
        truncates the Float64 division result to an Int, it doesn't stay a float)."""
        if not isinstance(type_ann, str):
            return value
        if type_ann in self._INT_TYPE_NAMES and isinstance(value, float):
            return int(value)
        if type_ann in self._FLOAT_TYPE_NAMES and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        if type_ann == 'Bool' and isinstance(value, int) and not isinstance(value, bool):
            return bool(value)
        return value

    def execute_VarDecl(self, node: N.VarDecl):
        """Execute variable declaration."""
        value = self.eval_expr(node.value)
        # `var a, b = expr` (tuple unpacking) is parsed as a single VarDecl
        # whose `name` is a comma-joined string ("a,b") — see
        # mojo_compiler.py's `_parse_var_decl`. A plain single name never
        # contains a comma, so this only fires for the unpacking case.
        if ',' in node.name:
            names = node.name.split(',')
            values = list(value) if hasattr(value, '__iter__') and not isinstance(value, (str, bytes)) else [value]
            for name, v in zip(names, values):
                self.scope.define(name, v)
            return value
        value = self._coerce_to_declared_type(value, getattr(node, 'type_ann', None))
        self.scope.define(node.name, value)
        return value

    def execute_AugAssignStmt(self, node):
        """Execute augmented assignment (+=, -=, etc.)."""
        # Get current value
        current = self.eval_expr(node.target)
        # Get RHS value
        rhs = self.eval_expr(node.value)
        # Apply operator
        op = node.op[:-1]  # Remove '=' from the operator (e.g., '+=' -> '+')
        if op == '+':
            new_value = current + rhs
        elif op == '-':
            new_value = current - rhs
        elif op == '*':
            new_value = current * rhs
        elif op == '/':
            new_value = current / rhs
        elif op == '%':
            new_value = current % rhs
        elif op == '//':
            new_value = current // rhs
        elif op == '**':
            new_value = current ** rhs
        elif op == '&':
            new_value = current & rhs
        elif op == '|':
            new_value = current | rhs
        elif op == '^':
            new_value = current ^ rhs
        elif op == '<<':
            new_value = current << rhs
        elif op == '>>':
            new_value = current >> rhs
        else:
            raise NotImplementedError(f"{self._loc(node)}Augmented operator {node.op} not implemented")
        # Assign new value
        self._assign_target(node.target, new_value)
        return new_value

    def _assign_target(self, target, value):
        """Assign a value to a target (variable, member, subscript, tuple, etc.)."""
        if self._is_instance(target, 'IdentExpr'):
            # Check if this is a global variable
            global_vars = getattr(self, 'global_vars', set())
            if target.name in global_vars:
                # Find and update the global scope
                scope = self.scope
                while scope.parent:
                    scope = scope.parent
                scope.define(target.name, value)
            else:
                self.scope.define(target.name, value)
        elif self._is_instance(target, 'MemberExpr'):
            obj = self.eval_expr(target.obj)
            setattr(obj, target.member, value)
        elif self._is_instance(target, 'SubscriptExpr'):
            obj = self.eval_expr(target.obj)
            idx = self.eval_expr(target.index)
            obj[idx] = value
        elif self._is_instance(target, 'TupleExpr') or self._is_instance(target, 'TupleLiteral'):
            # Tuple unpacking: a, b, c = expr or (a, b, c) = expr
            values = list(value) if hasattr(value, '__iter__') and not isinstance(value, (str, bytes)) else [value]
            elements = target.elements
            if len(values) != len(elements):
                raise ValueError(f"{self._loc(target)}Cannot unpack {len(values)} values into {len(elements)} targets")
            for t, v in zip(elements, values):
                self._assign_target(t, v)
        else:
            raise NotImplementedError(f"{self._loc(target)}Cannot assign to {type(target).__name__}")

    def execute_ReturnStmt(self, node: N.ReturnStmt):
        """Execute return statement."""
        value = self.eval_expr(node.value) if hasattr(node, 'value') and node.value else None
        raise ReturnValue(value)

    def execute_IfStmt(self, node: N.IfStmt):
        """Execute if statement."""
        cond = self.eval_expr(node.condition)
        if cond:
            for stmt in node.then_body:
                self.execute(stmt)
        else:
            if node.elifs:
                for elif_cond, elif_body in node.elifs:
                    if self.eval_expr(elif_cond):
                        for stmt in elif_body:
                            self.execute(stmt)
                        return None
            if node.else_body:
                for stmt in node.else_body:
                    self.execute(stmt)
        return None

    def execute_MatchStmt(self, node):
        """`match subject: case p1: ... case p2, p3: ... case _: ...`

        Switch-style equality dispatch, not full PEP 634 structural pattern
        matching — see mojo_compiler.py's MatchStmt docstring for why (bare
        names in real Python match patterns are irrefutable captures, but
        every real use here wants a value comparison against an
        already-defined constant)."""
        subject = self.eval_expr(node.subject)
        # `case` is deliberately never used as a Python variable name here —
        # it's a reserved word in C, and this file self-hosts (gets compiled
        # to C by gimple_codegen.py), which doesn't rename local variables
        # that happen to collide with a C keyword.
        for match_case in node.cases:
            matched = False
            for pattern in match_case.patterns:
                if self._is_instance(pattern, 'IdentExpr') and pattern.name == '_':
                    matched = True
                    break
                if self.eval_expr(pattern) == subject:
                    matched = True
                    break
            if not matched:
                continue
            if match_case.guard is not None and not self.eval_expr(match_case.guard):
                continue
            for stmt in match_case.body:
                self.execute(stmt)
            return None
        return None

    def execute_ComptimeIfStmt(self, node):
        """`comptime if cond: ... elif ...: ... else: ...` — the interpreter
        doesn't do compile-time branch elimination, so this just evaluates
        like a regular runtime if/elif/else."""
        cond = self.eval_expr(node.condition)
        if cond:
            for stmt in node.then_body:
                self.execute(stmt)
        else:
            if node.elifs:
                for elif_cond, elif_body in node.elifs:
                    if self.eval_expr(elif_cond):
                        for stmt in elif_body:
                            self.execute(stmt)
                        return None
            if node.else_body:
                for stmt in node.else_body:
                    self.execute(stmt)
        return None

    def execute_ComptimeVarStmt(self, node):
        """`comptime NAME = expr` — a compile-time-constant variable. The
        interpreter has no separate comptime evaluation phase, so this is
        just a regular variable assignment."""
        value = self.eval_expr(node.value)
        self.scope.define(node.target, value)
        return value

    def execute_WhileStmt(self, node: N.WhileStmt):
        """Execute while statement."""
        while self.eval_expr(node.condition):
            try:
                for stmt in node.body:
                    self.execute(stmt)
            except BreakException:
                break
            except ContinueException:
                continue
        return None

    def execute_ForStmt(self, node: N.ForStmt):
        """Execute for statement."""
        iterable = self.eval_expr(node.iterable)
        # Handle both 'targets' (list) and 'target' (single) for compatibility
        if hasattr(node, 'targets'):
            targets = node.targets
        else:
            targets = [node.target]

        for value in iterable:
            # Bind loop variable(s)
            if len(targets) == 1:
                # Extract name from target if it's an object
                target_name = targets[0]
                if hasattr(target_name, 'name'):
                    target_name = target_name.name
                elif not isinstance(target_name, str):
                    target_name = str(target_name)
                self.scope.define(target_name, value)
            else:
                # Unpacking
                for i, target in enumerate(targets):
                    target_name = target
                    if hasattr(target_name, 'name'):
                        target_name = target_name.name
                    elif not isinstance(target_name, str):
                        target_name = str(target_name)
                    self.scope.define(target_name, value[i] if isinstance(value, (list, tuple)) else value)

            try:
                for stmt in node.body:
                    self.execute(stmt)
            except BreakException:
                break
            except ContinueException:
                continue
        return None

    def execute_ExprStmt(self, node: N.ExprStmt):
        """Execute expression statement."""
        return self.eval_expr(node.value)

    def execute_PassStmt(self, node: N.PassStmt):
        """Execute pass statement."""
        return None

    def execute_AssertStmt(self, node):
        """Execute `assert cond` / `assert cond, msg`."""
        cond = self.eval_expr(node.value)
        if not cond:
            msg = self.eval_expr(node.msg) if getattr(node, 'msg', None) is not None else None
            raise AssertionError(f"{self._loc(node)}{msg if msg is not None else 'assert failed'}")
        return None

    def execute_GlobalStmt(self, node):
        """Execute global statement."""
        if hasattr(node, 'names'):
            if not hasattr(self, 'global_vars'):
                self.global_vars = set()
            self.global_vars.update(node.names)
        return None

    def execute_BreakStmt(self, node: N.BreakStmt):
        """Execute break statement."""
        raise BreakException()

    def execute_ContinueStmt(self, node: N.ContinueStmt):
        """Execute continue statement."""
        raise ContinueException()

    def execute_WithStmt(self, node: N.WithStmt):
        """Execute with statement."""
        # With statement: with expr as var: body
        if not node.items:
            # No items, just execute body
            for stmt in node.body:
                self.execute(stmt)
            return None

        item = node.items[0]  # Support single with item for now
        ctx = self.eval_expr(item.expr)
        entered = ctx.__enter__() if hasattr(ctx, '__enter__') else ctx
        if item.alias:
            self.scope.define(item.alias, entered)
        try:
            for stmt in node.body:
                self.execute(stmt)
        except Exception as e:
            # Standard context-manager protocol: __exit__ gets the exception
            # and may suppress it by returning truthy (e.g. assert_raises's
            # `with assert_raises(): raise ...` — the raise is expected and
            # must not propagate as a test failure).
            if hasattr(ctx, '__exit__') and ctx.__exit__(type(e), e, None):
                return None
            raise
        if hasattr(ctx, '__exit__'):
            ctx.__exit__(None, None, None)
        return None

    def execute_RaiseStmt(self, node):
        """`raise value` / `raise` (bare re-raise, only valid inside an
        already-active except handler — Python's own semantics apply).

        `value` may be a bare string, an `Error(...)` (a real MojoError,
        which *is* a real Python Exception subclass), or an instance of a
        user-defined exception struct (a MojoInstance — not a real Python
        exception type at all). Anything that isn't already a real
        BaseException is stashed on self._raised_mojo_value and signaled via
        the fieldless MojoRaisedException marker, so it still flows through
        Python's real exception propagation; execute_TryStmt's
        _matches_exc_type reads _raised_mojo_value back for matching (see
        MojoRaisedException's docstring for why not a field on the
        exception object itself)."""
        if node.value is None:
            raise
        value = self.eval_expr(node.value)
        if isinstance(value, BaseException):
            raise value
        self._raised_mojo_value = value
        raise MojoRaisedException()

    def _matches_exc_type(self, e, exc_class):
        """Does exception `e` (as caught by execute_TryStmt's real Python
        `except Exception as e:`) match an `except exc_class:` clause?

        Python's own isinstance() already understands real exception-type
        hierarchies (ValueError, our BreakException/ReturnValue/MojoError,
        etc.) — used directly for those. It does *not* understand a
        MojoClass (a user-defined `struct MyError(BaseError):` exception
        type, itself just a MojoInstance, not a real Python type at all),
        so that case walks the *raised value's own* class's `.bases` chain
        instead, mirroring Python's subclass-catches-via-base semantics for
        this interpreter's own class model rather than Python's. `except
        Exception`/`except BaseException` must catch a
        MojoRaisedException-wrapped custom struct too, even though the
        wrapped value isn't a Python Exception instance itself — same
        universal-catch special case as gimple_codegen.py's compiled-path
        dispatch."""
        raised_value = self._raised_mojo_value if isinstance(e, MojoRaisedException) else e
        if isinstance(exc_class, MojoClass):
            if isinstance(raised_value, MojoInstance):
                stack = [raised_value._mojo_class]
                seen = set()
                while stack:
                    c = stack.pop()
                    if id(c) in seen:
                        continue
                    seen.add(id(c))
                    if c is exc_class:
                        return True
                    stack.extend(c.bases)
            return False
        if exc_class in (Exception, BaseException):
            return True
        try:
            return isinstance(raised_value, exc_class)
        except TypeError:
            return False

    def execute_TryStmt(self, node: N.TryStmt):
        """Execute try statement."""
        try:
            for stmt in node.body:
                self.execute(stmt)
        except Exception as e:
            if node.handlers:
                handled = False
                bound_value = self._raised_mojo_value if isinstance(e, MojoRaisedException) else e
                for handler in node.handlers:
                    exc_type = handler.exc_type
                    handler_body = handler.body
                    # exc_type can be None (catch all), a string (exc name), or an expression
                    should_handle = False
                    if exc_type is None:
                        should_handle = True
                    elif isinstance(exc_type, str):
                        # If exc_type is a string, look it up in the scope
                        try:
                            exc_class = self.scope.get(exc_type)
                            should_handle = self._matches_exc_type(e, exc_class)
                        except NameError:
                            should_handle = False
                    else:
                        # Otherwise evaluate it as an expression
                        try:
                            exc_class = self.eval_expr(exc_type)
                            should_handle = self._matches_exc_type(e, exc_class)
                        except NameError:
                            should_handle = False

                    if should_handle:
                        # Bind exception to variable if handler has a name
                        if handler.name:
                            old_val = None
                            had_old = handler.name in self.scope.vars
                            if had_old:
                                old_val = self.scope.vars[handler.name]
                            self.scope.define(handler.name, bound_value)

                        for stmt in handler_body:
                            self.execute(stmt)

                        # Restore old value if it existed
                        if handler.name:
                            if had_old:
                                self.scope.vars[handler.name] = old_val
                            else:
                                del self.scope.vars[handler.name]

                        handled = True
                        break
                if not handled:
                    raise
            else:
                raise
        finally:
            if node.finally_body:
                for stmt in node.finally_body:
                    self.execute(stmt)
        return None

    # Expression evaluation

    def eval_expr(self, expr):
        """Evaluate an expression."""
        if expr is None:
            return None

        method_name = f'eval_{type(expr).__name__}'
        method = getattr(self, method_name, None)

        if method is None:
            raise NotImplementedError(f"{self._loc(expr)}No handler for {type(expr).__name__}")

        return method(expr)

    def eval_IdentExpr(self, expr: N.IdentExpr):
        """Evaluate identifier."""
        if expr.name == 'super':
            return self._eval_super(expr)
        try:
            return self.scope.get(expr.name)
        except NameError:
            raise NameError(f"{self._loc(expr)}name '{expr.name}' is not defined")

    def _eval_super(self, expr: N.IdentExpr):
        """Split out of eval_IdentExpr: returning a `_MojoSuper` instance
        from the same function as the plain `self.scope.get(expr.name)`
        path corrupted the self-hosted compiler's type inference for
        `Scope.get` elsewhere (two incompatible return types out of one
        function). Keeping the `_MojoSuper`-returning branch in its own
        function avoids that."""
        self_val = self.scope.get('self')
        if isinstance(self_val, MojoInstance):
            cls = self_val._mojo_class
            if cls.bases:
                return _MojoSuper(cls.bases[0], self_val, self)
        raise NameError(f"{self._loc(expr)}'super' used outside of struct method with a base class")

    def eval_IntLiteral(self, expr: N.IntLiteral):
        """Evaluate integer literal."""
        return expr.value

    def eval_FloatLiteral(self, expr: N.FloatLiteral):
        """Evaluate float literal."""
        return expr.value

    def eval_StringLiteral(self, expr: N.StringLiteral):
        """Evaluate string literal."""
        value = expr.value
        is_fstring = value.startswith('f"') or value.startswith("f'")
        # Mojo's `t"..."` template-string literal shares f-string's `{expr}`/
        # `{{`-escape interpolation syntax (see mojo_compiler.py's
        # _strip_string_prefix_and_quotes) — real Mojo turns it into a
        # Template-like object, but every use we've seen immediately feeds it
        # to `String(...)` anyway, so evaluating it as a plain f-string (via
        # Python's own, unrelated PEP 750 t-strings would produce a
        # string.templatelib.Template object instead of a str) gets the same
        # final value without needing to model an intermediate Template type.
        is_tstring = value.startswith('t"') or value.startswith("t'")
        if is_fstring or is_tstring:
            body = value[1:]  # strip the leading f/t prefix
            # Detect a triple-quoted body without ever writing a literal
            # triple-quote substring in this file's own source: mojo_compiler's
            # replace_multiline_strings does a whole-source, nesting-unaware
            # sweep for opening/closing """ or ''' runs, so a literal '"""'
            # constant here would itself get mistaken for the start of a new
            # multi-line string and swallow everything up to the next triple-
            # quote sequence found anywhere later in this file.
            triple_quote_len = 3
            is_triple = (len(body) >= triple_quote_len
                         and body[0] == body[1] == body[2]
                         and (body[0] == chr(34) or body[0] == chr(39)))
            if is_triple:
                body = body[3:-3]
            else:
                body = body[1:-1]
            try:
                result = self._format_fstring_body(body)
            except Exception:
                # A malformed/unsupported {expr} shouldn't crash the whole
                # program — fall back to the raw literal, same graceful-
                # degradation behavior this already had.
                return MojoString(value)
            return MojoString(result)
        return MojoString(value)

    def _format_fstring_body(self, body: str) -> str:
        # Parse an f-string body (prefix/quotes already stripped) into its
        # final string: literal text interspersed with {expr} groups, each
        # parsed and evaluated through this interpreters own tokenizer and
        # parser/eval_expr, not Pythons eval() on the whole f-string, which
        # bypasses this interpreters own operator/dispatch semantics
        # entirely. Handles {{ / }} escapes and !conversion / :format_spec
        # suffixes the same way CPythons own f-strings do.
        out = []
        i, n = 0, len(body)
        while i < n:
            c = body[i]
            if c == '{':
                if i + 1 < n and body[i + 1] == '{':
                    out.append('{')
                    i += 2
                    continue
                j = self._find_fstring_field_end(body, i + 1)
                out.append(self._eval_fstring_field(body[i + 1:j]))
                i = j + 1
            elif c == '}':
                if i + 1 < n and body[i + 1] == '}':
                    out.append('}')
                    i += 2
                    continue
                out.append('}')  # stray '}' — permissive, don't raise
                i += 1
            else:
                out.append(c)
                i += 1
        return ''.join(out)

    def _find_fstring_field_end(self, body: str, start: int) -> int:
        # Index of the closing brace for an f-string {expr} field that
        # began at start (just past the opening brace), tracking nested
        # brackets/parens/braces and quoted strings so a dict-subscript or
        # nested-brace expression does not close early on an inner quote
        # or brace.
        depth = 1
        in_str = None
        j = start
        n = len(body)
        while j < n:
            cj = body[j]
            if in_str:
                if cj == '\\':
                    j += 2
                    continue
                if cj == in_str:
                    in_str = None
            elif cj == '"' or cj == "'":
                in_str = cj
            elif cj == '(' or cj == '[' or cj == '{':
                depth += 1
            elif cj == ')' or cj == ']' or cj == '}':
                depth -= 1
                if depth == 0:
                    return j
            j += 1
        return n  # unterminated — treat the rest of the body as the field

    def _split_fstring_field(self, field: str):
        # Split a field's inner text into (expr_text, conversion, spec),
        # scanning for the top-level conversion/spec markers CPythons own
        # f-string grammar recognizes: top-level meaning outside any nested
        # bracket/quote, so a slice colon or dict-literal colon is not
        # mistaken for the format-spec separator. Mojo/Python has no
        # general prefix-bang operator (not is used instead), so any bare
        # bang in real expression text is always either part of a not-
        # equal comparison or the f-string conversion flag; checking that
        # the char after r/s/a is the field end or a colon distinguishes
        # them.
        depth = 0
        in_str = None
        i, n = 0, len(field)
        while i < n:
            c = field[i]
            if in_str:
                if c == '\\':
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            elif c == '"' or c == "'":
                in_str = c
            elif c == '(' or c == '[' or c == '{':
                depth += 1
            elif c == ')' or c == ']' or c == '}':
                depth -= 1
            elif depth == 0 and c == '!' and i + 1 < n and field[i + 1] in ('r', 's', 'a'):
                nxt = i + 2
                if nxt == n or field[nxt] == ':':
                    conv = field[i + 1]
                    spec = field[nxt + 1:] if nxt < n else None
                    return field[:i].strip(), conv, spec
            elif depth == 0 and c == ':':
                return field[:i].strip(), None, field[i + 1:]
            i += 1
        return field.strip(), None, None

    def _eval_fstring_field(self, field: str) -> str:
        # Evaluate one expr / expr!conv / expr:spec / expr!conv:spec field
        # (raw text between the outer braces, not including them). Uses
        # only repr/str plus this interpreters own string ops for the
        # conversion/spec step, not the ascii()/format() builtins: those
        # have no compiled-path runtime backing (undefined _ascii/_format
        # symbols at link time when this method itself gets self-hosted-
        # compiled), so they would work only under the Python interpreter
        # and silently fail once compiled.
        expr_text, conv, spec = self._split_fstring_field(field)
        value = self._eval_fstring_expr(expr_text)
        if conv == 'r' or conv == 'a':
            text = repr(value)
        else:
            text = str(value)
        if spec:
            text = self._apply_fstring_format_spec(text, spec)
        return text

    def _apply_fstring_format_spec(self, text: str, spec: str) -> str:
        # Minimal fill/align/width subset of the format-spec mini-language
        # (e.g. ">10", "<5", "^8", "05"), operating on the already-
        # stringified value rather than dispatching by numeric type -
        # covers the common alignment/padding use case without needing a
        # full numeric formatter.
        fill = ' '
        align = None
        i = 0
        if len(spec) >= 2 and (spec[1] == '<' or spec[1] == '>' or spec[1] == '^'):
            fill = spec[0]
            align = spec[1]
            i = 2
        elif len(spec) >= 1 and (spec[0] == '<' or spec[0] == '>' or spec[0] == '^'):
            align = spec[0]
            i = 1
        elif len(spec) >= 1 and spec[0] == '0':
            fill = '0'
            align = '>'
            i = 1
        width_digits = ''
        while i < len(spec) and spec[i] >= '0' and spec[i] <= '9':
            width_digits = width_digits + spec[i]
            i += 1
        if not width_digits:
            return text
        width = int(width_digits)
        pad = width - len(text)
        if pad <= 0:
            return text
        padding = ''
        p = 0
        while p < pad:
            padding = padding + fill
            p += 1
        if align == '<':
            return text + padding
        if align == '^':
            left = pad // 2
            right = pad - left
            left_pad = ''
            j = 0
            while j < left:
                left_pad = left_pad + fill
                j += 1
            right_pad = ''
            j = 0
            while j < right:
                right_pad = right_pad + fill
                j += 1
            return left_pad + text + right_pad
        return padding + text

    def _eval_fstring_expr(self, expr_text: str):
        # Parse and evaluate a single expression string through this
        # interpreters own tokenizer/parser/eval_expr, used for f-string
        # and t-string field interpolation. Deliberately not Pythons
        # eval(): that would evaluate Mojo-flavored expression syntax
        # using CPythons own operators/semantics directly, bypassing this
        # interpreters own dispatch (eval_BinaryOp, eval_CallExpr, etc.)
        # entirely.
        from mojo_compiler import py_tokenize, Parser
        tokens = py_tokenize(expr_text)
        node = Parser(tokens)._parse_expr(0)
        return self.eval_expr(node)

    def eval_BoolLiteral(self, expr: N.BoolLiteral):
        """Evaluate boolean literal."""
        return expr.value

    def eval_NoneLiteral(self, expr: N.NoneLiteral):
        """Evaluate None literal."""
        return None

    def eval_ListLiteral(self, expr: N.ListLiteral):
        """Evaluate list literal."""
        return [self.eval_expr(e) for e in expr.elements]

    def eval_DictLiteral(self, expr: N.DictLiteral):
        """Evaluate dict literal."""
        result = {}
        for key, value in expr.pairs:
            result[self.eval_expr(key)] = self.eval_expr(value)
        return result

    def eval_SetLiteral(self, expr: N.SetLiteral):
        """Evaluate set literal."""
        return {self.eval_expr(e) for e in expr.elements}

    def eval_TupleLiteral(self, expr: N.TupleLiteral):
        """Evaluate tuple literal."""
        return tuple(self.eval_expr(e) for e in expr.elements)

    @staticmethod
    def _wrap_int(v):
        """Mojo's Int is a fixed-width 64-bit signed integer (unlike Python's
        arbitrary-precision int), so arithmetic on it wraps on overflow instead
        of growing. Only ints (not bools, not floats) that come out of a
        user-source BinaryOp/UnaryOp are Mojo Int values, so wrapping here
        cannot affect interpreter-internal bookkeeping."""
        if isinstance(v, int) and not isinstance(v, bool):
            v &= 0xFFFFFFFFFFFFFFFF
            if v >= 0x8000000000000000:
                # 2**64 (0x10000000000000000) doesn't fit in any C integer
                # type this self-hosts to, not even uint64_t (max is
                # 2**64-1) — the existing large-int-literal fix (an explicit
                # ULL suffix, see gimple_codegen.py's _lower_IntLiteral)
                # only covers values up to UINT64_MAX, so this one still
                # warned ("integer constant is too large for its type") once
                # compiled. Split into two in-range subtractions of 2**63
                # (already used, and already known to compile cleanly, a
                # few lines up) instead — same net effect.
                v -= 0x8000000000000000
                v -= 0x8000000000000000
        return v

    @staticmethod
    def _resolve_ambiguous_empty_braces(left, right):
        """Mojo's bare `{}` literal is polymorphic (empty Dict or empty Set,
        inferred from context); this interpreter always parses it as an empty
        dict (Python's default — see mojo_compiler.py's `{}` handling). When
        one side of a set-algebra operator is already a real set, treat an
        empty-dict operand as the empty set Mojo would have inferred, instead
        of raising a TypeError Mojo code would never hit (`set() & {}`)."""
        if isinstance(left, set) and isinstance(right, dict) and not right:
            right = set()
        elif isinstance(right, set) and isinstance(left, dict) and not left:
            left = set()
        return left, right

    def eval_BinaryOp(self, expr: N.BinaryOp):
        """Evaluate binary operation."""
        op = expr.op
        # 'and'/'or' must short-circuit — evaluating both operands
        # unconditionally like every other operator here breaks the
        # extremely common `guard and use_guarded_value` pattern (e.g.
        # `isinstance(x, FunctionDef) and x.name == 'main'`): the right
        # side would still run and raise (AttributeError: no `.name`) even
        # when the left side was falsy and specifically meant to prevent
        # that. Found via 3-levels-deep self-referential interpretation
        # (`mojo.py run mojo.py run mojo.py help`) tripping over exactly
        # this pattern in the project's own source.
        if op == 'and':
            left = self.eval_expr(expr.left)
            return left if not left else self.eval_expr(expr.right)
        if op == 'or':
            left = self.eval_expr(expr.left)
            return left if left else self.eval_expr(expr.right)

        left = self.eval_expr(expr.left)
        right = self.eval_expr(expr.right)

        if op in ('&', '|', '^', '-'):
            left, right = self._resolve_ambiguous_empty_braces(left, right)
        if op == '+': return self._wrap_int(left + right)
        elif op == '-': return self._wrap_int(left - right)
        elif op == '*': return self._wrap_int(left * right)
        elif op == '/': return left / right
        elif op == '//': return left // right
        elif op == '%': return left % right
        elif op == '**': return self._wrap_int(left ** right)
        elif op == '==': return left == right
        elif op == '!=': return left != right
        elif op == '<': return left < right
        elif op == '>': return left > right
        elif op == '<=': return left <= right
        elif op == '>=': return left >= right
        elif op == 'in': return left in right
        elif op == 'is': return left is right
        elif op == 'is not': return left is not right
        elif op == '&': return self._wrap_int(left & right)
        elif op == '|': return self._wrap_int(left | right)
        elif op == '^': return self._wrap_int(left ^ right)
        elif op == '<<': return self._wrap_int(left << right)
        elif op == '>>': return left >> right
        else:
            raise NotImplementedError(f"{self._loc(expr)}Binary operator {op!r} not implemented")

    def eval_UnaryOp(self, expr: N.UnaryOp):
        """Evaluate unary operation."""
        operand = self.eval_expr(expr.operand)
        op = expr.op

        if op == '-': return self._wrap_int(-operand)
        elif op == '+': return +operand
        elif op == '~': return self._wrap_int(~operand)
        elif op == 'not': return not operand
        else:
            raise NotImplementedError(f"{self._loc(expr)}Unary operator {op} not implemented")

    def eval_CallExpr(self, expr: N.CallExpr):
        """Evaluate function call."""
        func = self.eval_expr(expr.func)
        args = [self.eval_expr(arg) for arg in expr.args]
        kwargs = {}

        # Evaluate keyword arguments. CallExpr stores these as `kwargs`, a
        # list of (name, expr) tuples (see mojo_compiler.py's CallExpr and
        # ast_nodes.py) — not a `keywords` dict. The old attribute-name
        # mismatch meant `hasattr(expr, 'keywords')` was always False, so
        # every keyword argument to every call was silently dropped in
        # favor of the callee's default value.
        if getattr(expr, 'kwargs', None):
            kwargs = {k: self.eval_expr(v) for k, v in expr.kwargs}

        if isinstance(func, MojoOverloadSet):
            try:
                return self.invoke(func, *args, **kwargs)
            except _NoOverloadMatch as e:
                raise TypeError(f"{self._loc(expr)}{e}")
        return self.invoke(func, *args, **kwargs)

    def invoke(self, func, *args, **kwargs):
        """Call a value that may be a Mojo-defined function (which needs the
        interpreter threaded through as its first argument) or a plain Python
        callable — shared by eval_CallExpr and builtins like map[func] that
        need to invoke a callee passed to them at runtime."""
        if isinstance(func, (MojoFunction, MojoOverloadSet, _MojoBoundComptimeFunction)):
            return func(self, *args, **kwargs)
        else:
            return func(*args, **kwargs)

    def eval_MemberExpr(self, expr: N.MemberExpr):
        """Evaluate member access."""
        obj = self.eval_expr(expr.obj)
        if isinstance(obj, MojoInstance):
            if expr.member in obj.__dict__:
                return obj.__dict__[expr.member]
            method = obj._mojo_class.methods.get(expr.member)
            if method is not None:
                return BoundMethod(method, obj, self)
            raise AttributeError(f"{self._loc(expr)}'{obj._mojo_class.name}' object has no attribute '{expr.member}'")
        return getattr(obj, expr.member)

    def eval_SubscriptExpr(self, expr: N.SubscriptExpr):
        """Evaluate subscript access."""
        obj = self.eval_expr(expr.obj)
        idx = self.eval_expr(expr.index)
        return obj[idx]

    def eval_SliceExpr(self, expr: N.SliceExpr):
        """Evaluate slice expression."""
        obj = self.eval_expr(expr.obj)
        start = self.eval_expr(expr.start) if expr.start else None
        stop = self.eval_expr(expr.stop) if expr.stop else None
        return obj[start:stop]

    def eval_TernaryExpr(self, expr: N.TernaryExpr):
        """Evaluate ternary conditional."""
        condition = self.eval_expr(expr.condition)
        if condition:
            return self.eval_expr(expr.then_val)
        else:
            return self.eval_expr(expr.else_val)

    def eval_TupleExpr(self, expr):
        """Evaluate tuple expression."""
        return tuple(self.eval_expr(e) for e in expr.elements)

    # Aliases for mojo_compiler node types (ListExpr, DictExpr, SetExpr)
    def eval_ListExpr(self, expr):
        """Evaluate list expression (mojo_compiler naming)."""
        return self.eval_ListLiteral(expr)

    def eval_DictExpr(self, expr):
        """Evaluate dict expression (mojo_compiler naming)."""
        return self.eval_DictLiteral(expr)

    def eval_SetExpr(self, expr):
        """Evaluate set expression (mojo_compiler naming)."""
        return self.eval_SetLiteral(expr)

    def _bind_comprehension_target(self, target_str, value):
        """A comprehension/generator `for` clause's target is a plain string
        (possibly comma-joined for tuple unpacking, e.g. "a, b" or "(a, b)"
        — see mojo_compiler.py's _parse_generator_target), not an Expr node.
        Mirrors execute_VarDecl's handling of the same comma-joined-string
        representation for `var a, b = ...`."""
        name = target_str.strip()
        if name.startswith('(') and name.endswith(')'):
            name = name[1:-1].strip()
        if ',' in name:
            names = [n.strip() for n in name.split(',')]
            values = (list(value) if hasattr(value, '__iter__')
                      and not isinstance(value, (str, bytes)) else [value])
            for n, v in zip(names, values):
                self.scope.define(n, v)
        else:
            self.scope.define(name, value)

    def eval_Comprehension(self, expr):
        """List/set/dict comprehensions and parenthesized generator
        expressions (`expr.kind` in 'list'/'set'/'dict'/'generator').

        Real Python comprehensions get their own scope; this interpreter
        evaluates them in the *current* scope instead (same simplification
        execute_ForStmt already makes for a plain `for` loop) — loop
        variables leak into the enclosing scope, a known minor fidelity
        gap. A 'generator' expression is likewise returned as a plain list,
        not a lazy generator — every real consumer seen here (sum(), any(),
        list(), etc.) accepts any iterable, so the laziness itself is never
        actually needed.

        For a dict comprehension, mojo_compiler.py's parser stores the KEY
        expression in `.element` and the VALUE expression in `.key` (yes,
        swapped from what the names suggest — see _parse_dict_or_set)."""
        results = []

        def run(generators):
            if not generators:
                if expr.kind == 'dict':
                    k = self.eval_expr(expr.element)
                    v = self.eval_expr(expr.key)
                    results.append((k, v))
                else:
                    results.append(self.eval_expr(expr.element))
                return
            gen = generators[0]
            rest = generators[1:]
            for item in self.eval_expr(gen.iterable):
                self._bind_comprehension_target(gen.target, item)
                if all(self.eval_expr(cond) for cond in gen.conditions):
                    run(rest)

        run(expr.generators)
        if expr.kind == 'set':
            return set(results)
        if expr.kind == 'dict':
            return dict(results)
        return results
