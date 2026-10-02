#!/usr/bin/env python3
"""Every module global whose binding carries values of MORE THAN ONE C type.

The census behind `bugs/CODEGEN_multi_kind_global_read_before_the_
reassignment_reads_the_placeholder.md` and the safety argument for the
`global`-reassignment join in `mojo/backend_gimple/module_gen.py`'s
`_phase17_scan_global_reassignments`: that join changes a global's declared
type, so the question "which code does it change?" needs an answer that is a
MEASUREMENT rather than an assurance.

It is one `parse_module()` + `rewrite()` + `_quick_type` per file — no codegen,
no gcc, no link — which is what makes it cheap enough to re-run after every
change to the pass. Two roots:

    python3 tools/scan_globals.py                 # the Mojo stdlib
    python3 tools/scan_globals.py --selfhost      # this compiler's own .py

`--selfhost` is the one that bounds the bootstrap: those 262 files are what
`fire.py --dump-full fire.py` compiles, and a global whose C type changes in
there is a change to the self-hosted build's own output.

The scan deliberately re-implements the pass's traversal rather than importing
it: the pass is a closure inside `gen_module_impl`, and importing the backend
to call one nested helper would make this script slower and more fragile than
the thing it measures. The rule to keep them in agreement is the node classes
each one tests, which are spelled out below.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fire_compiler as FC          # noqa: E402
import ast_rewriter                 # noqa: E402
import gimple_codegen               # noqa: E402
import module_loader                # noqa: E402


def _collect(body, seq):
    """Pre-order every statement of `body`, descending into control flow AND
    into a nested `FunctionDef` — a `global N` inside a nested `def` still
    names the module binding, which is the one thing `_each_binding`
    (infra_infer) deliberately does NOT do, and the reason this walker
    exists rather than a reuse of it."""
    for s in (body or []):
        seq.append(s)
        if isinstance(s, FC.FunctionDef):
            _collect(s.body, seq)
        elif isinstance(s, FC.IfStmt):
            _collect(s.then_body, seq)
            _collect(getattr(s, 'else_body', None), seq)
            for _c, eb in (getattr(s, 'elifs', None) or []):
                _collect(eb, seq)
        elif isinstance(s, (FC.WhileStmt, FC.ForStmt)):
            _collect(getattr(s, 'body', None), seq)
            _collect(getattr(s, 'else_body', None), seq)
        elif isinstance(s, FC.WithStmt):
            _collect(s.body, seq)
        elif isinstance(s, FC.TryStmt):
            _collect(s.body, seq)
            for h in (getattr(s, 'handlers', None) or []):
                _collect(getattr(h, 'body', None), seq)
            _collect(getattr(s, 'else_body', None), seq)
            _collect(getattr(s, 'finally_body', None), seq)


def _kinds_in(path, gen):
    """`[(global name, sorted kinds)]` for one file's multi-kind globals."""
    try:
        src = open(path, encoding='utf-8', errors='replace').read()
        stmts = FC.Parser(FC.py_tokenize(src)).with_filename(path).parse_module()
        stmts = ast_rewriter.rewrite(stmts)
    except Exception:
        return None
    kinds: dict = {}

    def note(name, value):
        qt = gen._quick_type(value)
        if qt and qt.endswith('*'):
            kinds.setdefault(name, set()).add(qt)

    for s in stmts:
        if isinstance(s, FC.AssignStmt) and isinstance(s.target, FC.IdentExpr):
            note(str(s.target.name), s.value)
        elif isinstance(s, FC.MultiAssignStmt):
            for t in (s.targets or []):
                if isinstance(t, FC.IdentExpr):
                    note(str(t.name), s.value)
    for s in stmts:
        if not isinstance(s, FC.FunctionDef):
            continue
        seq: list = []
        _collect(s.body, seq)
        declared = set()
        for x in seq:
            if isinstance(x, FC.GlobalStmt):
                for nm in (x.names or []):
                    declared.add(str(nm))
        if not declared:
            continue
        for x in seq:
            if isinstance(x, FC.AssignStmt):
                targets = [x.target]
            elif isinstance(x, FC.MultiAssignStmt):
                targets = list(x.targets or [])
            else:
                continue
            for t in targets:
                if isinstance(t, FC.IdentExpr) and str(t.name) in declared:
                    note(str(t.name), x.value)
    return sorted((n, sorted(k)) for n, k in kinds.items() if len(k) > 1)


def _files(root, exts):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ('.git', 'build', '.tmp', 'node_modules')]
        for fn in sorted(filenames):
            if fn.endswith(exts):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def main(argv):
    selfhost = '--selfhost' in argv
    if selfhost:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        files = _files(root, ('.py',))
    else:
        root = module_loader.STDLIB_PATH
        files = _files(root, ('.mojo',))
    gen = gimple_codegen.GimpleGen()
    gen.module_name = ''
    total = 0
    for path in files:
        got = _kinds_in(path, gen)
        if not got:
            continue
        for name, k in got:
            total += 1
            print('  %s  %s  %s' % (os.path.relpath(path, root), name, k))
    print('%s: %d files scanned, %d multi-kind global(s)'
          % ('selfhost' if selfhost else 'stdlib', len(files), total))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
