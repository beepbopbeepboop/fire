#!/usr/bin/env python3
"""Read the type solver's ledger (FIRE_TSOLVE_LEDGER) and summarize it.

    python3 tools/tsolve_why.py --classify LEDGER   # one row per decided name, by kind
    python3 tools/tsolve_why.py --shadow LEDGER     # the solver/backend disagreements (S2)
    python3 tools/tsolve_why.py --undecided LEDGER  # undecided names, by reason
    python3 tools/tsolve_why.py --fn NAME ROOT.py [--path PART]
                                                    # the flows into NAME's return, solved
    python3 tools/tsolve_why.py --undecidable ROOT.py
                                                    # undecidable functions, by summarizer site

The last two build the solved program of ROOT.py the way the compile does (the same
ClosureLoader), so they take about a minute on the closure. They read the summarizer through
its public entry points only; nothing in the closure is changed for them.

The ledger is written by the compile (bugs/GIR_type_solver_precision.md, 4.5): one
`early`, `conflict`, `undecided reason=...` or `shadow solver=... measured=...` line per
name, then a `summary` line. This tool is not in the closure and may use any library.
"""
import collections
import sys


def read_lines(path: str) -> list:
    with open(path) as f:
        return [ln.rstrip('\n') for ln in f if ln.strip()]


def classify(lines: list) -> None:
    kinds = collections.OrderedDict()
    for ln in lines:
        if ln.startswith('summary'):
            print(ln)
            continue
        parts = ln.split(' ')
        kind = parts[0]
        name = parts[1] if len(parts) > 1 else ''
        kinds.setdefault(kind, []).append(name)
    for kind in kinds:
        names = sorted(set(kinds[kind]))
        print('%-10s %4d lines, %4d names' % (kind, len(kinds[kind]), len(names)))


def shadow(lines: list) -> None:
    rows = [ln for ln in lines if ln.startswith('shadow ')]
    print('shadow: %d names disagree' % len(rows))
    for ln in sorted(rows):
        print(' ', ln[len('shadow '):])


def undecided(lines: list) -> None:
    counts = collections.Counter()
    for ln in lines:
        if ln.startswith('undecided '):
            reason = ln.rsplit('reason=', 1)[-1] if 'reason=' in ln else '?'
            counts[reason] += 1
    for reason, n in counts.most_common():
        print('%-14s %d names' % (reason, n))


def build_program(root: str):
    """The solved program of `root`, built the way `_solve_import_closure` builds it."""
    import os
    import sys
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo)
    import fire_compiler as N
    import ast_rewriter
    import gimple_codegen
    from mojo.middle.funcs_shared import ClosureLoader
    from mojo.tsolve import summarize, solve
    root = os.path.abspath(root)
    with open(root) as f:
        stmts = ast_rewriter.rewrite(N.Parser(N.py_tokenize(f.read())).parse_module())
    gen = gimple_codegen.GimpleGen()
    gen._current_filename = root
    prog = summarize.summarize_closure(root, stmts, ClosureLoader(gen))
    solve.solve(prog)
    return prog


def fn_provenance(prog, name: str, path_part: str) -> None:
    """Every flow into the return of the function `name` (optionally in a path containing
    `path_part`): its origin and what its source evaluates to in the solved program."""
    from mojo.tsolve import solve as S
    matches = []
    for key in prog.fns:
        fs = prog.fns[key]
        if fs.name == name and (path_part == '' or path_part in fs.path):
            matches.append(fs)
    if not matches:
        print('no function named %r' % name)
        return
    for fs in matches:
        print('%s (decidable=%s, annotated=%s) ret = %s' % (fs.path + '.' + name, fs.decidable,
                                                         fs.annotated_ret, prog.vars[fs.ret].key))
        for fl in prog.flows:
            if fl.dst == fs.ret:
                val = S.eval_term(prog, fl.src)
                print('  %-50s src %-8s = %s' % (fl.origin or '(no origin)', fl.src.op, val.key))


def undecidable_by_site(root: str) -> None:
    """Undecidable functions of ROOT's closure, grouped by the summarizer line that made each one
    undecidable. The hook is installed BEFORE the program is built, so it sees every call."""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from mojo.tsolve import summarize
    first_site = {}
    original = summarize._Summarizer._undecidable

    def record(self, scope):
        fn = getattr(scope, 'fn', None)
        if fn is not None and fn.name + '@' + fn.path not in first_site:
            frame = sys._getframe(1)
            first_site[fn.name + '@' + fn.path] = '%s:%d' % (frame.f_code.co_name, frame.f_lineno)
        original(self, scope)

    summarize._Summarizer._undecidable = record
    try:
        prog = build_program(root)
    finally:
        summarize._Summarizer._undecidable = original
    counts = collections.Counter()
    for key in prog.fns:
        fs = prog.fns[key]
        if fs.decidable:
            continue
        site = first_site.get(fs.name + '@' + fs.path, 'declared (decorator, generator, async, overload)')
        counts[site] += 1
    for site, n in counts.most_common():
        print('%5d  %s' % (n, site))
    print('total undecidable: %d of %d functions' % (sum(counts.values()), len(prog.fns)))


def main(argv: list) -> int:
    if len(argv) >= 1 and argv[0] in ('--fn', '--undecidable'):
        if argv[0] == '--undecidable':
            if len(argv) != 2:
                print(__doc__)
                return 2
            undecidable_by_site(argv[1])
            return 0
        path_part = ''
        args = argv[1:]
        if '--path' in args:
            i = args.index('--path')
            path_part = args[i + 1]
            args = args[:i] + args[i + 2:]
        if len(args) != 2:
            print(__doc__)
            return 2
        fn_provenance(build_program(args[1]), args[0], path_part)
        return 0
    if len(argv) != 2 or argv[0] not in ('--classify', '--shadow', '--undecided'):
        print(__doc__)
        return 2
    lines = read_lines(argv[1])
    {'--classify': classify, '--shadow': shadow, '--undecided': undecided}[argv[0]](lines)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
