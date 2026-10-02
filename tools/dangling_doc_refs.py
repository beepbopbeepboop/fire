#!/usr/bin/env python3
"""dangling_doc_refs.py -- every `bugs/<name>.md` this tree cites that is not
in `bugs/`.

CLAUDE.md deletes a bug doc when the bug is fixed, rather than leaving it
behind with a Status history: a fixed bug still listed is indistinguishable
from an open one to whoever reads the queue next. That is the right rule and
it has a cost this tool exists to measure — every citation of a deleted doc
becomes a reference to nothing, in a file that exists to be believed. The
first instance found (`bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md`)
was a test file's module docstring, which is documentation a reader trusts
sending them to a file that is not there.

The walk is over `.md` and `.py`, and it reuses `checked_run.is_derived_dir`
rather than keeping a second list of "not part of the repo", for the reason
that function's docstring gives: two lists are two answers to "what is a file
in this repo", and they eventually disagree.

    python3 tools/dangling_doc_refs.py            # the census, by doc name
    python3 tools/dangling_doc_refs.py --by-file  # by citing file
    python3 tools/dangling_doc_refs.py --json     # machine-readable

Exit code is 1 when anything dangles, 0 when nothing does, so this can become
a hook without being edited first. It is NOT wired into any bucket, and the
reason is the measurement rather than taste: on 2026-10-01 it found 335
citations across 126 deleted names, and two thirds of them are inside
`fire_compiler.py`, `gimple_codegen.py`, `formal/` and `mojo/` — files that
belong to whichever worker owns that area, not to whoever fixes the prose. A
`check()` over the whole corpus would go red on every one of those branches for
something it did not do, and a red check is indistinguishable from a real
regression. The census is a CAMPAIGN, so it is reported as one.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import checked_run  # noqa: E402  — after the sys.path line that finds it

# A `bugs/` path, with the optional subdirectory the tree uses (`hard/`, and
# one `consolidated/`). The character class is deliberately narrow — no spaces,
# no shell metacharacters — because a wider one starts matching prose that
# merely mentions the directory.
REF = re.compile(r'bugs/((?:hard/|consolidated/)?[A-Za-z0-9_][A-Za-z0-9_./+-]*'
                 r'\.md)')
SUFFIXES = ('.md', '.py')


def existing_docs():
    """Every `bugs/**.md` path, relative to the repo root."""
    out = set()
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, 'bugs')):
        dirnames[:] = sorted(d for d in dirnames
                             if not checked_run.is_derived_dir(d))
        for name in sorted(filenames):
            if name.endswith('.md'):
                rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
                out.add(rel.replace(os.sep, '/'))
    return out


def candidates():
    """Every `.md`/`.py` in the repo that could cite a doc, as root-relative
    paths, with the derived directories dropped."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames
                             if not checked_run.is_derived_dir(d))
        for name in sorted(filenames):
            if name.endswith(SUFFIXES):
                rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
                yield rel.replace(os.sep, '/')


def find(skip=()):
    """(cited, by_doc, by_file) for every reference to a doc that is gone.

    `skip` is a set of repo-relative paths to leave out — used by
    test_suite.py to exclude its own synthetic fixture names, which are
    deliberately non-existent and are what proves the walk works.
    """
    have = existing_docs()
    by_doc, by_file = {}, {}
    for rel in candidates():
        if rel in skip:
            continue
        try:
            text = open(os.path.join(ROOT, rel), encoding='utf-8',
                        errors='replace').read()
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name in REF.findall(line):
                if f'bugs/{name}' in have:
                    continue
                by_doc.setdefault(name, []).append((rel, lineno))
                by_file.setdefault(rel, []).append((name, lineno))
    return have, by_doc, by_file


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--by-file', action='store_true',
                    help='group the census by citing file instead of by '
                         'deleted doc name (this is the landing order: it is '
                         'sorted by count)')
    ap.add_argument('--json', action='store_true', help='machine-readable')
    args = ap.parse_args()

    _have, by_doc, by_file = find()
    n_cites = sum(len(v) for v in by_doc.values())

    if args.json:
        print(json.dumps({
            'deleted_names': len(by_doc),
            'citations': n_cites,
            'by_doc': {k: [f'{f}:{n}' for f, n in v]
                       for k, v in sorted(by_doc.items())},
            'by_file': {k: [f'{d}@{n}' for d, n in v]
                        for k, v in sorted(by_file.items())},
        }, indent=2, sort_keys=True))
        return 1 if by_doc else 0

    print(f'{n_cites} citations of {len(by_doc)} bugs/ docs that are not there, '
          f'across {len(by_file)} files')
    if args.by_file:
        for rel, cites in sorted(by_file.items(), key=lambda kv: -len(kv[1])):
            names = sorted({d for d, _n in cites})
            shown = ', '.join(names[:3]) + (' …' if len(names) > 3 else '')
            print(f'  {len(cites):4}  {rel}\n         {shown}')
    else:
        for name, cites in sorted(by_doc.items(), key=lambda kv: -len(kv[1])):
            print(f'  {len(cites):4}  bugs/{name}')
            for rel, lineno in cites[:3]:
                print(f'         {rel}:{lineno}')
            if len(cites) > 3:
                print(f'         … and {len(cites) - 3} more')
    print('\nThe fix for one of these is to name the BUG rather than the doc — '
          'the\nsymptom, or the commit that fixed it — which is what '
          'test_arm64_encoders.py\nsays at its shift sweep. See '
          'bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md.')
    return 1 if by_doc else 0


if __name__ == '__main__':
    sys.exit(main())
