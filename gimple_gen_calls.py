"""Call/constructor/subscript lowering for the GIMPLE backend.

Function-extraction architecture: former GimpleGen methods as module-level
functions taking `gen` first; delegates remain on the class; cross-module
references are qualified (single-emission closure rule).
"""
from __future__ import annotations

import os
import re

from mojo_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,
    EllipsisLiteral, NoneLiteral,
    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,
    GlobalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
)
import regex_compile
import mlir
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
import gimple_codegen
import gimple_gen_methods as gmp
import gimple_gen_calls as ggc

def _lower_call(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    # Step I (create_task/Task/TaskGroup/RaisingTask project):
    # `create_task(f())` / `create_raising_task(f())` where `f` is a
    # supported compiled async function (top-level OR nested — a
    # nested one is only resolvable here while THIS enclosing
    # function's body is being compiled, via gen_module's scoped
    # push into self._async_api — see
    # _compile_nested_async_functions's docstring). Constructs the
    # coroutine via `{base}_start(args...)` (exactly like the
    # generator-call path elsewhere in this method) and schedules it
    # onto Step A's ready queue via `mojo_async_schedule_ready` -- but,
    # unlike `asyncio.run(...)`'s bridge, does NOT drive the scheduler
    # to completion here: real Mojo's own `create_task` returns a
    # `Task` immediately, without blocking, and this project's
    # single-threaded cooperative scheduler only actually RUNS
    # scheduled work when something later drains it (`.wait()` -- see
    # _lower_method_call's own `MojoAsync *`.`wait()` case -- or
    # another `await`). The resulting `MojoAsync *` handle is tracked
    # in self._async_var_api (mirrors self._generator_var_api's
    # identical "value -> api" side-table pattern exactly) so a later
    # `.wait()` on the variable it gets assigned to can recover which
    # extern "C" API/value_ctype to use. No structural difference is
    # made here between `create_task` and `create_raising_task` -- see
    # _lower_method_call's own docstring on why this codegen's promise
    # already stages ANY escaped exception generically regardless of a
    # `raises` annotation, so both map onto the identical handle shape.
    #
    # Checked FIRST, before ANY other dispatch in this method
    # (including the generic-import elaboration a little further
    # down): real Mojo's own `create_task`/`create_raising_task` are
    # themselves imported, generic-looking free functions from
    # `std.runtime.asyncrt` (`create_raising_task[type: Movable,
    # origins: OriginSet](...)`), so `_elaborate_generic_call` would
    # otherwise try to elaborate their REAL body (raw MLIR ops,
    # ThinAllocation, ...) instead of ever reaching this special case
    # — and worse, that path unconditionally lowers every argument
    # (`self.lower_expr(a) for a in node.args`, BEFORE its own
    # try/except) to drive type inference, which would eagerly
    # evaluate `f()` as a value-consuming call and hit THIS module's
    # own, unrelated "async function called as a value" honest
    # refusal a few hundred lines down — a confusing, wrong failure
    # for a perfectly supported create_task/create_raising_task shape.
    # Intercepting here, before that dispatch is even attempted, avoids
    # it entirely rather than trying to special-case around it deeper
    # in the shared generic-elaboration machinery.
    # `_create_task(f(...), desired_worker_id=<hint>)` (test_asyncrt.
    # mojo's `test_create_task_with_affinity_runs_coroutine`) is real
    # Mojo's own affinity-hinted variant of `create_task` -- the hint is
    # documented as purely advisory (correctness must hold whether or
    # not the runtime honours it; see that test's own docstring), and
    # this codegen's scheduler has no worker-affinity concept at all, so
    # the hint is simply dropped (still lowered via `self.lower_expr`
    # for its side effects, matching every other discarded-value
    # argument elsewhere in this file) and the call is treated exactly
    # like a bare `create_task(f(...))` -- an honest, documented
    # simplification (the hint's own contract permits this), not a
    # silent correctness gap.
    # `TaskGroup()` (test_locks.mojo's own idiom: `var tg = TaskGroup();
    # ...; tg.create_task(inc()); ...; tg.wait[origin]()`) -- real
    # Mojo's own `TaskGroup` (std/runtime/asyncrt.mojo) is a genuinely
    # deep struct (raw MLIR ops, an atomic counter, a `_Chain` low-
    # level completion primitive, a `List[_TaskGroupBox]`) nowhere near
    # reachable by this codegen's general (non-async) struct-compiling
    # path -- reinterpreted here exactly like `create_task`/
    # `create_raising_task` already are: not by compiling TaskGroup's
    # REAL body, but as a small set of intrinsics this codegen
    # understands directly. A TaskGroup is represented as a plain
    # `MojoList *` of `(int64_t)` `MojoAsync *` handles (this project's
    # EXISTING mojo_list_new/mojo_list_append_int/mojo_list_get_int/
    # mojo_list_len infrastructure, reused rather than inventing a
    # parallel dynamic-array type -- see CLAUDE.md's consolidation
    # principle) -- `self._taskgroup_var_api` (name -> {'base',
    # 'value_ctype'}, populated lazily by the FIRST `.create_task(...)`
    # call on it, see `_lower_method_call`) tags which names are really
    # task groups, mirroring `self._async_var_api`'s identical name-
    # keyed "value -> api" side-table pattern for a bare `create_task`
    # handle. Every task added to ONE group must compile to the SAME
    # async unit (an honest compile-time refusal if a second, different
    # one is ever added -- see `.create_task()`'s own check below) --
    # real Mojo's TaskGroup allows heterogeneous tasks (type-erased via
    # `_TaskGroupBox`), but every real target shape only ever adds ONE
    # kind of task to a given group, so this narrower contract is
    # honest (a hard refusal, not silent wrongness) rather than solving
    # the fully general heterogeneous case.
    if (isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name == 'TaskGroup'
            and not node.args and not getattr(node, 'kwargs', None)):
        handle = gen._call_expr('MojoList *', 'mojo_list_new', [])
        gen._taskgroup_var_api[handle] = {'base': None, 'value_ctype': None}
        return 'MojoList *', handle
    _ct_kwargs = getattr(node, 'kwargs', None) or []
    if (isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name == '_create_task'
            and len(node.args) == 1 and len(_ct_kwargs) == 1
            and _ct_kwargs[0][0] == 'desired_worker_id'):
        gen.lower_expr(_ct_kwargs[0][1])
        node = gimple_ctypes.CallExpr(func=gimple_ctypes.IdentExpr(name='create_task'), args=node.args, kwargs=[])
    if (isinstance(node.func, gimple_ctypes.IdentExpr)
            and node.func.name in ('create_task', 'create_raising_task')
            and len(node.args) == 1 and not getattr(node, 'kwargs', None)):
        _fname = node.func.name
        inner = node.args[0]
        # Resolve any keyword arguments on the inner call (e.g. real
        # Mojo's own `create_raising_task(conditional_raise(should_fail
        # =False))`) against the callee's real parameter order — see
        # _resolve_kwargs_for_known_async_call's own docstring; reused
        # here (not re-implemented) since this is the SAME "keyword-
        # argument call to a known async function" shape
        # _normalize_await_kwargs already handles for the `await
        # <call>` composition case, just reached from ordinary
        # (non-coroutine-body) code instead.
        gen._resolve_kwargs_for_known_async_call(inner)
        # A nested async def with no comptime bracket parameters is
        # normally captured by gen_module's own _compile_nested_async_
        # functions pass (registered into self._nested_async_api, then
        # scoped-pushed into self._async_api for this enclosing
        # function's body compile — see that pass's docstring) and
        # resolves via the self._async_api lookup just below. But
        # gen_module also has a SEPARATE, independently-built nested-
        # in-top-level-function discovery pass (the comptime-bracket-
        # parametrized one — see _async_closure_api's 'comptime_params'
        # key) that targets the identical parent shape (an ordinary
        # top-level function's body) and, for a param-less nested
        # async def, would produce an equally valid compiled unit —
        # gen_module's pass ORDERING already guarantees only one of the
        # two ever actually claims any given nested async def (each
        # pops its id out of the shared `_async_fns` on success, and
        # the other checks that first), so no double-compile occurs.
        # This fallback exists purely so create_task(...)'s own lookup
        # doesn't silently regress if a future change to that ordering
        # (or a bracket-param-free call to a function that happens to
        # be comptime-parametrized) ever lets the OTHER pass claim it
        # first instead.
        _resolved = gen._resolve_and_start_task(inner)
        if _resolved is not None:
            handle, api = _resolved
            gen._async_var_api[handle] = api
            return 'MojoAsync *', handle
        # DELIBERATE, DOCUMENTED SIMPLIFICATION (not silent wrongness —
        # see this project's own standing "honest, documented
        # simplification" standard, e.g. bugs/CODEGEN_device_context_
        # host_function_enqueue_synchronous_stub.md): the inner call
        # names a REAL `async def` somewhere in this module (found by
        # gen_module's own initial `_walk_ast` scan — self.
        # _all_async_fn_names — regardless of whether it ended up
        # eligible for this codegen's narrow C++20-coroutine path), but
        # it never got compiled (e.g. a non-scalar/String return type —
        # this codegen's shared coroutine-body emitter is deliberately
        # scalar-only throughout, see _gen_cpp_async_unit's docstring).
        # Concretely hit by test_raising_asyncrt.mojo's own
        # `test_raising_async_error_message_via_wrapper` — a test the
        # file's OWN author already disabled at its one call site in
        # `main()` (commented out, citing a genuine, separate upstream
        # Mojo MLIR bug, MOCO-3408) — so this specific function is
        # provably unreachable in that file, yet (unlike a function
        # body this codegen simply never emits) still has to COMPILE
        # since every top-level function gets a C definition regardless
        # of whether anything calls it.
        #
        # Rather than hard-refusing the WHOLE MODULE over one
        # genuinely-dead, upstream-acknowledged-broken function, this
        # emits a loud, honest RUNTIME failure in its place — a real
        # `abort()` with a diagnostic message, not a silently wrong
        # value — so if this specific call path were ever, contrary to
        # the analysis above, actually reached, it fails LOUDLY at run
        # time instead of returning a plausible-looking but bogus
        # result. Scoped narrowly to names already confirmed to be
        # real async functions (not a catch-all for any unresolved
        # name) — an undefined/typo'd name still hits the ordinary
        # hard compile-time refusal below.
        if inner.func.name in gen._all_async_fn_names:
            for a in inner.args:
                gen.lower_expr(a)  # side effects, if any
            gen._emit(
                f'  fprintf(stderr, "mojo: {_fname}({inner.func.name}(...)) '
                f'reached at runtime, but {inner.func.name!r} could not be '
                'compiled to a real coroutine by this codegen (deliberate '
                'stub -- see gimple_codegen.py\'s _lower_call comment on '
                'create_task/create_raising_task) -- aborting\\n");')
            gen._emit("  abort ();")
            handle = gen._new_val('MojoAsync *', '(MojoAsync *)0')
            # Marked 'stub' (no real base/value_ctype exists) so a
            # later `.wait()` on whatever variable this gets assigned
            # to (see _lower_method_call's own `MojoAsync *`.`wait()`
            # case) also degrades to the same abort()-based fallback
            # instead of trying to call a nonexistent extern "C" API.
            gen._async_var_api[handle] = {'stub': True}
            return 'MojoAsync *', handle
        raise RuntimeError(
            f"cannot compile module: {_fname}(...) is only "
            "supported for the shape "
            f"`{_fname}(<call to a supported compiled async "
            "function>)` -- falling back to interpreting this module "
            "from source instead")
    # __get_address_as_owned_value(addr)  →  *(int64_t *)addr
    # Mojo ownership intrinsic: load the value at a raw-pointer address.
    if isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name == '__get_address_as_owned_value' \
            and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        ptr = gen._new_temp('int64_t *')
        gen._safe_coerce_emit(at, 'int64_t *', av, ptr)
        val = gen._new_temp('int64_t')
        gen._emit(f"  {val} = *{ptr};")
        return 'int64_t', val
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr) \
            and node.func.obj.name in ('external_call', '_external_call_const'):
        return gen._lower_external_call(node)
    mlir_call = gen._maybe_lower_mlir_op(node)
    if mlir_call is not None:
        return mlir_call
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr) \
            and node.func.obj.name in gen._imported_generic_structs:
        res = gen._elaborate_generic_struct_call(node)
        if res is not None:
            return res
    if isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name in gen._imported_overloads:
        res = gen._elaborate_overload_call(node)
        if res is not None:
            return res
    _gen = (isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr)
            and node.func.obj.name in gen._imported_generics) or \
           (isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name in gen._imported_generics)
    if _gen:
        res = gen._elaborate_generic_call(node)
        if res is not None:
            return res
    # Bracket call to a nested async function/closure with its OWN
    # comptime bracket parameter(s), e.g. test_asyncrt.mojo's
    # `test_asyncrt_add[1](rhs)` (`test_asyncrt_add` is a sibling
    # nested `async def` inside the SAME enclosing function currently
    # being compiled — see gen_module's "Async closures/functions
    # NESTED INSIDE A TOP-LEVEL FUNCTION" discovery pass). The bracket
    # argument(s) were threaded through as ordinary trailing
    # parameters at definition time (in comptime_params order, before
    # any free-variable captures) — forward them here the same way.
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr):
        _acl_key2 = (gen.current_func_name, node.func.obj.name)
        _api2 = gen._async_closure_api.get(_acl_key2)
        if _api2 is not None and _api2.get('comptime_params'):
            _cp_list = _api2['comptime_params']
            _idx2 = node.func.index
            _elems2 = _idx2.elements if isinstance(_idx2, gimple_ctypes.TupleExpr) else [_idx2]
            if len(_elems2) == len(_cp_list):
                # Ordinary args FIRST, then bracket (comptime) elements,
                # then any trailing captures -- matches the callee's
                # REAL compiled signature order (_gen_cpp_async_unit:
                # `fn.params` then `extra_captures`), not bracket-
                # elements-first. See the sibling coroutine-body
                # composition site's own identical fix (a few thousand
                # lines down, `_bc9_args`) for the hand-verified repro
                # that caught this same ordering bug (masked here too
                # by every existing caller's own commutative arithmetic
                # -- never independently exercised until test_tracing.
                # mojo's real shape).
                arg_pairs2 = [gen.lower_expr(a) for a in node.args]
                arg_pairs2 += [gen.lower_expr(a) for a in _elems2]
                for cap_name, _cap_ctype in _api2['captures'][len(_cp_list):]:
                    arg_pairs2.append(gen.lower_expr(gimple_ctypes.IdentExpr(name=cap_name)))
                handle2 = gen._call_expr('MojoAsync *', f"{_api2['base']}_start", arg_pairs2)
                if _api2['value_ctype'] != 'void':
                    raise RuntimeError(
                        "cannot compile module: call to nested async "
                        f"function {node.func.obj.name!r} whose result "
                        "is consumed as a value and carries a real "
                        "return value — this codegen has no await/"
                        "top-level-run mechanism yet to drive it to "
                        "completion here (use asyncio.run(...) to "
                        "drive a single such call directly instead)")
                return 'MojoAsync *', handle2
    if isinstance(node.func, gimple_ctypes.MemberExpr):
        return gen._lower_method_call(node)
    # Subscripted method call: obj.method[TypeParam](...) — unwrap type param and route as method call.
    # A method whose comptime bracket parameter is function-typed and
    # actually used (registered in _method_threaded_comptime_params —
    # see its docstring / bugs/CODEGEN_device_context_captured_function_
    # parameter_closures_broken.md's Repro 1) is compiled with that
    # parameter as an ordinary TRAILING C parameter (_gen_struct_method),
    # so the bracket argument(s) here must be forwarded as extra
    # positional args, in the same order as the method's own
    # comptime_params — dropping them silently (the pre-existing
    # behavior, still correct for every OTHER bracket parameter: a pure
    # type-bound never referenced as a plain identifier, or an Int/Bool/
    # other comptime parameter this narrow mechanism doesn't touch)
    # left `func` unresolved inside the method body / its nested
    # closures, emitted as a bogus, never-defined bare C identifier call.
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.MemberExpr):
        method_name = node.func.obj.member
        extra_args = []
        # Resolve the receiver's struct name cheaply (no side effects —
        # _quick_type is a pure lookup) so the (struct_name, method_name)
        # key can't cross-contaminate an unrelated struct's same-named
        # method (see _method_threaded_comptime_params' docstring for
        # why struct-name-blind keying is unsafe: std/builtin/
        # variadics.mojo's VariadicList.consume_elements — an ordinary,
        # non-generic method — vs. the unrelated VariadicPack.
        # consume_elements[elt_handler: def[idx: Int](...)]).
        _recv_ct = gen._quick_type(node.func.obj.obj)
        _struct_name = _recv_ct[:-2] if _recv_ct.endswith(' *') else _recv_ct
        orders_by_oid = gen._method_comptime_param_order.get((_struct_name, method_name))
        if orders_by_oid:
            idx = node.func.index
            elems = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]
            # Which sibling overload does this call site's bracket-
            # argument COUNT match? Real overload resolution happens
            # deeper (in _lower_method_call, called below), which this
            # narrow, textual pre-scan doesn't have access to — but the
            # comptime-param arity alone is enough to disambiguate
            # honestly: if exactly one candidate overload's
            # comptime_params list is the same length as the bracket-
            # argument list actually supplied here, use its threaded-
            # parameter set; if zero or more than one match (genuinely
            # ambiguous), do nothing — the pre-existing "drop the
            # bracket" behavior — rather than guess and risk forwarding
            # an extra argument to an overload compiled WITHOUT a
            # matching trailing parameter.
            _candidates = [oid for oid, order in orders_by_oid.items()
                           if len(order) == len(elems)]
            if len(_candidates) == 1:
                oid = _candidates[0]
                order = orders_by_oid[oid]
                threaded = gen._method_threaded_comptime_params.get((_struct_name, method_name), {}).get(oid, [])
                for i, cp_name in enumerate(order):
                    if cp_name in threaded and i < len(elems):
                        extra_args.append(elems[i])
        inner = gimple_ctypes.CallExpr(func=node.func.obj, args=list(node.args) + extra_args,
                         kwargs=getattr(node, 'kwargs', []), line=getattr(node, 'line', 0))
        return gen._lower_method_call(inner)
    # Generic container constructors: List[T](...), Dict[K,V](...), Set[T](...), Optional[T](...)
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr):
        base = node.func.obj.name
        if base in ('List', 'InlineList', 'SmallVector', 'DynamicVector', 'InlineArray',
                    'Buffer', 'NDBuffer'):
            t = gen._new_val('MojoList *', 'mojo_list_new ()')
            for a in node.args: gen.lower_expr(a)
            return 'MojoList *', t
        if base in ('Dict', 'OrderedDict'):
            t = gen._new_val('MojoDict *', 'mojo_dict_new ()')
            for a in node.args: gen.lower_expr(a)
            return 'MojoDict *', t
        if base in ('Set', 'FrozenSet'):
            t = gen._new_val('MojoSet *', 'mojo_set_new ()')
            for a in node.args: gen.lower_expr(a)
            return 'MojoSet *', t
        if base == 'Optional':
            if node.args:
                at, av = gen.lower_expr(node.args[0])
                t = gen._new_val('int64_t', f'(int64_t){av}' if at.endswith(' *') else av)
                return 'int64_t', t
            return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
    if not isinstance(node.func, gimple_ctypes.IdentExpr):
        # Calling the RESULT of a call expression directly —
        # `factory()(5)`, `make_adder2(100)(2)`, `pick(1)(x)` — where the
        # inner call returns a first-class callable VALUE. Previously
        # stubbed to 0 (silently wrong; returned 0 instead of calling).
        # Dispatch on the inner value's type exactly like an ordinary
        # identifier-backed call: a `MojoBoundMethod *` (a capturing
        # closure / bound method bundle) re-supplies its env via
        # mojo_bound_method_call_N; a bare function pointer
        # (`void *`/int64_t-boxed, a non-capturing closure or free fn)
        # goes through mojo_fnptr_call_N.
        # ONLY a CallExpr callee (a genuine chained call) and a
        # LambdaExpr callee (an immediately-invoked lambda — a real
        # runtime callable value) are value-lowered here. A
        # SubscriptExpr callee is a GENERIC TYPE/constructor expression
        # (`Scalar[x.dtype](...)` — a comptime bracket argument, not a
        # runtime value), whose eager value-lowering would miscompile
        # (found via math.mojo's `Scalar[x.dtype](...)`); those keep the
        # old stub.
        if isinstance(node.func, (gimple_ctypes.CallExpr, gimple_ctypes.LambdaExpr)):
            _callee_t, _callee_v = gen.lower_expr(node.func)
            if _callee_t == 'MojoBoundMethod *':
                return gen._lower_bound_method_call_value(_callee_v, node)
            if _callee_t == 'void *' or _callee_t in ('int', 'int64_t', '_Bool'):
                return gen._lower_fnptr_call_value(_callee_t, _callee_v, node)
        # `SomeGeneric[ExplicitArg](args)` where SomeGeneric ALSO has
        # implicit/inferred bracket params this elaborator can't bind
        # (e.g. std.python.numpy.from_numpy_array[mut, //, dtype,
        # origin] — only `dtype` is ever passed explicitly; `mut`/
        # `origin` are inferred from the argument's own lifetime, which
        # this codegen has no model for) never reaches
        # _elaborate_generic_call's success path and falls all the way
        # here. Stubbing to a bare int64_t 0 (below) is fine on its
        # own, but a caller doing `for x in from_numpy_array(...):`
        # then hits _gen_for_iter's boxed-dict/list runtime-dispatch
        # fallback (the ONLY thing an opaque int64_t can mean there),
        # which unconditionally declares the loop var `char *` (the
        # dict-key type) — a hard C type error once the loop body uses
        # it as anything else (`total: Float64 ... total += value`,
        # real, in stdlib's test_numpy.mojo). Reading just the callee's
        # OWN `-> ReturnType:` annotation and resolving its outer
        # container shape (Span/List/Dict/Set) lets the stub return a
        # well-typed NULL of the right pointer kind instead — the for
        # loop then correctly takes the "no iterator protocol" path
        # and drops the loop body (still functionally a stub, but one
        # that compiles) rather than colliding types.
        if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr):
            _static_ct = gen._static_generic_return_ctype(node.func.obj.name)
            if _static_ct is not None:
                for a in node.args: gen.lower_expr(a)
                t = gen._new_val(_static_ct, f'({_static_ct})0')
                gimple_ctypes._debug_note('un-elaboratable generic call statically-typed stub',
                            (node.func.obj.name, _static_ct))
                return _static_ct, t
        gimple_ctypes._debug_note('indirect call stubbed', type(node.func).__name__)
        t = gen._new_temp('int64_t')
        gen._emit(f'  {t} = (int64_t)0;  /* indirect call via {type(node.func).__name__} */')
        return 'int64_t', t

    fname_raw = node.func.name
    if fname_raw.startswith('mojo_python_'):
        gen._python_api_needed = True
    # An async closure NESTED INSIDE THIS METHOD (device_context.mojo's
    # `async def wrapper(...) capturing -> None:` shape — see
    # gen_module's dedicated discovery pass / _async_closure_api).
    # Constructs via `{base}_start(<ordinary args>, <captures>)`,
    # mirroring the top-level-async-function construct convention
    # exactly (Step B: never runs the body immediately). Captures are
    # read HERE, at the call site, as ordinary already-in-scope
    # identifiers (this method's own param/threaded-comptime-param) —
    # not pre-populated into an env struct at the nested `async def`
    # statement itself (see _gen_stmt_FunctionDef's matching skip).
    _acl_key = (gen.current_func_name, fname_raw)
    if _acl_key in gen._async_closure_api:
        handle, vct = gen._lower_async_closure_construct(_acl_key, node)
        if vct != 'void':
            raise RuntimeError(
                "cannot compile module: call to nested async closure "
                f"{fname_raw!r} whose result is consumed as a value "
                "and carries a real return value — this codegen has no "
                "await/top-level-run mechanism yet to drive a nested "
                "async closure to completion and read a real value "
                "back out of it; only a void-returning nested async "
                "closure (device_context.mojo's own shape) may have its "
                "raw, un-driven handle captured this way")
        return 'MojoAsync *', handle
    # Milestone B: `counter()` where `counter` is a supported generator
    # function — constructs the coroutine (via its C++20-emitted
    # `<base>_start()`) WITHOUT running any body code yet, matching real
    # Python/Mojo "calling a generator function returns a generator
    # object" semantics. Checked before every other CallExpr special
    # case below (mirrors how `_gen_for_iter`'s .finditer() structural
    # check runs before the generic path) since a generator call must
    # never fall through to the ordinary function-call lowering (there is
    # no ordinary C function with this name to call — see gen_module's
    # Phase 2a skip for _supported_generators).
    if fname_raw in gen._generator_api:
        api = gen._generator_api[fname_raw]
        # Argument lowering reuses the exact same self.lower_expr(a)-per-
        # arg + _call_expr/_emit_call path every ordinary function call
        # in this file uses (see the plain call path a little further
        # down) — func_param_types[f"{base}_start"] (registered in
        # gen_module's generator pre-pass) is what lets _emit_call's
        # existing coercion logic (int literal -> int64_t, etc.) apply
        # here with no separate/duplicated coercion code.
        arg_pairs = [gen.lower_expr(a) for a in node.args]
        # Pad missing trailing params with keyword args / real defaults,
        # mirroring _lower_named_call's identical padding for ordinary
        # functions (see its own comment on `greet()` vs `def greet(name
        # = "world")`). Without this, a generator call omitting any
        # keyword-or-defaulted param (e.g. `tokenize(src, filename=
        # filename)`, real code in Tools/cases_generator/lexer.py) only
        # ever passed the bare positional args straight through — the
        # keyword argument was silently DROPPED entirely (this whole
        # branch never even looked at `node.kwargs`) and no default
        # value filled the gap either, producing a hard "too few
        # arguments to function '<base>_start'" compile error since
        # `<base>_start`'s real C signature has one slot per Python
        # parameter, unconditionally.
        _gen_kwargs = getattr(node, 'kwargs', []) or []
        _gen_expected = gen.func_param_types.get(f"{api['base']}_start", [])
        # Which C-signature slot (if any) is this generator function's
        # OWN `**kwargs` parameter — see _func_kwargs_slot's docstring.
        # A literal keyword argument destined for that slot must be
        # PACKED into a real MojoDict (via _pack_kwargs_dict), exactly
        # like _lower_named_call's identical `_kwslot_for_pack` handling
        # for ordinary (non-generator) functions — mirrored here rather
        # than duplicated differently. Without this, the loop below
        # (before this fix) just popped the next literal keyword
        # argument's raw lowered VALUE into whichever slot came next in
        # sequence, with no awareness that one particular slot is a
        # `MojoDict *`: `gen_forward(3, b=5)` emitted `_t4 = (MojoDict
        # *)_t3` — the integer 5 reinterpreted as a dict pointer —
        # which segfaults the moment the generator body reads its own
        # `**kwargs` (same failure shape as the bug _func_kwargs_slot's
        # own docstring documents for the ordinary call path; found via
        # the coroutine-body `**kwargs`-forwarding repro in bugs/
        # COMPILE_FAIL_Tools_c-analyzer_c_analyzer___init__.md, whose
        # `gen_forward(3, b=5)` top-level call site hit this exact bug
        # even before reaching the generator BODY's own separately
        # fixed `**kwargs`-forwarding).
        _gen_kwslot = gen._func_kwargs_slot.get(
            fname_raw, gen._func_kwargs_slot.get(f"{api['base']}_start", -1))
        if _gen_expected and len(arg_pairs) < len(_gen_expected):
            _gen_kwarg_dict = {kn: gen.lower_expr(ke) for kn, ke in _gen_kwargs}
            _gen_kwarg_values = list(_gen_kwarg_dict.values())
            _gen_dflts = gen._func_param_defaults.get(f"{api['base']}_start", [])
            while len(arg_pairs) < len(_gen_expected):
                _pos = len(arg_pairs)
                if _gen_kwslot >= 0 and _pos == _gen_kwslot:
                    arg_pairs.append(('MojoDict *', gen._pack_kwargs_dict(_gen_kwarg_dict)))
                    _gen_kwarg_values = []
                    continue
                if _gen_kwarg_values:
                    arg_pairs.append(_gen_kwarg_values.pop(0))
                    continue
                _dv = _gen_dflts[_pos][1] if _pos < len(_gen_dflts) else None
                if _dv is not None:
                    arg_pairs.append(gen._default_expr_to_pair(_dv))
                else:
                    arg_pairs.append(('int', '0'))
        else:
            for _, _ke in _gen_kwargs:
                gen.lower_expr(_ke)
        t = gen._call_expr('MojoGenerator *', f"{api['base']}_start", arg_pairs)
        gen._generator_var_api[t] = api
        return 'MojoGenerator *', t
    # Step B (revised — see bugs/CODEGEN_compiled_async_eager_execution_
    # semantic_mismatch.md): `f()` where `f` is a supported compiled
    # async function, with its result actually CONSUMED as a value
    # (assigned, passed as an argument, ...). Calling an async function
    # NEVER runs its body — it produces a not-yet-started coroutine
    # object (real Python semantics; this project's own interpreter's
    # MojoCoroutine matches). The correct lowering is therefore to
    # CONSTRUCT the coroutine handle ({base}_start) and return it as a
    # first-class MojoAsync* value — the body never runs until/unless
    # something later drives it (await / a top-level driver). Used for
    # real by types.py's metaprogramming idiom
    # `async def _c(): pass; _c = _c()` (a coroutine object created for
    # type(_c)/.close() without ever being run).
    if fname_raw in gen._async_api:
        api = gen._async_api[fname_raw]
        arg_pairs = [gen.lower_expr(a) for a in node.args]
        handle = gen._call_expr('MojoAsync *', f"{api['base']}_start", arg_pairs)
        gen._async_var_api[handle] = api
        return 'MojoAsync *', handle
    # next(g) where `g` is (or holds) a MojoGenerator* — the compiled-
    # generator "first-class value" gap (bugs/CODEGEN_compiled_generator_
    # not_first_class_value.md, second failure): previously `next` had NO
    # real lowering at all anywhere in this file (only a variadic FIXME
    # extern declaration for the generic builtin — see the `next` entry
    # in the always-declared-externs table — that has no definition
    # anywhere and fails at LINK time, not compile time, for ANY use of
    # next(), not just on generators; confirmed via grep, there is no
    # pre-existing "next() on some other iterable type" convention to
    # reuse here). Mirrors _gen_for_generator_iter's own resume()/value()
    # driving exactly (same "returns 2 things" scheme, not invented
    # fresh), but signals exhaustion as a real StopIteration exception
    # via the SAME mojo_exc_type_set()/mojo_raise() mechanism
    # _gen_stmt_RaiseStmt uses for `raise StopIteration`, rather than a
    # third, novel signaling convention — so `except StopIteration:`
    # around a next() call in the same function catches it correctly.
    if fname_raw == 'next' and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        at = gen._get_actual_type(at, av)
        if at == 'MojoGenerator *':
            api = gen._generator_var_api.get(av)
            if api is not None:
                base, vct = api['base'], api['value_ctype']
                resumed = gen._new_val('_Bool', f"{base}_resume ({av})")
                bb_ok = gen._new_bb(); bb_exhausted = gen._new_bb(); bb_merge = gen._new_bb()
                bb_stopiter = gen._new_bb()
                gen._emit(f"  if ({resumed}) goto {bb_ok}; else goto {bb_exhausted};")
                gen._emit_label(bb_exhausted)
                # Milestone D: `_resume` reporting false is ambiguous
                # between real exhaustion (StopIteration, the pre-
                # existing convention below) and an uncaught exception
                # that unwound the generator's whole body — see
                # _emit_generator_pending_exc_check's docstring.
                gen._emit_generator_pending_exc_check(av, base, False, bb_stopiter)
                gen._emit_label(bb_stopiter)
                gen._emit(f"  mojo_exc_type_set ({gen._exc_type_id('StopIteration')});")
                gen._emit("  mojo_raise ();")
                gen._emit(f"  goto {bb_merge};")
                gen._emit_label(bb_ok)
                result = gen._new_val(vct, f"{base}_value ({av})")
                gen._emit(f"  goto {bb_merge};")
                gen._emit_label(bb_merge)
                return vct, result
            gimple_ctypes._debug_note('next() on MojoGenerator* with no known _generator_var_api entry '
                        '(unreachable in normal use — see assign-then-next() propagation)', av)
    # next(g, default) — same MojoGenerator* driving as the 1-arg form
    # above, but exhaustion returns `default` instead of raising
    # StopIteration (real Python semantics: the 2-arg form is exactly
    # how callers opt OUT of the exception — e.g. importlib/resources/
    # _itertools.py's `first_value = next(it, default)`). Before this,
    # the 2-arg form fell through to the SAME declared-but-never-
    # defined variadic `next(...)` stub the 1-arg form used to hit
    # (undefined symbol at link time), since the check above only
    # matched `len(node.args) == 1`.
    if fname_raw == 'next' and len(node.args) == 2:
        at, av = gen.lower_expr(node.args[0])
        at = gen._get_actual_type(at, av)
        if at == 'MojoGenerator *':
            api = gen._generator_var_api.get(av)
            if api is not None:
                base, vct = api['base'], api['value_ctype']
                resumed = gen._new_val('_Bool', f"{base}_resume ({av})")
                result = gen._new_temp(vct)
                bb_ok = gen._new_bb(); bb_exhausted = gen._new_bb(); bb_merge = gen._new_bb()
                gen._emit(f"  if ({resumed}) goto {bb_ok}; else goto {bb_exhausted};")
                gen._emit_label(bb_ok)
                ok_val = gen._new_val(vct, f"{base}_value ({av})")
                gen._safe_coerce_emit(vct, vct, ok_val, result)
                gen._emit(f"  goto {bb_merge};")
                gen._emit_label(bb_exhausted)
                # `default` is only evaluated on the exhausted branch —
                # real Python semantics (a non-trivial default expr must
                # not run when the iterator actually yields a value).
                dt, dv = gen.lower_expr(node.args[1])
                gen._safe_coerce_emit(dt, vct, dv, result)
                gen._emit(f"  goto {bb_merge};")
                gen._emit_label(bb_merge)
                return vct, result
    # A local variable of a callable struct type, invoked like a function:
    # obj(args) → obj.__call__(args).
    if (fname_raw in gen.var_types and fname_raw not in gen.func_return_types
            and fname_raw not in gen._global_inline_defs):
        _csn = gimple_exprtypes._struct_name_of(gen.var_types[fname_raw])
        if _csn and _csn in getattr(gen, '_callable_structs', set()):
            _cm = gimple_ctypes.MemberExpr(obj=node.func, member='__call__',
                             line=getattr(node, 'line', 0))
            return gen._lower_method_call(gimple_ctypes.CallExpr(
                func=_cm, args=node.args,
                kwargs=getattr(node, 'kwargs', []), line=getattr(node, 'line', 0)))
    # Only redirect to the synthesized entry point when 'main' really is
    # this module's own entry-point function. `from foo import main;
    # main()` (e.g. Lib/idlelib/idle.py) binds 'main' to an *imported*
    # function with its own real signature — rewriting that call to
    # _gimple_main/_lib_main mismatches the synthesized stub's signature
    # and produces "conflicting types for '_gimple_main'".
    if (fname_raw == 'main' and gen.current_func_name != 'main'
            and fname_raw not in gen.imported_symbols
            and fname_raw not in gen._unresolved_import_aliases):
        if gen.emit_entry_points:
            fname_raw = '_gimple_main'
        else:
            _mod_id = gen.module_name.replace('.', '_').replace('-', '_') if gen.module_name else ''
            fname_raw = f"_{_mod_id}_main" if _mod_id else '_lib_main'
        # _lower_named_call's missing-arg padding (below, via
        # self.func_param_types.get(fname_raw, [])) looks up the
        # RENAMED symbol, but _collect_function_param_types registered
        # main's arity under its original name 'main' — so a call with
        # fewer args than main declares (relying on a default, e.g.
        # `def main(args=None): ...` called as bare `main()`) found no
        # expected_params here and never got padded, unlike the exact
        # same call written as a bare top-level statement (a separate,
        # unaffected code path). Only reachable as a *nested* call
        # (`sys.exit(main())`, `identity(main())`, ...) — found via
        # mojolib BUG-2026-032's transpiler.mojo. Mirror the arity under
        # the new key too, so the lookup below succeeds either way.
        if 'main' in gen.func_param_types and fname_raw not in gen.func_param_types:
            gen.func_param_types[fname_raw] = gen.func_param_types['main']
        # Same problem one step further down _lower_named_call: its
        # "completely unknown name" auto-stub check
        # (fname_raw not in self.func_return_types and ...) also looks
        # up the renamed symbol, found nothing (func_return_types has
        # 'main', not '_gimple_main'), and treated the call as an
        # opaque external function — emitting a variadic
        # `int64_t _gimple_main (...);` stub that conflicts with the
        # real, concretely-typed definition ("conflicting types for
        # '_gimple_main'; have 'int64_t(int64_t)'").
        if 'main' in gen.func_return_types and fname_raw not in gen.func_return_types:
            gen.func_return_types[fname_raw] = gen.func_return_types['main']

    # Builtin dispatch
    if fname_raw == 'strided_load' and node.args:
        return gen._lower_strided(node, store=False)
    if fname_raw == 'strided_store' and len(node.args) >= 2:
        return gen._lower_strided(node, store=True)
    # `_locally_binds_name` gate: `len` is an ordinary identifier a
    # module could shadow with its own top-level def — same class of
    # gate as `open`/`filter`/`any`/`all` elsewhere in this file (no
    # confirmed real-world stdlib instance found for `len` specifically,
    # but the gate is a single cheap lookup and keeps this dispatch
    # consistent with every other BUILTIN_VALUE_MAP-adjacent name).
    if (fname_raw == 'len' and node.args
            and not gen._locally_binds_name('len')):
        return gen._lower_builtin_len(node)
    # ord()/chr() had NO real lowering at all — any call fell through to
    # a declared-but-never-defined variadic stub (`int64_t ord(...);`),
    # an undefined symbol at link time. Found via regex_compile.py's own
    # ord(c) calls. mojo_ord/mojo_chr operate on the first byte only
    # (this codebase's strings are plain bytes, not full Unicode).
    if fname_raw == 'ord' and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        if at == 'char':
            return 'int64_t', gen._new_val('int64_t', f'(int64_t){av}')
        if at not in ('char *', 'MojoStr *'):
            av = gen._new_val('char *', f'(char *){gen._ensure_local(at, av)}')
        return 'int64_t', gen._call_expr('int64_t', 'mojo_ord', [('char *', av)])
    if fname_raw == 'chr' and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        av64 = av if at == 'int64_t' else gen._new_val('int64_t', f'(int64_t){av}')
        return 'char *', gen._call_expr('char *', 'mojo_chr', [('int64_t', av64)])
    if fname_raw == 'isinstance'      and len(node.args) == 2:  return gen._lower_builtin_isinstance(node)
    # `_locally_binds_name` gate: a module can define its OWN top-level
    # `any`/`all` (e.g. tokenize.py's `def any(*choices): return
    # group(*choices) + '*'`, called with exactly 1 arg at
    # `Ignore = Whitespace + any(r'\\\r?\n' + Whitespace) + maybe(...)`).
    # Without this gate, that call was misrouted to the builtin
    # all-args-truthy/any-args-truthy runtime helper instead of the
    # user's own function — same class of bug as the `open` gate just
    # below, and the same fix.
    if (fname_raw in ('all', 'any') and len(node.args) == 1
            and not gen._locally_binds_name(fname_raw)):
        return gen._lower_builtin_all_any(fname_raw, node)
    # `_locally_binds_name` gates below: `dir`/`sorted`/`zip`/`set`/
    # `frozenset`/`dict`/`list`/`tuple` are all ordinary identifiers a
    # module could shadow with its own top-level def/import — same class
    # of gate as `open`/`filter`/`any`/`all`/`len` elsewhere in this
    # file. `__import__` is left unguarded: it is not a plausible name
    # for real Python source to redefine as an ordinary function.
    if fname_raw == 'dir' and not gen._locally_binds_name('dir'):
        return gen._lower_builtin_dir(node)
    if (fname_raw == 'sorted' and node.args
            and not gen._locally_binds_name('sorted')):
        return gen._lower_builtin_sorted(node)
    if (fname_raw == 'zip' and len(node.args) > 2
            and not gen._locally_binds_name('zip')):
        return gen._lower_builtin_zip_n(node)
    if fname_raw == '__import__':                                return gen._lower_builtin_import(node)
    if (fname_raw in ('set', 'frozenset')
            and not gen._locally_binds_name(fname_raw)):
        return gen._lower_builtin_set(node)
    if fname_raw == 'dict' and not gen._locally_binds_name('dict'):
        return gen._lower_builtin_dict(node)
    if (fname_raw in ('list', 'tuple') and len(node.args) <= 1
            and not gen._locally_binds_name(fname_raw)):
        return gen._lower_builtin_list(node)
    if fname_raw == 'open'            and not gen._locally_binds_name('open'):
        return gen._lower_builtin_open(node)
    if fname_raw == 'Self':                                      return gen._lower_self_ctor(node)
    # iter(x) — the container is already iterable (for-loops consume it directly),
    # so model the builtin as identity rather than emitting an undefined `iter` call.
    if fname_raw == 'iter' and len(node.args) == 1 and 'iter' not in gen.func_return_types:
        return gen.lower_expr(node.args[0])

    # repr(x): dispatch by the argument's own static type instead of
    # boxing everything through one generic runtime function. The old
    # single mojo_repr(int) both truncated any 64-bit value AND treated
    # a string/list/struct pointer as a plain integer, printing a
    # plausible-looking-but-wrong decimal number for anything that wasn't
    # a small int. Real strings need quoting (Python's repr("hi") ==
    # "'hi'"); anything else (list/dict/set/struct pointer) has no
    # runtime field-metadata table to reconstruct a real Python repr
    # from, so it's formatted as an address rather than silently
    # mistaken for a number. Found via mojo.py's own `--dump`'s
    # `repr(ast)` on a parsed AST list.
    if fname_raw == 'repr' and node.args:
        rat, rav = gen.lower_expr(node.args[0])
        return 'char *', gen._repr_value(rat, rav)

    # str(x): dispatch on the argument's static type via _stringify_value
    # (int → mojo_str_from_int, float → mojo_repr_float, ...) rather than
    # the generic mojo_str(void *), which can't tell a real int value of 0
    # apart from a NULL pointer and returns "None" for it — `str(0)`,
    # `str(x)` where x==0, etc. all printed None. Same dispatch f-strings
    # and %-formatting already use; this just routes the bare builtin
    # through it too. (char*/unknown-pointer args still reach mojo_str via
    # _stringify_value's fallthrough, unchanged.)
    # `_locally_binds_name` gate: `str` is an ordinary identifier a
    # module can shadow with its own top-level def (e.g. Lib/locale.py's
    # own `def str(val):`) — confirmed via a real shadowing repro
    # (without this gate the call was routed to `mojo_str_from_int`
    # instead of the user's own function). Same class of bug/fix as the
    # `open`/`filter`/`enumerate` gates elsewhere in this file.
    if (fname_raw == 'str' and len(node.args) == 1
            and not gen._locally_binds_name('str')):
        et, ev = gen.lower_expr(node.args[0])
        # A bare True/False literal lowers with ctype 'int' (not '_Bool' —
        # _lower_BoolLiteral does this deliberately; other sites depend on
        # it), so str(True) would take the int path → "1". Recover the
        # bool intent from the AST so it stringifies as "True"/"False".
        if isinstance(node.args[0], gimple_ctypes.BoolLiteral):
            et = '_Bool'
        return 'char *', gen._stringify_value(et, ev)

    # str(bytes_obj, encoding[, errors]): real Python's bytes-decode
    # form. This codegen has no real `bytes` type (bytes-like values are
    # already represented as plain `char *`, same as str -- see
    # BACKLOG-CODEGEN.md/bugs/hard's own notes on bytes()), so decoding
    # is a no-op: the first argument already IS the decoded string.
    # Before this, the 2/3-arg form fell through to the generic call
    # path, which still routed to the 1-arg `mojo_str(void *)` runtime
    # helper with 2-3 arguments -- "too many arguments to function
    # 'mojo_str'; expected 1, have 2/3" -- found via encodings/idna.py's
    # `str(label, "ascii")` and encodings/punycode.py's `str(text[:pos],
    # "ascii", errors)`. `encoding`/`errors` are still evaluated (for
    # any side effects a real decode call would have), just discarded.
    if (fname_raw == 'str' and len(node.args) in (2, 3)
            and not gen._locally_binds_name('str')):
        et, ev = gen.lower_expr(node.args[0])
        for _extra in node.args[1:]:
            gen.lower_expr(_extra)
        if et != 'char *':
            ev = gen._stringify_value(et, ev)
        return 'char *', ev

    # pow(base, exp, mod): real Python's 3-arg modular-exponentiation
    # form -- integer semantics, entirely distinct from the ordinary
    # 2-arg pow(x, y) (which stays real-valued, routed to libc's own
    # `pow(double, double)` via _KNOWN_SIGS below). Before this, the
    # 3-arg form fell through to that SAME 2-arg libc signature —
    # "too many arguments to function 'pow'; expected 2, have 3" —
    # found via Modules/_decimal/libmpdec/literature/fnt.py's and
    # Modules/_decimal/tests/bignum.py's own `pow(base, exp, mod)`.
    if fname_raw == 'pow' and len(node.args) == 3:
        bt, bv = gen.lower_expr(node.args[0])
        et, ev = gen.lower_expr(node.args[1])
        mt, mv = gen.lower_expr(node.args[2])
        bv = gen._to_int64(bt, bv)
        ev = gen._to_int64(et, ev)
        mv = gen._to_int64(mt, mv)
        return 'int64_t', gen._call_expr(
            'int64_t', 'mojo_pow_mod',
            [('int64_t', bv), ('int64_t', ev), ('int64_t', mv)])

    # hash(x): was previously only a bare, never-defined forward
    # declaration (`_util_pairs`'s preamble stub) — compiled fine but
    # failed to LINK ("undefined symbols: _hash") the instant anything
    # actually called it. Found via Modules/_decimal/tests/bignum.py's
    # `xhash` (calls hash() on nothing directly, but sits alongside
    # the pow(base, exp, mod) fix above in the same file/investigation)
    # and importlib/metadata/_text.py. Dispatch on the STATICALLY known
    # argument type when possible (matching Python's real hash(int) ==
    # int for the common int case, real content hashing for a string)
    # rather than always routing through the generic opaque-value
    # fallback (mojo_hash, which can't tell a small int from a real
    # string apart from a raw int64_t without a static type hint).
    if (fname_raw == 'hash' and len(node.args) == 1
            and not gen._locally_binds_name('hash')):
        ht, hv = gen.lower_expr(node.args[0])
        if ht in ('int', 'int64_t', '_Bool'):
            return 'int64_t', gen._to_int64(ht, hv)
        if ht in ('char *', 'MojoStr *'):
            hv = gen._stringify_value(ht, hv) if ht != 'char *' else hv
            return 'int64_t', gen._call_expr('int64_t', 'mojo_hash_str', [('char *', hv)])
        return 'int64_t', gen._call_expr('int64_t', 'mojo_hash', [('int64_t', gen._to_int64(ht, hv))])

    # sum(list_of_doubles): the generic `mojo_sum` (BUILTIN_VALUE_MAP
    # below) always reads each MojoList slot via mojo_list_get_int and
    # returns int64_t -- for a list this codegen tracks (via
    # _elem_types, e.g. from a `[3.5, 2.5]` literal or a param inferred
    # from float usage) as holding doubles, that silently misreads
    # every element's raw int64_t bit pattern as if it were an integer
    # instead of a float. Route to the double-aware runtime helper
    # instead, mirroring _list_repr_fn's identical "route through
    # _elem_types" pattern for repr(). Found via Tools/lockbench/
    # lockbench.py's `sum(values)`/`sum(x**2 for x in values)` on a
    # list of floats.
    if (fname_raw == 'sum' and len(node.args) == 1
            and not gen._locally_binds_name('sum')):
        at, av = gen.lower_expr(node.args[0])
        if gen._elem_types.get(av) == 'double':
            acast = av if at == 'void *' else gen._new_val('void *', f'(void *){av}')
            return 'double', gen._call_expr('double', 'mojo_sum_double', [('void *', acast)])
        acast = av if at == 'void *' else gen._new_val('void *', f'(void *){av}')
        return 'int64_t', gen._call_expr('int64_t', 'mojo_sum', [('void *', acast)])

    # Trivial builtins: lower_expr all args, call runtime fn
    _SIMPLE_BUILTINS = {
        'str':       ('char *',  'mojo_str'),
        'enumerate': ('void *',  'mojo_enumerate'),
        'hasattr':   ('int',     'mojo_hasattr'),
    }
    # `_locally_binds_name` gate: `enumerate`/`hasattr`/`str` are all
    # ordinary identifiers a module can shadow with its own top-level def
    # (e.g. Lib/threading.py's `def enumerate():`). Without this, a
    # locally-defined `enumerate` was routed straight to the builtin
    # `mojo_enumerate` runtime helper instead of the user's own function
    # (confirmed via a real shadowing repro — same class of bug as the
    # `open`/`filter` gates elsewhere in this file).
    if (fname_raw in _SIMPLE_BUILTINS and node.args
            and not gen._locally_binds_name(fname_raw)):
        rt, fn = _SIMPLE_BUILTINS[fname_raw]
        pairs = [gen.lower_expr(a) for a in node.args]
        return rt, gen._call_expr(rt, fn, pairs)
    # `vars(obj)` on a value whose struct type is statically known — same
    # real MojoDict* field view as `obj.__dict__` just above in
    # `_lower_MemberExpr` (see that call site's own comment; this is
    # Step 0 of bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md,
    # `vars()`/`__dict__` are the same operation in real Python). Scoped
    # the same way: only when the argument's struct type is genuinely
    # known, so an opaque/generic receiver falls through unchanged.
    if fname_raw == 'vars' and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        if gimple_exprtypes._struct_name_of(at) in gen.struct_field_types:
            gen._asdict_dispatch_needed.add(1)
            return 'MojoDict *', gen._call_expr(
                'MojoDict *', '_mojo_dispatch_asdict', [(at, av)])
    if fname_raw == 'getattr' and len(node.args) >= 2:
        # `getattr(f, "_cached", None)` where `f` is a free function
        # memoizing a value on itself (see `_func_attrs`'s pre-scan
        # docstring, gen_module Phase 1) — read the real backing global
        # instead of falling through to `_mojo_dispatch_getattr` (a
        # struct-instance reflection helper; `f` boxed as a function
        # pointer has no type tag it recognizes, so it always silently
        # returned a bogus "not found" value — the memoization compiled
        # without error but never actually cached anything).
        _fattrs_g = gen._func_attrs
        if (_fattrs_g and isinstance(node.args[0], gimple_ctypes.IdentExpr)
                and node.args[0].name in _fattrs_g
                and isinstance(node.args[1], gimple_ctypes.StringLiteral)
                and node.args[1].value in _fattrs_g[node.args[0].name]):
            mangled = _fattrs_g[node.args[0].name][node.args[1].value]
            gtype = gen._global_var_types.get(mangled, 'int64_t')
            return gtype, gen._new_val(gtype, mangled)
        # A5: `getattr(s, 'elifs', [])` / `getattr(handler, 'body', None)`
        # on a BOXED AST handle. The generic path below drops the default
        # arg and returns untyped int64_t, so `for _cond, elif_body in
        # getattr(s, 'elifs', []):` saw an opaque int64_t and fell to
        # mojo_unsupported_iter (the codegen's own structural walkers
        # silently skipped every if/else body in the compiled binary).
        # Mirror _lower_MemberExpr's A5 handling: when the attr names an
        # unambiguous struct field, resolve its static C type and read it
        # through the typedef. _mojo_dispatch_getattr returns 0 for a
        # missing/unknown field, so a provided default (the codegen's own
        # defensive `getattr(s, 'elifs', [])` pattern) is substituted.
        if (isinstance(node.args[1], gimple_ctypes.StringLiteral)
                and len(node.args) in (2, 3)):
            _attr = node.args[1].value
            _boxed_ft = gen._known_field_type(_attr)
            if _boxed_ft is not None:
                ot, ov = gen.lower_expr(node.args[0])
                if ot in ('int', 'char'):
                    ov = gen._new_val('int64_t', f'(int64_t){ov}')
                vp = gen._new_val('void *', f'(void *){ov}')
                raw = gen._call_expr('int64_t', '_mojo_dispatch_getattr',
                                      [('void *', vp), ('char *', f'"{_attr}"')])
                if len(node.args) >= 3:
                    dt, dv = gen.lower_expr(node.args[2])
                    if dt != 'int64_t':
                        dv = gen._new_val('int64_t', f'(int64_t){dv}')
                    zero = gen._new_val('int64_t', '(int64_t)0')
                    # GIMPLE: the ?: condition must be a _Bool temp (an
                    # inline `!=` in the selector is "bogus comparison
                    # result type" / "expected ';' before '?'").
                    cond = gen._new_val('_Bool', f'{raw} != {zero}')
                    raw = gen._new_val('int64_t', f'{cond} ? {raw} : {dv}')
                if _boxed_ft.endswith(' *'):
                    t = gen._new_val(_boxed_ft, f'({_boxed_ft}){raw}')
                else:
                    t = gen._new_temp(_boxed_ft)
                    gen._emit(f"  {t} = ({_boxed_ft}){raw};")
                return _boxed_ft, t
        pairs = [gen.lower_expr(a) for a in node.args[:2]]  # drop optional default
        return 'int64_t', gen._call_expr('int64_t', '_mojo_dispatch_getattr', pairs)
    if fname_raw == 'type'    and len(node.args) == 1:
        _, av = gen.lower_expr(node.args[0])
        # Read the struct's real leading __mojo_type_id field (see
        # mojo_read_type_tag_safe) instead of mojo_type()'s always-0 stub —
        # `type(node).__name__` needs it to dispatch (see the __name__
        # member-expr handling above). int64_t return (mojo_read_type_tag_
        # safe's own type); the old 'int' boxed the 64-bit tag into a 32-bit
        # temp, a hard gcc "invalid conversion in gimple call" error.
        av64 = gen._new_val('int64_t', f"(int64_t){av}")
        return 'int64_t', gen._new_val('int64_t', f"mojo_read_type_tag_safe ({av64})")
    if fname_raw == 'setattr' and len(node.args) >= 3:
        pairs = [gen.lower_expr(a) for a in node.args[:3]]
        return gen._void_call('_mojo_dispatch_setattr', pairs)
    if fname_raw == 'delattr' and len(node.args) >= 2:
        # `del obj.attr` (myinterpreter.py's execute_DelStmt) — the compiled
        # runtime has no dynamic attribute deletion (attributes are struct
        # fields), so this is a documented no-op that still compiles/links.
        pairs = [gen.lower_expr(a) for a in node.args[:2]]
        return gen._void_call('mojo_delattr', pairs)

    # Struct constructors. Map a C-keyword struct name (`auto()`) to its
    # renamed registration (`_kw_auto`) so the constructor resolves.
    _fname_ctor = gen._c_kw_struct_renames.get(fname_raw, fname_raw)
    if _fname_ctor in gen.struct_field_types:
        return gen._lower_struct_constructor(_fname_ctor, node.args, getattr(node, 'kwargs', None))
    if gen.func_return_types.get(fname_raw) == f'{fname_raw} *':
        return gen._lower_imported_struct_ctor(fname_raw, node)

    # Scalar type constructors (Float32, Int8, etc.) — before opaque-uppercase check
    _SCALAR_CTORS = {
        'Float32': 'float', 'Float64': 'double', 'Float16': '__fp16', 'BFloat16': '__fp16',
        'Int8': 'int8_t', 'Int16': 'int16_t', 'Int32': 'int32_t', 'Int64': 'int64_t',
        'UInt8': 'uint8_t', 'UInt16': 'uint16_t', 'UInt32': 'uint32_t', 'UInt64': 'uint64_t',
        'Int': 'int64_t', 'UInt': 'uint64_t', 'Bool': '_Bool',
    }
    if (fname_raw in _SCALAR_CTORS and fname_raw not in gen.func_return_types
            and fname_raw not in gen.imported_symbols):
        return gen._lower_scalar_ctor(fname_raw, _SCALAR_CTORS[fname_raw], node)

    # Closure / recursive self-call
    inner_name = getattr(gen, '_inner_func_name', '')
    if inner_name and fname_raw == inner_name and gen._env_param:
        return gen._lower_recursive_self_call(fname_raw, node)
    if fname_raw in gen._closure_envs:
        return gen._lower_closure_call(fname_raw, node)
    # Lambda body references an outer closure — call the lifted version with null env
    outer_ci = getattr(gen, '_lambda_outer_closures', {}).get(fname_raw)
    if outer_ci:
        return gen._lower_outer_closure_call(fname_raw, outer_ci, node)

    # Opaque uppercase constructor (imported type not in any table)
    if (gen.func_return_types.get(fname_raw, 'int64_t') == 'int64_t'
            and fname_raw[0:1].isupper()
            and fname_raw not in gen.func_param_types
            and fname_raw not in gen.imported_symbols
            and fname_raw not in gen._KNOWN_SIGS
            and fname_raw not in gimple_ctypes._C_RESERVED_FUNCS
            and fname_raw not in gen.BUILTIN_VALUE_MAP):
        return gen._lower_opaque_ctor(fname_raw, node)

    # Local variable holding a bound-method value (`f = self.b; ...; f()`
    # — see _lower_bound_method_value/bugs/
    # CODEGEN_bound_method_as_value_not_resolved.md). Must be checked
    # before the plain-function-pointer case just below: a
    # `MojoBoundMethod *` also needs `self` re-supplied as the implicit
    # first argument, which a bare fn-ptr call has no way to do. The var
    # may be declared as a real `MojoBoundMethod *` OR boxed through
    # `int64_t` — the general-purpose var-type-inference pre-pass has no
    # idea about this new pointer type and can default an assigned-from
    # variable to int64_t, same as it does for every other unfamiliar
    # struct pointer; _get_actual_type resolves that the same way
    # _lower_MemberExpr's own object-lowering path already does.
    # Fall back to the GLOBAL type table when fname_raw isn't a known
    # local — a bare reference to a module-level global inside a
    # function that never declared `global fname_raw` (no assignment to
    # it in this function, only a read/call, so Python/Mojo scoping
    # doesn't require the declaration) never gets seeded into
    # `self.var_types` here (contrast `_gen_stmt_GlobalStmt`, which DOES
    # seed it — see gen_module's `if name in self._global_var_types and
    # name not in self.var_types: self.var_types[name] = ...`, but only
    # runs for an explicit `global` statement). Without this fallback, a
    # module-level global holding a function pointer obtained via
    # `alias = m.some_func` (see `_lower_MemberExpr`'s module-alias
    # function-value resolution) and later called from a DIFFERENT
    # function than the one that assigned it — the common "lazy-init a
    # global once, call it from anywhere" pattern, e.g. BUG-2026-049's
    # `_helper_add = m.helper_add` in `ensure_helper()` then
    # `_helper_add(...)` in `main()` — fell all the way through to
    # `_lower_named_call` below, which just guesses the call target is a
    # C function literally named after the Mojo variable (never true
    # here) instead of recognizing it as a real function-pointer value.
    _fname_var_ctype = gen.var_types.get(fname_raw) or gen._global_var_types.get(fname_raw, '')
    if gen._get_actual_type(_fname_var_ctype, fname_raw) == 'MojoBoundMethod *':
        return gen._lower_bound_method_call(fname_raw, node, _fname_var_ctype)

    # Local variable (or captured variable) holding a function pointer.
    # Emit a proper function-pointer call via a C cast. Any name that is
    # a LOCAL VARIABLE here (not a known function/builtin, which the
    # dispatch above already handled) MUST be a function pointer — e.g.
    # `func(self.interpreter)` where func came from a `for name, func in
    # test_funcs:` tuple loop. Its declared type can be a misleading
    # first-decl-wins `char *` (a sibling `_gen_for_dict` branch declared
    # it for the dict-iteration arm), so treat any var-types local as a
    # fnptr call rather than guessing it names a C function.
    if (fname_raw in gen.var_types) or (_fname_var_ctype in ('int', 'int64_t', 'void *', '_Bool')):
        return gen._lower_fnptr_call(fname_raw, _fname_var_ctype, node)

    return gen._lower_named_call(fname_raw, node)


def _lower_builtin_len(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    at, av = gen.lower_expr(node.args[0])
    _LEN_FNS = {
        'MojoStr *':  f'mojo_str_len ({av})',
        'MojoList *': f'mojo_list_len ({av})',
        'MojoDict *': f'mojo_dict_len ({av})',
        'MojoSet *':  f'mojo_set_len ({av})',
    }
    if at in _LEN_FNS:
        return 'int64_t', gen._new_val('int64_t', _LEN_FNS[at])
    if at == 'char *':
        # A plain string (the overwhelmingly common representation of
        # Mojo/Python `str` in this compiler) had no case here at all —
        # fell all the way to the final "unsupported type" fallback,
        # so len(any_string) always silently returned 0. Found via
        # len(c_code) on a real compiled program's C output.
        return 'int64_t', gen._call_expr('int64_t', 'mojo_strlen', [('char *', av)])
    if at.endswith(' *') and at[:-2] in gen.struct_field_types \
            and '_len' in gen.struct_field_types[at[:-2]]:
        return 'int64_t', gen._new_val('int64_t', f'{av}->_len')
    if at in ('int', 'int64_t'):
        # `at` is just the local's declared storage type — for a value
        # widened to int64_t because it's joined with other assignment
        # sites in the same function (e.g. `rest = raw[prefix_len:]`
        # then `rest = raw`, both really char*), the actual pointer kind
        # survives in _actual_types (set wherever the value was stored;
        # see AssignStmt's "Track actual type if storing a pointer as
        # int64_t"). Blindly assuming MojoList* here — the previous,
        # only case — misroutes a boxed char* through mojo_list_len,
        # which then reads len*8 bytes off the string as if they were a
        # MojoList header. Found via mojo_compiler.py's own
        # _strip_string_prefix_and_quotes: len(rest) on a `rest` that's
        # really a string segfaulted deep in mojo_list_get_int.
        actual = gen._actual_types.get(av)
        if actual == 'char *':
            cp = gen._new_val('char *', f'(char *){av}')
            return 'int64_t', gen._call_expr('int64_t', 'mojo_strlen', [('char *', cp)])
        if actual == 'MojoDict *':
            dp = gen._new_val('MojoDict *', f'(MojoDict *){av}')
            return 'int64_t', gen._new_val('int64_t', f'mojo_dict_len ({dp})')
        if actual == 'MojoSet *':
            sp = gen._new_val('MojoSet *', f'(MojoSet *){av}')
            return 'int64_t', gen._new_val('int64_t', f'mojo_set_len ({sp})')
        ip = gen._new_val('int64_t', f'(int64_t){av}')
        lp = gen._new_val('MojoList *', f'(MojoList *){ip}')
        return 'int64_t', gen._new_val('int64_t', f'mojo_list_len ({lp})')
    return 'int64_t', gen._new_val('int64_t', f'(int64_t)0  /* len() on unsupported type {at} */')


def _isinstance_one_type(gen, obj_type: str, obj_val: str, type_name: str) -> str:
    """Emit the check for `isinstance(x, SingleType)` and return a _Bool
    value name. Factored out of _lower_builtin_isinstance so `isinstance(x,
    (A, B, ...))` (a tuple of types) can OR together one of these per
    alternative instead of the previous always-False stub."""
    if type_name == 'type':
        return gen._new_val('_Bool', '0')  # isinstance(x, type) always false in C
    if type_name in gen.struct_field_types:
        # A real user-defined struct/dataclass type: compare the
        # object's runtime type tag (see mojo_read_type_tag in
        # runtime/mojo_runtime.c, and the tag stamped by every
        # _alloc_<StructName> helper) against this type's own
        # deterministic hash — NOT the always-false mojo_isinstance()
        # stub below, which only covers scalar builtins with no
        # tagged runtime representation. Was a real, general bug:
        # isinstance(node, AnyStructType) always took the "not this
        # type" branch when compiled, found via find_imports() (used
        # by `mojo --dump`'s own do_imports resolution) never
        # recognizing an import statement nested in a function/if/try
        # block once self-hosted.
        target_id = gimple_exprtypes._struct_type_id(type_name)
        if obj_type.endswith(' *'):
            ov_local = gen._ensure_local(obj_type, obj_val)
            vp = gen._new_val('void *', f'(void *){ov_local}')
            addr = gen._new_val('int64_t', f'(int64_t){vp}')
        elif obj_type == 'int64_t':
            addr = obj_val
        else:
            addr = gen._new_val('int64_t', f'(int64_t){obj_val}')
        tag = gen._call_expr('int64_t', 'mojo_read_type_tag', [('int64_t', addr)])
        target = gen._new_val('int64_t', f'(int64_t){target_id}')
        cmp_t = gen._new_temp('_Bool')
        gen._emit(f'  {cmp_t} = {tag} == {target};')
        return cmp_t
    _TYPE_IDS = {'bool': '1', 'int': '2', 'float': '3', 'str': '4',
                 'list': '5', 'dict': '6', 'set': '7'}
    type_id = _TYPE_IDS.get(type_name, '0')
    # Scalar isinstance by STATIC type. The runtime mojo_isinstance stub
    # always returns 0 (false), so e.g. `isinstance(node.name, str)` was
    # ALWAYS False for a char* name once compiled — every VarDecl's
    # `isinstance(node.name, str)` guard (gimple_codegen.py's own
    # `_gen_stmt_VarDecl`) then treated node.name as a non-string and
    # formatted the char* as an integer, emitting raw heap addresses as
    # variable/type names in the native .ci (A5 part 2). A char* IS str,
    # an int64_t/int IS int, a MojoList* IS list, etc. — this codebase's
    # representation makes the static C type a sound verdict. Only an
    # ambiguous boxed int64_t falls through to the (still always-false)
    # mojo_isinstance stub.
    _SCALAR_TYPE_MATCH = {
        'str':   ('char *', 'MojoStr *'),
        'int':   ('int', 'int64_t', 'uint64_t', 'int8_t', 'int16_t', 'int32_t',
                  'uint8_t', 'uint16_t', 'uint32_t', 'long', 'short', 'size_t', '_Bool'),
        'float': ('double', 'float', '__fp16'),
        'bool':  ('_Bool',),
        'list':  ('MojoList *',),
        'dict':  ('MojoDict *',),
        'set':   ('MojoSet *',),
    }
    if type_name in _SCALAR_TYPE_MATCH:
        if obj_type in _SCALAR_TYPE_MATCH[type_name]:
            if obj_type.endswith(' *'):
                # A NULL pointer here means None (e.g. the "default"
                # branch of a dynamic getattr(obj, attr, None) on a
                # struct that doesn't have this field — see the A5
                # getattr-with-default lowering above, which types the
                # result by the FIELD NAME across all structs, not by
                # this particular object). isinstance(None, list) must
                # be False even though the static C type matches —
                # checking the static type alone made every such
                # "attribute absent" NULL look like a real empty-or-full
                # list, which then got pushed onto a caller's worklist
                # and iterated as if non-null (real bug: unbounded
                # memory growth / wild-pointer crash self-hosting a
                # large file, root-caused via _register_imported_structs
                # __collect's `getattr(st, attr, None)` +
                # `isinstance(sub, list)` walk).
                iv = gen._new_val('int64_t', f'(int64_t){obj_val}')
                zero = gen._new_val('int64_t', '(int64_t)0')
                return gen._new_val('_Bool', f'{iv} != {zero}')
            return gen._new_val('_Bool', '(_Bool)1')
        if obj_type not in ('int64_t', 'void *', ''):
            return gen._new_val('_Bool', '(_Bool)0')
    res = gen._new_temp('int')
    if obj_type in ('char *', 'void *', 'MojoDict *', 'MojoList *', 'MojoSet *') or obj_type.endswith(' *'):
        iv  = gen._new_val('int64_t', f'(int64_t){obj_val}')
        iv2 = gen._new_val('int', f'(int){iv}')
        gen._emit(f'  {res} = mojo_isinstance ({iv2}, {type_id});')
    else:
        gen._emit(f'  {res} = mojo_isinstance ({obj_val}, {type_id});')
    return gen._new_val('_Bool', f'(_Bool){res}')


def _lower_builtin_isinstance(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    obj_type, obj_val = gen.lower_expr(node.args[0])
    type_arg = node.args[1]
    t = gen._new_temp('int')
    if isinstance(type_arg, gimple_ctypes.IdentExpr):
        type_name = type_arg.name
        cmp_t = gen._isinstance_one_type(obj_type, obj_val, type_name)
        gen._emit(f'  {t} = (int){cmp_t};')
    elif isinstance(type_arg, gimple_ctypes.TupleExpr):
        # isinstance(x, (A, B, ...)) — OR together a per-alternative check
        # (see _isinstance_one_type). Previously stubbed to always-False,
        # which silently broke every `isinstance(s, (VarDecl, AssignStmt))`-
        # style filter once compiled — e.g. Parser._parse_struct's own
        # `[s for s in body if isinstance(s, (VarDecl, AssignStmt))]`
        # always produced an empty struct field list.
        acc = None
        for alt in type_arg.elements:
            if not isinstance(alt, gimple_ctypes.IdentExpr):
                continue
            one = gen._isinstance_one_type(obj_type, obj_val, alt.name)
            # `|` not `||`: GIMPLE rejects a raw `||` token in a plain
            # assignment RHS ("not valid in GIMPLE") — only simple binary
            # ops are allowed. Bitwise OR on two already-computed _Bool
            # (0/1) values is equivalent and GIMPLE-legal.
            acc = one if acc is None else gen._new_val('_Bool', f'{acc} | {one}')
        if acc is None:
            acc = gen._new_val('_Bool', '0')
        gen._emit(f'  {t} = (int){acc};')
    else:
        gimple_ctypes._debug_note('isinstance with complex type arg stubbed to 0')
        gen._emit(f'  {t} = 0;  /* TODO: isinstance with complex type arg */')
    return 'int', t


def _lower_builtin_all_any(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    runtime_fn = 'mojo_list_all' if fname_raw == 'all' else 'mojo_list_any'
    stub_val   = '1'             if fname_raw == 'all' else '0'
    at, av = gen.lower_expr(node.args[0])
    t = gen._new_temp('int')
    if at == 'MojoList *' or (at.endswith(' *') and at != 'char *'):
        lv = av if at == 'MojoList *' else gen._new_val('MojoList *', f'(MojoList *){av}')
        gen._emit_call('int', t, runtime_fn, [('MojoList *', lv)])
    else:
        gen._emit(f'  {t} = {stub_val};  /* {fname_raw}() stubbed */')
    return 'int', t


def _lower_builtin_dir(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    for a in node.args: gen.lower_expr(a)
    return 'MojoList *', gen._new_val('MojoList *', 'mojo_list_new ()  /* dir() stubbed */')


def _lower_builtin_sorted(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    arg0 = node.args[0]
    # sorted(dict.items()) — a list of (key, value) tuples sorted by key.
    # Without this, mojo_sorted's int64-payload sort orders the tuple
    # POINTERS, a non-deterministic order that diverges from Python (this
    # drives generated struct-typedef field order via
    # `for field_name, field_type in sorted(fields.items()):`).
    if (isinstance(arg0, gimple_ctypes.CallExpr) and isinstance(arg0.func, gimple_ctypes.MemberExpr)
            and arg0.func.member == 'items' and not arg0.args):
        ov_t, ov_v = gen.lower_expr(arg0.func.obj)
        ov_c = gen._coerce_to_type(ov_t, 'MojoDict *', ov_v)
        for a in node.args[1:]: gen.lower_expr(a)
        t = gen._call_expr('MojoList *', 'mojo_dict_items_sorted', [('MojoDict *', ov_c)])
        # Mirror .items(): the sorted item-list has the same [char* key,
        # boxed value] pair shape — carry the dict's value type through.
        # Look up from the ORIGINAL lowered value first (ov_c is a fresh
        # coercion temp with no value-type entry of its own).
        gen._dict_items_val_elems[t] = (
            gen._dict_val_types.get(ov_v) or gen._dict_val_types.get(ov_c) or 'int64_t')
        return 'MojoList *', t
    at, av = gen.lower_expr(arg0)
    for a in node.args[1:]: gen.lower_expr(a)
    # Dispatch on the container type so `sorted(...)` matches Python's
    # semantics instead of running mojo_sorted's generic int64 payload
    # bubble-sort over the wrong layout (a MojoSet has a completely
    # different struct layout from MojoList — mojo_sorted(set) read
    # garbage and could segfault; and sorting a list-of-strings by its
    # char* pointer values gives a non-deterministic, non-alphabetical
    # order that diverges from `python3 mojo.py --dump` output).
    if at == 'MojoSet *':
        return 'MojoList *', gen._call_expr('MojoList *', 'mojo_set_sorted', [(at, av)])
    if at == 'MojoDict *':
        return 'MojoList *', gen._call_expr('MojoList *', 'mojo_dict_sorted_keys', [(at, av)])
    if at == 'MojoList *' and gen._elem_of(av) == 'char *':
        t = gen._call_expr('MojoList *', 'mojo_list_sorted_str', [(at, av)])
    else:
        t = gen._call_expr('MojoList *', 'mojo_sorted', [(at, av)])
    # sorted() only reorders — the result keeps the input's element /
    # nested-element (tuple-pair) types, so a later `for x, y in
    # sorted(lst):` tuple-target loop reads slots with the right accessor.
    if at == 'MojoList *' and av in gen._nested_elem_types:
        gen._nested_elem_types[t] = gen._nested_elem_types[av]
    if at == 'MojoList *' and av in gen._elem_types:
        gen._elem_types[t] = gen._elem_types[av]
    return 'MojoList *', t


def _lower_builtin_zip_n(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """zip(a, b, c, ...) with >2 args — chain as mojo_zip(mojo_zip(a, b), c, ...)."""
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    # Fold left: mojo_zip(mojo_zip(a,b), c)
    acc_t, acc_v = 'void *', gen._call_expr('void *', 'mojo_zip', [arg_pairs[0], arg_pairs[1]])
    for ap in arg_pairs[2:]:
        acc_v = gen._call_expr('void *', 'mojo_zip', [('void *', acc_v), ap])
    return 'void *', acc_v


def _lower_builtin_import(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    for a in node.args: gen.lower_expr(a)
    return 'int', gen._new_val('int', '0  /* __import__ stubbed */')


def _lower_ctor_from_iterable(_g, kind: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Shared `set(iterable)` / `list(iterable)` lowering: build a
    synthetic `{x for x in <arg>}` / `[x for x in <arg>]` Comprehension
    node and hand it to `_lower_comprehension`, so `set(...)`/`list(...)`
    get the exact same generic-iterable handling (range/MojoList*/
    MojoStr*/MojoDict*(keys)/MojoSet*, plus the int64_t-boxed-pointer
    resolution `_lower_comprehension` already does) as real
    comprehensions and `for x in <iterable>:` loops, instead of a third,
    narrower iteration scheme. See bugs/CODEGEN_set_list_ctor_ignores_iterable_arg.md.
    """
    if not node.args:
        new_fn = 'mojo_set_new' if kind == 'set' else 'mojo_list_new'
        res_type = 'MojoSet *' if kind == 'set' else 'MojoList *'
        return res_type, _g._new_val(res_type, f'{new_fn} ()')
    _g.temp_counter += 1
    var = f"_ctor_elem{_g.temp_counter}"
    gen = gimple_ctypes.Generator(target=var, iterable=node.args[0], conditions=[],
                     line=node.line, col=node.col)
    compr = gimple_ctypes.Comprehension(kind=kind, element=gimple_ctypes.IdentExpr(var, node.line, node.col),
                           generators=[gen], line=node.line, col=node.col)
    return _g._lower_comprehension(compr)


def _lower_builtin_set(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    return gen._lower_ctor_from_iterable('set', node)


def _lower_builtin_dict(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    if not node.args:
        return 'MojoDict *', gen._new_val('MojoDict *', 'mojo_dict_new ()')
    at, av = gen.lower_expr(node.args[0])
    t = gen._new_temp('MojoDict *')
    if at == 'MojoList *':
        gen._emit_call('MojoDict *', t, 'mojo_dict_from_pairs', [('MojoList *', av)])
    elif at in ('int64_t', 'int') or not at.endswith(' *') or at == 'void *':
        raw = gen._new_val('MojoDict *', f'(MojoDict *){av}')
        gen._emit_call('MojoDict *', t, 'mojo_dict_copy', [('MojoDict *', raw)])
    else:
        gen._emit_call('MojoDict *', t, 'mojo_dict_copy', [(at, av)])
    return 'MojoDict *', t


def _lower_builtin_list(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    return gen._lower_ctor_from_iterable('list', node)


def _lower_builtin_open(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    # open(path) — read mode
    if len(node.args) == 1:
        fn_type, fn_val = gen.lower_expr(node.args[0])
        return 'int64_t', gen._call_expr('int64_t', 'mojo_open_file', [(fn_type, fn_val)])
    if not node.args:
        # open() with no args — a bare `open` reference used as a value
        # (e.g. tarfile's `fileobj = open` or `self._open`). Return a
        # generic function-pointer-ish placeholder rather than crashing.
        return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
    # open(path, mode)
    fn_type,   fn_val   = gen.lower_expr(node.args[0])
    mode_type, mode_val = gen.lower_expr(node.args[1])
    fn_val   = gen._ensure_local('char *', gen._coerce_to_type(fn_type,   'char *', fn_val))
    mode_val = gen._ensure_local('char *', gen._coerce_to_type(mode_type, 'char *', mode_val))
    tmp = gen._new_val('void *',   f'mojo_open ({fn_val}, {mode_val})')
    return 'int64_t', gen._new_val('int64_t', f'(int64_t){tmp}')


def _lower_self_ctor(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    sname = getattr(gen, '_current_struct_name', None)
    if sname:
        arg_pairs = [gen.lower_expr(a) for a in node.args]
        gen._self_ctor_stubs.add(sname)
        return 'int64_t', gen._call_expr('int64_t', f'{sname}___new', arg_pairs)
    for a in node.args: gen.lower_expr(a)
    return 'int64_t', gen._new_val('int64_t', '0  /* Self() constructor: no struct context */')


def _lower_imported_struct_ctor(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    t = gen._new_temp('int64_t')
    if arg_pairs:
        atype, aval = arg_pairs[0]
        if atype.endswith(' *'):
            gen._emit(f'  {t} = (int64_t){aval};')
        else:
            gen._emit(f'  {t} = (int64_t){gen._ensure_local(atype, aval)};')
    else:
        gen._emit(f'  {t} = (int64_t)0;')
    return 'int64_t', t


def _lower_scalar_ctor(gen, fname_raw: str, ctype: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    t = gen._new_temp(ctype)
    if node.args:
        at, av = gen.lower_expr(node.args[0])
        for xa in node.args[1:]: gen.lower_expr(xa)
        if not at.endswith(' *') and at not in ('MojoList *', 'MojoDict *', 'MojoSet *', 'void *', 'char *'):
            gen._emit(f'  {t} = ({ctype}){gen._ensure_local(at, av)};')
        else:
            gen._emit(f'  {t} = ({ctype})0;  /* {fname_raw}(struct) unsupported */')
    else:
        gen._emit(f'  {t} = ({ctype})0;')
    return ctype, t


def _lower_opaque_ctor(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    ctor_args = [gen.lower_expr(a) for a in node.args]
    t = gen._new_temp('int64_t')
    if ctor_args:
        at, av = ctor_args[0]
        if at.endswith(' *'):       gen._emit(f'  {t} = (int64_t){av};')
        elif at == 'int64_t':       gen._emit(f'  {t} = {av};')
        else:                       gen._emit(f'  {t} = (int64_t){gen._ensure_local(at, av)};')
    else:
        gen._emit(f'  {t} = (int64_t)0;')
    return 'int64_t', t


def _lower_recursive_self_call(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    lifted   = gen.current_func_name
    env_var  = gen._env_param
    ret_type = gen.func_ret_type or gen.func_return_types.get(lifted, 'int64_t')
    # Route through _emit_call/_call_expr (like _lower_closure_call's
    # sibling-closure-call path just below) so each argument is coerced
    # to the callee's DECLARED param type instead of passed as whatever
    # raw C type happened to fall out of lower_expr. This was always a
    # real gap here (never applied, unlike every other call-emission
    # path in this file) — previously invisible only because a
    # `__GIMPLE`-tagged lifted closure's raw pre-lowered GIMPLE body
    # bypasses gcc's normal call-argument type checking; a recursive
    # closure whose own body also contains try/except (and therefore
    # must drop `__GIMPLE`, see _reset_func's `_func_used_setjmp`
    # comment) gets compiled by the ordinary strict C frontend instead,
    # which correctly flags a mismatched arg (e.g. int64_t passed where
    # a struct pointer is declared) as a hard error. See
    # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md.
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    env_type = gen.func_param_types.get(lifted, ['void *'])[0]
    full_arg_pairs = [(env_type, env_var)] + arg_pairs
    fname_c  = gimple_ctypes._safe_name(lifted)
    if ret_type == 'void':
        return gen._void_call(fname_c, full_arg_pairs)
    return ret_type, gen._call_expr(ret_type, fname_c, full_arg_pairs)


def _lower_outer_closure_call(gen, fname_raw: str, ci, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Call an outer function's nested closure from inside a lambda body.

    The env pointer is not available here (it belongs to the outer function scope),
    so pass a null env — safe at link time; will crash at runtime if the env fields
    are actually accessed, but the selfhost test only checks compile+link.
    """
    lifted    = ci.lifted_name
    ret_type  = gen.func_return_types.get(lifted, 'int64_t')
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    fname_c   = gimple_ctypes._safe_name(lifted)
    if ci.env_struct:
        null_env = gen._new_val(f'{ci.env_struct} *', f'({ci.env_struct} *)0')
        full_arg_pairs = [(f'{ci.env_struct} *', null_env)] + arg_pairs
    else:
        full_arg_pairs = arg_pairs
    if ret_type == 'void':
        return gen._void_call(fname_c, full_arg_pairs)
    return ret_type, gen._call_expr(ret_type, fname_c, full_arg_pairs)


def _lower_closure_call(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    lifted   = f'{gen.current_func_name}_{fname_raw}'
    env_var  = gen._closure_envs[fname_raw]
    ret_type = gen.func_return_types.get(lifted, 'int64_t')
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    # Pad missing positional args with the closure's own declared
    # defaults (`def _inject(iterator=iterator, suffix=suffix): ...`
    # called bare as `_inject()`) -- see the defaults registration in
    # the closure-scan pass (Pass 3) for why nested closures need
    # their own entry here rather than sharing the top-level
    # free-function one.
    expected_params = gen.func_param_types.get(lifted, [])
    user_param_count = len(expected_params) - (1 if env_var and expected_params else 0)
    if user_param_count > len(arg_pairs):
        kwargs = getattr(node, 'kwargs', []) or []
        kwarg_dict = {kname: gen.lower_expr(kexpr) for kname, kexpr in kwargs}
        _dflts = gen._func_param_defaults.get(lifted) or []
        while len(arg_pairs) < user_param_count:
            _pos = len(arg_pairs)
            _pname = _dflts[_pos][0] if _pos < len(_dflts) else None
            if _pname is not None and _pname in kwarg_dict:
                arg_pairs.append(kwarg_dict[_pname])
            elif _pos < len(_dflts):
                # Evaluate the default AST directly (self.lower_expr),
                # not the literal-only _default_expr_to_pair used for
                # top-level free functions: the extremely common
                # `def _inject(iterator=iterator, suffix=suffix): ...`
                # idiom binds the OUTER function's own live variable as
                # the default, and we're generating code for THIS call
                # site while still inside that outer function's own
                # body, so its scope (self.var_types) is exactly the
                # right context to resolve the identifier in.
                arg_pairs.append(gen.lower_expr(_dflts[_pos][1]))
            else:
                arg_pairs.append(('int', '0'))
    fname_c  = gimple_ctypes._safe_name(lifted)
    if env_var:
        # No slice inside the f-string: the self-hosted f-string parser
        # reads `[1:]` as a format spec and mis-parses the interpolation.
        env_base = env_var[1:]
        env_type = gen.func_param_types.get(lifted, [f"{env_base} *" if '_env_' in env_var else 'void *'])[0]
        full_arg_pairs = [(env_type, env_var)] + arg_pairs
    else:
        full_arg_pairs = arg_pairs
    if ret_type == 'void':
        return gen._void_call(fname_c, full_arg_pairs)
    return ret_type, gen._call_expr(ret_type, fname_c, full_arg_pairs)


def _lower_LambdaExpr(gen, node) -> tuple:
    """Lift a lambda expression to a top-level C function.

    Returns a (void *, static_ptr_name) pair so the lambda can be passed
    as a function pointer.  The actual body is accumulated in
    self._lambda_parts and flushed by gen_module into func_parts.
    """
    outer_ctx = gen.current_func_name or 'root'
    gen._lambda_counter += 1
    lifted_name = f'{outer_ctx}_lambda_{gen._lambda_counter}'

    # Build a synthetic FunctionDef whose body is `return <lambda.body>`
    syn_body = [gimple_ctypes.ReturnStmt(value=node.body)]
    # Lambda params are (pname, default_value) not (pname, type_ann).
    # Strip defaults so _gen_lifted_closure doesn't try to resolve them as types.
    syn_params = [(p, None) for p, _ in node.params]
    syn_def  = gimple_ctypes.FunctionDef(
        name=lifted_name,
        params=syn_params,
        return_type=None,
        body=syn_body,
    )

    # Infer param types from captures + existing var_types context.
    # `node.params` elements are (pname, default_value_AST_or_None) —
    # NOT (pname, type_ann) — so the `pname` branch below only ever
    # fires for a default-less param; a defaulted param's second
    # element is an expression node (never `None`), so it always
    # skipped this loop entirely. That silently missed the standard
    # tkinter-callback idiom `lambda e, self=self: ...` (bind an
    # outer-scope value into the lambda without a real closure) —
    # including the common `lambda e, w=window: ...` shape where the
    # default's identifier differs from the param name — so a
    # captured struct-pointer param like `self` never got its real
    # ctype recorded here and fell back to a generic `int64_t` default
    # a few lines down in `_gen_lifted_closure`, while the forward
    # declaration built from THIS list (a few lines below) kept
    # whatever `pname` itself resolved to. Two lambdas differing only
    # in whether their default-bound param happened to coincide with
    # `pname` could each end up with a mismatched decl-vs-definition
    # ctype for the same lifted name, a "conflicting types" hard
    # error (real repro: Tools/unittestgui/unittestgui.py's
    # `errorListbox.bind("<Double-1>", lambda e, self=self: self.
    # showSelectedError())`).
    captures = []
    for pname, default in node.params:
        if isinstance(default, gimple_ctypes.IdentExpr) and default.name in gen.var_types:
            captures.append((pname, gen.var_types[default.name]))
        elif default is None and pname in gen.var_types:
            captures.append((pname, gen.var_types[pname]))

    ci = gimple_solvers.ClosureInfo(
        lifted_name=lifted_name,
        env_struct='',
        captures=captures,
        inner_def=syn_def,
    )
    # Register return type and param types now so call sites resolve correctly
    ret_type = gen._infer_return_type(syn_body)
    gen.func_return_types[lifted_name] = ret_type
    param_ctypes = []
    seen_lambda_varargs = False
    for pname, ptype in node.params:
        # A lambda's own *args/**kwargs (e.g. `lambda *args, **kwargs:
        # cls(loader(*args, **kwargs))`, importlib/util.py's LazyLoader.
        # factory) must resolve to the SAME concrete MojoList*/MojoDict*
        # convention _gen_lifted_closure's real param-building loop
        # below uses for the actual definition (see its `pname.
        # startswith('**')`/`startswith('*')` branches) — this list
        # feeds the forward declaration / static fn-pointer cast type,
        # which must match the definition exactly or GCC rejects it as
        # "conflicting types". Previously this loop had no `*`/`**`-
        # prefix handling at all: a literal `'*args'`/`'**kwargs'` name (the
        # star baked into the string) never matched anything in
        # var_types below, so both fell through to the plain `int64_t`
        # default — a forward decl silently mismatched against the
        # real MojoList*/MojoDict* body it was declaring.
        if pname.startswith('**'):
            param_ctypes.append('MojoDict *')
        elif pname.startswith('*'):
            if not seen_lambda_varargs:
                param_ctypes.append('MojoList *')
                seen_lambda_varargs = True
        # Lambda params: second element is default value (AST node), not a type annotation.
        # Resolve from var_types context; default to int64_t.
        elif pname in gen.var_types:
            param_ctypes.append(gen.var_types[pname])
        else:
            param_ctypes.append('int64_t')
    gen.func_param_types[lifted_name] = param_ctypes

    # Generate the lifted function body and queue for emission
    # Save/restore per-function state around the nested codegen
    saved_decls          = gen.decls
    saved_body           = gen.body_lines
    saved_var_types      = dict(gen.var_types)
    saved_func_name      = gen.current_func_name
    saved_ret_type       = gen.func_ret_type
    saved_bb             = gen.bb_counter
    saved_temp           = gen.temp_counter
    saved_captures       = dict(gen._captures)
    saved_env            = gen._env_param
    saved_inner          = gen._inner_func_name
    saved_loop_stack     = list(gen.loop_stack)
    saved_loop_depth     = gen._loop_depth
    saved_closure_envs   = dict(gen._closure_envs)
    saved_func_decl_glob = set(gen._func_declared_globals)

    # Expose outer closure info so the lambda body can resolve calls to parent
    # nested functions (e.g. compile_one_object) via their lifted C names with
    # a null env pointer (safe at link time; runtime env is unavailable in lambda).
    outer_closures_for_lambda = {}
    outer_all_closures = gen._all_closures.get(outer_ctx, {})
    for _inner_n, _env_v in saved_closure_envs.items():
        _outer_ci = outer_all_closures.get(_inner_n)
        if _outer_ci:
            outer_closures_for_lambda[_inner_n] = _outer_ci
    gen._lambda_outer_closures = outer_closures_for_lambda

    body_code = gen._gen_lifted_closure(ci)
    gen._lambda_outer_closures = {}

    gen.decls                   = saved_decls
    gen.body_lines              = saved_body
    gen.var_types               = saved_var_types
    gen.current_func_name       = saved_func_name
    gen.func_ret_type           = saved_ret_type
    gen.bb_counter              = saved_bb
    gen.temp_counter            = saved_temp
    gen._captures               = saved_captures
    gen._env_param              = saved_env
    gen._inner_func_name        = saved_inner
    gen.loop_stack              = saved_loop_stack
    gen._loop_depth             = saved_loop_depth
    gen._closure_envs           = saved_closure_envs
    gen._func_declared_globals  = saved_func_decl_glob

    gen._lambda_parts.append(body_code)
    gen._lambda_parts.append('')

    # Forward declaration so the preamble's static pointer initialiser can
    # reference the function before its definition appears in the output.
    # Param names must have their `*`/`**` prefix stripped here too (bare
    # `args`/`kwargs`, matching _gen_lifted_closure's real definition) —
    # left raw, `MojoList * *args` parses in C as `args: MojoList **`
    # (an extra, unintended level of pointer-ness from the literal `*`
    # character surviving into the declared NAME), a second, subtler
    # "conflicting types" mismatch beyond the ctype-only bug fixed above.
    params_str = ', '.join(
        f'{ct} {pn.lstrip("*")}' for ct, (pn, _) in zip(param_ctypes, node.params)
    ) or 'void'
    # Re-read the return type from func_return_types instead of the
    # `ret_type` local computed above (BEFORE the body was generated):
    # `_gen_lifted_closure` (just above) independently re-infers the
    # real return type from the SAME body and overwrites `func_return_
    # types[lifted_name]` with its own answer (gimple_codegen.py's
    # `self.func_return_types[ci.lifted_name] = ret_type` inside
    # `_gen_lifted_closure`) — and the two inference calls can DISAGREE
    # (different `self` context/state at each call site: this one runs
    # before any capture/var_types seeding for the lifted function,
    # `_gen_lifted_closure`'s runs after). Using the stale early value
    # here produced a forward declaration with the WRONG return type,
    # invisible until the struct-method `_lambda_parts`-flush fix above
    # started actually emitting the (correct) definition next to it —
    # confirmed via Lib/zipfile/__init__.py's `ZipFile.open`'s `lambda:
    # self._writing`: forward-declared `_Bool ZipFile_open_lambda_1
    # (void)` (this function's own early, pre-body-gen guess) but
    # DEFINED `int64_t ZipFile_open_lambda_1 (void)` (the real,
    # post-body-gen answer) — a hard "conflicting types" error.
    ret_type = gen.func_return_types.get(lifted_name, ret_type)
    fwd_decl = f'{ret_type} {lifted_name} ({params_str});'
    if fwd_decl not in gen._elaborated_externs:
        gen._elaborated_externs.append(fwd_decl)
    if lifted_name not in gen.func_return_types:
        gen.func_return_types[lifted_name] = ret_type
    gen._funcptr_builtins_needed.add(lifted_name)

    static_name = f'_funcptr_{lifted_name}'
    t = gen._new_val('void *', static_name)
    return 'void *', t


def _lower_async_closure_construct(gen, key: tuple, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Construct (never run the body of) a nested async closure — see
    _async_closure_api's registration in gen_module and this call
    site's caller in _lower_call. Returns (handle_expr, value_ctype);
    the caller decides whether consuming that handle as a value is
    allowed (only when value_ctype == 'void' — see the caller)."""
    api = gen._async_closure_api[key]
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    for cap_name, cap_ctype in api['captures']:
        arg_pairs.append(gen.lower_expr(gimple_ctypes.IdentExpr(name=cap_name)))
    handle = gen._call_expr('MojoAsync *', f"{api['base']}_start", arg_pairs)
    return handle, api['value_ctype']


def _emit_asyncio_run_drive(gen, base: str, vct: str, arg_pairs: list) -> tuple[str, str]:
    """`asyncio.run(f(...))`'s real drive-to-completion sequence for
    ANY compiled-async-coroutine API sharing the `_start`/`_value`/
    `_destroy`/`_translate_pending_exc` shape (self._async_api's
    top-level functions AND self._async_closure_api's nested async
    closures/functions alike) — construct via `_start`, schedule +
    run Step A's scheduler to completion, translate any pending
    exception (Step E's own convention — see _gen_cpp_async_unit's
    promise exc/exc_pending fields), then read back the value (skipped
    for a genuinely void-returning coroutine, matching device_
    context.mojo's own wrapper closures — a `void` GIMPLE local is
    invalid C) and destroy the frame. Factored out of _lower_call's
    `asyncio.run(...)` branch so the nested-async-closure case (test_
    asyncrt.mojo's `asyncio.run(test_asyncrt_add[1](10))`) doesn't
    duplicate this same real sequence a second time."""
    handle = gen._call_expr('MojoAsync *', f"{base}_start", arg_pairs)
    gen._emit(f"  mojo_async_schedule_ready ({handle});")
    gen._emit(f"  mojo_async_run_until_complete ();")
    gen._emit(f"  {base}_translate_pending_exc ({handle});")
    pending_t = gen._new_val('int', "mojo_exc_pending_get ()")
    bb_pending = gen._new_bb()
    bb_ok = gen._new_bb()
    gen._emit(f"  if ({pending_t}) goto {bb_pending}; else goto {bb_ok};")
    gen._emit_label(bb_pending)
    gen._emit(f"  mojo_exc_pending_set (0);")
    gen._emit(f"  {base}_destroy ({handle});")
    gen._emit("  mojo_raise ();")
    gen._emit_label(bb_ok)
    if vct == 'void':
        gen._emit(f"  {base}_destroy ({handle});")
        return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
    result = gen._new_val(vct, f"{base}_value ({handle})")
    gen._emit(f"  {base}_destroy ({handle});")
    return vct, result


def _lower_fnptr_call(gen, fname_raw: str, var_ctype: str,
                      node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Emit a call through a function pointer stored in a local/captured variable.

    Uses mojo_fnptr_call_N() runtime helpers because __GIMPLE functions cannot
    cast-and-call in a single expression.  All args are widened to int64_t;
    the result is then narrowed to the expected return type.
    """
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    n = len(arg_pairs)
    # Load the raw function pointer value.
    # For captured vars, _lower_IdentExpr reads from _env->name.
    # For a module-level GLOBAL not shadowed by a same-named local (the
    # `fname_raw not in self.var_types` half of the caller's ctype
    # lookup — see _lower_call's `_global_var_types.get(...)` fallback,
    # added for BUG-2026-049), the raw Mojo name is NOT a valid C
    # identifier on its own: a global is stored in the `_root_globals`
    # struct (or a per-module globals struct — see `_global_to_module`),
    # not as a bare C variable, so `self._c_names.get(fname_raw,
    # fname_raw)` below would emit a reference to an undeclared local
    # named e.g. `_helper_add` instead of the real `_root_globals.
    # _helper_add` field. Route through the SAME general IdentExpr
    # lowering every other global read already uses (`_lower_IdentExpr`,
    # ~line 6521 "Module-level global variable") instead of
    # hand-rolling the field access here a second time.
    if fname_raw in gen._captures and gen._env_param:
        fp_type, fp_raw = gen.lower_expr(gimple_ctypes.IdentExpr(name=fname_raw))
    elif fname_raw not in gen.var_types and fname_raw in gen._global_var_types:
        fp_type, fp_raw = gen.lower_expr(gimple_ctypes.IdentExpr(name=fname_raw))
    else:
        fp_raw = gen._c_names.get(fname_raw, fname_raw)
        fp_type = var_ctype
    ret_type = gen.func_return_types.get(fname_raw, 'int64_t')
    return gen._lower_fnptr_call_value(fp_type, fp_raw, node, ret_type)


def _lower_fnptr_call_value(gen, fp_type: str, fp_raw: str, node: gimple_ctypes.CallExpr,
                            ret_type: str = 'int64_t') -> tuple[str, str]:
    """Emit a call through an already-lowered function-pointer VALUE
    (`fp_raw`, of C type `fp_type`), the value-based twin of
    _lower_fnptr_call (shared so an arbitrary callable VALUE — e.g. the
    result of a chained `factory()(5)` call expression — dispatches
    through the same mojo_fnptr_call_N runtime helpers)."""
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    n = len(arg_pairs)
    # Cast to void * so the runtime helper receives a stable pointer type.
    if fp_type != 'void *':
        fp_void = gen._new_val('void *', f'(void *){fp_raw}')
    else:
        fp_void = fp_raw
    # Widen each arg to int64_t.
    widened = []
    for at, av in arg_pairs:
        if at == 'int64_t':
            widened.append(av)
        else:
            widened.append(gen._new_val('int64_t', f'(int64_t){av}'))
    # Emit the runtime-helper call; helpers exist for 0..4 args.
    helper = f'mojo_fnptr_call_{min(n, 4)}'
    call_args = ', '.join([fp_void] + widened[:4])
    raw_t = gen._new_val('int64_t', f'{helper} ({call_args})')
    if ret_type in ('int64_t', 'int'):
        return ret_type, raw_t
    if ret_type == 'void':
        gen._emit(f'  {helper} ({call_args});')
        return 'int', gen._new_val('int', '0')
    # Narrow back to declared return type.
    t = gen._new_val(ret_type, f'({ret_type}){raw_t}')
    return ret_type, t


def _default_expr_to_pair(gen, _dflt) -> tuple:
    """Convert a default-arg expression AST node to a (ctype, rvalue) pair,
    for padding a call site that omitted the argument. Mirrors the struct
    ctor default handling in _build_call_args_for_candidate."""
    if _dflt is None:
        return ('int', '0')
    if isinstance(_dflt, gimple_ctypes.BoolLiteral):
        return ('_Bool', '1' if _dflt.value else '0')
    if isinstance(_dflt, gimple_ctypes.StringLiteral):
        return ('char *', f'"{gimple_ctypes._c_escape(_dflt.value)}"')
    if isinstance(_dflt, (gimple_ctypes.IntLiteral, gimple_ctypes.FloatLiteral)):
        return ('int', str(_dflt.value))
    if isinstance(_dflt, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr, gimple_ctypes.SetExpr, gimple_ctypes.DictExpr)):
        return ('int64_t', '0')
    if isinstance(_dflt, gimple_ctypes.IdentExpr) and _dflt.name in ('True',):
        return ('int', '1')
    if isinstance(_dflt, gimple_ctypes.IdentExpr) and _dflt.name in ('False', 'None'):
        return ('int', '0')
    return ('int', '0')


def _pack_vararg_trailing_params(gen, fname, fname_raw, arg_pairs, kwarg_dict,
                                  call_has_spread=False):
    """Shared by `_lower_named_call` (value-consuming call sites) and
    `_gen_stmt_ExprStmt` (bare, value-discarding statement call sites —
    see that function's own duplicated general-call-building path for
    why it needs this too, not just _lower_named_call).

    `def f(fixed, *args, trailing_kwonly=default, ...)` — a vararg
    followed by more (keyword-only, per Python syntax) params, but NO
    `**kwargs`. `_emit_call`'s own packing check only fires when the
    `'...'` sentinel is the LAST entry of param_types; here it isn't
    (the trailing params come after it), so that check silently never
    fires — the call's extra positional args get coerced 1:1 against
    the trailing params' concrete C types instead of packed, and the
    trailing params themselves never receive a value at all. Real
    instance: importlib/_bootstrap.py's `_verbose_message(message,
    *args, verbosity=1)` called as `_verbose_message(fmt, a, b)`
    (verbosity left at its default) — `"too many arguments"` / a
    pointer-from-integer cast error at the call site. Python syntax
    guarantees anything textually after `*args` in a `def` is
    keyword-only, so it can NEVER be filled positionally by a call
    site — every entry of `arg_pairs` at/after the vararg's own
    position is unambiguously a vararg-pack candidate; the trailing
    param(s) must come from an explicit keyword argument (already in
    `kwarg_dict`, keyed by the call site's own real argument names) or
    their own default (`_func_param_defaults`, keyed by declared name
    — the trailing keyword-only slots are always exactly its LAST
    `len(_trailing_ptypes)` entries, since a param before `*args` is
    never keyword-only and so never appears in that tail).

    `func_param_types[name]`'s sentinel gets overwritten with the
    concrete real signature once the function's forward declaration
    is finalized (see _emit_call's own "starts life ending in the
    packing sentinel... gets overwritten... Every OTHER call site
    compiled afterwards then sees the concrete signature and
    silently skips packing" comment a few hundred lines up) — a call
    site compiled AFTER that point (the overwhelmingly common case
    for any function called more than once, or called from code
    textually after its own definition) sees a signature with no
    `'...'` at all, not even in the middle. `_mangled_signature_
    ctypes` preserves the original sentinel form untouched, so it's
    consulted FIRST here — `_emit_call`'s own existing fallback to it
    only checks `mangled_sig[-1] == '...'`, which is exactly as blind
    to a NON-final sentinel as the primary check it's guarding, so
    this reimplements that preference for the non-final case too
    rather than assuming `_emit_call`'s narrower version covers it.

    Returns the (possibly repacked) `(arg_pairs, kwarg_dict)`.
    """
    if call_has_spread:
        return arg_pairs, kwarg_dict
    _vararg_ptypes = (gen._vararg_trailing_param_types.get(fname)
                      or gen._vararg_trailing_param_types.get(fname_raw)
                      or gen._mangled_signature_ctypes.get(fname)
                      or gen._mangled_signature_ctypes.get(fname_raw)
                      or gen.func_param_types.get(fname)
                      or gen.func_param_types.get(fname_raw))
    if not (_vararg_ptypes and '...' in _vararg_ptypes and _vararg_ptypes[-1] != '...'):
        return arg_pairs, kwarg_dict
    _sentinel_idx = _vararg_ptypes.index('...')
    _n_fixed2 = _sentinel_idx
    _trailing_ptypes = _vararg_ptypes[_sentinel_idx + 1:]
    _trailing_dflts = (gen._func_param_defaults.get(fname)
                       or gen._func_param_defaults.get(fname_raw) or [])
    _trailing_names_defaults = (_trailing_dflts[-len(_trailing_ptypes):]
                                if _trailing_ptypes else [])
    _fixed2 = arg_pairs[:_n_fixed2]
    _vararg2 = arg_pairs[_n_fixed2:]
    _lst2 = gen._new_val('MojoList *', "mojo_list_new ()")
    for _at2, _av2 in _vararg2:
        _av2 = gen._coerce_to_type(_at2, 'int64_t', _av2)
        gen._emit(f"  mojo_list_append_int ({_lst2}, {_av2});")
    _trailing_pairs = []
    for _i2, _tpt in enumerate(_trailing_ptypes):
        _tname = (_trailing_names_defaults[_i2][0]
                 if _i2 < len(_trailing_names_defaults) else None)
        if _tname is not None and _tname in kwarg_dict:
            _trailing_pairs.append(kwarg_dict.pop(_tname))
        elif (_i2 < len(_trailing_names_defaults)
              and _trailing_names_defaults[_i2][1] is not None):
            _trailing_pairs.append(
                gen._default_expr_to_pair(_trailing_names_defaults[_i2][1]))
        else:
            _trailing_pairs.append((_tpt, '0'))
    arg_pairs = _fixed2 + [('MojoList *', _lst2)] + _trailing_pairs
    return arg_pairs, kwarg_dict


def _lower_named_call(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Final dispatch for user-defined and C stdlib functions."""
    # `_locally_binds_name` gate: BUILTIN_VALUE_MAP's entries (open,
    # filter, enumerate, str, len, sorted, ...) are all ordinary
    # identifiers a module can legally shadow with its own top-level
    # def/import (e.g. Lib/fnmatch.py's `def filter(names, pat):`,
    # Lib/tokenize.py's `def open(filename):`). Every per-branch early
    # return above this point in `_lower_call` already special-cases the
    # handful of names it recognizes structurally (some gated on this
    # same check, some not — see each one's own comment), but ANY
    # BUILTIN_VALUE_MAP name that falls all the way through to this
    # final, generic dispatch (either because it has no dedicated early
    # branch at all — `filter`/`map`/`print`/`range`/`max`/`min`/... — or
    # because its own early branch's gate correctly declined to intercept
    # a locally-bound name and let it fall through) must NOT be re-routed
    # to the builtin runtime symbol here: `self.BUILTIN_VALUE_MAP.get(
    # fname_raw, self._func_csym(fname_raw))`'s `.get()` unconditionally
    # preferred the map entry whenever `fname_raw` was a key, completely
    # ignoring whether THIS module shadows it — e.g. `open`'s own
    # dedicated early-return gate (a few hundred lines up) correctly
    # skips `_lower_builtin_open` when shadowed, but the call then fell
    # through everything else unmatched and landed HERE, where `'open' in
    # BUILTIN_VALUE_MAP` won regardless, still emitting a call to
    # `mojo_open_file` instead of the user's own `_func_csym('open')`
    # symbol (confirmed via a real shadowing repro: `fn open(x: Int) ->
    # Int: ...` compiled to `mojo_open_0c85c9` but every call site still
    # read `mojo_open_file(...)`). `_func_csym` already produces the
    # exact right symbol for a shadowing definition (same `_safe_name` +
    # overload-suffix scheme the definition itself used), so route
    # straight to it, bypassing BUILTIN_VALUE_MAP entirely, whenever this
    # module locally binds the name.
    if fname_raw in gen.BUILTIN_VALUE_MAP and gen._locally_binds_name(fname_raw):
        fname = gen._func_csym(fname_raw)
    # C reserved function renaming
    elif (fname_raw in gimple_ctypes._C_RESERVED_FUNCS and fname_raw not in gen.func_return_types
            and fname_raw not in gimple_ctypes._FORCE_RENAME_RESERVED
            and fname_raw not in gen.imported_symbols):
        fname = gen.BUILTIN_VALUE_MAP.get(fname_raw, fname_raw)
    else:
        # _func_csym applies the same overload suffix the definition used.
        fname = gen.BUILTIN_VALUE_MAP.get(fname_raw, gen._func_csym(fname_raw))
    if fname == 'main' and fname_raw in gen._unresolved_import_aliases:
        # See bugs/hard/CODEGEN_aliased_external_import_no_backing_
        # symbol.md: `from X import Y as main; main()` — 'main' is kept
        # a fixed, unmangled C name for THIS module's own synthesized
        # entry point (see the NO_OVERLOAD_MANGLE note above), so an
        # imported name that merely happens to be ALIASED to 'main'
        # must never be emitted (stub or call) under that same literal
        # C symbol — "conflicting types for 'main'; have
        # 'int(int, const char **)'" otherwise. Mirrors _C_RESERVED_
        # FUNCS's own definition/call-site rename chokepoint pattern.
        fname = '_unresolved_import_main'
    ret_type = gen.func_return_types.get(fname_raw, 'int64_t')

    # Auto-stub completely unknown names (e.g. bracket params like `cmp_fn: fn(T,T)->Bool`
    # that the parser skips). Without a declaration GCC gives "implicit function declaration".
    # Skip the self-host hardcoded forward-declared symbols — gen_module's
    # `_is_selfhost_file` block declares those concretely, and a variadic
    # stub here would conflict ("conflicting types").
    _is_unknown = (fname_raw not in gen.func_return_types
                   and fname_raw not in gen.imported_symbols
                   and fname not in gen._KNOWN_SIGS
                   and fname_raw not in gen.BUILTIN_VALUE_MAP
                   and fname_raw not in gimple_ctypes._C_RESERVED_FUNCS
                   and fname not in gimple_codegen._SELFHOST_HARDCODED_FUNCS)
    if _is_unknown:
        _stub_key = gimple_ctypes._stub_guard_name(fname)
        if fname_raw in gen._unresolved_import_aliases:
            # See bugs/hard/CODEGEN_aliased_external_import_no_backing_
            # symbol.md: a name imported from a module load_module()
            # couldn't resolve (relative import, or a real external/
            # unmodeled package) will NEVER get a real definition
            # anywhere in this compile — unlike the ordinary "unknown
            # name" case just below (ret_type=int64_t bare forward
            # decl), which is fine because it's typically a same-TU
            # forward reference that a real definition follows later.
            # A bare decl here just moves the failure to link time
            # ("undefined symbols for architecture arm64"), exactly
            # the same shape _lower_struct_method_call's own auto-stub
            # path already hit and fixed (weak definition instead of
            # decl-only) for the analogous "inherited from an
            # unmodeled base class" case.
            _stub_decl = (f'#ifndef {_stub_key}\n#define {_stub_key}\n'
                          f'__attribute__((weak)) int64_t {fname} (...) '
                          f'{{ mojo_print ((char *)"{fname_raw}: unavailable in compiled mode '
                          f'(imported from an unresolved external/relative module)"); '
                          f'return (int64_t)0; }}\n#endif')
        else:
            # See the _unresolved_import_aliases branch just above for
            # the general reasoning (bugs/hard/CODEGEN_aliased_
            # external_import_no_backing_symbol.md). This is the SAME
            # "declared but never defined" shape for the remaining
            # _is_unknown cases (Python builtins this codegen has no
            # lowering for — `vars`/`bytes`/`hash`/`next`/`object`/
            # `divmod`/`callable`/... — and the "bracket params,
            # implicit fnptrs" placeholders the comment above
            # mentions). By construction, anything reaching this branch
            # is NOT in func_return_types — and every top-level
            # function's return type is pre-registered in an earlier
            # pass (well before any function body is lowered, see
            # gen_module's Pass 1/1.3 registration), so a genuine
            # same-TU forward reference to a function defined later in
            # this file can never actually reach `_is_unknown=True` —
            # only a name that will NEVER be defined anywhere in this
            # compile does. A bare decl here was therefore never
            # actually saving anything: it only postponed today's
            # inevitable "implicit declaration" compile failure into an
            # equally inevitable "undefined symbols" LINK failure for
            # any such name that's actually called at runtime (dead/
            # never-called placeholders are unaffected either way).
            # Confirmed empirically via the full quality gate (compile_
            # stdlib.py 664/664 unchanged, 0 new skips) before landing.
            _stub_decl = (f'#ifndef {_stub_key}\n#define {_stub_key}\n'
                          f'__attribute__((weak)) int64_t {fname} (...) '
                          f'{{ mojo_print ((char *)"{fname_raw}: unavailable in compiled mode"); '
                          f'return (int64_t)0; }}\n#endif')
        if _stub_decl not in gen._elaborated_externs:
            gen._elaborated_externs.append(_stub_decl)
    if fname in gen._KNOWN_SIGS:
        ret_type = gen._KNOWN_SIGS[fname][0]

    # A renamed C-reserved *builtin* passthrough (e.g. calling libm exp2 with
    # no local def) needs a variadic extern. But if there's a local Mojo def of
    # the same name (now overload-mangled), it already has a typed forward decl
    # — emitting the variadic stub too would conflict. Skip those.
    if (fname != fname_raw and fname_raw in gimple_ctypes._C_RESERVED_FUNCS
            and fname_raw not in gen._mangled_funcs):
        if fname not in gen._renamed_builtin_calls:
            gen._renamed_builtin_calls[fname] = ret_type

    arg_pairs = [gen.lower_expr(a) for a in node.args]
    kwargs    = getattr(node, 'kwargs', []) or []
    kwarg_dict = {kname: gen.lower_expr(kexpr) for kname, kexpr in kwargs}

    # Disambiguate a call to a `(*args, **kwargs)`-declared callee by
    # the CALL SITE's own shape, not the callee's signature alone (see
    # bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.
    # md). _signature_ctypes types such a callee's `*args` as a plain
    # concrete `MojoList *` (no packing) — correct for the spread-
    # forwarding idiom (`f(*a, **k)`: the parser wraps each spread in
    # UnaryOp(op='*'/'**', operand=...), and _lower_UnaryOp passes an
    # already-packed MojoList*/MojoDict* through UNCHANGED, so
    # `arg_pairs` already has the right shape and must be left alone)
    # — but WRONG for an ordinary literal-argument call to the same
    # shape (`CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_size_t)`, no
    # spreads at all): the extra positional args would otherwise be
    # coerced 1:1 against `*args`'s/`**kwargs`'s concrete param types
    # instead of being packed, producing an arity mismatch or a silent
    # type-confusion bug. Detect a real spread from the ORIGINAL AST
    # args — a UnaryOp(op='*'/'**', ...) survives lowering as a
    # same-shaped pass-through, so it can't be told apart from a real
    # packed value after the fact. `_func_kwargs_slot` is only
    # populated for genuine user free functions (gen_module's own
    # FunctionDef registration pass), so this never fires for struct
    # methods (a separate call-lowering path, out of scope here) or
    # unresolved/imported names with no recorded signature.
    _call_has_spread = any(isinstance(_a, gimple_ctypes.UnaryOp) and _a.op in ('*', '**')
                           for _a in node.args)
    _kwslot_for_pack = gen._func_kwargs_slot.get(fname)
    if _kwslot_for_pack is None:
        _kwslot_for_pack = gen._func_kwargs_slot.get(fname_raw, -1)
    if _kwslot_for_pack >= 0 and not _call_has_spread:
        # Whether the callee ALSO declares a real `*args` before its
        # `**kwargs` (the `f(self, *args, **kwargs)` forwarding pattern,
        # which gets a concrete `MojoList *` C param) — as opposed to
        # `**kwargs` being its only vararg-style parameter (`def
        # f(**kwargs)`, exactly one `MojoDict *` C param; see
        # `_func_kwargs_has_vararg`'s own docstring). Defaults to True
        # (the old, always-pack-a-list-too behavior) when unknown, since
        # every call site that reaches this branch at all necessarily
        # has a `_func_kwargs_slot` entry, and both dicts are populated
        # together at the exact same registration site — this fallback
        # only matters for some other, not-yet-audited path that might
        # populate `_func_kwargs_slot` without its sibling.
        _has_vararg = gen._func_kwargs_has_vararg.get(
            fname, gen._func_kwargs_has_vararg.get(fname_raw, True))
        _n_fixed = max(0, _kwslot_for_pack - 1) if _has_vararg else _kwslot_for_pack
        _fixed_pairs = arg_pairs[:_n_fixed]
        _vararg_pairs = arg_pairs[_n_fixed:]
        _packed_dict_pair = ('MojoDict *', gen._pack_kwargs_dict(kwarg_dict))
        if _has_vararg:
            _lst = gen._new_val('MojoList *', "mojo_list_new ()")
            for _at, _av in _vararg_pairs:
                _av = gen._coerce_to_type(_at, 'int64_t', _av)
                gen._emit(f"  mojo_list_append_int ({_lst}, {_av});")
            arg_pairs = _fixed_pairs + [('MojoList *', _lst), _packed_dict_pair]
        else:
            # No `*args` slot at all: any leftover positional args (a
            # real Python-level TypeError against a kwargs-only
            # signature, but this codegen has no type-checker to catch
            # it earlier) have nowhere valid to go — pass them through
            # unchanged ahead of the single `MojoDict *` param rather
            # than silently discarding them, mirroring `_fixed_pairs`'
            # existing "leave it to the generic arity/coercion handling
            # further down" convention for a genuinely malformed call.
            arg_pairs = _fixed_pairs + _vararg_pairs + [_packed_dict_pair]
        kwarg_dict = {}

    # `def f(fixed, *args, trailing_kwonly=default, ...)` — a vararg
    # followed by more (keyword-only) params but no `**kwargs`; see
    # `_pack_vararg_trailing_params`'s own docstring for the full
    # rationale (shared with `_gen_stmt_ExprStmt`'s statement-level
    # twin call path below).
    arg_pairs, kwarg_dict = gen._pack_vararg_trailing_params(
        fname, fname_raw, arg_pairs, kwarg_dict, _call_has_spread)

    # Keyword argument padding for known functions
    if fname_raw == 'compile_to_gimple':
        if 'do_imports' in kwarg_dict: arg_pairs.append(kwarg_dict['do_imports'])
        elif len(arg_pairs) < 2:       arg_pairs.append(('int', '0'))
        if 'filename' in kwarg_dict:   arg_pairs.append(kwarg_dict['filename'])
        elif len(arg_pairs) < 3:       arg_pairs.append(('char *', '0'))
    if fname_raw == 'interpret_and_execute':
        if 'filename' in kwarg_dict:   arg_pairs.append(kwarg_dict['filename'])
        elif len(arg_pairs) < 2:       arg_pairs.append(('int', '0'))
    if fname_raw == 'format_ast'  and len(arg_pairs) == 1: arg_pairs.append(('int', '0'))
    if fname_raw == 'emit_module' and len(arg_pairs) == 1: arg_pairs.append(('int', '0'))

    # General kwarg padding when expected param count is known. A call
    # compiled in isolation (e.g. monomorphize.py's instantiate(), which
    # builds a brand-new GimpleGen per generic instantiation with none of
    # the surrounding module's imports registered) never populates
    # func_param_types for an imported function — but a C-stdlib-style
    # function like `memcpy` still has its real arity in `_KNOWN_SIGS`.
    # Falling back to that (rather than leaving expected_params empty)
    # is what lets a keyword-only call like std.memory's
    # `memcpy(dest=.., src=.., count=..)` still get its arguments bound
    # here instead of silently emitting a bare, argument-less `memcpy()`
    # — confirmed cause of a cascading, confusing GCC error that broke
    # every cold-CAS-cache stdlib build (investigated 2026-07-15). Purely
    # additive/narrower than dropping kwargs outright: a name with no
    # entry in _KNOWN_SIGS either (e.g. a struct constructor like
    # ARM64JIT, called with stale/vestigial kwargs its real 0-arg
    # constructor ignores) is untouched, exactly as before.
    expected_params = gen.func_param_types.get(fname_raw, [])
    if not expected_params and fname_raw in gen._KNOWN_SIGS:
        expected_params = gen._KNOWN_SIGS[fname_raw][1]
    elif not expected_params and fname in gen._KNOWN_SIGS:
        # `fname_raw` (the ORIGINAL Python name, e.g. 'eval') is never
        # itself a _KNOWN_SIGS key — only its BUILTIN_VALUE_MAP-renamed
        # C symbol ('mojo_eval') is. Python's 1-arg `eval(expr)` (the
        # overwhelmingly common form; globals/locals default to the
        # caller's own scope) called this renamed 3-arg C function with
        # only 1 argument, a hard "too few arguments" compile error —
        # found via Tools/build/generate_token.py's own `eval(string)`.
        # mojo_eval's own globals/locals params are unused anyway (a
        # documented eval() stub — real eval() can't run in a compiled
        # C bootstrap), so padding with NULL below is exactly right,
        # not just "doesn't crash."
        expected_params = gen._KNOWN_SIGS[fname][1]
    if expected_params and len(arg_pairs) < len(expected_params):
        kwarg_values = list(kwarg_dict.values()) if kwarg_dict else []
        # Free-function param defaults: `def greet(name: String = "world")`
        # called as `greet()` must pad with "world", not NULL/0.
        _dflts = gen._func_param_defaults.get(fname) or gen._func_param_defaults.get(fname_raw) or []
        _dflt_by_pos = {pn: _dv for pn, _dv in _dflts}
        # `param_defaults` only holds entries for params THAT HAVE one,
        # starting at the first defaulted position — i.e. the last
        # len(_dflts) slots (a leading required param like
        # `check_like(name, ok=True)` shifts the run off zero, and plain
        # `_dflts[_pos]` indexing then missed every time, padding the
        # omitted arg with 0 — BUG-2026-020).
        _first_dflt = len(expected_params) - len(_dflts)
        # `**kwargs` slot: pack the LITERAL keyword arguments into a real
        # MojoDict (see _func_kwargs_slot). `f(**d)` forwarding is a
        # different shape — the parser flattens the spread into a single
        # positional arg, so it never reaches this padding loop.
        _kw_slot = gen._func_kwargs_slot.get(fname)
        if _kw_slot is None:
            _kw_slot = gen._func_kwargs_slot.get(fname_raw, -1)
        while len(arg_pairs) < len(expected_params):
            if _kw_slot >= 0 and len(arg_pairs) == _kw_slot:
                arg_pairs.append(('MojoDict *', gen._pack_kwargs_dict(kwarg_dict)))
                kwarg_values = []
                continue
            if kwarg_values:
                arg_pairs.append(kwarg_values.pop(0))
                continue
            # Map the missing positional slot to its param name via the
            # C-type-list position (param names aren't in expected_params).
            _pos = len(arg_pairs)
            _dv = None
            if _dflts and 0 <= _pos - _first_dflt < len(_dflts):
                _dv = _dflts[_pos - _first_dflt][1]
            if _dv is not None:
                arg_pairs.append(gen._default_expr_to_pair(_dv))
            else:
                arg_pairs.append(('int', '0'))

    # exit(msg)/quit(msg): Python's builtin exit()/quit() (and
    # sys.exit(), which redirects here the same way) accept an
    # arbitrary object, not just an int — a string prints as an error
    # message (exit code 1), matching real Python's SystemExit(msg)
    # behavior on an uncaught exit. `exit`/`quit` are otherwise treated
    # as a direct passthrough to libc's real `exit(int status)` (see
    # _C_RESERVED_FUNCS), so `exit("some message")` — real code, e.g.
    # Tools/build/generate_token.py's own `exit('\n'.join(...))` —
    # passed a `char *` straight to libc exit(), a hard "makes integer
    # from pointer without a cast" compile error, not just wrong
    # behavior. A bare int arg (the common case) is unaffected: this
    # only intercepts when the argument ISN'T already int-shaped.
    if fname_raw in ('exit', 'quit') and len(arg_pairs) == 1:
        _ex_t, _ex_v = arg_pairs[0]
        if _ex_t not in ('int', 'int64_t', '_Bool'):
            _msg = gen._stringify_value(_ex_t, _ex_v)
            gen._emit_call('void', '', 'mojo_print_stderr', [('char *', _msg)])
            gen._emit("  exit (1);")
            return 'int64_t', gen._new_val('int64_t', '(int64_t)0')

    # int(s, base) — drop the base arg
    if fname_raw == 'int' and len(arg_pairs) > 1:
        arg_pairs = arg_pairs[:1]

    # abs of an integer → inline `x < 0 ? -x : x`.
    # We deliberately do NOT call the libc `llabs`: gcc -fgimple ICEs
    # (gimplify_var_or_parm_decl) when the recognized builtin llabs is applied
    # to a local computed temp. Inlining is also strictly better — no libc call
    # for a one-instruction operation.
    # TODO(gimple-builtins): revisit once the gcc -fgimple builtin-arg ICE is
    # fixed upstream; we could then route abs back through llabs if desired.
    if fname_raw in ('abs', 'mojo_abs') and len(arg_pairs) == 1:
        at, av = arg_pairs[0]
        if at in ('int64_t', 'long long') or at.endswith(' *'):
            v = gen._ensure_local('int64_t', av if not at.endswith(' *')
                                   else gen._new_val('int64_t', f'(int64_t){av}'))
            zero = gen._new_val('int64_t', '(int64_t)0')
            neg  = gen._new_val('_Bool', f'{v} < {zero}')
            negv = gen._new_val('int64_t', f'-{v}')
            return 'int64_t', gen._new_val('int64_t', f'{neg} ? {negv} : {v}')

    # range(stop) or range(start, stop, step)
    if fname_raw == 'range':
        if len(arg_pairs) == 1:
            _zero = gen._new_val('int64_t', '(int64_t) 0')
            arg_pairs = [('int64_t', _zero), arg_pairs[0]]
        elif len(arg_pairs) == 3:
            fname = 'mojo_range3'
        return 'void *', gen._call_expr('void *', fname, arg_pairs)

    # min/max over scalar args → fold into nested ternaries (avoids the
    # mojo_min(void*) variadic-pack signature, which we don't emit packs for).
    _NUM = ('int64_t', 'int', '_Bool', 'double', 'float',
            'uint64_t', 'int32_t', 'uint32_t', 'int16_t', 'uint16_t',
            'int8_t', 'uint8_t', 'size_t', 'long', 'short')
    if (fname_raw in ('min', 'max') and arg_pairs
            and all(t in _NUM for t, _ in arg_pairs)):
        op = '<' if fname_raw == 'min' else '>'
        def _as_i64(t, v):
            return v if t == 'int64_t' else gen._new_val('int64_t', f'(int64_t){v}')
        acc = _as_i64(*arg_pairs[0])
        for t, v in arg_pairs[1:]:
            bv = _as_i64(t, v)
            cond = gen._new_val('_Bool', f'{acc} {op} {bv}')
            acc = gen._new_val('int64_t', f'{cond} ? {acc} : {bv}')
        return 'int64_t', acc

    # min/max over string-ish (char* and/or single-char) args → same
    # ternary-fold approach as the numeric case above, but lexicographic
    # comparison needs a real strcmp-style call (`<`/`>` directly on two
    # char* pointers compares ADDRESSES, not string content) —
    # mojo_cstr_cmp mirrors the string-equality lowering above (`==`/
    # `!=`) doing the identical strcmp-based comparison for the same
    # char* representation. A bare 'char' operand (e.g. a value read via
    # `_mojo_at_char`/string indexing, as opposed to a char*-boxed
    # single-character string) is normalized to a real 1-char string via
    # mojo_char_to_str first, mirroring the equality lowering's own
    # `_to_char_star` helper immediately above. Without this, a 2-arg
    # call mixing these representations, like Tools/build/deepfreeze.py's
    # `maxchar = max(maxchar, c)` (maxchar: char*, c: char, from
    # iterating a str), fell through to the generic call-expr path
    # below, calling the real runtime's `mojo_max(void *args)`
    # (single-iterable-of-ints signature) with 2 scalar args — a hard
    # "too many arguments to function 'mojo_max'" -fgimple compile
    # error, not a subtler runtime bug.
    _STRINGY = ('char *', 'char')
    if (fname_raw in ('min', 'max') and len(arg_pairs) >= 2
            and all(t in _STRINGY for t, _ in arg_pairs)
            and any(t == 'char *' for t, _ in arg_pairs)):
        def _as_cstr(t, v):
            if t == 'char *':
                return v
            return gen._call_expr('char *', 'mojo_char_to_str', [('char', v)])
        acc = _as_cstr(*arg_pairs[0])
        for t, v in arg_pairs[1:]:
            cv = _as_cstr(t, v)
            cmp_i = gen._call_expr('int', 'mojo_cstr_cmp', [('char *', acc), ('char *', cv)])
            cmp64 = gen._new_val('int64_t', f'(int64_t){cmp_i}')
            zero = gen._new_val('int64_t', '(int64_t)0')
            # cmp64 < 0 means acc sorts strictly before cv (acc is the
            # lexicographically smaller string); max wants the larger of
            # the two, so max replaces acc with cv exactly when
            # cmp64 < 0, min replaces when cmp64 > 0 — equal strings
            # keep acc either way, matching the numeric fold's identical
            # "keep acc on tie" behavior above.
            replace_op = '<' if fname_raw == 'max' else '>'
            cond = gen._new_val('_Bool', f'{cmp64} {replace_op} {zero}')
            acc = gen._new_val('char *', f'{cond} ? {cv} : {acc}')
        return 'char *', acc

    # round(x, ndigits) → round(x*10^n)/10^n (libm round() takes 1 arg only)
    if fname_raw == 'round' and len(arg_pairs) == 2:
        (xt, xv), (nt, nv) = arg_pairs
        xd = xv if xt == 'double' else gen._new_val('double', f'(double){xv}')
        nd = nv if nt == 'double' else gen._new_val('double', f'(double){nv}')
        p  = gen._new_val('double', f'pow (10.0, {nd})')
        scaled = gen._new_val('double', f'{xd} * {p}')
        r = gen._new_val('double', f'round ({scaled})')
        return 'double', gen._new_val('double', f'{r} / {p}')

    # int(x) — direct cast for already-numeric types. Only a STRING
    # argument (`int("42")`) should route through the mojo_make_int
    # runtime helper (parses digits, _KNOWN_SIGS declares it as
    # `int64_t mojo_make_int(char *)`); a numeric argument
    # (`int(self.fraction * float(totalWidth))`, `int(True)`, an
    # already-int64_t value) previously fell through to that same
    # generic BUILTIN_VALUE_MAP['int'] = 'mojo_make_int' call
    # unconditionally, and generic arg coercion then blindly cast the
    # numeric value to the callee's declared `char *` param type
    # (`_t8 = (char *)_t6;` reinterpreting a double's bit pattern as a
    # pointer) instead of converting it — a `-fgimple` "invalid types
    # in conversion to integer" hard error at the following
    # `mojo_make_int(_t8)` call (real repro: Tools/unittestgui/
    # unittestgui.py's `ProgressBar.paint`: `width = int(self.fraction
    # * float(totalWidth))`). C's double->int64_t cast truncates
    # toward zero, matching Python's `int(float)` semantics, so a
    # straight cast is correct here — mirrors the analogous `float(x)`
    # direct-cast special case immediately below.
    if fname_raw == 'int' and len(arg_pairs) == 1:
        at, av = arg_pairs[0]
        if at == 'double':
            return 'int64_t', gen._new_val('int64_t', f'(int64_t){av}')
        if at == 'int64_t':
            return 'int64_t', av
        if at in ('int', '_Bool'):
            return 'int64_t', gen._new_val('int64_t', f'(int64_t){av}')

    # float(x) — direct cast for numeric types
    if fname_raw == 'float' and arg_pairs:
        at, av = arg_pairs[0]
        if at in ('int64_t', 'int', '_Bool'): return 'double', gen._new_val('double', f'(double){av}')
        if at == 'double':                    return 'double', av

    # bool(x) — Python truthiness is container LENGTH, not pointer
    # identity (`bool([])`/`bool({})`/`bool(set())` are False even though
    # each empty container's pointer is a real, non-NULL allocation). The
    # generic `bool(...)` → `mojo_make_bool((int)ptr)` path compared
    # pointer-non-nullness, so the self-hosted binary compiled `bool(empty
    # container)` to True — a native-vs-Python divergence (same semantics
    # `_ensure_bool_cond` already implements for if/while conditions via
    # _CONTAINER_LEN_FN, but a bool() CALL was the one path that never
    # used it). Mirror that here so both paths agree.
    if fname_raw == 'bool' and len(arg_pairs) == 1:
        _bt, _bv = arg_pairs[0]
        if _bt in gen._CONTAINER_LEN_FN:
            # GIMPLE-valid statement form, identical to
            # _ensure_bool_cond's own container branch (a bare
            # `len != 0` expression typed int is rejected as a "bogus
            # comparison result type").
            _n = gen._call_expr('int64_t', gen._CONTAINER_LEN_FN[_bt],
                                 [(_bt, _bv)])
            _b = gen._new_temp('_Bool')
            _z = gen._new_temp('int64_t')
            gen._emit(f'  {_z} = (int64_t)0;')
            gen._emit(f'  {_b} = {_n} != {_z};')
            return '_Bool', _b

    if ret_type == 'void':
        return gen._void_call(fname, arg_pairs)
    t = gen._call_expr(ret_type, fname, arg_pairs)
    if fname_raw in gen._return_elem_types:
        # Annotated `-> tuple[...]` functions resolve to boxed int64_t (see
        # _mojo_type), so unlike the MojoList*-typed case above the elem
        # must be recorded for ANY ret_type — consumers resolve the boxed
        # handle back via _actual_types. Keyed on the callee having a
        # recorded return elem type, which only true container returns get.
        gen._elem_types[t] = gen._return_elem_types[fname_raw]
        if ret_type == 'MojoList *':
            gen._actual_types[t] = ret_type
        elif ret_type in ('int', 'int64_t'):
            gen._actual_types[t] = 'MojoList *'
    # A function that RETURNS a generator (`def mk(): return counter(3)`,
    # typed `MojoGenerator *` by Pass 1.3e/1.3f) — record the underlying
    # generator function's api on the call's result temp (Pass 1.3f-gen
    # pre-pass populates self._fn_returns_generator), so any later
    # consumer of the value (`g = mk(); for x in g:`, `for x in mk():`,
    # `consume(mk())`) recovers the right base/value_ctype exactly like a
    # direct generator call's own call-site recording (see _lower_call's
    # generator branch). See bugs/CODEGEN_compiled_generator_not_first_
    # class_value.md.
    if ret_type == 'MojoGenerator *':
        _gf = gen._fn_returns_generator.get(fname_raw)
        if _gf is not None and _gf in gen._generator_api:
            gen._generator_var_api[t] = gen._generator_api[_gf]
    return ret_type, t


def _resolve_overload(gen, candidates: list, args: list, kwargs: list | None) -> dict | None:
    """Pick the candidate overload matching a call site's argument count/
    types, from a list of signature dicts as built by the Pass 2b-bis
    registration loop (each: overload_id, param_names, param_ctypes,
    min_arity, max_arity).

    Mirrors real Mojo's observed overload resolution closely enough for
    already-valid, already-typechecked source (which is all this compiler
    ever transpiles — genuine ambiguity is a hard error in real Mojo, so a
    real call site should never present one): filter by arity range
    (accounting for default parameters), then by keyword-argument names,
    then score remaining candidates by per-position exact C-type match.
    Only ever calls the side-effect-free `_quick_type` here — the actual
    `lower_expr` (which emits code) happens once, after the caller uses
    the chosen candidate to build the real call.
    """
    if not candidates:
        return None
    kwargs = kwargs or []
    call_arity = len(args) + len(kwargs)
    kwarg_names = [kn for kn, _ke in kwargs]
    survivors = [c for c in candidates
                 if c['min_arity'] <= call_arity <= c['max_arity']
                 and all(kn in c['param_names'] for kn in kwarg_names)]
    if not survivors:
        return None
    if len(survivors) == 1:
        return survivors[0]

    arg_types = [gen._quick_type(a) for a in args]
    # Keyword args bind by name to whichever positional slot that name
    # occupies in a given candidate; scored per-candidate below since
    # candidates can disagree on where a name falls.
    def _score(cand: dict) -> int:
        score = 0
        # For a `*args` pack candidate, every positional arg at or past
        # pre_star_count is consumed by the pack, not by a fixed param —
        # param_ctypes past that point belongs to necessarily-keyword-only
        # params (Mojo syntax forbids positional args after a `*args`), so
        # comparing a pack-bound arg's type against one of those ctypes at
        # the same flat index is a category error, not a real type match
        # (confirmed: it let DeviceGraphBuilder.add_function's *args-pack
        # overload lose a tie to a same-arity sibling by a coincidental
        # int64_t/int64_t collision at a position that meant nothing).
        _cap = cand['pre_star_count'] if cand.get('has_varargs') else len(arg_types)
        for i, at in enumerate(arg_types):
            if i >= _cap:
                break
            if i < len(cand['param_ctypes']) and cand['param_ctypes'][i] == at:
                score += 1
        for kn, ke in kwargs:
            if kn in cand['param_names']:
                idx = cand['param_names'].index(kn)
                if idx < len(cand['param_ctypes']) and cand['param_ctypes'][idx] == gen._quick_type(ke):
                    score += 1
        return score

    best = max(survivors, key=_score)
    best_score = _score(best)
    # Same arity, but (when best_score == 0) no candidate's declared param
    # type matched any argument's type at all — our type erasure genuinely
    # can't tell these overloads apart (e.g. two structurally-different
    # Mojo generic types, like Tuple[T,T] and Interval[T], both erasing to
    # int64_t in this codegen's type system today). This used to return
    # None here so the caller would fall back to an unsuffixed call
    # against a "catch-all variadic stub" — but survivors has 2+ entries
    # whenever we reach this point (the len(survivors)==1 case returns
    # above), and gimple_codegen always hash-suffixes a method once it has
    # 2+ overloads, so that stub is never actually defined: the fallback
    # call site links (against -undefined dynamic_lookup) but crashes at
    # dyld resolution the moment it's actually invoked (confirmed via
    # AMDBufferResource/String in build/libmojostdlib.dylib — the "use"
    # side's assumption didn't match what the "generate" side emits).
    # Picking a real, defined candidate deterministically — same
    # first-in-declaration-order rule already used for genuine ties below
    # — is strictly safer: a plausible overload beats a guaranteed crash.
    ties = [c for c in survivors if _score(c) == best_score]
    if len(ties) > 1:
        gimple_ctypes._debug_note('ambiguous or type-indistinguishable overload, picking first in declaration order',
                    f"candidates={[c['overload_id'] for c in ties]}")
    return ties[0]


def _lower_varargs_pack(gen, pack_args: list) -> tuple:
    """Lower the call-site positional args matched to a `*args` pack
    parameter into a single MojoList* value. A lone arg that already
    lowers to a MojoList* (e.g. `*args` re-forwarded from the caller's
    own pack param, as in `def f(*args): g(*args)`) is passed straight
    through unchanged; otherwise each value is boxed individually,
    mirroring _emit_call's trailing-'...' packing convention."""
    lowered = [gen.lower_expr(a) for a in pack_args]
    if len(lowered) == 1 and lowered[0][0] == 'MojoList *':
        return lowered[0]
    lst = gen._new_val('MojoList *', "mojo_list_new ()")
    for atype, aval in lowered:
        aval = gen._coerce_to_type(atype, 'int64_t', aval)
        gen._emit(f"  mojo_list_append_int ({lst}, {aval});")
    return ('MojoList *', lst)


def _pack_kwargs_dict(gen, kwarg_pairs) -> str:
    """Build a real MojoDict from a call site's LITERAL keyword arguments,
    for a callee whose `**kwargs` parameter is a concrete `MojoDict *`
    (see _func_kwargs_slot / gen_func's param loop).

    `kwarg_pairs` maps each keyword name to its ALREADY-LOWERED
    (ctype, value) pair — re-lowering here would emit the argument
    expression's side effects a second time.

    String values go through mojo_dict_set_str so the dict's own value
    type is right (mojo_dict_set_int would store the char* as an integer
    and later read it back as one). Everything else — ints, doubles,
    pointers — goes through mojo_dict_set_int, which _emit_call coerces,
    matching how `d[k] = v` already lowers a subscript store."""
    d = gen._new_val('MojoDict *', 'mojo_dict_new ()')
    _val_ty = ''
    for kname in (kwarg_pairs or {}):
        kt, kv = kwarg_pairs[kname]
        _val_ty = kt if not _val_ty or _val_ty == kt else 'int64_t'
        if kt == 'char *':
            gen._emit_call('void', '', 'mojo_dict_set_str',
                            [('MojoDict *', d), ('char *', f'"{gimple_ctypes._c_escape(kname)}"'),
                             ('char *', kv)])
        else:
            gen._emit_call('void', '', 'mojo_dict_set_int',
                            [('MojoDict *', d), ('char *', f'"{gimple_ctypes._c_escape(kname)}"'),
                             (kt, kv)])
    if _val_ty:
        gen._dict_val_types[d] = _val_ty
    return d


def _build_call_args_for_candidate(gen, chosen: dict, args: list, kwargs: list | None,
                                   defaults: dict | None = None) -> list:
    """Build the C arg-value list (self excluded) for a resolved struct
    constructor/method overload. When the overload has a `*args` pack
    parameter (chosen['has_varargs']), the params before it are lowered
    positionally, the pack itself is boxed via _lower_varargs_pack, and
    every param after it is necessarily keyword-only (Mojo syntax) so is
    bound by name from kwargs, defaulting to 0 when omitted — the old flat
    by-position scheme had no slot for the pack at all. Otherwise,
    unchanged from before: args lowered positionally, kwargs overlaid by
    name, then zero-padded up to max_arity."""
    kw = dict(kwargs or [])
    if chosen.get('has_varargs'):
        pre_n = chosen['pre_star_count']
        param_names = chosen['param_names']
        # Pre-star params bind positionally first (an actual call-site
        # positional arg wins), then by keyword name, then their real
        # default. The old code only ever consulted `args[:pre_n]` —
        # real Python allows a pre-star param to be passed by KEYWORD
        # too (`def __init__(self, x=None, *args, **kwargs)` called as
        # `f(x=1)`), and when it was, this loop produced NO entry for
        # it at all (not even a placeholder), desyncing the whole
        # trailing arg list by one slot and dropping the value outright
        # — e.g. Lib/calendar.py's `_CLIDemoCalendar(highlight_day=today)`
        # against `def __init__(self, highlight_day=None, *args,
        # **kwargs)` silently lost `today` and emitted one argument too
        # few ("too few arguments ... expected 4, have 3").
        out = []
        for _i in range(pre_n):
            if _i < len(args):
                out.append(gen.lower_expr(args[_i]))
                continue
            _pname = param_names[_i] if _i < len(param_names) else None
            if _pname is not None and _pname in kw:
                out.append(gen.lower_expr(kw.pop(_pname)))
                continue
            _dflt = (defaults or {}).get(_pname) if _pname else None
            out.append(gen._default_expr_to_pair(_dflt))
        out.append(gen._lower_varargs_pack(args[pre_n:]))
        # Post-star params are necessarily keyword-only (Python/Mojo
        # syntax). A `**kwargs` slot among them is a real MojoDict*
        # param — pack every keyword arg left unconsumed by the
        # pre-star binding above and by other named post-star params
        # into it (mirrors the non-varargs branch below), instead of
        # always leaving it null.
        for pname in param_names[pre_n:]:
            if pname.startswith('**'):
                continue
            out.append(gen.lower_expr(kw.pop(pname)) if pname in kw else ('int', '0'))
        if any(pn.startswith('**') for pn in param_names[pre_n:]):
            out.append(('MojoDict *', gen._pack_kwargs_dict(
                {_kn: gen.lower_expr(_kv) for _kn, _kv in kw.items()})))
        return out
    out = [gen.lower_expr(a) for a in args]
    # A `**kwargs` parameter is a concrete `MojoDict *` (see
    # _gen_struct_method's param loop), so literal keyword arguments at
    # the call site must be PACKED into a real dict. Otherwise the
    # zero-padding below filled that slot with `(MojoDict *)0` and every
    # `**kwargs` field read a null dict — the compiled-path half of the
    # `for fname in pat.fields:` failure (A5-BUG.md section 1).
    _kw_idx = -1
    for _i, _pn in enumerate(chosen['param_names']):
        if _pn.startswith('**'):
            _kw_idx = _i
            break
    for idx, pname in enumerate(chosen['param_names']):
        if pname not in kw:
            continue
        while len(out) <= idx:
            out.append(('int', '0'))
        out[idx] = gen.lower_expr(kw[pname])
    if _kw_idx >= 0:
        _named = set(chosen['param_names'])
        _rest = {}
        for _kn in kw:
            if _kn not in _named:
                _rest[_kn] = gen.lower_expr(kw[_kn])
        while len(out) <= _kw_idx:
            out.append(('int', '0'))
        out[_kw_idx] = ('MojoDict *', gen._pack_kwargs_dict(_rest))
    while len(out) < chosen['max_arity']:
        _dflt = (defaults or {}).get(chosen['param_names'][len(out)]) if len(out) < len(chosen['param_names']) else None
        if isinstance(_dflt, gimple_ctypes.BoolLiteral):
            out.append(('_Bool', '1' if _dflt.value else '0'))
        elif isinstance(_dflt, gimple_ctypes.StringLiteral):
            out.append(('char *', f'"{gimple_ctypes._c_escape(_dflt.value)}"'))
        elif isinstance(_dflt, (gimple_ctypes.IntLiteral, gimple_ctypes.FloatLiteral)):
            out.append(('int', str(_dflt.value)))
        elif isinstance(_dflt, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr, gimple_ctypes.SetExpr, gimple_ctypes.DictExpr)):
            out.append(('int64_t', '0'))
        else:
            out.append(('int', '0'))
    return out


def _lower_struct_constructor(gen, struct_name: str,
                              args: list, kwargs: list | None = None) -> tuple[str, str]:
    """
    Lower TypeName(field1, field2, ...) to allocation + field init + __init__ call.

    Uses _alloc_StructName() helper (emitted in preamble) because
    sizeof(T) is invalid in __GIMPLE body when T is not in the signature.
    """
    ctype  = f"{struct_name} *"
    t      = gen._new_temp(ctype)
    gen._struct_allocs_needed.add(struct_name)
    gen._emit(f"  {t} = _alloc_{struct_name} ();")

    # Same-file overload resolution: if this struct's __init__ overloads
    # (including any @fieldwise_init-synthesized one) were registered from
    # the CURRENT file's own AST, pick the one matching this call site's
    # arity/types instead of assuming there's only one. Structs known only
    # via dylib reflection (_struct_has_init set without a
    # _struct_method_signatures entry — see ~line 2672) fall through to
    # the single-signature path below unchanged; cross-module overload
    # resolution is a separate follow-on (elaborate.py extension).
    _init_candidates = gen._struct_method_signatures.get((struct_name, '__init__'))
    if _init_candidates:
        _chosen = gen._resolve_overload(_init_candidates, args, kwargs)
        if _chosen is not None:
            init_fname = gen._struct_method_csym(struct_name, '__init__', _chosen['overload_id'])
            arg_pairs = [(f"{struct_name} *", t)] + \
                gen._build_call_args_for_candidate(
                    _chosen, args, kwargs,
                    gen._struct_init_defaults.get(struct_name, {}))
            gen._emit_call('void', '', init_fname, arg_pairs)
            return ctype, t
        # No candidate could be resolved — either no candidate's arity fits
        # this call at all, or (same arity, but every candidate erases to
        # an identical C signature — e.g. two structurally different Mojo
        # generics both boxed as int64_t — so there's no type signal to
        # pick between them). Either way, guessing a specific overload_id
        # would be worse than what this struct has always done before
        # same-file resolution existed: fall straight through to the
        # single-signature path below (unsuffixed call if __init__ exists
        # at all, field-assignment otherwise) rather than returning here.

    # If struct has __init__, call it with the provided arguments
    if struct_name in gen._struct_has_init:
        init_fname = gen._struct_method_csym(struct_name, '__init__', '')
        arg_pairs = [(f"{struct_name} *", t)]  # self parameter
        for arg in args:
            arg_pairs.append(gen.lower_expr(arg))
        full_params = gen.func_param_types.get(init_fname, [])
        expected = len(full_params) - 1  # -1 for self
        # Bind keyword args to the __init__ parameters. For a struct whose
        # source we have, init_pnames gives the parameter names, so a kwarg
        # binds at the position of its named parameter. For a reflected
        # struct (no param names from the C signature), bind kwargs in source
        # order after the positional args.
        init_pnames = gen._struct_init_params.get(struct_name, [])
        init_defaults = gen._struct_init_defaults.get(struct_name, {})
        if kwargs and init_pnames:
            kw = dict(kwargs)
            for idx, pname in enumerate(init_pnames):
                if pname not in kw:
                    continue
                pos = idx + 1  # +1 for self slot
                while len(arg_pairs) <= pos:
                    arg_pairs.append(('int', '0'))
                arg_pairs[pos] = gen.lower_expr(kw[pname])
            # `**kwargs`: pack every keyword that isn't a named parameter
            # into a real MojoDict (see _pack_kwargs_dict). Without this
            # the padding below left `(MojoDict *)0` in that slot, so
            # `def __init__(self, t, **fields): self.fields = fields`
            # stored a null dict — the compiled-path half of
            # ast_rewriter's `for fname in pat.fields:` failure.
            _kw_i = -1
            for _i, _pn in enumerate(init_pnames):
                if _pn.startswith('**'):
                    _kw_i = _i
                    break
            if _kw_i >= 0:
                _named = set(init_pnames)
                _rest = {}
                for _kn in kw:
                    if _kn not in _named:
                        _rest[_kn] = gen.lower_expr(kw[_kn])
                _pos = _kw_i + 1  # +1 for self slot
                while len(arg_pairs) <= _pos:
                    arg_pairs.append(('int', '0'))
                arg_pairs[_pos] = ('MojoDict *', gen._pack_kwargs_dict(_rest))
        elif kwargs:
            for _kn, kexpr in kwargs:
                arg_pairs.append(gen.lower_expr(kexpr))
        # Pad any still-missing args with their declared default value (or 0
        # when no default is known). Padding with a bare `('int', '0')`
        # unconditionally silently flipped every `bool`/string default to
        # FALSE/0 in the compiled binary (e.g. `GimpleGen(do_imports=...)`
        # lost emit_str_pool/emit_struct_defs/emit_entry_points=True, so the
        # self-hosted gen_module skipped its whole struct-typedef preamble),
        # while real Python kept the true defaults — an A/B divergence
        # (python3 mojo.py --dump vs MOJO_NO_SHIM=1 ./mojoc --dump) that
        # dropped every struct typedef / dispatch helper from the native
        # output.
        while len(arg_pairs) - 1 < expected:
            _missing_pname = init_pnames[len(arg_pairs) - 1] if init_pnames and len(arg_pairs) - 1 < len(init_pnames) else None
            _dflt = init_defaults.get(_missing_pname) if _missing_pname else None
            if isinstance(_dflt, gimple_ctypes.BoolLiteral):
                arg_pairs.append(('_Bool', '1' if _dflt.value else '0'))
            elif isinstance(_dflt, gimple_ctypes.StringLiteral):
                arg_pairs.append(('char *', f'"{gimple_ctypes._c_escape(_dflt.value)}"'))
            elif isinstance(_dflt, (gimple_ctypes.IntLiteral, gimple_ctypes.FloatLiteral)):
                arg_pairs.append(('int', str(_dflt.value)))
            elif isinstance(_dflt, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr, gimple_ctypes.SetExpr, gimple_ctypes.DictExpr)):
                arg_pairs.append(('int64_t', '0'))
            else:
                arg_pairs.append(('int', '0'))
        gen._emit_call('void', '', init_fname, arg_pairs)
    elif kwargs or args:
        # Positional args + keyword args — assign fields by position then by name
        fields_list = list(gen.struct_field_types.get(struct_name, {}).items())
        fields_dict = dict(fields_list)
        # Assign positional args first (by field declaration order)
        for i, arg in enumerate(args):
            if i < len(fields_list):
                fname, ftype = fields_list[i]
                at, av = gen.lower_expr(arg)
                gen._safe_coerce_emit(at, ftype, av, f"{t}->{gimple_ctypes._safe_field(fname)}")
        # Then assign kwargs by name (may override positional, as in Python)
        for kname, kexpr in (kwargs or []):
            if kname in fields_dict:
                ftype = fields_dict[kname]
                at, av = gen.lower_expr(kexpr)
                gen._safe_coerce_emit(at, ftype, av, f"{t}->{gimple_ctypes._safe_field(kname)}")
    if struct_name == 'Span':
        # Span is erased to a hardcoded fat-pointer {_data, _len} struct
        # with no notion of its real element type (see struct_field_types
        # seed + _mojo_type's Span/StringSlice branch) — track it
        # ourselves, mirroring the existing _elem_types side-table
        # already used for MojoList *, so _lower_subscript's Span arm can
        # answer `span[i]` with the real element type instead of always
        # assuming a raw byte. Only covers the constructor shapes this
        # file actually needs (Span(ptr=.., length=..), Span(list_var),
        # Span(list=list_var)); anything else leaves _elem_types
        # untracked and _lower_subscript falls back to its existing
        # byte-oriented behavior unchanged.
        kw = dict(kwargs or [])
        elem_ct = None
        if 'ptr' in kw and isinstance(kw['ptr'], gimple_ctypes.IdentExpr):
            ptr_ct = gen.var_types.get(kw['ptr'].name)
            if ptr_ct:
                elem_ct = gimple_ctypes._elem_type(ptr_ct)
        elif 'list' in kw and isinstance(kw['list'], gimple_ctypes.IdentExpr):
            elem_ct = gen._elem_types.get(kw['list'].name)
        elif args and isinstance(args[0], gimple_ctypes.IdentExpr):
            elem_ct = gen._elem_types.get(args[0].name)
        if elem_ct:
            gen._elem_types[t] = elem_ct
    return ctype, t


def _array_field_elem_ptr(gen, member_expr) -> tuple[str, str] | None:
    """If `member_expr` (a MemberExpr, e.g. `world.blocks`) reads a
    fixed-size-array struct field (`var blocks: [Block; N]` — see
    _FIXED_ARRAY_ANN_RE and self._array_field_sizes, populated at struct
    registration in gen_module), return (elem_ptr_ctype, c_expr) where
    c_expr is the array field DECAYED to a real pointer to its first
    element (ordinary C array-to-pointer decay: `obj->field` used where
    a pointer value is expected). Returns None for every other MemberExpr
    (the ordinary field-read path handles those).

    This is the one place that understands the fixed-array field shape's
    C representation; both `_lower_subscript` (read: `obj.field[idx]`
    and, chained, `obj.field[idx].member`) and `_gen_stmt_AssignStmt`'s
    SubscriptExpr-target branch (write: `obj.field[idx] = ...`) call this
    BEFORE falling through to the ordinary `self.lower_expr(member_expr)`
    MemberExpr-read codegen, which has no notion of "this field is a
    whole embedded array, not a scalar or pointer" and could not
    otherwise produce it as a single valid C value. Once this returns a
    real pointer-to-element-type value, every existing pointer-based
    struct/array subscript mechanism elsewhere in this codegen (the
    working List[Struct]-element path, the generic `_mojo_at_` scaled-
    pointer-arithmetic helpers, and the existing whole-struct-array-
    element assignment field-by-field-copy branch) already handles it
    correctly with no further special-casing needed. See
    bugs/BUG-2026-008.md (box.3d/game) for the motivating real-world case
    (`World.blocks: [Block; MAX_BLOCKS]`)."""
    if not isinstance(member_expr, gimple_ctypes.MemberExpr):
        return None
    base_t, base_v = gen.lower_expr(member_expr.obj)
    if not base_t.endswith(' *'):
        return None
    sn = gimple_exprtypes._struct_name_of(base_t)
    info = gen._array_field_sizes.get(sn, {}).get(member_expr.member)
    if not info:
        return None
    elem_ct, _n = info
    safe_fn = gimple_ctypes._safe_field(member_expr.member)
    ptr_t = f"{elem_ct} *"
    # `-fgimple` rejects a bare array-typed component-ref assigned
    # directly to a pointer variable ("non-trivial conversion in
    # 'component_ref'") — ordinary C's implicit array-to-pointer decay
    # isn't a legal single GIMPLE rvalue; the address of the first
    # element (`&obj->field[0]`, an ADDR_EXPR of an ARRAY_REF) is.
    arr_base = gen._new_val(ptr_t, f"&{base_v}->{safe_fn}[0]")
    return ptr_t, arr_base


def _struct_data_field(gen, ctype: str):
    """Return (field_name, field_ctype) if ctype is a struct pointer with a pointer _data/data field, else (None, None)."""
    if not ctype.endswith(' *'):
        return None, None
    sn = gimple_exprtypes._struct_name_of(ctype)
    sft = gen.struct_field_types.get(sn, {})
    for fname in ('_data', 'data'):
        ft = sft.get(fname, '')
        if ft.endswith(' *'):
            return fname, ft
    return None, None


def _emit_struct_subscript_write(gen, obj_v: str, obj_t: str, idx_v: str, val: str, val_t: str) -> bool:
    """Emit `obj[idx] = val` for a struct-with-_data pointer. Returns True if handled."""
    fname, ftype = gen._struct_data_field(obj_t)
    if fname is None:
        return False
    dp = gen._new_val(ftype, f"{obj_v}->{fname}")
    # GIMPLE: can't chain casts in one expr; split into two steps
    vp = gen._new_val('void *', f"(void *){dp}")
    i64p = gen._new_val('int64_t *', f"(int64_t *){vp}")
    idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
    gen._ptr_helpers_needed.add('int64_t')
    addr = gen._new_val('int64_t *', f"_mojo_at_int64_t ({i64p}, {idx64})")
    v64 = gen._new_temp('int64_t')
    gen._safe_coerce_emit(val_t, 'int64_t', val, v64)
    gen._emit(f"  *{addr} = {v64};")
    return True


def _lower_subscript(gen, node: gimple_ctypes.SubscriptExpr) -> tuple[str, str]:
    # Keyword-parametrized slice, e.g. `x[byte=:-1]` (slice by byte offset).
    # The parser stashes the real SliceExpr in node.attrs (obj=None, since
    # the object wasn't known yet at that point) and leaves node.index as a
    # dummy IntLiteral(0) placeholder — attach the real object and lower it
    # as an actual slice instead of falling through to the scalar-index path.
    if node.attrs:
        for _attr_name, _attr_val in node.attrs:
            if _attr_name == 'byte' and isinstance(_attr_val, gimple_ctypes.SliceExpr):
                _attr_val.obj = node.obj
                return gen._lower_slice(_attr_val)

    # Regular slice subscript: node.index is a bare SliceExpr (obj=None)
    # whose object is really the SubscriptExpr's own obj — forward it so
    # _lower_slice can determine the container type and call the correct
    # runtime function (mojo_list_slice, mojo_str_slice, etc.) instead of
    # falling through to the generic pointer-arithmetic path below which
    # would return the raw address of the first element as int64_t.
    if isinstance(node.index, gimple_ctypes.SliceExpr):
        node.index.obj = node.obj
        return gen._lower_slice(node.index)

    # Fixed-size-array struct field: `obj.field[idx]` (and, chained,
    # `obj.field[idx].member`). See _array_field_elem_ptr's own
    # docstring for why this must run BEFORE the generic
    # `self.lower_expr(node.obj)` just below.
    if isinstance(node.obj, gimple_ctypes.MemberExpr):
        _arr = gen._array_field_elem_ptr(node.obj)
        if _arr is not None:
            _ot, _ov = _arr
            _elem_ct = _ot[:-2]  # strip trailing ' *'
            _idx_type, _iv = gen.lower_expr(node.index)
            _idx64 = gen._new_val('int64_t', f"(int64_t) {_iv}")
            gen._ptr_helpers_needed.add(_elem_ct)
            _addr = gen._new_val(_ot, f"_mojo_at_{gimple_ctypes._c_id(_elem_ct)} ({_ov}, {_idx64})")
            if _elem_ct in gen.struct_field_types:
                # Struct-valued element: return a POINTER to it (this
                # codegen's universal struct-field convention — same
                # shape the working List[Struct]-element path returns),
                # so a chained `.member` read/write off this subscript
                # routes through the ordinary `ptr->member` path.
                return _ot, _addr
            _t = gen._new_val(_elem_ct, f"*{_addr}")
            return _elem_ct, _t

    ot, ov = gen.lower_expr(node.obj)

    # `self.prop[key]` where `prop` is a 0-arg property/method accessed
    # without call syntax lowers `self.prop` alone to a deferred,
    # uncalled `MojoBoundMethod *` value (see _lower_bound_method_
    # value) — correct when the consuming context is itself a call
    # (`self.prop()`), but a subscript is NOT a call: real Python
    # auto-invokes `prop` (the property getter / bound method) first,
    # THEN subscripts its actual return value. Left unhandled, the
    # generic "opaque/unknown pointer type" fallback further below
    # tried to treat the MojoBoundMethod* itself as an array base
    # pointer (a `_mojo_at_MojoBoundMethod` GIMPLE pointer-arithmetic
    # helper on a struct with no such element shape — "cannot convert
    # to a pointer type" / "non-trivial conversion") and, worse,
    # reinterpreted the subscript's STRING key as a raw integer byte
    # offset. Confirmed via Lib/importlib/metadata/__init__.py's
    # `Distribution.name`/`.version` properties, both `return self.
    # metadata['Name']`/`self.metadata['Version']` where `metadata` is
    # an inherited `@property` defined on the base class — the
    # subscript's own object expression is a bare, uncalled bound
    # method the same way any deferred `f = self.method` reference is.
    if ot == 'MojoBoundMethod *':
        ot, ov = gmp._auto_invoke_bound_method_value(gen, ov)

    idx_type, iv  = gen.lower_expr(node.index)

    if ot == 'MojoList *':
        elem = gen._elem_of(ov)
        suf  = gimple_ctypes.TypeLattice.list_suffix(elem)
        idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
        if suf == 'double':
            t = gen._new_val('double', f"mojo_list_get_double ({ov}, {idx64})")
            return 'double', t
        if suf == 'str':
            t = gen._new_val('char *', f"mojo_list_get_str ({ov}, {idx64})")
            return 'char *', t
        t = gen._new_val('int64_t', f"mojo_list_get_int ({ov}, {idx64})")
        # Return the actual pointer type for pointer elements (MojoDict*,
        # MojoList*, MojoSet*) so downstream consumers (subscript, method
        # dispatch) see the real type instead of raw int64_t.  Without this,
        # x = lst[0]; x["key"] on a list-of-dicts field fails because
        # var_types[x] is int64_t and x["key"] dispatches on int64_t instead
        # of MojoDict* — see BUG-2026-044.
        if elem and elem.endswith(' *'):
            gen._actual_types[t] = elem
            cast_t = gen._new_val(elem, f'({elem}){t}')
            gen._actual_types[cast_t] = elem
            # Propagate nested element types for MojoList* (list-of-lists)
            if elem == 'MojoList *':
                if ov in gen._nested_elem_types:
                    gen._elem_types[cast_t] = gen._nested_elem_types[ov]
                    gen._elem_types[t] = gen._nested_elem_types[ov]
                else:
                    gen._elem_types[t] = gen._elem_types.get(ov, 'int64_t')
                    if gen._elem_types[t] in ('int64_t',) and ov in gen._elem_types:
                        gen._elem_types[cast_t] = gen._elem_types[ov]
            # For MojoDict* elements, propagate dict value type from the
            # container (list variable) so subsequent ["key"] subscript
            # dispatches to mojo_dict_get_str instead of mojo_dict_get_int.
            if elem == 'MojoDict *' and ov in gen._dict_val_types:
                gen._dict_val_types[cast_t] = gen._dict_val_types[ov]
            return elem, cast_t
        return 'int64_t', t

    if ot == 'MojoStr *':
        idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
        t = gen._new_val('char', f"mojo_str_char_at ({ov}, {idx64})")
        return 'char', t

    if ot == 'MojoDict *':
        # Ensure index is char * for dict subscript access (all dict keys are strings in runtime)
        idx_type, iv = gen._char_to_cstr(idx_type, iv)
        val_ctype = gen._dict_val_of(ov)
        if val_ctype == 'double':
            t = gen._call_expr('double', 'mojo_dict_get_double', [('MojoDict *', ov), (idx_type, iv)])
            return 'double', t
        if val_ctype == 'char *':
            t = gen._call_expr('char *', 'mojo_dict_get_str', [('MojoDict *', ov), (idx_type, iv)])
            return 'char *', t
        if val_ctype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
            # Pointer value stored boxed as int64_t; recover the real type so a
            # later v[k2] / v.get(...) dispatches on the right container.
            raw = gen._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', ov), (idx_type, iv)])
            t = gen._new_val(val_ctype, f"({val_ctype}){raw}")
            return val_ctype, t
        t = gen._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', ov), (idx_type, iv)])
        return 'int64_t', t

    # Opaque Python object (typed as int) — treat as MojoList via cast
    # `_Bool` is included here too: a SIMD comparison result (`simd_val.lt(...)`)
    # collapses to a scalar _Bool (SIMD itself has no width tracking — every
    # SIMD[dtype, N] value is scalar-erased regardless of N; subscripting the
    # vector directly, e.g. `simd_val[0]`, already goes through this exact
    # same MojoList-cast fakery below and "compiles" the same way). Without
    # this, `_Bool` falls to the final generic-pointer-deref fallback further
    # down, which assumes its receiver is a real pointer and errors trying to
    # dereference a bare _Bool.
    if ot in ('int', 'int64_t', '_Bool'):
        # Check actual type for globals loaded as int64_t
        actual_type = gen._get_actual_type(ot, ov)
        if actual_type == 'char *':
            # A string boxed as int64_t (its declared storage type was
            # widened joining with other assignment sites in the same
            # function — see _lower_builtin_len's identical blind spot,
            # fixed alongside this) still needs real char indexing, not
            # the MojoList* fallback below: that reinterprets the
            # string's own bytes as a MojoList header and segfaults deep
            # in mojo_list_get_int. Found via mojo_compiler.py's own
            # `rest[0]` in _strip_string_prefix_and_quotes.
            cp = gen._new_val('char *', f'(char *){gen._ensure_local(ot, ov)}')
            idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
            gen._ptr_helpers_needed.add('char')
            addr = gen._new_val('char *', f"_mojo_at_char ({cp}, {idx64})")
            t = gen._new_val('char', f"*{addr}")
            return 'char', t
        # A STRING index proves the container is a dict even when its own
        # type is opaque: no list is indexable by a string. `pat.fields`
        # in ast_rewriter.py is exactly this — the A5 boxed-member read
        # can't type it (Node.fields is a boxed int64_t while
        # StructDef.fields is a MojoList*, so _known_field_type is
        # ambiguous), and `pat.fields[fname]` with `fname` a dict key then
        # fell to the MojoList* fallback below, reinterpreting the dict
        # header as a list and faulting inside mojo_list_get_int.
        _idx_is_str = (idx_type in ('char *', 'MojoStr *')
                       or gen._get_actual_type(idx_type, iv) == 'char *')
        if actual_type == 'MojoDict *' or (_idx_is_str and actual_type not in ('MojoList *', 'MojoSet *')):
            # Dict subscript: int64_t → MojoDict *
            dp = gen._new_temp('MojoDict *')
            ip = gen._new_temp('int64_t')
            ov_local = gen._ensure_local(ot, ov)
            if ot == 'int64_t':
                gen._emit(f"  {ip} = {ov_local};")
            else:
                gen._emit(f"  {ip} = (int64_t){ov_local};")
            gen._emit(f"  {dp} = (MojoDict *){ip};")
            # Propagate dict value type from source (ov) so _dict_val_of
            # below returns the correct value type (char * etc.) instead
            # of defaulting to int64_t — fixes BUG-2026-043.
            if ov in gen._dict_val_types:
                gen._dict_val_types[dp] = gen._dict_val_types[ov]
            # Ensure index is char * for dict access (all dict keys are strings in runtime)
            idx_type_for_dict, idx_for_dict = gen._char_to_cstr(idx_type, iv)
            val_ctype = gen._dict_val_of(dp)
            if val_ctype == 'double':
                t = gen._call_expr('double', 'mojo_dict_get_double', [('MojoDict *', dp), (idx_type_for_dict, idx_for_dict)])
                return 'double', t
            if val_ctype == 'char *':
                t = gen._call_expr('char *', 'mojo_dict_get_str', [('MojoDict *', dp), (idx_type_for_dict, idx_for_dict)])
                return 'char *', t
            t = gen._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', dp), (idx_type_for_dict, idx_for_dict)])
            return 'int64_t', t
        # Otherwise treat as MojoList* stored as int; cast and subscript
        lp = gen._new_temp('MojoList *')
        ip = gen._new_temp('int64_t')
        ov_local = gen._ensure_local(ot, ov)
        if ot == 'int64_t':
            gen._emit(f"  {ip} = {ov_local};")  # same type, no cast
        else:
            gen._emit(f"  {ip} = (int64_t){ov_local};")
        gen._emit(f"  {lp} = (MojoList *){ip};")
        idx64 = gen._to_int64(idx_type, iv)
        # Copy element type tracking from the int64_t temp to the MojoList * temp
        # This is critical for nested list access: when lp came from arr[i], we need to know
        # what elements lp contains so subsequent accesses like lp[j] use the right function
        if ov in gen._elem_types:
            gen._elem_types[lp] = gen._elem_types[ov]
        if ov in gen._nested_elem_types:
            gen._nested_elem_types[lp] = gen._nested_elem_types[ov]
        # Get element type: check _elem_types (if ov is a tracked temp), else check _nested_elem_types
        elem = gen._elem_of(ov)
        if not elem or elem == 'int64_t':
            # Check if ov came from a subscript that returned a list with tracked nested elements
            if ov in gen._elem_types:
                elem = gen._elem_types[ov]
            elif ov in gen._nested_elem_types:
                elem = gen._nested_elem_types[ov]
        if elem == 'char *':
            t = gen._new_val('char *', f"mojo_list_get_str ({lp}, {idx64})")
            return 'char *', t
        if elem == 'double':
            t = gen._new_val('double', f"mojo_list_get_double ({lp}, {idx64})")
            return 'double', t
        t = gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
        # Any OTHER pointer element type (struct pointers like Recipe*,
        # or MojoDict*/MojoList*/MojoSet*) was falling all the way
        # through to the plain int64_t return below, unlike the direct
        # `ot == 'MojoList *'` branch above which already casts back to
        # `elem` when it ends in ' *'. Every global container is boxed
        # as int64_t at the C struct level (see "Globals are stored at
        # C level as int64_t" elsewhere in this file), so a global
        # `List[Struct]` ALWAYS arrives here via this opaque-cast path,
        # never the direct branch -- meaning a struct-element global
        # list's reads always silently degraded to raw int64_t instead
        # of the real struct pointer, and a later `.field` access on
        # that mistyped int64_t fell back to dynamic `_mojo_dispatch_
        # getattr`, which only recognizes the FIRST field of the
        # boxed-int64_t "value" mojo_list_get_int actually returned
        # (the pointer's own low bytes were being read further, not the
        # struct's memory at all) -- e.g. `r.width`/`r.output_id` in
        # box.3d/game/lib/recipes.mojo's `match_shaped` reading garbage
        # for every recipe. See bugs/DYLIB_struct_list_index_reads_
        # first_field_only_wrong_craft_results.md.
        if elem and elem.endswith(' *'):
            gen._actual_types[t] = elem
            cast_t = gen._new_val(elem, f'({elem}){t}')
            gen._actual_types[cast_t] = elem
            if elem == 'MojoList *':
                if ov in gen._nested_elem_types:
                    gen._elem_types[cast_t] = gen._nested_elem_types[ov]
                    gen._elem_types[t] = gen._nested_elem_types[ov]
            if elem == 'MojoDict *' and ov in gen._dict_val_types:
                gen._dict_val_types[cast_t] = gen._dict_val_types[ov]
            return elem, cast_t
        return 'int64_t', t

    # Struct pointer subscript: Span[i] → Span->_data[i] etc.
    if ot.endswith(' *') and gimple_exprtypes._struct_name_of(ot) in gen.struct_field_types:
        tracked = gen._elem_types.get(ov)
        if tracked and tracked in gen.struct_field_types:
            # Span's hardcoded {_data, _len} model always assumes a raw
            # byte element (see struct_field_types['Span'] and
            # _struct_data_field) — but this particular Span * was
            # constructed from a real struct-typed source and its element
            # type was tracked (_lower_struct_constructor's Span
            # handling), mirroring the existing _elem_types side-table
            # already used for MojoList *. Cast the raw byte _data
            # pointer through the real element pointer type and reuse the
            # same generic _mojo_at_ scaled-arithmetic helper (already
            # works for any element C type, struct or scalar — no new
            # helper-generation code needed) instead of the byte-oriented
            # fallback below.
            fname, ftype = gen._struct_data_field(ot)
            if fname is not None:
                raw = gen._new_val(ftype, f"{ov}->{fname}")
                et_ptr = tracked + ' *'
                dp = gen._new_val(et_ptr, f"({et_ptr}){raw}")
                cn = gimple_ctypes._c_id(tracked)
                gen._ptr_helpers_needed.add(tracked)
                idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
                addr = gen._new_val(et_ptr, f"_mojo_at_{cn} ({dp}, {idx64})")
                t = gen._new_val(tracked, f"*{addr}")
                return tracked, t
        fname, ftype = gen._struct_data_field(ot)
        if fname is not None:
            dp = gen._new_val(ftype, f"{ov}->{fname}")
            et = gimple_ctypes._elem_type(ftype)
            cn = gimple_ctypes._c_id(et)
            gen._ptr_helpers_needed.add(et)
            idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
            addr = gen._new_val(ftype, f"_mojo_at_{cn} ({dp}, {idx64})")
            if et == 'void':
                return ftype, addr
            t = gen._new_val(et, f"*{addr}")
            return et, t
        # Struct without pointer _data: return int64_t opaque handle
        t = gen._new_val('int64_t', f"(int64_t){ov}")
        return 'int64_t', t

    # p[i] via _mojo_at_ helper (ptr arithmetic not allowed in __GIMPLE)
    et = gimple_ctypes._elem_type(ot)
    cn = gimple_ctypes._c_id(et)
    gen._ptr_helpers_needed.add(et)
    idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
    addr = gen._new_val(ot, f"_mojo_at_{cn} ({ov}, {idx64})")
    # Can't dereference void* (no element type); return the pointer itself
    if et == 'void':
        return ot, addr
    # Struct types: return int64_t (opaque handle) — can't cast struct→int64_t in GIMPLE
    if et in gen.struct_field_types:
        t = gen._new_val('int64_t', f"(int64_t){addr}")
        return 'int64_t', t
    t = gen._new_val(et, f"*{addr}")
    return et, t


def _lower_slice_bounds(gen, node: gimple_ctypes.SliceExpr) -> tuple[str, str]:
    """Compute (start_v, stop_v) C expressions for a SliceExpr's bounds
    — shared by _lower_slice (read a sub-range) and the DelStmt lowering
    for `del container[a:b]` (remove a sub-range in place), since both
    need the identical bound normalization."""
    if node.start is not None:
        _st, sv = gen.lower_expr(node.start)
        # Use the REAL type lower_expr just gave `sv`, not _quick_type's
        # static estimate — _quick_type(IntLiteral) always guesses
        # 'int64_t', but _lower_UnaryOp('-', IntLiteral) actually emits a
        # plain C `int`-typed temp for a negated literal (its "pointer
        # negate" special-case only widens to int64_t for pointer
        # operands). _to_int64 trusted the estimate and skipped the
        # int->int64_t cast, so `groups[:-1]` on a struct method (any
        # context where `_ensure_local` couldn't already coerce it)
        # passed a bare 32-bit -1 where mojo_list_slice's `int64_t stop`
        # expects one — GIMPLE calls don't do C's usual argument
        # promotion, so the raw bits got zero-extended into
        # 4294967295 instead of sign-extended into -1, `stop < 0` came
        # back false, and the slice silently returned the WHOLE list
        # instead of dropping the last element. Found via a from-scratch
        # minimal repro (struct method + `lst[:-1]` comprehension) while
        # chasing `make bootstrap`'s verify byte-identity failures.
        start_v = gen._to_int64(_st, sv)
    else:
        start_v = '0'
    if node.stop is not None:
        _et, ev = gen.lower_expr(node.stop)
        stop_v = gen._to_int64(_et, ev)
    else:
        # Sentinel for "to end" — must NOT be a plain -1, which a real
        # `x[:-1]` (drop the last char/element) also produces; see
        # MOJO_SLICE_STOP_OMITTED's doc comment in mojo_runtime.h.
        stop_v = 'MOJO_SLICE_STOP_OMITTED'
    return start_v, stop_v


def _lower_slice(gen, node: gimple_ctypes.SliceExpr) -> tuple[str, str]:
    ot, ov = gen.lower_expr(node.obj)
    start_v, stop_v = gen._lower_slice_bounds(node)

    if ot == 'MojoStr *':
        t = gen._new_val('MojoStr *', f"mojo_str_slice ({ov}, {start_v}, {stop_v})")
        return 'MojoStr *', t

    if ot == 'MojoList *':
        t = gen._new_val('MojoList *', f"mojo_list_slice ({ov}, {start_v}, {stop_v})")
        # propagate elem type
        if ov in gen._elem_types:
            gen._elem_types[t] = gen._elem_types[ov]
        return 'MojoList *', t

    if ot == 'Span *':
        # Span is the fat-pointer {_data, _len} struct (see _mojo_type's
        # Span/StringSlice branch) — slicing it means allocating a new Span
        # whose _data is advanced by `start` bytes and whose _len is
        # shortened accordingly, not raw pointer-to-the-struct arithmetic
        # (which is what the generic fallback below would do, corrupting it).
        gen._struct_allocs_needed.add('Span')
        t = gen._new_temp('Span *')
        gen._emit(f"  {t} = _alloc_Span ();")
        old_data = gen._new_val('char *', f"{ov}->_data")
        old_data_i = gen._new_val('int64_t', f"(int64_t){old_data}")
        start_i = gen._new_val('int64_t', f"(int64_t){start_v}")
        new_data_i = gen._new_val('int64_t', f"{old_data_i} + {start_i}")
        new_data = gen._new_val('char *', f"(char *){new_data_i}")
        gen._emit(f"  {t}->_data = {new_data};")
        old_len = gen._new_val('int64_t', f"{ov}->_len")
        if node.stop is not None:
            # GIMPLE strict mode: a bare literal stop bound (e.g. `[:0]`)
            # comes back from _to_int64 uncast (its _ensure_local fast path
            # treats a bare digit as "already fine"), so re-cast defensively
            # here — mirroring start_i just above — or `stop_v - start_i`
            # mixes an untyped int literal with an int64_t and GIMPLE
            # rejects the binary expression outright.
            stop_i = gen._new_val('int64_t', f"(int64_t){stop_v}")
            new_len = gen._new_val('int64_t', f"{stop_i} - {start_i}")
        else:
            new_len = gen._new_val('int64_t', f"{old_len} - {start_i}")
        gen._emit(f"  {t}->_len = {new_len};")
        return 'Span *', t

    if ot == 'char *':
        # A plain (non-MojoStr-wrapped) Python str, boxed as char* — a
        # NUL-terminated C string has no length field to bound a slice
        # copy against, unlike MojoStr's `->len`. The generic "plain
        # pointer" fallback below just adds `start` to the pointer,
        # which happens to look right for `s[start:]` (the tail reads
        # correctly to the string's own real end) but silently drops
        # `stop` entirely for `s[:stop]`/`s[start:stop]` — no truncation
        # ever happens. See mojo_cstr_slice in runtime/mojo_runtime.c.
        t = gen._new_val('char *', f"mojo_cstr_slice ({ov}, {start_v}, {stop_v})")
        return 'char *', t

    # Plain pointer: return pointer to start (no bounds check)
    # GIMPLE: no pointer+integer; cast pointer through int64_t; both operands
    # must be plain variables (no cast expressions in binary operands).
    t = gen._new_temp(ot)
    cast_t = gen._new_val('int64_t', f"(int64_t){ov}")
    # Cast start to int64_t in a separate statement (GIMPLE binary operands
    # must be variables, not cast expressions)
    if start_v.lstrip('-').isdigit():
        sv_cast = gen._new_val('int64_t', f"(int64_t){start_v}")
    else:
        # start_v is already a variable; ensure it's int64_t
        sv_cast = gen._new_val('int64_t', f"(int64_t){start_v}")
    add_t = gen._new_val('int64_t', f"{cast_t} + {sv_cast}")
    gen._emit(f"  {t} = ({ot}){add_t};")
    return ot, t
