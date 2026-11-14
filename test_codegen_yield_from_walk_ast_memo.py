#!/usr/bin/env python3
"""CODEGEN_walk_ast_memo_cpp_yield_from: proof that `_cpp_yield_from`'s
in-place `call.func.member` rewrite drops the walk-memo entry for the
ENCLOSING `call` node, at the write site.

Background (the deleted doc, bugs/CODEGEN_walk_ast_memo_cpp_yield_from.md):
`_cpp_yield_from` rewrites `call.func.member = _self_method_name` on both
the classname path and the `self.<method>()` path. The site must invalidate
the walk memo for the node it rewrote; the doc's next step was
`_walk_ast_invalidate(call)` at each site, which branch
work/bug-codegen-walk-ast-memo-cpp-yield-from landed. The census in
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

    # Scenario 1 — the `self._iter_member_(...)` alias rewrite: the stored
    # member changes value, so a stale memo entry would be a wrong answer.
    call = gimple_ctypes.CallExpr(
        func=gimple_ctypes.MemberExpr(
            obj=gimple_ctypes.IdentExpr('self'), member='_iter_member_'))
    ET._walk_ast_reset()
    ET._walk_ast(call)          # prime the memo for call AND call.func
    ET._walk_ast(call.func)
    gen = _StubGen({('S', '_iter_member_by_def_'):
                    {'base': '_S_iter', 'params': [], 'receiver': 'self',
                     'value_ctype': 'int64_t'}})
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
    if not (isinstance(out, list) and out and all(isinstance(s, str)
                                                  for s in out)):
        fails.append("_cpp_yield_from did not return emitted C++ lines")

    # Scenario 2 — the classname path (`yield from S.plan(...)`): same write
    # shape, second site the doc's next step names.
    call2 = gimple_ctypes.CallExpr(
        func=gimple_ctypes.MemberExpr(
            obj=gimple_ctypes.IdentExpr('S'), member='plan'))
    ET._walk_ast_reset()
    ET._walk_ast(call2)
    gen2 = _StubGen({('S', 'plan'):
                     {'base': '_S_plan', 'params': [], 'receiver': 'self',
                      'value_ctype': 'int64_t'}})
    out2, recorded2 = _drive(gen2, call2)
    if not any(n is call2 for n in recorded2):
        fails.append("classname path: enclosing CallExpr was never "
                     "invalidated at the rewrite site")
    if not (isinstance(out2, list) and out2
            and all(isinstance(s, str) for s in out2)):
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
