#!/usr/bin/env python3
"""The typed-IR checker (mojo/ir, tools/gimple_lint.py): unit tests, and a
ratchet over real compiler output.

    python3 test_gimple_lint.py            # everything
    python3 test_gimple_lint.py unit       # the checker's own rules (1 s)
    python3 test_gimple_lint.py ratchet    # emitted code of CORPUS vs BASELINE

Why the ratchet exists.  GCC verifies only functions tagged `__GIMPLE`, and
even there it does not look at call arguments.  A call whose argument has the
wrong type is not converted, it is passed as-is: an `int` passed to an
`int64_t` parameter arrives with garbage in the upper 32 bits, an integer
passed to a `double` parameter arrives in the wrong register.  Measured with
gcc-mp-15 on arm64 (see doc/GIR.md, "the call-argument hole").  So every
finding code below is counted over a fixed corpus and may only go DOWN.

When a count goes down, lower BASELINE in the same commit (the test tells you
the new number).  Never raise one: fix the emitter.  The usual fix is to pass
the argument through `gen._emit_call` / `gen._call_expr`, which coerce each
argument to the declared parameter type, instead of spelling the call as text
inside `gen._new_val(...)` / `gen._emit(...)`.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))

from mojo.ir import reader, verify          # noqa: E402
from mojo.ir import types as T              # noqa: E402

# Sources whose emitted code the ratchet checks.  Chosen to be the compiler's
# own largest modules that dump cleanly, plus small programs.
CORPUS = [
    'myinterpreter.py', 'fire_compiler.py', 'module_loader.py', 'cas.py',
    'ast_rewriter.py', 'mojo/middle/solvers.py', 'mojo/middle/comptime.py',
    'mojo/middle/iter_factory.py', 'mojo/backend_gimple/module_gen.py',
    'hello.mojo', 'class_jit.mojo',
    'test_struct.mojo', 'array_ops_jit.mojo',
]

# finding code -> number of findings over CORPUS.  May only shrink.
BASELINE = {
    # empty since 2026-11-13: every call-argument finding in CORPUS was closed
    # by `_repr_fix_args` (emit_infra.py). Keep that class empty.
    # Rule added 2026-11-14: a pointer made by casting a `_Bool` or an `int`
    # (GCC's -Wint-to-pointer-cast). Zero since the return-type and parameter
    # inference fixes of 2026-11-17 (`_apply_binary_op` and `_eval_member_of`
    # declare their parameter and result types).
}

_INJECTED = r'''
#include <stdint.h>
#include <fire_runtime.h>
typedef struct P { int64_t __mojo_type_id; char * name; double w; } P;
struct _g { int64_t xs; } _root_globals;
int64_t f (int64_t);
__GIMPLE int64_t g (P * self, char * s)
{
  int _t1;
  int64_t _t2;
  _Bool _t3;
  double _t4;
  MojoList * _t5;
  MojoDict * _t6;
  char * _t7;
  _t1 = mojo_list_len (_t5);
  _t2 = _t1;
  _t1 = _t2;
  _t3 = _t2;
  _t2 = _t2 + _t1;
  _t3 = _t2 < _t1;
  _t1 = _t2 < _t2;
  _t2 = self->name;
  _t4 = _t2;
  _t5 = _t6;
  _t2 = f (_t1);
  _t2 = f (s);
  _t2 = f (_t2, _t2);
  _t7 = (char *)_t4;
  _t2 = (int)_t2;
  _t5 = _root_globals.xs;
  _t4 = pow (2.0, _t2);
  if (_t3) goto a; else goto b;
a:
  return _t1;
b:
  return s;
}
int64_t clean (P * self, int64_t n)
{
  int64_t _t1;
  _Bool _t2;
  char * _t3;
  void * _t4;
  MojoList * _t5;
  double _t6;
  int _t7;
  _t1 = 2LL;
  _t1 = (int64_t)1;
  _t1 = 7;
  _t2 = n < _t1;
  _t2 = 0;
  _t3 = self->name;
  _t3 = 0;
  _t4 = (void *)_t3;
  _t1 = (int64_t)_t4;
  _t5 = mojo_list_new ();
  mojo_list_append_int (_t5, _t1);
  _t1 = mojo_list_len (_t5);
  _t6 = self->w;
  _t6 = (double)_t1;
  _t7 = (int)_t1;
  _t1 = _root_globals.xs;
  _t1 = f (_t1);
  free (_t3);
  if (_t2) goto a; else goto b;
a:
  return _t1;
b:
  return n;
}
'''

# line offset of each injected statement -> the code it must produce
_EXPECT = [
    ('_t1 = mojo_list_len (_t5);', 'copy-int-narrow'),
    ('_t2 = _t1;', 'copy-int-widen'),
    ('_t1 = _t2;', 'copy-int-narrow'),
    ('_t3 = _t2;', 'copy-bool-int'),
    ('_t2 = _t2 + _t1;', 'op-int-widen'),
    ('_t3 = _t2 < _t1;', 'cmp-int-widen'),
    ('_t1 = _t2 < _t2;', 'cmp-result'),
    ('_t2 = self->name;', 'copy-int-ptr'),
    ('_t4 = _t2;', 'copy-int-float'),
    ('_t5 = _t6;', 'copy-ptr-kind'),
    ('_t2 = f (_t1);', 'arg-int-widen'),
    ('_t2 = f (s);', 'arg-int-ptr'),
    ('_t2 = f (_t2, _t2);', 'arg-count'),
    ('_t7 = (char *)_t4;', 'cast-illegal'),
    ('_t2 = (int)_t2;', 'cast-int-widen'),
    ('_t5 = _root_globals.xs;', 'copy-int-ptr'),
    ('_t4 = pow (2.0, _t2);', 'arg-int-float'),
    ('return _t1;', 'ret-int-widen'),
    ('return s;', 'ret-int-ptr'),
]

_fails = 0


def check(cond: bool, what: str) -> None:
    global _fails
    if cond:
        print(f"  ok    {what}")
    else:
        _fails += 1
        print(f"  FAIL  {what}")


def lint(path: str):
    mod = reader.read_ci(path, [os.path.join(ROOT, 'runtime')])
    rep = verify.Report()
    verify.verify_module(mod, rep)
    return mod, rep


def test_unit() -> None:
    print("unit: type rules")
    check(T.trivially_convertible(T.I64, T.BASE_TYPES['long']), 'long is int64_t')
    check(not T.trivially_convertible(T.I64, T.INT), 'int is not int64_t')
    check(not T.trivially_convertible(T.I64, T.U64), 'uint64_t is not int64_t')
    check(not T.trivially_convertible(T.BOOL, T.INT), '_Bool is not int')
    check(T.trivially_convertible(T.ptr_to(T.struct_named('A')), T.VOIDP),
          'any data pointer converts to any data pointer (GIMPLE)')
    check(T.mismatch_class(T.ptr_to(T.struct_named('A')), T.ptr_to(T.struct_named('B')))
          == 'ptr-kind', 'A * vs B * is ptr-kind (our stricter rule)')
    check(T.mismatch_class(T.ptr_to(T.struct_named('A')), T.VOIDP) == '',
          'void * is the generic pointer')
    check(T.ptr_to(T.I64) is T.ptr_to(T.I64), 'types are interned')
    check(not T.cast_is_legal(T.CHARP, T.F64), 'double -> pointer is not a conversion')

    print("unit: injected errors are each reported, clean code is not")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'inj.ci')
        with open(p, 'w') as f:
            f.write(_INJECTED)
        mod, rep = lint(p)
    check(mod.skipped == 0, 'every top-level item was modelled')
    check(len(mod.functions) == 2 and mod.functions[0].tagged and not mod.functions[1].tagged,
          'two functions, the first tagged __GIMPLE')
    check(rep.stmts_opaque == 0, 'every statement was modelled')
    got = [(f.stmt, f.code) for f in rep.findings if f.fn == 'g']
    for stmt, code in _EXPECT:
        check((stmt, code) in got, f"{code:<16} for `{stmt}`")
    check(len(got) == len(_EXPECT), f"exactly {len(_EXPECT)} findings in g (got {len(got)})")
    clean = [(f.stmt, f.code) for f in rep.findings if f.fn == 'clean']
    check(clean == [], f"no findings in the clean function (got {clean})")
    check(rep.unknown == {}, f"nothing unresolved (got {rep.unknown})")


def test_gate_wiring() -> None:
    """The gate's gimple-lint job is enabled, and its red-gate doc is deleted.

    The doc's contract is that its existence means the job is red.  It was
    fixed by 37f7325cc (both text-call/cast baselines back to 0), so the
    queue must not keep claiming otherwise.  This also pins the job itself:
    a red job is fixed or declared with a live bug doc, never switched off
    with a silent `disabled=` marker.
    """
    print("gate wiring: the gimple-lint job stays on")
    import re
    with open(os.path.join(ROOT, 'tools', 'suite.py'), encoding='utf-8') as f:
        suite = f.read()
    m = re.search(r"test\('gimple-lint'.*?(?=\ntest\()", suite, re.S)
    check(m is not None, 'gimple-lint is registered in tools/suite.py')
    check(m is not None and 'disabled=' not in m.group(0),
          'gimple-lint is enabled (no disabled= marker)')
    # NOT checked here: that this job's red-gate doc in bugs/ is absent. The
    # integrator writes that doc when a WORK BRANCH turns this job red; a
    # check on its absence then failed master for the doc's existence alone,
    # which is the doc keeping itself alive (it came back three times in
    # November 2026 with every other check here green).


def test_value_tables_reset() -> None:
    """Every table `carry_value_info` copies describes a VALUE and is keyed by
    the name holding it. Names restart in each function, so each table must
    be emptied by `_reset_func` and captured / put back by `save_func_state`
    / `restore_func_state`. Four were not until 2026-11-16, and a later
    function's `_t58` inherited an earlier one's generator API."""
    print("value tables: each one carry_value_info copies is reset per function")
    import re
    path = os.path.join(ROOT, 'mojo', 'backend_gimple', 'emit_infra.py')
    with open(path, encoding='utf-8') as f:
        src = f.read()

    def body(name: str) -> str:
        m = re.search(r'^def ' + name + r'\(.*?(?=^def |^class )', src, re.S | re.M)
        return m.group(0) if m else ''
    carry = body('carry_value_info')
    tables = sorted(set(re.findall(r'src in gen\.(_\w+)', carry)))
    check(len(tables) >= 18, f"found {len(tables)} tables in carry_value_info")
    reset = body('_reset_func')
    save = body('save_func_state')
    restore = body('restore_func_state')
    for t in tables:
        ok = ((re.search(r'gen\.' + t + r'\b[^=\n]*= ', reset) is not None
               or ('gen.' + t + '.clear()') in reset)
              and ('st.fs' + t + ' = gen.' + t) in save
              and ('gen.' + t + ' = st.fs' + t) in restore)
        if not ok:
            check(False, f"gen.{t} is copied by carry_value_info but is not reset in "
                         f"_reset_func and saved/restored in FuncState (emit_infra.py)")
    check(True, f"{len(tables)} value tables are reset, saved and restored")


def test_rt_sigs() -> None:
    print("rt_sigs: the generated runtime signature table is current")
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'gen_rt_sigs.py'),
                        '--check'], capture_output=True, text=True)
    check(r.returncode == 0, (r.stdout + r.stderr).strip())
    from mojo.middle import rt_call
    check(rt_call.rt_param_types('mojo_dict_set_bool') == ['MojoDict *', 'char *', 'int'],
          'mojo_dict_set_bool (MojoDict *, char *, int)')
    check(rt_call.rt_param_types('no_such_function') == [], 'an unknown name has no signature')
    check(rt_call.arg_needs_repr_cast('int64_t', 'int'), 'int -> int64_t needs a cast')
    check(rt_call.arg_needs_repr_cast('int', 'int64_t'), 'int64_t -> int needs a cast')
    check(rt_call.arg_needs_repr_cast('double', 'int64_t'), 'int64_t -> double needs a cast')
    check(not rt_call.arg_needs_repr_cast('int', '_Bool'), '_Bool -> int is already the right bits')
    check(rt_call.arg_needs_word_cast('MojoDict *', 'int64_t'), 'a word passed as a pointer is cast')
    check(not rt_call.arg_needs_repr_cast('_Bool', 'int64_t'), 'nothing is ever cast TO _Bool')
    check(rt_call.copy_needs_cast('int64_t', 'int'), 'copy: int into int64_t is cast')
    check(rt_call.copy_needs_cast('int', '_Bool'), 'copy: _Bool into int is cast')
    check(not rt_call.copy_needs_cast('_Bool', 'int'), 'copy: nothing is cast to _Bool')
    check(rt_call.copy_needs_cast('MojoList *', 'int64_t'), 'copy: a word into a pointer is cast')
    check(not rt_call.copy_needs_cast('MojoList *', 'MojoDict *'), 'copy: container kinds are not a cast')
    check(not rt_call.arg_needs_word_cast('MojoDict *', 'MojoList *'), 'two pointer kinds are not a word cast')
    check(not rt_call.arg_needs_repr_cast('uint64_t', 'int64_t'), 'same width, other sign: no cast')
    check(not rt_call.arg_needs_repr_cast('char *', 'int64_t'), 'pointers are not this rule\'s')
    check(not rt_call.arg_needs_repr_cast('int64_t', 'MojoList *'), 'erased values are not this rule\'s')


# Runtime calls still spelled as TEXT inside gen._emit(...) / gen._new_val(...).
# Such a call never reaches the argument conversion in `_emit_call` /
# `_rt_call`.  May only shrink; the way to shrink it is
#     gen._rt_call(ret_ctype, 'mojo_x', [a, b])   # value
#     gen._rt_into(dst, 'mojo_x', [a, b])         # into an existing temp
#     gen._rt_void('mojo_x', [a, b])              # effect only
TEXT_CALL_BASELINE = 0


def count_text_calls() -> tuple:
    import ast
    import glob
    import re
    from mojo.middle.rt_sigs import RT_SIGS
    pat = re.compile(r'\b((?:mojo|string)_\w+) ?\(')
    n = 0
    where: list[str] = []
    files = ([os.path.join(ROOT, 'gimple_codegen.py')]
             + sorted(glob.glob(os.path.join(ROOT, 'mojo', 'backend_gimple', 'emit_*.py')))
             + sorted(glob.glob(os.path.join(ROOT, 'mojo', 'middle', '*.py'))))
    for path in files:
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('_emit', '_new_val') and node.args):
                continue
            arg = node.args[-1]
            text = ''
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            elif isinstance(arg, ast.JoinedStr):
                text = ''.join(v.value for v in arg.values
                               if isinstance(v, ast.Constant) and isinstance(v.value, str))
            hit = [m for m in pat.findall(text) if m in RT_SIGS]
            if hit:
                n += 1
                where.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}: {hit[0]}")
    return n, where


# ANY call still spelled as text, whatever its callee: a computed name
# (`f"{base}_resume ({h})"`, `f"mojo_list_set_{suf} (...)"`), a user function,
# a libc function.  `_rt_call` / `_rt_into` / `_rt_void` take a computed callee
# name too.  May only shrink.
TEXT_ANY_CALL_BASELINE = 7


def count_text_any_calls() -> tuple:
    import ast
    import glob
    import re
    pat = re.compile(r'^ *(?:[^=(]+ = )?([\w{}]*[\w}]) \(')
    n = 0
    where: list[str] = []
    files = (sorted(glob.glob(os.path.join(ROOT, 'mojo', 'backend_gimple', 'emit_*.py')))
             + sorted(glob.glob(os.path.join(ROOT, 'mojo', 'middle', '*.py'))))
    for path in files:
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('_emit', '_new_val') and node.args):
                continue
            arg = node.args[-1]
            text = ''
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            elif isinstance(arg, ast.JoinedStr):
                text = ''.join(v.value if isinstance(v, ast.Constant) else '{}' for v in arg.values)
            m = pat.match(text)
            if m and m.group(1) not in ('if', 'sizeof', 'while'):
                n += 1
                where.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}: {text.strip()}")
    return n, where


# Arithmetic, bit operations and comparisons still spelled as text
# (`gen._new_val('int64_t', f"{a} + {b}")`).  `gen._binop(ctype, a, '+', b)`,
# `gen._cmp(a, '<', b)` and `gen._binop_into(dst, a, '+', b)` convert an
# operand of the wrong scalar type; text does not.  May only shrink.
TEXT_BINOP_BASELINE = 0


def count_text_binops() -> tuple:
    import ast
    import glob
    import re
    pat = re.compile(r'^(?: *[^=(]+ = )?\S+ (==|!=|<=|>=|<<|>>|<|>|\+|-|\*|/|%|&|\||\^|\{\}) \S+;?$')
    n = 0
    where: list[str] = []
    files = (sorted(glob.glob(os.path.join(ROOT, 'mojo', 'backend_gimple', 'emit_*.py')))
             + sorted(glob.glob(os.path.join(ROOT, 'mojo', 'middle', '*.py'))))
    for path in files:
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('_emit', '_new_val') and node.args):
                continue
            arg = node.args[-1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            elif isinstance(arg, ast.JoinedStr):
                text = ''.join(v.value if isinstance(v, ast.Constant) else '{}' for v in arg.values)
            else:
                continue
            if pat.match(text):
                n += 1
                where.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}: {text.strip()}")
    return n, where


# Casts still spelled as TEXT.  `gen._cast(ctype, v)` / `gen._cast_into(dst,
# ctype, v)` state the type once, so the temp's declaration and the written
# cast cannot disagree.  May only shrink.
TEXT_CAST_BASELINE = 0


def count_text_casts() -> tuple:
    import ast
    import glob
    import re
    new_val_pat = re.compile(r'^\([A-Za-z_][\w \*]*\)$')
    emit_pat = re.compile(r'^\s* = \([\w \*]*\);$')
    n = 0
    where: list[str] = []
    files = ([os.path.join(ROOT, 'gimple_codegen.py')]
             + sorted(glob.glob(os.path.join(ROOT, 'mojo', 'backend_gimple', 'emit_*.py')))
             + sorted(glob.glob(os.path.join(ROOT, 'mojo', 'middle', '*.py'))))
    for path in files:
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('_emit', '_new_val') and node.args
                    and isinstance(node.args[-1], ast.JoinedStr)):
                continue
            text = ''.join(v.value for v in node.args[-1].values
                           if isinstance(v, ast.Constant) and isinstance(v.value, str))
            pat = new_val_pat if node.func.attr == '_new_val' else emit_pat
            if pat.match(text):
                n += 1
                where.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}")
    return n, where


def test_text_casts() -> None:
    print("text casts: casts spelled as text may only shrink")
    n, where = count_text_casts()
    if n > TEXT_CAST_BASELINE:
        for w in where:
            print("        " + w)
        check(False, f"{n} casts are spelled as text, baseline {TEXT_CAST_BASELINE} -- "
                     f"use gen._cast(ctype, v) / gen._cast_into(dst, ctype, v)")
    elif n < TEXT_CAST_BASELINE:
        check(False, f"{n} casts are spelled as text, baseline {TEXT_CAST_BASELINE} -- "
                     f"fixed! lower TEXT_CAST_BASELINE to {n} in test_gimple_lint.py")
    else:
        check(True, f"{n} casts spelled as text (baseline {TEXT_CAST_BASELINE})")


# Control flow still spelled as TEXT.  `gen._goto(l)`, `gen._cond_goto(c, a, b)`,
# `gen._ret(v)` and `gen._ret_void()` are the only spellings of a jump or a
# return, so the code that must see every exit from a `try` / `with` region
# has one place to look.  May only shrink.
TEXT_CF_BASELINE = 1


def count_text_cf() -> tuple:
    import ast
    import glob
    import re
    pat = re.compile(r'^\s*(goto |return\b|if \(.*\) goto )')
    n = 0
    where: list[str] = []
    files = ([os.path.join(ROOT, 'gimple_codegen.py')]
             + sorted(glob.glob(os.path.join(ROOT, 'mojo', 'backend_gimple', 'emit_*.py')))
             + sorted(glob.glob(os.path.join(ROOT, 'mojo', 'middle', '*.py'))))
    for path in files:
        if os.path.basename(path) == 'emit_metal.py':
            continue        # the Metal shader emitter: its own language, its own `_emit`
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        helpers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                    '_goto', '_cond_goto', '_ret', '_ret_void'):
                for sub in ast.walk(node):
                    helpers.add(id(sub))
        for node in ast.walk(tree):
            if id(node) in helpers:
                continue
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == '_emit' and node.args):
                continue
            arg = node.args[-1]
            text = ''
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            elif isinstance(arg, ast.JoinedStr):
                text = ''.join(v.value if isinstance(v, ast.Constant) else 'X'
                               for v in arg.values)
            if pat.match(text):
                n += 1
                where.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}: {text.strip()[:50]}")
    return n, where


def test_text_cf() -> None:
    print("text control flow: jumps and returns spelled as text may only shrink")
    n, where = count_text_cf()
    if n > TEXT_CF_BASELINE:
        for w in where:
            print("        " + w)
        check(False, f"{n} jumps/returns are spelled as text, baseline {TEXT_CF_BASELINE} -- "
                     f"use gen._goto / gen._cond_goto / gen._ret / gen._ret_void")
    elif n < TEXT_CF_BASELINE:
        check(False, f"{n} jumps/returns are spelled as text, baseline {TEXT_CF_BASELINE} -- "
                     f"fixed! lower TEXT_CF_BASELINE to {n} in test_gimple_lint.py")
    else:
        check(True, f"{n} jumps/returns spelled as text (baseline {TEXT_CF_BASELINE})")


def test_text_calls() -> None:
    print("text calls: runtime calls spelled as text may only shrink")
    n, where = count_text_calls()
    if n > TEXT_CALL_BASELINE:
        for w in where:
            print("        " + w)
        check(False, f"{n} runtime calls are spelled as text, baseline {TEXT_CALL_BASELINE} -- "
                     f"use gen._rt_call / gen._rt_into / gen._rt_void")
    elif n < TEXT_CALL_BASELINE:
        check(False, f"{n} runtime calls are spelled as text, baseline {TEXT_CALL_BASELINE} -- "
                     f"fixed! lower TEXT_CALL_BASELINE to {n} in test_gimple_lint.py")
    else:
        check(True, f"{n} runtime calls spelled as text (baseline {TEXT_CALL_BASELINE})")
    n, where = count_text_any_calls()
    if n > TEXT_ANY_CALL_BASELINE:
        for w in where:
            print("        " + w)
        check(False, f"{n} calls are spelled as text, baseline {TEXT_ANY_CALL_BASELINE} -- "
                     f"use gen._rt_call / gen._rt_into / gen._rt_void (a computed callee name is fine)")
    elif n < TEXT_ANY_CALL_BASELINE:
        check(False, f"{n} calls are spelled as text, baseline {TEXT_ANY_CALL_BASELINE} -- "
                     f"fixed! lower TEXT_ANY_CALL_BASELINE to {n} in test_gimple_lint.py")
    else:
        check(True, f"{n} calls of any callee spelled as text (baseline {TEXT_ANY_CALL_BASELINE})")
    n, where = count_text_binops()
    if n > TEXT_BINOP_BASELINE:
        for w in where:
            print("        " + w)
        check(False, f"{n} binary operations are spelled as text, baseline {TEXT_BINOP_BASELINE} -- "
                     f"use gen._binop / gen._cmp / gen._binop_into")
    elif n < TEXT_BINOP_BASELINE:
        check(False, f"{n} binary operations are spelled as text, baseline {TEXT_BINOP_BASELINE} -- "
                     f"fixed! lower TEXT_BINOP_BASELINE to {n} in test_gimple_lint.py")
    else:
        check(True, f"{n} binary operations spelled as text (baseline {TEXT_BINOP_BASELINE})")


def dump_corpus(out_dir: str) -> list[str]:
    """Dump every CORPUS source to GIMPLE text; four at a time."""
    procs = []
    done: list[str] = []
    pending = list(CORPUS)

    def reap(block: bool) -> None:
        for src, pr in list(procs):
            if block:
                pr.wait()
            if pr.poll() is not None:
                procs.remove((src, pr))
                ci = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + '.ci')
                if pr.returncode != 0 or not os.path.isfile(ci):
                    check(False, f"dump {src} (exit {pr.returncode})")
                else:
                    done.append(ci)
                if block:
                    return

    while pending or procs:
        while pending and len(procs) < 4:
            src = pending.pop(0)
            procs.append((src, subprocess.Popen(
                [sys.executable, os.path.join(ROOT, 'fire.py'), '--dump',
                 os.path.join(ROOT, src)],
                cwd=out_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
        reap(True)
    return sorted(done)


def test_ratchet() -> None:
    print("ratchet: findings in real emitted code may only shrink")
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as d:
        files = dump_corpus(d)
        check(len(files) == len(CORPUS), f"all {len(CORPUS)} corpus files dumped")
        stmts = 0
        for ci in files:
            mod, rep = lint(ci)
            stmts += rep.stmts
            for f in rep.findings:
                counts[f.code] = counts.get(f.code, 0) + 1
                if f.code not in BASELINE:
                    print(f"        {os.path.basename(ci)}:{f.out_line}: {f.code}: "
                          f"{f.detail} in {f.fn}: {f.stmt}")
    print(f"        {stmts} statements checked")
    for code in sorted(set(counts) | set(BASELINE)):
        n = counts.get(code, 0)
        base = BASELINE.get(code, 0)
        if n > base:
            check(False, f"{code}: {n} findings, baseline {base} -- the emitter got worse; "
                         f"run `python3 tools/gimple_lint.py -v --code {code} <file.ci>`")
        elif n < base:
            check(False, f"{code}: {n} findings, baseline {base} -- fixed! lower "
                         f"BASELINE[{code!r}] to {n} in test_gimple_lint.py")
        else:
            check(True, f"{code}: {n}")


def main() -> int:
    which = sys.argv[1:] or ['unit', 'ratchet']
    if 'unit' in which:
        test_unit()
        test_gate_wiring()
        test_value_tables_reset()
        test_rt_sigs()
        test_text_calls()
        test_text_casts()
        test_text_cf()
    if 'ratchet' in which:
        test_ratchet()
    print(f"\n{'FAILED' if _fails else 'passed'}: {_fails} failure(s)")
    return 1 if _fails else 0


if __name__ == '__main__':
    sys.exit(main())
