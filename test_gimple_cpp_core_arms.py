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
PARENTS = [
    ('_cpp_expr', 'str', 101, [
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
            if want not in (ret, ret + ' | None'):
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

    for f in failures:
        print(f'FAIL: {f}')
    print(f'{pinned} arm(s) pinned across {len(PARENTS)} printer(s), '
          f'{len(failures)} failure(s)')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
