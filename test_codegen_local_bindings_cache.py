#!/usr/bin/env python3
"""Regression test for _local_bindings memoization (bug:CODEGEN_do_imports_large_closure_residual_hotspots).

Before the fix, _local_bindings recomputed the binding walk on every call,
returning a new list each time. After the fix, it caches the result per
function body + name, returning the same list object on repeated calls.
This test verifies the cache identity (same object) and correctness.
"""

import sys
sys.path.insert(0, '.')

from fire_compiler import (
    IdentExpr, AssignStmt, AugAssignStmt, IntLiteral, FunctionDef, VarDecl
)
import mojo.middle.types as gimple_ctypes
import mojo.backend_gimple.emit_infra as emit_infra


def make_mock_gen(body):
    """Create a minimal mock gen with _cur_func_body set and cache initialized."""
    class MockGen:
        def __init__(self, body):
            self._cur_func_body = body
            self._local_bindings_cache = {}
    return MockGen(body)


def test_local_bindings_cache_identity():
    """Repeated calls for the same name return the same list object."""
    # Build a small function body: x = 1; y = 2; x = 3
    body = [
        AssignStmt(target=IdentExpr(name='x'), value=IntLiteral(value=1)),
        AssignStmt(target=IdentExpr(name='y'), value=IntLiteral(value=2)),
        AssignStmt(target=IdentExpr(name='x'), value=IntLiteral(value=3)),
    ]
    gen = make_mock_gen(body)

    # First call
    bindings1 = emit_infra._local_bindings(gen, 'x')
    # Second call
    bindings2 = emit_infra._local_bindings(gen, 'x')

    # After fix: same cached object returned
    assert bindings1 is bindings2, f"Cache miss: {id(bindings1)} != {id(bindings2)}"

    # Verify correctness: two bindings, values 1 and 3
    assert len(bindings1) == 2
    assert isinstance(bindings1[0], IntLiteral) and bindings1[0].value == 1
    assert isinstance(bindings1[1], IntLiteral) and bindings1[1].value == 3


def test_local_bindings_different_names_different_caches():
    """Different names get separate cache entries."""
    body = [
        AssignStmt(target=IdentExpr(name='a'), value=IntLiteral(value=1)),
        AssignStmt(target=IdentExpr(name='b'), value=IntLiteral(value=2)),
    ]
    gen = make_mock_gen(body)

    a1 = emit_infra._local_bindings(gen, 'a')
    a2 = emit_infra._local_bindings(gen, 'a')
    b1 = emit_infra._local_bindings(gen, 'b')
    b2 = emit_infra._local_bindings(gen, 'b')

    assert a1 is a2
    assert b1 is b2
    assert a1 is not b1  # different names, different lists
    assert len(a1) == 1
    assert len(b1) == 1


def test_local_bindings_augassign():
    """AugAssign counts as a binder (None added)."""
    body = [
        AssignStmt(target=IdentExpr(name='x'), value=IntLiteral(value=1)),
        AugAssignStmt(target=IdentExpr(name='x'), op='+', value=IntLiteral(value=2)),
    ]
    gen = make_mock_gen(body)

    bindings = emit_infra._local_bindings(gen, 'x')
    assert len(bindings) == 2
    assert bindings[0].value == 1
    assert bindings[1] is None  # AugAssign binder


def test_local_bindings_cache_cleared_per_function():
    """Cache is per-function-body; different body yields fresh cache."""
    body1 = [AssignStmt(target=IdentExpr(name='x'), value=IntLiteral(value=1))]
    body2 = [AssignStmt(target=IdentExpr(name='x'), value=IntLiteral(value=2))]
    gen = make_mock_gen(body1)

    # First function body
    b1 = emit_infra._local_bindings(gen, 'x')
    assert len(b1) == 1 and b1[0].value == 1

    # Switch to second body (simulating _reset_func clearing cache)
    gen._cur_func_body = body2
    gen._local_bindings_cache = {}  # _reset_func does this

    b2 = emit_infra._local_bindings(gen, 'x')
    assert b1 is not b2
    assert len(b2) == 1 and b2[0].value == 2


def test_local_bindings_cache_keyed_by_body():
    """Cache key includes body identity: same gen, different bodies, different results.

    Before the fix, both calls for 'x' would return the same cached list because
    the cache was only keyed by name. After the fix, the cache key includes
    id(body), so each function body gets its own cache entry even without
    explicitly resetting the cache.
    """
    body1 = [AssignStmt(target=IdentExpr(name='x'), value=IntLiteral(value=1))]
    body2 = [AssignStmt(target=IdentExpr(name='x'), value=IntLiteral(value=2))]
    gen = make_mock_gen(body1)

    # First call with body1
    b1 = emit_infra._local_bindings(gen, 'x')
    assert len(b1) == 1 and b1[0].value == 1

    # Swap to body2 WITHOUT clearing the cache. Previously this would return
    # the cached result from body1 (BUG). After the fix, it recomputes using
    # the body-identity keyed cache.
    gen._cur_func_body = body2
    b2 = emit_infra._local_bindings(gen, 'x')
    assert b1 is not b2, "Different bodies should return different cached objects"
    assert len(b2) == 1 and b2[0].value == 2, f"Expected value 2, got {[v.value for v in b2]}"


if __name__ == '__main__':
    test_local_bindings_cache_identity()
    test_local_bindings_different_names_different_caches()
    test_local_bindings_augassign()
    test_local_bindings_cache_cleared_per_function()
    test_local_bindings_cache_keyed_by_body()
    print('All tests passed')