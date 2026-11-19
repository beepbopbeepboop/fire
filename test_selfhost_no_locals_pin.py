#!/usr/bin/env python3
"""Pin: no module in `fire.py`'s self-host closure may call the builtin
`locals()`.

Why this is a pin and not a style rule. `bootstrap-stage1-transitive` compiles
`fire.py`'s whole closure with the Python reference and rejects the dump if it
carries an `unavailable in compiled mode` weak stub. A bare `locals()` call is
one of the builtins that path cannot lower — it emits exactly that stub, which
returns 0 — so every `locals()` call in the closure is a stub the job counts,
and every *read* of it in the compiled compiler was silently answered with
`0`/absent instead of with the real local namespace.

The shape that hid this: a `'<name>' in locals()` guard whose name is bound
unconditionally on every path, or a `locals().get(...)` for a name that is not
a parameter at all. The guard is dead on the reference path, so CPython agrees
with the constant answer and nothing goes red there — but the compiled binary
read the stub's `0` and took the other branch. The sites this test covers were
removed on 2026-11-18 (emit_stmts.py's struct-subscript `__setitem__`
fallback, formal/build.py's `structs_by_name` probe, formal/arm64_proof_gen.py's
`_cf2_text` probe); the closure is not otherwise allowed to gain one back.

Scope: the syntactic import closure of `fire.py` (the set
`bootstrap-stage1-transitive` compiles). `cas.selfhost_closure_is_complete`
walks imports inside function/`try` bodies too, which the codegen's own import
collection also does — that is how `formal/build.py` reaches the dump through
`build_stdlib_dylib.py`'s function-local `import formal.build`.

A function that binds the name `locals` itself is exempt: a call there is a
call to that binding, not to the builtin.

Run: python3 test_selfhost_no_locals_pin.py
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cas  # noqa: E402

# The three files whose `locals()` sites were removed for this pin. Asserting
# they are IN the walk keeps the test honest if the closure walk changes: a
# walk that stopped descending into function bodies would otherwise make this
# test pass by looking at fewer files.
WATCHED = (
    'mojo/backend_gimple/emit_stmts.py',
    'formal/build.py',
    'formal/arm64_proof_gen.py',
)


def _binds_locals(scope) -> bool:
    """True when `scope` binds the name `locals` anywhere inside it.

    Deliberately conservative (it also sees nested scopes), so a genuine
    builtin call is never reported for a scope that may shadow it.
    """
    for n in ast.walk(scope):
        if isinstance(n, ast.arg) and n.arg == 'locals':
            return True
        if isinstance(n, ast.Name) and n.id == 'locals' \
                and isinstance(n.ctx, (ast.Store, ast.Del)):
            return True
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and n.name == 'locals':
            return True
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if (a.asname or a.name.split('.')[0]) == 'locals':
                    return True
        if isinstance(n, ast.ExceptHandler) and n.name == 'locals':
            return True
        if isinstance(n, (ast.Global, ast.Nonlocal)) and 'locals' in n.names:
            return True
    return False


class _LocalsCalls(ast.NodeVisitor):
    """Collect `locals(...)` calls whose name resolves to the builtin."""

    def __init__(self):
        self.scopes = []
        self.hits = []

    def _enter(self, node):
        self.scopes.append(node)
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Module(self, node):
        self._enter(node)

    def visit_FunctionDef(self, node):
        self._enter(node)

    def visit_AsyncFunctionDef(self, node):
        self._enter(node)

    def visit_ClassDef(self, node):
        self._enter(node)

    def visit_Lambda(self, node):
        self._enter(node)

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Name) and f.id == 'locals' \
                and not any(_binds_locals(s) for s in self.scopes):
            self.hits.append((getattr(node, 'lineno', 0), 'locals(...)'))
        self.generic_visit(node)


def locals_calls_in(src: str, filename: str = '<input>') -> list:
    """`[(lineno, which)]` for every builtin `locals()` call in `src`."""
    walker = _LocalsCalls()
    walker.visit(ast.parse(src, filename))
    return walker.hits


def selfhost_closure() -> list:
    """The `.py` files `bootstrap-stage1-transitive` compiles, sorted.

    Raises if the closure walk reaches a file the self-host key does not
    hash — the same invariant the key's own completeness check enforces — so
    this test never scans a set narrower than the dump.
    """
    missing, seen = cas.selfhost_closure_is_complete('fire.py')
    assert not missing, (
        'the fire.py closure reaches files the self-host key does not hash: '
        f'{sorted(missing)}')
    for name in WATCHED:
        assert name in seen, (
            f'{name} is not in the fire.py closure this test scans — the walk '
            'no longer descends where the dump does')
    return sorted(n for n in seen if n.endswith('.py'))


def test_no_locals_in_selfhost_closure():
    failures = []
    scanned = 0
    for name in selfhost_closure():
        path = os.path.join(HERE, name)
        if not os.path.isfile(path):
            continue
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            src = f.read()
        scanned += 1
        for lineno, which in locals_calls_in(src, name):
            failures.append(f'{name}:{lineno}: {which}')
    assert scanned > 50, f'only {scanned} modules scanned; the walk is broken'
    assert not failures, (
        'the self-host closure calls the builtin `locals()`, which the '
        'compiled path can only stub to 0 (each call is an '
        '"unavailable in compiled mode" weak stub in the --dump-full dump). '
        'Remove the probe or read the specific name/namespace it needs:\n  '
        + '\n  '.join(failures))


if __name__ == '__main__':
    test_no_locals_in_selfhost_closure()
    print('PASS')
