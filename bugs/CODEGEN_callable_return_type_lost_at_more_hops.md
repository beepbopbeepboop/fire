# CODEGEN: a callable's return type is lost at three more hops after the module-scope one

**State: OPEN, unfixed.** Found while fixing
`CODEGEN_lambda_bool_return_prints_as_int.md` (now deleted). Independent of it:
that one was the module-scope store/read hop, and these three are different
hops with different mechanisms. All three are silent wrong values with exit 0.

Every measurement below is `python3 .tmp/repro.py` on this tree: the same
source under CPython and compiled with `gcc -fgimple`, stdout + exit code
compared.

## 1. A FUNCTION calling a module global's callable — generation order

    g = lambda: False

    def show():
        print(g())

    show()

| | |
|---|---|
| CPython | `False` |
| compiled | `0` |

The store and the read are each individually fixed (see the deleted doc). The
two are simply in different functions, and **a function's body is lowered
BEFORE `_toplevel`'s**, so the name-keyed record the module-scope store leaves
is wiped twice over before the function that needs it is generated:

* `_reset_func` clears `gen._callable_ret_types` (and `_dict_callable_ret`,
  `_bound_method_ret_types`) at every function entry — they are per-function
  because temp names (`_tN`) recycle; and
* `gen_module_impl` calls `self._gen_toplevel(toplevel_stmts)` at
  `mojo/backend_gimple/module_gen.py:7693`, after every `FunctionDef` and
  struct method.

Measured directly (instrumenting `_lower_call` and `_lower_LambdaExpr`):

    CALL G in show in_toplevel False      <- _callable_ret_types is {}
    LAMBDA-lift, ctx = _toplevel          <- the global's store, far too late

So the answer a function needs is only ever known after the fact.

### Why the obvious fix is not the obvious fix

Emitting `_toplevel` first would fix it, but the pre-pass immediately above
it (`module_gen.py:7662-7690`, "Reconcile toplevel global C types with
LATE-resolved callee return types") exists precisely because the toplevel body
*needs* information the function passes produce. Reordering is a real change
to emission order, not a one-liner, and it is the same class of reordering the
two lambda bug docs describe as hazardous.

Recording the global's type in the existing pre-pass means re-running the
lambda's return-type inference there, i.e. a SECOND implementation of what
`_lower_LambdaExpr` does — which CLAUDE.md's "consolidate duplicates rather
than maintaining parallel implementations" rules out, and which would let the
two disagree (the `ret_type` re-read comment at `emit_calls.py:4741-4759` is a
record of them having disagreed once already).

### Next step

Either make the module-global callable's return type a COMPILE-scoped fact
recorded once, in a pre-pass that reuses `_lower_LambdaExpr`'s own inference
rather than repeating it (the lifted function's `func_return_types` entry is
already compile-scoped, so the inference may be reachable from the AST without
lifting), or emit the module body before the functions and re-gate. The first is
much smaller. Whichever is chosen, the shape-independent check is the existing
`gimple_module_level_callable_keeps_its_return_type` test with one call moved
into a `def`.

## 2. A function RETURNING a callable — the type stops at the return

    def a():
        e = lambda: False
        return e

    def c():
        e = a()
        print(e())

`int64_t a (void)` boxes the `void *` callable into an `int64_t`, and `c`'s
assignment records nothing, so `print(e())` printed `0`. The store-side carries
cannot help: the RHS is a CALL's result temp, and `_callable_ret_types` has no
entry for it. Same family as #1 — nothing carries the type across the call —
but a different hop, and fixing #1 does not fix this one.

Next step: a per-function "the callable this function returns, and what THAT
returns" record, written at the `return` and read at the call site. Note the
flush-ordering hazard both lambda docs record — a new side table whose writes
happen while a function body is generated needs a reset point at each of the
per-function entry points, or the same class of bug comes back as a stale
`_tN` entry.

## 3. A BOUND METHOD stored in a module global loses its CALLING CONVENTION

    class C:
        def __init__(self):
            self.k = 9
        def truthy(self):
            return self.k > 4

    m = C()
    f = m.truthy
    print(f())

The identical spelling inside a `def` is right. At module scope the globals
struct field is `int64_t` (`_global_dst_ctype`), so `_lower_IdentExpr`'s global
read returns `int64_t`, and the call site at `emit_calls.py:1257`
(`_callee_t == 'void *' or _callee_t in ('int', 'int64_t', '_Bool')`) routes to
`mojo_fnptr_call_0` — which calls the RAW method symbol with no receiver. The
generated C:

    _root_globals.f = _t7;      /* the MojoBoundMethod * boxed */
    _t11 = (void *) ...;
    _t12 = mojo_fnptr_call_0 (_t11);

This one is worse than a wrong value: it is a call with the wrong arity and no
`self`. It happened to print `1` here rather than crash, which is luck, not a
property. It is NOT the return-type carry — the same carry is now applied and
the convention is still wrong.

Next step: the globals struct field's declared C type has to be the value's
real type (`MojoBoundMethod *`) for a global bound method, the way it is for a
local, and the global-read path needs the same `_actual_types`-style overlay
`_lower_MemberExpr` already uses for a boxed container pointer.