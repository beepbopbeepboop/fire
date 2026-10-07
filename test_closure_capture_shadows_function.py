"""A closure's free name that the ENCLOSING function also binds is a
CAPTURE, even when some other module of the same compile has a function of
that name — `mojo/middle/closures.py`'s capture discovery, tested directly.

`discover_closures` used to subtract a `free_globals` set — every name in
`ctx.func_return_types` — from a nested function's free-variable set before
deciding what to capture, on the theory that a module-level function name
can never be a capture. The theory only holds for a name the enclosing
scope does not ALSO bind, and the `v in enriched_scope` membership test
that decides captures a few lines later already says exactly that.
Subtracting first therefore did nothing except delete captures in the one
case where the two disagreed: a name the enclosing function binds that
shadows a same-named function somewhere in the inlined closure.

The guard it reached for, `if _fg not in outer_params`, reads like "unless
an enclosing PARAMETER shadows it" and is not: `outer_params` is built from
`outer_scope.keys()`, and `outer_scope` holds the enclosing function's
parameters AND the names its own body binds *at statement level*. So a
parameter shadow and a top-level `x = ...` local both survived, and what
fell through was the shape that actually occurs in this compiler: the
binding is nested one block down (`if cond:` / `else:` / `for` / `try`),
where `discover_closures`' own `enriched_scope` walk descends but
`outer_scope`'s does not. The name is then in `enriched_scope` and not in
`outer_scope`, `free_globals` claims it, and the capture disappears.

The self-host build is what found it, because the compiler compiles itself
into one translation unit. `ownership_destruct.py`'s `_scan_expr` binds
`param_names` inside its `if isinstance(node, N.CallExpr):` arm (line 467)
and its nested `_arg_is_safe` reads it (lines 478 and 480), while
`mojo/middle/comptime.py` — also in the closure — defines a function
`param_names`. The capture was dropped, the nested body re-resolved the
name as that function, and `param_names[real_idx]` became pointer
arithmetic on a function address:

    _t20 = _mojo_at_void (_funcptr_mojo_middle_comptime_param_names_9f63a2, _t19);

which gcc rejects with "invalid argument to gimple call" — mojoc, selfhost
and bootstrap-stage2-cc all red. `len(param_names)` in the same body had
been silently answering a literal `0` all along (the generated C said so:
`(int64_t)0 /* len() on unsupported type void * */`), so the miscompile was
already producing wrong answers before gcc noticed the syntax.

Why this is tested at the `discover_closures` level rather than end to end:
the trigger is a cross-MODULE name collision, and whether it fires depends
on whether the colliding function is registered in `ctx.func_return_types`
before the closure is scanned — a property of the module ORDER of whatever
closure is being compiled, so a single-module program cannot be relied on
to reproduce it. Setting `func_return_types` directly states the
precondition the bug needs and tests the decision that was actually wrong.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fire_compiler import py_tokenize, Parser
from mojo.middle.closures import discover_closures

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


class _Ctx:
    """The TypeCtx protocol `discover_closures` documents, with every type
    collapsed to a scalar the way the formal backend's FormalClosureCtx
    does. `func_return_types` is the input the bug turned on: a name in it
    is a function this compile knows, wherever it was defined."""

    def __init__(self, func_return_types):
        self.var_types = {}
        self.func_return_types = dict(func_return_types)
        self.struct_field_types = {}
        self._func_param_defaults = {}
        self._nested_async_api = {}
        self._method_threaded_comptime_params = {}
        self._all_closures = {}

    def _quick_type(self, node):
        return 'int64_t'

    def _resolve_type(self, ptype):
        return 'int64_t'

    def _infer_return_type(self, body):
        return 'int64_t'

    def _struct_method_overload_ids(self, structdef):
        return []


def _captures(src, outer, inner, func_return_types=('probe', 'outer')):
    """[(name, ctype)] `inner` captures from `outer` in `src`, with
    `func_return_types` already holding every name listed — which is the
    state a cross-module collision leaves the closure pre-pass in."""
    stmts = Parser(py_tokenize(src)).with_filename('<test>').parse_module()
    ctx = _Ctx({n: 'int64_t' for n in func_return_types})
    discover_closures(ctx, stmts)
    return [tuple(c) for c in ctx._all_closures[outer][inner].captures]


# ── 1. the real shape: the enclosing binding is one block down ──
#
# `param_names` in ownership_destruct.py is assigned inside an `if` arm, and
# that is the whole difference between the case the old `outer_params` guard
# caught (a statement-level local) and the one it dropped. Asserted on the
# `if`/`else` form, which is what `_scan_expr` has.
_NESTED_SHADOW_SRC = """\
def outer(flag):
    if flag:
        probe = [10, 20]
    else:
        probe = [30, 40]
    def inner():
        return probe[1]
    return inner()
"""

check("block_nested_local_shadowing_another_modules_function_is_captured",
      _captures(_NESTED_SHADOW_SRC, 'outer', 'inner') == [('probe', 'int64_t')],
      f"got {_captures(_NESTED_SHADOW_SRC, 'outer', 'inner')}")

# ── 2. the same name bound straight in the enclosing body ──
#
# This one already worked (it is the `outer_params` case the old guard was
# written for) and is here so the pair documents WHICH shape regressed
# rather than leaving the fix looking like it changed a working case.
_FLAT_SHADOW_SRC = """\
def outer(flag):
    probe = [10, 20]
    def inner():
        return probe[1]
    return inner()
"""

check("statement_level_local_shadow_is_still_captured",
      _captures(_FLAT_SHADOW_SRC, 'outer', 'inner') == [('probe', 'int64_t')],
      f"got {_captures(_FLAT_SHADOW_SRC, 'outer', 'inner')}")

# ── 3. an enclosing PARAMETER of the same name ──
_PARAM_SHADOW_SRC = """\
def outer(probe):
    def inner():
        return probe + 1
    return inner()
"""

check("param_shadowing_another_modules_function_is_captured",
      _captures(_PARAM_SHADOW_SRC, 'outer', 'inner') == [('probe', 'int64_t')],
      f"got {_captures(_PARAM_SHADOW_SRC, 'outer', 'inner')}")

# ── 4. a genuine global is still NOT a capture ──
#
# The point of the rule, and the reason removing `free_globals` is safe:
# with nothing in the enclosing scope binding the name there is nothing to
# capture, and the nested body must keep reading it as the module-level
# function it is. This is the case the old set was written for.
_GLOBAL_SRC = """\
def outer(flag):
    if flag:
        pass
    def inner():
        return helper(3)
    return inner()
"""

check("unbound_function_name_is_still_not_a_capture",
      _captures(_GLOBAL_SRC, 'outer', 'inner',
                func_return_types=('helper', 'outer')) == [],
      f"got {_captures(_GLOBAL_SRC, 'outer', 'inner', func_return_types=('helper', 'outer'))}")

# ── 5. a name the inner function DECLARES is not a capture of anything ──
_OWN_LOCAL_SRC = """\
def outer(flag):
    if flag:
        shared = 1
    def inner():
        shared = 2
        return shared
    return inner()
"""

check("inner_declared_name_is_not_captured",
      _captures(_OWN_LOCAL_SRC, 'outer', 'inner',
                func_return_types=('shared', 'outer')) == [],
      f"got {_captures(_OWN_LOCAL_SRC, 'outer', 'inner', func_return_types=('shared', 'outer'))}")


if __name__ == '__main__':
    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    sys.exit(0 if _FAIL == 0 else 1)
