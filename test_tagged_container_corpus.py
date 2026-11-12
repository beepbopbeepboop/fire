#!/usr/bin/env python3
"""Corpus census for the mixed-container rebind decision behind
the mixed tagged-generator/container-name case (decided option 2, 2026-11-12 census) and
bugs/hard/CODEGEN_tagged_generator_mixed_type_step4.md.

The question the decision needs answered: does any real .mojo source bind one
name BOTH to a container value (a list/dict/set literal or constructor) AND to
a tagged generator word (`x = next(g)`, or a `for x in <call>(...)` target, in
the same function)? A positive count does not by itself mean the shape is
mixed-kind - the iterable must be a kind-mixed generator, which only the
codegen's mixed_slots analysis knows - so every candidate is printed for
manual review. Zero candidates means the census supports closing the container
case as a named diagnostic instead of a new box kind.

Corpora scanned:
  1. the repository this file lives in (*.mojo, skipping .git/.tmp/build/
     node_modules/claude/__pycache__), and
  2. the stdlib checkout: $MOJO_STDLIB if set, else the same preferred
     location module_loader._find_stdlib_path() uses
     (/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib).
     If no stdlib root is reachable the probe exits 3 rather than report a
     vacuous census.

Exit 0 when the scan completed (candidates, if any, are printed; the DECISION
is recorded in the docs, not here). Exit 3 when the stdlib root is missing.
Parse failures are counted and printed, not fatal: this is a census, and a
file that stopped parsing is data about the corpus, not a verdict on it.
"""
import dataclasses
import os
import sys

sys.setrecursionlimit(20000)
import fire_compiler as N

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_SKIP_DIRS = {'.git', '.tmp', 'build', 'node_modules', 'claude', '__pycache__'}
STDLIB_FALLBACK = '/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib'
CONTAINER_CTORS = {'List', 'Dict', 'Set'}


def _iter_mojo_files(root, skip_dirs):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
        for f in sorted(files):
            if f.endswith('.mojo'):
                yield os.path.join(dirpath, f)


def _stdlib_root():
    env = os.environ.get('MOJO_STDLIB')
    if env and os.path.isdir(env):
        return env
    if os.path.isdir(STDLIB_FALLBACK):
        return STDLIB_FALLBACK
    return None


def _walk(node):
    if node is None or isinstance(node, (str, int, float, bool)):
        return
    if isinstance(node, (list, tuple)):
        for x in node:
            yield from _walk(x)
        return
    if not hasattr(node, '__dataclass_fields__'):
        return
    yield node
    for f in dataclasses.fields(node):
        yield from _walk(getattr(node, f.name))


def _is_container_value(v):
    if isinstance(v, (N.ListExpr, N.DictExpr, N.SetExpr)):
        return True
    if isinstance(v, N.CallExpr):
        func = v.func
        # List(...) / List[Int](...) / Counter[...]  etc.
        while isinstance(func, N.SubscriptExpr):
            func = func.obj
        if isinstance(func, N.IdentExpr) and func.name in CONTAINER_CTORS:
            return True
    return False


def _is_next_call(v):
    return (isinstance(v, N.CallExpr)
            and isinstance(v.func, N.IdentExpr)
            and v.func.name == 'next')


def _scan_file(path, rel):
    with open(path, 'r', errors='replace') as fh:
        src = fh.read()
    if 'yield' not in src:
        return [], None
    try:
        mod = N.Parser(N.py_tokenize(src)).parse_module()
    except Exception as e:  # census data, not a verdict
        return [], f'{rel}: {e}'
    candidates = []
    for fn in _walk(mod):
        if not isinstance(fn, N.FunctionDef):
            continue
        container_names, tagged_names = set(), set()
        for node in _walk(fn):
            if isinstance(node, N.AssignStmt) and isinstance(node.target, N.IdentExpr):
                nm = node.target.name
                if _is_container_value(node.value):
                    container_names.add(nm)
                elif _is_next_call(node.value):
                    tagged_names.add(nm)
            elif isinstance(node, N.VarDecl):
                if node.value is not None and _is_container_value(node.value):
                    container_names.add(node.name)
            elif isinstance(node, N.ForStmt):
                if isinstance(node.target, N.IdentExpr) and isinstance(node.iterable, N.CallExpr):
                    tagged_names.add(node.target.name)
        for nm in sorted(container_names & tagged_names):
            candidates.append(f'{rel}: {fn.name}: {nm}')
    return candidates, None


def main():
    stdlib = _stdlib_root()
    if stdlib is None:
        print('census: no stdlib root reachable (set MOJO_STDLIB); refusing to '
              'report a census that scanned nothing')
        return 3
    all_candidates, parse_failures = [], []
    for label, root, skip in (('stdlib', stdlib, {'.git', '__pycache__', '.tmp'}),
                              ('repo', HERE, REPO_SKIP_DIRS)):
        scanned = 0
        for path in _iter_mojo_files(root, skip):
            scanned += 1
            rel = os.path.relpath(path, HERE if label == 'repo' else stdlib)
            candidates, err = _scan_file(path, rel)
            all_candidates.extend(f'{label}:{c}' for c in candidates)
            if err is not None:
                parse_failures.append(err)
        print(f'census: {label}: {scanned} .mojo files scanned')
    print(f'census: candidates (manually review; a hit only counts when the '
          f'loop/yield kind analysis says the iterable is kind-mixed): {len(all_candidates)}')
    for c in all_candidates:
        print(f'  candidate: {c}')
    print(f'census: parse failures: {len(parse_failures)}')
    for p in parse_failures:
        print(f'  parse failure: {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
