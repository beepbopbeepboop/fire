#!/usr/bin/env python3
"""The C++ printer's giant functions have no movable `if` arms left.

`tools/extract_arm.py` moves one top-level `if` arm of a giant function into
its own top-level function and replaces it with a call, checking that the moved
body is the same syntax tree.  It refuses an arm that reads a name its parent
has not bound on every path, binds a name the parent reads later, or calls a
nested function; a remaining `NO` arm is the tool's own verdict, not a todo.

This pins the stage-7 SHAPE step for `mojo/backend_gimple/cpp_core.py` (GIR.md,
"Stage 7. Other printers"): the C++ coroutine lowering's five dispatch
functions are split along their `isinstance` arms, which is exactly the unit a
later step makes return an IR expression instead of C++ text.  It is the same
state `test_gimple_arms_extracted.py` pins for the GIMPLE lowerer and
`test_gimple_module_passes.py` pins for `gen_module_impl`.

What is pinned:

  * every `_cpx_*`/`_cps_*`/`_cpw_*`/`_cpy_*`/`_cpf_*` function its parent
    calls is a module-level function called exactly ONCE from that parent (an
    arm inlined back into the parent, or a new arm written inline, fails);
  * each parent's own length, which may only shrink;
  * that `extract_arm.py --list` has nothing left to offer at 25 lines, the
    floor the earlier stage-6 pins use;
  * that the printers are reached through the generator object
    (`gen._cpp_stmt(...)`), never as a bare module-level call.  A direct
    `_cpp_stmt(gen, ...)` call makes `mojo.middle.coro`'s `_ParamFlow` see a
    cycle of top-level functions that each pass their own `gen` parameter on,
    and it then reports that parameter as a pass-through referenced generator
    (the cycle branch answers "ok"): `python3 fire.py --dump cpp_core.py`
    stops with a RecursionError in `_specialize_mixed_generator_callers`
    instead of dumping.  The method wrapper in `gimple_codegen.py`
    (`def _cpp_stmt(self, ...): return gcc_._cpp_stmt(self, ...)`) is the
    spelling the rest of this file already uses and the one that keeps the
    coro pass out of it.

The 28 arms were extracted with `tools/extract_arm.py` verbatim; the only
hand edit to a moved body is the `gen._cpp_stmt(...)` call above.  Generated
output is unchanged for both oracles (`tools/pydiff_corpus` C and
`tools/cpp_corpus` C++ companions); that comparison is `tools/c_oracle.py
check`, which is too slow to run here.

    python3 test_gimple_cpp_core_arms.py
"""
import ast
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, 'mojo', 'backend_gimple', 'cpp_core.py')
TOOL = os.path.join(ROOT, 'tools', 'extract_arm.py')

# (parent, return annotation, line ratchet, the arms extracted from it).
# The ratchet is the parent's length now: the arms below account for every
# line that could move, so the parent may only get shorter.
# The expression arms still building C++ text (plan step 4 in the stage 6/7 doc).
EXPR_ARMS_STILL_TEXT = {
    '_cpx_lambda_expr',
    '_cpx_member_expr', '_cpx_await_expr', '_cpx_call_expr',
}
PARENTS = [
    ('_cpp_expr_ex', 'Ex', 101, [
        '_cpx_ident_expr', '_cpx_member_expr', '_cpx_lambda_expr',
        '_cpx_unary_op', '_cpx_binary_op', '_cpx_compare_chain',
        '_cpx_walrus', '_cpx_call_expr', '_cpx_slice_expr',
        '_cpx_subscript_expr', '_cpx_await_expr',
    ]),
    ('_cpp_stmt', 'list[str]', 73, [
        '_cps_expr_stmt', '_cps_assign_stmt', '_cps_var_decl',
        '_cps_aug_assign', '_cps_while_stmt', '_cps_if_stmt',
        '_cps_return_stmt', '_cps_multi_assign_stmt', '_cps_import_stmt',
    ]),
    ('_cpp_with_stmt', 'list[str]', 256, [
        '_cpw_async_with',
    ]),
    ('_cpp_yield_from', 'list[str]', 595, [
        '_cpy_handle_local', '_cpy_unsupported_shape',
    ]),
    ('_cpp_for_stmt', 'list[str]', 456, [
        '_cpf_word_iterable', '_cpf_param_call', '_cpf_generator_handle',
        '_cpf_simple_target_call_iterable', '_cpf_call_iterable',
        '_cpf_list_iter_cursor', '_cpf_named_target',
    ]),
]

# The five dispatch functions the coro pass must not read as a pass-through
# caller (see the module docstring).  Their calls go through `gen.<name>(...)`.
PRINTERS = [row[0] for row in PARENTS]

_TOTAL = re.compile(r'^(\d+) lines can be moved$')


def list_arms(path: str, parent: str):
    """(movable_line_count, unexpected_lines) from `extract_arm.py --list`.

    25 lines is the floor the stage-6 pins measured their tables with.
    """
    p = subprocess.run(
        [sys.executable, TOOL, '--list', path, parent, '25'],
        capture_output=True, text=True)
    if p.returncode != 0:
        return None, [f'{parent}: --list exited {p.returncode}: '
                      + (p.stderr or p.stdout).strip().split('\n')[-1]]
    lines = p.stdout.strip().split('\n')
    m = _TOTAL.match(lines[-1]) if lines else None
    if not m:
        return None, [f'{parent}: no "N lines can be moved" line: {lines[-1:]!r}']
    odd = [l for l in lines[:-1] if ' NO (' not in l]
    return int(m.group(1)), odd


def main() -> int:
    src = open(PATH).read()
    tree = ast.parse(src)
    top = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    failures = []
    pinned = 0

    for parent, ret, ratchet, arms in PARENTS:
        fd = top.get(parent)
        if fd is None:
            failures.append(f'{parent}: the dispatch function is gone')
            continue

        calls = {}
        for n in ast.walk(fd):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                calls[n.func.id] = calls.get(n.func.id, 0) + 1
        got = {name for name in calls if name in arms}
        missing = sorted(set(arms) - got)
        if missing:
            failures.append(f'{parent}: not called from the parent: '
                            + ', '.join(missing))
        for name in arms:
            pinned += 1
            fn = top.get(name)
            if fn is None:
                failures.append(f'{name}: not a module-level function')
                continue
            if calls.get(name) != 1:
                failures.append(f'{name}: called {calls.get(name, 0)} times '
                                f'from {parent}; an arm is called once')
            want = ast.unparse(fn.returns) if fn.returns else ''
            # An expression arm not yet migrated still returns its C++ text; the
            # dispatcher wraps it with ex_text. Each migration removes it from this list.
            if name in EXPR_ARMS_STILL_TEXT and parent == '_cpp_expr_ex':
                want_ok = want in ('str', 'str | None')
            else:
                want_ok = want in (ret, ret + ' | None')
            if not want_ok:
                failures.append(f'{name}: return annotation {want!r}, '
                                f'want {ret!r} (or {ret + " | None"!r} for a '
                                f'fall-through arm)')

        lines = fd.end_lineno - fd.lineno + 1
        if lines > ratchet:
            failures.append(f'{parent} is {lines} lines, over the '
                            f'{ratchet}-line ratchet: extract the new arm '
                            f'with tools/extract_arm.py instead of inlining it')

        total, odd = list_arms(PATH, parent)
        if total is None:
            failures.extend(odd)
        elif total != 0:
            failures.append(f'{parent} still has {total} movable line(s): '
                            f'extract them with tools/extract_arm.py')
        elif odd:
            failures.append(f'{parent}: ' + '; '.join(odd[:3]))

    # A direct top-level call to a printer re-creates the coro pass-through
    # cycle described in the module docstring.
    for name in PRINTERS:
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == name):
                failures.append(f'line {n.lineno}: bare `{name}(...)` call; '
                                f'call `gen.{name}(...)` so the coro '
                                f'pass-through analysis stays out of it')

    # The IR helpers take C text or a stage-2b Ex operand, and the printer arms pass
    # both. A string reaching `Instr.show()` as an Ex crashed the generator corpus
    # (`'str' object has no attribute 'show'`), and the corpus does not reach every
    # arm, so each helper is pinned here with text operands directly.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mojo.backend_gimple import cpp_core as _C
    from mojo.ir.instr import ex_text as _ex
    text_cases = [
        (_C._cpp_assign_line('x', '1', '  '), '  x = 1;'),
        (_C._cpp_assign_line(_ex('x'), _ex('y'), ''), 'x = y;'),
        (_C._cpp_assign_line('*p', 'q', ''), '*p = q;'),
        (_C._cpp_call_line('  ', 'fprintf', ['stderr', '"m\\n"']), '  fprintf(stderr, "m\\n");'),
        (_C._cpp_ir_line('  ', 'end'), '  }'),
        (_C._cpp_ir_line('  ', 'for', '; c < n; '), '  for (; c < n; ) {'),
        (_C._cpp_ir_line('  ', 'decl', 'int64_t x'), '  int64_t x;'),
        (_C._cpp_ir_line('  ', 'block'), '  {'),
        (_C._cpp_ir_line('  ', 'coyield', '(0)'), '  co_yield (0);'),
        (_C._cpp_ir_line('  ', 'throw', 'x'), '  throw x;'),
        (_C._cpp_ir_line('  ', 'if', 'c'), '  if (c) {'),
        (_C._cpp_call_line('  ', 'mojo_exc_pending_set', ['0']), '  mojo_exc_pending_set(0);'),
    ]
    text_cases.append((_C._cpp_call_ex('f', ['a', '1']).show(), 'f(a, 1)'))
    text_cases.append((_C._cpp_call_ex('mojo_cstr_slice', ['(char *)(s)', '0', 'MOJO_SLICE_STOP_OMITTED']).show(), 'mojo_cstr_slice((char *)(s), 0, MOJO_SLICE_STOP_OMITTED)'))
    # The slice arm's three branches, through a stub generator: the list step,
    # the word step and the plain cstr slice (the corpus does not reach them all).
    import fire_compiler as _N

    class _StubGen:
        def __init__(self, decl):
            self._cpp_declared = decl
        def _cpp_expr(self, n):
            return n.name if isinstance(n, _N.IdentExpr) else str(n.value)
        def _cpp_container_cast_prefix(self, name, boxed):
            return ''

    def _slice(decl, obj, start, stop, step):
        n = _N.SliceExpr(obj=obj, start=start, stop=stop, step=step)
        return _C._cpx_slice_expr(_StubGen(decl), n).show()

    # The unary arm, through a stub: the strlen and truthy branches of `not`, and the
    # plain operator. Expected strings are HEAD's arm output for the same stub.
    class _UGen(_StubGen):
        def __init__(self, decl, params=()):
            super().__init__(decl)
            self._cpp_param_names = params
            self._cpp_none_guards = {}
        def _cpp_expr_ex(self, n):
            return _C._cpp_expr_ex(self, n)

    def _unary(op, decl, params=()):
        return _C._cpx_unary_op(_UGen(decl, params), _N.UnaryOp(op=op, operand=_N.IdentExpr(name='x'))).show()

    text_cases.append((_unary('not', {'x': 'char *'}), '(mojo_strlen((char *)(x)) == 0)'))
    text_cases.append((_unary('not', {'x': 'MojoList *'}), '(!mojo_truthy_word((int64_t)(intptr_t)(x)))'))
    text_cases.append((_unary('not', {'x': 'int64_t'}, ('x',)), '(!mojo_truthy_word((int64_t)(intptr_t)(x)))'))
    text_cases.append((_unary('not', {'x': 'int64_t'}), '(!x)'))
    text_cases.append((_unary('~', {'x': 'int64_t'}), '(~x)'))
    text_cases.append((_unary('-', {'x': 'MojoList *'}), '(-x)'))
    # The walrus and compare-chain arms, through a stub. Expected strings are HEAD's output.
    class _EGen(_StubGen):
        def __init__(self, decl):
            super().__init__(decl)
            self._cpp_param_names = ()
            self._cpp_none_guards = {}
            self._cpp_gen_self_struct = None
            self._async_api = None
            self._cpp_gen_self_fields = None
        def _cpp_expr_ex(self, n):
            return _C._cpp_expr_ex(self, n)
        def _cpp_struct_ptr_local(self, name):
            return False
        def _cpp_in_link(self, a, an, b, bn, negate=False):
            return f"in({a},{b})"

    _iv = lambda v: _N.IntLiteral(value=v)
    _walrus_name = _N.BinaryOp(op=':=', left=_N.IdentExpr(name='q'), right=_iv(3))
    text_cases.append((_C._cpx_walrus(_EGen({}), _walrus_name).show(), '(q = 3)'))
    _walrus_sub = _N.BinaryOp(op=':=', left=_N.SubscriptExpr(obj=_N.IdentExpr(name='xs'), index=_iv(1)), right=_iv(4))
    text_cases.append((_C._cpx_walrus(_EGen({'xs': 'MojoList *'}), _walrus_sub).show(),
                       '(mojo_list_set_int(xs, (int64_t)(1), (int64_t)(4)))'))
    _chain = _N.CompareChain(operands=[_N.IdentExpr(name='x'), _N.IdentExpr(name='y'), _N.IdentExpr(name='z')], ops=['<', '<='])
    text_cases.append((_C._cpx_compare_chain(_EGen({'x': 'int64_t', 'y': 'int64_t', 'z': 'int64_t'}), _chain).show(),
                       '((x < y) && (y <= z))'))
    # The identifier arm, through a stub: the literal spellings, a mutable capture, a
    # keyword-renamed parameter, a module global and a plain name. Expected strings are HEAD's.
    class _IGen(_StubGen):
        def __init__(self):
            super().__init__({'x': 'int64_t'})
            self._cpp_gen_self_struct = None
            self._cpp_mut_capture_names = {'x'}
            self._generator_api = {}
            self._supported_generators = ()
            self._global_var_types = {'zz': 'int64_t'}
            self._cpp_early_global_names = set()
            self.module_name = 'mm'
            self._current_module_ctx = None
            self._cpp_module_global_refs = set()
            self._cpp_module_func_refs = set()
            self.func_param_types = {}
            self._cpp_kw_param_renames = {'default': 'default_'}
        def _func_csym(self, n):
            return n
        def _cpp_sig_default_word(self, e):
            return None
        def _cpp_expr_ex(self, n):
            return _C._cpp_expr_ex(self, n)

    for _nm, _want in (('None', '0'), ('True', 'true'), ('False', 'false'), ('x', '(*x)'),
                       ('default', 'default_'), ('y', 'y'), ('zz', '_mm_globals.zz')):
        text_cases.append((_C._cpx_ident_expr(_IGen(), _N.IdentExpr(name=_nm)).show(), _want))
    # The subscript arm, through a stub. Expected strings are HEAD's arm output.
    class _SGen(_StubGen):
        def __init__(self, decl, **kw):
            super().__init__(decl)
            self._cpp_gen_self_struct = None
            self._async_api = None
            self._cpp_gen_self_fields = None
            self._cpp_list_local_elem_types = kw.get('elem', {})
            self._cpp_local_container_shapes = kw.get('shapes', {})
            self._cpp_local_dict_val_types = kw.get('dictval', {})
            self.func_return_types = {}
            self._cpp_object_params = kw.get('objp', ())
            self._cpp_none_guards = {}
            self._cpp_param_names = ()
        def _cpp_expr_ex(self, n):
            return _C._cpp_expr_ex(self, n)
        def _cpp_refuse_str_key_subscript(self, e):
            pass
        def _cpp_struct_ptr_local(self, n):
            return False
        def _cpp_dict_key_expr(self, idx_node, idx):
            return f'"{idx}"'

    _sub = lambda decl, **kw: _C._cpx_subscript_expr(_SGen(decl, **kw), _N.SubscriptExpr(obj=_N.IdentExpr(name='xs'), index=_N.IntLiteral(value=1))).show()
    text_cases.append((_sub({'xs': 'MojoList *'}), 'mojo_list_get_int((MojoList *)(xs), (int64_t)(1))'))
    text_cases.append((_sub({'xs': 'MojoList *'}, elem={'xs': 'char *'}), 'mojo_list_get_str((MojoList *)(xs), (int64_t)(1))'))
    text_cases.append((_sub({'xs': 'MojoDict *'}, dictval={'xs': 'Node *'}), '(Node *)mojo_dict_get_int((MojoDict *)(xs), "1")'))
    text_cases.append((_sub({'xs': 'int64_t'}, objp=('xs',)), 'mojo_getitem_word((int64_t)(xs), (int64_t)(1))'))
    text_cases.append((_sub({'xs': 'char *'}), 'mojo_char_at_str_cp((char *)(xs), 1)'))
    # The binary arm, through a stub. Expected strings are HEAD's arm output. The floormod
    # and div branches are not reached by any stub input here, so their call text is pinned
    # on the helper directly.
    def _bin(op, decl, left=None, right=None):
        n = _N.BinaryOp(op=op, left=left or _N.IdentExpr(name='x'), right=right or _N.IdentExpr(name='y'))
        return _C._cpx_binary_op(_SGen(decl), n).show()

    text_cases.append((_bin('//', {'x': 'int64_t', 'y': 'int64_t'}), '__mojo_floordiv(x, y)'))
    text_cases.append((_bin('**', {'x': 'int64_t', 'y': 'int64_t'}), 'pow(x, y)'))
    text_cases.append((_bin('+', {'x': 'int64_t', 'y': 'int64_t'}), '(x + y)'))
    text_cases.append((_bin('+', {'x': 'char *', 'y': 'char *'}), 'mojo_str_cat((char *)(x), (char *)(y))'))
    text_cases.append((_bin('%', {'x': 'int64_t'}, right=_N.IntLiteral(value=3)), '(x % mojo_int_divisor((int64_t)(3)))'))
    text_cases.append((_C._cpp_call_ex('__mojo_floormod', ['(int64_t)(a)', '(int64_t)(b)']).show(),
                       '__mojo_floormod((int64_t)(a), (int64_t)(b))'))
    text_cases.append((_C._cpp_call_ex('mojo_div_double', ['(double)(a)', '(double)(b)']).show(),
                       'mojo_div_double((double)(a), (double)(b))'))
    _xs = _N.IdentExpr(name='xs')
    _ints = lambda v: _N.IntLiteral(value=v)
    _lst = _slice({'xs': 'MojoList *'}, _xs, _ints(1), _ints(4), _ints(2))
    # Expected text is HEAD's arm output for the same stub (the operand is parenthesised).
    text_cases.append((_lst, 'mojo_list_slice_step((xs), 1, (int64_t)(1), 1, (int64_t)(4), (int64_t)(2))'))
    _wrd = _slice({'xs': 'int64_t'}, _xs, _ints(1), None, _ints(2))
    text_cases.append((_wrd, 'mojo_word_slice_step((int64_t)(xs), 1, (int64_t)(1), 0, (int64_t)(0), (int64_t)(2))'))
    _cst = _slice({'xs': 'char *'}, _xs, _ints(0), _ints(3), None)
    text_cases.append((_cst, 'mojo_cstr_slice((char *)(xs), 0, 3)'))
    from mojo.ir.instr import Ex as _Ex
    _p = _Ex('paren'); _p.a = _ex('a + b')
    text_cases.append((_p.show(), '(a + b)'))
    _u = _Ex('un'); _u.op = '!'; _u.a = _ex('x')
    text_cases.append((_u.show(), '!x'))
    for got, want in text_cases:
        if got != want:
            failures.append(f'IR helper text: got {got!r}, want {want!r}')

    for f in failures:
        print(f'FAIL: {f}')
    print(f'{pinned} arm(s) pinned across {len(PARENTS)} printer(s), '
          f'{len(failures)} failure(s)')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
