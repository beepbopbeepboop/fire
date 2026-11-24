#!/usr/bin/env python3
"""Yield-from walk-memo invalidation: proof that `_cpp_yield_from`'s
in-place `call.func.member` rewrite drops the walk-memo entry for the
ENCLOSING `call` node, at the write site.

Background (the ADRP-from/`self.` walk-memo invalidation bug, fixed on
2026-11-13 by 40985caba):
`_cpp_yield_from` rewrites `call.func.member = _self_method_name` on both
the classname path and the `self.<method>()` path. The site must invalidate
the walk memo for the node it rewrote; the fix was
`_walk_ast_invalidate(call)` at each site. The census in
test_gimple.py::test_every_ast_mutation_site_invalidates_the_walk_memo only
checks that the function calls `_walk_ast_invalidate` somewhere, so it
cannot distinguish this site's argument; this pin does.

The assertion that fails without the branch's change is
`any(n is call for n in recorded)` in `main()`: with the two
`_walk_ast_invalidate(call)` lines removed, the spy records only
`call.func` (the `MemberExpr`), never the enclosing `CallExpr`.

Run:

    python3 tools/memslot.py --gb 8 --label t -- python3 test_codegen_yield_from_walk_ast_memo.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mojo.middle.exprtypes as ET
import mojo.middle.types as gimple_ctypes
import mojo.backend_gimple.cpp_core as cc


class _StubGen:
    """The smallest `gen` the delegation path reads: struct name, the
    generator-method registration tables, and a fresh-name counter.

    `_iter_member_` (the enum Flag.__iter__ alias shape) is the one rewrite
    whose stored value CHANGES (`_iter_member_` -> `_iter_member_by_def_`),
    so the self-method scenario drives a real field rewrite, not a
    same-value store."""

    def __init__(self, api):
        self._cpp_gen_self_struct = 'S'
        self._generator_method_api = api
        self._supported_generator_methods = set(api)
        self._cpp_runtime_gen_resume_used = False
        self._n = 0

    def _cpp_fresh_name(self, prefix):
        self._n += 1
        return "%s_%d" % (prefix, self._n)


def _method_api(base, receiver):
    """A compiled generator METHOD's api entry, in the shape
    `module_gen.gen_module_impl` actually registers: the receiver is the
    callee's LEADING SLOT.

    `_gen_cpp_generator_unit` prepends `('self', '<Struct> *')` (or
    `('cls', 'int64_t')` for a `@classmethod`) to the method's own
    `param_ctypes`, and `_cpp_generator_param_names` starts `param_names`
    with that receiver — its docstring states the rule: "A generator
    method's receiver is its own leading slot ... and is NOT part of
    `fn.params[1:]`". `_cpp_yield_from` fills that slot from
    `api['receiver']` before binding the call's own arguments, so a
    registration that claims a receiver but carries no slot makes EVERY
    `yield from self.<gen>()` an over-arity call:

        `_UnsupportedGeneratorShape: too many arguments (the callee takes 0)`

    That is how this pin went stale in `51934e78b`, which replaced the
    per-site positional arithmetic with the shared
    `_cpp_generator_call_slot_pairs` (the old code appended the receiver
    without an arity check). Both scenarios build their registration here
    so the stub cannot drift from the real shape again."""
    if receiver not in ('self', 'cls'):
        raise ValueError("a method receiver is 'self' or 'cls', not %r"
                         % (receiver,))
    return {'base': base,
            'params': ['int64_t' if receiver == 'cls' else 'S *'],
            'param_names': [receiver],
            'receiver': receiver,
            'value_ctype': 'int64_t'}


def _registration_shape_problems():
    """Cross-check the stub's registration against the shape production
    DERIVES, not against a second hand-written copy of it.

    `_cpp_generator_param_names` is what `module_gen.gen_module_impl` calls
    for every generator method it registers, so comparing with it is what
    catches the regression this pin suffered: a stub that claims a receiver
    (`params`/`param_names` disagreeing, or the receiver absent from the
    leading slot) no longer describes any registration the compiler can
    produce, and `_cpp_yield_from` then refuses the delegation before a
    single assertion here runs."""
    from mojo.backend_gimple import module_gen

    fn = gimple_ctypes.FunctionDef(
        name='_iter_member_by_def_', params=[('self', 'S')],
        return_type=None, body=[])
    want_names = module_gen._cpp_generator_param_names(fn, 'self')
    api = _method_api('_S_iter', 'self')
    problems = []
    if api['param_names'] != want_names:
        problems.append("stub param_names %r != what module_gen derives %r"
                        % (api['param_names'], want_names))
    if len(api['params']) != len(api['param_names']):
        problems.append("stub has %d ctype slot(s) for %d name(s)"
                        % (len(api['params']), len(api['param_names'])))
    if not api['param_names'] or api['param_names'][0] != api['receiver']:
        problems.append("the receiver %r is not the leading name slot"
                        % (api['receiver'],))
    return problems


def _drive(gen, call):
    """Run `_cpp_yield_from` over `yield from <call>`, recording every node
    handed to `_walk_ast_invalidate`."""
    yf = gimple_ctypes.YieldFromExpr(value=call)
    recorded = []
    real = cc._walk_ast_invalidate

    def spy(node):
        recorded.append(node)
        real(node)

    cc._walk_ast_invalidate = spy
    try:
        out = cc._cpp_yield_from(gen, yf, '')
    finally:
        cc._walk_ast_invalidate = real
    return out, recorded


def main():
    fails = []

    # The stub is the harness, not the subject: check it first, because a
    # bad registration makes `_cpp_yield_from` refuse before any of the
    # assertions below are reachable (a version of this pin whose stub
    # claimed `receiver: 'self'` with `params: []` died in the binder, not
    # in one of its own assertions).
    shape = _registration_shape_problems()
    if shape:
        for p in shape:
            print("FAIL  test_codegen_yield_from_walk_ast_memo: " + p)
        sys.exit(1)

    # Scenario 1 — the `self._iter_member_(...)` alias rewrite: the stored
    # member changes value, so a stale memo entry would be a wrong answer.
    call = gimple_ctypes.CallExpr(
        func=gimple_ctypes.MemberExpr(
            obj=gimple_ctypes.IdentExpr('self'), member='_iter_member_'))
    ET._walk_ast_reset()
    ET._walk_ast(call)          # prime the memo for call AND call.func
    ET._walk_ast(call.func)
    gen = _StubGen({('S', '_iter_member_by_def_'):
                    _method_api('_S_iter', 'self')})
    out, recorded = _drive(gen, call)
    if call.func.member != '_iter_member_by_def_':
        fails.append("self._iter_member_ alias rewrite did not fire "
                     "(member=%r)" % call.func.member)
    if not any(n is call for n in recorded):
        fails.append("enclosing CallExpr was never invalidated at the "
                     "rewrite site (recorded only %s)"
                     % ([type(n).__name__ for n in recorded],))
    if not any(n is call.func for n in recorded):
        fails.append("rewritten MemberExpr was never invalidated")
    for node in (call, call.func):
        if id(node) in ET._WALK_AST_MEMO:
            fails.append("walk memo still holds an entry for %s after the "
                         "rewrite site invalidated it" % type(node).__name__)
    out_text = cc._cpp_render_lines(out)
    if not (isinstance(out_text, list) and out_text
            and all(isinstance(s, str) for s in out_text)):
        fails.append("_cpp_yield_from did not return emitted C++ lines")

    # Scenario 2 — the classname path (`yield from S.plan(...)`): same write
    # shape, second site the fix names.
    call2 = gimple_ctypes.CallExpr(
        func=gimple_ctypes.MemberExpr(
            obj=gimple_ctypes.IdentExpr('S'), member='plan'))
    ET._walk_ast_reset()
    ET._walk_ast(call2)
    gen2 = _StubGen({('S', 'plan'):
                     _method_api('_S_plan', 'self')})
    out2, recorded2 = _drive(gen2, call2)
    if not any(n is call2 for n in recorded2):
        fails.append("classname path: enclosing CallExpr was never "
                     "invalidated at the rewrite site")
    out2_text = cc._cpp_render_lines(out2)
    if not (isinstance(out2_text, list) and out2_text
            and all(isinstance(s, str) for s in out2_text)):
        fails.append("classname path: _cpp_yield_from did not return "
                     "emitted C++ lines")

    ET._walk_ast_reset()
    if fails:
        for f in fails:
            print("FAIL  test_codegen_yield_from_walk_ast_memo: " + f)
        sys.exit(1)
    print("PASS  test_codegen_yield_from_walk_ast_memo "
          "(both rewrite sites invalidate the enclosing call)")


if __name__ == '__main__':
    main()
