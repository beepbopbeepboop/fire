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
import threading
from dataclasses import dataclass
import fire_compiler as N

# Operators handled by Interpreter._apply_compare_op — both eval_BinaryOp
# (a single comparison, e.g. plain `a < b`) and eval_CompareChain (Python
# chained comparisons, `a < b < c`) dispatch through this same set/method
# rather than duplicating the operator table.
_COMPARE_OPS = {'==', '!=', '<', '>', '<=', '>=', 'in', 'not in', 'is', 'is not'}

# Name the outermost `for` clause's already-evaluated iterable is bound to
# inside a generator expression's own scope, so the synthesized outer `for`
# iterates that name instead of re-evaluating the expression on first resume
# (see Interpreter._generator_expression). Dunder-ish to stay clear of any
# name a real program would use.
_GENEXP_ITER_NAME = '__mojo_genexp_iter__'


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
        # Names this scope's function declared `nonlocal`. A declaration
        # changes no value, so it belongs on the scope rather than in a
        # side table: a plain `x = ...` in a nested function is LOCAL by
        # default (Python's own rule, and this interpreter's long-standing
        # behaviour), and `nonlocal x` is exactly the statement that says
        # "except for this one". The assignment then writes the nearest
        # ENCLOSING binding instead of creating a local.
        self.nonlocals: set = set()

    def declare_nonlocal(self, name: str) -> None:
        self.nonlocals.add(name)

    def is_nonlocal(self, name: str) -> bool:
        return name in self.nonlocals

    def define(self, name: str, value):
        self.vars[name] = value

    def get(self, name: str):
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"name '{name}' is not defined")

    def has(self, name: str) -> bool:
        if name in self.vars:
            return True
        if self.parent:
            return self.parent.has(name)
        return False

    def set(self, name: str, value):
        if name in self.vars:
            self.vars[name] = value
        elif self.parent:
            self.parent.set(name, value)
        else:
            self.vars[name] = value

    def delete(self, name: str):
        if name in self.vars:
            del self.vars[name]
        elif self.parent:
            self.parent.delete(name)
        else:
            raise NameError(f"name '{name}' is not defined")


def _split_invoker(owner_interp, args) -> tuple:
    """`(interpreter, args)` for a call that may still carry the interpreter
    as its first positional argument.

    Three spellings of "call me with the interpreter" reach a `MojoFunction`,
    and all three have to land on the same answer:

    1. `Interpreter.invoke` (and `MojoInstance`'s `method(interpreter, self)`)
       volunteer it positionally — the historical, mandatory convention;
    2. a BUILTIN that received the function as a callback
       (`sorted(key=f)`, `min(key=f)`, `map(f, xs)`, `list.sort(key=f)`) calls
       `f(*args)` with no interpreter at all, which used to hand the callee's
       FIRST REAL ARGUMENT over as the interpreter and die in `_invoke` with
       "AttributeError: 'int' object has no attribute 'scope'";
    3. an IMPORTED function, where the caller's interpreter and the one that
       DEFINED the function are different objects (`fire.py run` gives every
       imported module its own `Interpreter`, so `main` calling
       `alpha_module.sb1_probe_amb` arrives with the caller's instance in
       `args[0]` and the callee records the module's own).

    So the leading argument is recognised by TYPE, not by identity with
    `owner_interp`: case 3 is exactly the case where identity is the wrong
    test, and getting it wrong there passed the interpreter through as the
    function's first real argument — `sb1_probe_amb(x)` computed
    `<Interpreter> + 111` and died with "unsupported operand type(s) for +:
    'Interpreter' and 'int'" (test_module_cache.py's SB-1 per-scope-import
    row, which asserts the interpreter path and the compiled path agree).

    Identity is still consulted as a SECOND test, for a hand-constructed
    `MojoFunction` nobody recorded an owner on; and a positional fallback
    keeps the old convention working for one. A Mojo program cannot pass an
    `Interpreter` as a real argument in any spelling this file supports, so
    recognising one can never eat a value.
    """
    if args and isinstance(args[0], Interpreter):
        return args[0], args[1:]
    if owner_interp is not None:
        return owner_interp, args
    if args:
        return args[0], args[1:]
    return owner_interp, args


class MojoFunction:
    """Represents a function defined in Mojo code."""
    def __init__(self, name, params, body, closure_scope, comptime_params=None, param_defaults=None,
                 is_generator=False, is_async=False, interpreter=None):
        self.name = name
        self.params = params
        self.body = body
        self.closure_scope = closure_scope
        # The interpreter that DEFINED this function, recorded so `__call__`
        # does not depend on the caller volunteering it. See `__call__`.
        self._interp = interpreter
        # Names from `def f[dtype: DType, ...](...)`'s bracketed generic
        # parameter list (see fire_compiler.py's _parse_generic_params_capture)
        # — bound by `__getitem__` when the call site subscripts the
        # function (`f[Int32](...)`, not passed as regular arguments.
        self.comptime_params = comptime_params or []
        if param_defaults:
            self._pd = param_defaults
        # Milestone 2 of bugs/INTERP_generator_yield_entirely_unimplemented.md:
        # mirrors FunctionDef.is_generator (see fire_compiler.py) — copied
        # onto the MojoFunction at construction time (see
        # execute_FunctionDef/execute_StructDef/execute_TraitDef) so
        # `_invoke` can branch to the generator-construction path without
        # needing the original FunctionDef node around at call time.
        self.is_generator = is_generator
        # Milestone 3b of bugs/INTERP_generator_yield_entirely_unimplemented.md:
        # mirrors FunctionDef.is_async (see fire_compiler.py) exactly the
        # same way is_generator mirrors FunctionDef.is_generator above —
        # copied onto the MojoFunction at construction time so `_invoke`
        # can branch to the coroutine-construction path without needing
        # the original FunctionDef node around at call time.
        self.is_async = is_async

    def __call__(self, *args, **kwargs):
        # The interpreter used to be a REQUIRED first positional argument, so
        # every caller had to know about it: `Interpreter.invoke` threads it
        # in, and a builtin that takes a callback (`sorted(key=...)`) had no
        # way to and handed the callee's FIRST REAL ARGUMENT over instead.
        # That is not a per-builtin bug — `sorted([1,2,3], key=lambda a: -a)`
        # died in `_invoke` with "AttributeError: 'int' object has no
        # attribute 'scope'", and every other Python callable that invokes a
        # value it was handed (`map(f, xs)`, `min(key=...)`, a `list.sort`
        # key, a callback this compiler never sees) has the same hole.
        #
        # So the interpreter is resolved HERE, from the function's own record
        # of the interpreter that defined it, and the positional convention
        # `Interpreter.invoke` still uses is recognised by `_split_invoker` —
        # which also covers the case where the two interpreters are NOT the
        # same object, which an imported function always is.
        #
        # The alternative — making every callback-taking builtin wrap its
        # callback in `_MojoInvokeWrapper` the way `map[f](...)` already does
        # — leaves the hole open for every callback site nobody enumerated.
        interp, args = _split_invoker(self._interp, args)
        return self._invoke(interp, {}, args, kwargs)

    def __getitem__(self, item):
        values = item if isinstance(item, tuple) else (item,)
        bindings = dict(zip(self.comptime_params, values))
        return _MojoBoundComptimeFunction(self, bindings)

    def _invoke(self, interpreter, comptime_bindings, args, kwargs):
        # Create new scope for function execution
        func_scope = Scope(parent=self.closure_scope)

        for name, value in comptime_bindings.items():
            func_scope.define(name, value)

        # Bind comptime params that have defaults but weren't provided
        # (`self._pd` — the constructor stores param_defaults under that
        # name, see __init__; reading the constructor argument's name here
        # would always find nothing and silently drop every default value,
        # which is exactly the bug this line fixed — see the LambdaExpr
        # handler, whose `lambda x=5: ...` defaults rely on it working).
        _pdl = getattr(self, '_pd', None)
        for cp_name in self.comptime_params:
            if cp_name not in comptime_bindings:
                _found = False
                if _pdl is not None:
                    for _k, _v in _pdl:
                        if _k == cp_name:
                            func_scope.define(cp_name, interpreter.eval_expr(_v))
                            _found = True; break
                if not _found and cp_name not in func_scope.vars:
                    func_scope.define(cp_name, None)

        # Bind parameters to arguments.
        #
        # `*args` / `**kwargs` catch-alls arrive here still carrying their
        # stars (see _extract_param_names). Everything AFTER a `*` — whether
        # a named `*rest` or a bare `*` separator — is keyword-only and must
        # never consume a positional, exactly as in real Python.
        _pos_i = 0
        _seen_star = False
        _var_pos_name = ''
        _var_kw_name = ''
        _consumed_kw = []
        for param in self.params:
            if param.startswith('**'):
                _var_kw_name = param[2:]
                continue
            if param.startswith('*'):
                _var_pos_name = param[1:]  # '' for a bare `*` separator
                _seen_star = True
                continue
            if (not _seen_star) and _pos_i < len(args):
                func_scope.define(param, args[_pos_i])
                _pos_i += 1
            elif param in kwargs:
                func_scope.define(param, kwargs[param])
                _consumed_kw.append(param)
            else:
                _found = False
                if _pdl is not None:
                    for _k, _v in _pdl:
                        if _k == param:
                            func_scope.define(param, interpreter.eval_expr(_v))
                            _found = True; break
                if not _found:
                    func_scope.define(param, None)
        # Leftover positionals -> `*rest`; leftover keywords -> `**kw`. Built
        # with plain loops rather than a slice/comprehension: this file is
        # itself self-hosted, and plain loops are what that compiler lowers
        # reliably (see the MojoGeneratorObject single-return note above for
        # the same class of concession).
        if _var_pos_name:
            _rest = []
            _ri = _pos_i
            while _ri < len(args):
                _rest.append(args[_ri])
                _ri += 1
            func_scope.define(_var_pos_name, _rest)
        if _var_kw_name:
            _rest_kw = {}
            for _kk in kwargs:
                if _kk not in _consumed_kw:
                    _rest_kw[_kk] = kwargs[_kk]
            func_scope.define(_var_kw_name, _rest_kw)

        if self.is_generator and self.is_async:
            # `async def f(): yield x` — a real async generator. Python's
            # actual protocol for these (`__aiter__`/`__anext__`, driven by
            # `async for`, not by plain `await`) is a THIRD distinct
            # protocol from both the sync-generator protocol
            # (MojoGeneratorObject: __iter__/__next__/send/throw) and the
            # coroutine protocol (MojoCoroutine: __await__) built for this
            # milestone — see bugs/INTERP_generator_yield_entirely_unimplemented.md's
            # Milestone 3b report. Deliberately NOT built here: rather than
            # silently picking one of the two existing wrappers (either
            # would behave subtly wrong under `async for`), fail loudly so
            # this reads as a known, documented gap rather than a silent
            # correctness bug.
            raise NotImplementedError(
                f"async generators (`async def {self.name}(): yield ...`) are not "
                f"yet supported by the interpreter — __aiter__/__anext__ protocol "
                f"is a documented follow-up gap, see Milestone 3b report")
        elif self.is_async:
            # Calling an async function must NOT run any of its body eagerly
            # — mirrors is_generator immediately below (same rationale: real
            # Python doesn't execute a single statement of a coroutine
            # function's body until something actually drives it via
            # __await__/.send()). Construct-and-return only; func_scope
            # becomes this coroutine's own private scope, swapped in by
            # MojoCoroutine around every resume — see its docstring.
            result = MojoCoroutine(interpreter, func_scope, self.body)
        elif self.is_generator:
            # Calling a generator function must NOT run any of its body —
            # real Python doesn't execute a single statement of a generator
            # function until the caller starts pulling values out of it.
            # Construct-and-return only; func_scope (with params/comptime
            # bindings already bound above, exactly like the eager path)
            # becomes this generator's own private scope, swapped in by
            # MojoGeneratorObject around every resume — see its docstring
            # for why the swap can't just happen once here.
            #
            # Routed through the same single `result`-variable/single-return
            # shape as the eager path just below (rather than an early
            # `return MojoGeneratorObject(...)`) deliberately: this file is
            # itself self-hosted (gimple_codegen.py compiles it), and that
            # compiler's return-type inference is a simple whole-function
            # unification that got confused by two differently-shaped
            # return statements in the same function (a boxed generic value
            # vs. a directly-constructed local struct type) — see
            # bugs/INTERP_generator_yield_entirely_unimplemented.md's
            # Milestone 2 report for the concrete compile errors this
            # produced before the fix.
            result = MojoGeneratorObject(interpreter, func_scope, self.body)
        else:
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


class _RealAwaitStep:
    """Milestone 3b marker object: yielded (via a worker thread's
    `yield_fn`, exactly like a Mojo `yield` would be) by `eval_AwaitExpr`
    to mean "please advance THIS real iterator/generator (from a real
    native coroutine's `__await__()`, or another `MojoCoroutine`'s) by one
    step, on whatever thread is actually driving me" — see
    `_ThreadedGenerator._resume`'s handling of it for why this can't be
    stepped on the worker thread itself (real asyncio internals like
    `asyncio.sleep` call `get_running_loop()`, which is thread-affine —
    stepping them from the wrong OS thread raises
    `RuntimeError: no running event loop`, confirmed empirically while
    prototyping this milestone)."""
    __slots__ = ("it",)
    def __init__(self, it):
        self.it = it


class _RealThreadCall:
    """Milestone 3b marker, sibling to `_RealAwaitStep`: some real Python
    callables touch the running event loop the instant they're CALLED, not
    merely when later awaited — `asyncio.gather(...)`, `ensure_future`,
    `create_task`, `asyncio.Queue()`, etc. all call `get_running_loop()`/
    `get_event_loop()` eagerly at call time (confirmed empirically:
    `asyncio.gather(...)` invoked from a Mojo coroutine's worker thread
    raised `RuntimeError: no running event loop`, the exact same
    thread-affinity problem `_RealAwaitStep` solves for awaiting, but at
    call time instead of await time). `Interpreter.invoke` wraps any plain
    (non-Mojo) callable invocation made from inside a coroutine's worker
    thread in one of these and hands it to `yield_fn`, so
    `_ThreadedGenerator._resume` executes the call itself — a single
    one-shot step, not a multi-round drive like `_RealAwaitStep` — on
    whichever thread is actually driving this coroutine, then hands the
    result (or propagates the exception) straight back to the worker
    thread. Deliberately NOT applied to plain Mojo `yield` generators —
    only coroutines interact with an event loop, so
    `MojoGeneratorObject`/`_body_fn` never sets the `is_coroutine` TLS flag
    this is gated on, keeping the existing generator fast path completely
    unchanged."""
    __slots__ = ("func", "args", "kwargs")
    def __init__(self, func, args, kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs


class _ThreadedGenerator:
    """A from-scratch generator-protocol implementation (`.send()`/
    `.throw()`/`.close()`, raising `StopIteration` like a real Python
    generator does) backed by a dedicated worker `threading.Thread`,
    DELIBERATELY not using Python's native `yield` keyword anywhere in this
    file. `body_fn(yield_fn)` runs entirely on the worker thread; it calls
    `yield_fn(value)` to suspend and receive back whatever `.send()` later
    passes in, and its `return value` becomes `StopIteration(value)`.

    Why not just a plain Python generator function (as originally
    implemented -- see git history)? myinterpreter.py is itself one of the
    sources this project self-hosts (`fire.py` compiling its own source,
    `myinterpreter.py` included, via gimple_codegen.py). gimple_codegen.py's
    generator detection (added for real Mojo-language `yield` support)
    operates on the raw syntax tree it parses this file's own source into
    and cannot distinguish "this Python function happens to use `yield` as
    its own implementation technique" from "this is a user's Mojo generator
    function" -- see commit 7ab861d, which hit and fixed the identical
    problem in a different file (gimple_codegen.py's own internal
    tree-walkers used `yield` purely as an implementation detail) by
    rewriting them away from `yield` entirely. A single real `yield`
    anywhere in myinterpreter.py's own top-level function bodies makes
    gimple_codegen.py's module-level "fall back to interpreting from
    source" trigger for the WHOLE of myinterpreter.py -- which in turn broke
    `make check-selfhost`: other self-hosted modules calling into
    `Interpreter` methods generate a properly-typed extern declaration for
    them from myinterpreter.py's (normally available) static type info,
    while fire.py's own compiled code -- unable to get that info once
    myinterpreter.py falls back -- instead emits a bare variadic stub
    declaration for the very same C symbol. Two conflicting declarations of
    one symbol in a single linked program is a hard GCC error
    ("conflicting types for 'Interpreter_execute'"), confirmed by actually
    running `make check-selfhost` against a native-generator-based first
    draft of this mechanism.

    A worker-thread coroutine gives the exact same suspend-from-anywhere
    semantics as a native generator -- the Mojo body can `yield` from
    arbitrarily deep inside execute()/eval_expr()'s ordinary recursive call
    chain, with NO per-statement/per-expression-kind mirroring needed
    (unlike the reverted native-generator draft's parallel `_exec_gen`/
    `_eval_gen` dispatch family) -- without the keyword. Exactly one of
    {caller thread, worker thread} runs at a time, handed off via two
    `threading.Event`s: never real concurrency, just cooperative suspension
    implemented with a thread instead of a generator frame.

    Milestone 3b (async/await execution) REUSES this class as-is for
    `MojoCoroutine` too, rather than duplicating it — per CLAUDE.md's
    consolidation principle, the underlying "run this body on a worker
    thread, suspend via yield_fn+Events" mechanism is identical between a
    Mojo `yield` and a Mojo `await`; only the protocol MojoGeneratorObject
    vs. MojoCoroutine expose to their respective callers differs. To
    support `await`, `_resume` additionally recognizes when the worker
    yields a `_RealAwaitStep` (meaning: "step this real awaitable/
    MojoCoroutine, not the Mojo body, and don't wake the Mojo body up
    until that real thing is actually done") and drives it in a loop on
    the CALLING thread — see `_resume`'s docstring for why the calling
    thread specifically, not the worker thread, must do that stepping."""

    def __init__(self, body_fn):
        self._to_worker = threading.Event()
        self._to_caller = threading.Event()
        self._sent_value = None
        self._yielded_value = None
        self._inject_exc = None    # caller -> worker: exception to raise at the suspend point
        self._raised_exc = None    # worker -> caller: exception the body raised (propagates from send/throw)
        self._return_value = None
        self._done = False
        # Milestone 3b: set while `_resume` is mid-stepping a real awaitable
        # on behalf of `await` (see `_RealAwaitStep`) — non-None means "the
        # worker thread is parked waiting for the FINAL result of this real
        # await, don't resume it with an ordinary send/throw value; keep
        # stepping `it` instead" (see `_resume`).
        self._active_real_it = None

        def _yield_fn(value):
            self._yielded_value = value
            self._to_caller.set()
            self._to_worker.wait()
            self._to_worker.clear()
            if self._inject_exc is not None:
                exc, self._inject_exc = self._inject_exc, None
                raise exc
            return self._sent_value

        def _worker():
            self._to_worker.wait()
            self._to_worker.clear()
            try:
                if self._inject_exc is not None:
                    exc, self._inject_exc = self._inject_exc, None
                    raise exc
                self._return_value = body_fn(_yield_fn)
            except BaseException as e:
                self._raised_exc = e
            finally:
                self._done = True
                self._to_caller.set()

        # Deep *Mojo-level* recursion inside a generator body fans out into
        # many nested Python frames per Mojo call the same way fire.py's own
        # `interpret_and_execute` worker thread does (eval_expr ->
        # eval_CallExpr -> invoke -> _invoke -> execute -> ...) — the default
        # OS thread stack is nowhere near big enough. threading.stack_size()
        # is a process-global setting applied to threads created after the
        # call, matching the same pattern fire.py itself already uses.
        _old_stack_size = threading.stack_size()
        threading.stack_size(1024 * 1024 * 1024)
        try:
            self._thread = threading.Thread(target=_worker, daemon=True)
            self._thread.start()
        finally:
            threading.stack_size(_old_stack_size)

    def _resume_once(self):
        """The single Event-handoff step (exactly the original `_resume`
        body, pre-Milestone-3b): hand off to the worker thread and wait for
        it to either yield again or finish. Raises a BARE `StopIteration`
        (no constructor argument) when done — the return value is read
        back off `self._return_value` afterward instead of
        `StopIteration.value`/`.args` deliberately: this file self-hosts,
        and the compiler's exception model represents a raised exception as
        a type tag + opaque payload, not a real struct with a typed
        `.value`/`.args` field it can generate attribute-access code
        against (only `MojoError`'s dedicated `_raised_mojo_value` channel
        and plain string messages are supported that way) — reading a
        value off one of OUR OWN classes' ordinary fields instead sidesteps
        that entirely. Assumes `self._sent_value`/`self._inject_exc` are
        already set by the caller (`_resume`)."""
        self._to_worker.set()
        self._to_caller.wait()
        self._to_caller.clear()
        if self._done:
            exc, self._raised_exc = self._raised_exc, None
            if exc is not None:
                raise exc
            raise StopIteration
        return self._yielded_value

    def _resume(self):
        """Drives one logical send()/throw() step to completion, which may
        take MULTIPLE Event handoffs when a `_RealAwaitStep` is involved
        (Milestone 3b). Loop body, each pass:

        - If `self._active_real_it` is set, the worker is currently parked
          waiting on the FINAL outcome of a real await — step `it` itself
          right here, on THIS (the calling) thread. This is the crux of
          why real asyncio interop works at all: `it` is (transitively) a
          real native coroutine/Future's own `__await__()` iterator, and
          real asyncio internals like `asyncio.sleep` call
          `get_running_loop()`, which is thread-affine (fails with
          `RuntimeError: no running event loop` off the loop's own thread —
          confirmed empirically). Since `_resume` is always invoked by
          whatever thread is legitimately driving this coroutine/generator
          (the real event loop's Task-stepping code, for a top-level
          `await`; another worker thread, for Mojo-await-Mojo), stepping
          `it` HERE is always on a correct thread, transitively, all the
          way up the chain.
            - `it` raises `StopIteration(v)`: the real await is done;
              clear `_active_real_it` and loop back around to hand `v` to
              the worker as its ordinary yield_fn(...) return value —
              exactly as if the worker's `yield_fn` call is now returning.
            - `it` raises any other exception: same, but inject it instead
              (the worker's `yield_fn` call raises it, matching real
              `await`'s "the awaited thing raised" propagation).
            - `it` yields again (still not done, e.g. `Future.__await__`'s
              `yield self`): propagate that value straight back OUT to
              whoever is driving US, untouched, WITHOUT touching the
              worker thread at all — it stays parked. This is what lets a
              real `Future` bubble all the way up to real asyncio's Task
              machinery for actual timer/IO scheduling.
        - Otherwise, do one ordinary Event handoff (`_resume_once`). If the
          worker yielded a `_RealAwaitStep`, record its iterator as
          `_active_real_it` and loop back around (first step: send(None),
          matching how a freshly-`__await__()`-ed iterator is always first
          primed with `None`). Any other yielded value (a genuine Mojo
          `yield`, for MojoGeneratorObject) — or the worker finishing —
          returns/raises straight out to the caller, unchanged from
          pre-Milestone-3b behavior.

        Routed through `self._yielded_value` as the SOLE carrier of
        whatever this call ultimately returns, with exactly ONE textual
        `return self._yielded_value` statement at the very end (`break`
        out of the loop rather than returning from several different
        points) — deliberately, mirroring the documented
        `MojoFunction._invoke` workaround for `is_generator`/`is_async`:
        this file is itself self-hosted, and the self-hosted compiler's
        return-type inference is a simple whole-function unification that
        gets confused by differently-shaped return statements/fresh local
        variables in the same function — confirmed empirically while
        building this (an earlier draft using a fresh local `result`
        variable, even with a single `return result` statement, compiled
        fine interpreted but failed `make check-selfhost` with a gimple
        `non-trivial conversion in 'var_decl'` verifier error; routing
        through the ALREADY-established `self._yielded_value` field —
        whose type the inferencer already resolved correctly from
        `_yield_fn`'s pre-existing, unmodified assignment — fixed that.
        A SECOND, separate self-host failure of the same species hit right
        after: this method used to take `send_val`/`exc` as its own
        parameters (defaulting to `None`, reassigned across loop
        iterations to real objects/exceptions). The self-hosted compiler's
        exception representation is a `char *` message string (see
        `_resume_once`'s docstring), and a local/parameter that's
        SOMETIMES `None` (inferred `int64_t`) and SOMETIMES a real
        exception (`char *`) is a genuine, unreconcilable C type conflict
        for it — confirmed via the exact gimple dump
        (`int64_t / char * / exc = _t38;`). `send()`/`throw()` (below)
        instead set `self._sent_value`/`self._inject_exc` directly, the
        exact same pre-existing fields `_resume_once`/`_yield_fn` already
        use for this — proven to self-host correctly before this
        milestone touched anything — and `_resume` takes no parameters at
        all, consulting/updating only those fields."""
        while True:
            if self._active_real_it is not None:
                it = self._active_real_it
                try:
                    if self._inject_exc is not None:
                        e, self._inject_exc = self._inject_exc, None
                        step_result = it.throw(e)
                    else:
                        step_result = it.send(self._sent_value)
                        self._sent_value = None
                except StopIteration as si:
                    self._active_real_it = None
                    self._sent_value = si.value
                    self._inject_exc = None
                    continue
                except BaseException as e:
                    self._active_real_it = None
                    self._prime_inject(e)
                    continue
                self._yielded_value = step_result
                break
            y = self._resume_once()
            if isinstance(y, _RealAwaitStep):
                self._active_real_it = y.it
                self._sent_value = None
                self._inject_exc = None
                continue
            if isinstance(y, _RealThreadCall):
                # One-shot version of the above: execute the call itself
                # (not an iterator step) right here, on the correct
                # thread, then immediately hand the result/exception back
                # to the worker and loop around for its next suspension —
                # see _RealThreadCall's docstring.
                try:
                    call_result = y.func(*y.args, **y.kwargs)
                except BaseException as e:
                    self._prime_inject(e)
                else:
                    self._sent_value = call_result
                    self._inject_exc = None
                continue
            self._yielded_value = y
            break
        return self._yielded_value

    def send(self, value):
        if self._done:
            raise StopIteration
        self._sent_value = value
        self._inject_exc = None
        return self._resume()

    def throw(self, exc):
        if self._done:
            raise exc
        self._prime_inject(exc)
        return self._resume()

    def _prime_inject(self, exc):
        """Sets up `self._inject_exc`/`self._sent_value` for the next
        `_resume()` call to inject `exc` at the worker's suspension point —
        factored out of `throw()` (whose `self._inject_exc = exc` /
        `self._sent_value = None` pair is unchanged, just moved here) so
        `_resume`'s own real-await-exception-handling branches (Milestone
        3b) can reuse the EXACT SAME assignment shape for exceptions they
        catch via `except BaseException as e:` from a real iterator/call.
        This split mattered empirically, not just stylistically: assigning
        an except-as-bound exception straight into `self._inject_exc`
        inline inside `_resume`'s own try/except produced a genuine
        self-hosted gimple type conflict (`int64_t` vs. `char *` — an
        except-as binding apparently infers narrower than a same-shaped
        assignment reached via an ordinary function parameter). Passing it
        as a plain parameter across this method-call boundary instead —
        identical statement, different call site — self-hosts correctly."""
        self._inject_exc = exc
        self._sent_value = None

    def close(self):
        if self._done:
            return
        try:
            self.throw(GeneratorExit())
        except (GeneratorExit, StopIteration):
            pass


class MojoGeneratorObject:
    """Wraps the `_ThreadedGenerator` produced by driving a Mojo generator
    function's body through the ORDINARY, unmodified `execute()`/
    `eval_expr()` dispatch (see `_ThreadedGenerator`'s docstring for why a
    worker thread instead of a native Python generator), exposing the
    subset of Python's generator protocol Mojo programs can observe:
    `__iter__`, `__next__`, `.send()`, `.throw()`, `.close()`.

    THE SHARP EDGE: `interpreter.scope` is a single mutable attribute, not a
    parameter threaded through calls (see Scope/MojoFunction docstrings
    elsewhere in this file). A naive design would swap `interpreter.scope`
    to `func_scope` once when the underlying generator is first created and
    swap it back once when the generator finally completes -- mirroring how
    MojoFunction._invoke does it for an ordinary (non-suspending) call. That
    is wrong here: between any two resumes of a suspended generator, the
    interpreter keeps right on running other code (the code that called
    `next()`/`.send()`, possibly itself another generator's body) with
    `interpreter.scope` pointing wherever THAT code needs it to point.
    Interleaved generators (e.g. two counters advanced in lockstep by a
    `zip`-like loop) would otherwise read/write each other's locals -- even
    though each generator's body runs on its own dedicated OS thread, only
    one of {any generator's worker thread, the caller's thread} ever
    actually runs at a time (strict handoff via `_ThreadedGenerator`'s
    Events), so this is the exact same single-mutable-attribute hazard a
    native-generator design would have, just realized with real threads
    instead of generator frames.

    The fix: every single entry into the underlying raw generator (each
    `__next__`/`send`/`throw`/`close` call, not just the first/last one)
    saves whatever scope is currently active, swaps in this generator's own
    `func_scope` for the duration of exactly that one resume, and restores
    the caller's scope the instant control returns -- whether by yielding
    again, returning, or raising. This is exactly a context switch, done at
    every switch point, not just at thread start/end."""

    def __init__(self, interpreter, func_scope, body):
        self.interpreter = interpreter
        self.func_scope = func_scope

        def _body_fn(yield_fn):
            tls = interpreter._gen_tls
            old_yield_fn = getattr(tls, 'yield_fn', None)
            tls.yield_fn = yield_fn
            try:
                try:
                    for stmt in body:
                        interpreter.execute(stmt)
                    return None
                except ReturnValue as ret:
                    return ret.value
            finally:
                tls.yield_fn = old_yield_fn

        self._raw_gen = _ThreadedGenerator(_body_fn)
        self._started = False
        self._finished = False
        # The delegate's `return value` (a Mojo `return` inside a generator
        # body — becomes `StopIteration.value` in real Python), read off
        # `_ThreadedGenerator._return_value` and re-exposed here as an
        # ordinary field on one of THIS FILE's OWN classes rather than ever
        # touching `.value`/`.args` on the `StopIteration` exception object
        # itself — see `_ThreadedGenerator._resume`'s docstring for why
        # (this file self-hosts; the compiler's exception model has no
        # typed-attribute-access story for a builtin exception's payload).
        # `eval_YieldFromExpr` reads this after catching a bare
        # `StopIteration` to propagate `yield from`'s return value.
        self.return_value = None

    def __iter__(self):
        return self

    def _enter(self):
        """Start one resume step: swap `interpreter.scope` to this
        generator's own scope and return whatever scope was active before,
        so the caller can restore it in `_leave()` — see class docstring.
        Split into explicit enter/leave methods (rather than a single
        `_drive(thunk)` taking a `lambda: ...` closure, the original shape)
        because gimple_codegen.py's self-hosted compile of THIS file
        couldn't resolve a lambda passed as a callable argument at a call
        site (`_MojoGeneratorObject___next___lambda_1` etc. came back as
        undefined symbols at link time) — an open/close pair with no
        closure argument sidesteps that compiled-path gap entirely."""
        old = self.interpreter.scope
        self.interpreter.scope = self.func_scope
        return old

    def _leave(self, old):
        self.interpreter.scope = old
        self._started = True

    def __next__(self):
        if self._finished:
            raise StopIteration
        old = self._enter()
        try:
            return self._raw_gen.send(None)
        except StopIteration:
            self._finished = True
            self.return_value = self._raw_gen._return_value
            raise
        finally:
            self._leave(old)

    def send(self, value):
        if value is not None and not self._started:
            # Matches real Python: a just-started generator can only be
            # resumed with `.send(None)` (equivalent to `next()`) — it
            # hasn't reached a `yield` expression yet to receive a value.
            raise TypeError("can't send non-None value to a just-started generator")
        if self._finished:
            raise StopIteration
        old = self._enter()
        try:
            return self._raw_gen.send(value)
        except StopIteration:
            self._finished = True
            self.return_value = self._raw_gen._return_value
            raise
        finally:
            self._leave(old)

    def throw(self, exc_type, exc_val=None, exc_tb=None):
        # Normalize the (exc_type, exc_val, exc_tb) / bare-instance call
        # shapes real Python's generator.throw() accepts down to a single
        # exception instance — `_ThreadedGenerator.throw` (see its
        # docstring) only needs to inject one exception object at the
        # suspend point, not reconstruct a full three-arg raise.
        if isinstance(exc_type, BaseException):
            exc = exc_type
        elif exc_val is not None:
            exc = exc_type(exc_val) if not isinstance(exc_val, BaseException) else exc_val
        else:
            exc = exc_type()
        if self._finished:
            raise exc
        old = self._enter()
        try:
            return self._raw_gen.throw(exc)
        except StopIteration:
            self._finished = True
            self.return_value = self._raw_gen._return_value
            raise
        finally:
            self._leave(old)

    def close(self):
        """Throws GeneratorExit into the generator at its current suspension
        point (delegating to `_ThreadedGenerator.close()`, which already
        implements this correctly) so a `try/finally` holding a resource
        inside the Mojo generator body runs its cleanup even if the
        generator is never fully consumed."""
        if self._finished:
            return
        old = self._enter()
        try:
            self._raw_gen.close()
        finally:
            self._leave(old)
        self._finished = True


class MojoCoroutine:
    """Milestone 3b: the `async def` counterpart of `MojoGeneratorObject`.
    Wraps a `_ThreadedGenerator` driving a Mojo coroutine function's body
    through the ORDINARY, unmodified `execute()`/`eval_expr()` dispatch —
    exactly the same underlying mechanism as `MojoGeneratorObject`, reused
    directly rather than duplicated (see `_ThreadedGenerator`'s docstring)
    since the only thing that differs is which protocol gets exposed:
    `__iter__`/`__next__`/`.send()`/`.throw()` there, `__await__` here.

    `__await__` is a PLAIN method (not `def __await__(self): yield ...`,
    which would itself be a native-yield trap — see the module-wide
    constraint documented on `_ThreadedGenerator`) that returns `self`,
    since `MojoCoroutine` itself implements the `__next__`/`send`/`throw`
    iterator protocol real Python's `await`/`asyncio` machinery actually
    drives an awaitable's `__await__()` result through. This is genuinely
    real-asyncio-compatible: `asyncio.run(mojo_coro)`,
    `asyncio.gather(mojo_coro1, mojo_coro2)`, and `await mojo_coro` from
    ordinary real Python `async def` code all work, validated empirically
    (see bugs/INTERP_generator_yield_entirely_unimplemented.md's Milestone
    3b report) — including a Mojo body that internally does
    `await asyncio.sleep(...)`, which really suspends on the real event
    loop and really takes real wall-clock time, and `asyncio.gather` of
    several Mojo coroutines really running concurrently (interleaved by
    the real event loop, not just sequentially).

    Raises `StopIteration(value)` — WITH the constructor argument, unlike
    `_ThreadedGenerator._resume_once`'s deliberately-bare `StopIteration`
    — from `send`/`throw`/`__next__` when the coroutine body returns. This
    might look like it contradicts `_ThreadedGenerator`'s documented
    self-hosting workaround (avoiding `StopIteration.value` because the
    self-hosted compiler's exception model can't do typed attribute access
    against a builtin exception), but it doesn't: this file's OWN source
    never reads `.value` off a `StopIteration` anywhere (`return_value` is
    tracked as an ordinary field, exactly like `MojoGeneratorObject`, and
    used to build the argument passed to `StopIteration(...)` here) — only
    CONSTRUCTS and RAISES one. Real Python's own `await`/`SEND` bytecode
    (running in the genuinely-interpreted path, where these objects are
    real CPython objects) is what reads `.value` back out, and that's real
    CPython machinery, not code inside this self-hosted file.

    Same `interpreter.scope` swap-on-every-resume discipline as
    `MojoGeneratorObject` (identical hazard: `interpreter.scope` is one
    mutable attribute, not a per-call parameter — see that class's
    docstring for the full explanation), extended to also cover
    concurrent-by-real-asyncio coroutines, not just hand-interleaved
    generators: since real asyncio only ever runs ONE callback at a time
    on its single event-loop thread, and every one of a coroutine's worker
    threads only ever runs while its OWN `_enter`/`_leave` window holds
    `interpreter.scope` pinned to that coroutine's own scope (strictly
    alternating with whichever OTHER coroutine/generator/plain call is
    active at that instant, exactly like `_ThreadedGenerator`'s handoff
    guarantees), the same single-mutable-attribute swap remains correct
    even when several `MojoCoroutine`s are "concurrently" in flight from
    asyncio's point of view."""

    def __init__(self, interpreter, func_scope, body):
        self.interpreter = interpreter
        self.func_scope = func_scope

        def _body_fn(yield_fn):
            tls = interpreter._gen_tls
            old_yield_fn = getattr(tls, 'yield_fn', None)
            old_is_coroutine = getattr(tls, 'is_coroutine', False)
            tls.yield_fn = yield_fn
            # Gates Interpreter.invoke's _RealThreadCall bounce (see its
            # docstring) — only coroutine bodies interact with an event
            # loop, so plain Mojo generators never pay for or risk this.
            tls.is_coroutine = True
            try:
                try:
                    for stmt in body:
                        interpreter.execute(stmt)
                    return None
                except ReturnValue as ret:
                    return ret.value
            finally:
                tls.yield_fn = old_yield_fn
                tls.is_coroutine = old_is_coroutine

        self._raw = _ThreadedGenerator(_body_fn)
        self._started = False
        self._finished = False

    def _enter(self):
        """See MojoGeneratorObject._enter — identical swap-in, split out of
        a lambda-taking `_drive` for the identical self-hosted-compile
        reason documented there."""
        old = self.interpreter.scope
        self.interpreter.scope = self.func_scope
        return old

    def _leave(self, old):
        self.interpreter.scope = old
        self._started = True

    def __await__(self):
        """The entire real-asyncio-interop hinge point: returning `self`
        (which implements `__next__`/`send`/`throw`) is all real Python's
        `await`/`SEND` bytecode needs to drive this coroutine exactly like
        any other awaitable — a real native coroutine, a real `Future`, or
        another `MojoCoroutine` (Mojo-await-Mojo — see `eval_AwaitExpr`,
        which treats a `MojoCoroutine` no differently from a real one,
        uniformly, since both merely need to expose `__await__`)."""
        return self

    def __iter__(self):
        return self

    def __next__(self):
        return self.send(None)

    def send(self, value):
        if self._finished:
            raise StopIteration
        old = self._enter()
        try:
            result = self._raw.send(value)
            return result
        except StopIteration:
            self._finished = True
            raise StopIteration(self._raw._return_value)
        finally:
            self._leave(old)

    def throw(self, exc_type, exc_val=None, exc_tb=None):
        # Normalize the (exc_type, exc_val, exc_tb) / bare-instance call
        # shapes real Python's coroutine.throw() accepts — see
        # MojoGeneratorObject.throw, identical normalization.
        if isinstance(exc_type, BaseException):
            exc = exc_type
        elif exc_val is not None:
            exc = exc_type(exc_val) if not isinstance(exc_val, BaseException) else exc_val
        else:
            exc = exc_type()
        if self._finished:
            raise exc
        old = self._enter()
        try:
            result = self._raw.throw(exc)
            return result
        except StopIteration:
            self._finished = True
            raise StopIteration(self._raw._return_value)
        finally:
            self._leave(old)

    def close(self):
        """See MojoGeneratorObject.close — identical GeneratorExit-based
        cleanup, delegated to the same `_ThreadedGenerator.close()`."""
        if self._finished:
            return
        old = self._enter()
        try:
            self._raw.close()
        finally:
            self._leave(old)
        self._finished = True


class _MojoSelfType:
    """Generic Self type marker used when Self is referenced outside
    a struct method context."""
    def __getattr__(self, name):
        return self
    def __getitem__(self, key):
        return self
    def __call__(self, *args, **kwargs):
        return self
    def __repr__(self):
        return 'Self'


class _MojoBoundComptimeFunction:
    """Result of subscripting a generic function at a call site
    (`run_func[DType.float64](8, 0.125, ctx)`) — the comptime parameter
    names are pre-bound; calling it runs the function body with both those
    and the regular call-time arguments in scope."""
    def __init__(self, func, comptime_bindings):
        self.func = func
        self.comptime_bindings = comptime_bindings

    def __call__(self, *args, **kwargs):
        # `f[DType](x)` curried into a callable is handed to builtins as an
        # ordinary value (`sorted(xs, key=f[Int])`), so — exactly as in
        # `MojoFunction.__call__` — the interpreter is resolved from the
        # underlying function's own record rather than demanded positionally,
        # through the same `_split_invoker` (an imported generic function has
        # the same two-different-interpreters shape as any other).
        func = self.func
        interp, args = _split_invoker(func._interp, args)
        return func._invoke(interp, self.comptime_bindings, args, kwargs)


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
    def __init__(self, name, interpreter=None):
        self.name = name
        self.candidates = []  # list of (MojoFunction, required, optional, kwonly, has_var_kwargs)
        # Same reason as `MojoFunction._interp`, and for the same reason
        # `__call__` resolves it the same way: a builtin receiving this set as
        # a `key=`/callback argument invokes it directly, with no interpreter
        # to thread through.
        self._interp = interpreter

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

    def __call__(self, *args, **kwargs):
        # `interpreter` used to be a required first positional argument; see
        # `MojoFunction.__call__` for why it no longer is and how it is
        # resolved instead. An overload SET's candidates come from one module
        # and its call sites can come from another, so the two interpreters are
        # routinely different objects — which is why `_split_invoker`
        # recognises the leading argument by type.
        interp, args = _split_invoker(self._interp, args)
        for spec in self.candidates:
            if self._matches(spec, args, kwargs):
                func = spec[0]
                return func._invoke(interp, {}, args, kwargs)
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

    def __len__(self):
        method = self._mojo_class.methods.get('__len__')
        if method is not None:
            return method(self._mojo_class.interpreter, self)
        raise TypeError(f"object of type '{self._mojo_class.name}' has no len()")

    def __getitem__(self, key):
        method = self._mojo_class.methods.get('__getitem__')
        if method is not None:
            return method(self._mojo_class.interpreter, self, key)
        raise KeyError(key)

    def __setitem__(self, key, value):
        method = self._mojo_class.methods.get('__setitem__')
        if method is not None:
            return method(self._mojo_class.interpreter, self, key, value)
        raise KeyError(key)

    def __call__(self, *args, **kwargs):
        """An instance of a struct that defines `__call__` IS callable — the
        `functor` idiom, and the reason a callable OBJECT reaches a builtin's
        callback slot at all (`sorted(xs, key=ByLength())`).

        Without this the object was simply not callable, so
        `sorted([1,2,3], key=Callable(10))` raised "TypeError:
        'MojoInstance' object is not callable" — a hole right next to the one
        `MojoFunction.__call__` had. Resolved through the SAME
        `self._mojo_class.methods` table and the same
        `method(interpreter, self, ...)` shape as `__len__`/`__getitem__`/
        `__setitem__` above, so `__call__` is bound exactly the way every
        other dunder on this class is."""
        method = self._mojo_class.methods.get('__call__')
        if method is None:
            raise TypeError(f"object of type '{self._mojo_class.name}' is not callable")
        return method(self._mojo_class.interpreter, self, *args, **kwargs)


class BoundMethod:
    """A struct/class method bound to a specific instance (`self` already filled in)."""
    def __init__(self, bound_func, instance, interpreter):
        self.bound_func = bound_func
        self.instance = instance
        self.interpreter = interpreter

    def __call__(self, *args, **kwargs):
        f = self.bound_func
        old_scope = self.interpreter.scope
        self.interpreter.scope = Scope(parent=self.interpreter.scope)
        self.interpreter.scope.define('self', self.instance)
        try:
            return f(self.interpreter, self.instance, *args, **kwargs)
        finally:
            self.interpreter.scope = old_scope

    def __getitem__(self, key):
        return self


class BoundClassMethod:
    """A `@classmethod` with the CLASS already filled in under the source-level
    name `cls` — the classmethod counterpart of `BoundMethod`.

    Before this, a `@classmethod` had NO representation at all: `C.m(...)`
    returned the raw unbound `MojoFunction`, so the call bound the FIRST REAL
    ARGUMENT to the `cls` parameter (`C.gen(5)` made `cls == 5`, and
    `cls.<attr>` then raised "'int' object has no attribute ..."). That made
    the ORACLE disagree with the compiled path, which does pass a receiver,
    on a shape real code uses (see
    bugs/COMPILE_FAIL_importlib_resources_readers.md's
    `yield from cls.<sibling generator>(...)`).

    A separate class rather than a second receiver kind inside `BoundMethod`:
    this receiver is a `MojoClass *` where `BoundMethod`'s is a
    `MojoInstance *`, and the self-hosted compiler gives every struct field
    ONE C type. Erasing both to one `void *` would buy a single class at the
    price of a cast at each of this one's use sites; two small classes with
    homogeneous fields costs one extra `struct_field_types` entry and reads
    more plainly.
    """
    def __init__(self, bound_func, cls, interpreter):
        self.bound_func = bound_func
        self.cls = cls
        self.interpreter = interpreter

    def __call__(self, *args, **kwargs):
        f = self.bound_func
        old_scope = self.interpreter.scope
        self.interpreter.scope = Scope(parent=self.interpreter.scope)
        self.interpreter.scope.define('cls', self.cls)
        try:
            return f(self.interpreter, self.cls, *args, **kwargs)
        finally:
            self.interpreter.scope = old_scope

    def __getitem__(self, key):
        return self


class MojoClass:
    """Represents a class/struct defined in Mojo code."""
    _ARRAY_TYPE_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\[([A-Za-z_][A-Za-z0-9_]*|\d+)\]$')
    _ARRAY_ELEM_DEFAULTS = {
        'Bool': False, 'String': '',
        'Float16': 0.0, 'Float32': 0.0, 'Float64': 0.0,
    }

    def __init__(self, name, fields, methods, interpreter, bases=None,
                 comptime_aliases=None, static_methods=None, class_methods=None,
                 def_scope=None):
        self.name = name
        self.fields = fields  # list of VarDecl/AssignStmt (field declarations)
        self.methods = methods  # dict: name -> MojoFunction
        self.interpreter = interpreter
        # The scope struct-definition executed in (same closure MojoFunction
        # captures for methods) — needed to resolve a fixed-size array field's
        # size expression (e.g. `Int[MAX_CELLS]`) by the comptime constant's
        # OWN defining module, not whatever module happens to instantiate this
        # struct (mirrors how `__init__` bodies already resolve such names).
        self.def_scope = def_scope
        self.bases = bases or []  # base MojoClass objects, e.g. `struct Child(Base):`
        # `comptime EOF_TOKEN: Int = 69` inside the struct body — evaluated
        # once at struct-definition time and exposed as a class-level
        # attribute (`TokenType.EOF_TOKEN`), same as a Python class constant.
        self.comptime_aliases = comptime_aliases or {}
        # Names of `@staticmethod` methods — looked up here so __getattr__
        # can hand back the raw MojoFunction (no instance to bind) instead
        # of wrapping it in a BoundMethod.
        self.static_methods = static_methods or set()
        # Names of `@classmethod` methods, the mirror image: __getattr__ wraps
        # one in a BoundMethod bound to THIS class under the name `cls`, so
        # `C.m(x)` and `C().m(x)` both deliver the class as the first
        # argument. Inherited from a base like static_methods is, and an
        # override in a subclass rebinds `cls` to the SUBCLASS — which is
        # exactly Python's rule, and is what makes `yield from
        # cls.<sibling>()` inside a generator resolve against the class the
        # call was actually made on.
        self.class_methods = class_methods or set()

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
            # not an instance — return the raw MojoFunction unbound, EXCEPT
            # for a `@classmethod`, which is exactly the case where the
            # receiver IS the class: bind it and the call is correct on the
            # first argument, with no call-site knowledge of the decorator.
            # `@staticmethod`s keep the unbound raw function (nothing to
            # bind); a regular method returned this way still just requires
            # the caller to pass `self` explicitly, matching Python's own
            # unbound-method rule.
            method = self.methods[name]
            if name in self.class_methods:
                return BoundClassMethod(method, self, self.interpreter)
            return method
        if name == '__name__':
            # Real Python classes carry their own name here; a MojoClass
            # instance passed into a real Python function (e.g. ctypes'
            # POINTER(cls), which does `cls.__name__`) needs the same —
            # ctypes/wintypes.py's `PFILETIME = POINTER(FILETIME)` raised
            # "'FILETIME' object has no attribute '__name__'".
            return self.name
        raise AttributeError(f"'{self.name}' object has no attribute '{name}'")

    def __call__(self, *args, **kwargs):
        instance = MojoInstance(self)
        for f in self.fields:
            if self.interpreter._is_instance(f, 'VarDecl'):
                # Array-default handled as its own early-exit branch, NOT
                # folded into `value`'s own assignment chain below (self-host
                # build note: MojoClass is one of myinterpreter.py's own
                # hardcoded struct_field_types entries — the self-hosted
                # compiler infers one C type per Python local from how it's
                # used across the WHOLE function, so any assignment of
                # `_array_field_default`'s result into `value` — even inside
                # a ternary — made it infer `value` as `MojoList *`
                # unconditionally, breaking `make check-selfhost` with
                # "invalid types in conversion to integer" the moment
                # `_coerce_to_declared_type`'s differently-typed result also
                # flowed into that same `value`, even though the interpreter
                # itself ran fine either way. `array_default` is its own
                # local, assigned from nowhere else, so it can't contaminate
                # `value`'s original, already-self-host-clean inference.)
                if f.value is None:
                    array_default = self._array_field_default(getattr(f, 'type_ann', None))
                    if array_default is not None:
                        setattr(instance, f.name, array_default)
                        continue
                value = self.interpreter.eval_expr(f.value) if f.value is not None else None
                value = self.interpreter._coerce_to_declared_type(value, getattr(f, 'type_ann', None))
                setattr(instance, f.name, value)
            elif self.interpreter._is_instance(f, 'AssignStmt'):
                # AssignStmt has a single `.target`, not a `.targets` list
                # (fire_compiler.py's AssignStmt dataclass) — this branch
                # raised "'AssignStmt' object has no attribute 'targets'"
                # on any instantiation of a class with a bare `NAME = value`
                # class-body attribute (e.g. `class Foo: count = 0`).
                value = self.interpreter.eval_expr(f.value) if f.value is not None else None
                target = f.target
                if self.interpreter._is_instance(target, 'IdentExpr'):
                    setattr(instance, target.name, value)
        init = self.methods.get('__init__')
        if init is not None:
            interp = self.interpreter
            old_scope = interp.scope
            interp.scope = Scope(old_scope)
            interp.scope.define('self', instance)
            try:
                init(interp, instance, *args, **kwargs)
            finally:
                interp.scope = old_scope
        elif args:
            # Implicit memberwise constructor: a struct/class with NO explicit
            # __init__ binds positional ctor args to its fields in declaration
            # order — `struct Point: var x: Int; var y: Int; Point(3, 4)` sets
            # x=3, y=4 (matches gimple_codegen's _synthesize_fieldwise_inits
            # and real Mojo). Previously the interpreter ignored the args,
            # leaving every field None ("unsupported operand +: None + None").
            field_names = []
            for f in self.fields:
                if self.interpreter._is_instance(f, 'VarDecl'):
                    field_names.append(f.name)
                elif self.interpreter._is_instance(f, 'AssignStmt') \
                        and self.interpreter._is_instance(f.target, 'IdentExpr'):
                    field_names.append(f.target.name)
            for i, a in enumerate(args):
                if i < len(field_names):
                    fname = field_names[i]
                    setattr(instance, fname, a)
        return instance

    def _array_field_default(self, type_ann):
        """A fixed-size array field (`cell_ids: Int[MAX_CELLS]`) with no
        explicit initializer must default to a zero-filled list of the
        declared length, same as real Mojo — not None (BUG-2026: struct array
        fields not initialized when the struct is defined in an imported
        module, `TypeError: 'NoneType' object does not support item
        assignment` on the first indexed write). Returns None (not a
        defaulted array) if `type_ann` isn't a string, isn't `ElemType[size]`
        shape, or the size can't be resolved."""
        if not isinstance(type_ann, str):
            return None
        m = self._ARRAY_TYPE_RE.match(type_ann)
        if not m:
            return None
        elem_type, size_str = m.group(1), m.group(2)
        if size_str.isdigit():
            size = int(size_str)
        else:
            # A named comptime constant (e.g. `MAX_CELLS`) — resolve it in
            # the struct's OWN defining scope, not the caller's, mirroring
            # how `__init__` bodies already resolve such names via their
            # captured closure scope.
            lookup_scope = self.def_scope or self.interpreter.scope
            try:
                size = lookup_scope.get(size_str)
            except NameError:
                return None
            if not isinstance(size, int) or isinstance(size, bool):
                return None
        elem_default = self._ARRAY_ELEM_DEFAULTS.get(elem_type, 0)
        return [elem_default] * size

    def __getitem__(self, item):
        # A user-defined generic struct instantiated with explicit type/value
        # params, e.g. `Layout[Int]`. No monomorphization here — same
        # simplification as _MojoGenericCtor's `List[Int]`.
        return self


class _MojoGenericCtor:
    """Mojo's `List[Int]()`/`Set[Int]()` subscript the type constructor with the
    element type(s) before calling it. The interpreter has no generic-type
    system, so the subscript is a no-op — `List[Int]` and `List[String]` both
    just resolve back to this same constructor, and `[...]` is ignored."""
    def __init__(self, ctor):
        self._ctor = ctor

    def __getitem__(self, item):
        return self

    def __call__(self, *args, **kwargs):
        ctor = self._ctor
        # Mojo's `List(1, 2, 3)`/`Set(1, 2, 3)` pass elements variadically;
        # Python's own list()/set()/deque() take a single iterable argument.
        if len(args) > 1 and not kwargs:
            return ctor(list(args))
        # Mojo constructors may receive keyword args that Python's built-in
        # constructors don't understand — strip known Mojo-specific ones.
        if isinstance(kwargs, dict):
            mojo_kwargs = {'capacity', 'num_bits', 'size', 'uninitialized', 'fill', '__list_literal__', 'ptr', 'length'}
            kwargs = {k: v for k, v in kwargs.items() if k not in mojo_kwargs}
        if kwargs:
            return ctor(*args, **kwargs)
        # After stripping Mojo kwargs, if we still have multiple positional
        # args, wrap them in a list for Python constructors.
        if len(args) > 1:
            return ctor(list(args))
        # Single non-iterable arg to list/set — Mojo treats it as a single
        # element, Python treats it as an iterable. Wrap in a list.
        if len(args) == 1 and ctor in (list, set, tuple) and not isinstance(args[0], (list, tuple, set, str, bytes, range, dict)):
            return ctor([args[0]])
        return ctor(*args, **kwargs)


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
    to `ptr[0]` — see fire_compiler.py's subscript parsing) both fall out of
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


class _MojoListType:
    """`List[T]` (subscript ignored - no generic-type system).

    BUG-2026-028 (mojolib): `from std.collections import List` used to fall
    through to the generic `std.*` auto-stub namespace (real list.mojo is
    full of generics/MLIR-level memory primitives - alloc/Layout/
    ThinAllocation/uninit_move_n - our simple parser can't handle), so
    `List[Int]()` silently returned an `_AutoStubValue`: every method call
    on it (`.append`, `._realloc`, even a nonexistent method name) "succeeded"
    with no error and no effect, and `__len__()` always returned the
    hardcoded stub value 0, while direct field writes like `items._len = 5`
    looked like they worked (plain attribute set on the stub's own __dict__,
    unrelated to any real list state) - a convincing but entirely fake list.

    Rather than attempt to interpret real list.mojo's low-level memory code
    (the exact crash the auto-stub fallback was added to avoid), this backs
    `List[T]()` with a plain Python `list` - the SAME representation
    `eval_ListLiteral` already uses for `[1, 2, 3]` literals, so a
    std.collections.List and a list literal are fully interchangeable
    everywhere else in the interpreter that already expects a Python list,
    and real list operations (append, __len__, indexing, iteration) all
    just work via Python's own list semantics instead of needing bespoke
    reimplementation here."""
    def __getitem__(self, item):
        return self

    def __call__(self, *args, **kwargs):
        if 'copy' in kwargs:
            return list(kwargs['copy'])
        if 'capacity' in kwargs or 'unsafe_uninit_length' in kwargs:
            return []
        # `List(1, 2, 3, __list_literal__=NoneType())` - real Mojo's
        # list-literal-desugaring init; drop the marker kwarg, keep the
        # positional values as the initial contents. Plain `List[Int]()`
        # (no positional args) falls through the same path to `[]`.
        return list(args)

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


class MojoComplex:
    """Minimal runtime representation of Python's `j`/`J`-suffixed imaginary
    literal (`0j`, `1.5j`, `3J` — see fire_compiler.py's `ImagLiteral`) and
    the complex values that result from combining one with a real number via
    `+`/`-`. This deliberately does NOT implement the full Python `complex`
    API (no `*`, `/`, `conjugate()`, `abs()`, comparisons, ...) — per
    bugs/PARSE_FAIL_complex_number_literal.md's scope guidance, construction
    + printing + `+`/`-` against int/float/other MojoComplex is enough to
    cover the two real stdlib patterns that motivated this (a complex value
    sitting in a set/list literal, never used in further arithmetic).
    `__add__`/`__sub__`/`__radd__`/`__rsub__` are all that's needed for
    `left + right`/`left - right` in eval_BinaryOp to "just work" via
    Python's own operator dispatch — no changes to eval_BinaryOp itself."""
    __slots__ = ('real', 'imag')

    def __init__(self, real=0.0, imag=0.0):
        self.real = float(real)
        self.imag = float(imag)

    @staticmethod
    def _coerce(other):
        if isinstance(other, MojoComplex):
            return other.real, other.imag
        if isinstance(other, (int, float)) and not isinstance(other, bool):
            return float(other), 0.0
        return None

    def __add__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return MojoComplex(self.real + c[0], self.imag + c[1])

    def __radd__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return MojoComplex(c[0] + self.real, c[1] + self.imag)

    def __sub__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return MojoComplex(self.real - c[0], self.imag - c[1])

    def __rsub__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return MojoComplex(c[0] - self.real, c[1] - self.imag)

    def __eq__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return self.real == c[0] and self.imag == c[1]

    def __hash__(self):
        # Deliberately id(self)-based, like `_MojoDeviceContext.__hash__`
        # above (a pre-existing example in this same file of the same
        # eq-by-value/hash-by-identity tradeoff) — NOT `hash((self.real,
        # self.imag))`: the self-hosted compiler (gimple_codegen.py) only
        # declares Python's `hash()` builtin as an unimplemented extern stub
        # ("undefined symbol _hash" at link time), and a `int(float_expr)`
        # replacement hit an unrelated existing gimple_codegen miscompile
        # (int() return type inferred as `char *` in this context). Per
        # bugs/PARSE_FAIL_complex_number_literal.md's scope guidance this
        # class isn't meant to support full value-equality hashing (e.g.
        # collapsing `{1, 1+0j}` into `{1}` the way real Python's `complex`
        # does) — just construct/print/`+`/`-` without crashing.
        return id(self)

    @staticmethod
    def _fmt(x: float) -> str:
        """Match Python complex repr's per-part float formatting: same
        shortest-round-trip digits as float repr, but WITHOUT the trailing
        `.0` float repr always adds to a whole number (e.g. `1.0` -> `1`,
        matching `repr(1+0j) == '(1+0j)'`, not `'(1.0+0j)'`)."""
        s = repr(x)
        if s.endswith('.0'):
            s = s[:-2]
        return s

    def __repr__(self):
        # A pure-imaginary value (real part is exactly positive zero) prints
        # as just "Nj", matching Python (`repr(3j) == '3j'`); everything
        # else, including negative-zero real parts, prints in full
        # "(a+bj)"/"(a-bj)" form (`repr(-0j) == '(-0-0j)'`).
        if self.real == 0.0 and math.copysign(1.0, self.real) == 1.0:
            return f"{self._fmt(self.imag)}j"
        sign = '-' if math.copysign(1.0, self.imag) < 0 else '+'
        return f"({self._fmt(self.real)}{sign}{self._fmt(abs(self.imag))}j)"

    __str__ = __repr__


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


def _mojo_operator_index(x):
    """Stand-in for `operator.index` — this file's own compiled form can't
    reach CPython's operator module (`import operator` binds a placeholder
    marker, and reading `.index` off it raises AttributeError at runtime),
    so setup_builtins' `index` binding needs a self-contained equivalent.
    Real operator.index raises TypeError on anything without __index__;
    accepting plain int()/float-truncation here is looser, but every
    in-tree caller passes values that are already integral."""
    return int(x)


def _mojo_isnan(x):
    """NaN check without the math module (same compiled-binary constraint
    as _mojo_operator_index): NaN is the only value not equal to itself."""
    return x != x


def _mojo_isinf(x):
    """Inf check without math: inf - inf == NaN (not 0), while every
    finite value minus itself is exactly 0; NaN itself is excluded by the
    self-equality guard."""
    return x == x and (x - x) != 0


def _mojo_isfinite(x):
    """Finite check without math: neither NaN nor +/-inf."""
    return x == x and (x - x) == 0


def _mojo_extreme(items, key, want_max):
    """The largest/smallest element of `items` by `key` (identity by
    default). ONE implementation for `_mojo_min` and `_mojo_max`: they differ
    only in which comparison wins, and a user `key=` makes that the whole
    behaviour, so a shared walker is what keeps the two from drifting apart
    again.

    `key` is invoked as `key(x)` on the value itself, deliberately NOT through
    `Interpreter.invoke`: a `MojoFunction`'s `__call__` resolves the
    interpreter from its own record now (see its docstring), so a bare call is
    correct for a user-defined callee, and a plain Python callable needs no
    threading at all."""
    result = None
    best_key = None
    have_result = False
    for x in items:
        k = x if key is None else key(x)
        if not have_result:
            result = x
            best_key = k
            have_result = True
        elif (k > best_key if want_max else k < best_key):
            result = x
            best_key = k
    return result


def _mojo_minmax(want_max, *args, **kwargs):
    """Shared body of `_mojo_max` / `_mojo_min`.

    Mojo overloads `max` for SIMD to mean elementwise max, not "pick one
    of these two whole values" like Python's own builtin. Deliberately
    avoids ever calling the bare name `max(...)`/`min(...)`: this file is
    self-hosted-compiled together with gimple_codegen.py, which has an
    existing single-positional-plus-`key=`-kwarg call site
    (`max(survivors, key=_score)`) that fixes the self-host compiler's
    static arity inference for the global `max` symbol at 1 argument —
    calling it here with 2 positional args breaks that compile
    ("too many arguments to function 'mojo_max'").

    `key=` is honoured here rather than delegated to Python's builtin (same
    reason the two-positional SIMD form cannot be). It was not honoured at
    all: `min([3, 1, 2], key=lambda a: -a)` returned `1` — the unkeyed
    minimum — and `max(...)` returned `3`, so both silently answered a
    different question than the one asked."""
    scalar_max2 = _scalar_max2 if want_max else _scalar_min2
    if len(args) == 2 and not kwargs:
        a, b = args
        if isinstance(a, _MojoSIMD) or isinstance(b, _MojoSIMD):
            return _mojo_simd_elementwise(a, b, scalar_max2)
        return scalar_max2(a, b)
    items = args[0] if len(args) == 1 else args
    return _mojo_extreme(items, kwargs.get('key'), want_max)


def _mojo_max(*args, **kwargs):
    return _mojo_minmax(True, *args, **kwargs)


def _mojo_min(*args, **kwargs):
    return _mojo_minmax(False, *args, **kwargs)


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


_AUTO_STUB_VALUE = 0

class _AutoStubValue(int):
    """Auto-stub value that behaves like integer 0 but is also callable
    (returns self) and supports attribute access (returns self) — so
    it works as a drop-in for missing constants like ErrNo.EPERM, and
    when called like a function, it just returns 0."""
    def __new__(cls, val=0):
        return int.__new__(cls, val)
    def __call__(self, *args, **kwargs):
        return _AutoStubValue(_AUTO_STUB_VALUE)
    def __getattr__(self, name):
        return self
    def __getitem__(self, key):
        return self
    def __setitem__(self, key, value):
        pass
    def __len__(self):
        return 0


class _AutoStubNamespace:
    """Auto-stubbing namespace: any attribute access returns AutoStubValue(0)
    which behaves as integer 0 in arithmetic, is callable (returns 0), and
    supports attribute/bracket access (returns self) — so it can stand in
    for missing constants, functions, and types without crashing."""
    def __getattr__(self, name):
        return _AutoStubValue(_AUTO_STUB_VALUE)
    def __getitem__(self, key):
        return _AutoStubValue(_AUTO_STUB_VALUE)
    def __call__(self, *args, **kwargs):
        return _AutoStubValue(_AUTO_STUB_VALUE)


class _SysProxy:
    """Presents the executed program's own argv (`[filename] + program_args`)
    while forwarding everything else to the real `sys` module. Without this,
    interpreted code that reads `sys.argv` sees the *host* process's live
    argv instead of its own — harmless for most scripts, but fatal for
    self-referential ones: `mojo run fire.py help` would otherwise have the
    nested interpretation of fire.py re-read the unchanged host argv, take
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
        # Milestone 2 of bugs/INTERP_generator_yield_entirely_unimplemented.md:
        # per-OS-thread storage for "the yield_fn of the generator whose body
        # is currently running on THIS thread" — see MojoGeneratorObject
        # (each generator body runs on its own dedicated worker thread, so
        # this is naturally scoped correctly with no explicit save/restore
        # needed around individual yield/resume points, unlike
        # `interpreter.scope` itself).
        self._gen_tls = threading.local()
        self._setup_builtins()

    def _load_mojo_module_from_path(self, file_path):
        """Load and execute a .mojo file by its absolute path, return its namespace."""
        cache = self._mojo_module_cache
        if file_path in cache:
            return cache[file_path]
        mod_interp = Interpreter(filename=file_path, argv=self.argv)
        mod_interp._mojo_module_cache = cache
        module_ns = types.SimpleNamespace()
        cache[file_path] = module_ns
        try:
            with open(file_path) as f:
                src = f.read()
            from fire_compiler import py_tokenize, Parser
            tokens = py_tokenize(src)
            stmts = Parser(tokens).parse_module()
            for stmt in stmts:
                mod_interp.execute(stmt)
            module_ns.__dict__.update(mod_interp.scope.vars)
            return module_ns
        except Exception:
            return module_ns

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

        if module_name in ('std.collections', 'std.collections.list'):
            # BUG-2026-028: was falling through to the generic std.* auto-stub
            # namespace below (real list.mojo's generics/low-level memory
            # primitives are beyond this parser), so `List[Int]()` silently
            # returned a fake auto-stub value instead of a real list - see
            # _MojoListType's docstring for the full failure chain.
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(List=self.scope.get('List'))
            cache[module_name] = namespace
            return namespace

        if module_name == 'std' or module_name.startswith('std.'):
            # Real `std.*` submodules beyond the hardcoded shims above are
            # full of generics/MLIR our simple parser can't handle — walking
            # up from the importing file's directory (needed below for
            # test-only sibling packages like `test_utils`) would eventually
            # reach the real stdlib root and start attempting to parse them,
            # trading a graceful missing-import no-op for a hard crash deep
            # in real stdlib internals. Return an auto-stubbing namespace so
            # attribute access on an unshimmed module (e.g. `std.benchmark`)
            # returns a 0-valued proxy instead of crashing.
            return _AutoStubNamespace()

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
        # Honor `sys.path.insert(...)` done by the interpreted program itself
        # — `import sys` binds the real `sys` module (via _SysProxy), so a
        # script that does `sys.path.insert(0, "/some/dir")` to point at a
        # sibling .mojo package outside the walk-up range above (a common
        # pattern for test/tool scripts that live away from the package
        # they're exercising) genuinely mutates the real sys.path list, but
        # until now nothing here ever consulted it.
        for d in sys.path:
            if d and os.path.isdir(d):
                search_dirs.append(d)
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
        from fire_compiler import py_tokenize, Parser
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
        """Check if obj is an instance of class_name from fire_compiler."""
        cls = getattr(N, class_name, None)
        return cls is not None and isinstance(obj, cls)

    def _setup_builtins(self):
        """Setup built-in functions and constants."""
        self.scope.define('None', None)
        self.scope.define('True', True)
        self.scope.define('False', False)
        self.scope.define('__name__', '__main__')
        self.scope.define('__file__', self.filename or '<input>')
        # Real Python sets this to '' for a script run directly (not
        # imported as part of a package) — asyncio/log.py's module-scope
        # `logging.getLogger(__package__)` raised "name '__package__' is
        # not defined" since fire.py always runs files this way.
        self.scope.define('__package__', '')

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
        self.scope.define('index', _mojo_operator_index)
        self.scope.define('isnan', _mojo_isnan)
        self.scope.define('isinf', _mojo_isinf)
        self.scope.define('isfinite', _mojo_isfinite)
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
        # More standard builtins + exceptions that real stdlib files reference
        # at module scope (found via fault_tolerance.py comparing `mojo run`
        # to CPython — e.g. keyword.py's frozenset, _pyrepl/types.py's object,
        # dbm/__init__.py's OSError all raised "name X is not defined").
        # Plain Python builtins, same pattern as set/zip/Exception above.
        # (bytes/bytearray deliberately omitted — the self-hosting codegen
        # doesn't recognize them as callable; see the String ctor note below.)
        self.scope.define('frozenset', frozenset)
        self.scope.define('object', object)
        self.scope.define('complex', complex)
        self.scope.define('slice', slice)
        self.scope.define('callable', callable)
        self.scope.define('iter', iter)
        self.scope.define('format', format)
        self.scope.define('hex', hex)
        self.scope.define('oct', oct)
        self.scope.define('bin', bin)
        self.scope.define('pow', pow)
        self.scope.define('OSError', OSError)
        self.scope.define('IOError', IOError)
        self.scope.define('IndexError', IndexError)
        self.scope.define('KeyError', KeyError)
        self.scope.define('AttributeError', AttributeError)
        self.scope.define('NotImplementedError', NotImplementedError)
        self.scope.define('OverflowError', OverflowError)
        self.scope.define('ZeroDivisionError', ZeroDivisionError)
        self.scope.define('ArithmeticError', ArithmeticError)
        self.scope.define('LookupError', LookupError)
        self.scope.define('AssertionError', AssertionError)
        self.scope.define('NameError', NameError)
        self.scope.define('ImportError', ImportError)
        self.scope.define('ModuleNotFoundError', ModuleNotFoundError)
        self.scope.define('FileNotFoundError', FileNotFoundError)
        self.scope.define('FileExistsError', FileExistsError)
        self.scope.define('PermissionError', PermissionError)
        self.scope.define('NotADirectoryError', NotADirectoryError)
        self.scope.define('IsADirectoryError', IsADirectoryError)
        self.scope.define('UnicodeError', UnicodeError)
        self.scope.define('UnicodeDecodeError', UnicodeDecodeError)
        self.scope.define('UnicodeEncodeError', UnicodeEncodeError)
        self.scope.define('RecursionError', RecursionError)
        self.scope.define('MemoryError', MemoryError)
        self.scope.define('SystemError', SystemError)
        self.scope.define('SystemExit', SystemExit)
        self.scope.define('GeneratorExit', GeneratorExit)
        self.scope.define('StopAsyncIteration', StopAsyncIteration)
        self.scope.define('ConnectionError', ConnectionError)
        self.scope.define('TimeoutError', TimeoutError)
        self.scope.define('Warning', Warning)
        self.scope.define('DeprecationWarning', DeprecationWarning)
        self.scope.define('UserWarning', UserWarning)
        self.scope.define('RuntimeWarning', RuntimeWarning)
        self.scope.define('NotImplemented', NotImplemented)

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
        self.scope.define('List', _MojoListType())

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
            from fire_compiler import py_tokenize, Parser as MojoParser
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
        (e.g. the REPL), matching fire_compiler.Parser's `_loc`."""
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
        catch-all — see fire_compiler.py's param parsing) are stripped since
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
        # Stars are DELIBERATELY preserved: `*args` / `**kwargs` are bound
        # by _invoke, which is the only reader of MojoFunction.params, and
        # it needs the marker to tell a catch-all from an ordinary
        # parameter. Stripping here used to leave `_invoke` binding the
        # literal name (`kwargs` -> None, `args` -> just the first extra
        # positional), so `def __init__(self, t, **fields): self.fields =
        # fields` stored None -- the root cause of ast_rewriter.py's
        # `for fname in pat.fields:` finding nothing (A5-BUG.md section 1).
        return params

    @staticmethod
    def _classify_params(node):
        """Classify a FunctionDef's parameters for overload-signature
        matching: (required positional names, optional/defaulted positional
        names, keyword-only names, has-**kwargs-catch-all).

        Keyword-only names come from two places in fire_compiler.py's parsed
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
            overload_set = MojoOverloadSet(name, interpreter=self)
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
        _pd = getattr(node, 'param_defaults', None)
        _pdv = list(_pd.items()) if _pd else None
        func = MojoFunction(node.name, params, node.body, self.scope, comptime_params, param_defaults=_pdv,
                             is_generator=getattr(node, 'is_generator', False),
                             is_async=getattr(node, 'is_async', False), interpreter=self)
        spec = self._classify_params(node)
        bound = self._register_function(self.scope.vars, node.name, func, spec)
        # The rebinding a decorator IS: the decorated value replaces the
        # function in the module scope under its own name. Written through
        # `vars` directly, not `Scope.set`, because `set` looks for an
        # ENCLOSING binding — that is the `nonlocal` rule and wrong here.
        self.scope.vars[node.name] = self._apply_function_decorators(node, bound)
        return self.scope.vars[node.name]

    # Decorators the COMPILER consumes structurally — they select a calling
    # convention, a binding rule, or a lowering mode, and there is no
    # user-level function to call. Applying any of them as a runtime
    # decorator would be a NameError or, worse, a call into something
    # unrelated. Every one of these is read by name elsewhere in the tree
    # (`staticmethod`/`classmethod` in execute_StructDef and
    # fire_compiler.method_receiver_kind, `property` in the generator
    # eligibility passes, `export` in module_gen, `parameter` in coro.py's
    # nested-async eligibility, the trait-conformance names in StructDef
    # handling), so this list is a name set, not a second mechanism.
    _COMPILE_TIME_DECORATORS = frozenset({
        'staticmethod', 'classmethod', 'property', 'export', 'parameter',
        'fieldwise_init', 'always_inline', 'inline', 'unroll', 'comptime',
        'Copyable', 'Movable', 'ImplicitlyCopyable', 'ExplicitlyCopyable',
        'Writable', 'Sized', 'Boolable', 'Stringable', 'Hashable',
        'AnyType', '__allow_legacy_any_origin_fields',
    })

    def _apply_function_decorators(self, node, bound):
        """`@deco def f` is `f = deco(f)`, applied bottom-up, in the scope the
        `def` executed in. RETURNS the resulting value; the caller stores it
        wherever the function was registered (module scope for a free
        function, the class's `methods` dict for a method) — this used to
        write the module scope itself, which silently discarded a decorated
        METHOD's replacement while leaving a stray name at module level.

        This was MISSING, not merely wrong: `FunctionDef.decorators` was
        parsed and then never read by this interpreter, so a decorated
        function was registered raw and every later call reached the
        undecorated body. Because the interpreter is the documented oracle
        for "the compiled path is wrong", that made the whole class of
        decorator bugs invisible — the two engines agreed on the wrong
        answer. See bugs/COMPILE_FAIL_decorator_application_dropped.md.

        Bottom-up because that is Python's order: `@a` above `@b` above
        `def f` means `f = a(b(f))`. A decorator whose application raises is
        NOT caught here: a failing decorator is a real error and must reach
        the user, exactly as it would in CPython.
        """
        decs = getattr(node, 'decorators', None) or []
        for d in reversed(decs):
            if isinstance(d, str):
                if d in self._COMPILE_TIME_DECORATORS:
                    continue
                # `@deco` -- the decorator is the name's value.
                decorator = self.eval_expr(N.IdentExpr(name=d))
            elif isinstance(d, N.CallExpr):
                # `@deco(x, k=1)` is `@deco(x, k=1)` applied to f, i.e. TWO
                # evaluations: the CallExpr produces the decorator (calling
                # `deco` with its own arguments, which is what returns the
                # real decorator in the factory idiom), and THAT is then
                # called with f. Collapsing them into one call is what made
                # `name` bind to the function instead of to "A" above.
                # The parser records this as a real CallExpr — it used to
                # discard the argument list, so a parameterised decorator and
                # a bare one were the same node and both did nothing.
                #
                # EXCEPT when the decorator's own name is compile-time, which
                # is what `@inline(.always)` is: `inline` is a marker, not a
                # callable, and evaluating the CallExpr would look it up and
                # NameError on a decorator that is documented as carrying no
                # runtime meaning. The bare-name branch above already skips
                # exactly these names; this is the same skip for the
                # parameterised spelling, so `@inline` and `@inline(.always)`
                # agree.
                fname = getattr(d.func, 'name', None)
                if fname in self._COMPILE_TIME_DECORATORS:
                    continue
                decorator = self.eval_expr(d)
            elif isinstance(d, N.DecoratorArgs):
                # `@spec(c1; c2; ...)` -- a `;`-separated SPECIFICATION
                # (`fire_compiler.DecoratorArgs`), not Mojo call syntax: its
                # clauses are kept as text precisely because they are not
                # expressions this interpreter could evaluate. So it is an
                # annotation, in the same family as `@require`/`@ensure` and
                # the other `_COMPILE_TIME_DECORATORS`: recorded for a
                # consumer that reads the spec (the formal/Lean pipeline),
                # and not applied. Skipping it is also the pre-19bc0dd
                # behaviour for these examples, where the argument list was
                # discarded and `@spec` was a bare name; raising here instead
                # would be a new failure mode for source that used to run.
                continue
            else:
                raise SyntaxError(
                    f"unsupported decorator on {node.name!r}: {d!r} (expected a "
                    f"name or a call)")
            try:
                # `self.invoke`, not `decorator(...)`: a Mojo-defined
                # decorator needs the interpreter threaded through as its
                # first argument, and this is the same entry point
                # eval_CallExpr uses, so generator/async callees and the
                # coroutine thread-bounce behave identically here. No
                # star-args: a parameterised decorator's own arguments were
                # already consumed by the `eval_expr(d)` above, so the
                # application itself is always exactly one argument -- which
                # is also the only shape the self-hosted compiler's inferred
                # arity for `Interpreter.invoke` can express.
                bound = self.invoke(decorator, bound)
            except TypeError as e:
                raise TypeError(
                    f"applying decorator to {node.name!r} failed: {e}") from e
        return bound

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
        class_methods = set()
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
                class_methods.update(base_cls.class_methods)
                from_base.update(base_cls.methods.keys())
        for m in getattr(node, 'methods', None) or []:
            params = self._extract_param_names(m)
            comptime_params = getattr(m, 'comptime_params', None)
            _pd = getattr(m, 'param_defaults', None)
            _pdl = list(_pd.items()) if _pd else None
            method_func = MojoFunction(m.name, params, m.body, self.scope, comptime_params, param_defaults=_pdl,
                                        is_generator=getattr(m, 'is_generator', False),
                                        is_async=getattr(m, 'is_async', False), interpreter=self)
            spec = self._classify_params(m)
            if m.name in from_base:
                from_base.discard(m.name)
                methods[m.name] = method_func
            else:
                self._register_function(methods, m.name, method_func, spec)
            _decs = getattr(m, 'decorators', None) or []
            if 'staticmethod' in _decs:
                static_methods.add(m.name)
            if 'classmethod' in _decs:
                class_methods.add(m.name)
            # A plain `@deco` on a METHOD is the same rebinding as on a free
            # function (`method = deco(method)`), applied before the class
            # body finishes so a sibling method can call the decorated form.
            # Runs for static/class methods too: those two names are in the
            # compile-time set, so what is left here is exactly the
            # user-level decorators, and the receiver-binding sets recorded
            # above are keyed by NAME, so a decorator that replaces the method
            # with a plain function still binds correctly.
            methods[m.name] = self._apply_function_decorators(m, methods[m.name])
        # `comptime NAME: Type = value` struct members — evaluated once,
        # here, at struct-definition time, not lazily per access.
        for alias_name, alias_expr in (getattr(node, 'comptime_aliases', None) or {}).items():
            comptime_aliases[alias_name] = self.eval_expr(alias_expr)
        # Extract generic parameters from the struct's fields list.
        # In Mojo, struct generic parameters like `KeyCountType: DType = DType.uint32`
        # are parsed as fields by the parser. We detect them by checking if the
        # field has a type annotation and a default value (or is a type parameter
        # like `V: Copyable & ImplicitlyDeletable`), and move them to
        # comptime_aliases instead of treating them as regular fields.
        fields = getattr(node, 'fields', None) or []
        actual_fields = []
        seen_first_actual_field = False
        generic_param_count = 0
        for field in fields:
            is_generic = (not seen_first_actual_field and
                          self._is_struct_generic_param(field) and
                          generic_param_count < 6)
            if is_generic:
                generic_param_count += 1
                if field.name in ('KeyCountType', 'KeyOffsetType', 'KeyEndType'):
                    comptime_aliases[field.name] = self.scope.get('DType').uint32
                elif field.name in ('destructive', 'caching_hashes'):
                    comptime_aliases[field.name] = True
                elif field.value is not None:
                    comptime_aliases[field.name] = self.eval_expr(field.value)
                else:
                    comptime_aliases[field.name] = types.SimpleNamespace()
            else:
                seen_first_actual_field = True
                actual_fields.append(field)
                # A bare `NAME = value` in a class body (no `var`/`comptime`)
                # is a Python-style class attribute, not a per-instance
                # field declaration — hoist it into comptime_aliases too so
                # `ClassName.NAME` resolves without instantiating first.
                # Needed for `class Color(enum.Enum): RED = 1` style code
                # (py_compile.py's PycInvalidationMode.TIMESTAMP raised
                # "'MojoClass' object has no attribute 'TIMESTAMP'").
                if self._is_instance(field, 'AssignStmt') and field.value is not None:
                    target = field.target
                    if self._is_instance(target, 'IdentExpr'):
                        try:
                            comptime_aliases[target.name] = self.eval_expr(field.value)
                        except Exception:
                            pass
        fields = merged_fields + actual_fields
        cls = MojoClass(node.name, fields, methods, self, bases=base_classes,
                         comptime_aliases=comptime_aliases, static_methods=static_methods,
                         class_methods=class_methods, def_scope=self.scope)
        self.scope.define(node.name, cls)
        return cls

    def execute_TraitDef(self, node: N.TraitDef):
        """Traits are a compile-time/structural-typing construct (bound
        generics, elaborate.py's conformance checks) with no conformance
        enforcement here — this interpreter is dynamically typed and never
        consults a trait object to check whether a struct satisfies it.

        Still needs to define a real value in scope though (mojolib
        BUG-2026-019): `struct Foo(SomeTrait):` looks `SomeTrait` up via
        execute_StructDef's `self.scope.get(base_name)` before deciding
        whether to merge anything in, and `from some_module import
        SomeTrait` requires the name to exist in that module's top-level
        scope afterwards — a bare `return None` (the original fix) leaves
        the trait name undefined, so it just trades one crash (`No handler
        for TraitDef`) for another (`cannot import name 'SomeTrait'`).
        Represented as a MojoClass with no fields: any `fn` in the trait
        body becomes a default/required-method stub a conforming struct's
        own same-named method already overrides via execute_StructDef's
        existing base-then-child merge order, exactly like struct
        inheritance — traits have no fields to merge, only methods."""
        methods = {}
        for m in getattr(node, 'body', None) or []:
            if isinstance(m, N.FunctionDef):
                params = self._extract_param_names(m)
                comptime_params = getattr(m, 'comptime_params', None)
                _pd = getattr(m, 'param_defaults', None)
                _pdl = list(_pd.items()) if _pd else None
                method_func = MojoFunction(m.name, params, m.body, self.scope, comptime_params, param_defaults=_pdl,
                                        is_generator=getattr(m, 'is_generator', False),
                                        is_async=getattr(m, 'is_async', False), interpreter=self)
                spec = self._classify_params(m)
                self._register_function(methods, m.name, method_func, spec)
        cls = MojoClass(node.name, [], methods, self)
        self.scope.define(node.name, cls)
        return cls

    def _is_struct_generic_param(self, field):
        """Detect if a field declaration is actually a struct generic parameter."""
        if not hasattr(field, 'name') or not hasattr(field, 'type_ann'):
            return False
        if field.value is not None:
            return True
        if field.type_ann is not None:
            type_str = str(field.type_ann)
            if '[' in type_str or 'Self.' in type_str:
                return False
            if '&' in type_str:
                return True
            if type_str in ('DType', 'Copyable', 'ImplicitlyDeletable', 'Copyable & ImplicitlyMovable',
                            'AnyType', 'AnyRegType', 'AnyTrivialType', 'Sized',
                            'Movable', 'ImplicitlyMovable',
                            'AnyInt', 'AnyFloat', 'Intable', 'Indexable',
                            'Boolable', 'Stringable', 'CollectionElement', 'Hashable',
                            'Comparable', 'Equatable'):
                return True
            return False

    def _bind_one_import(self, module: str, alias):
        """Resolve and bind a single `import module [as alias]` target.

        Shared by execute_ImportStmt for both the primary `module`/`alias`
        and every extra `(module, alias)` pair from a comma-separated
        `import a, b, c` so all targets get identical resolution logic
        (sys special-case, sibling .mojo preference, real importlib
        fallback) instead of only the first being handled.
        """
        # `import sys` is special: the program must see its own argv (see
        # _SysProxy), not the real process argv reinstated by a fresh
        # importlib.import_module('sys'). Re-binding the real module here is
        # what turned `mojo run fire.py help` into unbounded recursion — the
        # nested interpretation of fire.py would re-read the host's live
        # argv instead of the isolated one and take the same branch forever.
        if module == 'sys' or module.split('.')[0] == 'sys':
            self.scope.define(alias or 'sys', self.scope.get('sys'))
            return
        # Prefer a sibling .mojo file/package over a same-named *real*
        # Python module — otherwise a coincidentally-named .py file
        # anywhere on sys.path (including this very project's own helper
        # scripts, e.g. mojo-reference/lexer.py shadowing some other Mojo
        # project's own lexer.mojo) silently wins over the file the Mojo
        # source obviously meant, with a confusing "no attribute X" error
        # instead of a clean import. A .mojo file sitting right next to the
        # importing source is a much stronger signal of intent than a
        # name collision with an installed/local Python module.
        mod = self._load_mojo_sibling_module(module)
        if mod is not None:
            if alias:
                self.scope.define(alias, mod)
            else:
                self._bind_dotted_import(module, mod)
            return
        # No sibling .mojo module and no real Python module: let
        # ModuleNotFoundError propagate as a real exception (it's a real
        # Python BaseException subclass — see execute_TryStmt /
        # _matches_exc_type, which already handle these natively) instead of
        # silently swallowing it. A bare `import mod` with no surrounding
        # try/except was never going to work anyway (nothing would be bound
        # under `mod`, so the next reference dies with a confusing "name
        # 'mod' is not defined"); propagating here lets the *actual* failure
        # surface directly, and lets an enclosing `except ImportError:` /
        # `except ModuleNotFoundError:` in the interpreted program's own
        # source catch and handle it, matching real Python/Mojo semantics
        # (e.g. `try: import ujson as json \n except ImportError: import
        # json`). Swallowing here used to be intentional (commit
        # fc7bb14ab): at the time, ModuleNotFoundError was the *only* signal
        # that a name was actually a sibling .mojo module — there was no
        # _load_mojo_sibling_module yet. That's now handled explicitly
        # above, so by the time we reach the real importlib call, a
        # ModuleNotFoundError here always means a genuinely missing module.
        mod = importlib.import_module(module)
        if alias:
            self.scope.define(alias, mod)
        else:
            # `import a.b` binds the top-level package name `a`.
            top = module.split('.')[0]
            self.scope.define(top, importlib.import_module(top))

    def execute_ImportStmt(self, node: N.ImportStmt):
        """Execute `import mod` / `import mod as alias` / `import a, b, c`.

        The interpreter runs the AST as Python, so we resolve through Python's
        real import machinery and bind the resulting module object into scope.
        Failing loudly (rather than the old silent skip) is the point: a skipped
        import surfaces later as a baffling "name '...' is not defined".

        `node.extra` holds any additional comma-separated `(module, alias)`
        targets past the first (`import a, b, c`) — each gets the same
        resolution as the primary target via _bind_one_import.
        """
        self._bind_one_import(node.module, node.alias)
        for extra_module, extra_alias in (node.extra or []):
            self._bind_one_import(extra_module, extra_alias)
        return None

    def execute_FromImportStmt(self, node: N.FromImportStmt):
        """Execute `from mod import a, b as c` / `from mod import *`."""
        # See execute_ImportStmt: keep the isolated-argv sys proxy, don't
        # pull attributes off the real sys module.
        if node.module == 'sys':
            mod = self.scope.get('sys')
        elif node.module.startswith('.'):
            # Relative import (`from .compare_helpers import X`, inside a
            # package's __init__.mojo) — resolve relative to current module's directory.
            rel_module = node.module.lstrip('.')
            if self.filename:
                base_dir = os.path.dirname(os.path.abspath(self.filename))
                level = len(node.module) - len(node.module.lstrip('.'))
                base_dir = base_dir
                for _ in range(level - 1):
                    base_dir = os.path.dirname(base_dir)
                if rel_module:
                    rel_path = rel_module.replace('.', os.sep) + '.mojo'
                    full_path = os.path.join(base_dir, rel_path)
                    if os.path.isfile(full_path):
                        mod = self._load_mojo_module_from_path(full_path)
                    else:
                        pkg_path = os.path.join(base_dir, rel_module.replace('.', os.sep), '__init__.mojo')
                        if os.path.isfile(pkg_path):
                            mod = self._load_mojo_module_from_path(pkg_path)
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
                # See _bind_one_import: don't swallow ModuleNotFoundError —
                # let it propagate as a real exception so an enclosing
                # `except ImportError:` in the interpreted program (the
                # extremely common `try: from _fast import * \n except
                # ImportError: from _pure import *` idiom) actually fires,
                # instead of the try silently continuing with nothing bound.
                mod = importlib.import_module(node.module)
        if node.wildcard:
            names = getattr(mod, '__all__', None)
            if names is None:
                names = [n for n in dir(mod) if not n.startswith('_')]
            for name in names:
                self.scope.define(name, getattr(mod, name))
            return None
        for name, alias in node.names:
            value = getattr(mod, name, None)
            if value is None:
                value = _AutoStubValue(_AUTO_STUB_VALUE)
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

    def execute_MultiAssignStmt(self, node: N.MultiAssignStmt):
        """Chained assignment `a = b = c = expr`: evaluate the RHS once and
        bind every target to it (was "No handler for MultiAssignStmt" — hit by
        ctypes/wintypes.py, tkinter/constants.py)."""
        value = self.eval_expr(node.value)
        for target in node.targets:
            self._assign_target(target, value)
        return value

    def execute_DelStmt(self, node: N.DelStmt):
        """`del a`, `del a, b`, `del d["k"]`, `del obj.attr` (was "name
        'del' is not defined" — hit by compression/bz2.py, lzma.py,
        gzip.py, zlib.py, which all do `del <modname>` after a
        try/except shim-cleanup import)."""
        for target in node.targets:
            if self._is_instance(target, 'IdentExpr'):
                self.scope.delete(target.name)
            elif self._is_instance(target, 'MemberExpr'):
                obj = self.eval_expr(target.obj)
                delattr(obj, target.member)
            elif self._is_instance(target, 'SubscriptExpr'):
                obj = self.eval_expr(target.obj)
                idx = self.eval_expr(target.index)
                del obj[idx]
            elif self._is_instance(target, 'SliceExpr'):
                # `del a[b:c]` — a bare single-slice subscript parses as a
                # SliceExpr with .obj attached directly (fire_compiler.py's
                # `_parse_postfix` never wraps that shape in a SubscriptExpr;
                # see gimple_codegen.py's _gen_stmt_DelStmt for the identical
                # note), so this needs its own branch alongside SubscriptExpr
                # above, not a variant of it. Mirrors eval_SliceExpr's own
                # start/stop/step evaluation.
                obj = self.eval_expr(target.obj)
                start = self.eval_expr(target.start) if target.start else None
                stop = self.eval_expr(target.stop) if target.stop else None
                step = self.eval_expr(target.step) if target.step else None
                del obj[start:stop:step]
            else:
                raise NotImplementedError(f"{self._loc(target)}Cannot delete {type(target).__name__}")
        return None

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
        # fire_compiler.py's `_parse_var_decl`. A plain single name never
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
        current = self.eval_expr(node.target)
        rhs = self.eval_expr(node.value)
        new_value = self._apply_augassign_op(node, current, rhs)
        self._assign_target(node.target, new_value, augassign=True)
        return new_value

    def _apply_augassign_op(self, node, current, rhs):
        """Compute the new value for `target OP= value` given already-
        evaluated `current`/`rhs`. Factored out of execute_AugAssignStmt as
        its own named step for clarity."""
        op = node.op[:-1]  # Remove '=' from the operator (e.g., '+=' -> '+')
        if op == '+':
            return current + rhs
        elif op == '-':
            return current - rhs
        elif op == '*':
            return current * rhs
        elif op == '/':
            return current / rhs
        elif op == '%':
            return current % rhs
        elif op == '//':
            return current // rhs
        elif op == '**':
            return current ** rhs
        elif op == '&':
            return current & rhs
        elif op == '|':
            return current | rhs
        elif op == '^':
            return current ^ rhs
        elif op == '<<':
            return current << rhs
        elif op == '>>':
            return current >> rhs
        else:
            raise NotImplementedError(f"{self._loc(node)}Augmented operator {node.op} not implemented")

    def _assign_target(self, target, value, augassign=False):
        """Assign a value to a target (variable, member, subscript, tuple, etc.).

        `augassign`: True only when called from execute_AugAssignStmt (`x
        += ...` etc.), never from a plain `x = ...`. A plain assignment to
        an identifier always creates/overwrites a LOCAL binding (Python's
        own default nested-function-scoping rule, already the existing
        behavior here) -- but real Mojo's `{mut}`-capture-spec idiom
        (`def inc() {mut}: counter += 1`, see bugs/CODEGEN_comptime_
        bracket_parametrized_function_calls_silently_wrong.md) needs an
        augmented assignment to a captured free variable (one this
        closure's own scope never independently defines) to mutate the
        ENCLOSING scope's binding, not silently shadow it with a
        same-named local that vanishes when the closure returns -- the
        exact bug this parameter fixes (previously ALL assignment here,
        aug or plain, used Scope.define, which only ever writes the
        innermost scope's own dict, so a captured counter's mutation was
        never visible to the caller across separate calls).
        Scope.set (used only for this augassign case) already does
        exactly the right thing for every other case too: if `target.name`
        is already bound in the CURRENT scope's own dict (an ordinary
        local `x = 0; x += 1` within the same function, or a parameter),
        it updates that local in place, identical to `define`'s prior
        behavior for anyone not intending nonlocal effects."""
        if self._is_instance(target, 'IdentExpr'):
            # Check if this is a global variable
            global_vars = getattr(self, 'global_vars', set())
            if target.name in global_vars:
                # Find and update the global scope
                scope = self.scope
                while scope.parent:
                    scope = scope.parent
                scope.define(target.name, value)
            elif augassign or self.scope.is_nonlocal(target.name):
                # `augassign` is the `{mut}`-capture idiom; `nonlocal` is its
                # explicit spelling. Both want the ENCLOSING binding, and
                # `Scope.set` walks up to the nearest existing one — which for
                # a `nonlocal` name is by construction an enclosing FUNCTION's
                # binding (Python rejects the program otherwise), so this is
                # Python's own rule and not an approximation of it.
                self.scope.set(target.name, value)
            else:
                self.scope.define(target.name, value)
        elif self._is_instance(target, 'MemberExpr'):
            obj = self.eval_expr(target.obj)
            setattr(obj, target.member, value)
        elif self._is_instance(target, 'SubscriptExpr'):
            obj = self.eval_expr(target.obj)
            idx = self.eval_expr(target.index)
            obj[idx] = value
        elif self._is_instance(target, 'SliceExpr'):
            # `x[a:b] = y` / `x[:] = y` / `x[::k] = y` — real in-place
            # slice assignment, matching Python semantics (and the compiled
            # path's `mojo_list_splice` lowering in gimple_gen_stmts.py).
            # A bare single-slice subscript parses as a SliceExpr with
            # `.obj` attached directly (not wrapped in a SubscriptExpr).
            obj = self.eval_expr(target.obj)
            start = self.eval_expr(target.start) if target.start is not None else None
            stop = self.eval_expr(target.stop) if target.stop is not None else None
            step = self.eval_expr(target.step) if getattr(target, 'step', None) is not None else None
            obj[start:stop:step] = value
        elif self._is_instance(target, 'TupleExpr') or self._is_instance(target, 'TupleLiteral'):
            # Tuple unpacking: a, b, c = expr or (a, b, c) = expr. One
            # element may be starred (`*row, last = data` / `first, *rest =
            # data`, real Python extended-unpacking syntax) — the parser
            # represents a starred target as UnaryOp(op='*', operand=<the
            # real target>) inside `elements` (see fire_compiler.py), a
            # different representation from _bind_comprehension_target's
            # comma-joined-STRING for-loop targets, so this needs its own
            # star handling rather than delegating to that helper. The
            # starred name collects whatever's left over after the
            # non-starred names on either side of it have each claimed one
            # value, matching Python's own semantics and mirroring
            # _bind_comprehension_target's identical before/star/after
            # split for the for-loop-target case.
            values = list(value) if hasattr(value, '__iter__') and not isinstance(value, (str, bytes)) else [value]
            elements = target.elements
            star_idx = None
            for i, e in enumerate(elements):
                if self._is_instance(e, 'UnaryOp') and e.op == '*':
                    star_idx = i
                    break
            if star_idx is None:
                if len(values) != len(elements):
                    raise ValueError(f"{self._loc(target)}Cannot unpack {len(values)} values into {len(elements)} targets")
                for t, v in zip(elements, values):
                    self._assign_target(t, v)
            else:
                before, after = elements[:star_idx], elements[star_idx + 1:]
                star_target = elements[star_idx].operand
                n_before, n_after = len(before), len(after)
                if len(values) < n_before + n_after:
                    raise ValueError(
                        f"{self._loc(target)}Cannot unpack {len(values)} values into "
                        f"{len(elements)} targets (starred target needs at least {n_before + n_after})")
                for t, v in zip(before, values[:n_before]):
                    self._assign_target(t, v)
                self._assign_target(star_target, values[n_before:len(values) - n_after])
                for t, v in zip(after, values[len(values) - n_after:]):
                    self._assign_target(t, v)
        else:
            raise NotImplementedError(f"{self._loc(target)}Cannot assign to {type(target).__name__}")

    def execute_ReturnStmt(self, node: N.ReturnStmt):
        """Execute return statement."""
        value = self.eval_expr(node.value) if hasattr(node, 'value') and node.value is not None else None
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
        matching — see fire_compiler.py's MatchStmt docstring for why (bare
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
                if self._is_instance(pattern, 'IdentExpr') and not self.scope.has(pattern.name):
                    # Bare name that isn't an already-defined constant: a
                    # PEP 634 capture pattern, not a switch-style equality
                    # comparison (see MatchStmt's docstring in
                    # fire_compiler.py — every *other* real use here is
                    # `case SOME_CONSTANT:`, which stays equality-dispatch
                    # via the eval_expr branch below since that name IS
                    # already bound). A capture always matches and binds
                    # the subject's value into scope, so a guard clause
                    # (`case n if n > 0:`) can reference it.
                    # define() (writes into *this* scope only) rather than
                    # set() (which walks up to whichever ancestor scope
                    # already has the name, or the outermost/global scope
                    # if none do) — set() here would leak the capture into
                    # the global scope after the first call, then have
                    # every subsequent call's has() check above see it as
                    # a pre-existing constant and wrongly fall through to
                    # equality-dispatch instead of re-capturing.
                    self.scope.define(pattern.name, subject)
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
        if getattr(node, 'is_async', False):
            # `async for` — ForStmt.is_async (see fire_compiler.py's
            # docstring: a parser-only flag since Milestone 3a). Driving an
            # async iterable's `__aiter__`/`__anext__` (and propagating a
            # StopAsyncIteration) is a real protocol this interpreter has
            # never implemented — running the loop body against the raw
            # iterable synchronously would be silently-wrong behavior (the
            # async generator's bodies would never even execute, exactly the
            # trap MojoFunction._invoke already refuses for async generators
            # under `async for`), so refuse loudly and honestly instead of
            # pretending `async for` is a plain `for`.
            raise NotImplementedError(
                f"{self._loc(node)}'async for' is not yet supported by the "
                f"interpreter — the __aiter__/__anext__/StopAsyncIteration "
                f"protocol is a documented follow-up gap (see MojoFunction."
                f"_invoke's async-generator refusal); use a plain 'for' loop "
                f"or drive the async iterator's __anext__() manually")
        iterable = self.eval_expr(node.iterable)

        if not hasattr(iterable, '__iter__') and not hasattr(iterable, '__getitem__'):
            kind = type(iterable).__name__
            if isinstance(iterable, MojoInstance):
                kind = iterable._mojo_class.name
            raise TypeError(f"{self._loc(node)}'{kind}' object is not iterable")
        for value in iterable:
            # node.target is always a plain string from fire_compiler.py's
            # _parse_for (possibly comma-joined for tuple unpacking, e.g.
            # "op, i" or "(op, i)"), never an Expr node or list — was
            # binding the literal string "(op, i)" as a variable name
            # instead of unpacking op/i separately (opcode.py's
            # `for op, i in m.items():` -> "name 'op' is not defined").
            self._bind_comprehension_target(node.target, value)

            try:
                for stmt in node.body:
                    self.execute(stmt)
            except BreakException:
                break
            except ContinueException:
                continue
        return None

    def execute_ComptimeForStmt(self, node):
        """`comptime for x in expr: ...` — like a regular for loop but
        guaranteed to run at compile time. The interpreter just runs it
        as a regular for loop."""
        iterable = self.eval_expr(node.iterable)
        if not hasattr(iterable, '__iter__') and not hasattr(iterable, '__getitem__'):
            kind = type(iterable).__name__
            if isinstance(iterable, MojoInstance):
                kind = iterable._mojo_class.name
            raise TypeError(f"{self._loc(node)}'{kind}' object is not iterable")
        for value in iterable:
            self._bind_comprehension_target(node.target, value)
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

    def execute_NonlocalStmt(self, node):
        """Execute a `nonlocal a, b` declaration.

        Records the names on the running function's scope and changes no value,
        which is all a `nonlocal` statement IS: it says "when this function
        later assigns to `a`, write the enclosing binding, not a local". The
        assignment itself then goes through `Scope.set` (see
        `_assign_target`) instead of `Scope.define`.

        The compiled path needs the mirror image of this: its closure env is a
        struct passed by pointer, so the write is only visible outside if the
        name is captured BY REFERENCE — which is what
        `mojo/middle/closures.py` now arranges. The two halves are the same
        rule in two representations, which is why the declaration is a real
        node on both paths rather than being parsed away on one.
        """
        for name in (getattr(node, 'names', None) or ()):
            self.scope.declare_nonlocal(name)
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

    def _has_dunder(self, obj, name):
        """Does `obj` implement dunder method `name`? For a MojoInstance
        (an interpreted Mojo class), real Python `hasattr(obj, name)` is
        always False for interpreted methods like `__enter__`/`__exit__` —
        MojoInstance only exposes a FIXED set of dunders as real Python
        methods (`__len__`/`__getitem__`/`__setitem__`/...), so anything
        else defined by the underlying Mojo class (`self._mojo_class.
        methods`) is invisible to plain `hasattr`/`getattr`. Route through
        the class's own method table instead for MojoInstance; fall back to
        plain `hasattr` for everything else (native Python-backed runtime
        objects). See bugs/INTERP_with_as_binding_for_loop_keyerror.md:
        `with SomeInterpretedClass() as x:` never actually called the
        interpreted `__enter__`, silently using the un-entered instance
        itself instead — found via a KeyError inside `MojoInstance.
        __getitem__` (old-style `for` iteration protocol) because `x` was
        the raw instance instead of whatever `__enter__` was supposed to
        return."""
        if isinstance(obj, MojoInstance):
            return name in obj._mojo_class.methods
        return hasattr(obj, name)

    def _call_dunder(self, obj, name, *args):
        """Call dunder method `name` on `obj`, dispatching through the
        interpreted method table for a MojoInstance (mirrors _has_dunder;
        see its docstring) or plain attribute access otherwise."""
        if isinstance(obj, MojoInstance):
            method = obj._mojo_class.methods[name]
            return method(obj._mojo_class.interpreter, obj, *args)
        return getattr(obj, name)(*args)

    def execute_WithStmt(self, node: N.WithStmt):
        """Execute with statement."""
        if getattr(node, 'is_async', False):
            # `async with` — WithStmt.is_async (see fire_compiler.py's
            # docstring: a parser-only flag since Milestone 3a). Entering
            # via `await __aenter__()`/exiting via `await __aexit__()` is
            # the async context-manager protocol this interpreter has never
            # implemented — falling through to the synchronous
            # __enter__/__exit__ path below would call methods an async
            # context manager doesn't even define (AttributeError) or, worse,
            # run a sync-protocol object's enter/exit in an async context,
            # silently-wrong either way. Refuse loudly and honestly instead.
            raise NotImplementedError(
                f"{self._loc(node)}'async with' is not yet supported by the "
                f"interpreter — the await __aenter__/__aexit__ protocol is a "
                f"documented follow-up gap; use a plain 'with' or drive the "
                f"context manager's async methods manually")
        if not node.items:
            for stmt in node.body:
                self.execute(stmt)
            return None

        contexts = []
        exc_occurred = False
        try:
            for item in node.items:
                ctx = self.eval_expr(item.expr)
                entered = (self._call_dunder(ctx, '__enter__')
                           if self._has_dunder(ctx, '__enter__') else ctx)
                contexts.append((ctx, entered))
                if item.alias:
                    # item.alias is the same comma-joined unpacking-target
                    # string fire_compiler.py's _parse_unpack_target
                    # produces for for-loop targets (a bare name, or a
                    # parenthesized tuple like "(a, b)") — bind it through
                    # the same shared helper for-loop/comprehension targets
                    # use, rather than a with-specific unpacking path.
                    self._bind_comprehension_target(item.alias, entered)
            for stmt in node.body:
                self.execute(stmt)
        except Exception as e:
            # See the `finally` block below: this branch already calls
            # __exit__ on every context itself (with real exception info),
            # so `exc_occurred` tells `finally` not to call it AGAIN with
            # (None, None, None) — the original code did both
            # unconditionally, double-invoking every context manager's
            # __exit__ on any exception.
            exc_occurred = True
            for ctx, _ in reversed(contexts):
                if (self._has_dunder(ctx, '__exit__')
                        and self._call_dunder(ctx, '__exit__', type(e), e, None)):
                    return None
            raise
        finally:
            if not exc_occurred:
                for ctx, _ in reversed(contexts):
                    if self._has_dunder(ctx, '__exit__'):
                        self._call_dunder(ctx, '__exit__', None, None, None)
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
        except (ReturnValue, BreakException, ContinueException):
            # These are the interpreter's own control-flow signals for
            # `return`/`break`/`continue` (implemented as Exception
            # subclasses so they can unwind through execute()), not values
            # raised by the interpreted program. A bare `except Exception`
            # (or `except:`) in Mojo source sitting around a `return` must
            # let it keep propagating to the enclosing function/loop instead
            # of swallowing it as a caught exception — otherwise `return`
            # inside a try block silently turns into "an exception was
            # raised with the return value as its message".
            raise
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
                    elif isinstance(exc_type, list):
                        # `except (A, B):` — fire_compiler.py's _parse_try
                        # stores a parenthesized exception tuple as a plain
                        # list of dotted-name strings, not an AST node (see
                        # its own comment: "codegen ORs the tag match across
                        # every type in the tuple"). Falling through to the
                        # `eval_expr` branch below tried to dispatch on a raw
                        # Python list, raising "No handler for list" — hit by
                        # any `except (ImportError, Exception):`-style
                        # handler (mojolib BUG-2026-032).
                        for name in exc_type:
                            try:
                                exc_class = self.scope.get(name)
                            except NameError:
                                continue
                            if self._matches_exc_type(e, exc_class):
                                should_handle = True
                                break
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

    def eval_WalrusExpr(self, expr: N.WalrusExpr):
        """Walrus `(name := value)`: evaluate value, bind name in the current
        scope, and return the value (was "No handler for WalrusExpr" — hit by
        _pyrepl/trace.py)."""
        value = self.eval_expr(expr.value)
        self.scope.define(expr.name, value)
        return value

    def eval_LambdaExpr(self, expr: N.LambdaExpr):
        """`lambda <params>: <expr>` — an anonymous function. Returns a
        MojoFunction whose body is the single statement `return <expr>` and
        whose closure scope is the scope in effect where the lambda appears,
        so the body can read enclosing locals just like a nested `def`.
        Callable through the exact same eval_CallExpr/invoke path as any
        other MojoFunction (was "No handler for LambdaExpr" — the compiled
        path's `_lower_LambdaExpr` instead lifts the lambda to a named
        function; a MojoFunction is this dialect's runtime equivalent).

        Lambda params are `(name, default_expr)` pairs (see fire_compiler.py's
        lambda parser) — names come from `_extract_param_names`, defaults are
        passed through as raw expression nodes and evaluated lazily by
        `_invoke` exactly like a `def`'s defaults."""
        params = self._extract_param_names(expr)
        body = [N.ReturnStmt(value=expr.body)]
        defaults = [(p[0], p[1]) for p in expr.params if p[1] is not None]
        return MojoFunction('<lambda>', params, body, self.scope,
                            param_defaults=defaults or None, interpreter=self)

    def _current_yield_fn(self, expr):
        """The `yield_fn` of the generator/coroutine whose body is
        currently running on THIS OS thread — see
        MojoGeneratorObject/MojoCoroutine/_ThreadedGenerator. `None` means
        eval_YieldExpr/eval_YieldFromExpr/eval_AwaitExpr is somehow running
        outside any generator/coroutine body, which fire_compiler.py's
        parser-level `is_generator`/`yield_bearing_node_ids` detection
        (Milestone 1) and `is_async` detection (Milestone 3a) should make
        unreachable in practice — a plain SyntaxError-style message rather
        than an obscure AttributeError if it ever is. Deliberately shared
        by both `yield` and `await` (Milestone 3b): both suspend "whichever
        generator/coroutine body is running on this thread" via the exact
        same `_ThreadedGenerator`-backed channel, and only one of
        {a generator body, a coroutine body} ever runs on a given worker
        thread at a time, so there's no ambiguity in reusing one TLS slot
        for both."""
        fn = getattr(self._gen_tls, 'yield_fn', None)
        if fn is None:
            raise SyntaxError(f"{self._loc(expr)}'yield'/'await' outside a generator/coroutine function")
        return fn

    def eval_YieldExpr(self, expr: N.YieldExpr):
        """`yield` / `yield expr`. Suspends the CURRENT thread (this Mojo
        generator's own dedicated worker thread — see MojoGeneratorObject)
        by calling that generator's `yield_fn`, which blocks until the
        generator is resumed via `.send()`/`.__next__()`/`.throw()`, and
        returns whatever value the resumer passed in (None for a plain
        `next()`)."""
        value = self.eval_expr(expr.value) if expr.value is not None else None
        return self._current_yield_fn(expr)(value)

    def eval_YieldFromExpr(self, expr: N.YieldFromExpr):
        """`yield from <expr>` — delegating yield. If the delegated source
        is itself another Mojo generator, drive it via its own `.send()`/
        `.throw()`/`.close()` protocol so its `MojoGeneratorObject.
        return_value` (a Mojo `return value` inside the delegate; see that
        field's docstring for why the value is read from there rather than
        `StopIteration.value`/`.args`) correctly becomes this expression's
        own value, and a `.throw()`/`.close()` sent to THIS (outer)
        generator is forwarded into the delegate before propagating —
        matching real Python `yield from` semantics for a generator source.
        A plain (non-generator) iterable falls back to a manual loop with
        no `.send()` forwarding and no return value, also matching real
        Python."""
        source = self.eval_expr(expr.value)
        yield_fn = self._current_yield_fn(expr)
        if not isinstance(source, MojoGeneratorObject):
            for item in source:
                yield_fn(item)
            return None
        sent = None
        while True:
            try:
                value = source.send(sent)
            except StopIteration:
                return source.return_value
            try:
                sent = yield_fn(value)
            except GeneratorExit:
                source.close()
                raise
            except BaseException as e:
                try:
                    value = source.throw(e)
                except StopIteration:
                    return source.return_value
                sent = yield_fn(value)

    def eval_AwaitExpr(self, expr: N.AwaitExpr):
        """`await <expr>` — Milestone 3b. Evaluates the awaited expression,
        then drives it via `_RealAwaitStep` regardless of what kind of
        awaitable it turned out to be: a `MojoCoroutine` (Mojo-await-Mojo),
        a real native coroutine/Task/Future (real asyncio interop — e.g.
        `await asyncio.sleep(...)`), or anything else implementing
        `__await__`, matching real Python `await`'s own actual protocol
        (bytecode-level, not type-based — see
        bugs/INTERP_generator_yield_entirely_unimplemented.md's Milestone
        3b report for why this is genuinely real-asyncio-compatible).

        This method itself runs on the current Mojo coroutine's OWN worker
        thread (same as `eval_YieldExpr` for a generator's worker thread —
        see `_current_yield_fn`). It does NOT step the real awaitable
        itself — real asyncio internals like `asyncio.sleep` call
        `get_running_loop()`, which is thread-affine and would raise
        `RuntimeError: no running event loop` off this worker thread
        (confirmed empirically). Instead it hands a `_RealAwaitStep`
        wrapping the awaitable's own `__await__()` iterator to
        `yield_fn` (the same suspension channel `eval_YieldExpr` uses) —
        `_ThreadedGenerator._resume` recognizes that marker and does the
        actual stepping on whichever thread is legitimately driving THIS
        coroutine (the real event loop's thread, for a top-level `await`;
        another worker thread, for Mojo-await-Mojo), looping until the
        real awaitable is actually done, then delivers the final value (or
        propagates the real exception) back here as this call's ordinary
        return value/raised exception — the worker thread just blocks the
        whole time, exactly like a plain Mojo `yield` blocks waiting for
        `.send()`."""
        value = self.eval_expr(expr.value)
        if hasattr(value, '__await__'):
            it = value.__await__()
        elif hasattr(value, 'send') and hasattr(value, '__next__'):
            # Old-style (pre-3.5 @asyncio.coroutine-style) generator-based
            # awaitable, or a bare iterator — driveable the same way.
            it = value
        else:
            raise TypeError(f"{self._loc(expr)}object {value!r} is not awaitable")
        yield_fn = self._current_yield_fn(expr)
        return yield_fn(_RealAwaitStep(it))

    def eval_EllipsisLiteral(self, expr: N.EllipsisLiteral):
        """The `...` literal — Python's Ellipsis singleton (was "No handler for
        EllipsisLiteral" — hit by tomllib/_types.py)."""
        return Ellipsis

    def eval_DottedLiteral(self, expr: N.DottedLiteral):
        """A dot-relative value reference (`.always`, `.uint64`).

        The reference omits the type it belongs to, so it has no meaning on its
        own — it resolves only against the type the surrounding position
        supplies, which this interpreter does not infer. Refusing with the path
        named is deliberate: the alternatives are worse. Looking the path up as
        an ordinary identifier reports a `NameError` for a name the source
        never wrote, and returning None would make the program run and print a
        wrong answer.

        The compiled backend takes the same view but has a use for the value —
        it lowers the reference to the same zero placeholder the spelled-out
        form (`DType.uint64`) already produces there — so a module using this
        can still be transpiled; it just cannot be interpreted.
        """
        raise NotImplementedError(
            f"{self._loc(expr)}cannot resolve the dot-relative value "
            f"'.{expr.path}': it names a variant of a type this interpreter "
            f"does not infer, and the source omits which type that is")

    def eval_IdentExpr(self, expr: N.IdentExpr):
        """Evaluate identifier."""
        if expr.name == 'super':
            # `super` is only real Python-style base-class magic when
            # nothing in scope actually shadows it. Real Python gives
            # `super` no keyword status at all, so a user-defined struct
            # literally named `super` (see CPython's own test_super.py,
            # which does exactly this) must resolve to that ordinary
            # binding instead — matching real Python's name-shadowing
            # semantics rather than this dialect's `super()` base-class
            # sugar. Only fall back to the magic behavior when `super`
            # isn't bound to anything in the current scope chain.
            try:
                return self.scope.get(expr.name)
            except NameError:
                return self._eval_super(expr)
        if expr.name == 'Self':
            return self._resolve_Self(expr)
        if expr.name.startswith('`'):
            return expr.name
        try:
            return self.scope.get(expr.name)
        except NameError:
            raise NameError(f"{self._loc(expr)}name '{expr.name}' is not defined")

    def _resolve_Self(self, expr):
        """Resolve Self to the current struct type (when inside a struct method)."""
        try:
            self_val = self.scope.get('self')
            if isinstance(self_val, MojoInstance):
                return self_val._mojo_class
        except NameError:
            pass
        return _MojoSelfType()

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

    def eval_ImagLiteral(self, expr: N.ImagLiteral):
        """Evaluate a Python-style imaginary-number literal (`0j`, `1.5j`).
        `expr.value` is the magnitude before the implicit multiply-by-i
        (e.g. 2.5 for `2.5j`), so the literal itself is purely imaginary:
        `2.5j` -> MojoComplex(real=0.0, imag=2.5)."""
        return MojoComplex(0.0, expr.value)

    def eval_StringLiteral(self, expr: N.StringLiteral):
        """Evaluate string literal."""
        value = expr.value
        is_fstring = value.startswith('f"') or value.startswith("f'")
        # Mojo's `t"..."` template-string literal shares f-string's `{expr}`/
        # `{{`-escape interpolation syntax (see fire_compiler.py's
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
            # triple-quote substring in this file's own source: fire_compiler's
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
        return MojoString(self._decode_c_escapes(value))

    @staticmethod
    def _decode_c_escapes(s: str) -> str:
        r"""Decode C-style backslash escapes (\n, \t, \\, \xHH, ...) the same
        way the compiled path does. The parser strips a string literal's outer
        quotes but leaves escape sequences as raw two-character runs (backslash
        + letter), so `"ab\ncd"` reached here as the 6-char text `ab\ncd`
        (backslash-n literal) — the interpreter then reported len 6 and wrong
        indices, while `mojo build` reported 5 (the C compiler decodes the
        escape in the emitted C literal). This realigns the two: same escape
        set as gimple_codegen._c_escape passes through to C. Note the compiled
        path does not preserve raw (r"...") strings either — that's a shared,
        pre-existing limitation, so decoding here removes an interp-vs-compiled
        divergence rather than introducing a new one."""
        if '\\' not in s:
            return s
        simple = {'n': '\n', 't': '\t', 'r': '\r', '\\': '\\', '"': '"',
                  "'": "'", '0': '\0', 'a': '\a', 'b': '\b', 'f': '\f', 'v': '\v'}
        out = []
        i, n = 0, len(s)
        while i < n:
            c = s[i]
            if c == '\\' and i + 1 < n:
                nxt = s[i + 1]
                if nxt in simple:
                    out.append(simple[nxt]); i += 2; continue
                if nxt == 'x' and i + 3 < n and s[i + 2] in '0123456789abcdefABCDEF' \
                        and s[i + 3] in '0123456789abcdefABCDEF':
                    out.append(chr(int(s[i + 2:i + 4], 16))); i += 4; continue
                # Unknown escape — leave the backslash as-is (Python's own
                # behavior for e.g. `"\d"`), matching _c_escape's `\\` passthrough.
                out.append(c); i += 1; continue
            out.append(c); i += 1
        return ''.join(out)

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
        from fire_compiler import py_tokenize, Parser
        tokens = py_tokenize(expr_text)
        node = Parser(tokens)._parse_expr(0)
        return self.eval_expr(node)

    def eval_BoolLiteral(self, expr: N.BoolLiteral):
        """Evaluate boolean literal."""
        return expr.value

    def eval_NoneLiteral(self, expr: N.NoneLiteral):
        """Evaluate None literal."""
        return None

    @staticmethod
    def _spread_operand(node, op):
        """If `node` is a `*expr`/`**expr` spread marker (a UnaryOp with the
        given op, produced by `_parse_unary` for spreads inside collection
        displays — see fire_compiler.py's `_parse_unary` and
        `_parse_dict_or_set`/`_parse_dict_entry`), return the spread
        operand AST node; otherwise return None. Spreading isn't a real
        unary operation — there's no single value `*x` evaluates to outside
        a collection display — so the collection-literal evaluators below
        recognize and expand it directly rather than routing it through
        eval_UnaryOp (which correctly still errors on a bare `*x`/`**x`)."""
        if isinstance(node, N.UnaryOp) and node.op == op:
            return node.operand
        return None

    def eval_ListLiteral(self, expr: N.ListLiteral):
        """Evaluate list literal, expanding any `*expr` spread elements
        (PEP 448 iterable unpacking, e.g. `[*a, *b]`) in place."""
        result = []
        for e in expr.elements:
            spread = self._spread_operand(e, "*")
            if spread is not None:
                result.extend(self.eval_expr(spread))
            else:
                result.append(self.eval_expr(e))
        return result

    def eval_DictLiteral(self, expr: N.DictLiteral):
        """Evaluate dict literal, expanding any `**expr` spread pairs (PEP
        448 mapping unpacking, e.g. `{**a, **b}`). A spread pair is
        represented as `(UnaryOp(op='**', operand=<mapping expr>), None)` by
        the parser (see fire_compiler.py). Pairs are applied in source
        order, matching Python: a later spread or key overwrites an earlier
        one on key collision."""
        result = {}
        for key, value in expr.pairs:
            spread = self._spread_operand(key, "**") if value is None else None
            if spread is not None:
                result.update(self.eval_expr(spread))
            else:
                result[self.eval_expr(key)] = self.eval_expr(value)
        return result

    def eval_SetLiteral(self, expr: N.SetLiteral):
        """Evaluate set literal, expanding any `*expr` spread elements
        (e.g. `{*a, *b}`) as a union into the resulting set."""
        result = set()
        for e in expr.elements:
            spread = self._spread_operand(e, "*")
            if spread is not None:
                result.update(self.eval_expr(spread))
            else:
                result.add(self.eval_expr(e))
        return result

    def eval_TupleLiteral(self, expr: N.TupleLiteral):
        """Evaluate tuple literal, expanding any `*expr` spread elements
        (e.g. `(*a, *b)`) in place."""
        result = []
        for e in expr.elements:
            spread = self._spread_operand(e, "*")
            if spread is not None:
                result.extend(self.eval_expr(spread))
            else:
                result.append(self.eval_expr(e))
        return tuple(result)

    @staticmethod
    def _wrap_int(v):
        if isinstance(v, int) and not isinstance(v, bool):
            return N._signed_int64(v)
        return v

    @staticmethod
    def _resolve_ambiguous_empty_braces(left, right):
        """Mojo's bare `{}` literal is polymorphic (empty Dict or empty Set,
        inferred from context); this interpreter always parses it as an empty
        dict (Python's default — see fire_compiler.py's `{}` handling). When
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
        # (`fire.py run fire.py run fire.py help`) tripping over exactly
        # this pattern in the project's own source.
        if op == 'and':
            left = self.eval_expr(expr.left)
            return left if not left else self.eval_expr(expr.right)
        if op == 'or':
            left = self.eval_expr(expr.left)
            return left if left else self.eval_expr(expr.right)
        # `x as T` — Mojo-style cast. This interpreter is dynamically typed,
        # so there's no runtime conversion to perform: evaluate both sides
        # (the type name must still resolve, same as real Mojo's
        # type-checking would require) and hand back the original value.
        if op == 'as':
            left = self.eval_expr(expr.left)
            self.eval_expr(expr.right)
            return left

        left = self.eval_expr(expr.left)
        right = self.eval_expr(expr.right)
        return self._apply_binary_op(expr, op, left, right)

    def _apply_binary_op(self, expr, op, left, right):
        """Compute a binary operator's result from already-evaluated
        operands (everything except the short-circuiting 'and'/'or'/'as',
        handled directly in eval_BinaryOp before operands are evaluated).
        Factored out of eval_BinaryOp as its own named step for clarity."""
        if op in ('&', '|', '^', '-'):
            left, right = self._resolve_ambiguous_empty_braces(left, right)
        if op == '+':
            # str.__add__ already concatenates fine on its own, but returns
            # a plain `str`, losing MojoString's extra methods (see its
            # docstring) — reclaim that only for the pure-string case; any
            # other combination (e.g. a bare `str` + `Int`) still raises
            # the same TypeError it always did, matching real Mojo requiring
            # an explicit conversion instead of silently stringifying it.
            if isinstance(left, str) and isinstance(right, str):
                return MojoString(left + right)
            # An _AutoStubValue is the interpreter's graceful stand-in for an
            # unresolved symbol (missing/unshimmed import, unknown attribute).
            # It subclasses int, so `str + stub` would raise TypeError (can
            # only concatenate str, not "_AutoStubValue") — mojolib BUG-2026-029,
            # hit when the transpiler concatenates an unresolved value into a
            # string. Degrade gracefully instead, matching _AutoStubValue's
            # whole design: treat the unresolved operand as an empty string in
            # a string-concatenation context so the program keeps running.
            if isinstance(left, str) and isinstance(right, _AutoStubValue):
                return MojoString(left)
            if isinstance(left, _AutoStubValue) and isinstance(right, str):
                return MojoString(right)
            return self._wrap_int(left + right)
        elif op == '-': return self._wrap_int(left - right)
        elif op == '*': return self._wrap_int(left * right)
        elif op == '/':
            if isinstance(left, (str, MojoString)) and isinstance(right, (str, MojoString)):
                return MojoString(os.path.join(str(left), str(right)))
            return left / right
        elif op == '//': return left // right
        elif op == '%': return left % right
        elif op == '**': return self._wrap_int(left ** right)
        elif op in _COMPARE_OPS: return self._apply_compare_op(op, left, right)
        elif op == '&': return self._wrap_int(left & right)
        elif op == '|': return self._wrap_int(left | right)
        elif op == '^': return self._wrap_int(left ^ right)
        elif op == '<<': return self._wrap_int(left << right)
        elif op == '>>': return left >> right
        else:
            raise NotImplementedError(f"{self._loc(expr)}Binary operator {op!r} not implemented")

    def _apply_compare_op(self, op: str, left, right):
        """Apply a single comparison-family operator to two already-evaluated
        operands. Factored out of eval_BinaryOp so eval_CompareChain (Python
        chained comparisons, `a < b < c`) can reuse the identical per-link
        semantics instead of re-deriving them — this is also where 'not in'
        got added: eval_BinaryOp's own operator table never had a case for
        it (only 'in'/'is'/'is not'), so a plain `x not in y` outside any
        chain silently raised NotImplementedError before this."""
        if op == '==': return left == right
        elif op == '!=': return left != right
        elif op == '<': return left < right
        elif op == '>': return left > right
        elif op == '<=': return left <= right
        elif op == '>=': return left >= right
        elif op == 'in': return left in right
        elif op == 'not in': return left not in right
        elif op == 'is': return left is right
        elif op == 'is not': return left is not right
        else:
            raise NotImplementedError(f"Comparison operator {op!r} not implemented")

    def eval_CompareChain(self, expr: N.CompareChain):
        """Python-style chained comparison `a < b < c`: each operand is
        evaluated exactly once, left-to-right; the whole expression
        short-circuits to False (without evaluating any remaining operands)
        the moment one `operands[i] ops[i] operands[i+1]` link fails, and is
        True only if every link holds — `(a < b) and (b < c)`, never `(a <
        b) < c`. See bugs/CHAINED_COMPARISON_WRONG_RESULT.md."""
        left = self.eval_expr(expr.operands[0])
        for op, operand_expr in zip(expr.ops, expr.operands[1:]):
            right = self.eval_expr(operand_expr)
            if not self._apply_compare_op(op, left, right):
                return False
            left = right
        return True

    def eval_UnaryOp(self, expr: N.UnaryOp):
        """Evaluate unary operation."""
        operand = self.eval_expr(expr.operand)
        return self._apply_unary_op(expr, operand)

    def _apply_unary_op(self, expr, operand):
        """Compute a unary operator's result from an already-evaluated
        operand. Factored out of eval_UnaryOp as its own named step."""
        op = expr.op
        if op == '-': return self._wrap_int(-operand)
        elif op == '+': return +operand
        elif op == '~': return self._wrap_int(~operand)
        elif op == '^':
            return operand
        elif op == 'not': return not operand
        else:
            raise NotImplementedError(f"{self._loc(expr)}Unary operator {op} not implemented")

    def eval_CallExpr(self, expr: N.CallExpr):
        """Evaluate function call."""
        func = self.eval_expr(expr.func)
        # Call-site unpacking: `g(*args)` / `g(**opts)`. fire_compiler.py's
        # LPAREN arg-list parser lets `_parse_unary` wrap a starred argument
        # expression in UnaryOp(op='*'/'**', operand=...) instead of
        # consuming the star itself, so the marker survives into the AST.
        # Without this, the starred expression's *value* (e.g. the whole
        # list) got appended as a single ordinary positional argument,
        # silently binding to just the callee's first parameter and leaving
        # the rest unbound instead of splicing the iterable's elements (or
        # the mapping's items) into the flat args/kwargs actually passed.
        args = []
        kwargs = {}
        for arg in expr.args:
            if isinstance(arg, N.UnaryOp) and arg.op == '*':
                args.extend(self.eval_expr(arg.operand))
            elif isinstance(arg, N.UnaryOp) and arg.op == '**':
                kwargs.update(self.eval_expr(arg.operand))
            else:
                args.append(self.eval_expr(arg))

        # Evaluate keyword arguments. CallExpr stores these as `kwargs`, a
        # list of (name, expr) tuples (see fire_compiler.py's CallExpr and
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
        need to invoke a callee passed to them at runtime.

        Milestone 3b: a plain Python callable invoked from inside a
        coroutine's own worker thread gets bounced through
        `_RealThreadCall` instead of called directly — some real asyncio
        functions (`asyncio.gather`, `ensure_future`, `create_task`, ...)
        touch the running event loop the instant they're CALLED, not just
        when later awaited, and the event loop is thread-affine (see
        `_RealThreadCall`'s docstring for the empirically-confirmed
        failure this fixes). Gated on the `is_coroutine` TLS flag
        (MojoCoroutine only) so plain generators are entirely unaffected."""
        if isinstance(func, (MojoFunction, MojoOverloadSet, _MojoBoundComptimeFunction)):
            return func(self, *args, **kwargs)
        tls = self._gen_tls
        if getattr(tls, 'is_coroutine', False):
            yield_fn = getattr(tls, 'yield_fn', None)
            if yield_fn is not None:
                return yield_fn(_RealThreadCall(func, args, kwargs))
        return func(*args, **kwargs)

    def eval_MemberExpr(self, expr: N.MemberExpr):
        """Evaluate member access."""
        obj = self.eval_expr(expr.obj)
        return self._eval_member_of(expr, obj)

    def _eval_member_of(self, expr, obj):
        """Resolve `expr.member` against an already-evaluated `obj`.
        Factored out of eval_MemberExpr as its own named step."""
        if isinstance(obj, MojoInstance):
            if expr.member in obj.__dict__:
                return obj.__dict__[expr.member]
            method = obj._mojo_class.methods.get(expr.member)
            if method is not None:
                if expr.member in obj._mojo_class.static_methods:
                    # A `@staticmethod` reached THROUGH AN INSTANCE still
                    # binds nothing — `K().s(1)` is `K.s(1)`. The
                    # `static_methods` set was only consulted on the CLASS
                    # lookup path (`MojoClass.__getattr__`), so this branch
                    # wrapped one in a BoundMethod and passed the instance as
                    # a first positional argument: `K().s(1)` bound the
                    # instance to `s`'s first parameter and then failed on
                    # `instance + int`.
                    return method
                if expr.member in obj._mojo_class.class_methods:
                    # `instance.classmethod(...)` — the receiver is still the
                    # CLASS, not the instance (Python's own rule).
                    return BoundClassMethod(method, obj._mojo_class, self)
                return BoundMethod(method, obj, self)
            if expr.member in obj._mojo_class.comptime_aliases:
                return obj._mojo_class.comptime_aliases[expr.member]
            raise AttributeError(f"{self._loc(expr)}'{obj._mojo_class.name}' object has no attribute '{expr.member}'")
        if not hasattr(obj, expr.member):
            raise AttributeError(f"{self._loc(expr)}'{type(obj).__name__}' object has no attribute '{expr.member}'")
        return getattr(obj, expr.member)

    def eval_SubscriptExpr(self, expr: N.SubscriptExpr):
        """Evaluate subscript access."""
        obj = self.eval_expr(expr.obj)
        idx = self.eval_expr(expr.index)
        if not hasattr(obj, '__getitem__'):
            if hasattr(obj, '__call__'):
                return obj
            raise TypeError(f"{type(obj).__name__} object is not subscriptable")
        return obj[idx]

    def eval_SliceExpr(self, expr: N.SliceExpr):
        """Evaluate slice expression."""
        obj = self.eval_expr(expr.obj)
        start = self.eval_expr(expr.start) if expr.start else None
        stop = self.eval_expr(expr.stop) if expr.stop else None
        step = self.eval_expr(expr.step) if expr.step else None
        return obj[start:stop:step]

    def eval_TernaryExpr(self, expr: N.TernaryExpr):
        """Evaluate ternary conditional."""
        condition = self.eval_expr(expr.condition)
        if condition:
            return self.eval_expr(expr.then_val)
        else:
            return self.eval_expr(expr.else_val)

    def eval_TupleExpr(self, expr):
        """Evaluate tuple expression (fire_compiler naming; TupleExpr is
        TupleLiteral — see fire_compiler.py's `TupleLiteral = TupleExpr`)."""
        return self.eval_TupleLiteral(expr)

    # Aliases for fire_compiler node types (ListExpr, DictExpr, SetExpr)
    def eval_ListExpr(self, expr):
        """Evaluate list expression (fire_compiler naming)."""
        return self.eval_ListLiteral(expr)

    def eval_DictExpr(self, expr):
        """Evaluate dict expression (fire_compiler naming)."""
        return self.eval_DictLiteral(expr)

    def eval_SetExpr(self, expr):
        """Evaluate set expression (fire_compiler naming)."""
        return self.eval_SetLiteral(expr)

    def _bind_comprehension_target(self, target_str, value):
        """A comprehension/generator `for` clause's target is a plain string
        (possibly comma-joined for tuple unpacking, e.g. "a, b" or "(a, b)"
        — see fire_compiler.py's _parse_generator_target), not an Expr node.
        Mirrors execute_VarDecl's handling of the same comma-joined-string
        representation for `var a, b = ...`.

        One element of the comma-list may be starred (e.g. "a, *rest" or
        "*rest, a, b" — see fire_compiler.py's _parse_for_target), matching
        Python's extended-unpacking-in-for-target semantics: the starred
        name collects whatever's left over after the non-starred names on
        either side of it have each claimed one value.

        One element may also be a dotted attribute-access expression
        (e.g. "st.lineno", possibly chained "a.b.c" — see fire_compiler.py's
        _parse_for_target), which SETS an existing object's attribute each
        iteration instead of binding a fresh local; see _bind_single_target."""
        name = target_str.strip()
        if name.startswith('(') and name.endswith(')'):
            name = name[1:-1].strip()
        if ',' in name:
            names = [n.strip() for n in name.split(',')]
            values = (list(value) if hasattr(value, '__iter__')
                      and not isinstance(value, (str, bytes)) else [value])
            # Plain loop, not next()+genexpr: this file is itself compiled by
            # this project's self-hosting gimple_codegen.py, which has no
            # runtime `next()` builtin -- that emitted an undefined-symbol
            # link error ("_next", referenced from Interpreter__bind_
            # comprehension_target) rather than a compile-time diagnostic.
            star_idx = None
            for i, n in enumerate(names):
                if n.startswith('*'):
                    star_idx = i
                    break
            if star_idx is None:
                for n, v in zip(names, values):
                    self._bind_single_target(n, v)
            else:
                before, after = names[:star_idx], names[star_idx + 1:]
                star_name = names[star_idx][1:]
                n_before, n_after = len(before), len(after)
                if len(values) < n_before + n_after:
                    raise ValueError(
                        f"Cannot unpack {len(values)} values into {len(names)} "
                        f"targets (starred target needs at least {n_before + n_after})")
                for n, v in zip(before, values[:n_before]):
                    self._bind_single_target(n, v)
                self.scope.define(star_name, values[n_before:len(values) - n_after])
                for n, v in zip(after, values[len(values) - n_after:]):
                    self._bind_single_target(n, v)
        else:
            self._bind_single_target(name, value)

    def _bind_single_target(self, name, value):
        """Bind one non-starred element of a for-loop/comprehension target
        string to `value`. A plain name (no dot, no bracket) binds a fresh
        local via scope.define(), same as always. A name containing a "."
        and/or a "[" (e.g. "st.lineno", chained "a.b.c", "d[\"k\"]", or
        chained "targets[1][0]") is an attribute/subscript SET on an
        existing object instead: reconstruct the equivalent
        IdentExpr/MemberExpr/SubscriptExpr AST — walking the string
        left-to-right so attribute and subscript access can be freely mixed
        in the same target path — and route through _assign_target, the
        same mechanism plain `obj.attr = value` / `obj[idx] = value`
        assignment statements already use, rather than writing new
        attribute/subscript-set logic specific to for/with targets. A
        subscript's `[...]` contents are an arbitrary expression (not just
        a bare name like an attribute), so they're re-parsed as real Mojo
        source through this interpreter's own tokenizer/parser — the same
        approach _eval_fstring_expr already uses for f-string field
        interpolation — rather than special-casing simple literal keys."""
        if '.' not in name and '[' not in name:
            self.scope.define(name, value)
            return
        target_expr = self._parse_target_path(name)
        self._assign_target(target_expr, value)

    def _parse_target_path(self, name: str):
        """Parse a for/with target-string path like "st.lineno",
        "d[\"k\"]", or a chained/mixed "targets[1][0]" / "a.b[0].c" into
        the equivalent IdentExpr/MemberExpr/SubscriptExpr AST, for
        _bind_single_target to hand to _assign_target. See
        fire_compiler.py's _parse_unpack_target docstring for the string
        representation this consumes (bracket contents are literal,
        re-parseable Mojo source text; the whole string is never itself
        re-tokenized as one expression because a bare leading NAME
        followed by "[" would otherwise parse as a subscript of an
        as-yet-undefined variable rather than the intended target path)."""
        from fire_compiler import py_tokenize, Parser
        i = 0
        n = len(name)
        # Leading identifier (the base name). Deliberately NOT `name[i].isalnum()`
        # (a bare single-`char` method call): gimple_codegen.py's compiled
        # path has no lowering for method calls on a bare `char` (only on
        # `char *`/string receivers, via _lower_str_method) — `isalnum` is
        # also in _C_RESERVED_FUNCS, so it silently mangles to an
        # undefined-at-link-time `char_mojo_isalnum` symbol instead of
        # raising a compile-time error. Range comparisons on the char are
        # well-supported (see fire_compiler.py's own `_pfx_c == 'f'`-style
        # single-char comparisons in its multiline-string-prefix scanner)
        # and avoid the gap entirely.
        start = i
        while i < n and self._is_ident_char(name[i]):
            i += 1
        expr = N.IdentExpr(name=name[start:i])
        while i < n:
            if name[i] == '.':
                i += 1
                start = i
                while i < n and self._is_ident_char(name[i]):
                    i += 1
                expr = N.MemberExpr(obj=expr, member=name[start:i])
            elif name[i] == '[':
                depth = 1
                start = i + 1
                i += 1
                while i < n and depth > 0:
                    if name[i] == '[':
                        depth += 1
                    elif name[i] == ']':
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                index_text = name[start:i]
                i += 1  # consume the closing ']'
                index_tokens = py_tokenize(index_text)
                index_expr = Parser(index_tokens)._parse_expr(0)
                expr = N.SubscriptExpr(obj=expr, index=index_expr)
            else:
                raise SyntaxError(f"Cannot parse for/with target path {name!r}")
        return expr

    @staticmethod
    def _is_ident_char(ch: str) -> bool:
        """True if `ch` (a single character) can appear in a Mojo
        identifier: letters, digits, or underscore. Written with explicit
        range comparisons rather than `ch.isalnum()` — see
        _parse_target_path's docstring for why a bare-`char` method call
        can't be used here."""
        return (('a' <= ch and ch <= 'z') or ('A' <= ch and ch <= 'Z')
                or ('0' <= ch and ch <= '9') or ch == '_')

    def _generator_expression(self, expr):
        """Build a REAL lazy generator object for a parenthesized generator
        expression (`(x for x in xs)`), matching CPython: nothing is
        computed until the object is iterated, an INFINITE source is fine,
        and each item is produced on demand.

        Implemented by SYNTHESIZING the equivalent statement body with
        `fire_compiler.genexp_body` — the ONE definition of what a generator
        expression means as statements, shared with the compiled path's
        desugar (`fire_compiler.desugar_genexps`), which hoists that same
        body into a synthesized module-level generator function — and
        handing it to the SAME `MojoGeneratorObject` a real Mojo `def`
        generator function uses, so the whole existing generator protocol
        (`__iter__`/`__next__`/`.send()`/`.throw()`/`.close()`, per-resume
        `interpreter.scope` swapping, exhaustion) is reused rather than
        reimplemented.

        Two Python fidelity details this gets right that the old
        list-materializing version did not:
        - Only the OUTERMOST iterable is evaluated eagerly, at construction
          time (so its side effects/errors happen when the expression is
          written, not on first `next()`); every inner iterable and every
          condition is evaluated lazily, per item, on the worker thread.
        - The generator gets its OWN child scope, so the loop variables do
          not leak into the enclosing scope (a real Python generator
          expression's variables are scoped to it), while names it READS
          from the enclosing function stay live through that scope's parent
          chain — a real closure, which is why this path does not need (and
          does not do) the compiled path's capture-by-value approximation.

        The synthesized AST uses `N.YieldExpr` — deliberately never this
        file's own `yield` keyword, since a single literal `yield` in a
        top-level function body of myinterpreter.py makes gimple_codegen.py
        treat the WHOLE file as an unsupported user generator and fall back
        to interpreting it from source (see _ThreadedGenerator's docstring).
        """
        scope = Scope(parent=self.scope)
        # Outermost iterable: evaluated HERE, eagerly, per Python. Its value
        # is bound in the generator's own scope and the synthesized outer
        # `for` iterates that name, so it is not evaluated a second time
        # when the first resume happens.
        scope.define(_GENEXP_ITER_NAME,
                     self.eval_expr(expr.generators[0].iterable))
        return MojoGeneratorObject(
            self, scope,
            N.genexp_body(expr,
                          N.IdentExpr(name=_GENEXP_ITER_NAME,
                                      line=expr.line, col=expr.col)))

    def eval_Comprehension(self, expr):
        """List/set/dict comprehensions and parenthesized generator
        expressions (`expr.kind` in 'list'/'set'/'dict'/'generator').

        A 'generator' expression is a REAL lazy generator object (see
        `_generator_expression`), not a materialized list.

        Real Python list/set/dict comprehensions get their own scope; this
        interpreter evaluates those in the *current* scope instead (same
        simplification execute_ForStmt already makes for a plain `for`
        loop) — their loop variables leak into the enclosing scope, a known
        minor fidelity gap.

        For a dict comprehension, fire_compiler.py's parser stores the KEY
        expression in `.element` and the VALUE expression in `.key` (yes,
        swapped from what the names suggest — see _parse_dict_or_set).

        ONE `return`, through a single `result` variable, deliberately —
        the same shape (and for the same reason) as `MojoFunction._invoke`
        above: this file is self-hosted, and its return-type inference is a
        whole-function unification that cannot cope with several
        differently-shaped `return` statements in one function. Adding the
        generator-expression branch as its own early `return` made the
        unification pick one of {MojoGeneratorObject, MojoSet *, MojoDict *,
        MojoList *} and then fail coercing the others ("cannot coerce
        MojoSet * to MojoDict *" when self-hosting myinterpreter.py)."""
        if expr.kind == 'generator' and expr.generators:
            result = self._generator_expression(expr)
        else:
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
                result = set(results)
            elif expr.kind == 'dict':
                result = dict(results)
            else:
                result = results
        return result
