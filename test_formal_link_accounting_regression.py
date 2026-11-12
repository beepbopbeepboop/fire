#!/usr/bin/env python3
"""Regression for bug:SUITE_formal_link_accounting.

Pins the root causes that broke `test_formal_link_accounting.py`:
- hostmods docstrings must not cite deleted bug docs (cross-refs resolve),
- modules with formal/hostmods source must not remain in claim tiers, and
- written hostmods modules must be accounted for by the link ledger.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import formal.imports as I

_CROSS_REF_RE = re.compile(
    r'(?<![\w/.-])((?:bugs/[\w./-]+\.md)|(?:test_[\w]+\.py)'
    r'|(?:formal/[\w./-]+\.(?:mojo|py))|(?:tools/[\w./-]+\.py)'
    r'|(?:doc/[\w./-]+\.(?:md|html))|(?:[\w-]+\.md))(?![\w])')

RESULTS = []


def check(ok, what, detail=''):
    RESULTS.append(bool(ok))
    if not ok:
        print(f'FAIL  {what}' + (f': {detail}' if detail else ''), flush=True)


def test_hostmod_cross_refs_resolve():
    hostmods = os.path.join(HERE, 'formal', 'hostmods')
    dangling = []
    for dirpath, dirnames, filenames in os.walk(hostmods):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fn in sorted(filenames):
            if not fn.endswith('.mojo'):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, HERE)
            with open(path, errors='replace') as fh:
                for lineno, line in enumerate(fh, 1):
                    for ref in _CROSS_REF_RE.findall(line):
                        if not (os.path.exists(os.path.join(HERE, ref))
                                or os.path.exists(os.path.join(
                                    os.path.dirname(path), ref))):
                            dangling.append(f'{rel}:{lineno} -> {ref}')
    check(not dangling, 'hostmod cross-references resolve',
          '; '.join(dangling[:8]))


def test_source_modules_left_claim_tiers():
    claim_with_source = sorted(
        (set(I.HOST_UNREACHABLE) | set(I.HOST_MODELLED))
        & I.hostmod_source_modules())
    check(not claim_with_source,
          'modules with hostmods source are not in claim tiers',
          f'claims with real source behind them {claim_with_source}')


def test_written_modules_accounted_for():
    # These modules have hostmods source and must not be unaccounted.
    for name in ('contextvars', 'hoststatus', 'keyword', 'multiprocessing',
                 'builtins', 'collections', 'copy', 'functools', 'importlib'):
        path = I.resolve_module_path(name, project_root=HERE)
        check(path is not None and os.path.isfile(path),
              f'{name} has resolvable hostmods source', str(path))
        check(I.host_module_tier(name) not in ('unreachable', 'modelled'),
              f'{name} is not classified as an unmet claim tier',
              I.host_module_tier(name))


def main():
    test_hostmod_cross_refs_resolve()
    test_source_modules_left_claim_tiers()
    test_written_modules_accounted_for()
    npass = sum(RESULTS)
    nfail = len(RESULTS) - npass
    print(f'\n{npass} passed, {nfail} failed, {len(RESULTS)} checks')
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
