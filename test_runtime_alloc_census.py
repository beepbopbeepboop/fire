#!/usr/bin/env python3
"""Regression test for the opt-in allocation census in runtime/fire_alloc_census.h.

The census (built with -DMOJO_ALLOC_CENSUS) attributes every malloc/calloc/
realloc/free made by fire_runtime.c to its call site and reports, at exit,
how many objects and bytes each site still holds live. It is the measurement
bugs/mid/CODEGEN_bootstrap_resource_blowup.md needs before choosing an AST-
lifetime fix over a temporaries fix.

The harness below includes fire_runtime.c itself (so the redirects apply to
the harness's own calls too) and makes allocations whose live counts are known
by construction:

  * one malloc that is never freed            -> live 1, bytes 100
  * one calloc that is freed                  -> live 0, total 1
  * one malloc that is realloc'd              -> old site live 0, new site
                                                 live 1, bytes 500
  * 40000 malloc blocks at one site (enough to pass the side table's first
    growth step), every odd one freed -> 20000 live, and the survivors must
    still be found after the growth rehash and the backward-shift deletions
    (a broken probe chain would under-count or drop them).

It runs with the census flag on and checks the rows the atexit report prints.
Without the census, the report does not exist and the test fails.

Usage: python3 test_runtime_alloc_census.py
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')

HARNESS_LINES = [
    '#include "fire_runtime.c"',
    'int main(void) {',
    '    void *never = malloc(100);            /*@A*/',
    '    void *freed = calloc(4, 10);          /*@B*/',
    '    free(freed);                          /*@FREE_B*/',
    '    void *grown = malloc(7);              /*@C*/',
    '    grown = realloc(grown, 500);          /*@D*/',
    '    static void *blk[40000];',
    '    for (int i = 0; i < 40000; i++)',
    '        blk[i] = malloc(i + 1);           /*@E*/',
    '    for (int i = 1; i < 40000; i += 2)',
    '        free(blk[i]);',
    '    (void)never; (void)grown;',
    '    return 0;',
    '}',
]

ROW = re.compile(
    r'^alloc-census live_objs=(\d+) live_bytes=(\d+) total=(\d+) (\S+):(\d+)$')


def _marker_line(lines, tag):
    hits = [i + 1 for i, text in enumerate(lines) if f'/*@{tag}*/' in text]
    assert len(hits) == 1, (tag, hits)
    return hits[0]


def _rows(stderr):
    """Map (basename, line) -> (live_objs, live_bytes, total) from the report."""
    out = {}
    for text in stderr.splitlines():
        m = ROW.match(text)
        if m:
            objs, nbytes, total, path, line = m.groups()
            out[(os.path.basename(path), int(line))] = (
                int(objs), int(nbytes), int(total))
    return out


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td:
        harness_c = os.path.join(td, 'harness.c')
        exe = os.path.join(td, 'harness')
        with open(harness_c, 'w') as f:
            f.write('\n'.join(HARNESS_LINES) + '\n')
        build = subprocess.run(
            ['cc', '-O0', '-DMOJO_ALLOC_CENSUS', '-I', RUNTIME_DIR,
             harness_c, '-o', exe, '-lm'],
            capture_output=True, text=True)
        if build.returncode != 0:
            print('FAIL: harness did not build with -DMOJO_ALLOC_CENSUS:')
            print(build.stderr)
            return 1
        run = subprocess.run([exe], capture_output=True, text=True)
        if run.returncode != 0:
            print(f'FAIL: harness exited {run.returncode}: {run.stderr}')
            return 1

    rows = _rows(run.stderr)
    if not any(line.startswith('alloc-census sites=') for line in run.stderr.splitlines()):
        failures.append('no summary line in the census report')

    def expect(tag, want, note):
        line = _marker_line(HARNESS_LINES, tag)
        got = rows.get(('harness.c', line))
        if got != want:
            failures.append(f'{note} (harness.c:{line}): got {got}, want {want}')

    expect('A', (1, 100, 1), 'malloc never freed')
    expect('B', (0, 0, 1), 'calloc freed')
    expect('C', (0, 0, 1), 'malloc that was realloc\'d away')
    expect('D', (1, 500, 1), 'realloc result still live')
    # Odd blocks i (size i+1) were freed; even blocks survive.
    survivors = [i for i in range(40000) if i % 2 == 0]
    expect('E', (len(survivors), sum(i + 1 for i in survivors), 40000),
           'loop of 40000 with every odd block freed')

    if failures:
        for f in failures:
            print('FAIL:', f)
        print('--- report ---')
        print(run.stderr[:2000])
        return 1
    print(f'ok: census rows for {len(rows)} sites match the known live counts')
    return 0


if __name__ == '__main__':
    sys.exit(main())
